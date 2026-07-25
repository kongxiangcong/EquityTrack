# 资格化 MarketRegime v2 的数据与最小组件

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01, 03

## Question

基于当前 Tushare-compatible 网关、官方/聚合来源边界和既有 MarketSnapshot 实现，决定第一版回答“当前市场对哪类投资逻辑更友好”最少需要哪些可解释组件。必须复验趋势、宽度、流动性、波动率、行业轮动和资金相关候选的接口权限、字段、单位、时间、横截面覆盖、历史分布、缓存与失败语义；宏观、新闻、情绪、拥挤度若不能可靠进入本切片，应给出明确降级而不是黑箱热度分。

## Current canonical baseline

- 这是未来数据资格研究，不得把候选指标写成已实现。每个候选数据集必须落到实际的 [`SourcePolicy@1`、typed query 与 `DataProvider`](../../../src/trading_platform/domain/data.py)，经 [`DataSynchronization`](../../../src/trading_platform/application/cli_tasks.py) 进入 frozen snapshot；CLI/Web 不得直连端点。
- A 股结构化行情与 CNINFO/SZSE official disclosure 的当前角色、authority、PIT/freshness/quality 和失败状态以 [adoption Issue 13](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md) 的 production/live evidence 为基线。SSE、BSE 与公司正式 IR ingestion 仍是 future/unavailable；空、部分、过期、身份冲突、schema drift、source-rights 不足或尚未实现的 official source 都必须保持 unknown/blocked，不能推导为“无事件”或零。
- MarketRegime 的未来输出只可作为 `ResearchEvaluationPlan@1`/计划指标的冻结输入；研究执行仍由 application `ResearchWorkflow` 管理 `ResearchWorkflowRequest@2` lifecycle 并经 `WorkflowLedger` 持久化，用户可见研究证据只来自 `ResearchDecisionView@2`。实现版本和生产 browser/PDF/workbook acceptance 见 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。
- `StrategyValidation` capability 保持 unavailable：未请求为 `not_requested`，显式选择时为非阻断 `requested_unavailable` + `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`。它不属于 MarketRegime 最小组件，也不要求 Vibe-Trading、回测、broker、order、自动交易或盘中做 T。

## Answer

MarketRegime v2 的最小可解释目标包锁定为四个互补组件，不合成为黑箱总分：

- `market.trend`：固定 A 股-only benchmark `930903.CSI` 中证 A 股指数的 SMA20/SMA60 与 5 日斜率，点位单位为 `index_point`，输出 `up/down/mixed`；
- `market.breadth`：每个 session 当时 `930903.CSI` PIT 成分的上涨比例与站上 SMA20 比例；official methodology 的样本空间只含 SSE/SZSE/BSE A 股并排除 ST/*ST，runtime 仍以 typed `instrument_type=A_SHARE` fail closed，输出 `broad/narrow/mixed`；
- `market.liquidity`：对每个历史 session 的同一 A 股 PIT 横截面汇总千元人民币成交额，再把当前 session 总额与此前 120–252 个完整 session 总额比较 percentile，输出 `ample/normal/thin`；121-session 门槛约束聚合序列，不要求每个新纳入成员拥有 121 日自身历史；
- `market.volatility`：固定 `930903.CSI` 的 20 日已实现波动率相对历史 percentile，输出 `high/normal/low`。

完整字段、单位、时间、覆盖、历史窗口、freshness、cache、typed failure 与 live probe 证据见 [MarketRegime v2 数据资格与最小组件决定](../research/market-regime-v2-data-qualification.md)。

`blocked_data_qualification` 是本票的 planning disposition，不是现有 runtime status；当前 runtime 只有 `SnapshotStatus=blocked|limited|complete` 和 component reason codes。现有实现只证明四组件的确定性算法与 fail-closed，而且用一个静态 universe tuple 计算历史流动性，尚未满足 per-session PIT A 股 population。当前 `DailyOhlcvQuery` 和 `SecurityMasterQuery` 都是单证券 identity，2026-07-25 receipt 也只证明 8 个日历记录、1 个 universe 成员与 5 个单证券日线。后续实现必须新增 `930903.CSI` index、per-session constituent membership、typed A 股 identity 与 cross-section queries，经 `SourcePolicy@1`/`DataProvider`/`WorkflowLedger` 唯一路径取得 identity-bound receipt；control-plane 的 `index_member(930903.CSI)` legal-empty 不能被解释为“无成分”，因此 membership 仍 blocked。缺历史、缺覆盖、stale、partial、schema drift、身份/单位冲突或 transport/权限失败均保留 blocked/unknown，空值不转为零。

行业轮动、资金流、宏观、新闻、情绪和拥挤度不进入第一版。只读协议 probe 已证明 SW2021 分类/成员/行业日线以及 `moneyflow`/跨境流/融资融券候选当前有 entitlement，但它们没有 typed query、SourcePolicy、PIT/单位/覆盖/cache/failure 合同或 production receipt。行业与资金概念不能因 endpoint 可调用就升级为 ready；成交额不能改名为净流入。它们保持 `unsupported`，不得以热度、概念榜、静态当前分类或 caller-authored JSON 替代。

`StrategyValidation` 继续 capability unavailable，既不是 MarketRegime 数据源，也不阻断研究、计划草稿或确定性计划评估；本决定不引入 Vibe-Trading 或任何 broker/order/自动交易/盘中路径。
