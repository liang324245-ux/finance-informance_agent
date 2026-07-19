# 财经 Agent 系统

一套运行在云服务器上的全自动财经信息系统，每天定时抓取多个权威新闻源，由 AI 筛选整理后推送到飞书，同时监控 AI 产业链龙头公司动态及重要财报发布时间。

---

## 系统架构

系统由三个并行模块组成，每次运行按顺序执行：

```
早报直发（财联社早报，不经AI处理）
    ↓
产业链监控（扫描6层龙头公司，按层单独推送）
    ↓
主推送（AI筛选+总结，推送每日财经速递）
```

---

## 功能说明

### 一、每日财经速递（主推送）

从六个来源抓取新闻，经 DeepSeek AI 按照预设的筛选规格过滤，生成「今日市场总结」和「精选新闻列表」，推送到飞书。

**新闻来源及信任层级：**

| 来源 | 定位 | 时间过滤 |
|---|---|---|
| 华尔街见闻 | 国际宏观+AI产业链深度分析，商业媒体，单次占比不超40% | 48小时 |
| 财联社-深度 | 持牌通讯社，国内政策/数据第一手权威来源 | 48小时 |
| 36氪 | AI/科技/创投动向 | 48小时 |
| 证券时报-要闻 | 证监会主管，A股资本市场权威 | 48小时 |
| 同花顺-AI产业链 | AI产业链龙头公司盘中快讯 | 48小时 |
| 国家统计局-数据发布 | 官方原始经济数据，PMI/CPI/GDP等 | 24小时 |

**AI 筛选标准（7条）：**

1. 宏观政策信号（货币/财政/利率/产业政策）
2. 重要经济指标原始数据（优先国家统计局原文）
3. 影响全局的市场大势（股指/大宗商品/汇率）
4. AI 与半导体行业趋势性动态
5. AI 产业链头部公司重大动向
6. 资金战略动向（国资/机构战略布局，非游资日内数据）
7. 重大经济论坛关键表态（达沃斯/G20/博鳌/Jackson Hole/中央经济工作会议等）

**去重原则：**
- 同一中国宏观数据：只留国家统计局原文，丢弃华尔街见闻解读版
- 同一人物表态：只留信息最全那条
- 同一场合发言被拆分成多篇：只留信息量最大的1-2条
- 同一市场行情：全天只留1条综述

**多样性控制：**
- 单一来源不超过总数40%
- 同一市场事件最多1条
- 精选应覆盖：宏观政策、经济数据、市场动态、产业趋势、资金动向多维度

---

### 二、财联社早报（直发）

每天早报直接推送到飞书，不经过 AI 筛选，保留原始内容。仅在早报模式（早9点）执行，晚报不发。

---

### 三、AI 产业链监控（WATCHLIST）

按 AI 算力6层架构，实时监控50+龙头公司相关新闻，按层单独推送到飞书：

| 层级 | 代表公司 |
|---|---|
| 1️⃣ 电力层 | ABB、西门子能源、特变电工、Vertiv、台达 |
| 2️⃣ 冷却层 | CoolIT、Ecolab、英维克、佳力图 |
| 3️⃣ 计算层 | 英伟达、AMD、华为昇腾、寒武纪、超微 |
| 4️⃣ 数据层 | SK海力士、美光、三星、长鑫存储、长江存储 |
| 5️⃣ 网络层 | 博通、Arista、中际旭创、Coherent |
| 6️⃣ 调度层 | vLLM、TensorRT、MindSpore、飞桨 |

**匹配逻辑：** 标题包含公司名 → AI轻量过滤（去广告/软文）→ 按层单独发飞书

**关注内容：** 技术突破、资金投入、融资动作、上市/IPO、重大合作、业绩数据

---

### 四、财报提醒（earnings-reminder）

通过 Finnhub API 自动查询未来90天内关注公司的财报日期，在发布当天和前一天自动推送飞书提醒。

**关注公司：** 微软、谷歌、苹果、亚马逊、Meta、英伟达、AMD

---

## 运行时间表

| 时间 | 任务 |
|---|---|
| 每天 09:00 | 早报直发 + 产业链监控 + 主推送（早报模式，48小时窗口） |
| 每天 22:00 | 产业链监控 + 主推送（晚报模式，13小时窗口，不发早报） |
| 每天 08:00 | 财报提醒检查（查询今日/明日是否有关注公司发财报） |

---

## 技术架构

