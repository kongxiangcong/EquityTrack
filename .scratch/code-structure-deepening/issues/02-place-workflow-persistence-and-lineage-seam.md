# 决定 Workflow persistence 与 artifact lineage seam

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

决定 `WorkflowRepository` 中 SQL、锁、事务、对象发布、checkpoint/manifest 持久化与 artifact lineage、frozen market calibration、领域不变量之间的唯一职责分界：目标深模块各自拥有何种小接口和稳定错误合同，领域校验如何只消费类型化证据而不依赖 SQLite，仓储如何原子持久化已验证结果，同时避免把现有大类拆成 repository facade 加一组转发对象。

## Answer

### 决策

把当前 `WorkflowRepository` 替换为两个职责不同、依赖单向的深 module：

1. **`ArtifactLineage` 领域 module**：无状态、无 I/O，只拥有 typed research artifact graph、frozen market calibration 和 artifact identity 的领域不变量。它以 immutable typed evidence 为输入，输出已经过验证且 identity 已固定的 persistence plan；不认识 SQLite、filesystem、lock、clock 或 transaction。
2. **`WorkflowLedger` persistence module**：workflow、checkpoint、manifest、typed research artifact graph 与 content-addressed object 的唯一 persistence path。它独占 SQLite schema mapping、跨进程 writer lock、transaction、object publication ordering、幂等/冲突、typed reads 与 integrity audit；它在同一 aggregate mutation 内物化 typed evidence、调用 `ArtifactLineage`，然后原子持久化验证结果。

依赖方向固定为：

`application workflow task` -> `WorkflowLedger` -> `ArtifactLineage`

`WorkflowLedger` 同时依赖 SQLite、data-root writer lock 和本地 content-addressed storage 这些具体 local-substitutable dependencies。这里不建立 `ArtifactRepository`、`ManifestRepository`、`SnapshotEvidenceRepository`、`WorkflowRepositoryFacade` 或单实现 port；它们只会把同一 transaction 拆成一组转发对象，降低 locality。SQLite temp data root 已是生产实现的真实测试替身，不需要为了 mock 暴露 connection。删除 `WorkflowLedger` 会把 SQL、锁、crash ordering 和一致性判断散回多个 caller，因此它通过 deletion test；删除任何只转发其方法的 wrapper 则只需内联一行，因此不得创建。

### `ArtifactLineage` 的唯一 interface

公开 interface 是一个领域操作：

`validate(ArtifactSubmission, FrozenLineageEvidence) -> ValidatedArtifactCommit`

`ArtifactSubmission` 是 discriminated union，至少覆盖现有 sibling research artifact bundle 和 append-only `ForecastReviewArtifact`；不是 raw payload dictionary。`ValidatedArtifactCommit` 只包含可持久化的 canonical envelopes、content hashes、record identities、typed dependency edges、workflow-use roles、manifest members 和已确认的 model/snapshot identity。它不执行 write，也不返回 `sqlite3.Row`。

`FrozenLineageEvidence` 是一次验证所需事实的 immutable aggregate，而不是一个新 persistence service。它包含：

- research run、workflow run、security、canonical subject 与 valid-as-of aliases；
- bound data snapshot 的 identity、purpose、classification、freshness、quality、timezone、calendar、as-of 与 PIT cutoff；
- snapshot member 的 normalized identity、provider provenance、published/available/retrieved time、content hash 和 quality；
- calendar sessions、OHLCV series、adjustment/currency、starting-price member、market-state inputs 与 corporate-action/factor evidence；
- 已持久化 parent artifact 的 typed identity、schema、payload identity 和 dependency graph。

它不是长期缓存，也不是第二份 source of truth。`WorkflowLedger` 在持有 writer lock 的 SQLite transaction 内从 canonical tables 物化它；领域 module 只能消费这个 typed value。现有 `_platform_subject_aliases`、`_validate_forecast_review_evidence` 与 `_validate_frozen_market_calibration` 中的 SQL 属于 evidence materialization，留在 persistence implementation；其中关于 subject、PIT、official provenance、calendar continuity、OHLCV、adjustment、starting price、market state、currency、unmodeled action 和 parent graph 的判定全部移入 `ArtifactLineage`。现有 `_forecast_payload_matches` 和 `_validate_research_artifact_lineage` 的纯规则也完全移入该 module，旧实现随后删除。

