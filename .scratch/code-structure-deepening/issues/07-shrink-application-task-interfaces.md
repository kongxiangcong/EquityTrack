# 决定 Application task interfaces 并收缩 Facade

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 03, 06

## Question

在底层深模块 seam 已明确后，决定正式应用层应暴露哪些完整用户任务接口，以及 `ApplicationFacade` 中 watchlist、data、research、workflow query、workspace、account、chart annotation、plan 和 market 的镜像方法应如何迁移、合并或删除；同时决定 CLI、Web 和测试的唯一调用路径，使 Facade 不再复制各 port 的表面积，也不以新的总线、service locator 或兼容 wrapper 替代旧 Facade。

## Answer

### 决策

删除 `ApplicationFacade`，不保留一个较小的同名 facade，也不建立 `ApplicationService`、`ApplicationTasks`、mediator、command bus、service locator 或兼容 wrapper。正式应用边界由下面按完整用户任务命名的 deep modules 共同组成；每个 module 自己拥有 typed command/query、策略、事务或生命周期，adapter 直接依赖它实际使用的 task interface：

`CLI / Web / acceptance adapter -> one or more named application tasks -> domain module ports -> persistence/provider adapters`

`ProductionCompositionRoot` 只构造对象、管理共享资源生命周期并把具体 task 注入 adapter。它不得公开 `.facade`、`.tasks`、任意 `get_service()` 或 backing repository，也不得根据字符串 capability 选择业务实现。删除一个目标 task module 会把其事务、状态转换、证据门禁或跨模块 policy 散回 caller；删除当前 Facade 只会把同样的转发调用移到 caller，因此当前 Facade 未通过 deletion test。

当前 Facade 43 个公开方法中，除 `query_health` 的 capability 汇总和 `get_plan_version_diff` 的二次转发外，其余方法几乎都是 1 次 null-check 加 1 次 port mirror；`execute` 永远返回 unavailable。生产调用者也没有使用完整表面积：CLI 只使用 sync、research start/resume/history、market snapshot/evaluation，Web 只使用 workspace、update authorization、chart/annotation 和 plan confirmation，provider qualification 只使用 watchlist registration、sync 和 attempt evidence。大量 detail/getter 只由测试直接调用，不能据此保留 public application surface。

### 唯一 task-interface inventory

下列名称描述职责和 seam；实施时可以沿用已经满足契约的现有深实现，而不是为每个名称再包一层同名 class。

