# 让应用任务拥有唯一原子边界

账户确认、研究提交、估值评估、计划准备与确认、监控评估和决策复盘分别通过 `account.confirm`、`research.commit`、`valuation.assess`、`planning.prepare`、`planning.confirm`、`monitor.evaluate` 和 `review.commit` 完成；跨模块写入由该应用任务的一次短事务拥有，领域模块不自行提交。所有 mutation 共用唯一的 application command 幂等记录，正常数据不足作为局部 `insufficient` 结果返回，只有无效输入、引用不存在、输入过期、幂等冲突、持久化和内部故障进入稳定失败合同。
