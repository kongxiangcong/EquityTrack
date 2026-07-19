# 决定 Workflow 状态机与研究执行 seam

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 02

## Question

决定 `ResearchWorkflowService` 中 run/resume/cancel、lease/heartbeat/retry、节点状态推进、研究引擎调用、artifact gate、share binding、展示权限和查询转发的职责归属：哪个深模块拥有 WorkflowRun 状态机，哪个模块执行研究节点与门禁，哪些查询应由独立任务接口承担，以及如何让一次 workflow 任务保持单一外部接口而不产生编排器套编排器或纯转发层。

## Answer

### 决策

以两个深 module 替换当前 `ResearchWorkflowService` 的混合职责，但只允许其中一个拥有 orchestration：

1. **`ResearchWorkflow` application module** 是 `WorkflowRun` 状态机的唯一 owner。它拥有 start/replay/resume/cancel、versioned node 顺序、lease supervision、checkpoint 决策、bounded retry、terminal transition 与从内部 typed failure 到 workflow failure 的归一化。它不执行研究计算、不读 source-manifest 文件、不计算展示权限、不写 SQL/对象。
2. **`ResearchExecution` application/domain module** 执行一个已经由状态机选定的研究节点。它拥有 research projection/engine 的领域门禁、研究运行或复用、typed artifact preparation、研究展示输入的生成，以及对 `WorkflowLedger` artifact operations 的调用；它不知道下一节点、run status、attempt number、retry budget、lease heartbeat 或 cancel transition。

依赖方向固定为：

`application task caller` -> `ResearchWorkflow` -> `ResearchExecution` -> deterministic research/domain modules

`ResearchWorkflow` -> `WorkflowLedger` <- `ResearchExecution`

`WorkflowLedger` -> `ArtifactLineage`

`ResearchExecution` -> target `ResearchDecisionView` module

不建立一个独立的 generic `WorkflowEngine` 再包住 `ResearchWorkflow`。当前 checkout 只有 `RESEARCH_WORKFLOW` 一条真实 definition，`registry.py` 也只有这一个三节点常量；通用 engine 会迫使 caller 学习 generic command/context/handler registration，却没有第二个真实 workflow adapter，形成编排器套编排器和 speculative seam。版本化 definition 是 `ResearchWorkflow` implementation 内的 immutable policy，不是一个可被任意调用的 registry module。将来若出现第二条具有相同 lifecycle 语义的真实 workflow，必须以代码证据另行决定是否提取 internal runtime；本 effort 不预建它。

### `ResearchWorkflow` 的唯一 interface

module 对 application caller 只暴露一个 task interface：

`handle(ResearchWorkflowCommand) -> ResearchWorkflowOutcome`

`ResearchWorkflowCommand` 是 discriminated union：

- `StartResearchWorkflow(ResearchWorkflowRequest)`；
- `ResumeResearchWorkflow(workflow_run_id, owner_token, lease_seconds)`；
- `CancelResearchWorkflow(workflow_run_id, reason)`。

`Start` 和 `Resume` 同步推进到既有成功、受限成功或 typed terminal failure；`Cancel` 返回 typed `CancellationAccepted`，只承诺已记录请求，不伪称能中断正在执行的普通 Python 调用。现有 Facade 是否用三个用户友好方法构造这个 command，由 07 号 application-interface 票决定；无论 presentation shape 如何，内部只能穿过这一条 task seam，不能保留 `run/resume/cancel` 三条各自重做状态判断的路径。

状态机完整拥有以下行为：

- 对 `invocation_id + canonical request fingerprint + workflow definition identity` 做 create/replay/conflict；成功 terminal replay 返回既有 result，不重跑节点；failed/cancelled run 是 terminal，不被新 owner 隐式复活。
- 取得、续约、失效和接管 lease；过期 owner 的未决 attempt 只可一次标记 `abandoned`，新 owner 创建单调递增 attempt。
- 按 immutable definition 选择 `freeze_research_projection -> run_or_link_research -> publish_run_manifest`，在进入节点前验证 preconditions、request identity 与已提交 checkpoint。
- 在长节点外包一层 lease supervisor；heartbeat、cancel safe point、attempt budget 和 delay 都属于状态机，不能散在 node implementation。
- 对每次 node outcome 选择 checkpoint commit、retry、terminal failure 或下一节点；研究复用只是 `run_or_link_research` 的成功 disposition，不是另一条 workflow。
- 在 final manifest、typed refs、reuse decision 与 terminal status 已由 `WorkflowLedger` 原子提交后返回 `ResearchWorkflowResult`。