- `PlatformHealth.check(HealthQuery) -> HealthResult`：只汇总已构造 runtime 的 typed capability/status，不持有 nullable ports，不执行业务命令。`PlatformCommand`、`CapabilityResult` 和永远 unavailable 的 `execute` 删除；bootstrap/migrate/doctor/backup/restore 继续由维护边界 `PlatformOperations` 独立拥有，不进入业务 task surface。
- `Watchlist.handle(WatchlistCommand) -> WatchlistOutcome` 与 `Watchlist.open() -> WatchlistView`：同一 watchlist module 拥有 security identity 校验、idempotency 和持久化事务。domain-specific command union仅覆盖 add/remove 等同一生命周期，不是全平台 bus；本 effort 不新增 remove 能力。provider job 的 security registration 调用该 task，不能直接调用 `PlatformStore`。
- `DataSynchronization.sync(SyncRequest) -> SyncResult`：沿用 `DataSyncService.sync` 的完整 provider/fallback/rights/normalization/snapshot 事务；`DataSnapshotInspection.inspect(snapshot_id) -> DataSnapshotInspectionView` 一次返回 snapshot members、attempt evidence refs、freshness/rights/source diagnostics。不得再公开 members 与 attempt evidence 两个 repository getter。
- `ProviderQualification.qualify(ProviderQualificationCommand) -> ProviderQualificationResult`：完整拥有 job decode、watchlist/security registration、authorized sync、attempt inspection、qualification policy 和 artifact result；当前 `ProviderQualificationService.run` 改为接受上述 task dependencies，不再自行创建 root 后连续拉取三个 Facade 方法。
- `DailyResearchCycle.run(DailyResearchCycleCommand) -> DailyResearchCycleResult`：完整拥有当前 CLI `_daily` 的 sync -> optional research -> optional market snapshot -> optional plan evaluation -> doctor gate 顺序和 typed substep diagnostics。CLI 不再自行编排四个业务模块，也不通过一个 generic dispatcher 执行它们。
- 03 号票的 `ResearchWorkflow.handle(StartResearch | ResumeResearch | CancelResearch) -> ResearchWorkflowOutcome`、`ResearchExecution.execute(ResearchNodeCommand)` 与 `WorkflowInspection.inspect(workflow_run_id) -> WorkflowInspection` 保持唯一入口；start/resume/cancel 不再是三个 Facade aliases，history/manifest/raw artifact/raw ResearchRun getters不再是应用查询。
- `ResearchArchive.open(ResearchArchiveQuery) -> ResearchArchiveView`：按 workflow/final manifest 返回 06 号票持久化的 canonical `ResearchDecisionView`、typed audit/artifact graph 和 workflow inspection；不返回让 adapter 重建含义的任意 payload。`ForecastReview.review(ForecastReviewCommand) -> ForecastReviewOutcome` 继续是与 workflow 独立的完整 commit task。
- `DecisionWorkspace.open(DecisionWorkspaceQuery) -> DecisionWorkspaceView`：完整拥有某 security + snapshot 的研究历史、canonical decision views、forecast review、账户/计划/市场/图表摘要组合与默认 version selection。它读取各 owning query ports 的 typed projection，不持有 raw SQL、artifact callbacks或 presentation builder。`WorkspaceUpdateAuthorization.authorize(UpdateAuthorizationCommand) -> UpdateAuthorizationOutcome` 独立拥有日期/session、idempotency 和审计写入，不能藏在 workspace getter 上。
- 账户现有的 `TonghuashunImportPreviewer.preview`、`AccountOpeningService.initialize`、`AccountOpeningService.get_detail`、`AccountHistoryImportService.import_history` 和 `AccountAcceptanceService.write_manifest` 分别作为 import preview、opening、inspection、history import 和 acceptance 的正式 task seams；它们已有实质解析、隐私、commit 或验收行为，不再为 `get_detail` 单独加 `AccountPort`/Facade mirror。CLI 全部通过这些 task interfaces，测试不得通过 root 私有 store 绕行。
- `ChartWorkspace.open(ChartWorkspaceQuery) -> ChartWorkspaceView` 一次返回 immutable series frame 与该 security 的 annotation projection；现有 `/api/chart-series` 和 `/api/annotations` 可以投影同一 typed result以保持 HTTP 行为，不能分别执行两个 persistence getters。`ChartAnnotations.handle(CreateAnnotation | ReviseAnnotation | DeleteAnnotation | RestoreAnnotation | MigrateAnnotationCoordinates) -> AnnotationOutcome` 完整拥有 optimistic version、frame identity、coordinate migration 和 receipt；单个 annotation history只作为该 module 的内部校验/query port，公开历史通过 chart workspace/audit projection读取。
- `TradePlans.handle(CreateDraft | UpdateDraft | DiscardDraft | ConfirmDraft | ActivateVersion | DeactivatePlan | EndPlan) -> TradePlanOutcome` 完整拥有 draft、immutable version、activation 和 lifecycle。`PlanConfirmation.preview(draft_id) -> PlanConfirmationView` 是用户确认前的完整 preview task；`TradePlanWorkspace.open(TradePlanWorkspaceQuery) -> TradePlanWorkspaceView` 返回某 security/plan 的 active state、draft/version history、confirmation/diff。不得把 draft/version/active/lifecycle/diff拆成 public getters；market evaluation所需的 exact version/lifecycle/account operands是 module-to-module typed `PlanEvaluationInputPort`，不是 adapter surface。
- `MarketSnapshotBuilder.build(BuildMarketSnapshotCommand) -> MarketSnapshotView` 与 `PlanEvaluator.evaluate(EvaluatePlanCommand) -> PlanEvaluationView` 是两个完整 task seams；前者拥有 frozen market input identity，后者拥有 plan/version/account binding、policy、deterministic evaluation 和 commit。历史 snapshot/evaluation detail进入 `DecisionWorkspace`/`TradePlanWorkspace` typed projection，删除两个 public detail getters。

