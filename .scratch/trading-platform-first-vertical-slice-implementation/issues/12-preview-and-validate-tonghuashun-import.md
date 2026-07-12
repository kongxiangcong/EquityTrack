# 12 — 本地预检并验证同花顺导出

**What to build:** 让用户在本地工作区选择同花顺导出的当前持仓、资金明细和历史持仓文件，先看到文件角色、覆盖期间、字段映射、缺失信息、重复风险和可导入能力，再决定是否初始化账户。预检阶段不写入账户、交易、现金或持仓领域记录，也不把个人数据发送到外部服务。

**Blocked by:** 10 — 完成 Windows 运维、备份恢复与统一 Skill.

**Status:** resolved

- [x] 导入器按文件内容和表头识别数据角色，而不是信任扩展名或文件名；当前样本应识别为 GB18030 编码、Tab 分隔的文本表，而不是真正的 Excel 二进制文件。
- [x] 当前持仓、资金明细和历史持仓分别映射到版本化 source schema；未知表头、列数变化、非法编码、截断行和多余非空列 fail closed，并提供用户可处理的错误。
- [x] 预检报告验证当前样本包含 2 条当前持仓、748 条资金明细和 120 条历史持仓，并显示资金明细覆盖 2025-07-14 至 2026-07-10；报告不把这些计数扩大解释为完整账户历史。
- [x] 用户必须提供本地 Account 别名和基础币种；源文件没有账户标识，因此系统不得根据文件路径、证券或余额猜测账户身份。
- [x] 当前持仓文件没有明确 as-of 字段；预检只能给出与最新资金日期、交易日历和导出时间的候选关联，必须由用户显式确认初始化时点，不能把推断日期写成来源事实。
- [x] 预检显示缺少成交时刻、券商合同/成交编号、费用税费拆分、完整公司行动和窗口开始前持仓，并据此区分“可初始化当前状态”与“可完整重建历史账本”。
- [x] 资金明细中自然字段完全相同但代表两次独立发生的记录必须分别保留；当前样本的两组碰撞由运行余额和文件内发生顺序区分，不能按弱自然键误去重。
- [x] 原始文件按 SHA-256 进入本地私有不可变 source object；预检、日志、诊断和页面只显示脱敏摘要，不复制证券明细、余额或本机绝对路径。
- [x] source object、导入 staging 和个人账户数据默认位于 Git 工作树之外；doctor 对位于仓库内或未被 ignore 的个人源文件给出阻断级隐私告警。
- [x] 用户确认前数据库只保存可过期的脱敏预检结果或临时 session ref；取消、关闭页面或校验失败不会留下半个 Account 或业务台账。

## Implementation Evidence

- `TonghuashunImportPreviewer` identifies the three roles from exact decoded headers, not filenames/extensions, and maps them to versioned schemas. Strict GB18030 decode, tab width, trailing-empty-column, truncation, unknown-header and role-completeness gates fail closed with typed codes.
- Repeatable synthetic contract and the local private samples both produce 2 current positions, 748 cash-ledger rows, 120 holding-history rows, cash coverage 2025-07-14 through 2026-07-10, and two weak-key collision groups/four distinct occurrences. Running balance plus file sequence remain evidence; no weak-key deduplication occurs.
- Preview requires an explicit local alias/base currency and reports a confirmation-required as-of candidate using latest cash date, supplied trading sessions and local-timezone filesystem mtime, clearly labeled as candidate metadata rather than a source fact.
- Safe output distinguishes current-state initialization from full-ledger reconstruction and lists missing timestamps, broker execution IDs, fee/tax splits, corporate actions and opening positions. It contains no security values, balances or absolute paths.
- Raw bytes are copied atomically into read-only SHA-256 objects under a private root. CLI defaults that root under LOCALAPPDATA; this or any other Git worktree is rejected. Selected in-repo sources must be untracked and ignored, and doctor applies the same repo-wide `.xls` privacy gate.
- Preview performs no Account, transaction, cash or position database writes; only a 30-minute redacted in-memory preview expiry is produced before confirmation.
- Targeted importer/operations tests passed: 25. Final full regression passed: Python 166, frontend 8, production build, compileall and `git diff --check`.
- Independent review from fixed point `a4bd579`: Standards PASS and Spec PASS after all valid findings were fixed and reverified.
