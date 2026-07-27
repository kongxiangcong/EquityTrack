# 本地运行时、存储与恢复基线研究

研究截至：2026-07-11  
适用范围：单用户、Windows、本地优先、可迁移的 Python 模块化单体；仅为第一条纵向切片提供候选与启用门槛，不替后续设计票决定最终架构。

## 结论摘要

本票没有证据支持“默认同时引入 SQLite、DuckDB、Parquet 和 PostgreSQL”。经官方文档、当前 checkout 与本机 probe 交叉核验，值得带入后续设计票的候选只有三档：

1. **最小组合候选：SQLite 事务权威 + 内容寻址的不可变本地文件**。SQLite 保存事务元数据、四类时间、版本、workflow/run journal、artifact manifest 与引用；raw 响应、ResearchRun JSON、HTML 和未来较大二进制产物写入同卷的 SHA-256 内容寻址目录。文件先持久化，引用再与节点完成状态在一个数据库事务中提交。它只有一个数据库权威，没有把文件目录冒充第二套数据库。
2. **分析扩展候选：在出现已测量的列式扫描瓶颈后，再加 Parquet + DuckDB 只读/单进程分析 adapter**。DuckDB/Parquet 不承担 workflow journal、交易计划版本、artifact manifest 或并发写权威。第一条单股切片的数据量没有证明该扩展现在必要。
3. **服务化升级候选：仅当多用户、多进程并发写、远程访问或真正数据库级 PITR 成为硬需求时改用 PostgreSQL**。PostgreSQL 的 MVCC、`pg_dump`、base backup + WAL/PITR 能解决更强的并发和恢复目标，但会把本地单文件应用升级为需要安装、运行、鉴权和备份运维的数据库服务。

