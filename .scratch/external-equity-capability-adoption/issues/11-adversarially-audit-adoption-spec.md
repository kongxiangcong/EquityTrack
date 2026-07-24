# 对抗性审计 adoption Spec 与真实替换门

Type: `task`
Mode: `AFK`
Status: `resolved`
Blocked by: 10

## Question

对 adoption Spec 同时执行 Standards + Spec 审计，并从财务/估值、数据时间、量化、组合风险、软件运维、安全许可、工作流和后见之明视角构造具体失败用例；核对每个 adopted 行都有真实替换门、两个合理 adapters、原子 caller/schema/presentation 迁移、明确删除对象和可运行验收，修复所有 blocker 后清空 fog、将 Map 标为 resolved，并明确移交 `/to-spec` 后续核验与 `/to-tickets` 的 implementation frontier。
## Answer

以 `7171489` 为repository fixed point、以新建Spec相对空文件的`git diff --no-index`为审计面，分别完成了独立Standards与Spec review，并在 [adversarial audit](../research/adoption-spec-adversarial-audit.md) 中记录财务/估值、数据时间、量化、组合风险、软件运维、安全许可、工作流和后见之明失败用例。初审Spec SHA-256为`F2A51F40A45C7E19656B602D66E3192DA3058E73922D9D5B90FAEDFC1798E0A1`，本票使用的更新Goal Prompt SHA-256为`CA1148516E14C148AC247123081CE7A2237863A725192779B3B9C7241FBEE41D`。

发现并修复的blockers为：decision enum越界；分层而非vertical slices；无owner的cleanup/release票；>600行owners无深模块拆分；缺六张portfolio planning回写；缺PDF；SourcePolicy无合规fallback；phase full verifier缺失；live JSON可伪造；adapter矩阵不全；0013/0014 schema不能唯一实施。修订后的 [Spec](../spec.md) 以I01–I04完整production slices、I05精确planning backwrite和Goal-level final proof取代旧I01–I06队列；每个`adapt-code`行都进入已有DataProvider port并有production + FixtureProvider adapters，当前零`adopt-external`，因此不存在伪造的external replacement gate。

Fog已清零。实现尚未开始；A/SEC adapters、migrations、PDF renderer、live receipts和persisted-root preflight是有owner的implementation preconditions。Map可标记resolved，下一Goal续轮必须先`/to-spec`核对published contract，再`/to-tickets`发布I01–I05，随后建立仅含本effort planning assets的baseline commit并claim I01。
