# 06: 建立计划监控与两阶段复盘

**What to build:** 让系统通过 `monitor.evaluate` 确定性评估活动 TradePlan，只在规则真实触发时创建 DecisionTask，并通过 `review.commit` 分别保存不受结果偏差污染的 PROCESS 复盘和引用它的 OUTCOME 复盘。

**Blocked by:** 03 / 建立宽松证据与研究提交; 05 / 建立受风险约束的计划准备与确认.

**Status:** completed

- [x] `monitor.evaluate` 是 application workflow 而不是第七个领域 Module；它只组合 EvidenceSet、planning 的 PlanEvaluation 和 review 的 DecisionTask。
- [x] planning Module 确定性计算 PlanEvaluation，结果明确区分触发、未触发、受阻和 insufficient，并记录直接依据。
- [x] 只有真实规则触发才在同一事务中幂等创建 DecisionTask；行情、EvidenceItem 或规则输入缺失不得创建任务。
- [x] 相同计划、规则和冻结输入的重试返回同一 PlanEvaluation 与 DecisionTask；不同请求的同一 key 返回 `IDEMPOTENCY_CONFLICT`。
- [x] DecisionTask 是需要用户处理的待复核事项，不是订单、交易信号或自动计划修改。
- [x] `review.commit` 是唯一复盘提交 operation，并通过 review Module 校验不可变性、任务关联和结果窗口。
- [x] DecisionReview(PROCESS) 只引用决策当时可用的冻结信息，不得读取后来结果重写过程判断。
- [x] DecisionReview(OUTCOME) 只能在结果窗口结束后提交，并必须引用对应 PROCESS 记录。
- [x] 周期汇总只是 DecisionReview、AccountSnapshot、ExecutionRecord 和开放 DecisionTask 的只读投影，不形成新的复盘真值或评分。
- [x] review Module 不修改 TradePlan、AccountSnapshot、ExecutionRecord 或历史理由。
- [x] 合成旧监控和复盘事实完成单向迁移；任务身份、PROCESS/OUTCOME 关系或结果窗口无法唯一还原时必须阻塞。
- [x] 迁移所有已进入本 seam 的生产和测试调用者，并删除不再需要的 PlanImpactAssessment、PlanChangeProposal、ActionLogEntry、DisciplineReviewVersion、通用 review workflow、schema、fixture、测试和文档。
- [x] 仍依赖最终公开切换的旧监控/复盘入口被冻结并进入最终删除清单，不增加兼容桥或双写真值。
- [x] Interface 测试覆盖触发、未触发、insufficient、任务幂等、事务回滚、PROCESS、OUTCOME、窗口、重启、投影和 migration。

## Answer

`monitor.evaluate` application workflow、有限 PlanEvaluation、触发任务幂等与 `review.commit` 两阶段时序已实现；投影/迁移窄套件：`5 passed`。
