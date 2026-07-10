# TradingAgents v0.3.1 源码审查与本地根 Interface 设计

> 审查对象：TauricResearch/TradingAgents
> 本地只读镜像：<code>.research/upstreams/TradingAgents</code>
> 固定提交：<code>01477f9afb7a47b849ed4c9259d3a9a4738d9fda</code>（tag <code>v0.3.1</code>，提交时间 2026-07-05T14:29:07Z）
> 固定提交链接：[01477f9](https://github.com/TauricResearch/TradingAgents/commit/01477f9afb7a47b849ed4c9259d3a9a4738d9fda)
> 审查日期：2026-07-10
> 证据范围：只使用该固定提交的源码、README、CHANGELOG、测试、CI 配置与 Git 提交元数据；未用项目外二手解读补足结论。

## 结论先行

TradingAgents 是一个已经相当成熟的 **LLM 投研编排脚手架**，不是完整的估值、组合风控或交易执行系统。它最值得借鉴的是确定性数据护栏与运行可靠性：ticker 规范化、instrument identity、无未来行情快照、显式 vendor chain、typed vendor errors、结构化决策、checkpoint 和结果记忆。它最不应照搬的是把“多角色辩论”当成投研方法本身，以及在没有官方披露血缘、确定性估值模型、真实组合状态和风险预算时直接输出 Buy/Sell、目标价、仓位和止损。

最关键的五条判断：

1. **编排完整，方法不完整。** 源码有从分析师到研究经理、交易员、风险辩论、组合经理的闭环，但没有 DCF、可比公司、SOTP、残余收益等可执行估值实现，也没有财务模型校验。
2. **数据可靠性设计值得复用。** 显式 vendor chain、typed errors、NO_DATA sentinel、ticker identity 和 verified market snapshot 是高 leverage 的深 Module 候选。
3. **A 股“能取行情”不等于“能做正式投研”。** README 支持 <code>.SS/.SZ</code>，但实际关键财务 vendor 只有 Yahoo Finance / Alpha Vantage，未见 CNINFO、深交所/上交所公告或公司 IR Adapter，也没有逐字段 source manifest。
4. **风险与交易是结构化语言输出，不是组合风控。** State 没有现金、持仓、成本、组合净值、风险预算或订单状态；仓位、入场、止损、目标价由 LLM 填写，README 所称模拟交易执行在当前源码中没有对应实现。
5. **必须统一运行入口。** 程序化 <code>propagate()</code> 接入 memory/checkpoint/logging，但 CLI 自己初始化 State 并直接 stream graph，绕过了这条路径；这正是本地重构应通过单一根 Interface 消除的路径漂移。

## 1. 当前架构到底是什么

README 把系统描述为真实交易机构角色的多 Agent 映射，并明确列出 Analyst、Bull/Bear Researcher、Trader、Risk Team、Portfolio Manager；源码中的 LangGraph 基本忠实实现了这张组织图。[README.md:60-99](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/README.md#L60-L99)

~~~text
Ticker + as_of date
  -> Market Analyst <-> market tools
  -> Sentiment Analyst
  -> News Analyst <-> news / macro / prediction tools
  -> Fundamentals Analyst <-> fundamental tools
  -> Bull <-> Bear debate
  -> Research Manager
  -> Trader
  -> Aggressive -> Conservative -> Neutral risk debate
  -> Portfolio Manager
  -> final AgentState + 5-tier rating
  -> JSON state log / Markdown report tree / decision memory
~~~

这不是四个分析师并行后汇合，而是按选择顺序串行执行：每个分析师先在 Agent 与 ToolNode 之间循环，清空 messages 后才进入下一个分析师；最后一个分析师结束后才进入 Bull Researcher。[tradingagents/graph/setup.py:61-155](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/graph/setup.py#L61-L155) 执行计划只保存有序的 AnalystNodeSpec 列表，并拒绝未知或空选择。[tradingagents/graph/analyst_execution.py:6-69](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/graph/analyst_execution.py#L6-L69)

### 1.1 Module 盘点

| Module | 当前 Interface / 入口 | Implementation 隐藏的行为 | 判断 |
|---|---|---|---|
| <code>TradingAgentsGraph</code> | 构造器、<code>propagate</code>、<code>save_reports</code> | LLM 创建、tool graph、状态传播、memory、checkpoint、日志 | 行为多，但构造副作用多且返回内部 State，Depth 被削弱 |
| <code>GraphSetup</code> | <code>setup_graph(selected_analysts)</code> | 所有 node 与 edge 装配 | 清晰、可测试，适合内部 Implementation |
| dataflow router | <code>route_to_vendor(method, ...)</code> | vendor 选择、fallback、错误降级 | 当前最深、最值得复用的 Module |
| Agent nodes | 每个 factory 返回一个 State -> delta 函数 | Prompt、工具调用、结构化输出或 free-text fallback | 角色清晰，但投研方法主要埋在 Prompt |
| decision schemas | Pydantic model + Markdown renderer | enum、可选数值、展示格式 | 输出形状稳定，但没有证据约束 |
| checkpointer | ticker/date/graph signature | SQLite LangGraph checkpoint | 机制好，但只在一条运行路径完整接线 |
| memory log | Markdown append/read/update | 5 日收益、alpha、反思注入 | 可作为实验遥测，不足以成为策略验证 |
| reporting | <code>write_report_tree</code> | 分目录 Markdown 与汇总 Markdown | 可复用性提升，但报告能力很浅 |

主类在构造时直接更新全局 dataflow config、创建目录、创建两个 LLM client、memory log、ToolNode 和 graph；这些依赖不是从外部注入的。[tradingagents/graph/trading_graph.py:65-150](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/graph/trading_graph.py#L65-L150) 这让生产使用方便，但测试和替换行为要靠 patch，且 CLI / 程序调用很容易各自重写半套生命周期。

## 2. 功能完整性与可行性

### 2.1 功能矩阵

| 能力 | 完整度 | 源码事实 | 对本地项目的意义 |
|---|---|---|---|
| 多 Agent 工作流 | 高 | LangGraph 覆盖分析、研究、交易、风险、组合决策全流程 | 可借鉴 State machine，不应把角色数量当质量 |
| 行情/技术数据 | 中高 | ticker 规范化、日期过滤、陈旧数据拒绝、verified snapshot | 可作为行情 Adapter 与验证 Implementation |
| 新闻/情绪 | 中 | Yahoo、StockTwits、Reddit、FRED、Polymarket；情绪有 structured confidence | 可做非关键 enrichment，不应提升财报证据等级 |
| 财务数据 | 低到中 | Yahoo / Alpha Vantage overview 与报表，无官方披露 Adapter 和逐数 source_id | 不满足本地正式估值 gate |
| 估值模型 | 缺失 | 没有 DCF/comps/SOTP/NAV/rNPV/残余收益计算 Module | 不能替代本地现有 valuation router 和 model validator |
| 风险管理 | 低 | 三种风险人格辩论，没有量化组合状态与硬约束 | 只能作为 narrative challenge |
| 交易计划 | 低到中 | 有 typed action、entry、stop、position sizing、price target | 形状稳定，但数值和仓位不由确定性规则生成 |
| 订单/回测 | 缺失 | README 说模拟执行；源码无 order/exchange Adapter，backtrader 仅为依赖 | 不可称为可执行交易系统 |
| 恢复/记忆 | 程序路径高、CLI 有缺口 | checkpoint、memory log 实现存在，但 CLI 绕过 <code>propagate</code> | 必须统一根 Interface |
| 报告 | 低 | Markdown 分节与汇总，无 HTML/PDF、图表、source manifest | 只能借鉴“统一 writer”，不能借鉴最终呈现 |
| 自动化测试 | 工程面高、金融面低 | CI + 大量 regression tests；无估值/组合风险正确性测试 | 本地应增加金融 invariants 与 golden cases |

### 2.2 Agents 与 workflow

AgentState 主要由字符串报告、字符串辩论历史与最终字符串决策组成。它记录 ticker、asset type、instrument context、date、四份分析报告、两组辩论 State 和最终决策，但没有 canonical facts、SourceRef、估值模型、组合或订单对象。[tradingagents/agents/utils/agent_states.py:47-76](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/utils/agent_states.py#L47-L76)

这一设计适合演示“不同观点如何接力”，但有三个方法论后果：

- 下游 Agent 读取的是上游 prose，而不是带来源和单位的 typed facts；错误会被辩论放大，而不是被独立重算。
- Bull/Bear 与三类 Risk Agent 使用同一组四份报告，没有独立证据池；多角色不能构成多源交叉验证。
- 辩论轮数只控制字符串往返次数，不能证明新增信息、独立性或收敛。路由仅按 count 和 speaker label 转移。[tradingagents/graph/conditional_logic.py:52-73](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/graph/conditional_logic.py#L52-L73)

Fundamentals Analyst 的 Prompt 要求“尽可能详细”和“actionable insights”，但它可用的只有 overview、资产负债表、现金流和利润表工具；没有估值方法路由、会计口径 reconciliation 或 source manifest。[tradingagents/agents/analysts/fundamentals_analyst.py:13-67](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/analysts/fundamentals_analyst.py#L13-L67)

正面例子是 Sentiment Analyst：项目发现“Prompt 要求社媒、工具却只有新闻”会诱发模型捏造，随后改为调用 LLM 前预取 news、StockTwits、Reddit，并用结构化 band / score / confidence 输出。[tradingagents/agents/analysts/sentiment_analyst.py:1-80](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/analysts/sentiment_analyst.py#L1-L80) 这说明最有效的修复不是增加 Prompt 警告，而是把不确定数据获取移出 LLM。

### 2.3 State、checkpoint 与 memory

程序化路径的生命周期相对完整：

1. <code>propagate</code> 先 resolve pending memory；
2. 如启用 checkpoint，则以 ticker 创建 SQLite saver；
3. checkpoint key 包含 ticker、date、selected analysts、debate depth、risk depth、asset type；
4. 运行完成后写 full state JSON、写 decision memory、清理成功 checkpoint；
5. 返回 <code>(final_state, parsed_rating)</code>。

证据见 [tradingagents/graph/trading_graph.py:348-482](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/graph/trading_graph.py#L348-L482) 与 [tradingagents/graph/checkpointer.py:28-98](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/graph/checkpointer.py#L28-L98)。

Memory log 把决策先记为 pending，后续同 ticker 运行时计算持有期收益和相对 benchmark alpha，生成一段反思，再把近期同 ticker 与跨 ticker lesson 注入 Portfolio Manager。[tradingagents/agents/utils/memory.py:30-95](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/utils/memory.py#L30-L95) [tradingagents/agents/utils/memory.py:99-216](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/utils/memory.py#L99-L216)

这套机制可借鉴为“可恢复运行 + outcome telemetry”，但不能视作策略学习证明：

- 固定 5 个交易日的 raw/alpha return 不是适合所有 thesis horizon 的评价函数；
- 没有交易成本、滑点、成交、风险调整收益或样本外检验；
- LLM 反思仍是自由文本，无法证明因果。

#### 关键缺陷：CLI 与程序化路径漂移

README 宣称 decision log 始终开启，CLI 的 <code>--checkpoint</code> 可以恢复中断任务。[README.md:244-269](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/README.md#L244-L269)

但当前 CLI：

- 构造 <code>TradingAgentsGraph</code> 后，自己创建 results/log/report 目录；
- 自己调用 <code>resolve_instrument_context</code> 和 <code>propagator.create_initial_state</code>；
- 直接 <code>graph.graph.stream(...)</code>；
- 没有调用 <code>propagate</code>、<code>_resolve_pending_entries</code>、<code>memory_log.get_past_context</code>、<code>store_decision</code>、<code>_log_state</code>，也没有按 signature 重编译 checkpointer。

证据见 [cli/main.py:997-1120](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/cli/main.py#L997-L1120) 与 [cli/main.py:1219-1267](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/cli/main.py#L1219-L1267)。CLI checkpoint 测试只验证 config precedence，没有覆盖“CLI crash 后实际恢复”。[tests/test_cli_config_precedence.py:57-69](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_cli_config_precedence.py#L57-L69)

这是源码对照后的推断，不是运行时抓包结论；但静态调用链已经足以说明两条入口不共享同一完整 Implementation。

### 2.4 Data vendors、数据质量与 as-of

默认 vendor 配置是：

- core stock / technical / fundamentals / news：yfinance；
- macro：FRED；
- prediction markets：Polymarket；
- 可显式切到 Alpha Vantage 或按顺序配置 fallback。

配置强调“配置列表就是精确链，不暗中切到未选择 vendor”。[tradingagents/default_config.py:128-163](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/default_config.py#L128-L163)

router 的设计很好：

- 工具先映射到 data category；
- tool-level vendor 覆盖 category-level vendor；
- 只在用户显式链内 fallback；
- rate limit、not configured、no data 有不同反应；
- 核心数据最终错误会抛出，macro/prediction 作为 optional enrichment 降级；
- 所有 vendor 无数据时返回明确 NO_DATA sentinel，并要求不要估算或捏造。

证据见 [tradingagents/dataflows/interface.py:35-144](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/interface.py#L35-L144) 与 [tradingagents/dataflows/interface.py:146-262](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/interface.py#L146-L262)。typed error 的数量按“router 需要采取几种不同反应”设计，而不是按 vendor 数量扩张，这是很好的 Error Taxonomy。[tradingagents/dataflows/errors.py:1-55](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/errors.py#L1-L55)

行情质量也有确定性护栏。verified snapshot 重新排除 as-of 之后的行，计算固定技术指标集合，输出最新 OHLCV、指标与近期收盘，并明确要求模型以它为精确数值真值。[tradingagents/dataflows/market_data_validator.py:1-123](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/market_data_validator.py#L1-L123) 新闻窗口同样排除历史运行中的未来或无日期文章。[tradingagents/dataflows/yfinance_news.py:60-128](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/yfinance_news.py#L60-L128)

但财务数据不满足正式估值要求：

- vendor registry 只有 yfinance / alpha_vantage / FRED / Polymarket，没有官方披露 Adapter；
- yfinance overview 的 <code>curr_date</code> 明确“not used”，返回的是调用时 info，包括 forward PE/EPS、TTM、52 周值等当前快照，不是历史 as-of snapshot；输出只有 retrieval timestamp，没有 source URL、filing id、发布日期、币种和口径。[tradingagents/dataflows/y_finance.py:274-338](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/y_finance.py#L274-L338)
- 报表过滤依据 fiscal period end date，而不是 disclosure available_at；历史运行可能看到当时尚未披露、后来修订或重述的数据。[tradingagents/dataflows/stockstats_utils.py:195-206](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/stockstats_utils.py#L195-L206)
- Alpha Vantage 报表也只按 <code>fiscalDateEnding <= curr_date</code> 过滤；overview 不过滤。[tradingagents/dataflows/alpha_vantage_fundamentals.py:6-63](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/dataflows/alpha_vantage_fundamentals.py#L6-L63)

因此对意华股份 <code>002897.SZ</code>，TradingAgents 可作为行情、技术、部分新闻/情绪的 Adapter 参考，但不能作为关键财务、估值和正式结论的唯一来源。README 对 A 股的承诺只是“Yahoo 覆盖的市场 ticker 可运行”。[README.md:180-188](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/README.md#L180-L188)

### 2.5 估值方法：源码中基本缺失

README 说 Fundamentals Analyst 识别 intrinsic value，但当前实现没有任何确定性估值 Module。[README.md:70-76](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/README.md#L70-L76)

在固定提交的 <code>tradingagents/</code> 与 <code>tests/</code> 中搜索 DCF、WACC、terminal value、comparable valuation、EV/EBITDA、SOTP、NAV、residual income，未找到相应计算 Implementation 或金融正确性测试。现有“model validation”测试实际验证的是 LLM provider/model catalog，不是财务模型。[tests/test_model_validation.py:1-54](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_model_validation.py#L1-L54)

唯一接近估值输出的是 LLM schema：

- Trader 可填 entry price、stop loss、position sizing；
- Portfolio Manager 可填 price target、time horizon；
- 这些数值是 optional float/string，没有公式、输入血缘、单位/币种约束、估值方法、敏感性或 reconciliation。

见 [tradingagents/agents/schemas.py:121-180](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/schemas.py#L121-L180) 与 [tradingagents/agents/schemas.py:188-250](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/schemas.py#L188-L250)。

所以 TradingAgents 不能解决本地项目的 DCF、估值路由和模型完整性问题；反过来，本地已经存在的 source manifest、valuation method router、DCF applicability、model validator 才应成为确定性 Implementation，Agent 只能消费其结果。

### 2.6 Risk、trading decision 与 execution

Research Manager、Trader、Portfolio Manager 使用 Pydantic structured output，这是好设计：它把 rating/action 字段限制在 enum 中，避免不同 provider 任意改标题。[tradingagents/agents/schemas.py:39-113](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/schemas.py#L39-L113)

但 structured invocation 失败后会直接退化到 free text，以“不要阻塞 pipeline”为最高优先级。[tradingagents/agents/utils/structured.py:49-79](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/utils/structured.py#L49-L79) 随后的 rating parser 如果没有识别到 rating，默认返回 Hold。[tradingagents/agents/utils/rating.py:28-46](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/utils/rating.py#L28-L46) 对正式系统，这是危险的 silent default：解析失败不应被解释为有证据支持的 Hold，应成为 <code>DecisionUnavailable</code> 或 degraded result。

三位 Risk Agent 本质是不同风险偏好的 Prompt persona；输入仍是四份报告和 Trader prose，没有组合状态或量化风险对象。[tradingagents/agents/risk_mgmt/aggressive_debator.py:7-57](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/risk_mgmt/aggressive_debator.py#L7-L57) [tradingagents/agents/risk_mgmt/conservative_debator.py:7-59](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/risk_mgmt/conservative_debator.py#L7-L59) [tradingagents/agents/risk_mgmt/neutral_debator.py:7-57](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/agents/risk_mgmt/neutral_debator.py#L7-L57)

缺失的硬约束包括：

- 当前持仓、成本、现金、组合净值；
- 单票/行业/因子暴露；
- 最大仓位、最大回撤、风险预算；
- 波动率或流动性驱动的确定性仓位公式；
- 订单类型、滑点、费用、成交与拒单状态；
- pre-trade / post-trade compliance。

README 说获批订单会送到模拟交易所执行。[README.md:96-99](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/README.md#L96-L99) 但固定提交源码中没有 order/exchange Adapter 或 backtrader import；<code>backtrader</code> 只出现在依赖声明。[pyproject.toml:11-34](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/pyproject.toml#L11-L34) 因而当前实际终点是 Markdown 决策，不是模拟成交。

### 2.7 报告与呈现

共享 report writer 是一个正向重构：CLI 和程序调用可以复用同一 writer。它按 analysts/research/trading/risk/portfolio 分目录写 Markdown，并拼出 <code>complete_report.md</code>。[tradingagents/reporting.py:1-100](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tradingagents/reporting.py#L1-L100)

但它没有：

- canonical report model；
- source/citation register；
- HTML/PDF；
- 图表、表格模型或交互数据；
- 报告级数字 cross-check；
- 版式 QA、分页、打印样式或无障碍；
- artifact manifest 与 hash。

因此本地 HTML 报告不应从 TradingAgents 的 Markdown 拼接扩展，而应从 validated canonical research result 渲染多个 Adapter：HTML、PDF、JSON 和可选 Excel。报告失败不应使已完成的研究计算失效。

### 2.8 Testing

固定提交有 51 个 <code>test_*.py</code> 文件；按静态函数定义统计为 435 个 test functions。CI 在 Python 3.10-3.13 跑 pytest，另有 clean-install smoke 和全仓 strict ruff。[.github/workflows/ci.yml:12-61](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/.github/workflows/ci.yml#L12-L61) Pytest marker 和 lint 规则集中在 pyproject。[pyproject.toml:36-87](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/pyproject.toml#L36-L87)

测试最强的部分是近期工程回归：

- vendor chain 不得越过配置、optional data 应降级、核心错误应暴露；[tests/test_vendor_routing.py:43-119](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_vendor_routing.py#L43-L119)
- 空行情不能污染 cache 或诱发捏造；[tests/test_no_data_handling.py:22-84](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_no_data_handling.py#L22-L84)
- 历史运行排除未来新闻；[tests/test_news_lookahead.py:19-78](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_news_lookahead.py#L19-L78)
- verified snapshot 排除未来行情；[tests/test_market_data_validator.py:24-76](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_market_data_validator.py#L24-L76)
- checkpoint 的低层 crash/resume 与 graph signature；[tests/test_checkpoint_resume.py:45-105](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_checkpoint_resume.py#L45-L105) [tests/test_checkpoint_resume.py:143-214](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_checkpoint_resume.py#L143-L214)
- structured agents 与 free-text fallback；[tests/test_structured_agents.py:180-285](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_structured_agents.py#L180-L285)
- report tree 文件是否生成。[tests/test_reporting.py:22-50](https://github.com/TauricResearch/TradingAgents/blob/01477f9afb7a47b849ed4c9259d3a9a4738d9fda/tests/test_reporting.py#L22-L50)

缺口同样明确：没有 DCF 公式、估值方法路由、财务报表 reconciliation、组合风险、仓位、交易成本、订单执行、报告数字血缘或 CLI 完整生命周期测试。

本地尝试运行 <code>python -m pytest -q -p no:cacheprovider</code> 时，当前机器只有默认 Python 3.14，且未安装 yfinance、questionary、langchain_openai 等项目依赖，collection 阶段即失败；3.14 也超出上游 CI matrix。这个结果只说明本地未创建专用依赖环境，不计作上游测试失败。运行前后 clone 保持 clean，且未生成 pycache/pytest cache。

## 3. 可借鉴与不应照搬

### 3.1 建议直接吸收的设计

| 设计 | 为什么有 leverage | 本地落点 |
|---|---|---|
| 显式 vendor chain | 调用者知道真实来源顺序，不会被隐式 fallback 改变口径 | internal Evidence Adapter registry |
| typed vendor errors | 错误类型按系统反应分类，新增 vendor 不扩张 catch 分支 | <code>NoEvidence</code> / <code>RateLimited</code> / <code>NotConfigured</code> / <code>Conflict</code> |
| ticker normalization + identity | 防止分析错公司、错交易所、错 instrument | Run 启动时固定 InstrumentIdentity |
| verified as-of snapshot | LLM 不负责精确数值真值 | MarketSnapshot 与 FinancialSnapshot 均由确定性 Implementation 产生 |
| graph-shape-aware checkpoint | 改配置后不会误续旧 State | checkpoint fingerprint 包含 policy、method profile、schema version、adapter versions |
| structured output + renderer | 机器可读与人读报告可并存 | canonical ResearchResult -> HTML/PDF/JSON Adapter |
| optional enrichment 降级 | FRED/情绪失败不应阻塞核心研究 | capability-level gate，而不是全局 Task 1 pass/fail |
| outcome memory | 可积累审计与后验结果 | 作为 experiment log；不能自动升级为策略证据 |

### 3.2 明确不要照搬

| 不应照搬 | 原因 |
|---|---|
| 以 Agent 角色作为顶层代码结构 | 角色是可变 Prompt 策略，不是稳定领域模型 |
| 所有中间产物都是 prose | 无法做 source lineage、单位、币种、口径和公式校验 |
| CLI/API 各自驱动 graph | 生命周期行为漂移，checkpoint/memory/report 不一致 |
| 关键财务依赖 Yahoo/Alpha Vantage | 不满足 A 股官方披露与正式估值要求 |
| structured 失败就 free-text，再默认 Hold | 把解析失败伪装成有效决策 |
| Risk persona 代替硬风险约束 | 没有组合、风险预算和 deterministic position sizing |
| optional target/entry/stop 由 LLM直接填 | 容易产生无来源的 false precision |
| Markdown 拼接作为最终报告模型 | 难以实现高质量 HTML/PDF、图表与自动 cross-check |
| 多轮 debate 作为研究深度旋钮 | 轮数增加 token，不保证新证据或正确性 |

## 4. 面向本地 equity research 的根 Interface

### 4.1 设计目标

根 Module 名为 <code>EquityResearch</code>。外部 Seam 放在建议路径 <code>src/equity_research/interface.py</code>；CLI、未来 Web、测试和批处理只能跨这一个 Seam。它的 Interface 只有三个入口，Task 1/2/3、skills、validators、数据源、LLM、估值与渲染全部隐藏在 Implementation 内。

这里的 Depth 来自：调用者只学习 start / advance / inspect，就能获得来源收集、渐进式门禁、方法路由、确定性估值、研究合成、交易情景、恢复和多格式报告。删除这个 Module，复杂度会重新扩散到 CLI、Web、批处理和测试，符合 deletion test。

### 4.2 Interface

~~~python
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol

RunStatus = Literal[
    "running",
    "needs_evidence",
    "degraded_complete",
    "complete",
    "failed",
]

Depth = Literal["exploratory", "decision_support", "full_model"]
EstimatePolicy = Literal["none", "scenario_only", "tagged_noncritical"]
OutputKind = Literal["json", "html", "pdf", "xlsx"]

@dataclass(frozen=True)
class ResearchRequest:
    request_id: str
    ticker: str
    as_of: date
    depth: Depth = "decision_support"
    outputs: tuple[OutputKind, ...] = ("json", "html")
    rating_requested: bool = False
    estimate_policy: EstimatePolicy = "scenario_only"

@dataclass(frozen=True)
class EvidenceSupplement:
    files: tuple[Path, ...] = ()
    source_urls: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    status: RunStatus
    instrument: "InstrumentIdentity"
    data_quality_grade: str
    allowed_outputs: tuple[str, ...]
    blocked_outputs: tuple[str, ...]
    evidence_gaps: tuple["EvidenceGap", ...]
    artifacts: "ArtifactBundle"
    next_action: "NextAction | None"

class EquityResearch(Protocol):
    def start(self, request: ResearchRequest) -> ResearchRun: ...

    def advance(
        self,
        run_id: str,
        supplement: EvidenceSupplement | None = None,
    ) -> ResearchRun: ...

    def inspect(self, run_id: str) -> ResearchRun: ...
~~~

依赖在 composition root 一次性注入 Implementation；不让每个调用者在每次 start 时传 vendor、LLM、store 或 renderer。测试使用 in-memory / fixture Adapters，生产使用真实 Adapters。

### 4.3 Usage

~~~python
run = engine.start(
    ResearchRequest(
        request_id="002897-20260710-full",
        ticker="002897.SZ",
        as_of=date(2026, 7, 10),
        depth="full_model",
        outputs=("json", "html", "pdf", "xlsx"),
        rating_requested=True,
        estimate_policy="scenario_only",
    )
)

if run.status == "needs_evidence":
    run = engine.advance(
        run.run_id,
        EvidenceSupplement(
            files=(
                Path("意华股份_2025年报.pdf"),
                Path("意华股份_2026一季报.pdf"),
            )
        ),
    )

assert run.artifacts.json is not None
~~~

调用者不需要知道当前处在 Task 1、Task 2 还是 Task 3，也不需要手工运行 validator 或读回 JSON。<code>needs_evidence</code> 是可恢复结果，不是异常；补充数据后 <code>advance</code> 从稳定 checkpoint 继续。

### 4.4 Invariants

1. **Instrument invariant**：run 创建后 ticker、exchange、currency、accounting standard 与 as_of 不可变；变化必须新建 run。
2. **As-of invariant**：每条 Evidence 都必须有 <code>period_end</code> 与 <code>available_at</code>；<code>available_at > as_of</code> 的数据不得进入历史分析。
3. **Lineage invariant**：每个 critical fact 必须引用 SourceRef，或明确标记 missing / estimate；prose 不能成为事实源。
4. **Estimate invariant**：估算永远不能提升 official-source coverage，也不能把 <code>needs_evidence</code> 变成 formal valuation ready。估算只进入单独的 scenario overlay。
5. **Capability invariant**：门禁按输出能力计算，而不是全局二元 pass/fail。缺少 DCF 输入只阻止 DCF/目标价，不阻止业务、风险、行情与数据缺口报告。
6. **Method invariant**：valuation method router 必须先于任何估值计算；DCF 只有 allowed / documented caution 才能创建结果。
7. **Calculation invariant**：估值、敏感性、仓位区间、收益风险比由确定性 Implementation 计算；LLM 只能解释。
8. **Decision invariant**：rating 仅在用户明确请求、数据/方法/model/policy gates 全部通过时出现；解析失败绝不默认 Hold。
9. **Safety invariant**：不接收或执行真实订单；输出是非个性化研究与条件式 trade setup，始终保留非投资建议声明。
10. **Artifact invariant**：HTML/PDF/XLSX 都从同一个 canonical ResearchResult 渲染；不同格式的数字必须一致。
11. **Idempotency invariant**：相同 request_id 与相同 fingerprint 重试不创建重复 run 或重复副作用。
12. **Resume invariant**：checkpoint fingerprint 至少包含 schema version、instrument、as_of、depth、policy、selected methods 和 Adapter data version。

### 4.5 Ordering constraints（由 Implementation 执行，调用者不可重排）

~~~text
1. Resolve InstrumentIdentity
2. Freeze RunPolicy + as_of + fingerprint
3. Collect evidence in parallel
4. Normalize to canonical facts + SourceRef
5. Validate conflicts, freshness, units, currencies, accounting periods
6. Build CapabilityMatrix
7. Route eligible valuation methods
8. Run deterministic financial model / valuation / scenarios
9. Run optional LLM synthesis and adversarial review over canonical facts
10. Apply policy gate to valuation view / rating / conditional trade setup
11. Render canonical result to requested artifacts
12. Run artifact QA and persist immutable manifest
~~~

LLM debate 放在计算之后，不能放在事实规范化和方法路由之前。报告渲染是最后一步；renderer 失败只标记 <code>RenderFailed</code>，不得丢弃已验证的 JSON/XLSX 结果。

### 4.6 从“Task 1 失败”改为 CapabilityMatrix

当前本地流程的问题不是安全 gate 本身，而是把所有输出绑在一个全局 gate 上。新 Implementation 应分别判定：

| Capability | 最低证据要求 | 缺失时 |
|---|---|---|
| company / industry research | 官方业务描述或明确降级的 secondary evidence | 输出 partial research + gaps |
| technical view | verified as-of OHLCV snapshot | 只禁用 technical section |
| financial quality view | 官方报表 + period/currency/accounting normalization | 禁用财务结论，保留非财务研究 |
| comps valuation | 至少 3 个可比、同口径、同币种或已转换、关键值有 SourceRef | 禁用 comps，不阻塞其他方法 |
| DCF | applicability 通过，FCFF/WACC/g/equity bridge 输入齐全且可追溯 | DCF disabled；不强迫整个 run 失败 |
| valuation range | 至少一个适用且通过验证的方法；正式结论按本地政策可要求两个方法交叉 | 输出 valuation unavailable 或 research view |
| rating | 用户明确请求 + source/model/report gates + policy gate | rating null |
| conditional trade setup | verified price/volatility/liquidity + 非个性化策略规则 | 输出 invalidation/catalyst watchlist，不输出仓位指令 |

这样意华股份即使暂时缺少部分一致预期或某个 DCF 输入，也能先得到完整的业务、风险、技术、数据质量与“哪些估值方法当前可用”的报告；只有被缺失输入直接依赖的 capability 被禁用。

### 4.7 Error modes

| Error mode | Interface 表现 | 是否可恢复 |
|---|---|---|
| <code>InvalidRequest</code> | <code>start</code> 抛 typed error | 否，修正请求 |
| <code>InstrumentAmbiguous</code> | <code>needs_evidence</code> + identity choice | 是 |
| <code>SourceUnavailable</code> | gap + retry hint；核心能力按依赖降级 | 是 |
| <code>EvidenceInsufficient</code> | <code>needs_evidence</code> 或 <code>degraded_complete</code>，不是异常 | 是 |
| <code>EvidenceConflict</code> | 冲突 facts 都保留，阻止依赖能力 | 是，补充官方证据 |
| <code>MethodInapplicable</code> | method disabled + reason | 正常终态 |
| <code>CalculationInvalid</code> | 依赖能力 blocked，保存 validation issues | 可修复输入/公式 |
| <code>PolicyDenied</code> | rating/target/trade fields 为 null，给出 policy reason | 正常终态 |
| <code>ProviderTransient</code> | run 保持可 resume，带 retry_after | 是 |
| <code>RenderFailed</code> | canonical artifacts 保留，只缺失败格式 | 是 |
| <code>InternalInvariantViolation</code> | <code>failed</code>，保存审计 trace，不输出结论 | 否，代码缺陷 |

### 4.8 Interface 后隐藏的 Implementation

建议结构只表达 seam 和 locality，不要求一次性全部落地：

~~~text
src/equity_research/
  interface.py                 # 唯一外部 Seam：start / advance / inspect
  engine/
    run_engine.py              # 状态机、checkpoint、idempotency
    capability_matrix.py       # 按输出能力渐进式 gate
    canonical_result.py        # 稳定 ResearchResult
  evidence/
    schema.py                  # Fact, SourceRef, available_at, quality
    normalize.py               # units/currency/period/accounting
    reconcile.py               # conflict and precedence
  valuation/
    router.py
    dcf.py
    comps.py
    industry_methods.py
    sensitivity.py
  decision_support/
    risk_rules.py              # 确定性风险与 trade setup
    synthesis.py               # LLM 只解释 validated result
  rendering/
    view_model.py
    artifact_qa.py
  adapters/
    disclosures/
    market_data/
    news/
    llm/
    stores/
    renderers/
~~~

现有 skills 不再承担顶层 orchestration。它们可以作为 Synthesis / Renderer 内部的版本化 Prompt 与模板资源；现有 source manifest validator、model validator、report validator、valuation method router 移到 Implementation 内，由 RunEngine 自动调用并把结果写入 canonical ResearchResult。

### 4.9 Dependencies 与 Adapters

按 codebase-design 的 dependency categories：

| 依赖 | 分类 | Seam / Adapter 策略 |
|---|---|---|
| method router、DCF/comps/行业模型、capability matrix、policy | in-process | 直接作为 Implementation；不为只有一个实现的纯计算凭空造 port |
| RunStore / ArtifactStore | local-substitutable | filesystem/SQLite Adapter + in-memory test Adapter |
| HTML/PDF/XLSX renderer | local-substitutable | production renderer + deterministic fixture renderer；内部 Seam |
| 官方披露 | true external | DisclosurePort；CNINFO/SZSE、SSE、HKEX、SEC/IR Adapters + recorded fixture Adapter |
| 行情 | true external | MarketDataPort；Yahoo/Alpha Vantage/其他实际 vendor Adapters + fixture Adapter |
| 新闻/情绪 | true external | NewsPort；明确标为 enrichment，失败不升级核心 error |
| LLM | true external | LLMPort；生产 provider Adapter + deterministic fake Adapter |
| Clock | local-substitutable | system clock + fixed clock，确保 as-of tests |
| 未来自建远程研究后端 | remote but owned | 只有真正出现第二个 deployment Adapter 时再建立 port；当前不要提前分布式化 |

这些都是内部 seams；根 Interface 不暴露 vendor 名称或 Agent 节点。遵守“一种 Adapter 只是臆想 seam，两种 Adapter 才是真 seam”：纯计算不为了 mock 而抽象，真实外部依赖则至少有 production 与 fixture 两个 Adapter。

### 4.10 Test surface

根 Interface 同时是主验收 test surface：

1. <code>start</code> 对完整 fixture 产生 complete、canonical JSON 与一致的 HTML/PDF/XLSX；
2. 缺少非关键数据时仍 degraded complete，不全局阻塞；
3. 缺少官方财务时只屏蔽估值/rating，不屏蔽公司与行情研究；
4. <code>advance</code> 补充文件后只重算受影响的 downstream capabilities；
5. 同 request_id 重试不重复写 artifact 或 memory；
6. renderer 崩溃后 canonical result 仍可 inspect，修复后 advance 只重渲染；
7. 历史 as-of 不读取 available_at 之后的报表、新闻或行情；
8. DCF 在 WACC <= g、FCFF/equity bridge 缺项或行业禁用时不会生成；
9. 结构化 decision 解析失败返回 unavailable，绝不默认为 Hold；
10. CLI、程序调用与 Web 的 contract tests 都只能通过同一个 EquityResearch Interface。

Adapter contract tests 验证 normalized Evidence；估值数学用 deterministic golden fixtures 和 property tests。已有浅 Module tests 在根 Interface 覆盖建立后应替换而不是叠加，避免内部重构导致大面积无价值测试修改。

### 4.11 Trade-offs

- **更高 Depth，更多内部复杂度。** RunEngine 会比单个 skill 大，但复杂度集中，CLI/Web/测试获得更高 leverage 与 locality。
- **canonical schema 有前期成本。** 需要定义 Fact、SourceRef、available_at、currency 和 accounting period；这是消除 prose 传值和 false precision 的必要成本。
- **渐进式 gate 更实用，也更容易被误读。** 每个 artifact 必须显著展示 data quality 与 blocked capabilities，避免用户把 partial research 当正式估值。
- **确定性模型降低表面“灵活性”。** 但公式、口径和敏感性可验证；LLM 仍可在计算后解释和挑战假设。
- **三入口不暴露 phase。** 调用者更简单，但调试需要 inspect 返回足够的审计事件；这些事件不能泄露可变的内部 AgentState contract。
- **不直接执行交易。** 牺牲“一站式下单”叙事，换来清晰的研究边界和可审计性；若未来增加模拟执行，应另建 Portfolio/Execution Module，而不是塞进 EquityResearch。

## 5. 意华股份测试应验证什么

TradingAgents 本身不应被当成意华股份的正式估值基线；它更适合作为以下重构验收的对照：

1. 输入 <code>002897.SZ</code> 后 deterministic identity 不得漂移到其他公司，所有 Adapter 保留交易所后缀。
2. as-of 2026-07-10 的行情、新闻和财报只允许使用当时可获得数据；财报按公告 available_at，而非仅按 fiscal period end。
3. Yahoo 行情可用但 CNINFO/深交所正式财报缺失时，technical capability 可完成，formal valuation/rating 必须 blocked。
4. 补充官方年报/季报后 <code>advance</code> 从 needs_evidence 继续，不要求用户重跑“Task 1”或重新生成已有行情。
5. method router 根据行业和数据可用性选择方法；DCF 不是 full_model 的默认必选项。
6. scenario estimates 保持独立标签，不改变 source coverage 和 data quality grade。
7. rating_requested 为 true 也不等于必然输出 rating；只有 gates 全过才允许。
8. HTML 至少包含 source register、关键财务/估值表、场景矩阵、风险/催化剂、价格与估值图、data quality badge；PDF/XLSX 数字与 canonical JSON 一致。
9. 任一缺口都落到具体 capability、required evidence 与 next action，不能只返回笼统“Task 1 failed”。

## 6. 对本地重构的最终建议

把 TradingAgents 当作“运行可靠性与 Agent 编排参考”，不要当作“估值和交易方法论参考”。本地重构的优先顺序应是：

1. 先建立唯一 <code>EquityResearch</code> 根 Interface 与持久化 Run state；
2. 把 source manifest 从最终 gate 文档提升为 canonical Evidence/Fact 模型；
3. 用 CapabilityMatrix 替代 Task 1 全局 pass/fail；
4. 把 valuation router、DCF applicability、model/report validators 收入确定性 Implementation；
5. 让 skills 退回内部 Prompt/模板角色；
6. 让 CLI、未来 Web 与批处理共享同一 start/advance/inspect；
7. 最后接 HTML/PDF/XLSX Renderer 与视觉 QA；
8. 用意华股份 fixture 同时测试“数据齐全”和“官方数据缺失但可降级”两条路径。

这会保留本地项目已有的金融安全与方法路由优势，同时吸收 TradingAgents 真正成熟的部分：显式数据路由、确定性验证、typed errors、checkpoint、结构化结果和可恢复执行。
