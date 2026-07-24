# Research/artifact replacement and deletion matrix

Captured: `2026-07-24`

Scope: read-only audit of the current checkout's Forecast, deterministic
scenario valuation, valuation Monte Carlo, market-path simulation, research
workflow, immutable artifact lineage/persistence, and canonical
`ResearchDecisionView@2` JSON/HTML/Web/XLSX path. This asset supplies the
research/artifact portion of Wayfinder ticket 02. It does not resolve the
ticket, change production code, or design the final `StrategyValidation`
interface.

The four decision words below are candidate conclusions, not evidence that a
later qualification ticket has already admitted an upstream capability.

## Current canonical path

```text
CLI / named application opener
  -> ResearchWorkflow.handle(StartResearchWorkflow(ResearchWorkflowRequest))
  -> ResearchEngine.run(ResearchRequest)
       -> optional ForecastEngine.build(ForecastRequest) -> ForecastGraph
  -> caller-supplied typed ImmutableArtifactDraft values
       Forecast -> Valuation -> optional Simulation
       optional Simulation + MarketDataSnapshot -> MarketPathSimulation
  -> ArtifactLineage.validate(...) -> WorkflowLedger transaction -> SQLite/CAS
  -> ResearchDecisionViewBuilder.build(...) -> ResearchDecisionView@2
  -> one persisted JSON + one persisted HTML
  -> ResearchArchive / Web workspace / XLSX adapter consume that view
```

This is not inferred from documentation alone:

- `ResearchWorkflow.handle` is the named task interface and owns start/replay,
  resume, cancellation, lease and lifecycle dispatch
  (`src/trading_platform/workflows/research.py:496-567`). The production
  composition root constructs it directly
  (`src/trading_platform/application/bootstrap.py:184-190`), while CLI tasks
  and the CLI cross `handle`, rather than calling persistence
  (`src/trading_platform/application/cli_tasks.py:133`,
  `src/trading_platform/cli.py:187`).
- `ResearchEngine.run(ResearchRequest) -> ResearchRun` is the deterministic
  inner research module; it validates manifest/security/as-of identity before
  calling `ForecastEngine.build`
  (`src/equity_research/engine.py:151-180`).
- The architecture document names the same path, including
  `ForecastGraphIdentity@2`, `ScenarioValuationEngine`, optional Simulation and
  MarketPathSimulation, and persisted `ResearchDecisionView@2`
  (`docs/architecture/target-architecture.md:29-50`).
- Typed analysis artifacts are submitted in the workflow request, previewed
  as a bundle, lineage-validated, and committed in the workflow's research
  checkpoint (`src/trading_platform/workflows/research.py:770-868`).

## Module-by-module evidence, impact, gaps, and deletion test

### Forecast and `ForecastGraphIdentity@2`

**Canonical implementation/interface.** `ForecastEngine.build(ForecastRequest |
DataInsufficientForecastRequest) -> ForecastGraph` is a one-operation
interface. It validates evidence, routes by company archetype, constructs an
explicit blocked graph on insufficient data, and delegates complete
manufacturing behavior internally
(`src/equity_research/forecast/__init__.py:45-129`). Scenario valuation also
uses this exact interface for its base/reference and each scenario-specific
graph (`src/equity_research/scenario_valuation/engine.py:99-130`).

`ForecastGraphCompiler.compile` materializes typed nodes/edges and obtains the
graph identity only through `ForecastGraphIdentity.build`
(`src/equity_research/forecast/graph.py:142-194`). Identity v2 binds security,
snapshot id and content hash, periods, review date, overrides, the full graph,
and the schema marker before returning `fg2_<digest>`
(`src/equity_research/forecast/graph.py:391-441`). Current tests prove
determinism, sensitivity to archetype/review/overrides, and v2 coverage for
every supported archetype (`tests/test_forecast_graph.py:403-498`).

**Caller/persistence/presentation impact.** Forecast graph identity flows into
the `Forecast` artifact and into the valuation artifact's source/structure
identity (`src/trading_platform/domain/workflow.py:270-424`). Artifact lineage
requires a single subject, frozen as-of and matching model snapshot before it
creates immutable envelopes
(`src/trading_platform/domain/artifact_lineage.py:131-284`). The decision view
derives story, drivers and scenario financials from the persisted Forecast and
Valuation artifact payloads, never from an external prose report
(`src/trading_platform/research_view.py:101-180`).

