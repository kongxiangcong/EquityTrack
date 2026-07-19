# 锁定替换迁移、删除和验证顺序

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 02, 03, 04, 05, 06, 07

## Question

综合已决定的目标接口，形成可直接交给 `/to-spec` 的迁移图：按什么 blockers-first 顺序逐个替换调用者、测试、公开导出、持久化与文档；每个 tracer bullet 必须删除哪些旧实现和私有测试；哪些行为矩阵、typed failure、artifact identity、数据库 backup/migration、完整 Python/Web/acceptance 命令构成完成证据；如何保证任一中间提交都只有一条正式路径且不引入兼容期。

## Answer

### 决策

实施必须按下面六个 blockers-first tracer bullets 顺序进行，每票一个 implementation context、一个 commit；同一票内遵循“建立目标 interface 回归 -> 完整迁移该 seam 的 production/test callers -> 删除旧实现/导出/测试 -> 搜索清零 -> 运行该票 gate”。不允许先合入空 package、forwarding class、旧 interface adapter、feature flag、old/new comparison、dual read/write 或“稍后删除”的 wrapper。

```text
TB-1 Forecast contract + Graph identity
  -> TB-2 Scenario valuation method families

TB-3 ArtifactLineage + WorkflowLedger
  -> TB-4 ResearchWorkflow + ResearchExecution + canonical DecisionView cutover

TB-1 + TB-2 + TB-4
  -> TB-5 CLI / research / data / account / market task cutover
  -> TB-6 Web task cutover + Facade deletion + final release proof
```

TB-1/2 与 TB-3 的代码工作可在不同分支调查，但不得并行合入会同时修改 `domain/workflow.py`、root exports 或 artifact fixtures 的提交；合入顺序固定为 TB-1、TB-2、TB-3、TB-4、TB-5、TB-6。每个中间 commit 对已迁移 seam 只有目标 implementation；尚未迁移的现有外层 caller可以继续是当时唯一正式路径，但不得获得第二条 target/legacy dispatch。`ApplicationFacade` 在 TB-5 开始按 caller 集合缩减，TB-6 删除；期间不得新增任何 Facade method或让已迁移 caller回穿 Facade。

估算使用一张本地 implementation ticket 可容纳的约 100K context：`L` 为一个高风险纯计算替换，`XL` 为一个跨 persistence/application seam 的完整替换。估算不是行数配额；若 implementation 调查发现精确文件集合外的新 caller，先更新该 implementation ticket并保持同一 seam，不把它藏成兼容层。

### TB-1 — 替换 Forecast package 并切换 `ForecastGraphIdentity@2`

**Blocker**：01、04 的现行决策；不依赖其他 implementation ticket。**估算**：`L`，1 context，约 8 个 production files + 4 个 test callers。

精确文件集合：

- 删除 `src/equity_research/forecast.py`；创建 `src/equity_research/forecast/__init__.py`、`contracts.py`、`evidence.py`、`graph.py`、`manufacturing.py`、`engine.py`；
- 修改 `src/equity_research/engine.py`、`src/equity_research/__init__.py`、`src/trading_platform/domain/workflow.py`；
- 修改 `tests/test_forecast_graph.py`、`tests/test_scenario_valuation.py`、`tests/platform/test_company_outlook_journeys.py`、`tests/platform/test_outlook_artifacts.py`、`tests/platform/test_runtime_skeleton.py`。

一票内完成 `ForecastEvidence.validate`、`ManufacturingForecast.project`、`ForecastGraph.compile/replay` 与唯一 `ForecastEngine.build`；所有 archetype使用同一 `ForecastGraphIdentity@2` canonical hash并产生 `fg2_` identity。旧 `fg_` artifacts保持 immutable bytes，只读历史不重算；新 code identity只产生新 artifact version，不更新旧 row、不写双 identity。删除旧 formula/build/hash bodies、financial/biopharma独立 hash、root-level Forecast aliases、测试对构造 helper和损坏 result重建的依赖。`ForecastInvariantError` 的 PIT、dimension、formula、cycle、reconciliation、lineage、identity code保持稳定；Graph identity collision新增回归必须证明“同 semantic content同 id、任一 assumption/narrative/archetype差异不同 id、ambient Decimal/order不影响 id”。

