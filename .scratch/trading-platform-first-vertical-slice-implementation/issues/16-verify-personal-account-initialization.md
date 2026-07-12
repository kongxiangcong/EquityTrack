# 16 — 验证个人账户初始化与增量更新

**What to build:** 在全新私有 data root 上使用三类同花顺导出完成账户预检、用户确认、当前状态初始化、历史导入、重复导入和增量更新，并生成可回放的验收证据。验收必须明确区分“当前状态已对账”与“完整历史会计能力仍受窗口限制”。

**Blocked by:** 11 — 生成验收证据并分类生产资格; 15 — 将 Account 与 Position 接入工作区和计划上下文.

**Status:** resolved

- [x] 生产 composition root 通过公开命令和本地 Web 完成预检、账户确认、opening state、历史导入、工作区查询和计划快照引用，不直接 seed 数据库或 mock repositories。
- [x] 当前样本成功形成一个用户确认的 Account、两条当前 Position、opening cash、PortfolioSnapshot、历史 typed events、质量 issues 和完整 source/object refs；敏感值只在本地授权视图中出现。
- [x] 相同三个源文件重复导入不会新增 Account、Transaction、CashLedger、PositionLot 或相同快照；ImportBatch 明确报告 reused disposition。
- [x] 部分重叠且新增记录的测试导出只追加增量记录和新快照；旧记录修订、合法重复发生和顺序变化分别按 revision、distinct occurrence 和 stable replay 处理。
- [x] 现金重放、当前 Position 数量和快照对账分别有 machine-readable check；四个已知窗口前持仓缺口与申购配号异常保持显式，不被 skip、平均、补零或虚构交易关闭。
- [x] 完全关闭并重建 facade、server restart、backup 到 bundle、restore 到新 root 和 doctor 后，账户、台账、持仓、快照、质量问题和 source refs 保持完整。
- [x] 离线 network spy 证明预检、初始化、重导入、查询、备份和恢复均零外连；secret、账户标识、原始路径和个人明细不进入日志或通用 acceptance artifact。
- [x] acceptance manifest 记录 import schema、canonical row identity、source safe hashes、AccountSnapshot/PortfolioSnapshot versions、reconciliation status、known limitations 和各 suite artifact refs。
- [x] `current_state_initialized`、`cash_reconciled`、`positions_reconciled` 和 `history_complete` 分开裁决；当前样本允许前三项通过时，`history_complete` 仍必须为 false。
- [x] 验收摘要明确第一条观察项纵向切片与个人账户初始化切片的完成范围，继续保持 `long_term_platform_complete=false`。

## Implementation Evidence

- Public preview, initialization, history import, workspace/server, plan context and `account-acceptance` CLI seams operate on a fresh private data root without database seeding or runtime network/LLM dependencies.
- Real local three-file replay in a temporary root produced one confirmed account, 2 positions, 748 typed events, 746 cash entries, 120 summaries, 4 opening gaps and 2 informational anomalies. Identical replay returned the original batch; backup/restore doctor passed.
- `AccountAcceptanceManifest@1` records opening/history batch and snapshot versions, opening+history source schemas/safe hashes, canonical identity version, aggregate issues/limitations and the hashes of all four required passing suite artifacts. Missing, failed or blocked evidence fails closed.
- Independent checks compare replay cash to opening cash and validate every current quantity equals available plus frozen. Real result: current state, cash and positions true; history complete false; long-term platform complete false.
- Final verification: Python 184 passed; frontend 9, production build, compileall and diff-check passed. Targeted post-manifest tests passed 3. Standards and Spec review findings were fixed and rechecked.
