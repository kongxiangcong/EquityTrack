# 锁定 ResearchEvaluation 与 StrategyValidation 的深模块 interface

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 02, 03, 04, 05, 06

## Question

基于删除矩阵和四类候选的运行证据，使用 Module/Interface/Seam/Adapter/Depth/Leverage/Locality 与领域词汇，锁定 typed `ResearchEvaluationPlan`、研究质量评估职责、`StrategyValidationRequest`/`StrategyValidationResult`、DataProvider/source-policy 交互、artifact identity/lineage、WorkflowLedger 写入和失败语义；证明每个新 port 有 production 与 deterministic test 两个真实 adapters，并用 deletion test 排除字符串 dispatch、dynamic import、service locator、万能 Manager、镜像 Facade 和纯字段重包装。
## Answer

决定见 [ResearchEvaluation 与 StrategyValidation interface 决定](../research/research-evaluation-strategy-validation-interface-decision.md)，当前 seam 与 caller/schema/test 证据见 [current seam audit](../research/research-evaluation-strategy-validation-current-seam-audit.md)。

唯一公开 application path 保持 `ResearchWorkflow.handle(...)`，但未来必须用一次性 `ResearchWorkflowRequest@2` 迁移删除 caller-authored projection mappings 与 analysis artifacts，改为 frozen snapshot refs 加 typed `ResearchEvaluationPlan`。`ResearchEvaluation`、source policy 与 future `StrategyValidationEngine` 都是目标内进程具体深模块，不建立新 port；只有既有 `DataProvider` 与 `WorkflowLedgerPort` 通过真实 production/deterministic-adapter 证明。Vibe 已拒绝且当前 StrategyValidation 有零个 production adapter，因此本票禁止 placeholder port/fake adapter，并将未实现请求锁定为 `blocked + STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`、无伪造 result/artifact。

设计已经锁定 plan 的 closed typed selections、方法路由最终否决权、冻结证据和策略 identity、Walk-Forward/PIT/A 股执行/成本/统计约束、result identity/diagnostics、专用 artifact lineage、ledger 原子写入和 typed failure semantics。删除矩阵明确要求在后续实现票中原子删除 Request@1 codec、自由 mapping public seam、caller artifact construction、虚假 `ResearchRunner` variation point、字符串 provider dispatch/hard-coded policy identity，以及任何 registry、dynamic import、万能 Manager、镜像 Facade、转发 repository、compatibility 或双路径。

`CONTEXT.md` 为启动时用户拥有的 untracked dirty 资产，本票不修改；领域词义已在决定资产中锁定。本票只形成 Wayfinder 设计决定，未修改生产代码，也未宣称 StrategyValidation 已实现。
