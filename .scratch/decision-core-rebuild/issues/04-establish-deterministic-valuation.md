# 04: 建立确定性估值

**What to build:** 让用户明确请求的估值通过 `valuation.assess` 从 InvestmentCase、EvidenceSet、方法请求和假设形成唯一的 ValuationAssessment；方法路由、数据门、公式和敏感性全部由 Python 确定性负责，输入不足成为正常结果。

**Blocked by:** 03 / 建立宽松证据与研究提交.

**Status:** ready-for-agent

- [ ] `valuation.assess` 是唯一估值 application operation，并使用共享事务、幂等和失败合同。
- [ ] valuation Module 拥有方法路由、行业适用性、会计桥接、单位、币种、公式、敏感性和方法输入校验。
- [ ] AI 可以提出方法与假设候选，但最终方法适用性、计算结果和 disabled reason 只能由 valuation Module 决定。
- [ ] ValuationAssessment 结果只有 `completed` 或 `insufficient`；方法关键输入缺失、方法不适用或证据时点不合格不作为异常。
- [ ] EvidenceSet 的非相关缺失不得阻塞估值；每个 insufficient 结果必须指出实际缺少的方法输入和它禁用的结论。
- [ ] Financial、biopharma、cyclical/resource 和普通企业使用各自适用方法边界；普通 FCFF/WACC DCF 不适用于金融企业。
- [ ] 条件情景只在同一驱动结构上使用 stress、base、improvement；没有校准证据时不增加概率权重。
- [ ] 可比估值在来源、币种、会计口径检查后少于三个可用 peers 时不能支持估值结论。
- [ ] 默认输出不产生评级、个性化行动建议或缺少关键官方事实支持的目标价结论。
- [ ] ValuationAssessment 是 SQLite 中唯一估值真值；JSON 是即时响应，Markdown 只按需投影且默认不落地。
- [ ] 合成旧估值事实完成单向迁移；来源不完整、方法身份冲突或无法复算的旧结论以 blocker 停止，不保留旧估值 decoder 或并行真值。
- [ ] 迁移所有已进入本 seam 的生产和测试调用者，并删除不再需要的旧估值记录、模拟/市场路径决定、重复报告产物、schema、fixture、测试、文档和依赖。
- [ ] Interface 测试覆盖方法路由、各行业方法门、单位/币种、公式、敏感性、情景、completed/insufficient、幂等、回滚、重启和 migration。

