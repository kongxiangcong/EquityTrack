# 10 — 完成 Windows 运维、备份恢复与统一 Skill

**What to build:** 让 Codex 通过统一控制面在 Windows 上可靠执行初始化、自检、迁移、同步、每日运行、服务、测试、备份、恢复和恢复执行，用户不需要拼接零散命令。备份和恢复必须验证完整关系并恢复到新 data root，恶意 bundle 或路径不能影响目标根之外的文件。

**Blocked by:** 08 — 从故障检查点安全恢复 WorkflowRun; 09 — 交付安全可访问的完整工作区与历史回看.

**Status:** resolved

- [x] 所有维护操作和 resume 都是真实能力而非 no-op，并在 Windows subprocess 中返回稳定 JSON envelope、正确退出码、run/artifact refs 和 typed error code。（AC-033）
- [x] doctor 校验实际 Python/SQLite/build identity、rollback-journal/WAL 门、路径、锁、schema/hash、FK/integrity、领域不变量、objects/manifests、配置和 Provider readiness。
- [x] mutation 使用 data-root scoped writer lock，migrate、bootstrap schema/root 变更和 restore switch 使用 exclusive maintenance lock；网络等待期间不持有长 SQLite 事务。
- [x] migrate 在已有 data root 上 backup-first，覆盖空库、N-1、重复、hash drift、未来版本、日期精度和失败保留旧库，不允许删库重建。（AC-029）
- [x] backup 生成不可变 frozen SQLite、完整 referenced objects、版本化 manifest 和逐项 hash，并拒绝位于 live data root 内的目标。
- [x] restore 永不覆盖 active root；它恢复到新 root，验证 hash、SQLite、schema、领域、journal、artifact refs 和最小查询，生成不可变报告后才允许显式切换。
- [x] restore 拒绝绝对路径、上跳、ADS、symlink、hardlink、junction、reparse point、hash/path mismatch 和大小或数量炸弹，并证明新 root 外无文件变化。（AC-047）
- [x] 真实 Windows E2E 完成 backup、restore 新 root、doctor、serve 和 history query，逐项验证关系和 hashes。（AC-030）
- [x] secret 只从环境或可替换 OS credential adapter 注入；输出只保存不可逆 credential scope 与 configured/missing，日志、DB、备份和页面不回显值。
- [x] Python/npm locks、package integrity、dependency/license inventory、适用的 NOTICE/LICENSE 和页面归属可重算；离线 build/runtime 无 CDN、遥测或自动安装。（AC-046）
- [x] 统一平台 Skill 能由 Codex 选择并调用全部维护能力，业务 wheel/import graph 不包含该 Skill 或 prompt，用户无需手工记忆命令。（AC-048）

## Implementation Evidence

- `trading_platform.cli` is the JSON control plane for bootstrap, doctor, migrate, sync, daily, serve, test, inventory, backup, restore, explicit root switch, workflow resume and history. Argument, infrastructure and unexpected failures return sanitized typed envelopes and non-zero exit codes.
- Maintenance uses data-root locks plus atomic server/workflow presence; bootstrap/migrate/switch reject active runtimes and live workflow leases. Existing-root migrate creates a new immutable full backup first, including the empty-database path, while the migration ledger still rejects drift/future/half-upgraded states transactionally.
- Backup freezes SQLite with the backup API, validates integrity/FK and canonical object paths/hashes, records app/database/config/journal versions and item hashes, refuses in-root or existing targets, and marks archives read-only. Restore targets a new root only, validates archive types/paths/counts/sizes/compression, exact manifest/object graph and metadata, doctor/domain/history state and a minimum query, then writes an itemized read-only report before explicit switch.
- Windows subprocess E2E proves backup → restore → switch → doctor → serve → workspace/history plus workflow resume and final manifest refs. Adversarial tests cover traversal, absolute/ADS paths, non-regular/link entries, reparse path checks, duplicate/count/size/total/compression bombs, safe-named junk, object path/hash mismatch, and unchanged outside sentinels.
- Credentials use an injectable adapter (environment default and Windows Credential Manager implementation); doctor and Provider readiness render only hashed scopes/status. Tests scan stdout/stderr, database, objects, backup, restore report and page payloads for secret leakage.
- `requirements.lock`, hashed `requirements-build.lock`, `package-lock.json`, integrity/license inventory, notices and page attribution are reproducible; offline sources contain no CDN/telemetry/auto-install behavior. The sole `skills/SKILL.md` routes every operation while runtime imports remain free of Skill/prompt dependencies.
- Targeted operations and persistence tests passed: 41. Full Python suite passed: 155. Frontend tests passed: 8; production build passed. Python compilation and `git diff --check` passed.
- Independent review from fixed point `3f91b07`: Standards PASS and Spec PASS after all valid findings were fixed and reverified.
