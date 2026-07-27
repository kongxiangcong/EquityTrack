# 调研本地运行时、存储与恢复基线

Type: `research`
Mode: `AFK`
Status: resolved
Blocked by: 01

## Question

对于单用户、Windows、本地优先、可迁移的模块化单体，哪些经过验证的技术模式最适合承载事务元数据、时序/原始数据、可恢复工作流、run journal、artifact hashes、备份与恢复，同时保持当前纯 Python 投研内核可复用？调研应以 SQLite、DuckDB/Parquet、必要时 PostgreSQL，以及 Alembic/等价迁移、原子文件发布、任务 journal 和备份工具的官方文档与核心实现为主，检查并发/锁、事务、PIT 查询、schema migration、Windows 路径与文件锁、崩溃恢复、备份一致性和测试策略；不得无理由引入多套存储。形成独立 Markdown 研究资产，给出可证据化的组合候选与拒绝理由，而不是提前拍板架构。

## Answer

已完成独立研究资产：[本地运行时、存储与恢复基线研究](../research/local-runtime-store-and-recovery.md)。研究截至 2026-07-11，以 SQLite、Python `sqlite3`、DuckDB、Apache Parquet、Alembic 与 PostgreSQL 官方文档为主，并结合当前 checkout 和本机 Windows probes；它给出候选与启用门槛，没有替后续设计票提前批准数据库实现。

第一条切片值得继续比较的最小组合是 **SQLite 事务权威 + SHA-256 内容寻址的不可变本地文件**：SQLite 承载事务元数据、四类时间、版本、workflow/run journal、artifact manifest 与引用；raw、canonical ResearchRun JSON、derived HTML 和较大二进制产物先在同卷原子发布，再把 artifact 引用、节点完成和状态 transition 放进一个短数据库事务。这样只有一个数据库权威，也不会把当前 `outputs/` 目录冒充缓存或 journal。现有 `ResearchEngine.run(ResearchRequest) -> ResearchRun` 继续保持无 I/O，全部持久化位于 seam 外。

本机存在一个阻止“直接启用 WAL”的硬证据：Python 3.14 与 uv Python 3.11 都链接 SQLite 3.50.4，而 SQLite 官方已确认 WAL-reset 竞态影响 3.7.0 至 3.51.2，修复版是 3.51.3，另有 3.50.7/3.44.6 回补。后续若选择多连接 WAL，统一 `doctor` 必须核验已修复构建；否则只能先保留 rollback-journal 候选并接受较低读写并发。Windows probe 也确认 SQLite 只有一个 writer，第二个 `BEGIN IMMEDIATE` 会得到 `database is locked`；修正 Python 3.12+ transaction policy 后，在线 backup 可恢复已提交状态并通过 `integrity_check`。第一次 probe 暴露的 `autocommit=True + Connection.commit()` 假提交必须进入跨 Python 版本测试。

DuckDB/Parquet 只保留为**达到真实列式分析门槛后的扩展候选**。DuckDB 原生文件的稳定默认写模型局限在单个进程，Parquet 不是事务 catalog；二者不得承担 workflow journal、交易计划版本或 artifact manifest。只有真实 OHLCV/derived benchmark 证明 SQLite baseline 不足时，才能用 SQLite 冻结文件 manifest、以 DuckDB 只读/单进程分析 immutable Parquet。PostgreSQL 只在多用户/多进程持续并发写、远程访问或数据库级 WAL/PITR 成为硬需求时重新评估；其 MVCC、`pg_dump`、base backup 和 `pg_verifybackup` 能力真实，但 Windows server lifecycle、角色/端口、升级、WAL 保留和恢复运维对当前单用户切片没有被证明合理。

迁移保留两个候选：若后续已采用 SQLAlchemy，再适配 Alembic，但必须显式处理 SQLite batch move-and-copy、外键与 unnamed constraint 限制；若保持零 ORM，则使用有 version/name/SHA-256/applied-at ledger 的顺序 SQL migrations，不能只写 `PRAGMA user_version`。两条路线都要求迁移前已验证备份、独占 writer、失败保留原库，以及迁移后的 `integrity_check`、`foreign_key_check` 和领域不变量。

研究给出了跨数据库/文件的可恢复顺序：同卷 temp write -> flush/fsync/hash -> `os.replace` 到 immutable object -> 短事务提交 artifact/node/cursor；因此 crash 只能留下 temp、可回收 orphan 或完整引用，不会留下 committed missing object。备份先用 SQLite online backup 冻结 DB，再从冻结副本枚举引用 objects、逐个 hash 校验并生成 versioned `backup_manifest.json`；恢复到新 data root，校验 DB/FK/schema/全部 hashes 和最小应用查询后再切换，禁止覆盖活跃数据库。

无需新增 Wayfinder ticket。物理存储、四类时间与是否触发 Parquet 由[决定分层存储、时间语义与同步契约](07-decide-data-storage-and-pit-contracts.md)收敛；workflow/node/attempt journal、artifact transaction 和统一 `doctor/migrate/backup/restore` 入口由[决定 Codex 控制面、确定性运行时与 run journal 边界](08-decide-control-plane-runtime-and-run-journal.md)收敛。备份介质、保留期和加密继续留在 map 的 fog，等待物理布局与 RPO/RTO 明确。
