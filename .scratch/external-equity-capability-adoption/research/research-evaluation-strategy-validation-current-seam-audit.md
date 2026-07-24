# ResearchEvaluation / StrategyValidation current-seam audit

## Audit envelope

- Scope: current production code, schema, tests, and resolved adoption tickets 02–06 in `E:\workspace\tradingSystem`.
- Method: local primary-source inspection only. No network calls, external execution, dependency installation, or production modification.
- Design test: the `codebase-design` deletion test and “two real adapters before a port” rule.
- This document records current facts and design constraints for ticket 07. It does not claim that a new production interface, schema, route, or migration already exists.

## Executive finding

The current checkout already has deep canonical modules for research execution/admission, data acquisition, immutable artifact lineage, workflow persistence, and presentation. Ticket 07 must deepen those seams; it must not introduce an upstream-shaped facade.

The important negative result is:

> After ticket 06 rejected Vibe-Trading and fixed the production MCP allowlist at `[]`, a new `StrategyValidation` **port has zero real production adapters**. A deterministic fake would be only one test adapter, not a second real variation. Creating `StrategyValidationPort` or `VibeTradingMcpAdapter` now would be hypothetical indirection and is forbidden by the two-adapter rule.

If strategy validation remains a product requirement, the only evidence-supported shape today is a target-owned, in-process deep module with a typed `StrategyValidationRequest -> StrategyValidationResult` interface and no external port. It should be introduced only with the actual deterministic implementation, named application task, lineage persistence, callers, and tests—not as a placeholder. Any future external engine would require a new qualification decision and a real second adapter before a port becomes justified.

`ResearchEvaluationPlan` likewise does not need a port. It is a typed policy/value contract that should compose with the existing `ResearchWorkflow` and its admission behavior. Public Equity Investing is unavailable and production-rejected, so there is no external research-evaluation adapter to abstract.

## Adoption decisions that constrain the seam

1. Ticket 02 keeps the named application tasks, `DataProvider -> DataSyncService -> DataRepository`, Forecast, Scenario Valuation, both existing simulations, `ResearchWorkflow`, `WorkflowLedger`/`ArtifactLineage`, and `ResearchDecisionView@2` as canonical owners (`.scratch/external-equity-capability-adoption/issues/02-map-capabilities-to-replacement-and-deletion.md:23-31`). It explicitly rejects a Skill runner, generic external provider, MCP-tool-mirror facade, fallback/dual paths, raw-report viewer, and second Web (`.../02-map-capabilities-to-replacement-and-deletion.md:33`).
2. Ticket 03 has zero Public Equity Investing executions. It rejects that plugin as runtime/data/valuation/persistence/presentation and keeps current Codex research execution local; there is no behavior evidence for an external adapter (`.../03-evaluate-public-equity-investing.md:30-48`).
3. Ticket 04 rejects all executable `a-stock-data` implementations and market-data endpoints. Only three official A-share disclosure/regulatory protocol families remain possible `adapt-code` inputs, to be reimplemented inside the existing OfficialDisclosure/DataProvider path after a full admission suite; it forbids a placeholder derived adapter (`.../04-qualify-a-stock-data-endpoints.md:15-27`, `.../04-qualify-a-stock-data-endpoints.md:46`).
4. Ticket 05 rejects the whole `global-stock-data` runtime and all existing parsers. Only SEC official protocol knowledge remains an `adapt-code` candidate; no current SEC/HKEX production adapter exists (`.../05-qualify-global-stock-data-endpoints.md:23-38`).
5. Ticket 06 rejects the entire Vibe MCP, `backtest(run_dir)`, alleged Walk-Forward, IID bootstrap, P&L-order Monte Carlo, and report path; production allowlist is `[]`. It explicitly says the surviving algorithm ideas do not authorize a `StrategyValidation` port (`.../06-validate-vibe-trading-credibility.md:18-28`).

These later tickets supersede ticket 02's conditional optimism about Vibe. The current design cannot name a Vibe production adapter, generic external research adapter, a-stock market adapter, or global-stock parser adapter.

