# 锁定受保护行为与目标模块依赖基线

Type: `task`
Mode: `AFK`
Status: `resolved`

## Question

以当前 checkout、长期任务 Prompt、公开导出、CLI/Web 调用者、持久化 schema、artifact identity 和测试为事实源，建立六个目标区域的完整依赖与行为基线：哪些正式可观察行为必须保持，哪些私有接口、直接私有方法测试、旧入口和重复导出应被迁移后删除；给出每个目标模块的调用者、被调用依赖、状态/副作用、错误合同和最小公开回归集合，使后续架构决策不依赖行数猜测。

## Answer

### 决策

本 effort 的受保护基线是**正式平台 task interface 上可观察的行为、领域语义、不可变历史、持久化数据和 artifact identity**，不是当前文件、类、方法数量或任何私有调用形状。六个区域后续都必须采用 replace-don't-layer：先在目标深 module 的小 interface 上建立等价公开回归，再一次性迁移正式调用者，最后删除被替代实现、旧导出、旧入口、跨 seam SQL 和直接私有方法测试；不得留下转发层、兼容分支或新旧双路径。

当前正式调用方向由代码证明为：

`trading_platform.cli` / `LocalChartWorkspaceServer` -> `ApplicationFacade` -> application task module -> domain module -> persistence/provider adapter。

`skills/SKILL.md` 已把 `python -m trading_platform.cli` 列为平台维护入口；`src/trading_platform/cli.py:67-91,156-171` 与 `src/trading_platform/web_server.py:19-96` 是当前真实调用者。相对地，`pyproject.toml:18` 的 `equity-research`、`scripts/research.py` 和 `skills/SKILL.md:244` 的旧 file/V3 CLI 是待正式调用者迁移后删除的旧入口，不构成兼容要求。

### 全局持久化与 identity 基线

- `migrations/0003_workflow_research_manifest.sql` 定义 `WorkflowRun`、node/attempt/transition、typed refs、`ArtifactManifest`、`ResearchProjection`、`ResearchRun` 和 reuse decision 的身份与关系；`migrations/0007_workflow_recovery.sql` 增加 lease、request hash、recovery event、definition/schema identity，并用 trigger 禁止历史、request、manifest 和 object 被更新或删除。
- `migrations/0012_research_artifact_bundle.sql` 把 typed research artifact identity 固定为 kind/schema/content hash/run/snapshot/security/subject/as-of/source/model/formula/code/policy/status，并把 lineage 与 workflow use 设为 append-only。`ImmutableArtifactDraft` 的 typed factory 和 canonical JSON/content hash（`domain/workflow.py:184-368,929-1022`）是正式写入前的 fail-closed identity gate。
- 因而默认不改变现有表、主键、schema version、content hash、manifest membership hash、ref disposition 或 artifact dependency graph。后续若 persistence seam 证明必须改 schema，只能由单独决策规定 backup-first、版本化、一次性迁移；本基线不授权双读、双写或旧 envelope fallback。
- `ResearchWorkflowRequest/Result`、`WorkflowHistory`、`ArtifactManifestView`、`ResearchArtifactView`（`domain/workflow.py:1057-1126`）是当前跨 application seam 的 typed observable contracts。内部 `sqlite3.Row`、raw tuple、connection、object store 和 writer lock 不是公开合同。

### 六个目标区域

#### 1. Application task interfaces / `ApplicationFacade`

- **当前 interface 与调用者**：`ApplicationFacade` 公开 44 个方法。CLI 正式使用 sync/daily、research run、market build/evaluate、resume/history、serve；本地 Web 使用 workspace、chart/annotation、plan confirmation 和 update authorization。测试和 `ProductionCompositionRoot.facade` 是同一 seam 的调用者。
- **被调用依赖**：构造函数直接接收八个 port/store，然后绝大多数方法一对一转发（`facade.py:35-246`）；composition root 构造 SQLite store、data sync、workflow、chart、plan、market、workspace、account 实现（`root.py:25-62`）。这证明当前 class 是宽而浅的镜像 Facade，不证明 44 个方法都应长期保留。
- **必须保持的行为**：正式 CLI JSON envelope 与 typed failure code；同一 invocation 的幂等/冲突语义；本地 Web 的 task-level query/command 结果；用户账户和研究数据仅走本地正式路径；所有研究/估值输出继续遵守金融边界。保护的是“完成一个 task 的结果”，不是 port 方法同名转发。
- **状态、副作用、failure**：Facade 自身不拥有 transaction 或状态，只做 dependency availability 检查；下游拥有 SQLite/object write、provider I/O 和 lifecycle。当前 failure 混用 `RuntimeError("... unavailable")`、domain error、`WorkflowError`，CLI 再归一为 JSON code（`cli.py:178-183`）。后续 task interface 必须让 typed failure 归属于完成该 task 的 module，不能继续由 Facade 字符串转译。
- **迁移后删除**：无 task policy 的一对一镜像方法、只复用另一个 getter 的 `get_plan_version_diff`、为镜像对象而存在的 `application/ports.py` 宽接口，以及 adapter/test 对 backing object 的直接访问。是否保留某个 task 由票据“决定 Application task interfaces 并收缩 Facade”按正式 CLI/Web caller 决定，不按当前公开关键字决定。
- **最小公开回归**：`tests/platform/test_runtime_skeleton.py`、`test_research_workflow.py`、`test_workflow_recovery.py`、`test_decision_research_view.py`、`test_company_outlook_journeys.py`，外加与被迁移 Web task 对应的 browser/Web tests。测试只能经 composition root/facade 或最终 task interface 观察结果。

