# 决定分层存储、时间语义与同步契约

Type: `grilling`
Mode: `HITL`
Status: resolved
Blocked by: 02, 03, 05

## Question

基于当前 MVP 审计、领域语言和 Provider/存储调研，第一条纵向切片的 Raw、Normalized、Derived、Artifacts 应分别落在哪里，`as_of`、`published_at`、`available_at`、`retrieved_at`、交易日/时区/复权模式如何进入主键、版本和查询语义，Provider adapter、增量游标、缓存键、TTL、强制刷新、内容哈希、幂等 upsert、staleness 和质量错误应遵守什么确定性契约？该决策必须给出断网缓存、数据修订、公司行动、同日重跑和迁移升级的具体反例，并明确第一条切片所需的最小 schema，而非一次设计完整平台数据库。

## Comments

- 用户确认第一条切片采用“SQLite 事务权威 + SHA-256 内容寻址不可变文件库”：SQLite 保存结构化数据、版本、时间、游标与引用；Raw、canonical ResearchRun JSON、HTML/PDF 等不可变内容进入 object store；不在本切片引入 DuckDB、Parquet 或 PostgreSQL。
- 用户确认 PIT 截面规则：平台以 UTC `as_of_at` 瞬时为权威截点，另存 `market_timezone=Asia/Shanghai` 与 `session_date`；`DataSnapshot` 只接纳 `available_at <= as_of_at` 的版本；`published_at` 与 `retrieved_at` 不替代 `available_at`；date-only 时间保留精度且默认下一交易时段可用；现有 `ResearchRequest.as_of_date` 由冻结快照派生。
- 第三个 grilling 问题直接采用推荐答案：`as_of_at` 是快照查询条件，不进入 normalized logical key；各数据集以 `dataset + security_id/market_id + natural_key` 标识逻辑记录，其中 OHLCV natural key 含 `session_date + interval`、财务事实含 `period_end + statement_scope + concept/unit`、公告含发布者公告 ID 或其确定性替代键。每次 raw/normalized 修订均新增不可变版本；`published_at/available_at/retrieved_at` 是版本属性。normalized version identity 由 schema/normalizer/source raw hash/canonical payload 决定；跨 Provider 冲突保留为不同来源版本，不用 upsert 静默择一。`DataSnapshot` 保存 cutoff、query-policy version 与有序 member version IDs，并同时记录 membership hash；其 identity 不靠“最新数据”动态解析。canonical OHLCV 不把复权模式放入 key；复权模式只进入 derived-series key。
- 第四个 grilling 问题直接采用推荐答案：Normalized 只保存交易所时区/日历下的未复权 OHLCV；公司行动作为官方事件的 append-only 版本，第三方复权因子只作结构化输入或交叉核验。`none / forward / backward` 复权序列属于 Derived，其 key 至少包含 security、interval、range、adjustment mode、factor-set version、input snapshot、algorithm version。PIT 计算只能使用在 cutoff 前已可得的公司行动/因子；更正或未来公司行动产生新 factor set 和新 derived version，不能改写旧快照或旧图表。图表与标注必须携带 adjustment mode、factor-set version 和 data-snapshot reference，禁止把今天下载的前复权历史冒充历史时点当时可得序列。
- 第五个 grilling 问题直接采用推荐答案：Provider contract 分为 `fetch(FetchRequest) -> FetchBatch` 与 `normalize(RawEnvelope) -> NormalizedBatch`；fetch request 明确 provider/adapter version、dataset、security/market、range、canonical params、dataset cursor 与不可逆 `credential_scope_id`，不得包含明文凭据。Raw envelope 原样保存 bytes/hash、真实 source URL、脱敏参数、响应状态/必要 headers、retrieved time、source/terms profile 与时间精度。结果状态限定为 `complete / partial / missing / failed / rate_limited`，fallback 不抹除前序 attempt。生产 adapter 与 fixture adapter 输出同一 Raw envelope；fixture 禁止联网并复用完全相同 normalizer/quality path。Provider 不直接写业务表；raw object、normalized versions、quality result 与 cursor advance 在编排层通过同一短事务登记，失败不得提前推进 cursor。
- 第六个 grilling 问题直接采用推荐答案：raw request key 是 provider + adapter version + dataset/endpoint + canonical params + credential scope 的确定性 hash；freshness 由带版本的 dataset policy 判定，不设全局 TTL。主数据每日最多验证一次，交易日历按周/跨年和官方变更验证，日 OHLCV 在最后完整交易日及 provider 延迟后到期，公告/公司行动每次 daily 增量验证，内容寻址 raw 永不过期。`force_refresh` 只绕过 freshness 并创建 revalidation attempt，不覆盖 raw/cursor；同 hash 复用 object 与 normalized version，变 hash 才新增版本。失败/空结果只进入有界 negative cache，尊重 `Retry-After`，不能生成“零值/无公告”事实。offline 模式禁止 adapter 网络调用，只读取 cutoff 合法的最后快照并返回 `stale_by + freshness_basis + last_success_at`；没有缓存则明确 `missing`，不得静默降级为在线或假数据。
- 第七个 grilling 问题直接采用推荐答案：upsert 只做三件事——按 logical natural key 找到记录、按 immutable version hash 去重、为新内容追加 revision；禁止 UPDATE 覆盖历史版本。数据库唯一约束保证 raw hash、request revalidation、normalized version、snapshot membership 与 dataset cursor commit 幂等。同日重跑命中相同 request/content/snapshot 时复用数据对象，但仍保留独立 attempt/run；发现新内容时产生新 raw、revision 和 snapshot。质量结果至少分 `pass / warning / quarantine / blocking`：warning 可入快照但必须传播，quarantine 不可入快照，blocking 终止该 dataset/capability。schema drift、身份/币种/单位冲突、非法 OHLC、未知交易日、无法解释的公司行动/复权冲突、关键官方来源矛盾均 fail closed；跨 Provider 冲突保留双方并要求显式 source policy/人工复核。staleness 按 dataset 和消费能力判断：陈旧 OHLCV 阻止“当日” MarketSnapshot/计划评估，陈旧公告索引允许回看旧 ResearchRun 但必须显示最后成功同步点；第三方 fallback 不恢复正式财务/估值权限。
- 第八个 grilling 问题直接采用推荐答案：当前本机 SQLite 3.50.4 未通过已知 WAL-reset 修复门，第一条切片默认本机卷上的 rollback journal、`foreign_keys=ON`、受测 synchronous/busy-timeout 与单短 writer；只有统一 `doctor` 精确识别 3.51.3 或官方回补修复构建后，才可显式迁移到 WAL。活跃 DB 不放 OneDrive/SMB/NAS。当前仓库无 ORM 依赖，因此 schema migration 采用不可变顺序 SQL + `schema_migration(version,name,sha256,applied_at,app_version)` ledger；启动拒绝未知未来版本或 hash 漂移，迁移由统一入口显式执行，先做已验证 backup、独占 writer、事务/显式 table rebuild，随后执行 integrity/FK/schema/domain checks；失败保留原库，禁止删库重建。若以后因其他架构决策采用 SQLAlchemy，再单独评估 Alembic，不能在本票预装。
- 第九个 grilling 问题直接采用推荐答案：本票只锁定第一切片的数据基础表，不提前决定 workflow、annotation、trade-plan 的专用表。最小 schema 是 `schema_migration`；稳定证券身份与代码历史 `security`, `security_identifier`；内容寻址对象 `object_blob`；抓取/重验证与游标 `provider_attempt`, `sync_cursor`；逻辑记录与不可变版本头 `normalized_record`, `normalized_version`；dataset 专用 1:1 typed payload `market_session_version`, `ohlcv_version`, `corporate_action_version`, `filing_version`, `financial_fact_version`；质量问题 `data_quality_issue`；冻结快照与成员 `data_snapshot`, `data_snapshot_member`；派生数据及输入引用 `derived_dataset`, `derived_input`；产物对象登记与派生关系 `artifact`, `artifact_relation`。`normalized_version` 统一承载 source/raw、四类时间、precision/basis、schema/normalizer/content hash、quality 与 supersedes；typed 表保存可约束、可索引的金融字段，不把核心数字只藏在 JSON。票据 08/09/10 可新增 journal/manifest、annotation version、trade-plan/evaluation 表，但必须外键引用这里的 snapshot/version/artifact 身份。
- 第十个 grilling 问题直接采用推荐答案并锁定反例：断网时，若只有上一交易日快照，则历史回看可继续但“当日” MarketSnapshot/计划评估因 stale 被阻断；无缓存返回 missing。财务更正发布后新增 raw hash/version，修订前 cutoff 仍选旧值、修订后 cutoff 才选新值。未来分红/拆并股导致前复权历史变化时，新建 factor set/derived dataset，旧图表与标注继续引用旧因子版本。相同 cutoff/请求/内容的同日重跑复用 object、normalized versions 和 snapshot，但新增 attempt/run；较晚 cutoff 看见新收盘数据或公告时创建新 snapshot。schema 升级不得为旧 date-only 数据伪造时刻；migration 失败保留旧库并 fail closed，成功升级后旧 snapshot membership/hash 仍可解析。另加两个必测失败：Provider HTTP 200 空响应只产生 short negative cache，不删除旧记录；object rename 后、DB commit 前崩溃只留下可回收 orphan，DB commit 后不得出现 missing object。
- 第十一个 grilling 问题直接采用推荐答案：`availability_basis` 使用受控枚举。官方精确发布时刻为 `publisher_timestamp`；只有日期为 `conservative_next_session`，在目标市场下一交易时段起才可见；完整日线等由交易所日历确定的收盘数据可用 `market_close_plus_provider_delay`，延迟规则必须带 provider/policy version；第三方明确且已保存证据的更新时间可用 `documented_provider_schedule`；其余只能用 `retrieved_only`，令 `available_at = retrieved_at`，不得根据 period end、文件名或今天看到的页面倒推历史可用时间。每个修订版本独立计算 availability；缺少 basis 的版本不得进入 PIT snapshot。
- 第十二个 grilling 问题直接采用推荐答案：cursor 由 provider + adapter version + dataset + scope + cursor-schema version 唯一标识，并保存 opaque payload 与对应成功 attempt/raw hash。OHLCV cursor 使用最后完整 session date，同时按 policy 回看最近若干 session 捕捉更正；公告/filing 使用 `(published_at precision, stable source id/page token)` 并按时间窗重叠抓取；交易日历保存已覆盖 range 与 source revision；公司行动/财务使用发布时点 + source id/revision 的复合 cursor。去重依赖内容/版本键而非假设 cursor 无重复。只有 batch complete，或 partial 明确声明且已提交安全 checkpoint 时，才在同一事务推进 cursor；rate limit、empty、schema drift、quarantine、blocking 或 artifact 未登记均保持旧 cursor。
- 第十三个 grilling 问题直接采用推荐答案：snapshot builder 使用带版本的 dataset `source_policy`。先筛选 `available_at <= as_of_at` 且质量为 pass/warning 的版本；同一 logical record + source 内只沿显式 `supersedes`/source revision 链选择 cutoff 时最新版本，不能按 retrieved_at 覆盖。再按数据集权威顺序选择：官方披露控制 filing/critical financial/company action，配置的结构化行情 Provider 控制 OHLCV/calendar，其他来源仅 fallback/cross-check。相同权威级别出现超出 tolerance 或无法解释的冲突时生成 blocking quality issue，不自动平均或取最新。snapshot 固化 source-policy version、所有入选 version IDs、被排除冲突摘要与 freshness 结果，使以后查询不重新解释“当前最佳来源”。