`ArtifactLineage` 的 failure 是 `ArtifactLineageError(code, message)`。`code` 保持当前正式 `RESEARCH_ARTIFACT_*` identity、parent、snapshot、lineage、market-calibration 与 content failure 语义；message 只能引用 redacted typed identities，不能包含 SQL、path 或 provider credential。证据不足、父对象缺失、identity 不一致和 calibration 不完整一律 fail closed；这里不做 provider fallback，也不把结构损坏降级成普通 research diagnostic。

### `WorkflowLedger` 的小 interface

`WorkflowLedger` 只公开 aggregate-level operations，不公开 table CRUD、connection、object store 或内部 evidence loader：

- `start_or_replay(StartWorkflow) -> StartOutcome`：建立或确认 invocation/request/definition identity；
- `record_transition(WorkflowTransition) -> TransitionReceipt`：原子处理 lease、heartbeat、cancel、attempt start/retry/failure 等 versioned lifecycle transition；具体合法状态与 retry policy 由 03 号 workflow-execution 票决定，ledger 只执行已类型化的 transition precondition；
- `commit_checkpoint(CheckpointCommit) -> CheckpointReceipt`：原子写 node result、checkpoint manifest、typed refs 与 history；
- `commit_artifacts(ArtifactSubmission) -> ArtifactCommitReceipt`：在 module 内物化 evidence、执行 lineage validation、发布对象并提交 record/edge/use/manifest/ref；
- `complete(WorkflowCompletion) -> ResearchWorkflowResult`：原子提交 final manifest、terminal transition、reuse decision 和 run status；
- `load(WorkflowQuery) -> WorkflowView`：discriminated query/result，只返回 run/result/history/manifest/request/artifact/research-run 等正式 typed view；
- `audit_integrity(IntegrityScope) -> IntegrityReport`：由 doctor 使用，检查 object、history、manifest、ref、artifact graph 与 immutable identity。

这些方法代表完整 transaction，不镜像 backing object 的每个 method。现有 33-method repository surface 中 `start/begin_node/finish_node/complete` 的旧非-recoverable 路径不进入目标 interface；recoverable lifecycle 的零散 row operations 收敛到 typed transition/checkpoint operations。03 号票可以决定 transition union 的 state-machine variants，但不得重新引入 SQL 或第二个 persistence interface。

Persistence failure 是 `WorkflowPersistenceError(code, operation, entity_ref)`；`entity_ref` 只能是可公开的 typed identity。保留并归一当前正式语义，包括 `RUNTIME_BUSY`、`WORKFLOW_BUSY`、`WORKFLOW_LEASE_LOST`、`WORKFLOW_DEFINITION_MISMATCH`、`WORKFLOW_FINGERPRINT_MISMATCH`、request/checkpoint/object integrity failure、parent missing/identity mismatch 和 artifact identity collision。SQLite locking/constraint/I/O 原因在此 seam 翻译为稳定 code，同时保留 redacted substep diagnostic；不得 broad-catch 成一个 undifferentiated failure。合法的“已有同 identity 结果”是 typed replay outcome，不是异常；只有 canonical bytes、所有 identity 字段、edges 和 roles 完全相同才可视为 replay。

### 原子性与 crash ordering

每次 mutation 的顺序固定为：

1. 取得 data-root writer lock，并以 workflow/artifact typed owner ref 标识持有者；
2. 开启 SQLite `BEGIN IMMEDIATE`，在同一 consistent snapshot 内读取 precondition、物化 `FrozenLineageEvidence` 并调用 `ArtifactLineage.validate`；
3. canonical serialize 后把每个对象写入同一 data root：temporary file -> flush/fsync -> hash/size verify -> atomic rename；
4. 在**同一尚未提交的 SQLite transaction** 中登记 `object_blob`，再写 checkpoint/artifact record、dependency edge、workflow use、manifest member/ref、transition 和 terminal state；
5. 对已存在 identity 做 exact collision comparison；全部一致则返回 replay receipt，否则 fail closed；
6. 提交 SQLite transaction，最后释放 writer lock。