票内 gate：`python -m pytest -q tests/test_forecast_graph.py tests/platform/test_company_outlook_journeys.py tests/platform/test_outlook_artifacts.py`，以及 AST guard证明 platform只从 canonical forecast package contract导入；不得保留旧 `forecast.py` wrapper。

### TB-2 — 替换 Scenario valuation package 与四个方法族

**Blocker**：TB-1。**估算**：`XL`，1 context，约 10 个 production files + 3 个 test callers。

精确文件集合：

- 删除 `src/equity_research/scenario.py`；创建 `src/equity_research/scenario_valuation/__init__.py`、`contracts.py`、`basis.py`、`industrial.py`、`cyclical.py`、`financial_institution.py`、`biopharma.py`、`engine.py`；
- 修改 `src/equity_research/engine.py`、`src/equity_research/__init__.py`、`src/trading_platform/domain/workflow.py`；
- 修改 `tests/test_scenario_valuation.py`、`tests/platform/test_outlook_artifacts.py`、`tests/platform/test_company_outlook_journeys.py`、`tests/platform/test_runtime_skeleton.py`。

一票内迁移 Scenario Set、`ValuationBasis` 与四个完整 family；只保留 `ScenarioValuationEngine.run` 外部 seam。删除 8009 行旧 engine、所有新 family 对旧 private method的调用、dict-shaped projection、37 个 root scenario aliases，以及 `_financial_projections`、`_discount_times`、`_financial_from_forecast` 私有测试。测试改由完整 family/internal interface或 public `run`观察 ACT/365、quantity normalization、bridge trace与结果。保持现有 request/result serialization、method ids/order、formula versions、`ValuationArtifact@1`、局部 blocked和 no-cross-method-composite；本票不再变更 schema/identity。unknown exception不得降级为 blocked。

票内 gate：`python -m pytest -q tests/test_scenario_valuation.py tests/platform/test_outlook_artifacts.py tests/platform/test_company_outlook_journeys.py`；矩阵必须覆盖 stress/base/improvement × industrial/cyclical/financial/biopharma × ready/blocked/disabled、probability absent/present、opening/terminal bridge、same-method weighting和 no-composite。

### TB-3 — 以 `ArtifactLineage` 和 `WorkflowLedger` 替换 repository

**Blocker**：02；为减少共享 caller冲突，在 TB-2 后合入。**估算**：`XL`，1 context，约 12 个 production files + 8 个 test files。

精确文件集合：

- 创建 `src/trading_platform/domain/artifact_lineage.py`、`src/trading_platform/persistence/workflow_ledger.py`；删除 `src/trading_platform/workflows/repository.py`；
- 修改 `src/trading_platform/domain/workflow.py`、`src/trading_platform/persistence/__init__.py`、`runtime.py`、`objects.py`、`doctor.py`、`src/trading_platform/workflows/research.py`、`workflows/__init__.py`、`workspace.py`、`application/root.py`、`operations.py`；
- 创建 `tests/test_artifact_lineage.py`、`tests/platform/test_workflow_ledger.py`；修改 `tests/platform/test_research_workflow.py`、`test_workflow_recovery.py`、`test_outlook_artifacts.py`、`test_forecast_review_artifact.py`、`test_operations_backup_restore.py`、`test_watchlist_persistence.py`。

`ArtifactLineage.validate`纯测试不创建 SQLite；`WorkflowLedger` temp-data-root tests覆盖 aggregate transactions。旧 `ResearchWorkflowService` 在本票只是唯一 production caller迁移到 Ledger，不能保留 repository adapter或connection escape；它的状态机替换留给 TB-4。`WorkspaceService` 对 workflow/research/artifact 的 SQL改为 typed `WorkflowLedger.load`，但账户/计划/图表组合行为直到 TB-6 才迁移。