#### 2. Workflow persistence 与 artifact lineage

- **当前 interface 与调用者**：`WorkflowRepository` 有 33 个 public 方法；生产调用者主要是 `ResearchWorkflowService`，但它还直接读取 `repository.connection`。`ProductionCompositionRoot` 暴露 `_workflow_repository`，`test_outlook_artifacts.py` 直接注入 fault、执行 SQL 和调用 bundle persistence。
- **被调用依赖**：SQLite connection、content-addressed object store、data-root writer lock、workflow registry identity、canonical hash，以及 `ImmutableArtifactDraft`/artifact view domain contracts（`repository.py:13-40`）。这些是 local-substitutable dependencies；SQLite temp data root 与本地 object store 已构成真实测试 stand-in，无需把 connection 暴露到 module interface。
- **必须保持的行为**：invocation 唯一性；run/node/attempt/transition 单调历史；lease takeover、heartbeat、bounded retry、cancel；checkpoint request/manifest/object 完整性；projection PIT/quality identity；research reuse；typed sibling artifact 的原子、幂等、append-only persistence；content-addressed object、artifact record、lineage、workflow use 和 final manifest 在重启后可读且 identity 不漂移。
- **状态、副作用、failure**：本 module 应独占 workflow/manifest/research artifact transaction、SQLite row transition、object publication ordering 和 writer lock。当前稳定 failure 包括 `WORKFLOW_BUSY`、`WORKFLOW_LEASE_LOST`、`WORKFLOW_DEFINITION_MISMATCH`、`WORKFLOW_FINGERPRINT_MISMATCH`、`CHECKPOINT_INTEGRITY_FAILED`、request/artifact/lineage integrity codes；底层 `PersistenceError` 只在这里翻译。不能把 raw `sqlite3.Row` 或任意 SQL 作为 error/状态合同。
- **迁移后删除**：已被 recoverable 流替代的 `start/begin_node/complete` 旧生命周期表面；service/workspace/root/test 对 `.connection`、`.objects`、`._workflow_repository` 的访问；重复 `_artifact_member_role` mapping；直接测试 `persist_research_artifact_bundle` 私有 transaction 形状。新 persistence module 删除时若只是把 SQL 散回 service/workspace，即未通过 deletion test。
- **最小公开回归**：`test_research_workflow.py` 的 create/reuse/restart/changed-input/diagnostic；`test_workflow_recovery.py` 的 object crash、checkpoint reuse、lease、retry、cancel、corruption；`test_outlook_artifacts.py` 的 typed artifact versioning、atomic crash recovery、concurrent replay；`test_forecast_review_artifact.py` 的 append-only lineage；doctor 的 manifest/history/reference integrity checks。

#### 3. Workflow execution

- **当前 interface 与调用者**：正式 interface 是 `run(request) -> ResearchWorkflowResult`、`resume(command)`、`cancel(command)`；四个 read/review 方法只是 repository 的一行转发（`research.py:767-800`）。Facade/CLI 是正式调用者。
- **被调用依赖**：workflow persistence、versioned registry、`SnapshotToResearchRequestAssembler`、deterministic `ResearchRunner`/`ResearchEngine`、code identity、typed artifact factories、research decision view 与 HTML renderer。执行 module 当前还越过 persistence seam 直接 SQL，并同时拥有 presentation permissions、artifact bundle preparation 和 forecast review。
- **必须保持的行为**：同 invocation 同 request replay；不同 request fail closed；`freeze_research_projection -> run_or_link_research -> publish_run_manifest` 的 versioned node/checkpoint/history语义；PIT 和 snapshot-purpose/classification validation；research reuse only when fingerprint+engine identity match；engine transient retry/heartbeat；失败 diagnostic redaction；resume/cancel/recovery；成功或受限 terminal result 与 final manifest 原子一致。
- **状态、副作用、failure**：执行 module 应拥有 orchestration state machine、node ordering、retry policy、lease heartbeat timing 和从 domain/persistence failure 到 `WorkflowError(code, workflow_run_id)` 的 typed translation；它不应拥有 SQL、artifact row transaction 或 presentation field parsing。正式 error code 集合来自 versioned `RESEARCH_WORKFLOW` node contracts，不能退化成 broad exception。
- **迁移后删除**：getter/review 镜像、执行层 direct SQL、重复 artifact role mapping、`ResearchRunCompatibility@*`/`ResearchReportHtmlCompatibility@1` 兼容 envelope 分支，以及测试对 `_research_workflow`/fault injector/private validation helpers 的直接操纵。替代测试应通过 run/resume/cancel/history/result 观察 checkpoint 与 failure。
- **最小公开回归**：`test_research_workflow.py`、`test_workflow_recovery.py`、`test_company_outlook_journeys.py` 中所有 facade journeys，加 CLI `daily/resume/history` contract tests。

