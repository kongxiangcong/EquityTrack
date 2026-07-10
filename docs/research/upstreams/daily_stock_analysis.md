# `ZhuLinsen/daily_stock_analysis` 上游研究

> 研究对象：<https://github.com/ZhuLinsen/daily_stock_analysis>
> 固定提交：[`d08374898c25f4718d61b1779ac4c1fedc9aa9a2`](https://github.com/ZhuLinsen/daily_stock_analysis/commit/d08374898c25f4718d61b1779ac4c1fedc9aa9a2)
> 提交时间：2026-07-10 22:22:35 +08:00
> 本地位置：`.research/upstreams/daily_stock_analysis`
> 研究方法：只读检查该固定提交的源码、仓内 README/文档、测试与 Git 提交元数据；没有把宣传文案当作已实现能力。

## 结论先行

`daily_stock_analysis`（下文简称 DSA）值得借鉴的核心不是估值方法，而是“把不稳定外部能力做成可日常使用产品”的工程经验：多数据源 fallback、断点续传、异步任务/SSE、诊断快照、历史记录、通知渠道和结构化 Web 工作台都相当完整。它证明了个人投研系统可以从一次性报告脚本演进成持续运行的工作台。

但 DSA 不是严谨的公司估值系统。固定提交中的 `valuation` 只收集 `pe_ratio`、`pb_ratio`、总市值和流通市值；仓库没有可执行的 DCF、WACC、FCFF/FCFE、终值、情景敏感性、同业可比筛选或行业特定估值路由。源码中唯一的 `DCF` 命中只是“不要把金融缩写误识别为股票代码”的停用词。证据见 [`data_provider/base.py:L3189-L3211`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L3189-L3211) 与 [`src/agent/orchestrator.py:L1462-L1472`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/agent/orchestrator.py#L1462-L1472)。因此它可作为本地系统的“运行壳、数据适配和报告体验”参考，不能替代本地项目现有的来源门、估值路由与可审计财务模型。

最重要的五条判断：

1. **借鉴其 fail-open，但改成能力级降级。** DSA 在实时行情、筹码、搜索和基本面失败时继续运行，避免一项缺失卡死整条链路；本地系统应进一步把门拆成 `research / valuation / trade_plan / rating` 独立 capability gate，而不是 Task 1 一个总门决定 Task 2 是否能开始。
2. **借鉴其 Adapter 生态，不照搬聚合器巨类。** `DataFetcherManager` 已证明多源 fallback 的价值，但 `BaseFetcher`/manager 同时承担行情、名称、基本面、资金流、板块和市场统计，形成超宽 Interface；本地应按能力 port 分离，并由一个深的根 Module 隐藏编排。
3. **LLM/skill 只做解释与候选观点，不做事实、估值或最终交易规则。** DSA 的 YAML skill 本质是自然语言 prompt 注入，类似 `sentiment_score +15` 的规则没有确定性执行语义；本地的财务计算、方法适用性、仓位和风控必须是可测试的 in-process Implementation。
4. **借鉴可观测性和“可解释降级”。** DSA 的 provider run、LLM run、通知 run、context pack 质量状态和 run-flow 可视化非常适合个人系统；它比简单抛出“数据不足”更能帮助用户补数据或重跑。
5. **报告应采用“规范化研究结果 -> 多 renderer”而不是字符串拼装。** DSA 的 Web 报告已具备卡片、评分仪表、追溯面板和运行流，但本地 Markdown/通知仍主要是文字和表格，且没有一等的独立 HTML 投研报告 renderer。应复用其信息架构，新增财务图表、估值敏感性、价格/事件时间轴和证据抽屉，而不是复制它的买卖措辞。

## 1. 项目定位与功能完整性

### 1.1 它实际是什么

DSA 是“日常股票分析与分发工作台”，不是交易执行系统。README 承诺的主输出是核心结论、评分、趋势、买卖点位、风险警报和检查清单；同时提供 CLI、FastAPI、Web、桌面壳、调度器、机器人和多渠道通知。[`README.md:L41-L50`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/README.md#L41-L50)

固定提交的代码面很宽：978 个 tracked files，其中 503 个 Python 文件、267 个 TS/TSX 文件、224 个 Python 测试文件和 92 个 Web 测试/规格文件。宽度来自多个产品用例共同生长，而不是一个紧凑的投研内核。

| 能力 | 完整性判断 | 主要证据 | 对本地重构的意义 |
|---|---|---|---|
| 多市场行情 | 较完整；A/H/US/JP/KR/TW 有显式路由和降级 | [`data_provider/base.py:L615-L627`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L615-L627) | 借鉴 Adapter 注册、市场能力矩阵与 fallback trace |
| 技术分析 | 有确定性 MA/MACD/RSI/量价/支撑压力与 100 分启发式评分 | [`src/stock_analyzer.py:L172-L200`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/stock_analyzer.py#L172-L200)、[`L585-L754`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/stock_analyzer.py#L585-L754) | 可作基线 indicator Module；阈值需版本化、校准与回测，不应视作普适方法论 |
| 新闻/事件 | 多 provider、缓存、相关性过滤、官方域名加权，工程较强 | [`src/search_service.py:L2098-L2258`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/search_service.py#L2098-L2258) | 借鉴搜索 Adapter 和证据去重；仍需独立公告/正式披露 port |
| 基本面 | 轻量聚合；增长、盈利、机构、资金流等块可 partial | [`data_provider/base.py:L3111-L3170`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L3111-L3170) | 借鉴 block status，不照搬数据权威性 |
| 估值 | 仅 PE/PB/市值快照；无内在价值模型 | [`data_provider/base.py:L3178-L3211`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L3178-L3211) | 不可替代本地 DCF/可比/行业方法路由 |
| 交易计划 | LLM dashboard 产出入场、止损、止盈、仓位文字；部分阶段护栏为确定性后处理 | [`src/schemas/report_schema.py:L92-L126`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/schemas/report_schema.py#L92-L126)、[`src/phase_decision_guardrail.py:L116-L205`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/phase_decision_guardrail.py#L116-L205) | 借鉴阶段护栏；价格点位和仓位应改为 deterministic policy output |
| 历史评估 | 能评价过去报告的方向、止损/止盈触达；不是完整策略回测 | [`src/core/backtest_engine.py:L158-L273`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/backtest_engine.py#L158-L273) | 借鉴 outcome feedback；另建含费用、滑点、组合资金曲线的策略回测 |
| Web/桌面 | React/Vite Web 工作台 + Electron 壳，历史、任务、回测、持仓、设置齐全 | [`apps/dsa-web/src/App.tsx:L15-L25`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/App.tsx#L15-L25) | 借鉴页面信息架构和任务可视化 |
| 独立 HTML 投研报告 | 未形成一等 renderer；核心 renderer 只声明 markdown/wechat/brief | [`src/services/report_renderer.py:L77-L113`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/services/report_renderer.py#L77-L113) | 本地应新增 `html`/`pdf` Artifact Adapter，而非把 Web 页面当报告文件 |

### 1.2 可行性边界

它对“每天看自选股、快速得到方向性提示、保存历史并推送”是可行的；对“可复核财务建模、估值结论、正式交易计划”不充分，原因有四个：

- 免费行情源能零配置运行，但项目自己明确承认限流、接口变化和网络波动，稳定运行建议 token 型数据源。[`README.md:L59-L61`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/README.md#L59-L61)
- 基本面 `source_chain` 只规范为 provider/result/duration，不能把每一个关键财务数字追到官方文档、页码、表格和发布日期。[`data_provider/base.py:L2640-L2677`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L2640-L2677)
- 报告 schema 对大量字段使用 `Optional`，Pydantic 校验失败还会继续走较弱的 parser contract；这提升“能出结果”的概率，却不是严格研究结论的证明。[`src/schemas/report_schema.py:L7-L10`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/schemas/report_schema.py#L7-L10)、[`src/analyzer.py:L4429-L4458`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/analyzer.py#L4429-L4458)
- LLM 输出失败时会尝试文本关键词推断方向，但结果标成 `success=False` 且不持久化；这是合理的 UX 兜底，却说明买卖语义可能来自文本启发式而非模型或估值证据。[`src/analyzer.py:L4649-L4716`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/analyzer.py#L4649-L4716)

## 2. 数据获取与降级

### 2.1 值得借鉴的实现

`BaseFetcher` 统一日线标准列、清洗和轻量指标计算；`DataFetcherManager` 按市场和 capability 过滤候选源，逐一尝试并记录延迟、错误类型、fallback 目标与记录数。[`data_provider/base.py:L327-L368`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L327-L368)、[`L1242-L1305`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L1242-L1305)

默认源按配置动态实例化：免费源直接可用，Tushare、TickFlow、Longbridge、Finnhub、AlphaVantage 只有配置后才加入，避免反复探测无凭据来源。[`data_provider/base.py:L1139-L1228`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L1139-L1228)

流水线先检查数据库是否已有目标交易日数据，有则跳过网络；新数据保存后再分析。即使本轮 fetch 失败，也尝试使用已有数据继续，这是降低日常摩擦的关键。[`src/core/pipeline.py:L304-L358`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/pipeline.py#L304-L358)、[`L2798-L2818`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/pipeline.py#L2798-L2818)

基本面采用统一块结构：`status / coverage / source_chain / errors / data`，并在总预算内做 timeout/retry。它将 `ok / partial / failed / not_supported` 保留下来，而不是把缺失值伪装成 0。[`data_provider/base.py:L2555-L2634`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L2555-L2634)、[`L2688-L2700`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L2688-L2700)

### 2.2 不应照搬

- `BaseFetcher` 的默认方法扩展到指数、市场宽度、板块、概念、热门股、涨停池等，manager 又继续扩展到实时行情、筹码、名称、基本面、资金流、龙虎榜；这是一个不断变宽的 Interface，不是真正按 capability 分开的 seam。
- `StockAnalysisPipeline.__init__` 在内部直接创建数据库、fetch manager、技术分析器、LLM、通知和搜索；caller 无法在根 Interface 注入依赖，测试只能 patch 全局单例或内部对象。[`src/core/pipeline.py:L175-L246`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/pipeline.py#L175-L246)
- timeout 通过 daemon thread + semaphore 实现，超时线程不能被真正取消，只是限制悬挂 worker 数；适合兼容同步第三方库，但不应成为新内核的默认并发模型。[`data_provider/base.py:L2555-L2602`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/data_provider/base.py#L2555-L2602)
- A 股财务数据以 AkShare 聚合结果为主，虽有 `stock_dividend_cninfo` 等接口和官方新闻域名加权，但没有本地项目所需的“关键字段 -> 官方披露文档 -> source_id”硬契约。不可用它放松正式估值的证据要求。

## 3. 工作流编排与容错

### 3.1 实际顺序

CLI/定时主流程先做交易日过滤和市场上下文，再构造 `StockAnalysisPipeline`；个股分析完成后可复用上下文生成大盘复盘并合并通知。[`main.py:L659-L782`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/main.py#L659-L782)

单股内部顺序是：

1. 日线断点续传；
2. 实时行情和筹码，失败回历史收盘/空块；
3. 基本面块聚合；
4. 确定性技术分析；
5. 根据配置进入 legacy LLM 或 Agent 分支；
6. 新闻/情报、context pack、LLM 生成；
7. 结构与阶段 guardrail；
8. 保存历史、抽取 decision signal、生成本地报告和通知。

主干证据见 [`src/core/pipeline.py:L360-L547`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/pipeline.py#L360-L547) 与 [`L549-L832`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/pipeline.py#L549-L832)。

批量任务用线程池并发，默认低并发；每只股票失败不会影响其它股票。结果收集完成后无论是否推送都保存本地报告。[`src/core/pipeline.py:L2848-L3024`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/pipeline.py#L2848-L3024)

Web API 将一只股票映射为一个异步任务，限制单批 50 只，去重后进入单例任务队列；SSE 推送 created/started/progress/completed/failed 和 heartbeat。[`api/v1/endpoints/analysis.py:L275-L347`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/api/v1/endpoints/analysis.py#L275-L347)、[`L654-L721`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/api/v1/endpoints/analysis.py#L654-L721)

### 3.2 对当前本地 Task 1 卡死问题的启发

DSA 的正确启发不是“删掉所有门”，而是把失败语义从 pipeline gate 改成 capability state：

| 数据状态 | 仍可执行 | 必须禁用 |
|---|---|---|
| 只有日线/实时行情 | 技术分析、市场阶段、观察条件、数据缺口报告 | 正式基本面估值、评级 |
| 财务块 partial | 公司概览、已覆盖指标、估算情景（明确标记） | 依赖缺失输入的方法、无证据目标价 |
| 官方披露不足但二级源可用 | 研究草稿、候选事实清单、待核验表 | 正式 source-ready 结论 |
| LLM 不可用 | 全部确定性计算、数据质量、模板化报告 | 自然语言综合与 Agent 讨论 |
| renderer/通知失败 | 已持久化 canonical research outcome | 只禁用对应 artifact/delivery |

也就是说，Task 1 不应再返回一个布尔值；它应产出 `EvidenceLedger + CapabilityAssessment`。Task 2 可以执行所有输入已满足的方法，未满足的方法单独 `disabled`，而不是整阶段不启动。

## 4. LLM、Agent 与 skill

DSA 同时保留两条生成路径：普通分析的 `GeminiAnalyzer`（实际通过 LiteLLM/本地 CLI backend）和可选 Agent。只有显式 `agent_mode`、请求指定 skill 或配置特定 skill 时才切 Agent，避免用户仅配置 API key 就被静默切换到更慢、更贵的路径。[`src/core/pipeline.py:L458-L473`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/pipeline.py#L458-L473)

普通路径把激活 skill 的 instructions 拼入 system prompt；skill 支持 YAML 与 `SKILL.md`，自定义同名 skill 覆盖内置 skill。[`src/analyzer.py:L2304-L2366`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/analyzer.py#L2304-L2366)、[`src/agent/skills/base.py:L315-L391`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/agent/skills/base.py#L315-L391)

skill loader 只校验名称、描述、instructions 等结构元数据；其判断与加减分仍是自然语言。例如“成长质量”直接写 `sentiment_score +15/-12`，并没有一个确定性 evaluator 执行或证明这些权重。[`src/agent/skills/base.py:L140-L202`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/agent/skills/base.py#L140-L202)、[`strategies/growth_quality.yaml:L17-L54`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/strategies/growth_quality.yaml#L17-L54)

多 Agent 模式按 `technical -> intel -> risk -> decision` 顺序运行；quick/standard/full/specialist 只是不同链长。intel、risk 和 skill agent 失败可降级，关键阶段失败才终止；整个链有总预算和每 stage 最小剩余预算。[`src/agent/orchestrator.py:L399-L492`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/agent/orchestrator.py#L399-L492)、[`L573-L627`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/agent/orchestrator.py#L573-L627)、[`L633-L665`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/agent/orchestrator.py#L633-L665)

可借鉴：

- skill 作为“观点/方法说明插件”很方便，支持用户扩展；
- Agent tool 有 scope/timeout/output-size 守卫，stage 有预算；
- 先准备确定性上下文，再让 Agent 消费，减少重复工具调用；
- 失败 stage 写入 degraded marker，最终结果能解释缺失。

不应照搬：

- 不让 skill 决定数据门、估值公式、仓位或最终评分；
- 不让 Agent 自由选择估值方法，方法路由必须先由 deterministic MethodRouter 决定；
- 不保留 legacy 与 Agent 两套端到端 pipeline。应只有一个事实/模型管线，LLM 是可替换的 Synthesis Adapter；
- 不把“多 Agent”当作正确性来源。多个 agent 共用同一不完整数据与相似 prompt 时，只会放大成本和相关性错误。

## 5. 配置与个人使用体验

优点是入口多、默认路径低门槛：股票列表 + 任一 LLM key 即可运行，免费行情源可零配置；CLI 支持 dry-run、指定股票、禁用通知、调度、Web、回测等。[`main.py:L265-L428`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/main.py#L265-L428)

配置写入采用带版本指纹的原子 upsert，敏感字段 mask 不会意外覆盖已有 secret；这很适合 Web 设置页。[`src/core/config_manager.py:L158-L215`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/config_manager.py#L158-L215)、[`L217-L256`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/core/config_manager.py#L217-L256)

主要问题是配置面已经失控：`.env.example` 约 49 KB，`Config` 单例同时承载数据、LLM、Agent、搜索、通知、调度、Web、机器人、回测和流控；全局只加载一次，又有部分热读 `.env` 的例外。[`src/config.py:L701-L776`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/config.py#L701-L776)、[`L839-L869`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/config.py#L839-L869)、[`L2736-L2764`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/config.py#L2736-L2764)

对个人用户，这会带来三个现实摩擦：不知道最小配置集、设置间存在隐式耦合、出错时难判断是数据源/模型/报告/通知哪一层。DSA 后来补的 diagnostics 和 Web 状态页缓解了后一个问题，但没有消除配置 Module 过浅、过宽的问题。

本地项目应采用分层配置：`ResearchPolicyConfig`、`ProviderConfig`、`ModelConfig`、`ArtifactConfig`、`DeliveryConfig`，由 composition root 组装；每个 use case 只看到自己的 typed view。保留 DSA 的原子更新、secret mask 和结构化 validation，但不要复制全局 `Config` 单例。

## 6. 输出报告、前端与 HTML

### 6.1 现状

后端 `AnalysisResult` 同时保存核心评分、技术/基本面/新闻长文本、dashboard、raw response 和运行元数据，字段很多且兼容历史格式。[`src/analyzer.py:L1666-L1735`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/analyzer.py#L1666-L1735)

Jinja renderer 会生成 markdown/wechat/brief；模板包含摘要、情报、核心结论、行情表、数据透视、阶段护栏、信号归因和“狙击点位”，但视觉载体仍是 Markdown 标题、列表和表格。[`templates/report_markdown.j2:L25-L114`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/templates/report_markdown.j2#L25-L114)、[`L116-L200`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/templates/report_markdown.j2#L116-L200)

而且 renderer 默认配置仍是关闭，失败后 caller 回退到 `NotificationService` 内的大段手工字符串拼装，导致两套报告 Implementation 并存。[`.env.example:L704-L719`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/.env.example#L704-L719)、[`src/notification.py:L1107-L1155`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/src/notification.py#L1107-L1155)

Web 报告的信息架构明显优于 Markdown：首屏是公司/价格/摘要 + 评分仪表，后续按策略点位、资讯、数据上下文、运行诊断和原始快照展开。[`apps/dsa-web/src/components/report/ReportSummary.tsx:L60-L99`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/components/report/ReportSummary.tsx#L60-L99)、[`ReportOverview.tsx:L245-L397`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/components/report/ReportOverview.tsx#L245-L397)

Web 还有两个尤其值得借鉴的体验：

- 数据上下文按 `available/missing/not_supported/fallback/stale/estimated/partial/fetch_failed` 展示质量分与限制，而不是只显示“失败”。[`AnalysisContextSummary.tsx:L20-L36`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/components/report/AnalysisContextSummary.tsx#L20-L36)、[`L270-L314`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/components/report/AnalysisContextSummary.tsx#L270-L314)
- 报告可以打开 run-flow 图，查看数据源和阶段拓扑；这比堆日志更适合个人排障。[`apps/dsa-web/src/pages/HomePage.tsx:L1066-L1078`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/pages/HomePage.tsx#L1066-L1078)

### 6.2 不足与本地建议

在固定提交的个股报告 composition 中，主要视觉只有 `ScoreGauge`、点位卡片、状态 badge 和历史表格；没有 K 线/成交量、财务三表趋势、利润率桥、估值区间/敏感性热图、同业散点图、事件时间轴或来源覆盖图。完整 Markdown drawer 仍只是 `react-markdown + GFM`。[`ReportStrategy.tsx:L48-L83`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/components/report/ReportStrategy.tsx#L48-L83)、[`ReportMarkdownBody.tsx:L11-L39`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/src/components/report/ReportMarkdownBody.tsx#L11-L39)

本地 HTML 报告应以同一 `ResearchOutcome` 为输入，并至少包含：

1. executive summary：research view、数据等级、估值区间、主要风险，不直接复用买卖口号；
2. evidence coverage：关键字段来源、as-of、缺失/估算、官方/二级源占比；
3. financials：收入、毛利、净利、现金流、ROE/ROIC 的多期图表；
4. valuation：方法选择理由、关键假设、base/bull/bear、敏感性矩阵、可比公司口径；
5. market/technical：K 线、均线、成交量、关键位与事件标注；
6. trade-plan research view：触发条件、失效条件、风险预算和复核时间；
7. provenance drawer：点击任一关键数字回到 source_id、文档、页码/表格；
8. diagnostics：provider fallback、模型版本、代码/模型版本、run id。

HTML、Markdown、JSON、PDF 应是四个 Artifact Adapter；任何 renderer 失败都不能改变 canonical outcome。

## 7. 测试与工程质量

优点：Python CI 执行语法检查、critical flake8、本地 deterministic checks 和全部 `not network` pytest；Docker 构建后还做关键 import smoke。[`.github/workflows/ci.yml:L41-L77`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/.github/workflows/ci.yml#L41-L77)、[`L79-L110`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/.github/workflows/ci.yml#L79-L110)

不足：Web CI 在前端改动时只跑 lint/build，没有执行已有 Vitest；Playwright 虽配置 trace/screenshot/video 和双 server，但需要密码环境变量且当前 CI workflow 没有调用。 [`ci.yml:L113-L135`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/.github/workflows/ci.yml#L113-L135)、[`apps/dsa-web/playwright.config.ts:L28-L63`](https://github.com/ZhuLinsen/daily_stock_analysis/blob/d08374898c25f4718d61b1779ac4c1fedc9aa9a2/apps/dsa-web/playwright.config.ts#L28-L63)

更深层问题是测试数量不能抵消模块过浅：`pipeline.py`、`analyzer.py`、`base.py`、`config.py`、`search_service.py`、`storage.py` 和 `notification.py` 都是数千行热点文件。改动常跨多个大文件和兼容分支，Locality 差。删除 `StockAnalysisPipeline` 后，复杂度会重新散落到 CLI、API、Agent、通知和历史调用者，说明它确实有一些 Depth；但它的 Interface（构造参数、共享可变状态、众多 helper 和隐式全局依赖）仍然太宽，尚未形成可替换、可测试的根 seam。

## 8. 可借鉴与不应照搬清单

### 8.1 直接借鉴

- provider capability matrix、优先级、短期熔断、fallback trace；
- 冻结 `as_of`/目标交易日，整次 run 使用同一时间基准；
- 数据块质量状态和 capability-level degradation；
- idempotent run id、断点续传、缓存与历史 snapshot；
- API 任务去重、SSE、run-flow 和诊断脱敏；
- 结构化 report view model，多语言 label 与 Web 信息层级；
- 过去建议的 outcome evaluation，为模型/规则校准提供闭环；
- 配置原子 upsert、secret mask 和兼容迁移测试。

### 8.2 有条件借鉴

- YAML/SKILL.md：只承载解释框架、检查清单和 narrative policy；若要参与计算，必须编译为 typed rule 并由 validator 拒绝非法规则；
- 多 Agent：只用于并行研究观点，且必须消费同一冻结 EvidenceLedger；不允许各自重新抓取并产生相互矛盾的事实；
- fail-open：研究视图可降级，正式估值/评级仍按 capability 关闭；
- 回测：保留报告 outcome evaluation，另建严谨策略 simulator。

### 8.3 不应照搬

- 一个 `Config` 单例覆盖所有域；
- 一个 fetcher Interface 覆盖所有数据能力；
- constructor 内创建真实依赖；
- legacy LLM 与 Agent 两套端到端路径；
- LLM 直接生成评分、目标点位、仓位和最终动作；
- 把 PE/PB 快照称为完整估值；
- 把 provider 名称当作关键财务数字的充分来源；
- renderer 默认关闭并长期维护第二套字符串报告；
- 用“缺字段后填占位符”替代能力状态和方法禁用。

## 9. 面向本地重构的根 Module 设计

### 9.1 Seam 与目标

建议把外部 seam 放在 `research/application/interface.py`，建立一个根 Module：`ResearchEngine`。CLI、FastAPI、调度器、Bot、测试和未来桌面端都是 caller；它们不再直接调用 Task 1/2/3 skill、validator、数据源或 renderer。

根 Module 只暴露一个入口，最大化 Depth：

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeAlias
from uuid import UUID

ResearchIntent: TypeAlias = (
    SecurityResearchIntent
    | TradePlanIntent
    | PortfolioReviewIntent
    | OutcomeEvaluationIntent
)

@dataclass(frozen=True)
class ResearchRequest:
    run_id: UUID
    as_of: datetime
    intent: ResearchIntent          # discriminated union，不是 dict 参数袋
    policy_profile: str             # 如 formal / exploratory / estimate_overlay
    artifact_profile: str           # 如 web_full / markdown_brief / machine_json
    refresh: RefreshPolicy

class ResearchEngine(Protocol):
    async def execute(self, request: ResearchRequest) -> "ResearchOutcome": ...

@dataclass(frozen=True)
class ResearchOutcome:
    run_id: UUID
    as_of: datetime
    status: RunStatus              # completed | degraded | blocked | failed | cancelled
    capabilities: CapabilityAssessment
    evidence: EvidenceLedger
    result: ResearchResult         # 与 intent 对应的 discriminated union
    artifacts: tuple[ArtifactRef, ...]
    diagnostics: RunDiagnostics
```

进度不作为 `execute` 的第二套返回 Interface。`RunEventPublisher` 在 composition root 注入 engine，按 `run_id` 发布 typed events；CLI Adapter 转成日志，FastAPI Adapter 转 SSE，测试使用 in-memory Adapter。这样调用者只学习一个业务 Interface，同时保留实时 UX。

### 9.2 Interface 的 invariants

1. **时间冻结**：`as_of` 必须带时区；所有 Adapter 只能返回 `observed_at/effective_at <= as_of` 的事实，未来数据触发 `EvidenceRejected`。
2. **幂等**：同一 `run_id + canonical request hash` 重放返回同一 outcome 或安全续跑；同一 run_id 配不同请求直接拒绝。
3. **事实可追溯**：每个 critical fact 必须引用 `source_id`；缺失、估算、fallback、stale 作为一等状态，不能用 0/空字符串伪装。
4. **计算确定性**：估值、技术指标、风险预算、仓位和 capability gate 只能由版本化 in-process Implementation 产生；LLM Adapter 不得写这些字段。
5. **能力级降级**：一个 capability 缺输入只禁用该 capability。`valuation=disabled` 不得阻断 `technical_research=available`；`html=failed` 不得把 research outcome 改成 failed。
6. **方法适用性先于计算**：MethodRouter 先产出 `selected/disabled + reason + required_inputs`，估值 Implementation 只能执行 selected 方法。
7. **策略边界**：默认不输出个性化买卖指令；若 policy 允许 rating，必须满足相应 capability、证据和免责声明条件。
8. **单一 canonical result**：所有 Artifact Adapter 只读 `ResearchOutcome`；HTML、Markdown、JSON、PDF 之间不得各自重算数字。
9. **先持久化后投递**：canonical outcome 与 evidence 成功提交后，才允许 Notification Adapter 对外发送。
10. **Adapter 无业务政策**：Adapter 只做协议/格式/供应商映射，不决定方法、数据门或动作。

### 9.3 Ordering constraints

```text
validate request
  -> freeze subject/as_of/policy
  -> build capability plan + required evidence
  -> collect independent evidence concurrently
  -> normalize/dedupe/reconcile + quality assessment
  -> method routing
  -> deterministic analysis/valuation/risk calculations
  -> optional LLM synthesis over frozen artifacts
  -> policy and safety evaluation
  -> commit canonical outcome + evidence ledger
  -> render artifacts independently
  -> deliver selected artifacts
```

只有 evidence collection 中互不依赖的 port 可以并发。估值不能早于 source reconciliation；LLM 不能早于 deterministic calculations；delivery 不能早于 persistence。Renderer 可并发且独立失败。

### 9.4 Error modes

| Error mode | 根 Module 语义 | 是否继续 |
|---|---|---|
| `RequestRejected` | 标的、as-of、intent 或 policy 非法 | `blocked`，不访问外部源 |
| `ProviderUnavailable/RateLimited/Timeout` | 记录 attempt，按 policy 尝试下一 Adapter | 有 fallback 则继续 |
| `EvidenceMissing/Stale/Conflicting` | 更新 EvidenceLedger 与 capability | 继续可用能力；受影响方法 disabled |
| `MethodNotApplicable` | 正常业务结果，不是异常 | 继续其它方法 |
| `CalculationFailed` | 隔离对应 calculator/version 和 capability | 其它能力继续，诊断必须保留 |
| `ModelUnavailable/InvalidOutput` | narrative 标记 unavailable；确定性结果保留 | 不阻断 valuation/report data |
| `PolicyViolation` | 删除/降级违规字段，保留原因 | 严重时 `blocked`，否则 `degraded` |
| `PersistenceFailed` | canonical outcome 未提交，禁止通知 | `failed` |
| `RendererFailed` | 只标记该 artifact failed | outcome 仍 completed/degraded |
| `DeliveryFailed` | outcome/artifact 保留，允许重投 | 不重跑研究 |
| `Cancelled` | 在 stage safe-point 停止并保存已完成诊断 | `cancelled` |

### 9.5 隐藏在 Implementation 内的复杂度

caller 不需要知道以下内容：provider 顺序、重试/熔断、缓存键、交易日历、字段 reconciliation、source ranking、官方披露解析、数据质量评分、Task 1/2/3 对应关系、估值方法路由、DCF/可比/rNPV/NAV Implementation、prompt、Agent 数量、JSON repair、历史校准、报告模板、通知分片和数据库表。

这正是 Module 的 Depth：一个 `execute()` 让所有入口复用相同行为；修复来源、门控或计算只发生在一个 Locality 内。删除根 Module 后，这些复杂度会重新散落到 CLI/API/scheduler/Bot/test，说明它在做真正工作，而不是 pass-through。

### 9.6 依赖分类、ports 与 Adapters

| 依赖类别 | Module/port | Production Adapters | Test Adapter | Seam 纪律 |
|---|---|---|---|---|
| in-process | MethodRouter、DCF/comps/NAV calculators、technical indicators、risk policy、capability evaluator | 无 Adapter，直接 Implementation | 直接用真实纯函数 | 不制造假 port |
| local-substitutable | `ResearchStorePort`、`ArtifactStorePort` | SQLite/Postgres、filesystem/object store | in-memory SQLite、temp filesystem | seam 保持在 engine 内部，不暴露给 caller |
| true external | `MarketDataPort` | Tushare/TickFlow/AkShare/YFinance | deterministic fake | 至少生产 + fake 两个 Adapter，是真 seam |
| true external | `DisclosurePort` | CNINFO/SSE/SZSE、HKEX、SEC | fixture Adapter | 与通用 SearchPort 分离，维护正式证据语义 |
| true external | `NewsPort` | Tavily/SerpAPI/SearXNG/本地资讯 | fixture Adapter | 只返回候选证据，不升级成官方披露 |
| true external | `ModelPort` | OpenAI-compatible/LiteLLM/local CLI | scripted fake | 只生成 narrative/分类候选，不写 deterministic 字段 |
| true external | `DeliveryPort` | email/Feishu/Slack/file | collecting fake | 放在 persistence 之后，可独立重试 |
| remote but owned（未来） | `RunQueuePort` | HTTP/queue worker Adapter | in-memory Adapter | 只有拆成独立 worker 部署时才引入；当前单进程不要预建 |

遵循“一种 Adapter 只是 hypothetical seam，两种 Adapter 才是真 seam”。例如当前只用 SQLite 时不必先做十层 repository abstraction；但 market/disclosure/model/delivery 天然已有多个 production Adapter 和 test fake，应明确建 port。

### 9.7 Usage

```python
# CLI、API、scheduler 都只负责把输入翻译成同一 Request。
request = ResearchRequest(
    run_id=uuid4(),
    as_of=parse_as_of("2026-07-10T15:00:00+08:00"),
    intent=SecurityResearchIntent(
        subject=EquityId("002897.SZ"),
        requested_capabilities={
            Capability.FUNDAMENTAL_RESEARCH,
            Capability.VALUATION,
            Capability.TECHNICAL_RESEARCH,
            Capability.TRADE_PLAN_RESEARCH_VIEW,
        },
    ),
    policy_profile="estimate_overlay",
    artifact_profile="web_full",
    refresh=RefreshPolicy.PREFER_CACHE_THEN_REFRESH,
)

outcome = await engine.execute(request)

# 调用者检查 capability，而不是猜 Task 1/2/3 是否能走。
if outcome.capabilities.valuation.is_disabled:
    show_missing_inputs(outcome.capabilities.valuation.requirements)
show_artifacts(outcome.artifacts)
```

### 9.8 Trade-offs

- 一个入口提高 Leverage，但 `ResearchIntent/ResearchResult` 的 discriminated union 必须严格版本化，否则会退化成万能 dict。
- typed EvidenceLedger 和 capability state 增加前期 schema 工作，却换来可测试性、跨 renderer 一致性和稳定降级。
- 把 LLM 降为 Adapter 会减少“灵活生成”的自由度，但能把事实、数字和安全政策集中在可验证 Implementation。
- 多 port 会增加 composition root 配置；只对真实变化的外部依赖建 seam，能避免过度抽象。
- 根 Module 内部仍可由多个小 Module 组成；它们是内部 seams，不应为了单元测试全部暴露到外部 Interface。测试应主要穿过 `ResearchEngine.execute()`，用 fake Adapters 覆盖成功、fallback、partial、冲突和失败路径。

## 10. 建议的本地目录落点

```text
src/
  research/
    application/
      interface.py          # ResearchRequest/Outcome/Engine
      engine.py             # 深 Implementation，隐藏 DAG
      capabilities.py
    domain/
      evidence.py
      methods.py
      valuation.py
      trade_plan.py
      diagnostics.py
    policies/
      source_policy.py
      method_router.py
      output_policy.py
    ports/
      market_data.py
      disclosures.py
      news.py
      models.py
      storage.py
      artifacts.py
      delivery.py
  adapters/
    market_data/
    disclosures/
    news/
    models/
    storage/
    artifacts/
    delivery/
  apps/
    cli/
    api/
    scheduler/
```

现有 skills 可以逐步迁移为两类：

- `NarrativeSkill`：只接收 frozen ResearchFacts/Calculations，输出带 schema 的观点草稿；
- `RuleModule`：把真正需要确定性的规则从 Markdown/YAML 提取为 typed Implementation，并通过根 Interface 集成。

最终不再由 skill 串起 Task 1/2/3，而是根 Module 编排；skill 只是内部可选能力。这样既保留扩展性，也把不确定性限制在可降级的 narrative 层。

## 11. 上游提交元数据说明

本地 clone 的 `HEAD` 为 `d08374898c25f4718d61b1779ac4c1fedc9aa9a2`，提交主题是“在决策合成前增加低敏多 Agent 分歧摘要”，该提交一次增加 1,145 行、删除 36 行，涉及 orchestrator、risk override、decision agent 和大量测试。由于首次完整传输超过执行窗口，随后在原 `.git` 上完成 `depth=100` 的 fetch 与 checkout；工作树文件完整，但本研究只把最近 100 个提交（2026-06-18 至 2026-07-10）的历史统计视为本地可证范围，不声称覆盖项目全部历史。

该近期变更本身也印证了两点：项目对 Agent 可解释性和测试投入很高；同时 orchestrator 正处于快速演进，高层 Agent Interface 不适合作为本地估值/风控的稳定根 seam。固定提交链接：[`d083748`](https://github.com/ZhuLinsen/daily_stock_analysis/commit/d08374898c25f4718d61b1779ac4c1fedc9aa9a2)。
