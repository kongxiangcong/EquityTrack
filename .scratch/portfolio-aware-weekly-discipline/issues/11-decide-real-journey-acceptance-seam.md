# 决定真实每周纪律旅程的最高层验收 seam

Type: `grilling`
Mode: `HITL`
Status: `open`
Blocked by: 07, 08, 09, 10

## Question

锁定在生产 composition root 和真实本地浏览器下的最高层验收旅程：用户手工创建账户快照，系统识别全部当前持仓与现金，生成组合风险快照和 MarketRegime，展示每个持仓的研究 readiness，用户创建/确认计划，收盘后评估，在下一交易日与周末回看不可变历史。决定哪些个人数据只作本地证据、哪些 aggregate 可进入 acceptance manifest，并列出正常、陈旧、缺失、冲突、重放、重启、备份恢复和零副作用反例。

## Current canonical baseline

- 最高层验收必须从 production application `bootstrap.open_*` composition functions 进入账户、`DataSynchronization`/`DataProvider`、市场、计划、`ResearchWorkflow` 与 `WorkflowLedger`，不得用 caller-authored JSON、fixture-only server、静态报告或私有 SQL 代替业务证据。
- 旅程须绑定 `SourcePolicy@1`、official evidence 与 frozen DataSnapshot identity，研究请求/计划为 `ResearchWorkflowRequest@2` / `ResearchEvaluationPlan@1`，浏览器、JSON、HTML、PDF、XLSX、archive 必须指向同一个 persisted `ResearchDecisionView@2` identity/hash。现有 production CDP、PDF、workbook、migration/restore 证据基线见 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。
- 未来组合旅程仍需新增自己的顶层 acceptance，至少证明正常、unknown/blocked、official evidence 陈旧/缺失/冲突、重复运行、重启、备份恢复、个人字段不出 manifest，以及 research/valuation 前后账户、授权、计划和 order state 无副作用。
- `StrategyValidation` 未请求时应为 `not_requested`；显式选择时应为非阻断 `requested_unavailable` + `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`。验收不得要求安装或配置 Vibe-Trading，也不得新增回测、broker、order、自动交易或盘中做 T 场景。
