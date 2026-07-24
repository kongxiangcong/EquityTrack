# Current canonical seams for external equity capability adoption

## Scope and evidence rule

This is a read-only source audit for the adoption Wayfinder. It describes the
current checkout, not the target state, and makes no adoption decision. Evidence
is limited to the repository's production code, migrations, tests, and
authoritative architecture documentation. No child ticket has been claimed or
resolved.

## Executive finding

The current application boundary is a set of named, statically composed tasks,
not an `ApplicationFacade`, task bag, service locator, or string-selected plugin
surface. The production composition root constructs one task for each CLI/Web
operation (`DataSynchronization`, `ResearchWorkflow`, `WorkflowInspection`,
`ResearchArchive`, `DecisionWorkspace`, etc.) and owns its lifetime
([`docs/architecture/target-architecture.md:3`](../../../docs/architecture/target-architecture.md),
[`src/trading_platform/application/bootstrap.py:122`](../../../src/trading_platform/application/bootstrap.py)).
External capabilities therefore need to enter behind one of these named task
interfaces and their domain ports; adding a second facade or allowing CLI/Web to
invoke upstream code directly would be a parallel path.

## Existing seams and their usable depth

### 1. Application and research lifecycle

- Formal research enters through
  `ResearchWorkflow.handle(StartResearchWorkflow(request))`. `ResearchWorkflow`
  owns start/replay, lease, checkpoint, retry, cancellation, transitions, frozen
  projection/snapshot selection, artifact validation, and publication
  ([`src/trading_platform/workflows/research.py:496`](../../../src/trading_platform/workflows/research.py),
  [`src/trading_platform/application/contracts.py:84`](../../../src/trading_platform/application/contracts.py)).
  The public-seam test asserts the workflow exposes this single task operation
  and exercises replay, frozen PIT inputs, degradation, and redacted failure
  evidence
  ([`tests/platform/test_research_workflow.py:27`](../../../tests/platform/test_research_workflow.py),
  [`tests/platform/test_research_workflow.py:167`](../../../tests/platform/test_research_workflow.py)).
- Production wiring is static in `application/bootstrap.py`: data sync,
  provider qualification, daily research, and standalone research each receive
  explicit dependencies; callers are not given the persistence store
  ([`src/trading_platform/application/bootstrap.py:122`](../../../src/trading_platform/application/bootstrap.py),
  [`src/trading_platform/application/bootstrap.py:169`](../../../src/trading_platform/application/bootstrap.py),
  [`src/trading_platform/application/bootstrap.py:206`](../../../src/trading_platform/application/bootstrap.py)).
- `ResearchWorkflowRequest` freezes identity/date inputs, a typed
  `ResearchProjection`, optional workflow/member identities, and a tuple of
  `ImmutableArtifactDraft` analysis artifacts
  ([`src/trading_platform/domain/workflow.py:1114`](../../../src/trading_platform/domain/workflow.py)).
  This is the closest current seam to a future typed `ResearchEvaluationPlan`,
  but no such plan contract currently exists.

**Adoption implication:** control-plane research helpers may prepare typed input,
but production execution and publication must continue through named application
tasks. A new complete user task should become a named task only if it owns real
policy/orchestration; it should not mirror an upstream API.

### 2. DataProvider, synchronization, PIT, and snapshots

- `DataProvider` is a small protocol:
  identity/version/fixture/endpoint plus
  `fetch(FetchRequest) -> FetchBatch`. `FetchRequest` carries canonical
  parameters, security/market/range/cursor identity, credential scope, and an
  explicit network authorization flag. Each `RawEnvelope` retains real source
  URL, authority, terms profile, redacted parameters, retrieval time, status,
  payload hash/cursor, and typed error
  ([`src/trading_platform/domain/data.py:74`](../../../src/trading_platform/domain/data.py),
  [`src/trading_platform/domain/data.py:92`](../../../src/trading_platform/domain/data.py),
  [`src/trading_platform/domain/data.py:113`](../../../src/trading_platform/domain/data.py)).
- Current production adapters are `HttpJsonProvider` and its
  `TushareCompatibleProvider` specialization; deterministic fixtures implement
  the same port. Unauthorized network access returns typed failure without
  calling transport
  ([`src/trading_platform/data/providers.py:20`](../../../src/trading_platform/data/providers.py),
  [`src/trading_platform/data/providers.py:51`](../../../src/trading_platform/data/providers.py),
  [`src/trading_platform/data/providers.py:90`](../../../src/trading_platform/data/providers.py),
  [`tests/platform/test_data_sync_pit.py:92`](../../../tests/platform/test_data_sync_pit.py)).
