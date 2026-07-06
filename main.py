import os
import time
import re
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
    "证券时报-要闻":    "http://host.docker.internal:1200/stcn/article/list/yw",   
    "36氪":             "https://36kr.com/feed",
    "人民网-财经":      "http://www.people.com.cn/rss/finance.xml",
    "同花顺-AI产业链":  "http://host.docker.internal:1200/10jqka/realtimenews",
    "国家统计局-数据发布": "https://www.stats.gov.cn/sj/zxfb/rss.xml",
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
# —— 直发源：不经AI筛选，抓到后直接推送飞书（适合早报等每日固定内容）——
DIRECT_SOURCES = {
    "财联社-早报": "http://host.docker.internal:1200/cls/subject/1151",
}
# ========== AI产业链6层架构龙头公司监控名单 ==========
WATCHLIST = {
    "1️⃣ 电力层": [
        "ABB", "西门子能源", "Siemens Energy", "日立能源", "Hitachi Energy",
        "GE Grid", "特变电工", "TBEA", "中国西电",
        "施���德电气", "Schneider", "维谛", "Vertiv", "伊顿", "Eaton",
        "台达", "Delta Electronics", "科华数据", "英威腾",
    ],
    "2️⃣ 冷却层": [
        "CoolIT", "Ecolab", "Modine", "Airedale", "Asetek", "Motivair",
        "英维克", "曙光数创", "佳力图", "Stulz",
    ],
    "3️⃣ 计算层": [
        "英伟达", "NVIDIA", "Blackwell", "NVL72",
        "AMD", "Instinct",
        "华为昇腾", "昇腾", "寒武纪", "海光信息",
        "英特尔", "Intel", "Xeon",
        "超微", "Supermicro", "工业富联", "浪潮信息", "中科曙光",
    ],
    "4️⃣ 数据层": [
        "SK海力士", "SK Hynix", "HBM",
        "美光", "Micron",
        "长鑫存储", "CXMT",
        "长江存储", "YMTC",
        "铠侠", "Kioxia", "闪迪",
        "三星", "Samsung",
    ],
    "5️⃣ 网络层": [
        "博通", "Broadcom",
        "Arista", "Marvell", "迈威尔",
        "InfiniBand",
        "中际旭创", "光迅科技", "天孚通信",
        "Coherent", "Lumentum",
        "硅光模块", "CPO",
    ],
    "6️⃣ 调度层": [
        "vLLM", "SGLang", "TensorRT",
        "MindSpore", "昇思",
        "飞桨", "PaddlePaddle",
        "魔搭", "ModelScope",
    ],
}

# 产业链公司新闻轻量过滤规格
WATCHLIST_FILTER_PROMPT = """你是一名AI产业链研究员。以下是提及特定龙头公司的新闻标题列表。

请保留涉及以下内容的新闻：技术突��/产品发布、资金投入/扩产计划、融资动作、上市/IPO动作、重大合作或订单、业绩数据、产能变化。

请丢弃：广告、软文、PR稿、无实质内容的会议预告、与公司核心业务无关的内容。

请直接输出保留的编号，格式（不要输出其他任何内容）：
保留: 1,3,5
若全部丢弃则输出：保留: 无"""

# —— 飞书 Webhook（发送目标，以后换渠道只改这里）——
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/f59e5349-365f-4b19-8f6a-69930b1a2794"

# —— DeepSeek 配置 ——
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
PER_SOURCE_LIMIT = 50   # 每个源各取前 N 条交给 AI（保证各源都被看到，解决覆盖偏差）

