# 07: 演练完整合成迁移与恢复

**What to build:** 使用代表完整旧系统关系的合成数据根，证明六个目标 Module、Application Interface 和一个 SQLite 可以从旧 schema 一向迁移、在每个失败边界原子回滚并从验证过的备份恢复，同时冻结最终原子切换的精确调用方与删除清单。

**Blocked by:** 02 / 建立账户、组合风险与统一应用事务; 03 / 建立宽松证据与研究提交; 04 / 建立确定性估值; 05 / 建立受风险约束的计划准备与确认; 06 / 建立计划监控与两阶段复盘.

**Status:** ready-for-agent

- [ ] 在隔离临时数据根中从 fresh、代表性旧版本、完整 populated、含歧义、含损坏和迁移中断六类合成状态启动演练。
- [ ] 迁移前创建不可覆盖的完整备份，并验证数据库和所有不可替代业务事实可以从该备份恢复。
- [ ] 一向迁移保留 AccountSnapshot、ExecutionRecord、InvestmentCase、ValuationAssessment、RiskPolicy、RiskLimitResult、TradePlan、DecisionTask 和 DecisionReview 的唯一身份与引用。
- [ ] PortfolioState、即时 JSON、Markdown 投影和其他可重建产物不作为迁移真值。
- [ ] 任何零匹配、多匹配、断裂引用、未知确认内容、无法判断修订关系或无法建立 PROCESS/OUTCOME 关系都以稳定、精确 blocker 停止整个迁移。
- [ ] 在对象准备、schema 变更、领域记录写入、幂等记录写入和 commit 前后注入失败，证明目标数据库不会出现半迁移状态。
- [ ] 迁移失败后原数据根和备份保持可恢复；修复合成输入后重试产生身份稳定的结果。
- [ ] 迁移成功后重启并运行 doctor，所有八个 Application operation 都能读取或继续使用迁移结果。
- [ ] 迁移完成的数据根不能再通过退休 runtime、旧 decoder、旧 schema 猜测、dual read 或 fallback 提供服务。
- [ ] 精确列出最终公开切换需要更新的 Skill 任务、CLI 命令、composition wiring、测试、文档、依赖和生成资产。
- [ ] 精确列出所有剩余退休 symbol、表、migration、fixture、测试和产物，并为每项确定在 08 中的删除动作；不允许模糊“后续清理”。
- [ ] 演练不读取、复制、探测或修改真实数据根，不使用真实 Provider、凭据、证券或账户。
- [ ] 报告每种演练的通过、失败、跳过和未运行项；只有全部合成迁移与恢复路径通过才能关闭本 ticket。

