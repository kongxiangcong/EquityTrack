# 14 — 导入历史流水并只做增量更新

**What to build:** 让用户在已初始化账户上导入近一年资金明细和历史持仓汇总，形成可审计的 Transaction、CashLedger 和历史摘要；以后导入重叠或扩展窗口时，只追加真正新增或修订的记录，重复文件和重复行不会重复记账。

**Blocked by:** 13 — 从当前快照初始化 Account 与 Position.

**Status:** resolved

- [x] 证券买入、证券卖出、银行转存、银行转取、股息入账、红利税补缴和利息归本映射为明确 typed event；申购配号保留为非现金 informational event，不能伪装成成交或现金变化。
- [x] 发生金额与数量乘均价的差额只记录为 `aggregate_charges_inferred`；源文件没有佣金、印花税、过户费等拆分时不得猜测费用组成。
- [x] 资金流水按日期升序、同日保持来源发生顺序重放；申购配号作为不参与现金链的 informational event 保留并显示其余额序列异常，排除这两条非现金事件后，当前样本 745 个相邻现金转换必须全部与运行余额精确相符。
- [x] 一年窗口内交易净数量与当前快照存在四个窗口前开仓造成的负缺口；系统不得为这些缺口伪造买入 Transaction、成交日期或费用，而应登记 `opening_history_incomplete`。
- [x] 历史持仓文件作为已清仓周期的汇总证据导入，不作为原始 Transaction、PositionLot 或现金台账来源；它缺少数量时不得反推成交股数。
- [x] ImportBatch 保存 source object hash、source schema/version、账户、导入范围、发生顺序规则、canonical row hashes、结果计数和质量问题；个人明细不会进入日志或通用 artifacts。
- [x] 完全相同 source hash 的重导入返回原 ImportBatch；重叠导出使用稳定 canonical row fingerprint、同日 occurrence ordinal 和运行余额上下文识别已存在记录，并保留合法的同字段重复发生。
- [x] 新导出只追加新增 Transaction/CashLedger/event 和新的不可变 account snapshot；旧行内容变化产生 source revision 或冲突待确认，不原地覆盖历史。
- [x] 每次增量导入后对现金余额、当前证券数量、可用/冻结数量和源当前快照执行 reconciliation；不一致时保留已提交的合法事件，但阻断新的 reconciled PortfolioSnapshot。
- [x] 缓存和增量测试覆盖相同文件重放、完全重叠文件、部分重叠扩展窗口、历史行修订、顺序变化、弱自然键碰撞和中途崩溃恢复。
- [x] 在完整窗口前交易或可信 opening lots 未补齐前，已实现盈亏、TWR、MWR、税费分析和完整成本批次明确 limited/unavailable；历史持仓汇总不能解除该门禁。

## Implementation Evidence

- Migration `0010` adds immutable import batches/sources, typed account events, transactions, cash ledger entries, holding-cycle summaries, revision conflicts, quality issues and account-history snapshots. The service and `account-history-import` CLI publish verified source objects to the local CAS and never emit personal rows to logs or generic artifacts.
- Cash replay is date-ascending with stable source sequence inside each date. Exact decimals validate every adjacent cash transition while informational allocations remain non-cash events with explicit balance-anomaly issues. Buy/sell quantity signs are normalized only after the raw row is hashed; the amount-versus-gross delta is stored solely as `aggregate_charges_inferred`.
- Stable identities combine canonical row content, occurrence ordinal and inferred previous cash balance. Tests prove identical replay, complete overlap, a partial-window extension, source sequence changes, growing exact weak-key collisions, cash and holding-summary revisions, account-scoped invocation safety, and rollback/recovery after an injected crash.
- Reconciliation checks final cash plus current quantity/available/frozen positions. Negative cumulative security quantities create one `opening_history_incomplete` issue per affected security without synthetic transactions or lots. Revision or current-state mismatch blocks reconciliation while retaining valid committed evidence; complete histories have a reachable reconciled state and per-snapshot limitations.
- Real local samples, processed only in a temporary data root, produced 748 events, 694 transactions, 746 cash entries, 2 informational events, 120 holding summaries, 4 opening-history gaps and 745 exact adjacent cash transitions; the resulting state is `limited_opening_history` with an immutable snapshot.
- Final verification passed: Python 181, frontend 8, production web build, compileall and `git diff --check`. Code review from fixed point `21c2c1f`: Standards PASS and Spec PASS after all valid findings were fixed.
