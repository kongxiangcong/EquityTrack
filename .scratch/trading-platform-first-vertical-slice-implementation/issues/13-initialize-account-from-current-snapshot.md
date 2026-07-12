# 13 — 从当前快照初始化 Account 与 Position

**What to build:** 让用户确认账户别名、币种和初始化时点后，以同花顺当前持仓快照和资金明细的最新余额建立一个可追溯的本地账户起点。初始化产生明确标记的 opening state，而不是伪造窗口开始前的交易；重启后用户可以回看现金、当前 Position、成本基础、来源和限制。

**Blocked by:** 12 — 本地预检并验证同花顺导出.

**Status:** resolved

- [x] 用户确认后原子创建 Account、初始化 ImportBatch、opening cash、opening Position/PositionLot 和 PortfolioSnapshot；任一步失败不留下半初始化账户。
- [x] 当前持仓的 Security 由代码、交易市场和有效标识历史解析；名称只作展示，不能作为 identity，除权名称变化不会产生新的 Security。
- [x] 股票数量、可用数量、冻结数量、成本价、币种和来源使用 exact decimal/整数合同；负数、非有限值、数量关系不成立或未知市场使初始化阻断。
- [x] 每个当前 Position 以 `opening_snapshot` 来源建立，不生成虚假的买入 Transaction；成本价只表示源快照给出的期初成本基础，不宣称已经重建 acquisition lots。
- [x] opening cash 来自资金明细按日期分组并按文件内发生顺序重建后的最新运行余额；重建规则、候选 as-of、源行 identity 和用户确认记录进入审计证据。
- [x] 当前样本的日内现金链除两次申购配号附近的四个跳变外均可由发生金额解释；这些异常必须保留为质量 issue，不能通过重排、补差或删除行使检查虚假通过。
- [x] 市价、市值、当日盈亏和仓位占比保留为源快照观察值，并带 source-as-of 限制；系统不得把它们升级为实时行情或重新计算后的权威组合估值。
- [x] 当前样本中逐行市值必须等于数量乘源市价，全部市值加重建后的期末现金必须在 0.01 个百分点内复现源仓位占比；不一致时阻断 reconciled PortfolioSnapshot。
- [x] Account、Position、opening state 和 PortfolioSnapshot 在 composition root 重启、server 重启和 backup/restore 后保持相同 identity、exact values 和 source refs。
- [x] 相同 invocation 或相同已确认 source snapshot 重放返回原初始化结果，不重复创建账户、现金、PositionLot 或 PortfolioSnapshot。
- [x] 工作区明确显示“历史账本尚未完整重建”和初始化时点之前的收益、现金流、成本批次与税费能力限制，不输出个性化交易建议。

## Implementation Evidence

- Migration `0009` adds immutable Account, import-source/batch, opening cash, Position/PositionLot, source observation, quality issue and PortfolioSnapshot records. One writer transaction creates the complete graph; injected final-write failure proves all business rows roll back.
- Security resolution uses market/code and the repository's half-open effective identifier history at confirmed as-of. Existing identities are reused, ambiguity/history gaps fail closed, new identifiers begin at the confirmed date, and source display names remain non-identity observations.
- Exact contracts reject negative/non-finite decimals, fractional total/available/frozen shares, invalid quantity relations, unknown markets and source/account currency mismatch. Source market value must exactly equal quantity × source price; each source weight must reconcile to market value/(market value+opening cash) within 0.01 percentage point.
- Opening cash uses latest source date then file occurrence order. Audit evidence persists full candidate-as-of/calendar/export basis, explicit confirmation identity/time/alias/currency, cash rule/date/row identity and source hashes. Four actual intraday jumps are retained as `CASH_RUNNING_BALANCE_JUMP` issues.
- Each row identity binds its source-object SHA. Verified raw files are published into data-root CAS and linked by `account_import_source`, so backup/restore preserves role/schema/hash/row count and exact source bytes.
- Positions/lots are `opening_snapshot`; no Transaction table or synthetic buys are created. Source price/value/day-P&L/weight are preserved as source-as-of observations, not promoted to live valuation.
- Production composition facade, CLI, workspace and local server expose the same opening detail and explicit incomplete-history/returns/cash-flow/acquisition-lot/fee limitations. Composition restart, server query and backup/restore preserve complete detail and CAS refs.
- Same invocation/source snapshot and concurrent replay return one identity. Targeted account/import tests passed: 19. Real local samples produced cash `206.62`, 2 positions, 4 retained quality issues and a reconciled PortfolioSnapshot.
- Final full regression passed: Python 178, frontend 8, production build, compileall and `git diff --check`. Independent review from fixed point `232b931`: Standards PASS and Spec PASS.