- `DataSyncService.sync` owns provider attempts, raw preservation, fixture-rights
  enforcement, normalization, quality/quarantine decisions, safe cursor advance,
  and immutable snapshot construction
  ([`src/trading_platform/data/service.py:16`](../../../src/trading_platform/data/service.py)).
  The schema persists provider attempts/cursors, normalized records and versions,
  quality issues, snapshots, and snapshot members
  ([`migrations/0002_provider_normalized_snapshot.sql:1`](../../../migrations/0002_provider_normalized_snapshot.sql)).
  Tests prove PIT exclusion, stable replay identity, immutable cursor behavior,
  offline degradation, redistribution qualification, rate-limit/schema-drift
  failure, and ordered fallback attempt evidence
  ([`tests/platform/test_data_sync_pit.py:58`](../../../tests/platform/test_data_sync_pit.py),
  [`tests/platform/test_data_sync_pit.py:231`](../../../tests/platform/test_data_sync_pit.py)).

**Obvious gaps before external data adoption:**

1. `DataSyncService` constructs Tushare-shaped parameters itself and uses the
   provider tuple as an implicit ordered fallback
   ([`src/trading_platform/data/service.py:27`](../../../src/trading_platform/data/service.py)).
   A-stock/global endpoint protocol translation and a versioned source policy
   need a deeper ownership boundary; callers must not select arbitrary adapters,
   and an external failure must not silently enter an undeclared source.
2. The normalizer currently has explicit production shapes for `daily`,
   `trade_cal`, `market_universe`, and `forecast_actual`; unknown datasets fail
   with `DATASET_UNSUPPORTED`
   ([`src/trading_platform/data/normalizer.py:44`](../../../src/trading_platform/data/normalizer.py)).
   Qualified official disclosure, corporate action, adjustment factor, HK/US
   identity, or auxiliary endpoint semantics are not obtained merely by adding
   another HTTP provider.
3. `HttpJsonProvider` implements one Tushare-style POST body and collapses
   non-429 HTTP errors to `PROVIDER_HTTP_FAILED`
   ([`src/trading_platform/data/providers.py:71`](../../../src/trading_platform/data/providers.py)).
   Candidate-specific auth, pagination, empty/partial semantics, field drift,
   timestamps, and endpoint rights require real protocol adapters, not
   configuration aliases.

### 3. Forecast and scenario valuation

- `ResearchEngine.run(ResearchRequest) -> ResearchRun` is the deterministic
  research module behind the workflow. It validates typed forecast identity
  against the source manifest and builds a forecast through `ForecastEngine`
  ([`src/equity_research/engine.py:155`](../../../src/equity_research/engine.py)).
- Forecast is a typed graph, not narrative JSON:
  `ForecastGraphIdentity@2`, typed nodes/edges/quantities, deterministic replay,
  source lineage, monitoring conditions, and graph invariants live in
  `equity_research.forecast`
  ([`src/equity_research/forecast/graph.py:391`](../../../src/equity_research/forecast/graph.py),
  [`src/equity_research/forecast/graph.py:611`](../../../src/equity_research/forecast/graph.py)).
- `ScenarioValuationEngine.run` requires the stress/base/improvement partition,
  rebuilds each scenario from driver overrides, routes by company archetype, and
  evaluates the applicable industrial, cyclical, financial-institution, or
  biopharma family. Missing inputs produce a typed conditional-only blocked
  result rather than a fabricated valuation
  ([`src/equity_research/scenario_valuation/engine.py:35`](../../../src/equity_research/scenario_valuation/engine.py),
  [`src/equity_research/scenario_valuation/engine.py:40`](../../../src/equity_research/scenario_valuation/engine.py),
  [`src/equity_research/scenario_valuation/engine.py:89`](../../../src/equity_research/scenario_valuation/engine.py)).

**Adoption implication:** Public Equity Investing can be compared as a
control-plane research structure, but it cannot replace these typed identity,
source, method-routing, formula, and fail-closed seams. Any candidate story or
question must be converted into evidence-bound typed inputs before formal use.

### 4. Valuation simulation and market-path simulation