## 1. Canonical application seam and concrete callers

### Current interface

Formal research enters through one typed command:

```text
ResearchWorkflow.handle(
    StartResearchWorkflow(ResearchWorkflowRequest)
) -> ResearchWorkflowResult
```

`StartResearchWorkflow`, resume, and cancel form the command union (`src/trading_platform/application/contracts.py:70-95`). `ResearchWorkflow.handle` validates the command type, enforces the completed presentation cutover, and owns start/resume/cancel routing (`src/trading_platform/workflows/research.py:496-533`). Start fingerprints and persists the exact request as `ResearchWorkflowRequest@1`, handles idempotent replay, and enters the versioned workflow (`src/trading_platform/workflows/research.py:535-567`).

The production composition root statically constructs `ResearchWorkflow` with `WorkflowLedgerPort`, local `ResearchEngine`, `SnapshotToResearchRequestAssembler`, and repository root; it does not use a runtime registry or service locator (`src/trading_platform/application/bootstrap.py:169-221`).

### Concrete production callers

- CLI `research` decodes a typed request and invokes `handle(StartResearchWorkflow(request))`; CLI `resume` uses the same workflow task (`src/trading_platform/cli.py:184-187`, `src/trading_platform/cli.py:411-421`).
- `DailyResearchCycle` runs data sync, decodes an optional research request from the configured job, invokes the same workflow, and rejects a wrong result type (`src/trading_platform/application/cli_tasks.py:101-138`).
- Browser acceptance prepares a typed `ResearchWorkflowRequest` and crosses the same workflow seam before creating downstream plan evidence (`src/trading_platform/application/browser_acceptance.py:76-129`).
- Production archive/inspection callers use named `ResearchArchive` and `WorkflowInspection` tasks, which load typed ledger queries; they do not receive raw database access (`src/trading_platform/application/research_tasks.py:27-55`).
- The public-seam test asserts that workflow and execution each expose one task operation, and verifies replay, canonical artifacts, decision view, node history, and snapshot quality (`tests/platform/test_research_workflow.py:27-35`, `tests/platform/test_research_workflow.py:167-207`).

### Deletion test

Deleting `ResearchWorkflow` would force CLI, daily cycle, browser fixtures, recovery, cancellation, replay, lease, PIT, admission, artifact commit, and publication policy back into callers. It is deep and earns its interface.

A new `ResearchEvaluationFacade` that merely accepts a plan, builds `ResearchWorkflowRequest`, and forwards to `ResearchWorkflow.handle` would fail the deletion test: deleting it would remove only field repackaging. A second facade must not be created.

## 2. Where a typed ResearchEvaluationPlan can fit

### Current typed input and output

`ResearchWorkflowRequest` already freezes invocation/security/date identity, a typed `ResearchProjection`, optional workflow snapshot/member classifications, and immutable analysis drafts (`src/trading_platform/domain/workflow.py:1099-1124`). `ResearchProjection` carries the manifest, estimates, research inputs, cutoff/profile, field semantics, diluted-share/net-debt identities, and a hash-bound source-manifest validation result (`src/trading_platform/domain/workflow.py:1099-1110`).

`SnapshotToResearchRequestAssembler` is the current input-admission module. It:

- validates the source-manifest validator version/authority/status and binds its content hash;
- rejects missing sources, PIT-illegal availability, missing or mismatched field semantics;
- enforces diluted-share and net-debt identities or declared gaps;
- creates a deterministic fingerprint including policy version and all frozen semantics
  (`src/trading_platform/research/assembler.py:26-56`, `src/trading_platform/research/assembler.py:58-166`).

`ResearchEngine.run(ResearchRequest)` is the deterministic assessment module. It validates forecast/source identity, evaluates capabilities, blocks all methods on manifest integrity errors, routes applicable methods otherwise, derives typed permissions/status, and produces `ResearchRun` (`src/equity_research/engine.py:151-217`, `src/equity_research/engine.py:260-316`). `ResearchRun` already exposes integrity issues, capability/method status, permissions, analysis completeness, debate/synthesis, report mode, conditional plan, and diagnostics (`src/equity_research/models.py:338-359`).