这些接口不是要求建立十三个 forwarding files。现有 `DataSyncService`、`ChartService`、`PlanService`、`MarketEvaluationService` 和 account services 只有在自身完整拥有上述行为时直接成为 task implementation；需要分离的地方移动完整行为与事务，随后删除原实现。`ResearchWorkflowService`、`WorkspaceService` 当前过宽/跨 SQL 的内部改造遵循 02、03、06 号票，不由本票重复设计。

### 现有 Facade surface 的一次性归宿

| 当前方法组 | 唯一归宿 | 删除内容 |
| --- | --- | --- |
| `query_health` | `PlatformHealth.check` | Facade version/capability null-check；`execute`、`PlatformCommand`、`CapabilityResult` |
| `add/list_watchlist_item` | `Watchlist.handle/open` | `PlatformPersistence` watchlist mirror；`doctor` mirror |
| `sync_data` | `DataSynchronization.sync` | `DataSyncPort` forwarding protocol |
| `get_data_snapshot_members`、`get_provider_attempt_evidence` | `DataSnapshotInspection.inspect`；qualification只消费该 view | 两个独立 getters |
| `run/resume/cancel_workflow` | `ResearchWorkflow.handle` | 三个 aliases 与宽 `ResearchWorkflowPort` |
| `get_workflow_history` | `WorkflowInspection.inspect` | history getter |
| manifest/artifact/ResearchRun getters | `ResearchArchive.open` 或 module-internal typed reads | raw payload/application getters |
| `review_forecast` | `ForecastReview.review` | workflow-owned alias |
| `get_workspace` | `DecisionWorkspace.open` | `WorkspacePort.build` mirror |
| `authorize_workspace_update` | `WorkspaceUpdateAuthorization.authorize` | `WorkspacePort.authorize_update` mirror |
| `get_account_opening` | `AccountOpeningService.get_detail` 作为 account inspection task | `AccountPort` 与唯一 getter mirror |
| chart series + annotation list/history | `ChartWorkspace.open` | series/history getters |
| annotation create/revise/delete/restore/migrate | `ChartAnnotations.handle` | 五个 verb mirrors 与 `ChartPort` |
| plan draft/version/lifecycle commands | `TradePlans.handle` | 七个 verb mirrors 与 `PlanPort` |
| plan confirmation/diff | `PlanConfirmation.preview` | `get_plan_version_diff` 二次转发 |
| plan draft/version/active/lifecycle getters | `TradePlanWorkspace.open`；内部 evaluator port | 五个 public getters |
| market snapshot/evaluation commands | `MarketSnapshotBuilder.build`、`PlanEvaluator.evaluate` | `MarketPort` umbrella |
| market/evaluation detail getters | workspace typed projections | 两个 detail getters |

### CLI、Web 与测试的唯一调用路径

CLI parser/JSON envelope仍是唯一 `python -m trading_platform.cli` adapter，但每个 operation handler只接收它对应的 task interface。production bootstrap在 composition root 内把 handler与task接好后返回已配置的 CLI application；handler不能持有 root、Facade、store或按 operation 名查询 service。`sync`调用 `DataSynchronization`，`daily`只调用 `DailyResearchCycle`，`resume/history`分别调用 `ResearchWorkflow`/`WorkflowInspection`，account commands调用既有 account tasks，maintenance commands只调用 `PlatformOperations`。当前 `_daily` 业务编排、`register_job_security(root, ...)` 和 account CLI 的随意直接构造同步迁入各 owning task/composition wiring；不得留下第二条直接 service 路径。

`LocalChartWorkspaceServer` 仍是 HTTP/security adapter。composition root按构造参数显式注入 `DecisionWorkspace`、`ChartWorkspace`、`ChartAnnotations`、`PlanConfirmation/TradePlans` 和 `WorkspaceUpdateAuthorization` 所需的窄 protocols；server不接收 root或通用容器。现有 route、CSRF/origin/host/body limit、typed error code和JSON shape是受保护 adapter行为。POST annotation handler不再先读 chart series、再读 history、再选择四个 Facade verb；它构造一个 typed annotation command，由 `ChartAnnotations.handle` 原子校验 security/frame/current version并执行。GET routes只投影相应 task view。