# —— AI 筛选规格（要调口味只改这段文字，不动代码）——
FILTER_PROMPT = """你是一名资深财经新闻编辑，服务的用户为了投资决策、把握宏观环���、防范AI泡沫风险、刷新对世界的认知而读新闻。

【信息来源说明】今天的新闻来自六个各有侧重的源，请结合来源性质做判断：
- 华尔街见闻：商业财经媒体，擅长包装国际信息，但以流量和订阅为商业导向，标题易夸大。优先采信其"全球实时快讯"（事实转述类）、海外政策原文转述、全球宏观数据汇总；对其评论、预测、分析类文章持保留态度，同等条件下优先选用财联社/证券时报/国家统计局的报道而非华尔街见闻的解读版本。单次精选中华尔街见闻来源不超过总数的40%。
- 财联社深度：国内政策+产业深度文章，中国官方数据的权威来源，优先保留
- 36氪：AI/科技/创投动向，信息密度高但噪音多，需严格过滤
- 证券时报-要闻：中国资本市场权威专业媒体，A股监管/上市公司/资本市场数据权威性高
- 人民网财经：官方政策信号，RSS可能混入旧闻，注意新鲜度
- 同花顺7×24：AI产业链龙头公司盘中快讯，条目短但事件真实，不因篇幅短降低价值
- 国家统计局-数据发布：中国官方统计机构直接发布的月度/季度经济数据，包括PMI（每月最后一天）、CPI/PPI（每月中旬）、GDP（每季度初）、工业利润、社融等核心指标。此类数据是宏观判断的原始依据，无论标题是否有分析深度，只要是新发布的指标数据，一律保留，不得以"内容简短"为由丢弃。
【保留标准】保留满足以下任一条件的新闻：
1. 宏观政策信号（货币政策、利率决议、财政政策、重大产业政策）
2. 重要经济指标当期最新数据（CPI、PCE、PMI、GDP、社融、进出口、工业利润等）——尤其是来自国家统计局-数据发布的原始数据，无条件保留
3. 影响全局的市场大势（主要股指大幅波动、大宗商品、汇率异动）
4. AI与半导体行业的趋势性动态、技术拐点、产业链利润结构变化
5. AI产业链头部公司重大动向（台积电、英伟达、微软、谷歌、亚马逊、Meta、苹果、OpenAI、Anthropic、DeepSeek等）
6. 资金战略动向（国资/社保/主权基金/央企的战略性投资布局方向；国家队加仓的行业或资产；重大并购与战略投资）——注意：仅保留结构性信号，丢弃A股概念股的游资追涨杀跌数据和主力资金日内进出数据
7. 重大经济论坛与峰会的关键表态（包括但不限于：达沃斯世界经济论坛、G7/G20峰会、博鳌亚洲论坛、Jackson Hole央行年会、APEC、中央经济工作会议、全国两会经济议题、BIS/IMF/世界银行年会）——保留范围：各国央行行长/财长/政府首脑的政策表态、峰会联合公报中的经济条款、重大议题的共识或分歧。丢弃：论坛边会的企业家观点、明星嘉宾发言、会议花絮报道。
8. A股市场整体资金流向与风格切换（板块轮动、主力资金净流入/���出统计、机构调研动向、南向/北向资金流向、市场情绪指标）——判断标准：反映的是板块或整体市场层面的资金行为，而非单一股票的涨跌消息。例如"券商保险板块拉升，科技股跳水""7股遭主力资金大幅出逃""南向资金6月净流入271亿港元"应保留。
【去重规则（严格执行）】
- 同一经济数据有多篇报道时：优先选财联社原文（官方通讯社，数据准确无主观渲染）；华尔街见闻对同一数据的解读文章单独保留仅当它提供了显著的市场分析增量，否则丢弃
- 中国宏观经济数据（PMI、CPI、PPI、GDP、工业利润、社融等）：以国家统计局-数据发布的原文为唯一保留版本，财联社对同一数据的转述可保留仅当有显著增量信息，华尔街见闻对同一中国数据的解读文章一律丢弃
- 同一场合/同一次发言被拆分成多篇独立报道时（如同一场论坛发言被按话题拆成多篇稿件）：
  第一步：从中挑出信息量最大、市场影响最直接的1-2条作为精选新闻正式列出，标题和链接必须是原文，不可改写标题。
  第二步：其余相关内容，在这1-2条精选新闻下方以"相关补充："开头，用2-3句话概括其余报道的关键事实信息。
  【严格限制】概括时只能转述原文已经明确写出的事实（人物、数字、政策动作、时间），绝对不允许添加任何原文没有的推断、评价、因果解读或市场影响判断。若无法在不推断的情况下概括，则直接省略该条，不勉强总结。
- 同一公司事件被多源重复报道，只留信息最全的那一条
- 同一天的股市整体涨跌行情（如某次五连跌、板块暴跌），全部合并只留1条综述，不留多条视角报道
- 严格执行：同类事件最终只留1条

【精选新闻】
1. 新闻标题 | 链接
   （若该新闻所在事件有相关补充信息，在此另起一行，以"相关补充："开头，2-3句话概括，只写原文明确事实，不做推断）
2. 新闻标题 | 链接
（每条一行，已按从宏观到微观排序）

【多样性（严格执行）】
- 最终精选必须覆盖不同维度：宏观政策、经济数据、市场动态、产业趋势、资金动向等
- 市场涨跌相关报道：合并后最多1条
- 同一公司/同一事件：最多1条
- 宁可选一条"国资战略布局AI"，也不要第3条"市场下跌解读"

【转载标注】仅当新闻的来源标签中含有"转自XXX"字样时（如"财联社转自国家统计局"），才在标题后括号内注明，格式：新闻标题（转自XXX）| 链接。绝大多数新闻并非转载，此时禁止添加任何来源标注，直接输出：新闻标题 | 链接

【新鲜度】只保留近48小时内的新闻，明显旧闻直接丢弃

【地域规则】
- 中国、美国：正常保留所有符合标准的财经新闻
- 其他国家：仅保留具有全球性宏观影响的内容（如欧洲���行/日本央行利率决议、影响全球供应链的事件）
- 丢弃：他国本国价格管控、补贴、社会政策

【明确丢弃】个股短线吹票、营销软文、基金理财广告、娱乐八卦、与全球宏观无关的他国政治社会事件

【取舍倾向】拿不准时倾向于保留，宁可多推，不漏重要新闻

【排序要求】精选新闻严格按"从宏观到微观"排序:
① 全球市场大势与地缘能源/资源矿产 → ② 经济指标 → ③ 国家宏观经济政策 → ④ 资金战略动向 → ⑤ A股市场资金流向与风格切换 → ⑥ AI/半导体行业趋势 → ⑦ AI/半导体头部公司动向

请严格按以下格式输出：
【今日市场总结】
（3-5句话，综合保留的新闻，点明今天的宏观主线和值得关注的趋势）

【精选新闻】
1. 新闻标题（转自XXX，如适用）| 链接
2. 新闻标题 | 链接
（每条一行，已按从宏观到微观排序）
"""