同一票删除旧 33-method repository、非recoverable lifecycle、独立 object DB registration、重复 artifact-role mapping、root `_workflow_repository` exposure和 application tests中的 workflow SQL。只有 `test_workflow_ledger.py`、migration/trigger/corruption tests可直接操作 SQLite/object fault seam。对象顺序固定为 durable temp/fsync/hash/rename -> 同一 `BEGIN IMMEDIATE`登记 object+artifact+edges+manifest+transition -> commit；crash只可留下 unreferenced object，不可留下 DB dangling reference。

failure矩阵覆盖 `ArtifactLineageError(RESEARCH_ARTIFACT_*)` 与 `WorkflowPersistenceError` 的 busy/lease/fingerprint/definition/checkpoint/object/collision/integrity code、exact replay、transaction rollback、concurrent writer、restart与doctor audit；不得让 SQLite/path/provider secret越过 seam。

票内 gate：`python -m pytest -q tests/test_artifact_lineage.py tests/platform/test_workflow_ledger.py tests/platform/test_research_workflow.py tests/platform/test_workflow_recovery.py tests/platform/test_outlook_artifacts.py tests/platform/test_forecast_review_artifact.py tests/platform/test_operations_backup_restore.py`，再用 AST guard证明 `src/trading_platform` 除 `persistence/` 外不访问 workflow tables/connection/object store。

### TB-4 — 原子替换 Research workflow、DecisionView 与历史引用

**Blocker**：TB-1、TB-2、TB-3。**估算**：`XL`，1 context，约 18 个 production files + 12 个 Python/Web tests。此票必须作为一个 canonical-research vertical合入，不能把 typed builder、workflow@2或历史迁移拆成互相兼容的阶段。

精确文件集合：

- 删除 `src/trading_platform/workflows/research.py`、`workflows/registry.py`；创建 `src/trading_platform/workflows/research/__init__.py`、`contracts.py`、`definition.py`、`workflow.py`、`execution.py`、`inspection.py`、`forecast_review.py`；
- 删除 `src/trading_platform/research_view.py`；创建 `src/trading_platform/research_view/__init__.py`、`contracts.py`、`decoding.py`、`builder.py`；创建 `src/trading_platform/persistence/research_view_cutover.py`；
- 修改 `src/trading_platform/domain/workflow.py`、`persistence/workflow_ledger.py`、`persistence/runtime.py`、`persistence/doctor.py`、`operations.py`、`research_presentation.py`、`valuation_workbook.py`、`workspace.py`、`application/contracts.py`、`application/facade.py`、`application/ports.py`、`application/root.py`、`workflows/__init__.py`、`trading_platform/__init__.py`；
- 修改 `web/src/research-view.js`、`web/src/app.js`、`web/tests/research-view.test.js`；
- 创建 `tests/platform/test_research_view_cutover.py`；修改 `tests/platform/test_research_workflow.py`、`test_workflow_recovery.py`、`test_decision_research_view.py`、`test_company_outlook_journeys.py`、`test_outlook_artifacts.py`、`test_forecast_review_artifact.py`、`test_market_path_simulation_artifact.py`、`test_valuation_simulation_artifact.py`、`test_valuation_workbook_adapter.py`、`test_secure_workspace.py`、`test_operations_backup_restore.py`。

此票同时完成：