测试分三层且全部跨同一 public interface：

1. task contract tests直接构造一个真实 task implementation与必要 fake external adapters，覆盖事务、idempotency、typed failure和immutable history；不 mock Facade、不直接测试 forwarding；
2. CLI/Web adapter tests注入窄 fake task interfaces，覆盖参数/HTTP到typed command的转换、安全边界、JSON envelope与错误映射；
3. production journey tests通过 composition root创建已配置 adapter或显式 task fixture，覆盖持久化重启、workflow、workspace、account、chart、plan和market的跨模块行为，但不使用 `root.facade`、`root._store.connection` 或私有 research methods。

现有直接 SQL 测试只有在验证 02 号 `WorkflowLedger`、migration或数据库 corruption recovery 的 owning persistence interface时保留；为了准备 plan/market/research fixture而执行 SQL的测试迁移到公开 task command。Facade forwarding assertions（同一 instance、unavailable `execute`、每个 getter等于 backing service）全部删除，不把它们搬到新 wrapper。

### State、失败与依赖约束

- composition root内不得用 `None` 表示 task capability。一个 operation所需依赖无法构造时，在 composition阶段产生 typed configuration/capability failure；task运行期间继续返回/抛出其领域 typed failure。删除 Facade 当前不同方法各自的 `RuntimeError("... unavailable")`。
- task command携带 invocation/idempotency、identity与expected revision；adapter不补做业务校验。task result保留当前公开 JSON/HTTP需要的typed projection与redacted diagnostics，不能 broad-catch成同一个 failure。
- query tasks只读取 owning ports的typed projection，不公开 connection、repository、artifact bytes、arbitrary Mapping或callback。command task不能经 query view反向写入。
- `DailyResearchCycle` 和 `ProviderQualification` 是唯一允许跨多个 task的application orchestration；它们各自对应明确用户操作与policy，不演变为可注册任意命令的流程引擎。
- Web、CLI和测试不能从 `trading_platform.__init__` root aliases导入 Facade或 backing services；package root只导出真正稳定的 contracts/entrypoint。具体 composition types留在 application bootstrap module。

### Replace-don't-layer 迁移与删除门

08 号票应把迁移排成自内向外、一次切换，不允许先加新 tasks再长期保留 Facade：

1. 先完成 02–06 已决 module contracts及其 public contract tests；
2. 把现有 services变成上述完整 task implementations，补齐 `DailyResearchCycle`、`ProviderQualification`、组合 query和窄 adapter protocols；
3. composition root显式注入 CLI/Web，迁移 production callers；
4. 将 journey tests迁到同一 task/adapters，提升需要保护的真实行为，删除 mirror/private-SQL fixture tests；
5. 同一 cutover删除 `application/facade.py`、`application/ports.py` 中宽 mirror protocols、`root.facade`、package re-exports、nullable backing fields、旧 CLI/Web调用和所有 Facade tests；搜索并证明 `ApplicationFacade`、`.facade`、`PlatformCommand`、旧 method names及 raw getter imports为零；
6. 运行 public task、CLI、HTTP/Chromium、persistence restart、workflow recovery、financial-boundary与完整 acceptance suites；只有全部正式 caller已切换且旧 symbols为零才关闭迁移。

不得保留旧 Facade一段时间作 adapter，不得用 `__getattr__`、aliases、dual injection、feature flag或旧新测试双跑。若一个历史数据读取需要迁移，按 08 号票进行 backup-first、versioned one-way migration；这不是保留 runtime compatibility的理由。

本决策解除既有 08 号迁移与验收顺序票的最后 application-interface blocker；所有剩余拆票、精确文件集合、估算、旧入口清单与 suite gate均由 08 号票统一锁定，没有新增 child issue。现有领域词汇未改变，故不修改 `CONTEXT.md`；删除 shallow Facade并采用显式 task injection是本项目工程政策的直接落实，不新增 ADR。