## Answer

已在[当前 MVP 审计](01-audit-current-mvp-and-reuse-seams.md)、[领域语言决策](02-sharpen-platform-domain-language.md)、[Provider/PIT 研究](../research/data-providers-pit-cache.md)和[本地存储/恢复研究](../research/local-runtime-store-and-recovery.md)的边界内完成 HITL grilling。第一条切片采用以下确定性数据合同；它是后续 Spec 的设计输入，不代表数据库或平台已经实现。

### 1. 物理分层

采用单一事务权威 **SQLite + SHA-256 内容寻址不可变文件库**，不在第一条切片引入 DuckDB、Parquet 或 PostgreSQL：

| 层 | 物理落点 | 不变量 |
|---|---|---|
| Raw | `<data_root>/objects/sha256/<prefix>/<hash>`；SQLite 只存抓取 envelope、hash 和引用 | 保存原始 bytes/PDF/JSON/CSV，不可变、不可覆盖；相同 bytes 复用 object |
| Normalized | SQLite 的通用 version header + dataset-specific typed tables | 金融主字段可约束、可索引；不用一个 JSON/EAV 大表隐藏数值与单位 |
| Derived | SQLite 保存 identity、算法/参数/输入引用和小型结构化结果；较大序列/JSON 放 object store | 必须引用冻结 DataSnapshot、算法版本和全部输入；重新计算产生新版本 |
| Artifacts | object store 保存 ResearchRun JSON、HTML/PDF/图像等；SQLite `artifact` 登记类型、schema、hash 与派生关系 | canonical ResearchRun JSON 与 HTML 是两个 artifact；重渲染不改写旧对象 |

