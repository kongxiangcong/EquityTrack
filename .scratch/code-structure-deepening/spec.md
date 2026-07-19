# 代码结构深模块改造 Spec

Status: `ready-for-agent`

## Problem Statement

当前平台已经形成研究、推演、估值、动态工作流、账户、图表、交易计划与复盘能力，但应用层和核心领域仍存在过宽且浅的接口、职责跨模块漂移、重复语义构建和存储旁路。`ApplicationFacade` 镜像大量底层方法；Forecast、Scenario Valuation、Workflow persistence、Workflow execution 与 Research decision view 的行为分别集中在大型多职责模块或被多个调用者重复解释；CLI、Web、测试和脚本还能接触私有对象、连接或旧入口。

这使一次局部修改可能同时触碰计算、状态机、持久化、展示和适配器，降低模块 leverage 与 locality，也让旧路径、兼容分支、双重 decoder 和私有测试持续存在。更严重的是，当前 ResearchRun source artifact 与 workflow-scoped DecisionView 的引用职责发生混合；如果仅机械拆文件或并行建立新实现，将破坏不可变历史、artifact identity、恢复语义和“一项能力只有一条正式路径”的仓库约束。

本 Spec 要在不改变正式平台可观察行为、不新增产品能力、不重写既有 MVP 的前提下，把这些职责原子迁移到少量 deep modules。每个迁移单元必须同时替换调用者和测试、删除旧实现与导出、完成必要的数据 cutover，并以公开行为、typed failure、不可变 artifact、备份恢复和真实浏览器证据证明完成。

## Solution

平台将按 blockers-first 顺序完成六个 tracer bullets：先建立 Forecast 的唯一领域入口与 versioned graph identity，再建立 Scenario Valuation 的唯一方法族入口；并行依赖链先建立纯领域 `ArtifactLineage` 与唯一持久化所有者 `WorkflowLedger`，随后原子替换 Research Workflow、Research Execution 和 canonical Research Decision View；最后先切换 CLI 及非 Web application tasks，再切换 Web tasks并删除 `ApplicationFacade`。

目标结构以用户任务为应用边界，以领域接口为行为边界，以 persistence adapter 为存储边界。CLI、Web、脚本和测试只依赖窄的 named task interfaces；领域计算不依赖适配器或具体存储；持久化负责事务、锁、对象发布、manifest 与恢复；renderers 只投影已经持久化的 typed view，不重算研究或估值语义。

迁移采用 replace-in-place 而非兼容期。每个 tracer bullet 在一个 implementation context 和一个 commit 中建立目标回归、迁移全部真实调用者、删除旧实现/导出/私有测试、执行搜索清零和窄 gate。涉及历史数据的 cutover 必须 backup-first、fail-closed、可精确重放；旧不可变 bytes 可保留为历史证据，但旧 runtime decoder、fallback、alias、wrapper、双读或双写不得保留。

## User Stories

