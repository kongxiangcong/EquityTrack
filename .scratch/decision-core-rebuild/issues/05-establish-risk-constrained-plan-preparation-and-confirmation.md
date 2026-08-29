# 05: 建立受风险约束的计划准备与确认

**What to build:** 让合成用户从 InvestmentCase、可选 ValuationAssessment、AccountSnapshot 和 RiskPolicy 准备一个受风险约束的 TradePlanDraft，并只通过对最终 content_hash 的一次明确确认形成不可变 TradePlan；未确认草稿不参与监控，也不产生订单。

**Blocked by:** 02 / 建立账户、组合风险与统一应用事务; 03 / 建立宽松证据与研究提交; 04 / 建立确定性估值.

**Status:** ready-for-agent

- [ ] `planning.prepare` 是唯一计划准备 operation，并在一个事务中计算和保存 RiskLimitResult、DecisionCard 与 TradePlanDraft。
- [ ] planning 不接收调用者预先计算的风险结果，不存在 `monitor_only` 或绕过风险政策的分支。
- [ ] DecisionCard 引用 InvestmentCase、可选 ValuationAssessment 和 RiskLimitResult，不能复制或覆盖它们的规范事实。
- [ ] TradePlanDraft 具有稳定 content_hash；任何内容变化都会产生新 hash 并使旧确认无效。
- [ ] `planning.confirm` 只接受 draft_id、content_hash 和用户明确确认，并在一个事务中形成不可变 TradePlan。
- [ ] TradePlan 直接记录确认时间、确认者和渠道；删除 PlanConfirmationChallenge、UserApprovalReceipt 和领域专属确认 receipt。
- [ ] 修订通过 plan_family_id、revision 和 supersedes_plan_id 连接；旧 TradePlan 保持不可变且可追溯。
- [ ] 没有替代计划时通过追加 PlanClosed 结束活动计划，不能覆盖或删除原计划。
- [ ] PlanRule 使用有限、类型化条件；不引入通用 AST、计划 graph、持仓 sleeve、策略语言、自动计划修改或订单。
- [ ] 未确认、拒绝、过期、STALE_INPUT、hash 不匹配和幂等冲突均不会产生活动 TradePlan 或部分写入。
- [ ] 规范计划真值只在 SQLite；即时 JSON 和按需 Markdown 不形成第二份计划记录。
- [ ] 合成旧计划事实完成单向迁移；只能保存能够唯一还原确认内容和修订关系的计划，歧义或缺失必须阻塞。
- [ ] 迁移所有已进入本 seam 的生产和测试调用者，并删除不再需要的 TradePlanVersion、master aggregate、graph、AST、sleeve、activation event、challenge、approval、专属 receipt、schema、fixture、测试和文档。
- [ ] 仍依赖最终公开切换的旧计划入口被冻结并进入最终删除清单，不增加转换 facade 或 fallback。
- [ ] Interface 测试覆盖准备原子性、风险引用、hash、确认、修订、关闭、冲突、过期、回滚、重启和 migration。

