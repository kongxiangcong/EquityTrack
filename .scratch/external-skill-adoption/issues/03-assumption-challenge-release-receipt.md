# Typed assumption challenge dossier and release receipt

Status: needs-triage

## Blocking edge

当前 Forecast 与 scenario 已有 rationale、bounds 和 invalidation condition，但
尚无统一 typed contract 强制每个 material assumption 同时记录支持证据、
counter-evidence 和 falsifier，也没有完整 WACC x g 参数面或覆盖 persisted
ledger/全部 DecisionView 的独立 release receipt。当前 workbook 会从 raw
OOXML 将 canonical 行和值与导出时的 `ResearchDecisionView` 做 `Decimal`
对账，并复算 equity bridge/per-share 链；它不是完整 DCF，也不是相对
persisted ledger 的独立二次来源校验。因此这些能力目前只能
作为研究复核流程与迁移验收，不能报告为已 fail-closed 的 runtime 正式
发布门。

## Required migration

- 为 material assumption 定义版本化 dossier：事实/计算/判断分类、支持来源、
  反证、可证伪条件、stress/base/improvement 值与责任 policy；
- dossier 缺失只限制依赖的方法或结论权限，不抹掉其他研究；
- 构建 source-calibrated 完整 WACC x g surface，并定义无支持 cell 的
  fail-closed 表示；
- DCF release receipt 分别记录 source、assumption、forecast/FCFF、method
  math、WACC x g surface、workbook projection 和跨 persisted ledger/全部
  DecisionView 的独立验证；不得让同一 projection 自证其来源一致性；
- 保留 workbook 相对导出 DecisionView 的 Decimal 对账与 bridge/per-share
  复算作为 XLSX delivery gate，
  但不把它升级为完整 DCF 或独立来源验证；
- 不提供默认概率，不使用 Bear/Base/Bull，不产生 target price 或交易动作；
- 完成领域 schema 与持久化的一次性迁移后删除旧的自由文本假设路径。

## Removal target

迁移完成后，报告与 workbook 只投影 typed dossier/receipt；不再把自由文本
assumption summary 当成正式发布充分条件。


## Comments