`ResearchWorkflow` 的外部 failure 是 `ResearchWorkflowError(code, workflow_run_id, node_id=None)`。保留当前正式 code 语义：invocation mismatch、busy/lease lost、definition/fingerprint mismatch、request/checkpoint integrity、PIT/quality/snapshot classification、cancelled，以及 registry 声明的 node failures。它只记录 redacted diagnostic identity，不携带 SQL、path、raw provider response 或异常字符串。

### Versioned state machine contract

`NodeDefinition` 中当前 `cache_policy`、`retry_policy` 是任意字符串，而实际“最多三次 attempt、指数退避、哪些异常可重试”硬编码在 `ResearchWorkflowService._is_retryable/_retry_delay`。目标 definition 必须把这些提升为 typed policy：node/version/input-output schema/preconditions/cache identity/failure code、`max_attempts`、retryable failure set、backoff strategy/cap 与 checkpoint requirements 都进入同一 canonical definition identity。状态机不再检查任意 exception 的 `status_code`、headers 或 SQLite message 来猜 retry。

状态转换合同为：

- `WorkflowRun`：`queued -> running -> succeeded | succeeded_with_limits | failed | cancelled`；terminal 状态不可恢复为 running。
- `WorkflowNodeRun`：未建立或 `pending -> running -> succeeded | pending(retryable) | failed`；schema 中虽允许 `skipped/blocked`，本三节点 definition 未使用时不得为了“通用性”制造新路径。
- `WorkflowNodeAttempt`：running attempt 只可一次终结为 `succeeded | reused | failed | abandoned`；retry 永远创建同 run/node 下的新 attempt，不更新历史 attempt。
- cancellation 是 running run 上的请求旗标，在 node safe point 被消费；若请求发生在不可抢占的 research call 中，已经 durable 的 content-addressed object/artifact transaction 可保留，当前节点可完成 fenced checkpoint，然后 run 在进入下一节点或 finalization 前转为 cancelled。不得删除已形成的历史，也不得发布成功 terminal manifest。

每个 workflow-scoped `WorkflowLedger` mutation 都必须携带 expected `owner_token` 与未过期 lease 作为同一 transaction 的 precondition。这样 heartbeat failure 或 lease takeover 后的 stale worker 即使结束了 engine call，也不能提交 checkpoint/final state。现有 schema 的 owner/expiry 字段足够完成 fencing check，不需要新增 schema；可能留下的未引用 content-addressed object 由 02 号票既定 orphan 规则处理。

将 free-form definition policy 改为 typed identity 可能要求新创建的 workflow 使用新的 definition version。08 号替换顺序票必须决定 cutover 时先 drain/明确终结所有 running run，再启用新 version；已完成历史继续按其原 definition hash 只读，不更新 immutable row，也不增加兼容执行分支。

### `ResearchExecution` 的唯一 interface

module 只暴露：

`execute(ResearchNodeCommand) -> ResearchNodeOutcome`

`ResearchNodeCommand` 只有当前有真实行为的两个 variants：

- `FreezeResearchProjection`：验证 PIT、projection fingerprint、workflow/research snapshot purpose 与 candidate/market/research-relevant member classification，通过 `WorkflowLedger` 冻结 projection，返回 `ProjectionFrozen`（typed refs、artifact/member identity、disposition、research fingerprint）。
- `RunOrLinkResearch`：消费已冻结 projection，返回 `ResearchProduced`（research run identity/status、created/reused disposition、typed artifact records、canonical JSON/HTML artifact identities、checkpoint members 与 finalization 所需的 reuse facts）。