1. As a platform user, I want existing research, chart, account, plan, and review journeys to retain their observable behavior, so that an architectural refactor does not disrupt my local workflow.
2. As a platform user, I want historical ResearchRun, WorkflowRun, DataSnapshot, Forecast, Valuation, PlanEvaluation, and ArtifactManifest identities to remain traceable, so that old decisions stay reproducible.
3. As a platform user, I want every new successful workflow to expose one canonical decision view, so that workspace and archive views cannot disagree.
4. As a platform user, I want missing or inconsistent historical evidence to stop migration with a precise reason, so that the platform never fabricates a usable view from incomplete data.
5. As a platform user, I want migration to create and verify a complete local backup before changing data, so that my private history is recoverable.
6. As a platform user, I want completed legacy workflows to remain inspectable but immutable, so that code upgrades cannot rewrite recorded history.
7. As a platform user, I want queued or running workflows to block migration until they are resolved under their original definition, so that no workflow silently changes semantics mid-run.
8. As a platform user, I want CLI and Web behavior to report typed, redacted, actionable failures, so that I can understand the failing substep without exposing local secrets.
9. As a platform user, I want financial-output safety boundaries to remain unchanged, so that architecture work cannot introduce unsupported ratings, target prices, or investment instructions.
10. As a platform user, I want the Web workspace to preserve security, accessibility, reload, and restart behavior, so that internal restructuring is invisible at the product boundary.
11. As a research operator, I want one `ForecastEngine.build` entry point, so that all supported company archetypes follow the same externally visible forecast contract.
12. As a research operator, I want Forecast evidence classification, driver-graph algebra, and manufacturing three-statement projection to have clear owners, so that evidence and calculation policy are not duplicated.
13. As a research operator, I want Forecast graph identities to distinguish archetype-specific semantics, so that two different graphs cannot collide under the same identity.
14. As a research operator, I want one `ScenarioValuationEngine.run` entry point, so that scenario construction and valuation routing remain deterministic and reviewable.
15. As a research operator, I want industrial, cyclical, financial-institution, and biopharma valuation economics to remain in complete method-family modules, so that sector-specific policy is not spread across callers.
16. As a research operator, I want Scenario Set and Valuation Basis to bind assumptions, probabilities, Forecast inputs, and equity bridges, so that scenario aggregation cannot combine incomparable methods.
17. As a research operator, I want one typed `ResearchDecisionView@2` built from an explicit `ResearchDecisionInput`, so that display permission, comparability, uncertainty, and financial boundaries are decided once.
18. As a research operator, I want HTML, workbook, workspace, and archive renderers to load the persisted DecisionView, so that presentation layers never reinterpret source artifacts.
19. As a research operator, I want ResearchRun source artifacts to remain distinct from workflow-scoped DecisionView artifacts, so that execution evidence is not mistaken for a presentation record.
20. As a workflow operator, I want `ResearchWorkflow.handle` to own run, lease, checkpoint, retry, cancellation, and transition policy, so that lifecycle rules have one owner.
21. As a workflow operator, I want `ResearchExecution.execute` to own only selected research-node execution and gates, so that execution logic cannot mutate workflow lifecycle independently.
22. As a workflow operator, I want workflow inspection and forecast review to be separate read/task seams, so that query behavior does not become another state-machine writer.
23. As a workflow operator, I want workflow definitions to be versioned and new runs to use only the new definition, so that replay and audit semantics are explicit.
24. As a persistence maintainer, I want pure `ArtifactLineage.validate` checks, so that artifact graph invariants can be tested without a database.
25. As a persistence maintainer, I want `WorkflowLedger` to be the sole owner of workflow SQL, locks, object registration, manifests, references, and aggregate transactions, so that no caller can create partial state.
26. As a persistence maintainer, I want durable object publication before atomic database registration, so that crashes may leave only auditable orphan objects and never dangling database references.
27. As a persistence maintainer, I want create, replay, conflict, concurrent writer, restart, corruption, and rollback behavior to have stable typed codes, so that recovery logic is deterministic.
28. As a maintainer, I want CLI operations to receive only their named application tasks, so that the composition root cannot become a service locator or business facade.
29. As a maintainer, I want Web routes to receive only DecisionWorkspace, ChartWorkspace, ChartAnnotations, TradePlan, and update-authorization interfaces, so that HTTP adapters cannot read storage and make domain decisions.
30. As a maintainer, I want daily research orchestration and provider qualification to each have one explicit task owner, so that cross-task policy is not duplicated in adapters.
31. As a maintainer, I want watchlist identity, idempotency, and transactions to live behind one application task, so that moving it out of persistence does not create a forwarding wrapper.
32. As a maintainer, I want the old file/V3 research entry, duplicate research script, and legacy HTML renderers removed after caller migration, so that documentation and runtime name only the canonical platform path.
33. As a maintainer, I want root-package aliases and private-object getters removed, so that callers import canonical package interfaces and tests cannot bypass them.
34. As a maintainer, I want target-interface tests to replace private-method and Facade-forwarding tests, so that the suite protects behavior rather than implementation shape.
35. As a maintainer, I want every implementation ticket to delete its superseded code in the same commit, so that no commit introduces an old/new compatibility period.
36. As a maintainer, I want static dependency guards and forbidden-symbol checks, so that future changes cannot quietly reintroduce storage bypasses or retired interfaces.
37. As a maintainer, I want one stable full-project verification command with visible sub-suite evidence, so that a timeout, skip, or external blocker cannot be reported as a pass.
38. As a maintainer, I want real Chromium acceptance after the Web cutover, so that DOM-only tests cannot hide browser, restart, security, keyboard, viewport, or reduced-motion regressions.
39. As a maintainer, I want fresh, prior-version, and populated data roots exercised through backup, migrate, doctor, archive, restore, and doctor, so that the cutover is proven against realistic local state.
40. As a maintainer, I want the final documentation, Skill entry, examples, runtime, tests, dependencies, notices, and built assets to describe one current path, so that the repository has no operational ambiguity.

