# External Research Skill Method Adoption

## Status

implemented_with_migration_frontier

## Decision

`skills/bridgewater-pat-research` 与 `skills/dcf-valuation-governance` 不作为
active Skill、CLI、数据源或第二套运行时接入。它们都不获取真实投研数据，
且候选代码不能满足本项目的来源、PIT、Decimal、降级、输出边界和许可要求。

本项目以 clean-room 方式吸收可验证的方法：冻结能力绑定、闭合分析 DAG、
节点身份与执行凭据、可挑战假设、DCF 参数面治理，以及工作簿相对导出
DecisionView 的 Decimal 对账与关键桥复算。只有已经实现并验证的行为进入
现有 `ResearchWorkflow`、领域合同和
唯一发布路径；其余方法保留为研究复核流程和版本化迁移验收，不能写成当前
runtime 已强制。

## Enforcement boundary

### Current enforced runtime

- 冻结 capability plan 与 strict `research_model_input` ingress；
- 既有来源/PIT/官方事实、适用性、缺失数据、方法数学和输出边界；
- DecisionView 当前审计投影绑定计划与实际节点 receipt，但不是跨
  DecisionView 的独立二次验证；
- workbook 交付前用 Python 从 raw OOXML 将 canonical 行和值与导出时的
  `ResearchDecisionView` 做 `Decimal` 对账，并复算 equity bridge/per-share
  链；这不是完整 DCF 或相对 persisted ledger 的独立来源验证。

### Research review and target migration

- material-assumption challenge dossier 的完整 typed contract；
- source-calibrated 完整 WACC x g 参数面；
- 跨 persisted ledger/DecisionView 的独立验证与统一 release receipt。

上述三项尚未成为 fail-closed runtime gate。当前可按其方法做 review 并记录
migration gap，但不得声称正式 DCF release receipt 已通过。

## Implemented slice

- `ResearchAnalysisPlan@1` 从正式 evaluation plan 与 frozen evidence 编译，
  调用方不能构造节点或代码；
- `research_model_input` ingress 与 compiler 使用同一严格字段合同，跨 dataset
  的同名路径不能被模型消费；
- DecisionView 当前审计投影绑定计划与实际节点 receipt，不宣称独立二次验证；
- valuation workbook 交付前从 raw OOXML 将 canonical 行和值与导出时的
  `ResearchDecisionView` 做 `Decimal` 对账，并复算 equity bridge/per-share；
  它既不是完整 DCF 复算，也不独立复核 persisted ledger 来源；
- Skill 文档把假设反证、falsifier 与 WACC x g 参数面作为研究复核方法和迁移
  验收，不把它们描述为当前 runtime 发布门；
- Teach 只映射为脱敏最小失败样例、公开 seam TDD 和人工 review，不自修改。

## Explicit non-adoption

- 不执行候选生成代码，不引入 PAT runtime、permission harness 或第二缓存；
- 不复制候选 CLI、JSON schema、25/50/25 概率或 Bear/Base/Bull 命名；
- 不新增 target-price、rating 或个性化交易结论；
- 不把 Tushare-compatible 数据升级为官方披露；
- 不声称已实现节点级缓存、完整 DCF 独立复算，或对
  ledger/DecisionView 来源做了独立二次校验。

## Migration frontier

下列工作需要版本化 one-way migration，不能塞进本次安全切片：

1. 从官方/结构化事实编译 `research_model_input` 的语义 lineage；
2. 分析节点级 checkpoint/reuse 与 descendant invalidation；
3. 类型化 assumption challenge dossier；
4. source-calibrated 完整 WACC x g 参数面；
5. 跨 persisted ledger/DecisionView 的独立验证与正式 release receipt。

对应 issues 位于本目录 `issues/`。

## Evidence

候选审计、数据路径、测试和许可证边界见
`research/candidate-skill-assessment.md`。
