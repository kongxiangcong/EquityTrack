# 15 — 将 Account 与 Position 接入工作区和计划上下文

**What to build:** 让用户在同一 Security 工作区看到观察关系、当前 Position、现金和初始化/对账状态，并在创建交易计划时引用一个确切的账户快照。计划仍是用户规则而不是指令；只有被初始化数据可靠覆盖的仓位和风险条件才能确定性评估。

**Blocked by:** 14 — 导入历史流水并只做增量更新.

**Status:** resolved

- [x] Security 工作区区分 WatchlistItem 与 Position，并展示 Position 所属 Account、snapshot as-of、数量、成本基础、可用/冻结状态和 freshness，不把观察项误写为持仓。
- [x] 默认视图只显示当前判断需要的持仓、现金、变化和真正影响能力的对账问题；ImportBatch、row hashes、源文件和完整 ledger 通过历史/审计渐进披露。
- [x] TradePlanVersion 可选择性引用确切 AccountSnapshot/PortfolioSnapshot；引用后内容 hash、版本差异和历史回看固定该快照，后续导入不会改写旧计划语境。
- [x] 对当前 Position 可由快照直接支持的数量、名义金额和账户币种规则使用 exact values；依赖窗口前成本批次、完整税费、组合历史收益或缺失现金流的规则保持 unknown/not_applicable。
- [x] 没有 Position 的 WatchlistItem 仍可创建计划，但页面明确区分“未持有”与“持仓数据缺失”，不能用零仓位掩盖导入失败。
- [x] 新增或修订导入只生成新的 AccountSnapshot/PortfolioSnapshot 和并列计划评估；旧计划、旧评估和旧历史继续引用原冻结快照。
- [x] 计划确认和评估不更改 Account、Position、CashLedger 或 Transaction，不生成数量建议、订单、委托导出或自动交易副作用。
- [x] browser E2E 覆盖当前持仓工作区、数据限制、计划引用账户快照、增量导入后变化解释和旧版本历史回看。
- [x] 页面、导出和 artifacts 不包含账户真实标识、原始文件路径或未经用户选择的完整个人交易流水。

## Implementation Evidence

- Migration `0011` freezes optional plan-to-account snapshot references with context JSON/hash and immutability triggers for opening positions/lots and PortfolioSnapshots. Exact account operands are enabled only for a selected immutable PortfolioSnapshot; AccountHistorySnapshot metrics without snapshot-specific lots/NAV remain unknown.
- Workspace values bind to one exact PortfolioSnapshot and expose only per-response local account labels, position/cash/cost/availability/frozen/freshness fields and capability limitations. Audit history exposes aggregate import counts/status without row hashes, source paths or full ledger rows.
- Relationship projection distinguishes `position`, `watchlist_not_held`, `account_data_missing` and `position_data_missing` using successful atomic import coverage; incomplete account identity cannot be presented as zero position.
- Plan content hash/version history includes the selected account snapshot. Incremental import integration proves a new AccountHistorySnapshot and parallel PlanEvaluation coexist while v1/v2 keep their original frozen snapshot references; evaluation does not mutate account, position, transaction or cash tables.
- Local browser API/reload coverage verifies current positions, limitations, new import history and privacy; frontend policy tests verify progressive disclosure and prohibited-language boundaries.
- Final verification passed: Python 184, frontend 9, production build, compileall and `git diff --check`. Independent review from fixed point `6155233`: Standards PASS and Spec PASS after all valid findings were fixed.