## Implementation Decisions

- Formal platform behavior, domain semantics, immutable history, persisted data, security boundaries, typed failure contracts, and artifact identities are protected. Retired private interfaces, duplicate entry points, forwarding methods, and old renderers are not compatibility surfaces.
- The dependency direction is adapters to named application tasks to domain modules, with persistence implementing domain/application ports. Domain modules must not import CLI, Web, presentation, or concrete persistence.
- The migration is split into six ordered tracer bullets: Forecast; Scenario Valuation; ArtifactLineage plus WorkflowLedger; Research Workflow plus Research Execution plus DecisionView cutover; CLI and non-Web task cutover; Web task cutover and final Facade deletion.
- Each tracer bullet is one implementation context and one commit. Before its commit boundary, all in-scope production and test callers must use the target interface and every superseded runtime path, export, fixture, test, instruction, and dependency must be removed.
- `ForecastEngine.build` is the sole external Forecast operation. `ForecastEvidence` owns typed fact/assumption/evidence normalization, `ForecastGraph` owns driver-graph invariants and identity, and `ManufacturingForecast` owns manufacturing projection behavior. Internal shells do not become public forwarding modules.
- New Forecast graphs use `ForecastGraphIdentity@2` with an `fg2_` identity that includes the semantics needed to prevent cross-archetype collision. Existing immutable graph bytes and identities remain valid historical evidence; there is no runtime compatibility branch that regenerates them.
- `ScenarioValuationEngine.run` is the sole external scenario-valuation operation. Scenario Set owns scenario and probability policy; Valuation Basis binds selected methods, Forecast inputs, currencies, accounting comparability, equity bridges, and method applicability.
- Industrial, cyclical, financial-institution, and biopharma method families each own complete sector economics and deterministic calculations. Aggregation is allowed only across scenarios using the same applicable method; cross-method weighted target values are forbidden.
- `ArtifactLineage.validate` is a pure domain operation that validates typed frozen evidence, artifact roles, graph completeness, identity relationships, and replay invariants without opening persistence.
- `WorkflowLedger` is the single persistence owner for WorkflowRun aggregate state, lease and checkpoint changes, object registration, artifact edges, manifests, references, exact replay, and transactional recovery. It exposes no raw connection or object-store escape hatch.
- Object writes follow durable temporary write, flush, hash, and atomic rename before a single immediate database transaction records the object, artifacts, edges, manifest, references, and state transition. Failure may leave an unreferenced object, but never a committed dangling reference.
- `ResearchWorkflow.handle` is the sole owner of workflow lifecycle policy. `ResearchExecution.execute` receives an already selected node and executes research gates without owning leases or transitions. `WorkflowInspection.inspect` and Forecast Review are separate query/task seams.
- New research workflows use `research-workflow@2`. A migration preflight rejects every queued or running workflow; such work must be resumed or cancelled under its old code identity before cutover. Completed workflow version 1 histories are read-only, while failed or cancelled histories remain inspection-only.
- `ResearchDecisionViewBuilder.build(ResearchDecisionInput)` is the only DecisionView builder. A workflow builds and persists exactly one typed `ResearchDecisionView@2`; HTML and workbook forms are projections of that persisted view, never independent semantic builders.
- ResearchRun source JSON/HTML and workflow-scoped DecisionView JSON/HTML have distinct ownership and references. A ResearchRun record always points to its unique source artifacts; a successful workflow points to one immutable `workflow_decision_view@1` manifest containing exactly `decision_view_json` and `decision_view_html` members through one `decision_view_manifest` reference.
- `ResearchDecisionViewCutover@1` reuses existing schema, manifest, and reference capabilities; it does not introduce a new SQL schema or shadow migration journal. Completeness is proven by exact source-pointer uniqueness and exactly one complete decision manifest per successful workflow.
- Historical source artifacts are matched by exact ResearchRun identity and engine schema. Zero or multiple matches fail closed. Existing valid DecisionViews are reused; a missing view may be materialized once only from a complete frozen typed DataSnapshot, Forecast, and Valuation graph. Incomplete history fails the entire migration.
- The canonical migration operation first proves no server or nonterminal workflow is active, then creates and validates a full immutable backup containing the database and every object blob, acquires the data-root writer lock, publishes objects durably, and commits all pointer/ref/manifest changes in one transaction. Retry is identity-stable and exact.
- A partially cut-over populated root cannot serve or run workflows and returns `RESEARCH_VIEW_CUTOVER_INCOMPLETE`. A fresh empty root is vacuously complete. There is no down migration, dual decoder, schema-prefix guessing, fallback, or old-definition execution in the new runtime.
- CLI operations receive named application tasks through static composition. Bootstrap owns wiring and lifetime only; it does not expose a root object, task bag, service lookup, or business workflow.
- Daily research and provider qualification each retain one canonical orchestrator. Research workflow, workflow inspection, research archive, health, data, watchlist, account, market, and maintenance operations cross their own complete task interfaces.
- The old equity-research console entry, duplicate research script, file/V3 runtime route, legacy ResearchRun HTML branch, and duplicate report renderers are deleted after CLI/task cutover. The canonical maintenance and formal research path remains the platform CLI.
- The Web server receives narrow DecisionWorkspace, ChartWorkspace, ChartAnnotations, TradePlan, and update-authorization interfaces. GET routes project returned task views; POST routes invoke one typed lifecycle command and do not read history or series to decide domain behavior.
- `ApplicationFacade`, mirror ports, root Facade access, nullable backing objects, private store exposure, and forwarding assertions are deleted only after every CLI, Web, script, and test caller has moved to the named task interfaces. No replacement bus, locator, compatibility Facade, or argument-forwarding wrapper is allowed.
- Repository adapter tests may access their owned persistence fault seams. Application journey tests, CLI tests, Web tests, and acceptance tests cross public task interfaces and observe typed task results or inspection views; they must not use raw SQL or private methods.
- Existing HTTP response shapes and user-visible workflow semantics remain stable unless a typed correction explicitly specified above requires a versioned identity or reference change.
- Documentation, Skill instructions, examples, tests, runtime entry points, dependency metadata, notices, and built Web assets must name and contain only the canonical current path when the final tracer bullet closes.
- If implementation discovers a source artifact that cannot be uniquely restored, a workflow that cannot be drained under old code, or an undeclared real caller of a retired interface, the current ticket remains incomplete with a precise blocker. A fallback, alias, feature flag, or temporary wrapper is not an acceptable workaround.