文件发布顺序固定为同卷 sibling temp -> write/flush/fsync/hash -> `os.replace` 到 hash path -> 短 SQLite 事务登记 object/reference/version/cursor。rename 前崩溃只可留下 temp，rename 后事务前崩溃只可留下 orphan，事务提交后不得存在 missing object。数据库只保存相对 data-root 路径或 hash，不保存开发机绝对路径。

### 2. 时间与 PIT 合同

- `event_at` 或 `period_end` 表示经济事实发生/覆盖的时点，不表示用户当时已经知道。
- `published_at` 原样保存发布者标注的时间或日期及其 `time_precision`；日期精度不得伪造为午夜。
- `available_at` 是唯一的历史可见性门禁。`DataSnapshot` 只允许 `available_at <= as_of_at` 的版本。
- `retrieved_at` 是本机实际获取时刻，只用于采集审计，不证明更早可用。
- 权威 cutoff 是 UTC `as_of_at` 瞬时；同时保存 `market_timezone=Asia/Shanghai`、交易所日历版本与 `session_date`。现有 `ResearchRequest.as_of_date` 从冻结快照派生，只作兼容字段。
- exact instant 以 UTC 整数微秒或等价严格格式保存；date-only source value 单独保存 local date/precision，不能混入 exact timestamp 列。