- `ValuationSimulationRequest`, `ValuationSimulationResult`, and
  `ValuationSimulationEngine` already form a separate deterministic domain seam
  ([`src/equity_research/simulation.py:442`](../../../src/equity_research/simulation.py),
  [`src/equity_research/simulation.py:458`](../../../src/equity_research/simulation.py),
  [`src/equity_research/simulation.py:547`](../../../src/equity_research/simulation.py)).
  Tests cover known quantiles and byte reproducibility, calibrated correlation,
  invalid dependency structures, heavy-tail sample sufficiency, rejection of an
  unqualified normal default, invalid operating paths, PIT/calibration gates,
  convergence, unit identity, and empirical support
  ([`tests/test_valuation_simulation.py:216`](../../../tests/test_valuation_simulation.py),
  [`tests/test_valuation_simulation.py:238`](../../../tests/test_valuation_simulation.py),
  [`tests/test_valuation_simulation.py:330`](../../../tests/test_valuation_simulation.py),
  [`tests/test_valuation_simulation.py:515`](../../../tests/test_valuation_simulation.py)).
- `MarketPathSimulation` is a distinct artifact child of valuation simulation and
  a frozen market-data snapshot, with separate lineage and presentation fields.
  Formal persistence rejects self-declared calendars, future availability,
  unbound starting price/state, and unsafe copied identities
  ([`src/trading_platform/domain/workflow.py:996`](../../../src/trading_platform/domain/workflow.py),
  [`tests/platform/test_market_path_simulation_artifact.py:397`](../../../tests/platform/test_market_path_simulation_artifact.py),
  [`tests/platform/test_market_path_simulation_artifact.py:491`](../../../tests/platform/test_market_path_simulation_artifact.py),
  [`tests/platform/test_market_path_simulation_artifact.py:883`](../../../tests/platform/test_market_path_simulation_artifact.py)).

**Adoption implication:** Vibe-Trading return/bootstrap Monte Carlo cannot be
stored as `Simulation` or treated as enterprise/equity value uncertainty. A
future strategy-validation result needs a new artifact kind and lineage contract
with an explicit boundary from both valuation simulation and market-price paths.

### 5. ResearchDecisionView and presentation

- `ResearchDecisionView` is the typed `ResearchDecisionView@2` formal
  presentation model. It binds workflow/research/snapshot/model/policy and
  valuation/simulation/market-path artifact identities, then exposes story,
  drivers, scenarios, optional distributions, divergence, audit, and the
  financial-output boundary
  ([`src/trading_platform/research_view.py:20`](../../../src/trading_platform/research_view.py)).
- `ResearchDecisionViewBuilder.build(ResearchDecisionInput)` validates the
  artifact graph before projection
  ([`src/trading_platform/research_view.py:68`](../../../src/trading_platform/research_view.py),
  [`src/trading_platform/research_view.py:81`](../../../src/trading_platform/research_view.py)).
  Tests prove workspace projection comes from typed artifacts rather than HTML,
  and formal JSON/HTML serialize the exact same view
  ([`tests/platform/test_decision_research_view.py:356`](../../../tests/platform/test_decision_research_view.py),
  [`tests/platform/test_decision_research_view.py:424`](../../../tests/platform/test_decision_research_view.py)).

**Obvious gap:** `ResearchDecisionView@2` has no strategy-validation section or
typed reference. If strategy evidence becomes decision-relevant, the canonical
view must be versioned and all JSON/HTML/Web/XLSX callers migrated atomically;
embedding Vibe HTML/PDF would create a second presentation model.

### 6. WorkflowLedger and immutable artifact graph

- `WorkflowLedgerPort` is the application-owned persistence port for lifecycle,
  transitions, checkpoints, immutable artifact commits, finalization, typed
  queries, and scoped integrity audit
  ([`src/trading_platform/application/workflow_ledger.py:558`](../../../src/trading_platform/application/workflow_ledger.py)).
  `persistence.WorkflowLedger` is its single SQLite owner
  ([`src/trading_platform/persistence/workflow_ledger.py:182`](../../../src/trading_platform/persistence/workflow_ledger.py)).
- The schema records immutable research artifacts with snapshot, subject,
  source, model/formula/code/policy identities and explicit parent-child
  dependencies; artifact rows and relations are protected by immutability
  triggers
  ([`migrations/0012_research_artifact_bundle.sql:1`](../../../migrations/0012_research_artifact_bundle.sql)).
  `ArtifactLineage.validate` checks typed kinds, dependency ordering, frozen
  subject/snapshot identity, as-of, content hashes, and parent relations before
  persistence
  ([`src/trading_platform/domain/artifact_lineage.py:113`](../../../src/trading_platform/domain/artifact_lineage.py)).
  Tests enforce one public persistence owner, atomic validation/replay, corruption
  failure, and immutable rows
  ([`tests/platform/test_workflow_ledger.py:219`](../../../tests/platform/test_workflow_ledger.py),
  [`tests/platform/test_workflow_ledger.py:290`](../../../tests/platform/test_workflow_ledger.py),
  [`tests/platform/test_workflow_ledger.py:388`](../../../tests/platform/test_workflow_ledger.py)).