1. `ResearchWorkflow.handle`成为唯一状态机，typed definition升级为 `research-workflow@2`，`ResearchExecution.execute`成为唯一节点执行 seam，`WorkflowInspection.inspect`与`ForecastReview.review`分离；删除旧 service、public registry、retry/heartbeat/role helpers、direct SQL、workflow permission helpers和 getter forwards。
2. `ResearchDecisionViewBuilder.build(ResearchDecisionInput)`成为唯一 builder；workflow每次恰好持久化一次 typed `ResearchDecisionView@2`及 HTML，Workspace/Archive只加载 bytes，不重建。删除 Mapping overload、schema-prefix decoder、`_validate_artifacts`重复规则、`_value_market_divergence` direct test、`renderSandboxReport`及其 JS report语义；XLSX只接收 typed view。
3. 使用现有 tables执行 versioned `ResearchDecisionViewCutover@1`，**不新增 SQL schema**：每个 succeeded/succeeded_with_limits workflow必须拥有一个 immutable `artifact_manifest(manifest_role='workflow_decision_view@1')`，成员角色精确为 `decision_view_json`、`decision_view_html`，并追加唯一 `workflow_run_ref(ref_role='decision_view_manifest')`。新 runtime只走该 ref -> manifest路径，不看旧 final-manifest role、不按 schema猜测、不 fallback。
4. 对历史 `research_run_record`，strict扫描 `artifact`/object中 exact `run_id + engine_schema_version` 的 `ResearchRun@*` 或 `ResearchRunCompatibility@*` source JSON/HTML；零个或多个候选以 `RESEARCH_SOURCE_ARTIFACT_NOT_UNIQUE` fail closed。把 record pointers一次性归回 source artifacts；旧 immutable objects、旧 final manifests和旧 `research_json/research_html` refs不修改不删除。已有 DecisionView严格验证后复用；只有 typed DataSnapshot/Forecast/Valuation graph完整的历史 workflow才可由 frozen bytes按 `ResearchDecisionViewMaterialization@1`一次性 materialize，缺输入则整次迁移失败，不制造 legacy limited view。
5. data migration由唯一 `python -m trading_platform.cli migrate` maintenance path触发：先证明 server/workflow presence为空且所有 workflow均 terminal；`queued/running` 任一存在返回 `MIGRATION_WORKFLOW_NOT_TERMINAL`，必须在旧 code identity下先 resume/cancel，不在新 runtime执行 legacy definition。然后生成并验证包含 SQLite+全部 object blobs 的 immutable full backup，再持有 data-root writer lock；对象可先durable publish，所有 pointer/ref/manifest变更在一个 SQLite transaction提交。失败只留下可审计 orphan object，DB回滚；重复 migrate exact replay。迁移完成条件由“每个成功 workflow恰有一个完整 decision manifest + 每个 research record指向唯一 source”本身证明，无另一个 shadow journal。
6. 新 composition/runtime在 cutover不完整时拒绝 serve/workflow并返回 `RESEARCH_VIEW_CUTOVER_INCOMPLETE`；fresh empty root视为 vacuously complete。已完成 workflow@1只读，failed/cancelled历史只由 inspection显示；不恢复执行，不改其 definition hash。

迁移验收矩阵必须覆盖 fresh root、无 workflow的旧 root、created/reused typed workflows、多个 workflow共享 ResearchRun、materialization、source zero/multiple、running/queued refusal、object fault、DB commit fault、exact retry、backup restore、old workflow只读与new workflow@2。`view_id`、`ResearchDecisionView@2`和旧 artifact bytes保持现有 identity；唯一新 identity是 versioned decision manifest/ref，不把 ResearchRun冒充 DecisionView。

票内 gate为上述 12 个 Python files、`npm test`、带 bundled runtime的 workbook 4 tests且 `0 skipped`，以及在迁移前备份的 populated fixture root上执行 `migrate -> doctor -> history/archive -> backup -> restore -> doctor`。不得把当前 ProjectVerification允许skip视为本票通过。

### TB-5 — 切换 CLI/research/data/account/market tasks并删除旧 file/V3 入口

**Blocker**：TB-4。**估算**：`XL`，1 context，约 28 个 production/docs files + 14 个 tests。

精确文件集合：