## Testing Decisions

- Tests protect the highest public seam that owns the behavior. Domain calculation tests use the one public engine operation; workflow tests use `ResearchWorkflow`; application journeys use named task interfaces; CLI/Web tests use their stable adapter contracts. Direct private-method and forwarding tests are deleted after replacement coverage exists.
- `ArtifactLineage` tests run without SQLite and cover typed evidence, role, identity, graph-completeness, tamper, and replay invariants. `WorkflowLedger` adapter tests cover atomic aggregate transactions, leases, fingerprints, checkpoints, object faults, collisions, concurrent writers, restart, rollback, and doctor audits.
- Forecast tests cover all supported archetypes through `ForecastEngine.build`, deterministic results, evidence classification, graph invariants, three-statement reconciliation where applicable, `ForecastGraphIdentity@2`, old immutable identity coexistence, and typed failures.
- Scenario Valuation tests cover the four method families through `ScenarioValuationEngine.run`, router applicability, scenario probability rules, Forecast binding, currency/accounting/peer gates, equity bridges, sensitivities, same-method aggregation, and disabled-method reasons.
- Workflow tests cover create, exact replay, conflict, created/reused ResearchRun, lease, heartbeat, retry, checkpoint, cancellation, recovery, inspection, Forecast Review, immutable manifests, and typed failure propagation without direct workflow SQL.
- DecisionView tests cover the single typed builder, display permission, data quality, uncertainty, comparability, financial-output boundaries, persisted byte loading, HTML escaping and progressive disclosure, workbook reconciliation, and tamper failures. Renderer tests must prove no semantic recomputation.
- Cutover tests cover a fresh root, an old root without workflows, created and reused typed workflows, multiple workflows sharing one ResearchRun, existing-view reuse, one-time materialization, zero/multiple source matches, queued/running refusal, object failure, database commit failure, exact retry, backup restore, old workflow read-only behavior, and new workflow version 2 behavior.
- CLI and application tests cover health, data sync, watchlist, daily orchestration, provider qualification, research, workflow inspection, archive, account, market, maintenance, and typed/redacted diagnostics exclusively through named tasks.
- Web tests cover unchanged HTTP contracts, DecisionWorkspace projections, chart and annotation lifecycle, TradePlan lifecycle, update authorization, immutable history, security headers, keyboard behavior, narrow viewport, and reduced motion. Node tests do not substitute for real browser acceptance.
- Static gates enforce inward dependencies, forbid concrete persistence outside owning adapters, prevent package-private imports, and require zero active references to retired Facade, repository, workflow service, compatibility schema decoder, duplicate renderer, old CLI/script, root getters, and directly tested private helpers.
- Every tracer bullet runs a narrow affected-suite gate before commit. The final gate runs `python -m trading_platform.cli test --repo-root .`, `npm test`, and `npm run build`; all discovered Python and Web tests must execute exactly once, with no timeout or unreported skip.
- Workbook acceptance sets the bundled artifact runtime and runs the workbook adapter suite with exactly four passing tests and zero skipped tests, including canonical view, reconciliation, and tamper behavior.
- Real browser acceptance builds the Web assets and runs `python scripts/verify_issue05_browser.py --keep-artifacts` against a production bootstrap and local HTTP server using Chrome or Edge CDP. It must verify reload, server restart, chart/annotation lifecycle, plan confirmation, DecisionView workspace, security, keyboard, viewport, and reduced-motion behavior.
- Migration acceptance exercises fresh, prior-version fixture, and populated roots through canonical `backup -> migrate -> doctor -> history/archive -> backup -> restore -> doctor`. It verifies backup hashes/counts, database integrity and foreign keys, object hashes, old/new Forecast graph identities, ResearchRun source pointers, unique DecisionView manifests, injected rollback, and identity-stable retry.
- Release acceptance runs `python -m pytest -q -m release_acceptance tests/platform/test_acceptance_evidence.py` with zero skipped tests, followed by the canonical acceptance CLI against a fresh root and fixture manifest. External provider unavailability may remain explicitly `external_blocked`; it may not be represented as qualified or passed.
- The final behavior/failure matrix covers create/replay/conflict, restart, workflow lifecycle, artifact corruption, Forecast archetypes, Scenario method families, DecisionView permission/comparability, chart/plan/account/market immutable history, CLI JSON, HTTP security, and financial-output boundaries. Each failure preserves the owning module's typed code and redacted substep evidence.
- Before completion, inspect `git status`, the complete diff, dependency and notice drift, generated assets, documentation, and forbidden symbols. Existing unrelated user changes must remain untouched and must not be staged as part of this effort.