#### 4. Forecast

- **当前 interface 与调用者**：真正有 leverage 的计算 interface 是 `ForecastEngine.build(ForecastRequest) -> ForecastGraph`。生产内调用者是 `ResearchEngine.run`（`engine.py:151-190`）；`ScenarioValuationEngine.run` 对每个情景重新调用它；typed artifact factory消费 `ForecastGraph`。`equity_research.__init__` 同时重导出 109 个名字，其中大量 forecast 数据类只是构建细节，不等于 109 个正式平台 interfaces。
- **被调用依赖**：typed `Security`、frozen `DataSnapshot`/facts、opening balance、assumption/override/narrative contracts、Decimal/period/valuation math。它是无 I/O 的 in-process deterministic module，不需要 persistence/provider port。
- **必须保持的行为**：subject/as-of/PIT/fact/assumption lineage fail-closed；exact Decimal、unit/currency/period algebra；segment/opening/three-statement reconciliation；archetype routing；deterministic graph/content identity；driver-to-financial-to-valuation-input transmission；graph replay、cycle/dimension validation；旧图作为 immutable `ForecastArtifact@1` 仍可读取与追溯。
- **状态、副作用、failure**：无外部状态或副作用；所有结果由 request 决定。failure 归 `ForecastInvariantError(code, message)`，不能由 caller 重做验证或改成任意 `ValueError`。
- **迁移后删除**：被新 deep module 完全吸收的 builder helpers、只为测试公开的 node/edge construction seam、重复 root exports 和围绕旧 `equity-research` CLI 的构造入口。构建 request 所需的稳定 domain value objects 可保留为 interface 类型，但内部 `_SegmentState/_CompanyState`、模板 helper 和调用其细节的测试不受保护。
- **最小公开回归**：`tests/test_forecast_graph.py` 应收敛为经 `ForecastEngine.build`/最终 forecast interface 断言 deterministic identity、replay、PIT/lineage、dimension/reconciliation、archetype routing；`test_company_outlook_journeys.py` 保证正式 workflow artifact 不漂移。

#### 5. Scenario valuation

- **当前 interface 与调用者**：计算 interface 是 `ScenarioValuationEngine.run(DeterministicScenarioRequest) -> DeterministicScenarioResult`。它以 base Forecast request、严格三分情景和 `ValuationPlan` 为输入；正式 workflow 当前不直接计算它，而是接收已构造的 typed `Valuation` artifact。因此后续必须把计算置于正式 research task 内部，不能新建第二应用入口。
- **被调用依赖**：Forecast reforecast、financial quantities、method-router gate 产物、Decimal/ACT-365/date math、typed method-family specs。它是无 I/O 的 in-process module。
- **必须保持的行为**：stress/base/improvement 完整互斥 partition；情景 driver 全覆盖；有证据时概率精确和为 1，否则 conditional-only；每个方法独立 applicability/failure，不因一个方法失败关闭其他方法；按公司 archetype 路由 DCF/SOTP/reverse/relative、cyclical/NAV、financial P/B-DDM-residual-income、biopharma rNPV/SOTP/runway；opening/terminal equity bridge、PIT lineage、单位/币种/期间、公式 version、conditional range、sensitivity；禁止跨方法 composite，只有同一方法跨情景 evidence-weighted range。
- **状态、副作用、failure**：无外部状态或副作用；请求完全决定结果。结构/partition/evidence 不变量归 `ScenarioInvariantError(code, message)`；方法自身的输入不足被隔离为该 `ScenarioMethodResult(status='blocked', diagnostics, lineage)`，而不是整个 run exception。
- **迁移后删除**：单个 8009 行 class 内的方法族 helper、重复的 forecast bridge/extraction、只为方法内部测试而暴露的 spec/export；`tests/test_scenario_valuation.py` 对 `_financial_projections`、`_discount_times`、`_financial_from_forecast` 的直接调用必须在目标方法族 interface 回归建立后删除。不能保留旧巨型 engine 再加一层方法族转发。
- **最小公开回归**：`tests/test_scenario_valuation.py` 经最终 scenario valuation interface 覆盖三分情景、各 archetype 方法路由、局部 fail-closed、PIT/bridge/dimension、ACT-365、probability weighting 和 no-composite；`test_outlook_artifacts.py`/`test_company_outlook_journeys.py` 覆盖 typed valuation artifact identity 与重启可读。

