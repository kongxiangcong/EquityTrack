# 02 — 持久化并恢复观察项

**What to build:** 让本地单用户通过公共入口初始化平台、创建一个观察项，并在应用完全重启后仍能看到同一稳定身份。该切片同时建立后续领域数据所依赖的 SQLite、不可变对象和迁移基础，但用户首先看到的是可恢复的观察列表，而不是存储内部结构。

**Blocked by:** 01 — 建立受保护的平台运行骨架.

**Status:** resolved

- [x] 空 data root 可以幂等 bootstrap 和 migrate；重复执行不会删库、覆盖不兼容数据或重建历史。（AC-001）
- [x] migration ledger 校验顺序、名称和 hash，并拒绝 hash drift、未知未来版本和半升级状态。
- [x] SQLite 使用受测的本地 rollback-journal 配置、外键和短事务；活跃数据库位于不受同步或网络文件系统影响的本机路径。
- [x] 内容寻址对象使用同卷临时文件、flush、SHA-256 和原子替换发布；数据库不会提交指向缺失或 hash 不符对象的引用。
- [x] 用户通过公共命令创建 `WatchlistItem`，相同 invocation 重放返回原结果，新 invocation 不制造重复关注关系。
- [x] composition root 完全关闭并重建后，公共查询仍返回相同的 Security 和 WatchlistItem identity。（AC-002）
- [x] 观察项明确表示关注关系，不携带 Position、账户、现金、成本或持仓语义。
- [x] doctor 能只读检查 schema ledger、SQLite integrity/foreign keys、基础领域约束、对象完整性和引用关系，并以稳定错误分类报告失败。（AC-016 部分）
- [x] 迁移测试覆盖空库、N-1、重复执行、日期精度、失败回滚和禁止删库重建。（AC-029 部分）

## Implementation Evidence

- `0001_core_identity_objects.sql` 建立 migration ledger、稳定 `Security`/有效期 identifier、Watchlist、object/artifact/relation 与 command receipt 基础表；核心字段受 FK、唯一性和日期精度约束。
- production composition root 注入 application-owned `PlatformPersistence` port；facade health 仅在真实 store 存在时报告 persistence available。
- SQLite 固定 rollback journal、foreign keys、FULL synchronous、busy timeout，并拒绝 UNC、映射远程盘及已知同步目录。
- migration runner 验证连续版本、名称/hash、future/half-upgrade；N-1 升级 backup-first 且验证备份，事务内故障回滚并保留旧库、日期精度和观察项。
- data-root writer lock 记录 PID、owner/run ref，拒绝活跃第二 writer 并回收可证明的 stale owner。
- object store 使用同卷 temp、flush/fsync、SHA-256、atomic replace；新对象与既存对象均复验 size/hash 后才登记数据库。
- public command 使用稳定 Security identity 和 invocation receipt；重放返回原结果，新 invocation 复用关注关系，currency/identifier 冲突 fail closed；重建 composition root 后 identity 不变。
- read-only doctor 检查 runtime/SQLite 配置、ledger、integrity/FK、required schema、领域不变量、object hashes、artifact 与多态 target refs。
- 验证：`python -m pytest tests/platform/test_watchlist_persistence.py -q` -> `8 passed`；`python -m pytest -q` -> `48 passed`；`python -m compileall -q src`；`git diff --check`。
- `code-review` 最终复审：Standards PASS；Spec PASS；全部有效发现均已修复并重新验证。