```
阿里云服务器（华东2，上海）
├── Docker 容器：finance-agent
│   ├── Python 3.12
│   ├── DeepSeek API（AI筛选）
│   └── 飞书 Webhook（消息推送）
├── Docker 容器：RSSHub（chromium-bundled版）
│   └── 端口 1200，供 agent 抓取财联社等特殊源
└── crontab 定时任务
    ├── finance-agent（早9点 + 晚22点）
    └── earnings-reminder（早8点）
```

---

## 项目结构

```
~/finance-informance_agent/    # 主项目（容器化）
├── main.py                    # 核心逻辑（抓取+AI筛选+推送+产业链监控）
├── Dockerfile                 # 容器化配置
├── requirements.txt           # Python 依赖
├── .env                       # 密钥（不上传 GitHub）
├── PRINCIPLES.md              # 系统设计原则
└── .github/workflows/         # GitHub Actions（已停用，改用服务器cron）

~/earnings-reminder/           # 财报提醒（独立轻量脚本）
├── earnings.py                # 财报日历查询+提醒逻辑
└── .env                       # Finnhub API Key（不上传 GitHub）
```

---

## 部署

### 前置条件

- 阿里云轻量应用服务器（Docker 镜像）
- Python 3.12（容器内）
- DeepSeek API Key
- 飞书自定义机器人 Webhook
- Finnhub API Key（免费）

### 主项目部署

```bash
# 克隆代码
git clone https://github.com/liang324245-ux/finance-informance_agent.git
cd finance-informance_agent

# 配置密钥
echo "DEEPSEEK_API_KEY=你的Key" > .env

# 构建镜像
docker build -t finance-agent .

# 手动测试（早报模式）
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e RUN_MODE=morning \
  finance-agent

# 设置 crontab 定时任务
# 0 9 * * * docker run --rm --add-host=host.docker.internal:host-gateway -e RUN_MODE=morning finance-agent >> /root/agent.log 2>&1
# 0 22 * * * docker run --rm --add-host=host.docker.internal:host-gateway -e RUN_MODE=evening finance-agent >> /root/agent.log 2>&1
```

### RSSHub 部署（财联社必须）

```bash
# 配置国内 Docker 加速器（写入 /etc/docker/daemon.json）
# 详见阿里云容器镜像服务-镜像加速器页面

# 启动 RSSHub（必须用带浏览器版本，普通版无法抓取财联社）
docker run -d \
  --name rsshub \
  -p 1200:1200 \
  -e PUPPETEER_SKIP_DOWNLOAD=false \
  diygod/rsshub:chromium-bundled
```

### 财报提醒部署

```bash
mkdir -p ~/earnings-reminder && cd ~/earnings-reminder

# 配置密钥
echo "FINNHUB_API_KEY=你的Key" > .env

pip3 install requests python-dotenv
# 创建 earnings.py（见项目文件）

# 测试运行
python3 earnings.py

# 设置定时任务
# 0 8 * * * cd /root/earnings-reminder && python3 earnings.py >> /root/earnings.log 2>&1
```

---

## 密钥管理

| 密钥 | 存储位置 |
|---|---|
| DEEPSEEK_API_KEY | 服务器 `~/.env`（本地） |
| FINNHUB_API_KEY | 服务器 `~/earnings-reminder/.env` |
| 飞书 Webhook | `main.py` / `earnings.py` 配置区 |

> ⚠️ `.env` 已加入 `.gitignore`，绝不上传 GitHub

---

## 日志查看

```bash
# 查看主推送最近日志
tail -80 /root/agent.log

# 查看财报提醒日志
tail -20 /root/earnings.log

# 搜索早报执行记录
grep -n "早报" /root/agent.log

# 清空日志（定期维护）
> /root/agent.log
```

---

## 待优化事项

- [ ] 新浪财经、Reuters、FT 等源（需自建 RSSHub 路由或代理）
- [ ] 飞书消息卡片样式美化（当前为纯文本）
- [ ] AI 提示词持续迭代（新闻源口味校准）
- [ ] RAG 接入 Obsidian 知识库（长期目标）
- [ ] 财经新闻筛选规格正式整理成 Skill 文档

---

## 设计原则

详见 `PRINCIPLES.md`：**稳定性、可延展性、多适配度**

- 配置与逻辑分离（换源/换口味只改配置区）
- 容错优先，失败可见（每次运行有日志记录）
- 小步验证，不把赌注压在单一来源
