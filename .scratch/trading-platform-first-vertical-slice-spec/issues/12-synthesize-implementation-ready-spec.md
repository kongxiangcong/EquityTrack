# 综合第一条纵向切片实现级 Spec

Type: `task`
Mode: `AFK`
Status: resolved
Blocked by: 11

## Question

如何把已关闭的审计、研究、领域和设计票据综合为一份与当前代码库一致、可直接进入实现阶段的第一条纵向切片 Spec？Spec 必须固定产品边界、用户故事、术语、当前复用 seam、目标模块边界、数据与时间模型、Provider/缓存契约、Codex/运行时边界、K 线与标注、交易计划状态机、市场状态、持久化/run journal/artifact manifest、Windows 运维、失败与降级、迁移路径、最高层验收 seam、逐条 acceptance criteria、实现顺序和明确非目标；所有采用/改造/拒绝结论必须链接审计或 research 资产，不得把尚未实现的设计写成当前事实，也不得在本 ticket 实现平台。

## Answer

已形成实现级资产：[个人投研交易策略平台：第一条纵向切片实现级 Spec](../spec.md)，版本 `0.1.0`，状态为 `implementation-ready-draft / pending-adversarial-audit`。本票只完成规划综合，没有实现平台代码、数据库、Provider 或正式 UI。

Spec 明确区分了当前 checkout 与目标设计：当前唯一稳定研究 seam 仍是 `ResearchEngine.run(ResearchRequest) -> ResearchRun`，平台目标能力全部位于该 seam 外；任何尚未实现的 Provider、SQLite、Web、K 线标注、计划、市场快照、run journal 和运维能力均以目标时态书写。

Spec 已固定：

- 观察项意华股份 `002897.SZ`、请求日 `2026-07-11`、有效交易日 `2026-07-10` 与既有 `2026-07-07 ResearchRun` 复用的八步用户旅程；
- 模块化单体、ApplicationFacade 唯一边界、snapshot-to-request adapter、Provider/PIT/cache、SQLite + object store、五段 migration、workflow/journal/manifest/resume、KLineChart adapter 与版本化标注、计划状态机/typed AST、四组件 MarketSnapshot 和只读 PlanEvaluation；
- 九项维护入口加 `resume`、Windows single-writer、backup/restore 新 root、失败/降级与秘密脱敏；
- 38 条连续编号的 acceptance criteria、分层测试归属、九步实现顺序、明确非目标和 live qualification 完成声明边界；
- 所有 adopt/adapt/reference/reject 结论到 MVP 审计、Provider/PIT、Kimi Datasource、图表、存储/恢复 research 资产的可解析链接。

验证结果：45 个本地 Markdown 证据链接全部存在；AC-001 至 AC-038 连续且无重复；`python -B -m unittest discover -s tests -v` 当前 35/35 通过。

本票没有暴露新的未覆盖设计问题。现有[对抗性审计 Spec 并关闭实施前缺口](13-adversarially-audit-and-close-spec-gaps.md)按原计划成为下一张 frontier ticket；它需要从八个对抗视角验证 Spec，未通过前不得把 `0.1.0` 升为实施基线或开始大规模平台实现。
