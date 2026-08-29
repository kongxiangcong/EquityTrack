# 01: 固定合成重构基线

**What to build:** 建立一个可重复、完全虚构的重构基线，使后续 agent 能准确识别当前 live runtime、需要保留的业务事实、必须退休的路径以及完整的合成旧 schema 输入，而无需访问真实账户、证券、来源或凭据。

**Blocked by:** None (can start immediately).

**Status:** completed

- [x] 固定当前公开命令、Application seam、领域记录、SQLite schema、migration、Skill 任务、测试、文档、生成产物和依赖的基线清单，并明确它们描述的是 live runtime 而非目标实现。
- [x] 建立退休清单，覆盖旧研究运行、数据快照、组合快照、投资论点版本、计划版本/graph/AST/sleeve、通用工作流、artifact、复盘版本、确认回执、计划影响和行为日志等目标设计已删除的概念。
- [x] 为每个退休概念记录生产调用方、测试调用方、持久化表或对象、文档和依赖，使后续切换可以证明搜索清零。
- [x] 把现有测试分类为“保留行为并迁移”“由更高 Interface 测试替代”或“随退休行为删除”，且每项只有一个处置结果。
- [x] 建立完全虚构的账户、Security、行情、财务事实、来源身份、时间和用户确认数据；名称、代码、数值和 source_id 均不得暗示真实主体。
- [x] 建立能够代表不可替代账户、执行、研究、估值、计划和复盘关系的合成旧 schema fixture，并包含缺失、陈旧、冲突和歧义样本。
- [x] fixture 能在隔离临时数据根中确定性重建，不能读取本机默认账户、真实数据根、环境凭据或网络。
- [x] 增加基线 guard，能检测真实身份、真实凭据、被禁止的项目阶段命名以及退休 symbol 的意外新增。
- [x] 记录当前完整测试命令及其准确通过、失败、跳过和超时结果；现有失败不得被改写为通过。
- [x] 本 ticket 不创建目标业务 Module、兼容层、双路径或实现 issues 之外的冗余产物。

## Answer

基线、退休矩阵、旧测试处置与完全虚构 fixture 已冻结；首次完整套件如实记录为 24 collection errors、1 deselected。离线基线 guard：`2 passed`。