- 创建 `src/trading_platform/application/bootstrap.py`、`health.py`、`daily.py`、`research_archive.py` 与 `src/trading_platform/watchlist.py`；修改 `application/contracts.py`、`facade.py`、`ports.py`、`root.py`、`application/__init__.py`、`trading_platform/__init__.py`；
- 修改 `src/trading_platform/cli.py`、`operations.py`、`provider_qualification.py`、`data/service.py`、`data/repository.py`、`account.py`、`account_import.py`、`account_history.py`、`account_acceptance.py`、`market.py`、`plans.py`、`persistence/runtime.py`、`persistence/__init__.py`、`workflows/research/workflow.py`、`workflows/research/execution.py`、`workflows/research/inspection.py`；删除 `src/trading_platform/persistence/watchlist.py`，把其 identity/idempotency/transaction行为完整迁入 Watchlist task而非包一层转发；
- 删除 `src/equity_research/cli.py`、`src/equity_research/__main__.py`、`scripts/research.py`、`src/equity_research/report.py`、`src/equity_research/professional_report.py`；修改 `src/equity_research/models.py`、`engine.py`、`__init__.py`，使 ResearchRun不再拥有 old HTML runtime branch；
- 修改 `pyproject.toml`、`README.md`、`skills/SKILL.md`、`examples/duofuduo-002407/README.md`、`docs/current-state-audit.md`、`docs/architecture/target-architecture.md`；删除 `equity-research` console script与所有 `scripts/research.py` instructions，正式研究只写 `python -m trading_platform.cli` task path；
- 删除 `tests/test_cli.py`；创建 `tests/platform/test_data_repository.py`；修改 `tests/test_research_engine.py`、`tests/test_skill_entrypoint.py`、`tests/platform/regression_baseline.json`、`test_runtime_skeleton.py`、`test_project_verification.py`、`test_watchlist_persistence.py`、`test_data_sync_pit.py`、`test_provider_qualification.py`、`test_research_workflow.py`、`test_workflow_recovery.py`、`test_account_opening.py`、`test_account_history_import.py`、`test_market_evaluation.py`、`test_operations_backup_restore.py`。

composition bootstrap静态注入每个 CLI operation所需的 named task；不得返回 root、`.tasks` bag或字符串 service lookup。`sync`、`DailyResearchCycle`、`ResearchWorkflow`、`WorkflowInspection`、`ResearchArchive`、account tasks、market builder/evaluator、provider qualification和maintenance全部直接跨各自 task interface。`DailyResearchCycle`是唯一 daily跨任务编排，provider qualification是唯一 qualification编排。Facade在同一票删除 health/watchlist/data/research/account/market methods及相应 ports，CLI/provider/tests不得再使用 `.facade`；Facade暂时仅服务尚未迁移的 Web chart/workspace/plan routes，不能新增 method。

把数据、计划、市场中需要证明持久化 adapter的 direct-SQL tests分别移入 owning repository adapter tests；application tests只经 task results/inspection views观察。`test_runtime_skeleton` 不再强制所有 platform code从 109-name root package导入，而是断言只可从各 canonical package interface导入且禁止 package-private modules。`regression_baseline.json` 删除 `test_cli.py`固定计数，保留 ResearchEngine的事实/证据/计算/金融边界回归；旧 HTML-only assertions删除，canonical DecisionView HTML tests承接 escaping/boundary/progressive disclosure。

票内删除门：active source/docs/tests中 `equity-research` entry、`scripts/research.py`、`ResearchRunCompatibility`、`ResearchReportHtmlCompatibility`、旧 report renderer、Facade非Web methods、root Forecast/Scenario/View builder aliases均为零。历史 `.scratch` 决策和 immutable data内schema string不参与runtime清理。

### TB-6 — 切换 Web tasks、删除 Facade并完成 release proof

**Blocker**：TB-5。**估算**：`XL`，1 context，约 18 个 production/Web/script files + 12 个 tests；这是最后一次 adapter cutover，不含新产品功能。

精确文件集合：

