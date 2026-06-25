import os
import feedparser
import requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()  # 加载 .env 里的环境变量（如 DEEPSEEK_API_KEY）

# ========== 配置区（要改口味，只动这里） ==========

# —— 新闻源：加源 / 删源 / 换源只改这个字典，主逻辑不用动 ——
SOURCES = {
    "36氪-科技创投": "https://36kr.com/feed",
    "华尔街见闻-宏观": "https://dedicated.wallstreetcn.com/rss.xml",
    "人民网-时政": "http://www.people.com.cn/rss/politics.xml",
    "人民网-财经": "http://www.people.com.cn/rss/finance.xml",
    "人民网-国际": "http://www.people.com.cn/rss/world.xml",
    "财联社": "http://host.docker.internal:1200/cls/telegraph",
    # —— 待办源（留口，以后专项接入）——
    # 巨潮资讯网：公告/财报，无官方 RSS，需逆向其加密接口
    # 国家统计局：PPI/PMI 等指标，需确认改版后的数据栏目
}

# —— 飞书 Webhook（发送目标，以后换渠道只改这里）——
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/f59e5349-365f-4b19-8f6a-69930b1a2794"

# —— DeepSeek 配置 ——
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
PER_SOURCE_LIMIT = 30   # 每个源各取前 N 条交给 AI（保证各源都被看到，解决覆盖偏差）

# —— AI 筛选规格（要调口味只改这段文字，不动代码）——
FILTER_PROMPT = """你是一名资深财经新闻编辑，服务的用户为了投资决策、把握宏观环境变化、刷新对世界的认知而读新闻。

请从新闻列表中，保留满足以下任一条件的新闻：
1. 普适重要财经新闻（货币政策、利率、重大监管、影响全局的市场或公司大事）
2. 国家宏观大政策（财政、产业、改革方向）
3. 每月重要经济指标（PPI、PMI、CPI、GDP、社融、进出口等）
4. AI 与半导体行业动态，以及反映 AI/半导体行业趋势、AI 冲击就业、头部科技巨头重大动向的新闻

请丢弃：个股短线吹票、营销软文、基金理财广告、八卦娱乐、与全球无关的纯他国政治社会新闻。

取舍原则：拿不准时倾向于保留（宁可多推，不可漏掉重要新闻）。

【排序要求】精选新闻必须按"从宏观到微观"排序：
① 全球市场大势与地缘/能源 → ② 国家宏观政策 → ③ 经济指标 → ④ AI/半导体行业趋势 → ⑤ AI/半导体相关公司与巨头动向

特别注意：
- 确保中美的宏观政策与重要经济新闻不要遗漏。
- 同时保留足够的 AI/半导体技术发展新闻，让宏观类和科技类保持均衡，不要让某一类挤占全部版面。

请按以下格式输出（严格遵守），精选新闻按"从宏观到微观"排序：
【今日市场总结】
（3-5 句话，综合所有保留的新闻，点明今天的宏观主线和值得关注的趋势）

【精选新闻】
1. 新闻标题 | 链接
2. 新闻标题 | 链接
（每条一行）
"""

# —— 网络请求通用设置 ——
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 20


# ========== 功能函数 ==========

def fetch_one_source(name, url):
    """抓取单个源。无论成功失败都返回结果，绝不让异常拖垮整个程序。"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        feed = feedparser.parse(response.content)
        news = [
            {"title": e.get("title", "无标题"),
             "link": e.get("link", ""),
             "source": name}
            for e in feed.entries
        ]
        return {"ok": True, "status": response.status_code,
                "count": len(news), "news": news}
    except Exception as error:
        return {"ok": False, "status": None, "count": 0,
                "news": [], "error": type(error).__name__}


def fetch_all():
    """遍历所有源，汇总能抓到的新闻，并打印每个源的状况（失败可见）。"""
    all_news = []
    print("=" * 50)
    for name, url in SOURCES.items():
        result = fetch_one_source(name, url)
        if result["ok"] and result["count"] > 0:
            print(f"✅ {name}: {result['count']} 条")
            all_news.extend(result["news"])
        elif result["ok"]:
            print(f"⚠️  {name}: 通了但 0 条（HTTP {result['status']}）")
        else:
            print(f"❌ {name}: 失败（{result['error']}）")
    print("=" * 50)
    return all_news


def pick_balanced(news_list, per_source_limit):
    """每个来源各取前 N 条，保证每个源都被 AI 看到（解决覆盖偏差）。"""
    grouped = defaultdict(list)              # 按来源把新闻分组
    for item in news_list:
        grouped[item["source"]].append(item)

    picked = []
    for source, items in grouped.items():
        picked.extend(items[:per_source_limit])   # 每组取前 N 条
    return picked


def ai_filter_and_summarize(news_list):
    """把均衡抽取后的新闻交给 DeepSeek，做筛选 + 写每日总结。失败返回 None。"""
    if not news_list:
        return None

    # 关键改动：每源各取前 N 条，而不是整体前 N 条
    selected = pick_balanced(news_list, PER_SOURCE_LIMIT)
    print(f"📋 均衡抽取后交给 AI 的新闻：{len(selected)} 条")

    news_text = "\n".join(
        f"{i}. [{item['source']}] {item['title']} | {item['link']}"
        for i, item in enumerate(selected, start=1)
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": FILTER_PROMPT},
            {"role": "user", "content": f"以下是今天抓取的新闻：\n{news_text}"}
        ]
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        print("🤖 正在让 AI 筛选并总结...")
        response = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=60)
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"]
        else:
            print(f"⚠️ AI 返回异常：{result}")
            return None
    except Exception as error:
        print(f"❌ AI 调用出错：{type(error).__name__} - {error}")
        return None


def send_to_feishu(text):
    """把一段文本发送到飞书。text 需包含关键词以通过校验。"""
    if not text:
        print("没有内容可发送")
        return
    message = {"msg_type": "text", "content": {"text": text}}
    try:
        response = requests.post(FEISHU_WEBHOOK, json=message, timeout=15)
        result = response.json()
        if result.get("code") == 0:
            print("✅ 已发送到飞书")
        else:
            print(f"❌ 飞书发送失败：{result}")
    except Exception as error:
        print(f"❌ 发送出错：{type(error).__name__} - {error}")


# ========== 主流程 ==========
# ========== 主流程 ==========
if __name__ == "__main__":
    news_list = fetch_all()
    print(f"\n所有源合计抓到 {len(news_list)} 条新闻\n")

    ai_result = ai_filter_and_summarize(news_list)

    if ai_result:
        # 先在控制台打印，方便你核对
        print("=" * 50)
        print(ai_result)
        print("=" * 50)
        # 再发送到飞书（开头补一个带关键词的标题，确保通过飞书关键词校验）
        feishu_text = f"【财经Agent】每日财经速递\n\n{ai_result}"
        send_to_feishu(feishu_text)
    else:
        print("AI 处理失败，本次不发送")