#### 6. Research decision view

- **当前 interface 与调用者**：`ResearchDecisionViewBuilder.build(...) -> ResearchDecisionView@2` 是唯一有 leverage 的 assembly interface；workflow 在生成正式 JSON/HTML 时调用，`WorkspaceService` 从持久化 typed artifacts 重建历史 view，Python HTML renderer、XLSX adapter 和 Web workspace 消费同一 canonical view。
- **被调用依赖**：只依赖 `ResearchArtifactView`、research run payload 和 canonical hash；它是无 I/O 的 in-process module。artifact读取、workspace SQL、HTML/XLSX/Web projection 都应留在 module 外的 adapter。
- **必须保持的行为**：DataSnapshot -> Forecast -> Valuation -> optional Simulation/MarketData/MarketPath 的 typed dependency graph 与全套 run/snapshot/security/subject/as-of/model/policy/code identity 一致性；三种情景、关键 drivers、market-implied expectations、simulation/path/divergence 的 deterministic projection；formal-per-share permission fail-closed；facts/sources/formulas/parameters/diagnostics/version audit；非投资建议 boundary；同一 view 的 JSON/HTML/Web/XLSX reconciliation 与历史版本并列可读。
- **状态、副作用、failure**：builder 无状态、无 I/O；identity、graph、scenario 和 payload failures 归 `ResearchViewError` 的稳定 code。renderer 只做 projection，不得重新解释金融许可或 lineage。
- **迁移后删除**：`build` 之外的私有 extraction/format helpers 不是 interface；`test_market_path_simulation_artifact.py` 对 `_value_market_divergence` 的直接测试应由完整 view 断言替代；`ResearchDecisionView@*` 输入兼容判断（`research_view.py:380-385`）、重复 Python/JS sandbox report 语义和旧 renderer 在正式消费者迁移后只保留一个 canonical presentation model，不得双实现漂移。
- **最小公开回归**：`test_decision_research_view.py` 的 typed-not-HTML source、exact JSON/HTML、optional distributions、parallel history；`test_market_path_simulation_artifact.py` 经完整 `build` 验证 divergence；Web `research-view` tests；valuation workbook reconciliation tests。

### 删除测试与迁移门

每个后续票据必须使用同一删除测试：若删除候选 module 只会把等量 SQL、validation、routing 或 formatting 散回 N 个 caller，它拥有 locality，应该被目标深 module 吸收；若删除它只需把一行转发内联到单一 caller，它是浅层，迁移后删除。现有直接私有 seam 测试明确包括：

- `test_scenario_valuation.py` 对 `_financial_projections/_discount_times/_financial_from_forecast`；
- `test_company_outlook_journeys.py` 对 workflow private presentation helpers 与 `ImmutableArtifactDraft._build`；
- `test_market_path_simulation_artifact.py` 对 `ResearchDecisionViewBuilder._value_market_divergence` 和 `_build`；
- `test_outlook_artifacts.py` 对 root `_workflow_repository/_research_workflow/_store`、repository connection 与 persistence method。

这些测试当前是调查证据，不是未来 interface。只有对应公开回归已覆盖相同正式行为后才能在同一实施票删除；不得先删保护网，也不得叠加保留两套测试。

### 本轮验证

- `python -m pytest -q tests/platform/test_research_workflow.py tests/platform/test_workflow_recovery.py tests/platform/test_decision_research_view.py tests/platform/test_outlook_artifacts.py`：`60 passed in 92.11s`。
- `python -m pytest -q tests/test_forecast_graph.py`：`31 passed in 0.90s`。
- `python -m pytest -q tests/test_scenario_valuation.py`：`55 passed in 13.21s`。
- `python -m pytest -q tests/platform/test_company_outlook_journeys.py`：`14 passed in 36.96s`。
- 首次合并执行上述大集合在 124 秒命令上限超时且没有最终结果；它不计为 pass，拆分后的四个独立命令才是本票据使用的通过证据。

该基线只锁定保护与删除边界，不预判后续 module topology。它解除“决定 Workflow persistence 与 artifact lineage seam”和“决定 Forecast 深模块拓扑”的阻塞；未产生需要新增 child issue 的新问题，map 的 `Not yet specified` 保持不变。
