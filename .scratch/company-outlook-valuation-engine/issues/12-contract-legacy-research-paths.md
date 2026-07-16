# 12 — 收缩遗留研究与模型路径

**What to build:** 让所有正式 JSON、HTML、XLSX 和平台视图从同一组 typed Forecast/Valuation artifacts 派生，移除自由 context、双报告模型和只能检查外观的 Excel 计算权威，同时保留必要的历史读取兼容。

**Blocked by:** 05 — 发布决策优先的研究视图; 09 — 支持周期与资源证券估值; 10 — 支持金融企业 Valuation; 11 — 支持创新药 rNPV 与 SOTP.

**Status:** completed

- [x] 新研究执行不再直接读取 analyses/debate/synthesis/scenarios/dcf_case 等 magic keys；兼容 adapter 只负责迁移旧输入并发出版本化诊断。
- [x] 旧 renderer 与新的专业 renderer 收敛到一个 decision-first view model；完整审计 appendix 仍可追溯。
- [x] XLSX 成为 canonical Valuation artifact 的输出 adapter，逐项对账公式与数值；核心输出硬编码或断链时验收失败。
- [x] 遗留 validator 不再作为正式运行权威；仍有价值的 raw/hash、公式和金融 invariant 迁移到单一实现。
- [x] 当前状态审计、目标架构、Skill 入口、方法文档和使用说明与实际实现一致，删除或明确归档冲突规范。

## Completion evidence

- Formal presentation: `ResearchDecisionView@2` drives workflow JSON, decision-first HTML, workspace history, and the XLSX adapter.
- Legacy input: `LegacyResearchContextAdapter@1` is the only reader of free-form research magic keys and emits versioned diagnostics.
- XLSX: 36 valuation points reconcile basis/equity/diluted-share/per-share bridge formulas; canonical-value and Summary-formula tampering fail acceptance.
- Runtime authority: platform source, forecast, valuation, artifact, and presentation invariants do not import the legacy standalone validators.
- Verification: full Python suite `345 passed`; workbook integration `4 passed`; fixed acceptance CLI passed; specification and standards reviews both `CLEAN`.