# —— 网络请求通用��置 ——
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 20

def ai_filter_watchlist(layer, items):
    """对产业链公司新闻做轻量AI过滤，去除广告/软文。失败时保留全部（宁多勿漏）。"""
    if not items:
        return []

    news_text = "\n".join(
        f"{i}. {item['title']}"
        for i, item in enumerate(items, start=1)
    )
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": WATCHLIST_FILTER_PROMPT},
            {"role": "user", "content": f"【{layer}】相关新闻：\n{news_text}"}
        ]
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=30)
        result = response.json()
        if "choices" not in result:
            return items
        content = result["choices"][0]["message"]["content"].strip()
        if "无" in content:
            return []
        numbers = re.findall(r'\d+', content)
        kept = {int(n) - 1 for n in numbers if 1 <= int(n) <= len(items)}
        return [items[i] for i in sorted(kept)]
    except Exception as e:
        print(f"⚠️ 产业链AI过滤出错（{layer}）：{e}，保留全部")
        return items


def scan_and_send_watchlist(news_list):
    """
    扫描新闻标题中的6层龙头公司，按层分组，AI过滤后各层单独发飞书。
    返回未匹配的新闻列表供主推送使用。
    """
    layer_matches = {layer: [] for layer in WATCHLIST}
    matched_indices = set()

    for i, item in enumerate(news_list):
        title = item["title"]
        for layer, companies in WATCHLIST.items():
            matched = False
            for company in companies:
                if company in title:
                    layer_matches[layer].append(item)
                    matched_indices.add(i)
                    matched = True
                    break
            if matched:
                break  # 每条新闻只归入第一个匹配的层，避免重复发送

    layers_with_news = {l: v for l, v in layer_matches.items() if v}

    if not layers_with_news:
        print("📊 今日无产业链龙头公司动态")
    else:
        print(f"📊 产业链扫描：共 {len(matched_indices)} 条匹配，涉及 {len(layers_with_news)} 个层")
        for layer, items in layers_with_news.items():
            filtered = ai_filter_watchlist(layer, items)
            if not filtered:
                print(f"   {layer}：{len(items)} 条扫描到，过滤后全部丢弃")
                continue
            # 构造飞书消息
            lines = [f"财经Agent AI产业链动态 {layer}\n"]
            for j, item in enumerate(filtered, start=1):
                lines.append(f"{j}. {item['title']}")
                lines.append(f"   {item['link']}")
            text = "\n".join(lines)
            success = send_to_feishu(text)
            status = "✅ 已发送" if success else "❌ 发送失败"
            print(f"   {layer}：{len(items)} 条 → 过滤后 {len(filtered)} 条 → {status}")
            time.sleep(5)  # 层间间隔，避免飞书频率限制

    # 返回未被产业链监控匹配的新闻，供主推送使用
    remaining = [item for i, item in enumerate(news_list) if i not in matched_indices]
    return remaining

# ========== 功能函数 ==========
def fetch_and_send_direct():
    """抓取直发源，不经AI筛选，直接推送到飞书（适合早报等每日固定内容）"""
    if not DIRECT_SOURCES:
        return
    print("📰 正在抓取直发源...")
    for name, url in DIRECT_SOURCES.items():
        result = fetch_one_source(name, url)
        if result["ok"] and result["count"] > 0:
            latest = result["news"][0]
            text = f"财经Agent {name}\n\n{latest['title']}\n\n{latest['link']}"
            success = send_to_feishu(text)
            if success:
                print(f"✅ 直发 {name}：已推送到飞书")
            else:
                print(f"❌ 直发 {name}：推送失败（见上方错误）")
        else:
            print(f"⚠️ 直发 {name}：未获取到内容（{result.get('error', '')}）")