**Real gaps.** The external candidates supply no typed ForecastGraph semantics
or equivalent identity contract. Public Equity Investing may supply prose;
`a-stock-data` has a free-standing `full_valuation`; Vibe supplies strategy
experiments. None binds the graph to frozen PIT source evidence and company
archetype. The physical Forecast implementation remains large
(`graph.py` is 1,070 lines), but the public interface is already narrow; file
size is not evidence that an upstream wrapper is a module boundary.

**Deletion test.** Deleting `ForecastEngine` would scatter evidence validation,
archetype routing, explicit degradation, graph construction/replay and identity
rules into ResearchEngine, ScenarioValuationEngine and tests. It is deep and
must remain. `ForecastGraphCompiler` and the identity policy are internal
implementation, not another application interface. Preserve the identity
behavior and `fg2_` namespace. Do not restore a reader/writer for the immutable
legacy `fg_` fixture (`tests/fixtures/legacy_forecast_graph_fg1.json`), and do
not introduce an upstream-to-Forecast wrapper or parallel graph type.

### `ScenarioValuationEngine`

**Canonical implementation/interface.** `ScenarioValuationEngine.run(
DeterministicScenarioRequest | DataInsufficientScenarioRequest) ->
DeterministicScenarioResult` is the single deterministic scenario valuation
interface (`src/equity_research/scenario_valuation/engine.py:35-175`). It:

- produces a typed conditional-only blocked result when official inputs are
  insufficient (`engine.py:45-97`);
- builds one coherent forecast graph per stress/base/improvement scenario and
  routes complete method families by company archetype
  (`engine.py:99-164`);
- permits evidence weighting only after probability gates and never creates a
  cross-method composite (`engine.py:165-175`,
  `src/equity_research/scenario_valuation/contracts.py:2913-2930`);
- carries method status, applicability, value basis, horizon, assumptions,
  formula version, conditional range, sensitivity, diagnostics and lineage
  (`contracts.py:2791-2870`).

**Caller/persistence/presentation impact.** `ImmutableArtifactDraft` converts
the typed result into the sole `ValuationArtifact@1`, validates all scenario
graphs against the Forecast structure, and records formula/source/dependency
identity (`src/trading_platform/domain/workflow.py:323-424`). Scenario methods
then feed the canonical view's permission-aware method presentation; formal
per-share output is withheld unless the frozen projection/source gates permit
it (`src/trading_platform/research_view.py:101-160`,
`src/trading_platform/research_view.py:479-588`).

**Real gaps.** The `contracts.py` implementation is 3,016 lines and the method
families are complex, but the public `run` interface is narrow and owns
substantial fail-closed domain behavior. None of the candidates supplies the
archetype router, equity bridge, method-level partial result, official-source
gate or compatible lineage. In particular, `a-stock-data.full_valuation`
consumes secondary quote/consensus values without the method router, official
source gate, source manifest, equity bridge or typed degradation
(`research/a-stock-data-upstream-audit.md:279-287`).

**Deletion test.** Deleting the engine would copy routing, scenario partition,
method applicability and weighting rules into callers and renderers. Keep it.
Delete/reject any adapted `full_valuation`, target-price calculation, prose
rating or external scenario output before it can become a formal artifact.
Do not add a second valuation artifact, renderer, schema or "external first,
local fallback" path.

### `ValuationSimulationEngine`

**Canonical implementation/interface.** `ValuationSimulationEngine.run(
ValuationSimulationRequest) -> ValuationSimulationResult` is the enterprise/
equity/basis-value uncertainty simulation. Its typed request binds valuation
source identity, calibrated distributions, dependency model, affine valuation
model, deterministic fallback, tail threshold and explicit budget
(`src/equity_research/simulation.py:420-516`). Its implementation fixes the RNG
identity, samples correlated inputs, gates convergence/tail sufficiency and
withholds stochastic quantiles on excessive invalid paths or non-convergence
(`simulation.py:547-672`).

**Caller/persistence/presentation impact.** The `Simulation` artifact must
match the parent Valuation subject/as-of/source identity and deterministic
fallback; its source identity hashes the complete simulation assumptions,
dependency/model/fallback and budget
(`src/trading_platform/domain/workflow.py:427-507`). The canonical view only
publishes per-share simulation when formal per-share permission passes and
retains seed, budget, dependency model, contributions and diagnostics
(`src/trading_platform/research_view.py:241-252`,
`src/trading_platform/research_view.py:589-653`).