`availability_basis` 必须是受控值：

1. `publisher_timestamp`：官方精确发布时刻；
2. `conservative_next_session`：只有日期时，从目标市场下一交易时段起可用；
3. `market_close_plus_provider_delay`：完整日线等由交易所收盘时间加已版本化 Provider 延迟确定；
4. `documented_provider_schedule`：保存过证据的第三方更新时间规则；
5. `retrieved_only`：无法证明历史可用性时令 `available_at = retrieved_at`。

缺少 basis 或无法解析为确定 cutoff 的版本不得进入 PIT snapshot。

### 3. 身份、版本和查询

- `as_of_at` 是查询条件，不进入 normalized logical key。
- logical key 按 dataset 定义：OHLCV 至少为 security + session date + interval；财务事实为 security + period end + statement scope + concept + unit/currency；公告优先使用发布者 stable ID，否则使用受版本控制的确定性替代键。
- `normalized_record` 标识逻辑事实；每个 raw/normalized 修订追加不可变 `normalized_version`。version identity 包含 schema version、normalizer version、source raw hash 与 canonical typed payload hash。
- `published_at/available_at/retrieved_at` 是版本属性，不是 logical key。修订和更正不能 UPDATE 覆盖旧版本。
- `DataSnapshot` 固化 `as_of_at`、query/source/freshness policy versions、有序 member version IDs、membership hash、质量与陈旧度摘要。以后回看只按成员表解析，不重新查询“当前最新”。
- snapshot builder 先过滤 cutoff 与质量，再在同一来源的显式 revision/supersedes 链内选当时最新版本，最后应用 dataset-specific source policy。官方披露控制 filing、关键财务和公司行动；配置的结构化行情源控制 OHLCV/日历；同级不可解释冲突 fail closed。

### 4. 未复权 canonical 与公司行动

Normalized OHLCV 只保存交易所日历/时区下的未复权价格与成交量。公司行动作为官方事件独立 append-only 版本；第三方复权因子只作结构化输入或交叉核验。