The workflow adds publication admission:

- frozen projection identity, purpose, PIT, freshness, quality, and member classification (`src/trading_platform/workflows/research.py:205-300`);
- trusted source-manifest validation before typed valuation publication (`src/trading_platform/workflows/research.py:323-380`);
- simulation calibration and per-share gates (`src/trading_platform/workflows/research.py:382-493`);
- typed artifact lineage and canonical decision-view construction before the atomic checkpoint (`src/trading_platform/workflows/research.py:804-869`).

### Seam conclusion

`ResearchEvaluationPlan` should be a typed, versioned in-process contract consumed by the existing research workflow/engine admission path. It may own genuinely new policy such as:

- required research dimensions/capabilities for a declared evaluation purpose;
- evidence and disconfirming-evidence admission criteria;
- allowed degraded outcomes and publication permissions;
- policy identity that participates in request/artifact fingerprints.

It must **not**:

- copy `profile`, manifest status, capabilities, permissions, and artifact fields into a second mirror object;
- evaluate source/PIT/per-share/valuation gates again;
- carry plugin names, prompt strings, class names, tool names, or callable import paths;
- select an evaluator through strings or a service locator;
- add a `ResearchEvaluationPort` while Public Equity Investing has no available runtime adapter.

Deletion test: a valid plan module earns its place only if deleting it would spread purpose-specific admission policy across `ResearchEngine`, `ResearchWorkflow`, CLI/daily callers, and tests. If deletion merely removes a conversion into `ResearchWorkflowRequest`, the plan module is shallow.

## 3. StrategyValidation: current absence and correct no-port decision

An exact scan of current `src/`, `tests/`, and `migrations/` found no `StrategyValidation`, `StrategyValidationRequest`, `StrategyValidationResult`, strategy table, or backtest-run table. Acceptance explicitly marks `full_trade_backtest` as `not_applicable` because execution, fees, slippage, and T+1 simulation are absent (`src/trading_platform/acceptance.py:483-505`).

Ticket 06 removes the only proposed production variation: Vibe's production allowlist is empty and no adapter/proxy/placeholder is allowed (`.scratch/external-equity-capability-adoption/issues/06-validate-vibe-trading-credibility.md:18-28`). The remaining Vibe ideas—one-bar lag/next-open, PIT masking, A-share rules skeleton, and hash inventory—are algorithm inputs for locally owned implementation, not adapters.

### Adapter count

| Candidate | Production adapter | Deterministic test adapter | Real port? |
|---|---|---|---|
| Vibe MCP | rejected; forbidden | qualification harness only, scheduled for deletion | no |
| Existing local strategy engine | does not exist | does not exist | no |
| Future target-owned deterministic engine | would be the implementation itself, not an adapter | direct known-answer tests/fixtures | no external port needed |

**Conclusion: do not define `StrategyValidationPort` in ticket 07.** A fake paired with no production adapter does not satisfy the two-adapter rule. A local deterministic engine is an in-process dependency and should be tested directly through its typed interface.

### Conditions for a future local module

If later tickets implement the capability, a complete deep interface can still be named now as a design target:

```text
StrategyValidationEngine.run(
    StrategyValidationRequest
) -> StrategyValidationResult
```

The request must bind a frozen platform market-data snapshot/universe identity, declarative strategy identity/config hash, dated execution-rule policy, fees/slippage, fold design, statistical method identity, seed/budget, and requested validation checks. The result must distinguish domain admission (`ready`/`partial`/`blocked`) from execution failure, and carry fill/rejection outcomes, fold identity, diagnostics, convergence, code/policy/data identities, and content hash.

This must be implemented as behavior, not as a dataclass-only placeholder. It must remain semantically distinct from both `ValuationSimulation` and `MarketPathSimulation`; ticket 02 already preserves those local canonical owners (`.../02-map-capabilities-to-replacement-and-deletion.md:23-31`).