## Out of Scope

- New research methods, valuation methods, Forecast archetypes, trading strategies, account capabilities, providers, data sources, automated trading, or personalized investment advice.
- Changes to product information architecture, visual styling, chart-library selection, or Web features beyond caller migration required to preserve formal behavior.
- Mechanical file splitting for line-count reduction, empty package scaffolding, speculative ports, forwarding modules, service buses, locators, adapters around retired interfaces, or a big-bang rewrite.
- Runtime LLM integration, natural-language prompts in business code, or moving deterministic financial calculations into Codex/Skill control-plane behavior.
- Down migrations, deletion or rewriting of immutable historical artifacts, compatibility aliases, dual reads/writes, old-schema fallback, or parallel old/new renderers.
- Unrelated performance optimization, dependency upgrades, build-system replacement, repository cleanup, or changes to the completed test-execution infrastructure.
- Changes to database schema unless implementation evidence invalidates the resolved no-schema-change decision and the work is stopped for a new explicit decision.

## Further Notes

- This Spec synthesizes the completed Wayfinder decisions. It intentionally records interfaces, ownership, dependencies, migration semantics, deletion gates, and public acceptance behavior without freezing implementation file paths.
- The current evidence baseline is 380 active Python tests collected as 377 passed plus 3 skipped, and 18 Web tests passed. These counts are diagnostic only; completion requires the post-migration discovered test set to pass, the workbook suite to report zero skips, and the real Chromium and release-acceptance gates to run successfully.
- The refactor must preserve the repository's local-first/privacy boundary and financial-output boundary. No acceptance result may silently turn missing official evidence into a valuation conclusion, rating, target price, or investment instruction.
- Implementation tickets should retain the six tracer-bullet boundaries and declared blocking order. If a ticket cannot finish its caller migration, deletion gate, data migration, and narrow tests in one context, it must remain incomplete rather than commit a compatibility period.