`none / forward / backward` 复权序列属于 Derived，其 identity 至少包含 security、interval、range、adjustment mode、factor-set version、input snapshot、algorithm version。PIT 计算只能使用 cutoff 前已可得的公司行动/因子。未来分红、拆并股或更正产生新 factor set 和新 derived dataset；旧图表、标注、研究和评估继续引用旧 factor set，不静默迁移价格坐标。

### 5. Provider、缓存和 cursor

Provider contract 分两段：

```text
fetch(FetchRequest) -> FetchBatch[RawEnvelope]
normalize(RawEnvelope) -> NormalizedBatch
```

FetchRequest 明确 provider/adapter version、dataset/endpoint、security/market、range、canonical params、dataset cursor 与不可逆 `credential_scope_id`；不含明文 Token。RawEnvelope 保存原始 object hash、真实来源 URL、脱敏参数、响应状态/必要 headers、retrieved time、source/terms profile 与时间精度。fixture adapter 禁止联网，并与生产 adapter 复用相同 normalizer/quality path。

结果状态限定为 `complete / partial / missing / failed / rate_limited`；fallback 成功不抹除前序 attempt。raw request key 是 provider + adapter version + dataset/endpoint + canonical params + credential scope 的 hash。

缓存使用带版本的 dataset freshness policy，而不是全局 TTL：主数据每日最多验证一次；交易日历按周、跨年或官方变更验证；日 OHLCV 在最后完整交易日及 Provider 延迟后到期；公告/公司行动每次 daily 增量验证；内容寻址 raw 永不过期。`force_refresh` 只绕过 freshness 并创建 revalidation attempt，不覆盖 raw。相同响应 hash 复用 object/normalized version；变化才新增版本。空响应或失败只作有界 negative cache，尊重 `Retry-After`，不能生成零值或“无公告”事实。

cursor 由 provider + adapter version + dataset + scope + cursor-schema version 标识：OHLCV 用最后完整 session date 并带 revision lookback；公告/filing 用发布时间精度 + stable source ID/page token 并重叠抓取；日历保存覆盖 range/source revision；公司行动/财务使用发布时点 + source ID/revision。只有 complete，或明确支持安全 checkpoint 的 partial batch，才能在 raw、normalized、quality 与 cursor 同一短事务中前移；empty、rate limit、schema drift、quarantine、blocking 或缺 object 时保持旧 cursor。

### 6. 幂等、质量和 staleness

upsert 只允许：按 logical key 找记录、按 version hash 去重、为新内容追加 revision。唯一约束覆盖 raw hash、request revalidation、normalized version、snapshot membership 与 cursor commit。同一 cutoff/请求/内容重跑复用数据对象与快照，但保留独立 provider attempt/workflow run；较晚 cutoff 看到新内容时形成新快照。

质量状态为 `pass / warning / quarantine / blocking`：warning 可入快照并传播；quarantine 不可入快照；blocking 终止 dataset/capability。schema drift、身份/币种/单位冲突、非法 OHLC、未知交易日、无法解释的公司行动/复权冲突、关键官方来源矛盾均 fail closed。跨 Provider 冲突保留双方，不自动平均或取“最后抓到的值”。

offline 模式禁止网络，只能读取 cutoff 合法的最后快照，并返回 `stale_by + freshness_basis + last_success_at`。没有缓存即 `missing`。陈旧 OHLCV 阻止“当日” MarketSnapshot 和计划评估；陈旧公告索引允许回看旧 ResearchRun，但必须显示最后成功同步点。第三方 fallback 不能恢复正式财务/估值权限。

### 7. 第一条切片的数据基础最小 schema