## 4. DataProvider and source-policy interaction

### Existing real port

`DataProvider` is already a small true-external port: identity/version/fixture/endpoint plus `fetch(FetchRequest) -> FetchBatch`. `FetchRequest` carries canonical parameters, security/market/range/cursor identity, credential scope, and explicit network authorization; `RawEnvelope` retains source authority/URL/terms, retrieval time, status, raw hash, cursor, and typed error (`src/trading_platform/domain/data.py:73-119`).

It has two real adapters:

- production `HttpJsonProvider` / specialized `TushareCompatibleProvider`, with explicit network denial and typed rate-limit/HTTP/transport failures (`src/trading_platform/data/providers.py:51-94`);
- deterministic `FixtureProvider`, which implements the same fetch contract and preserves fixture source/hash/failure identity (`src/trading_platform/data/providers.py:20-48`).

Tests exercise both adapter classes through the same `DataSyncService`: deterministic PIT/replay, unauthorized production HTTP with no transport call, offline degradation, fixture-rights blocking, conflict handling, and the Tushare-compatible raw/normalize/quality/PIT path (`tests/platform/test_data_sync_pit.py:50-170`).

### Existing source-policy gaps

`DataSyncService` currently owns an implicit ordered provider fallback and constructs Tushare-shaped wire parameters for each dataset (`src/trading_platform/data/service.py:16-41`). `provider_config.load_sync_job` accepts a string `provider_type` and maps it to concrete classes, while the composition root supplies a singleton provider tuple (`src/trading_platform/provider_config.py:21-99`; `src/trading_platform/application/bootstrap.py:122-165`).

The schema already stores `source_policy_version` on market universes and snapshots (`migrations/0002_provider_normalized_snapshot.sql:82-88`, `migrations/0002_provider_normalized_snapshot.sql:107-129`), but production persistence currently writes hard-coded identities `"universe-source@1"` and `"source@1"` rather than a request-bound policy (`src/trading_platform/data/repository.py:159-167`, `src/trading_platform/data/repository.py:194-230`).

### Seam conclusion

- Keep and deepen the existing `DataProvider` port. Official CNINFO/SSE/SZSE or SEC implementations become concrete protocol adapters only when a product task and admission suite justify them.
- Source selection/order/authority is in-process policy, not another provider port. It should be a typed, versioned source policy owned by data synchronization and included in snapshot identity.
- Move wire-parameter construction into each real adapter. Do not add a generic endpoint adapter configured by URL/method/field mappings.
- Do not create a provider registry/service locator or preserve the current `provider_type` string dispatch as the target architecture.
- Do not add a-stock/global placeholder adapters: tickets 04–05 retained protocol knowledge, not production implementations.

Deletion test: deleting a deep source-policy module should redistribute ordering, authority, fallback prohibition, admission, and policy-identity logic across sync callers/adapters. Deleting a dictionary mapping strings to provider constructors removes only dispatch and reveals a shallow module.

## 5. Artifact identity and lineage

### Existing canonical graph

`ImmutableArtifactDraft` canonicalizes payload/summary, forbids binary floats, computes content hash, and currently admits only:

```text
DataSnapshot -> Forecast -> Valuation -> Simulation
                               \
                                ForecastReview
Simulation + MarketDataSnapshot -> MarketPathSimulation
```

The exact dependency contract ends at `ForecastReview`; there is no strategy-validation kind (`src/trading_platform/domain/workflow.py:943-1053`).

`ResearchArtifactBundle` binds research run, platform data snapshot, code identity, typed drafts, optional workflow and market snapshot identities (`src/trading_platform/application/workflow_ledger.py:439-459`). `ArtifactLineage.validate` is a pure module that rejects empty/untyped/duplicate/misordered graphs, validates frozen subject/snapshot/engine identity, and produces deterministic record/object identities before persistence (`src/trading_platform/domain/artifact_lineage.py:19-42`, `src/trading_platform/domain/artifact_lineage.py:94-180`).

