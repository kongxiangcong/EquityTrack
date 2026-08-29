# 02: 建立账户、组合风险与统一应用事务

**What to build:** 让合成调用者通过唯一 Application Interface 确认和查看账户，并从不可变 AccountSnapshot 与已确认 ExecutionRecord 确定性计算 PortfolioState 和 RiskLimitResult；同一纵向切片建立所有 mutation 共用的事务、幂等和稳定失败语义。

**Blocked by:** 01 / 固定合成重构基线.

**Status:** completed

- [x] `account.confirm` 接收用户明确确认的账户候选，并在一个短事务中形成不可变 AccountSnapshot。
- [x] `account.show` 通过相同 Application Interface 返回账户只读视图，不允许 CLI、测试或投影直接查询 persistence。
- [x] 账户修订和纠错形成引用原快照的新 AccountSnapshot，不能覆盖历史或让既有计划引用漂移。
- [x] 未知现金、成本、可用数量和费用保持未知并只使直接依赖的 PortfolioState 或 RiskLimitResult 局部 insufficient；未知不得转换为零。
- [x] 行情和 Provider 输入只能影响临时 PortfolioState，不能改变 AccountSnapshot、持仓数量、现金或 ExecutionRecord。
- [x] RiskPolicy 只表达用户确认的确定性限制；RiskLimitResult 绑定明确 PortfolioState、输入引用、计算值、限制和无法判断项。
- [x] PortfolioState 不单独持久化；AccountSnapshot、ExecutionRecord、RiskPolicy 和 RiskLimitResult 通过一个 SQLite persistence path 保存。
- [x] 建立所有 mutation 共用的 application command 记录；相同 operation、idempotency key 和 request digest 重放原结果，不同 digest 返回 `IDEMPOTENCY_CONFLICT`。
- [x] 事务失败不会留下部分 AccountSnapshot、RiskLimitResult 或幂等记录；重启后精确重试保持同一结果身份。
- [x] 顶层失败只映射到 Spec 规定的稳定失败集合，同时保留脱敏的失败子步骤证据。
- [x] 合成旧账户、执行和风险事实完成单向迁移；任何无法无歧义保留的事实以精确 blocker 停止，不增加旧 decoder、alias、fallback 或双读。
- [x] 迁移所有已进入本 seam 的生产和测试调用者；删除不再被 live public surface 使用的旧账户/组合实现、专属 receipt、schema、fixture、测试和文档。
- [x] 仍被最终公开切换阻挡的旧调用方必须被冻结并进入最终删除清单，不能通过 bridge 调用新实现。
- [x] 公开 Interface 测试覆盖确认、读取、修订、纠错、未知传播、风险限制、幂等冲突、事务回滚、重启和 migration。

## Answer

`account.confirm/show`、portfolio/risk 与统一 application command/transaction 已建立；合成 seam 迁移、歧义阻塞、回滚和重启窄套件：`9 passed`。