def fetch_one_source(name, url):
    """抓取单个源，自动过滤48小时以外的旧闻。无论成功失败都返回结果。"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        feed = feedparser.parse(response.content)

        # 差异化时间窗口：低频源(国家统计局等)用更长的时间窗口
        LOW_FREQ_SOURCES = {"国家统计局-数据发布"}
        hours = 24   # 国家统计局改为24小时窗口，避免早晚报重复推送同一条数据 if name in LOW_FREQ_SOURCES else 48  
        # 差异化时间窗口：低频源(国家统计局)用更长的时间窗口
        LOW_FREQ_SOURCES = {"��家统计局-数据发布"}
        run_mode = os.getenv("RUN_MODE", "morning")  # 默认早报模式(48小时)，晚报模式传evening(13小时)
        if name in LOW_FREQ_SOURCES:
            hours = 720  # 国家统计局始终用30天窗口，不受早晚报模式影响
        elif run_mode == "evening":
            hours = 13   # 晚报：只看早报之后新增的内容
        else:
            hours = 48   # 早报：覆盖隔夜及周末的全部新闻
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
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

            # 检测是否为转载（description/summary 中含"原文链接"）
            summary = e.get("summary", "") or e.get("description", "") or ""
            is_repost = "原文链接" in summary
            original_source = ""
            if is_repost:
                match = re.search(r'来源[：:]\s*([^\s<，,。\n]{2,10})', summary)
                if match:
                    original_source = match.group(1).strip()
            news.append({
                "title":           e.get("title", "无标题"),
                "link":            e.get("link", ""),
                "source":          name,
                "is_repost":       is_repost,
                "original_source": original_source,
            })

        if skipped:
            print(f"   ↳ 过滤掉 {skipped} 条旧闻��超48小时）")

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
    """每个来源各取前 N 条，保证每个���都被 AI 看到（解决覆盖偏差）。"""
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
    selected = news_list
    print(f"📋 交给 AI 的新闻：{len(selected)} 条（全量）")
    def build_label(item):
        """构造新闻来源标签，转载时注明原始来源"""
        if item.get("is_repost") and item.get("original_source"):
            return f"{item['source']}转自{item['original_source']}"
        elif item.get("is_repost"):
            return f"{item['source']}(转载)"
        return item["source"]


    news_text = "\n".join(
        f"{i}. [{build_label(item)}] {item['title']} | {item['link']}"
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
        response = requests.post(
            DEEPSEEK_URL, json=payload, headers=headers, timeout=60)
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"]
        else:
            print(f"⚠️ AI 返回异常：{result}")
            return None
    except Exception as error:
        print(f"❌ AI 调用出错：{type(error).__name__} - {error}")
        return None


def send_to_feishu(text, max_retries=2):
    """把一段文本发送到飞书，失败时自动重试。返回 True/False。"""
    if not text:
        print("没有内容可发送")
        return False
    message = {"msg_type": "text", "content": {"text": text}}
    for attempt in range(max_retries):
        try:
            response = requests.post(FEISHU_WEBHOOK, json=message, timeout=15)
            result = response.json()
            if result.get("code") == 0:
                print("✅ 已发送到飞书")
                return True
            elif result.get("code") == 11232:
                # 频率限制：等待后重试
                wait = 60 * (attempt + 1)  # 第1次失败等60秒，第2次等120秒
                print(f"⏳ 飞书频率限制，等待{wait}秒后重试（第{attempt+1}次）...")
                time.sleep(wait)
            else:
                print(f"❌ 飞书发送失败：{result}")
                return False
        except Exception as error:
            print(f"❌ 发送出错：{type(error).__name__} - {error}")
            return False
    print("❌ 飞书发送多次重试后仍失败")
    return False

# ========== 主流程 ==========
if __name__ == "__main__":
    # 第一步：直发早报（不经AI）
    if os.getenv("RUN_MODE", "morning") == "morning":
        fetch_and_send_direct()

    # 第二步：抓取全部新闻
    news_list = fetch_all()
    print(f"\n所有源合计抓到 {len(news_list)} 条新闻\n")

    # 第三步：产业链龙头公司监控（单独按层发飞书，匹配的从主推送移走）
    remaining_news = scan_and_send_watchlist(news_list)
    print(f"\n主推送可用新闻：{len(remaining_news)} 条（已移除产业链匹配条目）\n")

    # 第四步：主推送（用剩余新闻做AI筛选+总结）
    ai_result = ai_filter_and_summarize(remaining_news)
    if ai_result:
        print("=" * 50)
        print(ai_result)
        print("=" * 50)
        feishu_text = f"财经Agent 每日财经速递\n\n{ai_result}"
        send_to_feishu(feishu_text)
    else:
        print("AI 处理失败，本次不发送")