Persistence stores artifact kind/schema/content hash, research/snapshot/subject/source/model/formula/code/policy identities and immutable dependency relations; triggers prohibit update/delete (`migrations/0012_research_artifact_bundle.sql:1-64`). Tests prove the lineage module works without SQLite, exact replay is stable, and tampered parent/subject/order fails closed (`tests/test_artifact_lineage.py:45-127`). Integration tests prove replay, object corruption detection, and immutable artifact rows (`tests/platform/test_workflow_ledger.py:290-398`).

### Strategy-validation implication

If a local strategy module is eventually implemented, it needs a dedicated artifact constructor and lineage validation, not caller-authored generic fields. Its dependency must reference a frozen platform market-data/universe snapshot and its identity must bind:

- engine code and dependency-lock identity;
- strategy/config identity;
- data snapshot, universe/membership, adjustment/calendar/source-policy identities;
- execution-rule, fee, slippage, fold, statistical-method, seed, and convergence identities;
- normalized result content hash.

Raw upstream JSON, HTML/PDF, file paths, booleans, or caller-authored hashes cannot become proof. Adding only `"StrategyValidation": ("MarketDataSnapshot",)` to the string table would be field repackaging unless behavior-specific invariants and tests arrive in the same slice.

## 6. WorkflowLedger persistence

`WorkflowLedgerPort` already owns lifecycle, transitions, checkpoints, artifact commits, completion, typed queries, and integrity audit (`src/trading_platform/application/workflow_ledger.py:490-620`). SQLite `WorkflowLedger` is the one production persistence owner; the architecture test fixes its public method set and rejects cross-seam SQL (`tests/platform/test_workflow_ledger.py:219-287`).

The test composition deliberately uses the production `PlatformStore.workflow_ledger`; it does not define an in-memory `WorkflowLedgerPort` adapter (`tests/platform/application_task_fixture.py:117-170`). This is a local-substitutable SQLite dependency, not evidence for creating a second strategy repository port.

Implications:

- persist future strategy evidence through typed commands/queries on the existing ledger owner;
- do not create `StrategyValidationRepository` that only forwards fields to `WorkflowLedger`;
- do not let a strategy module issue SQL or write artifact files;
- avoid expanding `WorkflowLedgerPort` with a mirror method per domain operation. A complete application task should prepare a typed commit and let the ledger own one transaction.

Deletion test: a forwarding repository would delete cleanly and remove no complexity, so it is shallow. Extending the existing transaction with strategy-specific validation, immutable relations, replay, and integrity behavior can earn depth.

## 7. Typed failure semantics to reuse

The current pattern separates domain/publication outcomes from execution faults:

- `ResearchRun` carries capability/method status, permissions, completeness, integrity issues, and diagnostics for fail-closed but representable research outcomes (`src/equity_research/models.py:338-359`);
- `ProjectionError` carries a stable code and message for typed admission failures (`src/trading_platform/research/assembler.py:15-18`);
- `ResearchExecutionError` carries stable code, retryability, failing substep, and redacted cause type; transient connection/timeout is retryable while value/runtime errors are terminal (`src/trading_platform/workflows/research.py:145-203`);
- each versioned workflow node declares its allowed failure codes (`src/trading_platform/workflows/research.py:90-92`);
- `_fail_node` normalizes unexpected codes, persists a redacted `WorkflowDiagnostic@1`, records the failed transition, then raises `WorkflowError` (`src/trading_platform/workflows/research.py:875-901`);
- tests prove engine failure never creates an empty research run, diagnostics retain the stable code without secret/path/URL leakage, transient attempts are bounded/monotonic, and non-retryable failure stops after one attempt (`tests/platform/test_research_workflow.py:386-412`, `tests/platform/test_workflow_ledger_recovery.py:283-298`).

Future strategy semantics should follow the same split:

