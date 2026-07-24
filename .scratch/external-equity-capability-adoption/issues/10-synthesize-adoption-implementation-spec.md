# 综合外部能力 adoption 实现级 Spec

Type: `task`
Mode: `AFK`
Status: `resolved`
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09

## Question

将 resolved Map 的证据和决定综合成唯一 `.scratch/external-equity-capability-adoption/spec.md`：包含候选决策矩阵、最终 application/DataProvider/CompanyForecast/ScenarioValuation/ValuationSimulation/StrategyValidation/ResearchDecisionView 数据流、typed contracts、领域语义分离、source/financial/privacy/fail-closed 门禁、单向迁移与删除序列、schema/NOTICE/升级政策、implementation issue 切片和可复现 phase/final acceptance；文档只能描述已证实的当前事实与明确待实施设计，不能把未来状态写成完成。
## Answer

唯一实现级 Spec 已写入 [`.scratch/external-equity-capability-adoption/spec.md`](../spec.md)，状态明确为 `draft-for-adversarial-audit`，SHA-256 为 `f2a51f40a45c7e19656b602d66e3192da3058e73922d9d5b90faedfc1798e0a1`。文档重新综合票 01–09 的最终 evidence/decisions，并在开头明确区分当前 checkout 事实与待实施设计；没有把 ProviderJob@2、migrations 0013/0014、A股/SEC adapters、Request@2 或 ResearchEvaluation 写成已完成。

Spec 包含最终候选决策矩阵（当前零 `adopt-external`）、唯一 application/DataProvider/CompanyForecast/ScenarioValuation/ValuationSimulation/StrategyValidation/ResearchDecisionView 数据流、typed queries/evidence/Request@2/Plan/result/artifact contracts、领域语义分离、source/PIT/financial/privacy/security/fail-closed gates、typed failure matrix、backup-first one-way schema cutover、NOTICE/归属/依赖/升级政策，以及 I01–I06 blocker-first implementation issues。每张 implementation issue 都绑定 caller、persistence/schema、presentation、tests/current docs和same-ticket deletion；StrategyValidation 当前只允许 unavailable result，不建立任何 production placeholder。

Phase acceptance 和 final acceptance 已锁定 public pytest slices、三市场 verifier、full project verifier、Web tests/build、real browser CDP、release acceptance、fresh/0012-populated/fault migration/restore matrix、forbidden-symbol/dependency/notice/generated-assets/final-diff gates。Spec 的 9 个相对 evidence 链接全部存在，结构检查为 6 个 typed-contract sections、6 个 implementation issue slices，UTF-8 replacement chars 为 0，`git diff --check` 通过。

本票只新增 Wayfinder Spec，未修改生产代码；票 11 仍是下一唯一 frontier，负责 Standards + Spec 对抗性审计、修复 blocker和决定 Map closure。在票 11 完成前不得 `/to-tickets` 或开始实现。