**Real gap and semantic exclusion.** This is not a strategy-return Monte Carlo.
It has no trade signal, universe, walk-forward fold, order fill, turnover,
position path or portfolio return contract. That is an intentional domain
separation, not a missing feature to hide inside this engine.

**Deletion test.** Deleting it would duplicate calibrated distribution,
dependency, convergence, tail and deterministic-fallback policy in artifact
factories or presentation. Keep it. Vibe's strategy Monte Carlo must not
replace it, feed its `Simulation` artifact, reuse its schema, or appear as a
fallback. Any such mapping is `reject`.

### `MarketPathEngine` / `MarketPathSimulation`

**Canonical implementation/interface.** The concrete class is
`MarketPathEngine`, not a strategy/backtest interface. `run(MarketPathRequest)
-> MarketPathResult` performs a state-conditioned contiguous block bootstrap
over frozen market observations with a fixed RNG identity
(`src/equity_research/market_path.py:285-345`). Its own interpretation says it
models traded-price paths and is not intrinsic value, a target price, or a
trading instruction (`market_path.py:294-297`). Validation binds the parent
valuation simulation, PIT/as-of/timezone evidence, backward-adjusted returns,
calendar/series members, state model, T+1 execution lag, cost, price-limit/tick
policy and minimum sample/budget (`market_path.py:436-573`).

**Caller/persistence/presentation impact.** `MarketPathSimulationArtifact@1`
depends on both `Simulation` and `MarketDataSnapshot`, validates their typed
lineage and constructs a content-addressed source identity
(`src/trading_platform/domain/workflow.py:553-685`). The canonical view keeps
`valuation_simulation`, `market_price_paths`, and
`value_market_divergence` separate; it returns `not_comparable` instead of
manufacturing a valuation/market comparison when bases differ
(`src/trading_platform/research_view.py:253-260`,
`src/trading_platform/research_view.py:654-809`).

**Real gap and semantic exclusion.** It has no strategy rule, position sizing,
walk-forward train/test folds, universe PIT/survivorship model, order/fill
ledger or strategy P&L. A block bootstrap of traded-price observations is not a
backtest. Vibe's backtest/Walk-Forward/strategy Bootstrap must therefore become
a separate child artifact family only if later qualified; it cannot be renamed
to `MarketPathSimulation` or spliced into this payload.

**Deletion test.** Deleting the module would scatter PIT, adjustment,
calendar, T+1, cost, state-block and result-interpretation rules. Keep it.
Reject any Vibe adapter that replaces this module or writes its artifact kind.

### `ResearchWorkflow`, `WorkflowLedger`, and `ArtifactLineage`

**Canonical implementation/interface.** `ResearchWorkflow.handle` is the
application task interface. It owns lifecycle/lease/checkpoint/retry/
cancellation and typed failure mapping; `ResearchExecution` owns selected node
execution without changing lifecycle state
(`docs/architecture/target-architecture.md:42-44`). `ArtifactLineage.validate`
is a pure domain interface over `ArtifactSubmission` and frozen evidence. It
requires unique, topologically ordered typed artifacts, single subject/as-of/
snapshot identity, then constructs content-addressed envelopes and dependency
ids (`src/trading_platform/domain/artifact_lineage.py:131-284`).

`WorkflowLedger` is the SQLite/CAS adapter behind
`WorkflowLedgerPort`. It atomically previews/commits research artifacts,
manifests, workflow checkpoints and immutable dependencies. The persistence
schema stores model/source/code/policy identity and makes artifact records and
relations immutable
(`migrations/0012_research_artifact_bundle.sql:1-65`); workflow lifecycle and
manifests are in the canonical ledger schema
(`migrations/0003_workflow_research_manifest.sql:1-90`).

**Caller/persistence/presentation impact.** The workflow builds
`ResearchDecisionView@2` only after the typed artifact bundle is previewed and
commits source JSON/identity-only HTML, decision JSON/HTML, the bundle and
checkpoint in one ledger operation
(`src/trading_platform/workflows/research.py:770-868`). `ResearchArchive`
exposes manifests, typed artifacts, source payload and decision-view bytes via
named read tasks (`src/trading_platform/application/research_tasks.py:41-55`).

**Real gaps.**