SQLite 候选目前有一个**必须先通过的版本门**：本机 Python 3.14 与 uv Python 3.11 都链接 SQLite **3.50.4**；SQLite 官方 2026-04 更新说明，WAL-reset 竞态影响 3.7.0 至 3.51.2，修复版为 3.51.3，另有 3.50.7 与 3.44.6 回补。当前本机库不能直接作为“WAL + 多连接”生产基线；`doctor` 必须识别已修复构建，或候选先使用 rollback journal 并接受更低读写并发。[SQLite WAL-reset bug](https://www.sqlite.org/wal.html#the_wal_reset_bug)

## 当前 checkout 与本机事实

- [`pyproject.toml`](../../../pyproject.toml) 要求 Python 3.10+，声明的运行时依赖为空；数据库、ORM、迁移和 Web 依赖均未进入项目契约。
- 当前稳定研究 seam 是 `ResearchEngine.run(ResearchRequest) -> ResearchRun`。[`current-product-state-audit.md`](../../../current-product-state-audit.md) 已决定：数据库、Provider、文件和 Web I/O 留在 seam 外，平台原样持久化 `ResearchRun.to_dict()`，HTML 是派生 artifact。
- 历史 `src/equity_research/cli.py` 曾有 Windows `msvcrt` / Unix `fcntl` 发布锁、同父目录 staging、backup 与 `os.replace`。该 retired 路径只证明跨平台锁和 staged publish 的可复用思路；它没有文件 `fsync`、artifact manifest、不可变历史、数据库事务或跨 DB/文件恢复协议，也不能作为当前 runtime 或兼容入口。
- 本机 probe：Python 3.14.0 和 uv Python 3.11.15 的 `sqlite3.sqlite_version` 均为 `3.50.4`；全局环境可导入 DuckDB 1.4.4、SQLAlchemy 2.0.50，不能导入 Alembic。全局可导入不等于项目依赖已固定。
- 修正事务控制后的 Windows smoke probe 验证了三件事：WAL 可启用；第二个 `BEGIN IMMEDIATE` writer 得到 `database is locked`；`Connection.backup()` 生成的副本通过 `PRAGMA integrity_check` 且包含已提交状态。第一次 probe 也暴露出 Python 3.12+ 易错点：`autocommit=True` 时 `Connection.commit()` 无效，显式 `BEGIN IMMEDIATE` 必须配显式 SQL `COMMIT`，或统一采用另一种受测事务策略。Python 官方明确区分 PEP 249 `autocommit` 与 SQLite autocommit。[Python sqlite3 transaction control](https://docs.python.org/3/library/sqlite3.html#transaction-control-via-the-autocommit-attribute)

这些 probe 只验证本机行为和未来测试路径，不证明尚未实现的平台已经满足崩溃恢复。

## 候选矩阵

| 候选 | 事务/并发 | 分析与 PIT | 备份/恢复 | Windows 与运维 | 本票结论 |
|---|---|---|---|---|---|
| SQLite + 内容寻址文件 | SQLite 支持多个 reader、单个 writer；WAL 可让 reader/writer 并行，但仍只有一个 writer | 业务 PIT 必须由应用保存版本与四类时间；事务 snapshot 不是历史事实库 | 在线 backup API / `VACUUM INTO` 可生成一致 DB snapshot；外部文件必须进入同一 backup manifest | 嵌入 Python、无服务；WAL 仅限同机本地文件系统；当前 3.50.4 未过 WAL 修复门 | **保留为最小组合候选；需版本门、迁移与恢复协议** |
| SQLite + Parquet + DuckDB | SQLite 仍为事务权威；DuckDB 原生文件只支持单个读写进程，多进程稳定并发写不成立 | DuckDB 对 Parquet 有投影/过滤下推，适合被证明的大型列式扫描 | Parquet 文件必须不可变、内容寻址，并由 SQLite manifest 管理；不能把目录 glob 当快照 | 新增 DuckDB/Parquet 版本、schema 与文件生命周期负担 | **延后；满足数据量/性能门槛后才引入** |
| DuckDB 原生库作为唯一权威 | 单进程内支持 MVCC/乐观并发；原生文件的多进程读写不是稳定默认能力 | 事务有 snapshot isolation，但不自动保存业务历史版本 | 有 WAL/checkpoint 与 export/import，但不替代应用 artifact backup bundle | 嵌入式、Windows 可用；Web/worker 分进程写入边界脆弱 | **拒绝作为 journal/事务主库** |
| PostgreSQL + 内容寻址文件 | MVCC 和服务端多会话并发最强 | 应用 PIT 仍需显式建模；WAL archive 可做数据库灾备 PITR | `pg_dump` 一致逻辑备份；base backup + WAL 支持 PITR，`pg_verifybackup` 校验 manifest | Windows 需安装/维护服务、角色、端口、升级、WAL/备份策略 | **条件升级，不是单用户第一切片默认值** |
| SQLite + Alembic/SQLAlchemy | 迁移编排成熟，但新增 ORM/迁移依赖 | 与 PIT 无直接关系 | revision 可审计；SQLite batch migration 是 move-and-copy | 跨平台，但必须处理 FK、反射与 batch 限制 | **仅当后续已决定采用 SQLAlchemy 时 adapt** |
| SQLite + 版本化 SQL migration ledger | 可用 stdlib `sqlite3` 保持依赖最小 | 与 PIT 无直接关系 | 每个 migration 文件带序号/hash，应用事务和备份前置 | 需自己实现校验、失败恢复和兼容测试 | **保留为零 ORM 候选，不只依赖 `user_version`** |

## SQLite：适合事务权威，但不是“零设计”

### 并发、锁与崩溃恢复

SQLite 的事务是 ACID，并由项目的 crash/power-failure test harness 检查；多个连接可以同时读，但只能有一个 write transaction。[SQLite transactional guarantees](https://www.sqlite.org/transactional.html)；[SQLite transactions](https://www.sqlite.org/lang_transaction.html)

WAL 模式让 reader 与 writer 并行，但仍只有一个 writer；长读事务可能阻止 checkpoint 前进，应用必须处理 `SQLITE_BUSY`。WAL 依赖同机共享内存，不能放在网络文件系统，`-wal` 是数据库持久状态的一部分，不能在活动/崩溃数据库旁单独删除或漏拷。[SQLite WAL concurrency and files](https://www.sqlite.org/wal.html)

因此若后续选择 SQLite：

- 数据根必须是本机受控卷，不支持 OneDrive/SMB/NAS 同步目录中的活动数据库；备份成品可以在关闭/校验后复制到其他介质。
- 所有连接统一设置并验证 `foreign_keys`、journal/synchronous、busy timeout 与事务策略，不依赖编译默认值。SQLite 官方说明 foreign-key enforcement 默认可能为 OFF，应用应显式设置。[SQLite pragmas](https://www.sqlite.org/pragma.html#pragma_foreign_keys)
- writer transaction 保持短小；Provider 网络请求、报告渲染和大文件 hash 不得在持有 write lock 时执行。
- 状态 claim 使用受测的原子事务，例如 `BEGIN IMMEDIATE` + 条件更新；锁冲突是可观测的 retryable 结果，不是静默成功。
- WAL 只有在 `doctor` 识别已修复 SQLite 构建后启用。不能只判断“大于某个旧最低版本”，因为官方同时发布了分支回补版。

### 三种“point in time”不得混用

1. **事务 snapshot**：SQLite read transaction 在存续期内看到稳定数据库版本；它只服务当前并发一致性。
2. **业务 as-of 查询**：`available_at <= requested_as_of`、版本/修订关系、`published_at/retrieved_at/event_at` 等必须由 schema 和查询显式保存。UPDATE 覆盖旧行后，数据库事务引擎不会替平台保留该业务历史。
3. **灾难恢复 PITR**：SQLite online backup 是某一时刻的一致副本，不是 PostgreSQL 式 base backup + 连续 WAL archive。若需要回到多个历史恢复点，必须保留版本化 backup bundles；run journal 也不能替代数据库备份。

因此 SQLite 是否被选中，不会改变 Provider 票已确定的四类时间和 append-only 修订要求。

### 一致备份与校验

Python `Connection.backup()` 可在其他 client 正在访问数据库时创建备份；SQLite online backup 完成后，目标是复制开始时的 source snapshot。直接用文件复制工具复制活动数据库可能混合新旧页面；若处于 WAL/rollback 状态，还可能漏掉 journal。应使用 backup API 或 `VACUUM INTO`。[Python `Connection.backup`](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)；[SQLite Backup API](https://www.sqlite.org/backup.html)；[safe backup approaches](https://www.sqlite.org/howtocorrupt.html#_backup_or_restore_while_a_transaction_is_active)

`VACUUM INTO` 也能生成 live consistent snapshot，优点是压缩并清除已删除内容，代价是更多 CPU 且中途崩溃的输出可能不完整；完成后在 NORMAL/FULL synchronous 下会调用持久化同步。[SQLite `VACUUM INTO`](https://www.sqlite.org/lang_vacuum.html#vacuuminto)

恢复校验必须同时运行：

- `PRAGMA integrity_check`，检查 B-tree、page、index 与约束结构；
- `PRAGMA foreign_key_check`，因为 `integrity_check` 不检查外键；
- 应用级 schema/revision、行数/关键不变量与 artifact hash 校验；
- 在隔离的新数据根执行一次真实启动/读取，再切换 canonical root。

[SQLite integrity and foreign-key checks](https://www.sqlite.org/pragma.html#pragma_integrity_check)

## DuckDB 与 Parquet：分析层候选，不是默认事务层

DuckDB 在一个读写进程内通过 MVCC 与 optimistic concurrency 支持多线程写；多个进程可以只读同一数据库，但原生 DuckDB 文件的稳定默认模型不是多进程读写。官方也警告共享目录、不同操作系统/文件系统和 NAS 的 file-lock 风险。[DuckDB concurrency](https://duckdb.org/docs/current/connect/concurrency)

DuckDB transaction 提供 snapshot isolation，WAL 可 checkpoint 到数据库文件；这能保证 DuckDB 自身事务一致性，但不自动提供 workflow lease、幂等 key、业务版本历史或外部 artifact 原子提交。[DuckDB transactions](https://duckdb.org/docs/current/sql/statements/transactions)；[DuckDB checkpoint](https://duckdb.org/docs/current/sql/statements/checkpoint)

DuckDB 对 Parquet 支持投影/过滤下推和多文件扫描；Parquet 文件把 column chunks 与 footer metadata 组织为列式文件，但 Parquet 规范本身不是事务 catalog、run journal 或 schema migration 系统。[DuckDB Parquet overview](https://duckdb.org/docs/stable/data/parquet/overview)；[Apache Parquet file format](https://parquet.apache.org/docs/file-format/)

DuckDB 官方对 partitioned write 的建议是避免大量小分区，通常每个分区至少约 100 MB；第一条单股纵向切片远未证明需要这种布局。`APPEND`/UUID 文件名只能避免文件名冲突，不能替代 SQLite 中冻结的 dataset manifest。[DuckDB partitioned writes](https://duckdb.org/docs/stable/data/partitioning/partitioned_writes)

若后续性能测试触发该扩展，应遵守：

- 每次 dataset version 写到新的不可变文件/目录，不原地覆盖分区；
- SQLite 记录明确文件列表、schema/version、row count、min/max time、hash 与 source snapshot；查询按 manifest，不用不受控 glob；
- DuckDB 仅作为同一应用进程的分析 adapter 或只读临时连接；它不改变 SQLite 的 journal 权威；
- 先以 SQLite 索引/分表/批量查询建立基线，再用真实 OHLCV/派生数据 benchmark 证明收益。

未出现这些证据前，引入 DuckDB/Parquet只会增加 schema evolution、备份、依赖固定和孤儿文件清理表面。

## PostgreSQL：能力真实，默认成本也真实

PostgreSQL 使用 MVCC，使 reader/writer 在多用户环境中低冲突并发；这正是 SQLite 单 writer 不再适合时的升级理由。[PostgreSQL MVCC](https://www.postgresql.org/docs/current/mvcc-intro.html)

备份能力分两类：

- `pg_dump` 在并发访问期间生成一致逻辑 snapshot，并适合跨版本恢复；
- base backup + 连续 WAL archive 支持恢复到 base backup 之后的目标时间/restore point；这是数据库灾备 PITR，不是业务事实的 `available_at` 查询。

[PostgreSQL `pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html)；[PostgreSQL continuous archiving and PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)

`pg_basebackup` 生成的 backup manifest 可由 `pg_verifybackup` 检查缺失/额外文件、size、checksum 与所需 WAL，但官方仍要求 test restore，因为 manifest 校验不能证明服务器一定可成功恢复。[PostgreSQL `pg_verifybackup`](https://www.postgresql.org/docs/current/app-pgverifybackup.html)

对当前单用户 Windows 切片，PostgreSQL 会新增 server lifecycle、端口/角色/凭据、service upgrade、WAL retention、备份工具版本和恢复演练。只有出现下列证据之一才重新评估：

- Web、daily worker 与其他进程确实需要持续并发写，SQLite 短事务 + retry 已无法满足；
- 数据库需由另一台机器访问或支持多人权限；
- RPO 明确要求连续 WAL/PITR，而版本化 SQLite backup bundles 不够；
- 数据规模/查询和运维能力已经证明服务端数据库的收益高于本地嵌入式复杂度。

## Schema migration 候选

### Alembic 不是 SQLite 的自动安全层

Alembic 对 SQLite 的复杂 ALTER 使用 batch “move and copy”：反射旧表、创建临时新表、`INSERT ... SELECT`、drop 旧表、rename 新表。引用目标表的外键会妨碍 drop；官方文档说明 batch workflow 可能需要关闭 FK enforcement，并且 unnamed CHECK constraints 不会自动恢复。[Alembic SQLite batch migrations](https://alembic.sqlalchemy.org/en/latest/batch.html)

因此 Alembic 只在后续决定使用 SQLAlchemy 时成立；不能只为一个零依赖 SQLite schema 引入 SQLAlchemy + Alembic，也不能把 autogenerate 当迁移审计。若采用，migration 必须显式审查生成 SQL、命名全部约束、先备份、独占 writer、迁移后执行 FK/integrity 和应用不变量测试。

### 零 ORM 候选也不能只写一个整数

SQLite 的 `PRAGMA user_version` 是留给应用使用的整数，SQLite 自身不解释它。[SQLite `user_version`](https://www.sqlite.org/pragma.html#pragma_user_version)

stdlib 候选应至少有 `schema_migration(version, name, sha256, applied_at, app_version)` ledger 和不可变、顺序化 migration 文件；启动拒绝未知的未来 schema，`migrate` 在统一维护入口中显式执行。每个 migration 的标准协议是：

1. doctor 检查 SQLite runtime、磁盘余量和无活动 writer；
2. 生成并验证迁移前 backup bundle；
3. 在一个可回滚事务内执行兼容 DDL/DML；需要 table rebuild 时使用显式新表/复制/校验/rename；
4. 同事务写 migration ledger/hash；
5. 执行 `integrity_check`、`foreign_key_check`、schema introspection 与领域不变量；
6. 失败则保留原库和失败日志，不通过“删库重建”恢复。

选择 Alembic 还是 versioned SQL ledger 交给后续架构票；本票排除“没有迁移工具”和“应用启动时悄悄改 schema”。

## 原子 artifact 发布与 hash 权威

Python `os.replace` 在成功时提供原子 rename，要求 source/destination 位于同一文件系统；跨平台覆盖已有 file 应使用 `replace` 而不是依赖 Windows `rename` 行为。[Python `os.replace`](https://docs.python.org/3/library/os.html#os.replace)

适合本平台的最小 crash-safe 顺序是：

1. 在最终目录同卷创建唯一 sibling temp file；
2. 流式写入，`flush` + file `fsync`，计算 SHA-256 与 size；
3. final path 只由 hash 派生，例如 `objects/sha256/ab/cd...`；若已存在则验证 hash/size 并复用；
4. `os.replace(temp, final)` 发布不可变 object；Windows sharing violation 明确失败并重试/报告，绝不改写现有 object；
5. 在一个短 SQLite transaction 中插入 artifact row、manifest relation、node completion 和 state transition；
6. crash 后清理超龄 temp 和没有 DB 引用的 orphan object，但从不删除仍被 manifest 引用的 hash。

这个顺序的 crash matrix 是确定的：rename 前 crash 只留下 temp；rename 后、DB commit 前 crash 只留下可回收 orphan；DB commit 后引用必然指向已经发布的 immutable file。反向顺序会产生数据库已经提交但文件尚不存在的坏引用。

`ResearchRun` canonical JSON 和 derived HTML 可以是两个 artifact row，后者通过 `derived_from` 指向前者；重渲染创建新 artifact/version，不覆盖旧 HTML 或 ResearchRun。SQLite 行内可保存小型、需要事务读取的结构化字段，但不应把原始 PDF/HTML/图像 BLOB 全塞入事务表来回避文件协议。

## 可恢复 workflow 与 run journal 模式

run journal 是业务状态，不是 debug log。第一切片所需最小概念候选：

- `workflow_run`：独立于 `ResearchRun.run_id` 的 identity、workflow version、request/dedupe key、data snapshot、code version、started/finished/status；
- `node_attempt`：node key/version、attempt number、typed input/cache key、lease/heartbeat、started/finished/outcome/error；
- `run_transition`：append-only previous/new state、reason、occurred_at、attempt；
- `artifact` / `artifact_manifest_item`：hash、size、media type、schema/version、relative object path、producer attempt、derived/source relation；
- `provider_attempt` / cursor commit：外部请求结果、raw hash、retry/rate-limit/error 与 next cursor。

恢复协议候选：

- workflow/node claim 与状态条件更新在同一事务，唯一约束阻止相同 dedupe/cache key 重复成功；
- `running` 不是完成证据。进程重启后，过期 lease 的 attempt 标为 `abandoned`，创建新 attempt；历史行不覆盖；
- 已完成节点只有在 node version、typed input hash、data snapshot、parameters/code version 均匹配时才可 cache hit；
- 非幂等外部 side effect 不在本切片；Provider 获取和 artifact publish 以 raw/object hash 幂等复用；
- node completion、artifact references 和 cursor advance 同事务提交；不能先推进 cursor 再登记 raw artifact；
- `ResearchEngine` 仍然只被调用一次并保持无 I/O，adapter 在调用前组装 snapshot/request，调用后持久化结果。

这是一组可验证的 journal 模式，不是对 ticket 08 的最终表结构或 workflow registry 决策。

## 跨 SQLite 与文件的 backup / restore bundle

外部 immutable objects 意味着“备份 `.sqlite3` 一个文件”不完整。候选一致备份协议：

1. 使用 SQLite online backup API 写到同卷 staging DB；完成后关闭目标连接；
2. 对 staging DB 执行 integrity/FK/schema 检查，并从这个冻结副本枚举它实际引用的 artifact hashes；
3. 把这些 immutable objects 复制到 staging bundle，逐个验证 size/hash；新运行可继续产生 object，因为冻结 DB 不会引用它们；
4. 生成 `backup_manifest.json`，记录 format version、app/schema version、source DB UUID、created_at、DB hash、每个 object hash/size/path、代码版本与检查结果；
5. 将完整 staging bundle 发布到新名字。失败 bundle 不进入保留集合；不得覆盖最后一个已验证备份。

恢复必须是离线/独占写模式：恢复到新的数据根，先验证 manifest、全部 hash、SQLite integrity/FK、schema compatibility 和最低应用查询，再通过配置/root pointer 切换；不得在活跃连接上覆盖或 rename 数据库文件。恢复后可以显式迁移到当前 schema，但必须保留原 backup bundle。

保留期、备份介质与加密仍在 map 的 fog 中；只有物理布局与 RPO/RTO 确定后才能精确决定。第一切片至少要有一个真实 backup/restore round trip 和故意缺文件/改 hash 的失败用例。

## Windows 路径与文件锁边界

- DB 中只保存相对 data-root 路径或纯 hash，不保存开发机绝对路径；restore 可迁移到不同盘符。
- object path 只使用 ASCII hash 分片，避开 Windows reserved name、冒号、尾随点/空格和用户输入路径穿越。
- 沿用当前 CLI 的 symlink/reparse-point 防护思想；data root、staging、restore target 必须 resolve 并验证都在预期根内。
- 活跃 SQLite/DuckDB 文件不放网络盘或云同步目录；WAL 官方明确要求同机，DuckDB 也警告 shared filesystem locks。
- Windows 打开的文件/目录可能导致 `PermissionError`/sharing violation；发布与 restore 必须失败可见、有界重试，不用删除/覆盖来“修好”。
- temp、final object 和 DB 同卷，确保 rename 不退化为 copy；备份到其他卷走显式 copy + hash verify。

## 强制测试与故障注入矩阵

| 维度 | 最低测试 |
|---|---|
| SQLite runtime | `doctor` 报实际 `sqlite_version`、journal/synchronous/foreign_keys；已知受影响 WAL 构建不得启用多连接 WAL |
| 事务策略 | Python 3.10/3.11/3.12+ 受支持运行时上验证 commit/rollback；复现并防止 `autocommit=True + Connection.commit()` 假提交 |
| 并发 | Web reader 持续查询时 writer 成功；第二 writer 得到受控 busy/retry；长 reader/checkpoint starvation 有监测与上限 |
| migration | 空库到 head、每个历史 fixture 到 head、重复 migrate no-op、未知未来 revision fail closed、table rebuild 保留 named constraints/FK |
| journal | 相同 dedupe key 重跑不重复；stale running attempt 恢复为新 attempt；已完成 cache key 改任一输入/version 即失效 |
| crash injection | 在 temp write、fsync、rename、DB manifest commit、node completion、cursor advance 前后 kill；恢复后只有 temp/orphan 或完整引用，不得 missing object |
| backup | 写入并发期间 online backup；恢复后 DB integrity/FK、schema、row/domain invariants、全部 object hash 通过 |
| negative restore | 缺 object、改 DB、改 hash、未知 schema、空间不足、目标已有活跃 root 均 fail closed |
| Windows | 空格/Unicode data root、不同盘符 restore、reparse point、sharing violation、长路径与只读备份介质 |
| DuckDB/Parquet gate | 在引入前用真实数据 benchmark SQLite baseline；manifest 冻结文件列表；schema drift、partial file、many-small-files 与多进程写测试 |
| 回归 | 现有 35 项 `ResearchEngine`/CLI 行为测试继续通过；研究内核不得导入 DB、DuckDB、SQLAlchemy 或文件 adapter |

## 依赖、许可与维护边界

- SQLite deliverable code/documentation 已由作者置于 public domain。[SQLite copyright](https://sqlite.org/copyright.html)
- DuckDB 使用 MIT license；若引入，应固定项目依赖版本并记录其 bundled third-party notices。[DuckDB license](https://github.com/duckdb/duckdb/blob/main/LICENSE)
- Apache Parquet format 使用 Apache-2.0；采用文件格式也要固定实际 writer/reader implementation 和 feature compatibility，不能只写“Parquet”。[parquet-format license](https://github.com/apache/parquet-format/blob/master/LICENSE)；[format compatibility](https://parquet.apache.org/docs/file-format/versions/)
- Alembic/SQLAlchemy 均为 MIT family；Alembic 当前官方文档已经明确 SQLite batch 限制。若采用，版本与 SQLAlchemy compatibility 一起固定。[Alembic license](https://github.com/sqlalchemy/alembic/blob/main/LICENSE)
- PostgreSQL 使用 PostgreSQL License。[PostgreSQL license](https://www.postgresql.org/about/licence/)

本票不因许可证宽松就建议引入依赖；许可证只是必要门，运行契约和恢复复杂度仍需单独证明。

## 交给后续 Wayfinder 票据的清晰问题

无需新增 ticket，当前结果已经把 fog 分配到既有票据：

- [决定分层存储、时间语义与同步契约](../issues/07-decide-data-storage-and-pit-contracts.md)：在“SQLite + immutable object store”与更小的 SQLite-only 变体之间决定第一切片物理落点；明确最小 schema、四类时间、revision/as-of 查询、是否/何时触发 Parquet；决定 WAL 修复运行库或 rollback journal。
- [决定 Codex 控制面、确定性运行时与 run journal 边界](../issues/08-decide-control-plane-runtime-and-run-journal.md)：决定 workflow/node/attempt/transition schema、lease/retry/cache key、artifact publish transaction、统一 `backup/restore/doctor/migrate` 入口和中断恢复验收。
- map 中既有“备份介质、保留期、加密和恢复演练细节”继续留在 fog，等待数据根布局与 RPO/RTO 被具体化；本票只提供一致 bundle 与测试边界。

## 研究判断边界

本研究支持把 SQLite + 内容寻址文件作为后续设计的默认对照候选，但**没有**批准数据库实现、schema、Alembic、DuckDB、Parquet 或 PostgreSQL 依赖。任何采用结论必须在后续 HITL 设计票中结合第一条用户故事、Web/worker 进程模型、数据量、RPO/RTO 和当前 SQLite runtime 修复路径作出。