- expected evidence insufficiency, unsupported method, incomplete coverage, or non-convergence belongs in a typed `StrategyValidationResult` with `blocked`/`partial` and explicit reason codes;
- transport/process timeout, crash, malformed adapter response, integrity violation, and persistence failure are typed execution failures with retryability and redacted substep evidence;
- no raw exception string, upstream JSON string, MCP success envelope, or generic `"error"` may cross the application interface.

## Rejected proposed shapes

| Proposed shape | Why it is shallow or unsafe | Required decision |
|---|---|---|
| `StrategyValidationPort` plus only a fake | one test adapter and no production variation | reject now |
| `VibeTradingMcpAdapter` placeholder | ticket 06 production allowlist is `[]` | reject |
| `ExternalResearchEvaluator` for Public Equity Investing | plugin has zero executable cases and runtime is rejected | reject |
| one method per upstream MCP tool | mirrors upstream surface and leaks transport concepts | reject |
| `Manager.run(kind: str, payload: dict)` | string dispatch, weak typing, service locator | reject |
| dynamic import/class path in plan or request | caller chooses implementation and bypasses composition root | reject |
| generic HTTP provider configured by endpoint/field strings | protocol/failure/PIT semantics stay in configuration/callers | reject |
| `StrategyValidationRepository` forwarding to ledger | pure field repackaging | reject |
| raw report/view adapter | creates a second presentation model | reject |
| adding a generic artifact kind with no invariants | string table change without domain behavior | reject |
| `ResearchEvaluationFacade` forwarding to `ResearchWorkflow` | duplicates the existing named task | reject |

The fixed lazy-import export table in `application/__init__.py` is packaging machinery, not precedent for runtime strategy/provider dispatch (`src/trading_platform/application/__init__.py:62-119`).

## Current seam decision table

| Concern | Existing canonical seam | Concrete adapters/callers | Ticket-07 constraint |
|---|---|---|---|
| Research execution | `ResearchWorkflow.handle(command)` | CLI, daily cycle, browser acceptance, workflow tests | extend typed request/policy; no mirror facade |
| Research-quality admission | assembler + `ResearchExecution` + `ResearchEngine` + lineage/view gates | direct deterministic engine plus workflow orchestration | `ResearchEvaluationPlan` is in-process policy/value, not a port |
| External data | `DataProvider.fetch` | HTTP/Tushare production and Fixture deterministic adapters | real port; deepen source policy and protocol ownership |
| Source policy | implicit provider tuple/hard-coded snapshot identity | bootstrap/job decoder/sync/repository | replace with typed versioned policy; no string registry |
| Strategy validation | none | none | no port; only implement target-owned deep module with behavior |
| Artifact lineage | `ImmutableArtifactDraft` + `ArtifactLineage` | pure validator and SQLite ledger commit | add dedicated invariants only with implementation |
| Persistence | existing `WorkflowLedgerPort` / SQLite owner | all named research/archive/inspection tasks | no forwarding repository or direct SQL |
| Presentation | `ResearchDecisionView@2` | canonical JSON/HTML/Web/workbook consumers | version and migrate atomically only if strategy evidence becomes decision-relevant |
| Failure semantics | typed outcome + typed execution error + ledger diagnostic | workflow/recovery tests | stable code/retryability/substep; no raw upstream text |

## Bottom line for ticket 07

1. Lock `ResearchEvaluationPlan` as a target-owned typed admission-policy contract inside the existing research workflow; do not introduce an evaluator port.
2. Do not create a `StrategyValidation` port or Vibe adapter. There are not two real adapters after ticket 06.
3. If the capability is retained, specify `StrategyValidationRequest/Result` as the future interface of one local deterministic deep module, and require implementation plus named application task, ledger lineage, tests, and callers in one atomic slice.
4. Reuse the real `DataProvider` port; introduce source policy as typed in-process policy and move wire semantics into real protocol adapters.
5. Reuse `ArtifactLineage`, `WorkflowLedger`, and typed failure patterns; extend them behavior-first, never through forwarding modules or raw external artifacts.