**Obvious gap:** the current artifact dependency vocabulary ends at
`ForecastReview`; there is no `StrategyValidation` kind, external-engine
identity, code/config hash, fold/run identity, convergence diagnostics, or
strategy artifact relation in the typed graph
([`src/trading_platform/domain/workflow.py:996`](../../../src/trading_platform/domain/workflow.py)).
The ledger should only be extended after the domain result contract is proven;
raw upstream JSON/HTML/PDF is not an authoritative ledger result.

### 7. Strategy/backtest baseline

An exhaustive symbol/schema scan of `src/`, `tests/`, and `migrations/` found no
`StrategyValidation`, `StrategyValidationRequest`,
`StrategyValidationResult`, `strategy` table, or `backtest_run` table. The
current acceptance contract explicitly marks `full_trade_backtest` as
`not_applicable` because there is no execution, fee, slippage, or T+1 simulator
([`src/trading_platform/acceptance.py:70`](../../../src/trading_platform/acceptance.py),
[`src/trading_platform/acceptance.py:496`](../../../src/trading_platform/acceptance.py)).

This is a genuine missing deep module, not a seam to wrap. Before any production
port is introduced, the adoption work must prove a real external adapter and a
deterministic fixture/in-memory adapter, then define typed request/result,
frozen-data identity, PIT/universe/execution rules, failure semantics, artifact
hashes, and ledger/presentation migration.

## Structural pressure points for later tickets

These are responsibility-audit triggers, not instructions to split files by
line count:

| File | Current size | Concentrated responsibilities relevant to adoption |
|---|---:|---|
| `src/trading_platform/persistence/workflow_ledger.py` | 2,468 lines | workflow lifecycle persistence, artifact commit/validation preparation, forecast review, decision-view cutover, projection and recovery queries |
| `src/equity_research/scenario_valuation/contracts.py` | 3,016 lines | contracts and invariants for several valuation families |
| `src/equity_research/simulation.py` | 1,483 lines | simulation contracts, validation, RNG/sampling, convergence and attribution |
| `src/trading_platform/research_view.py` | 1,140 lines | canonical view contract, artifact validation, semantic projection and presentation permissions |
| `src/trading_platform/domain/workflow.py` | 1,182 lines | workflow, artifact, projection, persistence-view and history contracts |
| `src/trading_platform/workflows/research.py` | 929 lines | lifecycle orchestration plus research/artifact/source/calibration gates |

Any adoption ticket that adds a new responsibility to one of these files must
first identify a cohesive behavior boundary and move that behavior completely.
Forwarders, `helpers/common/utils`, a mirrored facade, or a provider/model string
dispatcher would not deepen the architecture.

## Replacement-matrix inputs for the Wayfinder

| Capability | Current canonical implementation | Immediate gap to investigate |
|---|---|---|
| Application entry | statically composed named tasks in `application/bootstrap.py` | typed `ResearchEvaluationPlan`; possible complete `StrategyValidation` task |
| Structured market data | `DataProvider` -> `DataSyncService` -> `DataRepository`/immutable snapshots | provider-specific protocol translation and versioned source policy beyond Tushare-shaped requests |
| Company forecast | `ForecastEngine` / `ForecastGraphIdentity@2` | external research structure may supply candidate inputs only |
| Scenario valuation | `ScenarioValuationEngine` and archetype-specific families | no external candidate should bypass method/source/equity-bridge gates |
| Valuation uncertainty | `ValuationSimulationEngine` | must remain semantically separate from strategy return simulation |
| Traded-price paths | `MarketPathSimulation` artifact | not a backtest and not strategy validation |
| Formal presentation | persisted `ResearchDecisionView@2` -> canonical JSON/HTML/Web/XLSX | no strategy-validation projection yet |
| Workflow/artifacts | `WorkflowLedgerPort` + SQLite `WorkflowLedger` + `ArtifactLineage` | no strategy result kind or external-engine identity |
| Strategy validation/backtest | none; acceptance says `not_applicable` | full deep module, adapters, schema, ledger lineage and adversarial acceptance are absent |
