# 资格化 MarketRegime v2 的数据与最小组件

Type: `research`
Mode: `AFK`
Status: `open`
Blocked by: 01, 03

## Question

基于当前 Tushare-compatible 网关、官方/聚合来源边界和既有 MarketSnapshot 实现，决定第一版回答“当前市场对哪类投资逻辑更友好”最少需要哪些可解释组件。必须复验趋势、宽度、流动性、波动率、行业轮动和资金相关候选的接口权限、字段、单位、时间、横截面覆盖、历史分布、缓存与失败语义；宏观、新闻、情绪、拥挤度若不能可靠进入本切片，应给出明确降级而不是黑箱热度分。

## Current canonical baseline

- 这是未来数据资格研究，不得把候选指标写成已实现。每个候选数据集必须落到实际的 [`SourcePolicy@1`、typed query 与 `DataProvider`](../../../src/trading_platform/domain/data.py)，经 [`DataSynchronization`](../../../src/trading_platform/application/cli_tasks.py) 进入 frozen snapshot；CLI/Web 不得直连端点。
- A 股结构化行情与 CNINFO/SZSE official disclosure 的当前角色、authority、PIT/freshness/quality 和失败状态以 [adoption Issue 13](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md) 的 production/live evidence 为基线。SSE、BSE 与公司正式 IR ingestion 仍是 future/unavailable；空、部分、过期、身份冲突、schema drift、source-rights 不足或尚未实现的 official source 都必须保持 unknown/blocked，不能推导为“无事件”或零。
- MarketRegime 的未来输出只可作为 `ResearchEvaluationPlan@1`/计划指标的冻结输入；研究执行仍由 application `ResearchWorkflow` 管理 `ResearchWorkflowRequest@2` lifecycle 并经 `WorkflowLedger` 持久化，用户可见研究证据只来自 `ResearchDecisionView@2`。实现版本和生产 browser/PDF/workbook acceptance 见 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。
- `StrategyValidation` capability 保持 unavailable：未请求为 `not_requested`，显式选择时为非阻断 `requested_unavailable` + `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`。它不属于 MarketRegime 最小组件，也不要求 Vibe-Trading、回测、broker、order、自动交易或盘中做 T。