filesystem rename 不能由 SQLite rollback，因此 crash 可留下未引用的 content-addressed orphan；这是安全且可回收的。反方向不允许：已提交 DB reference 绝不能指向未完成或 hash 不匹配的 object。当前 `ContentAddressedObjectStore.publish` 内部使用 `with connection` 独立登记 `object_blob`，会越过 outer aggregate transaction；目标实现必须把“durable object publication”和“DB registration”收回 `WorkflowLedger` 的一个 transaction，而不是在它外面保留可公开调用的 `publish`。同理，final workflow status、final manifest 与 refs 必须一次提交，不能先标成功再补 artifact。

同进程 `RLock` 不是 correctness boundary；跨进程 data-root writer lock 与 SQLite transaction 才是。所有 workflow/artifact/data-root mutation caller 迁移后都必须经过 canonical writer policy，不得保留直接 connection write。读取 typed view 可以并发，但不能观察半套 manifest/edges/terminal state。

### Schema、envelope 与迁移结论

本结构改造**不需要数据库 schema 或 artifact envelope migration**。现有 migrations 已表达 run/node/attempt/transition、immutable request/history/object/manifest、research run/reuse、typed artifact record/relation/workflow use 所需 identity；`ResearchArtifactEnvelope@1`、content hash、record ID、membership hash、dependency graph 和既有 rows 均保持不变。目标 module 是对同一 persistence contract 的职责重置，不得创建 V2 envelope、shadow tables、dual read/write 或 fallback。

实施时先让 `WorkflowLedger` 映射现有 schema 并通过同一 fixture/data-root 回归，再一次性迁移 callers，最后删除旧 `WorkflowRepository`/object registration surface。只有未来出现本票未覆盖的新数据语义时，才可另开 decision 论证版本化、backup-first migration；不能以本次拆分为由顺手改 schema。

### Caller 迁移与删除边界

- `ResearchWorkflowService` 改用 typed transition/checkpoint/artifact/complete operations；删除其对 `.connection` 的 workflow ref、attempt、research-run、artifact、projection 查询和 presentation ID update，以及重复 artifact-role mapping。
- `WorkspaceService` 只消费 `load` 的 typed history/manifest/research artifact views；删除 workflow/artifact direct SQL。
- chart、plan persistence 与 operations 通过 typed reference/active-run query 取得所需事实；不得各自查询 workflow tables。
- doctor 只调用 `audit_integrity`，但 audit implementation 仍在 ledger 内保留逐表/逐对象 diagnostic locality。
- composition root 只组装 module，`ApplicationFacade` 不暴露 repository。删除 `_workflow_repository`、`_store.connection`、`.objects` 等 production/test bypass。
- `DataRepository` 继续是 provider sync/data snapshot 写入的 canonical path；ledger 的 evidence materialization 只是 artifact transaction 内的只读 cross-aggregate consistency query，不形成第二个 data mutation path。

不可把大文件机械拆成一组 `*Repository` 类。私有 helper 可以按完整行为组织 object durability、evidence materialization 或 row mapping，但不成为跨 module interface；如果删除 helper 只会把相同行为移回 ledger，它是 ledger 内部实现细节。

### Replace-don't-layer 验收

- `ArtifactLineage` 的纯 fixture tests 覆盖现有 subject/as-of/snapshot/parent graph、forecast/valuation/simulation、frozen market calibration、review evidence 和所有稳定 failure code；测试不创建 SQLite。
- `WorkflowLedger` 的 temp SQLite + temp data-root interface tests 覆盖 invocation/replay、lease/history、checkpoint、bundle/review append-only lineage、object fault boundary、transaction rollback、concurrent exact replay、collision、restart read 和 audit。只有 migration/trigger/corruption adapter tests 可在 persistence test package 内直接操纵 DB；application tests不得通过 connection 断言实现形状。
- facade/CLI/company-outlook journeys 继续验证公开 research result、history、manifest、artifact identity 与 restart behavior。替代公开回归全部通过后，在同一 implementation unit 删除旧 repository methods、独立 object DB registration、direct SQL callers、private root access 和相应私有 seam tests；不得叠加保留两套路径。

本票沿用 01 号票已通过的 workflow/recovery/outlook 基线；本轮只作结构决策、没有修改生产代码，因此没有把重复测试运行冒充为新的通过证据。结论解除 03 号 workflow execution 票的阻塞，也消除了 map 中“是否需要 schema/envelope migration”的 fog；没有产生需要新增 child issue 的独立未知项。
