# 03: 建立宽松证据与研究提交

**What to build:** 让 Skill 能在数据库事务外基于完全虚构的来源形成研究候选，再由 `research.commit` 通过 EvidenceSet 和 InvestmentCase 的唯一目标 seam 校验并持久化；证据缺失只限制直接消费者，不再产生全局研究门或研究运行产物。

**Blocked by:** 02 / 建立账户、组合风险与统一应用事务.

**Status:** completed

- [x] EvidenceItem 只能表达“值与 source_id”或“missing_reason”，不得用质量评分、默认值或缺失填零替代来源状态。
- [x] EvidenceSet 强制统一 as_of，并处理输入标准化、来源登记解析和重复项；它没有全局 completeness、rights、quality 或 pass/fail 状态。
- [x] Fixture Adapter 是当前唯一 Provider Adapter，支持确定性成功、缺失、陈旧、冲突和 Provider 失败，不读取网络或真实凭据。
- [x] `research.commit` 接收 Security、as_of、EvidenceSet 和 AI 研究候选，并通过共享 application command/transaction seam 保存 InvestmentCase。
- [x] InvestmentCase 包含论点、反方、驱动、风险、证伪条件和不确定性，不包含估值数字、目标价、评级或交易动作。
- [x] Python 只负责候选结构、引用一致性和确定性派生字段的校验；不得通过 prompt、规则树、评分或叙述模板拼装投资观点。
- [x] AI 研究发生在事务外，提交只持有短事务；失败或重试不会重复写入或长期持锁。
- [x] 非关键 EvidenceItem 缺失时 InvestmentCase 仍可局部受限地提交；关键缺失的影响必须精确记录到依赖判断。
- [x] 规范研究真值只保存在 SQLite；不生成或持久化 ResearchRun、CompleteReport、artifact manifest、lineage、HTML、PDF、workbook 或复杂图表。
- [x] 合成旧研究事实完成明确的一向迁移；只能从完整且唯一的旧身份建立 InvestmentCase，零个或多个候选都必须阻塞而不是猜测。
- [x] 迁移所有已进入本 seam 的生产和测试调用者；删除不再被 live public surface 使用的 ResearchRequest、ResearchAnalysisPlan、ResearchRun、DataSnapshot、EvidenceSnapshot、InvestmentThesisVersion 及其 schema、fixture、测试、文档和依赖。
- [x] 仍依赖最终公开切换的旧研究入口保持冻结并进入最终删除清单，不得新增旧到新或新到旧的兼容调用。
- [x] Module Interface 测试覆盖 as_of、来源/缺失、重复项、局部降级、候选校验、幂等、回滚、重启和 migration；AI 判断质量由 Skill eval 而非固定文本断言覆盖。

## Answer

EvidenceSet、唯一 Fixture Adapter 与 `research.commit` 已建立；研究迁移和候选唯一性阻塞窄套件：`6 passed`。AI 判断留在最终 Skill eval。
