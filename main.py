import os
import feedparser
import requests
from collections import defaultdict
from dotenv import load_dotenv
import calendar
from datetime import datetime, timezone, timedelta

load_dotenv()  # 加载 .env 里的环境变量（如 DEEPSEEK_API_KEY）

# ========== 配置区（要改口味，只动这里） ==========

# —— 新闻源：加源 / 删源 / 换源只改这个字典，主逻辑不用动 ——
SOURCES = {
    # —— 当前可用源（已验证出数据）——
    "华尔街见闻":       "https://dedicated.wallstreetcn.com/rss.xml",
    "财联社-深度":      "http://host.docker.internal:1200/cls/depth",
    "36氪":             "https://36kr.com/feed",
    "人民网-财经":      "http://www.people.com.cn/rss/finance.xml",
    "同花顺-AI产业链":  "http://host.docker.internal:1200/10jqka/realtimenews",

    # —— 待办源（留口，以后专项接入）——
    # 财联社电报 /cls/telegraph：已有深度替代，暂停接入
    # 金十数据 /jin10/telegraph：与财联社重叠，暂停
    # 新浪财经：路由待确认
    # Reuters /reuters/business/finance：国内服务器出海难
    # Bloomberg /bloomberg：同上
    # FT中文 /ftchinese：同上，暂缓
    # 巨潮资讯网：无官方RSS，需逆向接口
    # 国家统计局：需确认改版后栏目
}

# —— 飞书 Webhook（发送目标，以后换渠道只改这里）——
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/f59e5349-365f-4b19-8f6a-69930b1a2794"

# —— DeepSeek 配置 ——
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
PER_SOURCE_LIMIT = 30   # 每个源各取前 N 条交给 AI（保证各源都被看到，解决覆盖偏差）

# —— AI 筛选规格（要调口味只改这段文字，不动代码）——
FILTER_PROMPT = """你是一名资深财经新闻编辑，服务的用户为了投资决策、把握宏观环境、防范AI泡沫风险、刷新对世界的认知而读新闻。

【信息来源说明】今天的新闻来自五个各有侧重的源，请结合来源性质做判断：
- 华尔街见闻：国际宏观+AI产业链深度分析，文章质量高，优先保留
- 财联社深度：国内政策+产业深度文章，覆盖A股政策与产业动向，优先保留
- 36氪：AI/科技/创投动向，信息密度高但噪音也多，需严格过滤
- 人民网财经：官方政策信号权威，但RSS可能混入旧闻，注意新鲜度
- 同花顺7×24：AI产业链龙头公司的盘中快讯（台积电/英伟达/半导体等），条目短但事件真实，不因篇幅短而降低价值

【保留标准】保留满足以下任一条件的新闻：
1. 宏观政策信号（货币政策、利率决议、财政政策、重大产业政策）
2. 重要经济指标当期最新数据（CPI、PCE、PMI、GDP、社融、进出口等）
3. 影响全局的市场大势（主要股指大幅波动、大宗商品、汇率异动）
4. AI与半导体行业的趋势性动态、技术拐点、产业链利润结构变化
5. AI产业链头部公司重大动向（台积电、英伟达、微软、谷歌、亚马逊、Meta、苹果、OpenAI、Anthropic、DeepSeek等）

【去重（重要）】同一事件只保留信息量最大的那一条，其余全部丢弃：
- 同一经济数据（如PCE、PMI）有多篇报道 → 只留数据最完整的那一条，其余丢弃
- 同一人物表态有多篇解读 → 只留核心表态原文，去掉周边解读
- 同一公司事件被多源重复报道 → 只留信息最全的那一条
- 严格执行：同类事件最终只留1条，不留2条

【新鲜度】只保留近48小时内的新闻。标题或内容中能判断出是数天前、上周、上月的旧闻，直接丢弃，不论内容是否重要。

【地域规则】
- 中国、美国：正常保留所有符合保留标准的财经新闻
- 其他国家：仅保留具有全球性宏观影响的内容（如欧洲央行/日本央行利率决议、影响全球供应链或大宗商品的重大事件）
- 明确丢弃：他国本国的价格管控、补贴、社会政策等——例如"韩国下调燃油价格上限""印度上调电价"这类对全球宏观无影响的本国调控，一律丢弃

【明确丢弃】个股短线吹票、营销软文、基金理财广告、娱乐八卦、与全球宏观无关的他国政治社会事件

【取舍倾向】拿不准时倾向于保留，宁可多推，不漏重要新闻

【排序要求】精选新闻严格按"从宏观到微观"排序：
① 宏观政策与货币政策 → ② 重要经济指标 → ③ 全球市场与地缘能源 → ④ AI/半导体行业趋势 → ⑤ AI/半导体头部公司动向

请严格按以下格式输出：
【今日市场总结】
（3-5句话，综合保留的新闻，点明今天的宏观主线和值得关注的趋势）

【精选新闻】
1. 新闻标题 | 链接
2. 新闻标题 | 链接
（每条一行，已按从宏观到微观排序）
"""

# —— 网络请求通用设置 ——
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 20


# ========== 功能函数 ==========

def fetch_one_source(name, url):
    """抓取单个源，自动过滤48小时以外的旧闻。无论成功失败都返回结果。"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        feed = feedparser.parse(response.content)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        news = []
        skipped = 0

        for e in feed.entries:
            # 时间过滤：能解析 pubDate 时，丢弃48小时以外的旧闻
            if hasattr(e, 'published_parsed') and e.published_parsed:
                try:
                    pub_dt = datetime.fromtimestamp(
                        calendar.timegm(e.published_parsed), tz=timezone.utc
                    )
                    if pub_dt < cutoff:
                        skipped += 1
                        continue   # 旧闻，跳过
                except Exception:
                    pass           # 时间解析失败，宁可多推，保留这条

            news.append({
                "title": e.get("title", "无标题"),
                "link":  e.get("link", ""),
                "source": name
            })

        if skipped:
            print(f"   ↳ 过滤掉 {skipped} 条旧闻（超48小时）")

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
