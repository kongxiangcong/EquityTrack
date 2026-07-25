# 原型化任务优先的每周纪律驾驶舱

Type: `prototype`
Mode: `HITL`
Status: `open`
Blocked by: 02, 04, 05, 06

## Question

制作并与用户逐屏验证一个任务优先的本地 Web 原型：手工填写账户快照、查看组合集中度与真正影响能力的缺口、比较市场状态变化、查看每个持仓的研究/不确定性、创建和确认计划草稿、查看每日规则结果及周末复盘。默认界面必须突出当前判断、变化、影响和下一步确认点，完整 provenance/诊断渐进披露。动态标的身份、零 K 线 fail-closed、账户空状态与 production browser acceptance 已有验证证据，本票不得重开这些已关闭修复；若原型发现新回归，必须以独立证据和明确 owning ticket 处理。

## Current canonical baseline

- 原型必须经 `trading_platform.application` 的 `open_*` task interfaces 使用现有账户、市场、计划、研究与 `WorkflowLedger` seams；它可以验证未来组合交互，但不能另建 facade、Web data path、renderer 或 persistence path。
- 持仓研究卡只投影持久化 `ResearchDecisionView@2`；application `ResearchWorkflow` 管理 research run lifecycle，`ResearchWorkflowRequest@2` + `ResearchEvaluationPlan@1` 引用 frozen snapshot，来源资格由 [`SourcePolicy@1` / `DataProvider`](../../../src/trading_platform/domain/data.py) 决定。不得在浏览器中拼接 official evidence、重算估值或把 unknown 显示成零。
- 原型 acceptance 必须复用 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md) 已证明的 production bootstrap/local HTTP/real CDP seam，并覆盖 reload、restart、keyboard、窄视口、reduced motion、安全头和 hashed assets；静态 HTML/fixture 截图不算验收。
- `StrategyValidation` 未请求时为 `not_requested`；显式选择时只显示非阻断 `requested_unavailable` + `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`。原型不提供安装/配置入口，不接入 Vibe-Trading，也不增加回测、broker、order、自动交易或盘中做 T。
