---
name: equitytrack-decision-core
description: Use EquityTrack's single local decision path for account, research, valuation, planning, monitoring, and review tasks. Never provide personalized securities actions.
---

# EquityTrack 决策核心

这是唯一公开 Skill 入口。先识别用户要完成的自然语言任务，再读取且只读取对应 task 文档：

- [账户确认与查看](tasks/account.md)
- [投资研究](tasks/research.md)
- [确定性估值](tasks/valuation.md)
- [计划准备与确认](tasks/planning.md)
- [计划监控](tasks/monitoring.md)
- [两阶段复盘](tasks/review.md)

所有确定性操作都穿过八个 Application operation。不得直接读取 SQLite、调用领域私有函数、持久化 JSON/Markdown，或建立第二条命令路径。

AI 区分事实、假设、估计和缺失，提出论点、反方、驱动、风险、证伪条件、不确定性与复盘判断；Python 核实结构和引用、计算估值与风险、评估规则、执行幂等事务并保存真值；用户确认账户和最终 TradePlan。缺失只限制直接消费者，未知不填零。

默认使用研究语言，禁止个性化证券行动建议、评级和无充分方法输入的目标价结论。当前只允许明确虚构 Fixture Adapter 和隔离临时数据根；真实 Provider、凭据和真实数据验收未配置。