- 创建 `src/trading_platform/application/decision_workspace.py`、`chart_workspace.py`、`trade_plan_workspace.py`、`update_authorization.py`；修改 `application/bootstrap.py`、`contracts.py`、`application/__init__.py`、`trading_platform/__init__.py`；
- 修改 `src/trading_platform/chart.py`、`plans.py`、`market.py`、`workspace.py`、`web_server.py`、`cli.py`；删除 `src/trading_platform/application/facade.py`、`application/ports.py`、`application/root.py`；
- 删除 `scripts/serve_chart_workspace.py`；修改 `scripts/verify_issue05_browser.py`，移除对 `tests.platform.test_chart_annotations._root` 的 import，改由 production bootstrap + canonical fixture task建立真实 server；
- 修改 `web/src/app.js`、`web/tests/mutation-runner.test.js`、`web/tests/workspace-policy.test.js` 以消费不变 HTTP shape后的canonical task projection；`web/src/chart-adapter.js`、`web/tests/chart-adapter.test.js`、`web/package.json`、`web/package-lock.json`、`web/THIRD_PARTY_NOTICES.md` 与 licenses只作无漂移验证，因为本 effort不改变图表库或依赖；build后按源码重新生成并核对 `web/dist`；
- 创建/重组 owning adapter tests `tests/platform/test_chart_repository.py`、`test_plan_repository.py`、`test_market_repository.py`；修改 `test_chart_annotations.py`、`test_trade_plans.py`、`test_market_evaluation.py`、`test_account_workspace_plans.py`、`test_decision_research_view.py`、`test_secure_workspace.py`、`test_account_opening.py`、`test_operations_backup_restore.py`、`test_acceptance_evidence.py`、`test_project_verification.py`、`test_runtime_skeleton.py`。

`LocalChartWorkspaceServer`构造函数显式接收 `DecisionWorkspace`、`ChartWorkspace`、`ChartAnnotations`、`PlanConfirmation/TradePlans`和`WorkspaceUpdateAuthorization`的窄 interfaces；不接 root/container。GET chart/annotation routes可投影一次 `ChartWorkspace.open` 的不同字段；POST annotation只调用一个 typed lifecycle command，不在 adapter读 history/series后决定领域操作。计划、market、account和research历史只从组合 workspace views进入 Web。

同一票迁移全部 remaining production/test callers后删除 Facade、mirror ports、`root.facade`、nullable backing objects、root private store exposure和所有 forwarding assertions。composition bootstrap只负责静态 wiring/lifetime；删除它若只把 constructors移入 adapters是预期 composition职责，不把业务策略放入 bootstrap。任何 application journey里的 `root._store.connection`迁到 public task/inspection；只有新 repository adapter、migration、corruption tests保留 storage access。

### 完成证据与 release gate

每张 implementation ticket运行自己的窄 gate；TB-6 关闭前还必须依次满足全部证据，任一 skipped、timeout、external check未运行或 nonzero 都不能写成 pass：

