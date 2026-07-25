# 综合组合感知每周纪律闭环实现级 Spec

Type: `task`
Mode: `AFK`
Status: `open`
Blocked by: 05, 06, 08, 09, 10, 11

## Question

把本 map 的全部已关闭决策综合为一份与当前代码严格分界、可直接拆实施票据的 Spec。必须覆盖领域对象、手工账户快照 capability、风险政策、MarketRegime、研究门控、计划指标与状态机、日常/周末工作流、Web 交互、数据与时间、隐私安全、迁移、失败降级、验收 seam、逐条 acceptance criteria 和最小实施顺序；不得把未来实现写成已完成事实。

## Current canonical baseline

- Spec 的 current-state 章节必须准确引用唯一 application `open_*` tasks、`SourcePolicy@1`/typed `DataProvider`、frozen DataSnapshot、管理 lifecycle 的 `ResearchWorkflow`、`ResearchWorkflowRequest@2`、`ResearchEvaluationPlan@1`、concrete ResearchEvaluation、`WorkflowLedger` 与 `ResearchDecisionView@2`；未来组合对象/任务/迁移必须与这些 seam 分界，不能创建 facade、旁路或兼容路径。
- A 股 market data 与 CNINFO/SZSE official evidence 的 authority/PIT/freshness/quality/failure baseline 来自 [adoption Issue 13](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md)；Request@2、migration 0014、View@2、PDF/workbook/Web/archive、backup/restore 和 production browser evidence 来自 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。未由这些证据证明的组合能力必须标为 future/blocked/unavailable。
- Spec 的 acceptance criteria 必须绑定 typed identity/hash、official-source fail-closed、unknown-not-zero、重放/重启/恢复、隐私与零账户/order副作用，并要求 production composition root + local HTTP + real browser；不能用 caller-authored evidence 或 required skip 充当通过。
- `StrategyValidation` capability 固定为 unavailable：未请求是 `not_requested`，显式选择是非阻断 `requested_unavailable` + `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`；它不进入第一版组合纪律实现或验收依赖。不得新增 Vibe-Trading、回测、broker、order、自动交易、盘中做 T、美股或港股 runtime。
