# 09: 验收合成决策闭环

**What to build:** 通过唯一公开 Skill 和 Application Interface 验证账户、研究、估值、计划、监控及两阶段复盘的完整合成闭环，并用恢复、依赖和退休搜索证明仓库只剩当前系统；只有全部证据成立时才把进展更新为“合成通路已验证”。

**Blocked by:** 08 / 原子切换公开工作流并删除旧运行时.

**Status:** ready-for-agent

- [ ] 通过公开入口完成虚构 AccountSnapshot 确认与读取，并证明未知账户字段局部传播而不填零。
- [ ] 通过 Fixture Adapter 和 Skill 形成 EvidenceSet 与 InvestmentCase，覆盖完整证据和局部缺失两种路径。
- [ ] 完成一个 `completed` 和一个 `insufficient` ValuationAssessment，数字可确定性复算且没有金融输出越界。
- [ ] 完成 planning.prepare 的三记录原子写入、用户明确 planning.confirm、TradePlan 修订和 PlanClosed。
- [ ] 完成未触发、真实触发和 insufficient 三种 PlanEvaluation；只有真实触发产生 DecisionTask。
- [ ] 完成 DecisionReview(PROCESS) 与在结果窗口结束后的 DecisionReview(OUTCOME)，并证明 OUTCOME 引用且不改写 PROCESS。
- [ ] 重启后通过同一 Application Interface 读取所有规范记录，重复 mutation 精确重放且冲突返回稳定失败。
- [ ] 从验证过的合成备份恢复，doctor、完整闭环和只读投影再次通过。
- [ ] 所有保留 Python 测试、Skill fixture/eval、migration/recovery、dependency guard 和端到端测试通过，并报告准确计数、耗时、跳过、超时和未运行外部检查。
- [ ] 搜索确认退休 symbol、命令、schema、migration、fixture、测试、文档、产物格式、依赖和生成资产在活动 runtime 与控制面中清零。
- [ ] 搜索确认不存在兼容层、双读写、feature flag、fallback、平行 package、DSH 或量化平台占位实现。
- [ ] 检查最终 diff 和工作树，保留与本工作无关的用户变更，不清理、覆盖或提交未授权文件。
- [ ] 文档只描述一个当前路径，并明确合成验证不能证明真实 Provider 或真实数据通过。
- [ ] 只有上述条件全部满足时将状态从“设计已确认”更新为“合成通路已验证”；任一失败、跳过的必要 gate 或退休残留都保持未完成。
- [ ] 本 ticket 不配置真实凭据、不访问真实数据根、不删除真实备份、不声明“真实通路已验证”。