`publish_run_manifest` 没有独立研究行为，不进入 `ResearchExecution`；它是状态机对成功 node outcome 的 terminal commit，直接由 `ResearchWorkflow` 请求 `WorkflowLedger.complete`。因此 `ResearchExecution` 不选择 variants，也不是第二个 orchestrator；删除它会把 assembler、source gate、engine/reuse、artifact preparation 和 presentation policy 散回状态机，说明它具有 depth/locality，而删除只按 node name 转发的 handler class 不会丢失复杂度，所以不得创建这种 handler。

`ResearchExecution` 完整拥有：

- `SnapshotToResearchRequestAssembler` 的 fingerprint/assemble 调用与 projection/domain failure translation；
- repo-root containment、source-manifest identity/runtime gate、simulation calibration raw-evidence re-derivation，以及 typed valuation/simulation 在没有 diluted-share identity 时禁止 per-share publication的 pre-gate；
- research input + engine code identity 的 reuse candidate 选择；没有 exact candidate 时调用 deterministic `ResearchEngine`，有 candidate 时加载 immutable payload；
- 通过 `WorkflowLedger.commit_artifacts` 提交 typed sibling artifacts，并消费 `ArtifactLineage` 已验证的 receipt；不得自己写 object、record、relation、manifest 或 SQL；
- 调用目标 `ResearchDecisionView` interface 生成唯一 canonical decision model 与 JSON/HTML projection，并把 presentation artifacts 交由 ledger 持久化；不得保留 `ResearchRunCompatibility@*`、`ResearchReportHtmlCompatibility@1` 和 typed/non-typed 双 renderer 分支。

`ResearchExecution` 不拥有 retry loop或 sleep。它把已知失败归一为 `ResearchExecutionError(code, retry_class, retry_after=None, diagnostic=None)`：projection/source/share/calibration/lineage/identity failures一律 non-retryable；engine 或 persistence seam 只有在其 owner 明确返回 typed transient failure 时才可标 retryable。状态机再按 versioned node policy 决定是否创建下一 attempt。unexpected exception 在最接近的 owner seam 映射为该 node 已声明的稳定 failure，例如 engine -> `RESEARCH_ENGINE_FAILED`、ledger artifact commit -> `RESEARCH_ARTIFACT_PERSISTENCE_FAILED`；不再由 `_fail_node` 把任意 code 静默替换成 failure list 第一项。

### Share binding 与展示权限归属

`_diluted_share_binding`、`_share_bound_ready_methods` 和 `_presentation_permissions` 不属于 workflow lifecycle，也不应留在 `ResearchExecution` 里成为第二份 view 规则。其目标 owner 是 06 号票将定义的 **`ResearchDecisionView` module**：它以 typed `ResearchRun`、DataSnapshot/Valuation artifacts 和 source-gate evidence 为输入，统一决定 `formal_per_share_valuation` 等 presentation permission，再投影 JSON/HTML/Web/XLSX。`ResearchExecution` 只调用该 interface 并持久化结果，不能重算 permission；renderer 也不能解释或放宽它。

这里区分两个门禁：在没有 frozen diluted-share identity 时，包含 per-share 输出的 artifact **不得发布**，属于 `ResearchExecution` pre-gate；当 identity 存在时，fact binding、三情景 method bridge 完整性、至少两个 ready methods 与最终 presentation permission 属于 `ResearchDecisionView`。`ArtifactLineage` 继续独占持久化时的 subject/snapshot/parent/calibration identity revalidation，三者不得复制规则。

### 查询与 Forecast review 不进入 workflow interface

当前 `get_history/get_manifest/get_research_artifact/get_research_run_payload` 都是一行 repository 转发，扩大 `ResearchWorkflowPort` 却没有 leverage；`review_forecast` 更是独立领域 command，与 run/resume/cancel 无状态机关系。目标分配为：