1. `WorkflowLedgerPort` exposes many command/query overloads
   (`src/trading_platform/application/workflow_ledger.py:558-631`). It is a
   real persistence seam with a production SQLite adapter and test use, but its
   broad surface should not be mirrored in an external adapter or exposed to
   Vibe. A future strategy artifact must reuse the owning transaction/lineage
   mechanisms rather than create an MCP-specific database or generic artifact
   store.
2. `ImmutableArtifactDraft` is factory-only but collects many complete artifact
   factory behaviors in a 1,182-line module
   (`src/trading_platform/domain/workflow.py:206-720`). If implementation work
   touches it, split complete artifact-family invariant behavior, not helper
   forwarders; preserve one factory path and delete the moved implementation
   from this file in the same change.
3. Current workflow requests receive pre-built `analysis_artifacts`
   (`research.py:770-775`), so production generation of Forecast/Valuation/
   Simulation/MarketPath is not itself a new application task in this
   checkout. This does not authorize CLI/Web/Vibe direct construction or
   persistence. Any adopted external strategy capability needs an owning
   application task and atomic ledger path; it must not be appended as an
   untyped free-form report.
4. The one-way `ResearchDecisionView@2` cutover retains a one-implementation
   `ResearchDecisionViewMaterializerPort` and
   `CanonicalResearchDecisionViewMaterializer`
   (`src/trading_platform/application/workflow_ledger.py:253-265`,
   `src/trading_platform/application/research_view_cutover.py:21-84`), while
   every research start still checks a cutover-complete query
   (`src/trading_platform/workflows/research.py:512-521`). These are migration
   mechanics, not a second presentation path. After the minimum supported data
   version guarantees the cutover, the implementation ticket must decide
   whether to remove the callback port, materializer, repeated runtime gate,
   migration-only adapter code/tests/docs and operations calls atomically.
   They must not be reused as an external-result wrapper.

**Deletion test.** Deleting `ResearchWorkflow`, `ArtifactLineage`, or the
transactional ledger implementation would scatter lifecycle, idempotency,
lineage, CAS publication and recovery into CLI/Web/external adapters. Keep
them. Deleting the one-adapter cutover protocol after the migration floor is
locked would remove indirection rather than scatter production behavior, so it
is a concrete deletion candidate, conditional on migration evidence.

### `ResearchDecisionView@2` and JSON/HTML/Web/XLSX callers

**Canonical implementation/interface.** `ResearchDecisionView` is an exact
typed schema; `from_dict` rejects a schema other than
`ResearchDecisionView@2` and rejects missing/extra fields
(`src/trading_platform/research_view.py:19-64`).
`ResearchDecisionViewBuilder.build(ResearchDecisionInput)` validates the
DataSnapshot/Forecast/Valuation and optional Simulation/MarketDataSnapshot/
MarketPath artifact graph, applies formal-output permissions, derives the
decision-first model and binds `view_id` to all artifact content hashes
(`research_view.py:67-295`).

The four formal callers do not form four semantic paths:

- **JSON/HTML:** the workflow persists the exact view JSON and HTML together
  (`src/trading_platform/workflows/research.py:814-868`).
- **Web:** `DecisionWorkspace` loads only the persisted decision-view bytes,
  validates them with `ResearchDecisionView.from_dict`, then returns the same
  fields plus the persisted HTML projection
  (`src/trading_platform/persistence/workspace.py:123-148`). The JS renders
  typed story, drivers, scenarios, valuation simulation and market paths from
  `research_views`; tests cover this renderer
  (`web/src/app.js:1`, `web/tests/research-view.test.js:1-128`).
- **XLSX:** `ValuationWorkbookAdapter.export` accepts a typed
  `ResearchDecisionView`, serializes `view.to_dict()` to its isolated builder,
  and validates the produced workbook/preview
  (`src/trading_platform/valuation_workbook.py:27-148`;
  `tests/platform/test_valuation_workbook_adapter.py:31-147`).
- **Archive:** `ResearchArchive.decision_view` returns the persisted pair
  through the named application read task
  (`src/trading_platform/application/research_tasks.py:41-55`).

**Real gaps.** There is no field or child artifact for strategy validation,
fold identity, strategy return distribution, execution assumptions or
validation run card. Adding raw Vibe JSON/HTML/PDF to `ResearchDecisionView@2`
would create a parallel report and let an external schema define formal
presentation. If later strategy results belong in the decision workspace, the
typed artifact and view schema must migrate once, and JSON, HTML, Web and XLSX
must switch atomically.