1. **静态/删除**：`git diff --check`；AST dependency guard；在 `src/ web/src/ scripts/ skills/ README.md docs/ pyproject.toml tests/` 搜索 `ApplicationFacade|ResearchWorkflowService|WorkflowRepository|ResearchRunCompatibility|ResearchReportHtmlCompatibility|renderSandboxReport|scripts/research.py|equity-research|_financial_projections|_discount_times|_financial_from_forecast|_value_market_divergence|root.facade|root._workflow_repository`，除专门的 forbidden-symbol assertion文本外零命中；无 `TODO/FIXME`、alias、feature flag、dual decoder、old file wrapper。
2. **完整 Python/Web**：`python -m trading_platform.cli test --repo-root .`，六个 suites全 pass；`npm test`与`npm run build`（cwd=`web`）全 pass；测试清单证明每个 Python/Web test恰好执行一次。当前基线为 Python `380 collected = 377 passed + 3 skipped`、Web `18 passed`；目标必须是迁移后的实际 collected count全部 pass，不能固定沿用旧计数。
3. **Workbook**：通过 workspace bundled runtime设置 `CODEX_ARTIFACT_NODE`与`CODEX_ARTIFACT_NODE_MODULES`，执行 `python -m pytest -q tests/platform/test_valuation_workbook_adapter.py`，4 passed、0 skipped，并验证 exact canonical view、reconciliation和tamper failures。
4. **真实 Chromium**：先 `npm run build`，再 `python scripts/verify_issue05_browser.py --keep-artifacts`；必须使用本机 Chrome/Edge CDP完成真实 HTTP、reload/server restart、chart/annotation lifecycle、plan confirmation、workspace DecisionView、security headers、keyboard/narrow viewport/reduced motion检查并生成不含私密路径的 evidence。Node DOM tests不替代此项。
5. **迁移/恢复**：在 fresh root、N-1 fixture root与含 created+reused workflow的 populated root分别执行 canonical `backup -> migrate -> doctor -> history/archive -> backup -> restore -> doctor`；校验 backup sha/count、SQLite integrity/foreign keys、全部 object hashes、GraphIdentity@2新旧并列、ResearchRun source pointers、每个成功 workflow唯一 decision manifest、失败注入回滚和重试 identity。restore只能到新 root；不提供 down migration或删除旧 immutable artifacts。
6. **Release acceptance**：`python -m pytest -q -m release_acceptance tests/platform/test_acceptance_evidence.py` 必须0 skipped；随后运行 `python -m trading_platform.cli acceptance --data-root <fresh-root> --fixture-manifest tests/fixtures/platform_data/manifest.json --repo-root .`，若有当前 live qualification artifact则显式传入。acceptance suite ledger、51 criteria、command identities、browser/backup/legacy-replacement evidence和immutable manifest自校验全部通过；真实 provider不可用可保持精确 `external_blocked`，但不能伪造 qualified或把结构回归标为通过。
7. **行为/failure矩阵**：public task journeys覆盖 create/replay/conflict、restart、created/reused research、workflow retry/lease/cancel、artifact corruption、Forecast四类 archetype、Scenario四方法族、view permission/comparability、chart/plan/account/market immutable history、CLI JSON/HTTP security与金融输出边界。每个失败必须保留 owning module的 typed code和redacted substep evidence；不得 broad-catch成同一个错误。
8. **最终人工审计**：检查 `git status`与完整 diff，确认只包含该 ticket声明文件；README、Skill、examples、tests和runtime只命名一个 current path；依赖/lock/NOTICE与dist一致；用户无关dirty changes未被清理、暂存或覆盖。

### No-compatibility commit discipline

- package替换使用同一 commit的 delete-file/create-package；Python不能同时保留 `forecast.py`+`forecast/`、`scenario.py`+新 engine wrapper、`research.py`+new workflow dispatcher。
- 每个 semantic owner只有一个 writer和一个 decoder。内部 target module可先在同一 working change中构建，但在commit边界前必须完成caller切换与旧代码删除；不提交半成品中间层。
- 持久化迁移先完整备份、再preflight、再单writer/单transaction；成功后runtime只读target refs。旧 bytes留作历史证据不等于旧 runtime path；禁止以历史 artifact存在为由保留旧 decoder。
- 测试是替换关系：目标 interface测试覆盖同一行为后删除旧 private/Facade测试；不得把两套 suite都留在 acceptance ledger。corruption测试只能位于 owning persistence adapter package。
- 若实施时发现某一旧 artifact无法唯一归位、running workflow无法用旧 code drain、或声明外的真实 caller仍依赖旧 interface，该 implementation ticket必须保持未完成并记录精确 blocker；不得用 fallback、alias或临时 wrapper越过。

### Map closeout

六个 implementation tracer bullets的 interface、文件集合、blocker、删除条件、failure/identity/migration和验收命令均已锁定；`Not yet specified` 的 implementation拆分、私有测试归类和旧入口/renderer删除清单均已在本票毕业，没有新增 Wayfinder child issue。

`ResearchDecisionViewCutover@1` 是一次性技术迁移policy，不新增领域概念，故不修改 `CONTEXT.md`。它使用既有 schema/ref/manifest能力且不引入难以回退的新数据库结构；完整取舍和证据已由本票记录，不新增 ADR。地图完成后的唯一下一步是 `/to-spec .scratch/code-structure-deepening/map.md`，本轮不执行 `/to-spec`、`/to-tickets` 或 `/implement`。