- **Workflow inspection task**：一个 `inspect(workflow_run_id) -> WorkflowInspection` query，组合 run status、attempts、transitions、refs、checkpoint/final manifest 与 redacted diagnostic。它通过 `WorkflowLedger.load` 读取，不让 CLI/Web 拼多次 getter。
- **Research archive/decision query**：按 research run 或 artifact identity 打开 immutable research payload、typed artifact graph 与 canonical decision view；替换 workspace 当前的两个 callback 和逐 artifact getter。其最终 interface 由 06/07 号票收口。
- **Forecast review task**：独立 command module，拥有 `ForecastReviewEngine`、review target validation 和一次 `WorkflowLedger.commit_artifacts`；它不是 workflow resume 的节点，也不挂在 `ResearchWorkflow` 上。

这些是用户任务级 read/command seam，不是给 `WorkflowLedger.load` 套一层同名转发。若一个候选 query module 只把 ID 传给 ledger 再原样返回，它未通过 deletion test，应合并进承载完整 workspace/inspection use case 的 module。07 号票必须从真实 CLI/Web caller 选择最终最小 surface，不能机械保留四个 getter。

### 状态、副作用与并发归属

- Durable run/node/attempt/transition/checkpoint/artifact 状态只存在于 `WorkflowLedger`；`ResearchWorkflow` 仅持有一次调用期间的 ephemeral command context 和 lease supervisor。
- `ResearchWorkflow` 拥有 heartbeat scheduling 与 cancellation safe points。clock/sleeper/fault injection 是 implementation 内部 seam；不暴露到 task interface。
- `ResearchExecution` 的副作用只有读取 repo-bound evidence、调用 deterministic engine/assembler/view modules，以及请求 ledger 执行 canonical persistence transactions；它没有 background thread、lease 或 mutable global state。
- 同 invocation 并发、resume takeover、heartbeat 与 checkpoint/final commit 都以 ledger 的 writer lock + SQLite precondition 为 correctness boundary；Python `RLock` 或线程存活不是 correctness proof。

### Replace-don't-layer 迁移与验证

实施顺序受 08 号票最终裁决，但本 seam 的局部删除门明确为：

1. 先在 `ResearchExecution.execute` interface 上覆盖 projection/PIT/snapshot classification、source/calibration/per-share pre-gate、created/reused engine outcome、typed artifacts 和稳定 failures；测试使用 temp data root 与真实 local SQLite/assembler，engine 通过现有 deterministic runner seam 注入受控 outcome。
2. 在 `ResearchWorkflow.handle` interface 上覆盖 same-invocation replay/conflict、三节点 checkpoint、bounded monotonic attempts、lease takeover/heartbeat fencing、resume revalidation、cancel、terminal failure 与 final atomic result。断言通过 `WorkflowInspection`，不查询 private connection。
3. 公开 facade/CLI/company-outlook journeys 继续证明 result/artifact identity、restart/reuse、受限状态和金融边界；06 号 view interface 回归建立后，把 share binding/permission assertions迁移到完整 view tests。
4. 同一 implementation unit 迁移 callers 后删除 `ResearchWorkflowService`、宽 `ResearchWorkflowPort`、独立 `registry.py` public surface、repository connection SQL、`_node/_is_retryable/_retry_delay/_periodic_heartbeat/_artifact_member_role` 重复 helper、getter forwards、workflow 内 `review_forecast`、compatibility schemas/render branch 和 composition-root private workflow exposure。
5. 删除 application tests 对 `_research_workflow/_workflow_repository/_store.connection` 的 lifecycle assertions；只有 `WorkflowLedger` adapter 的 corruption/trigger/fault-boundary tests 可直接操纵 storage。不得保留旧 service 作为 wrapper，也不得让新 state machine 调回旧 `_execute/_research`。

当前 tests 已证明要提升的正式合同包括三节点顺序、same invocation、lease takeover/live-owner rejection、三次 bounded attempt、slow-call heartbeat、definition/fingerprint/request/checkpoint corruption、cancel history、node/object crash replay、typed artifact reuse 与 terminal manifest。01 号票记录的通过基线继续作为本决策证据；本轮未修改生产代码，所以没有重复运行测试并声称新的实现验收。

该决策解除 06 号 research decision view 与 07 号 application interface 的 workflow-side阻塞，并把 typed definition cutover/drain 要求交给既有 08 号迁移顺序票；没有产生需要新增 child issue 的独立 fog，也不需要新增领域词汇或 ADR。