**Deletion test.** Deleting `ResearchDecisionViewBuilder` would force JSON,
HTML, Web and XLSX to re-interpret source artifacts and duplicate output-policy
gates. Keep it. Delete/reject every upstream report renderer, copied HTML/PDF
template, raw-result viewer, external narrative field and renderer-specific
recomputation proposed for production. Do not create a parallel strategy
report.

## Candidate replacement/deletion matrix

| Capability | Current canonical implementation | External candidate | Candidate decision | Adoption condition | Delete if condition passes | Explicit rejection / protected objects |
|---|---|---|---|---|---|---|
| Research structure, diligence checklist, counter-evidence comparison | `ResearchWorkflow` + deterministic `ResearchEngine` + typed artifacts/view | Public Equity Investing | `keep-local` | If ticket 03 gains access, compare only against the same frozen non-personal source manifest and pass repository output/privacy gates | Nothing in production; discard comparison outputs after evidence capture unless stored as non-authoritative research evidence | It is `external_blocked`, unpinned and closed; never delete/replace ResearchEngine, Forecast, valuation, ledger, or view; no plugin report in runtime |
| A-share endpoint protocol/parser knowledge feeding research facts | Canonical DataProvider/DataSync path upstream of the frozen `DataSnapshot`; research/artifact stack consumes only typed frozen evidence | `a-stock-data` | `adapt-code` | Ticket 04 must qualify one endpoint at a time for rights, authority, PIT/published/available/retrieved time, typed empty/failure semantics and deterministic fixtures | For each admitted endpoint, atomically delete the exact superseded local provider protocol/parser, tests/docs/config; no artifact module deletion | Direct Skill execution and orchestration rejected; delete/reject `full_valuation`, report download path, empty-on-error and fallback; Forecast/valuation/artifacts are protected |
| `a-stock-data.full_valuation` and report/target workflow | `ScenarioValuationEngine` + repository source/method/equity-bridge gates + `ResearchDecisionView@2` | `a-stock-data` | `reject` | None under current evidence | No production object | Secondary quote/consensus calculation bypasses official-source, method-router, equity-bridge and degradation rules |
| US/HK endpoint protocol/parser knowledge feeding research facts | Canonical DataProvider/DataSync path upstream of frozen artifacts | `global-stock-data` | `adapt-code` | Ticket 05 must independently qualify SEC/HKEX/IR or individual secondary endpoints, including terms, UA/rate policy, field/schema/time/failure semantics and official cross-check | Delete the exact superseded provider protocol/parser and its fixtures/docs in the same admitted slice; no artifact module deletion | Direct Skill execution rejected; unqualified Yahoo/Eastmoney/Sina/Tencent and analyst ratings/targets cannot enter formal artifacts |
| Hosted/Skill/Vibe enterprise Forecast generation | `ForecastEngine.build` + `ForecastGraphIdentity@2` | All four candidates | `keep-local` | External material may only become qualified input evidence/assumptions through current typed gates | No Forecast implementation deletion | No candidate has equivalent PIT graph identity, replay, archetype routing and degradation; no wrapper/fallback/parallel graph |
| Deterministic multi-method scenario valuation | `ScenarioValuationEngine.run` | Public Equity Investing, `global-stock-data`, Vibe | `keep-local` | External output may be a comparison only, never authoritative | No valuation implementation/schema deletion | Hosted target/rating language, quote multiples and strategy P&L do not satisfy method/source/equity-bridge gates |
| Enterprise/valuation uncertainty Monte Carlo | `ValuationSimulationEngine.run` -> `Simulation` | Vibe-Trading | `keep-local` | No strategy Monte Carlo may enter this artifact kind | No valuation simulation deletion | Strategy-return Monte Carlo has a different random variable, identity, calibration and consumer |
| State-conditioned traded-price path simulation | `MarketPathEngine.run` -> `MarketPathSimulation` | Vibe-Trading | `keep-local` | Vibe may only be evaluated as strategy validation, not market-path replacement | No MarketPath implementation/schema deletion | A backtest/Walk-Forward result is not a market-price path; preserve `not_comparable` and interpretation boundary |
| Backtest, Walk-Forward, strategy Bootstrap/Monte Carlo and run card | No production strategy/backtest module; `full_trade_backtest` is explicitly `not_applicable` in current release evidence (`src/trading_platform/acceptance.py:70,496-503`) | Vibe-Trading pinned `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` | `adopt-external` | Ticket 06 must prove the pinned isolated stdio MCP subset with known answers, PIT/universe/fold/execution rules, reproducibility/convergence, timeout/crash/malformed/tamper failures, and no LLM/key/network/repo/personal-data access | No old strategy implementation exists. If admitted, atomically replace the stale `not_applicable` acceptance assertion and affected tests/docs with typed evidence; discard upstream raw report paths | Whole app, Web, persistence, loaders, live/broker/order, arbitrary file/web/search, memory/swarm/scheduler/shell/external MCP are rejected; it must not delete or replace Forecast, valuation simulations, MarketPath, ledger or canonical view |
| Workflow lifecycle, artifact identity, transactions and recovery | `ResearchWorkflow` + `ArtifactLineage` + SQLite/CAS `WorkflowLedger` | All four candidates | `keep-local` | External behavior must enter only through an owning named application task and typed artifact; no candidate controls persistence | Only migration mechanics proven obsolete by a supported-version floor may be deleted | Never adopt upstream workflow/persistence/Web or let Skill/MCP write artifacts directly; no second database, report store, dual-write/read or fallback |
| Formal JSON/HTML/Web/XLSX presentation | `ResearchDecisionView@2` is the sole presentation model | All four candidates | `keep-local` | Any admitted strategy result requires one typed schema migration and atomic caller cutover | Delete superseded schema fields/rendering branches/generated assets in that same migration; delete all upstream raw renderers from production scope | No upstream report, target/rating prose, raw JSON, HTML or PDF becomes canonical; no parallel strategy report |

