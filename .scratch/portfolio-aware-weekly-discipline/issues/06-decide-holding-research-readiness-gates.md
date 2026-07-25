# 决定持仓研究与条件估值的计划门控

Type: `research`
Mode: `AFK`
Status: `open`
Blocked by: 01, 02, 05

## Question

对于手工声明账户中的每个当前持仓，哪些 ResearchRun、官方证据、Forecast、Valuation、技术结构、事件和 freshness 状态必须存在，才能支持周计划中的不同规则；缺少公司研究、估值方法受阻、官方证据过期或只有市场行情时，哪些计划能力仍可用、哪些必须 blocked/unknown？锁定研究复核项与交易计划规则的边界，禁止把语言模型观点或条件价值区间直接变成行动指令。

## Current canonical baseline

- 门控必须读取已持久化的 `ResearchDecisionView@2`，不得由 Web/计划 caller 重跑或重新解释研究。`DataProvider` 由 `SourcePolicy@1` 约束并经 application synchronization 形成 frozen DataSnapshot；application `ResearchWorkflow` 接受 [`ResearchWorkflowRequest@2` + `ResearchEvaluationPlan@1`](../../../src/trading_platform/domain/research_evaluation.py)，concrete ResearchEvaluation 只通过 [`WorkflowLedgerPort`](../../../src/trading_platform/application/workflow_ledger.py) typed query 加载 frozen evidence，再由同一 `WorkflowLedger` 原子持久化 View@2。精确实现与 production acceptance 见 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。
- 当前门控证据必须保留 frozen DataSnapshot identity、`SourcePolicy@1`、official-source/PIT/freshness/quality 状态和 valuation router 的 disabled/not-ready/not-comparable 原因。当前只有 CNINFO/SZSE official ingestion 已实现；SSE、BSE 与公司正式 IR 仍是 future/unavailable。任何 required official evidence 缺失、过期、部分、quarantined、身份不一致或来源尚未实现，都不能被辅助行情升级为 ready；A 股 official vertical slice 证据见 [adoption Issue 13](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md)。
- 本票要决定不同计划规则可消费 View@2 的哪些明确字段和失败状态；不能把 Forecast、条件估值区间、语言模型文本或 unavailable capability 转换成买卖/加减仓动作。
- `StrategyValidation` 未请求时显示 `not_requested`；显式选择时只可显示非阻断 `requested_unavailable` 与 `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`。第一版持仓 readiness 不依赖它，不产生回测结果或 artifact，也不接入 Vibe-Trading、broker、order、自动交易或盘中做 T。
