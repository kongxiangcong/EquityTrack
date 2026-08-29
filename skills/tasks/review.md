# 复盘任务

PROCESS 候选只使用决策当时冻结的 DecisionCard、PlanEvaluation 与相关 EvidenceSet，评价过程并调用 `review.commit`。不得读取后来结果倒推当时理由。

结果窗口结束后，OUTCOME 候选必须引用对应 PROCESS DecisionReview，再调用同一 operation。评价结果与过程分离；二者都不修改账户、计划、执行记录或历史理由。周期汇总只是现有记录的只读投影，不形成评分或第二套真值。