## Atomic migration and deletion gates for later tickets

1. **No external capability is adopted by adding a caller.** A production
   decision changes only when the same ticket migrates the owning application
   task, typed contracts, artifact lineage, persistence/schema, JSON/HTML/Web/
   XLSX callers, tests/docs/generated assets, and deletes the superseded path.
2. **Data adaptations stop at the DataProvider seam.** They may change the
   frozen evidence entering Forecast, but cannot add a Skill or endpoint call
   in Forecast, valuation, ResearchWorkflow, renderers or Web.
3. **Strategy results are a new semantic child, not a rename.** They cannot
   reuse `Simulation`, `MarketPathSimulation`, their source identities, or
   their presentation fields. The later interface ticket must lock this
   without creating a generic external-tool facade.
4. **The ledger remains the single persistence path.** An isolated Vibe
   artifact directory is transport quarantine only, not a second business
   artifact store. Accepted bytes must be validated, transformed into a typed
   repository-owned result, and committed once through the canonical ledger.
5. **No upstream renderer survives production adoption.** Formal output remains
   `ResearchDecisionView@2` or its one-way successor. There is no external HTML/
   PDF report tab, raw MCP result viewer, or renderer fallback.
6. **Delete migration-only indirection when safe.** Before adding another
   artifact family, determine from the minimum supported schema/data version
   whether `ResearchDecisionViewMaterializerPort`,
   `CanonicalResearchDecisionViewMaterializer`, the repeated cutover gate, and
   their operations/tests/docs can be removed. Do not generalize them into a
   strategy wrapper.

## Candidate conclusions for the total ticket-02 matrix

- Correct any matrix that labels Public Equity Investing `adapt-code` or
  `adopt-external`: its only safe current role is `keep-local` comparison in
  the Codex control plane, and it is presently `external_blocked`.
- Split the two Skill repositories by behavior. Endpoint protocol/parser
  knowledge is conditionally `adapt-code`; their free-form execution,
  orchestration, valuation, recommendation, fallback and report behavior is
  `reject`. A single repository-wide decision would hide this essential
  deletion boundary.
- Preserve four separate meanings: Forecast graph, deterministic scenario
  valuation, valuation/enterprise-value Monte Carlo, and market-price paths.
  Vibe strategy simulation is a fifth meaning. Mapping any two to the same
  artifact kind or renderer is a semantic defect even if their JSON shapes
  look similar.
- The only current production capability gap in this audited slice is strategy
  validation. Vibe is an `adopt-external` candidate for that gap only; there is
  no local strategy implementation to wrap or retain as fallback.
- The artifact and presentation impact of adopting Vibe is not “add a report.”
  It requires typed identity/lineage, an atomic ledger write, a one-way view
  schema/caller migration if presentation is in scope, and deletion of every
  raw upstream report path.
