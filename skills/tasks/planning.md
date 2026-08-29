# 计划任务

从已提交 InvestmentCase、可选 ValuationAssessment、已确认 AccountSnapshot、价格与用户确认的 RiskPolicy 调用 `planning.prepare`。向用户展示风险限制、决策依据、有限规则、有效期和最终草稿；只在最终内容稳定后请求一次明确确认。

确认时只调用 `planning.confirm`，绑定 draft_id 与 content_hash，并记录确认时间、确认者和渠道。内容变化、过期、拒绝或沉默都不形成 TradePlan。修订追加 revision/supersedes 关系；无替代计划的关闭追加 PlanClosed。计划和规则不是订单，不得自动执行或自动修改。