| 表 | 最小责任/关键约束 |
|---|---|
| `schema_migration` | `version` PK，name/hash 唯一，applied_at/app_version；检测文件漂移和未来 schema |
| `security`, `security_identifier` | 稳定 Security identity；市场代码/名称带有效区间，改代码不换 security_id |
| `object_blob` | SHA-256 PK、size、media type、relative path、created_at；文件不可变 |
| `provider_attempt` | request key、provider/adapter/dataset、状态、时间、raw hash、错误、source/terms profile；所有 fallback/revalidation 可审计 |
| `sync_cursor` | provider/dataset/scope/cursor schema 唯一；payload、committed attempt/raw hash；条件更新防并发覆盖 |
| `normalized_record` | dataset + subject + natural-key hash 唯一；保存 canonical natural-key representation |
| `normalized_version` | record/source/raw、四类时间、precision/basis、schema/normalizer/content hash、quality、supersedes；不可变 |
| `market_session_version` | market、session date、open/close instant、timezone、状态；1:1 version payload |
| `ohlcv_version` | security/session/interval、未复权 OHLCV/amount/currency；价格与金额用 integer + scale 或等价 exact decimal，不用 binary float |
| `corporate_action_version` | action type、ex/record/pay dates、精确 ratio/cash terms、official filing/source ref |
| `filing_version` | security、source filing ID/type/title/period、official object ref |
| `financial_fact_version` | concept、period/scope、exact value + scale、unit/currency、filing ref |
| `data_quality_issue` | attempt/version/snapshot scope、稳定 error code、severity、details、created_at |
| `data_snapshot`, `data_snapshot_member` | cutoff、market context、policy versions、membership hash、freshness/quality；成员唯一且不可变 |
| `derived_dataset`, `derived_input` | kind/algorithm/params/adjustment/factor set/object ref；输入 snapshot/version 全引用 |
| `artifact`, `artifact_relation` | object、kind/media/schema、derived-from/source relation；后续 manifest 引用的稳定基础 |

票据[决定 Codex 控制面、确定性运行时与 run journal 边界](08-decide-control-plane-runtime-and-run-journal.md)、[原型化 K 线与持久化标注 seam](09-prototype-chart-and-annotation-seam.md)和[决定交易计划状态机与市场状态评估接口](10-decide-trade-plan-and-market-evaluation.md)分别增加 workflow/journal/manifest、annotation version 和 trade-plan/evaluation 表；它们必须引用这里的 snapshot/version/artifact identity，不得重新定义数据时间。

### 8. SQLite 与迁移门

当前本机 SQLite 3.50.4 未通过已知 WAL-reset 修复门，因此第一条切片默认 rollback journal、`foreign_keys=ON`、受测 synchronous/busy-timeout 和单短 writer；活跃 DB 不放 OneDrive/SMB/NAS。只有统一 `doctor` 精确识别 SQLite 3.51.3 或官方回补修复构建后才可显式启用 WAL。

当前不为迁移单独引入 ORM。采用不可变顺序 SQL + migration ledger；迁移前生成并验证 backup、取得独占 writer，迁移后执行 integrity/FK/schema/domain checks。失败保留旧库并拒绝启动不兼容 schema，禁止删库重建。未来若其他架构决策采用 SQLAlchemy，再单独评估 Alembic。

### 9. 必须通过的反例

| 反例 | 必须结果 |
|---|---|
| 断网且只有上一交易日行情 | 可回看旧 snapshot/ResearchRun；当日 MarketSnapshot/计划评估因 stale 阻断 |
| 官方发布财务更正 | 新 raw/version；更正前 cutoff 仍选旧值，更正后才选新值 |
| 后续公司行动改变前复权历史 | 新 factor set/derived dataset；旧快照、图表和标注不变 |
| 同日相同 cutoff/content 重跑 | 复用 object/version/snapshot；新增 attempt/run，不重复入库 |
| 同日较晚 cutoff 出现收盘数据或公告 | 新 DataSnapshot；不修改较早 snapshot |
| Provider HTTP 200 但空 payload | short negative cache/error；不删除旧数据、不写零值 |
| date-only 旧数据迁移到新时间 schema | 保留 date precision/basis；不得回填虚构时刻 |
| migration 中途失败 | 旧库和已验证 backup 可用；应用 fail closed，不半升级 |
| object rename 后、DB commit 前崩溃 | 只有可回收 orphan；不得产生 committed missing reference |

这组决策没有引出新的 Wayfinder ticket，也不改变 map 中关于备份介质、保留期和加密的 fog。`Raw / Normalized / Derived / Artifacts` 是总任务 Prompt 已固定的数据层分类，本次没有改变业务领域词义，因此无需修改 `CONTEXT.md`。
