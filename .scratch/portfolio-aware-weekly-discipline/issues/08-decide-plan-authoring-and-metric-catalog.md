# 决定计划编制、指标目录与确定性评估合同

Type: `grilling`
Mode: `HITL`
Status: `open`
Blocked by: 04, 05, 06, 07

## Question

在现有 `TradePlanDraft -> TradePlanVersion -> PlanEvaluation` seam 上，决定网页如何把用户确认的风险政策、手工账户快照、MarketRegime 和研究状态组合成可编辑草稿；需要新增哪些 `position.weight`、`portfolio.cash_ratio`、集中度、回撤、研究状态、事件窗口和市场状态指标；哪些规则效果只能是提示复核、标记风险、阻断候选意图或观察；如何显示触发、未触发、无法判断和阻断；如何保证任何修改产生新版本并且不生成订单或动作语言。

## Current canonical baseline

- 当前可复用实现是 [`TradePlanDraft -> TradePlanVersion`](../../../src/trading_platform/plans.py) 和 [`MarketSnapshot -> PlanEvaluation`](../../../src/trading_platform/market.py)；本票设计未来指标/状态，不得宣称组合级目录或日终编排已完成，也不得绕过 application tasks 或 `WorkflowLedger`。
- 研究类指标只能引用 persisted `ResearchDecisionView@2` 的明确状态/identity；application `ResearchWorkflow` 的上游请求是 `ResearchWorkflowRequest@2` + `ResearchEvaluationPlan@1`，数据来源由 `SourcePolicy@1`、typed `DataProvider` 和 official evidence gates 最终否决，再由 `WorkflowLedger` 持久化。缺失/陈旧/冲突/不可比必须映射为无法判断或阻断，unknown 永远不是 zero。
- 任何新增计划指标必须定义单位、as-of/PIT、freshness、source/view identity、适用规则、不可用原因及确定性 evaluation；不得从 Forecast 或估值直接生成行动语言。canonical research/presentation 与 production acceptance 证据见 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。
- `StrategyValidation` capability 当前 unavailable：未请求为 `not_requested`，显式选择为非阻断 `requested_unavailable` + `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`，均不阻断草稿、确认或评估。第一版目录不得包含回测绩效指标，不接入 Vibe-Trading、broker、order、自动交易或盘中做 T。
