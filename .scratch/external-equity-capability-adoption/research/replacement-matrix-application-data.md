# Application/data replacement and deletion matrix

Captured: `2026-07-24`

Scope: ticket 02 read-only audit of the current checkout's application and data
path. This asset does not qualify an endpoint, claim or resolve a ticket, change
the map, or propose direct execution of either upstream Skill. The external
rows below are architecture decisions for what may proceed to endpoint
qualification; `adapt-code` remains conditional on the later rights, protocol,
schema, PIT, and live-evidence gates.

## Vocabulary and decision rule

This audit uses the repository's deep-module vocabulary literally:

- **Module**: implementation plus the complete facts a caller must know.
- **Interface**: typed surface, invariants, ordering, failures, configuration,
  and performance facts.
- **Seam**: the location at which an Interface permits behavior to vary.
- **Adapter**: a concrete implementation occupying a Seam.
- **Depth**: leverage behind a small Interface.
- **Leverage**: capability shared by callers and tests per learned Interface.
- **Locality**: provider, transaction, quality, and PIT knowledge changes in one
  owning Module rather than in CLI, Web, or research callers.

The deletion test is decisive. `DataSyncService` and `DataRepository` earn their
place because deleting either redistributes provider ordering, fail-closed
quality, PIT admission, identity, transaction, cursor, raw-object, and snapshot
logic across several callers. A source-specific forwarding class, a Skill
runner, or a second source-to-research path fails the deletion test: deleting it
would remove indirection rather than recreate domain complexity.

Allowed decisions are only `adopt-external`, `adapt-code`, `keep-local`, and
`reject`. No row below permits wrapper-first adoption, fallback to retired code,
 dual read/write, shadow persistence, or direct CLI/Web/Skill execution.

## Current canonical implementation and real call graph

### Named application tasks and callers

The production sync path is:

```text
trading_platform.cli
  -> trading_platform.application.open_data_synchronization(...)
  -> DataSynchronization.run()
  -> DataSyncService.sync(SyncRequest)
  -> DataProvider.fetch(FetchRequest)
  -> normalize(...)
  -> DataRepository
  -> immutable object store + SQLite normalized/PIT snapshot schema
```

The combined daily path is:

```text
trading_platform.cli
  -> open_daily_research_cycle(...)
  -> DailyResearchCycle.run()
  -> sync -> optional ResearchWorkflow -> optional MarketEvaluation -> doctor
```

Primary evidence:

- `src/trading_platform/cli.py::_parser` defines the sole `sync` and `daily`
  commands; `main` calls only the public named-task openers.
- `src/trading_platform/application/bootstrap.py::open_data_synchronization`,
  `open_provider_qualification`, and `open_daily_research_cycle` are the only
  production composition points for provider-backed synchronization.
- `src/trading_platform/application/cli_tasks.py::DataSynchronization.run` owns
  watchlist registration plus one configured sync journey.
- `src/trading_platform/application/cli_tasks.py::DailyResearchCycle.run` owns
  the complete sync/research/market/doctor order.
- `tests/platform/test_cli_application_tasks.py::
  test_cli_imports_public_named_tasks_not_root_facade_or_persistence` proves the
  CLI crosses `trading_platform.application`, not persistence or a root facade.
- `tests/platform/test_cli_application_tasks.py::
  test_retired_routes_facade_ports_and_forwarders_are_deleted` proves the
  former facade, root, generic ports, and parallel research commands are absent.

The Web is a read/presentation caller, not a data-ingestion caller:

- `src/trading_platform/web_server.py::LocalChartWorkspaceServer` receives
  `DecisionWorkspace`, `ChartWorkspace`, `ChartAnnotations`,
  `PlanConfirmation`, and `UpdateAuthorizations`; it exposes persisted chart and
  workspace projections, not provider calls.
- `src/trading_platform/application/bootstrap.py::open_chart_workspace` and
  `open_decision_workspace` compose `ChartService` and `WorkspaceService`.
- `src/trading_platform/chart.py::ChartService.get_series` reads an immutable
  `data_snapshot` and typed `ohlcv_version` rows.
- `src/trading_platform/persistence/workspace.py::WorkspaceService.build` reads
  snapshot freshness/quality and history, then loads persisted
  `ResearchDecisionView` payloads through `WorkflowLedgerPort`.

Consequently, adopted data changes reach Web only after canonical persistence
and presentation projection. Adding Web routes that call an upstream source
would be a bypass.

### Current Modules, Interfaces, Adapters, and Depth

| Module | Interface and Seam | Canonical implementation and callers | Depth / deletion-test result |
|---|---|---|---|
| Application composition | public `open_*` named tasks in `trading_platform.application` | `application/bootstrap.py`; CLI, Web setup, and application journey tests | Keep. It owns readiness, lifetime, exact Adapter wiring, and dependency direction. A root/facade/service locator would reduce Locality and is already forbidden by tests. |
| Data synchronization journey | `DataSynchronization.run()` and `DailyResearchCycle.run()` | `application/cli_tasks.py`; CLI `sync`, CLI `daily`, provider qualification | Keep. It owns complete user tasks and gives callers high Leverage. |
| Provider Seam | `domain/data.py::DataProvider.fetch(FetchRequest) -> FetchBatch` plus provider identity/version/fixture/endpoint facts | `FixtureProvider`, `HttpJsonProvider`, `TushareCompatibleProvider`; `DataSyncService` is the caller | Real Seam: production and deterministic fixture Adapters exist. Preserve it, but deepen its Interface before adding heterogeneous sources so callers do not author provider-specific parameters. |
| Acquisition/PIT Module | `DataSyncService.sync`, `snapshot_members`, `provider_attempt_evidence` | `data/service.py`; named application tasks and owning tests | Keep and deepen. It owns ordered attempts, rights gates, normalization admission, cursor rules, coverage, freshness, and snapshot result. |
| Canonical normalization Module | `normalize(dataset, raw, ...) -> tuple[NormalizedItem, ...]` | `data/normalizer.py`; only `DataSyncService` calls it | Keep canonical validation behavior, but remove source-protocol parsing from this Interface. Adding branches for every external payload would destroy Locality. |
| Data persistence Module | `DataRepository` methods used by `DataSyncService` | `data/repository.py`; owns SQLite transactions and calls `WorkflowLedgerPort` for immutable raw objects | Keep. It owns meaningful transaction, hash, rights, revision, source-conflict, cursor, quality, and snapshot behavior; deletion would spread this complexity. It is concrete at an internal composition seam, not a public caller interface. |
| Raw/artifact persistence Adapter | `WorkflowLedgerPort.commit_artifacts/load` | `persistence/workflow_ledger.py::WorkflowLedger` and object tables/files | Keep. `DataRepository.record_attempt` content-addresses raw bytes through this owner; a provider-local cache would be a second persistence path. |
| Market read/evaluation Module | `MarketEvaluationService.build_market_snapshot/evaluate_plan` with `MarketRepository` Seam | `market.py`, `persistence/market.py::SQLiteMarketRepository`; daily and explicit market CLI callers | Keep. Deterministic trend, breadth, liquidity, volatility, price context, constraints, and rule evidence remain local domain behavior. |
| Chart presentation Module | `ChartWorkspace.get_series` | `ChartService`, `LocalChartWorkspaceServer` | Keep. It presents only snapshot-bound canonical series. It currently rejects adjusted series, exposing a real corporate-action ingestion gap rather than permission for a parallel chart feed. |
| Research input Module | `SnapshotToResearchRequestAssembler.assemble/fingerprint` | `research/assembler.py`; `ResearchWorkflow` | Keep. It validates frozen source-manifest semantics, but it does not currently assemble financial facts or filings from normalized data. This is a missing canonical bridge, not an invitation for a Skill-to-engine shortcut. |

### Persistence and presentation owned by the current path

`migrations/0002_provider_normalized_snapshot.sql` owns the core provider
tables: `provider_attempt`, `sync_cursor`, `normalized_record`,
`normalized_version`, `ohlcv_version`, `market_session_version`,
`market_universe_version/member`, `data_quality_issue`, `data_snapshot`,
`data_snapshot_member`, and `fixture_rights_profile`.
`DataRepository.record_attempt` stores raw bytes through
`WorkflowLedgerPort.commit_artifacts(GenericObjectCommit(...))`, so raw storage
is the same content-addressed object path used by the application. There is no
provider-owned cache to retain.

Downstream impact is deliberately narrow:

- CLI `sync` serializes `SyncResult`; CLI `daily` serializes
  `DailyResearchResult`.
- `ProviderQualificationService.run` reloads attempt evidence from the same
  repository; it does not trust provider-authored success.
- `ChartService.get_series` consumes typed snapshot-bound `ohlcv_version`.
- `SQLiteMarketRepository.build_market_snapshot` consumes snapshot-bound OHLCV,
  universe, and market constraints.
- `WorkspaceService.build` shows snapshot quality/freshness/history and
  persisted decision views; full provenance remains available through history
  rather than becoming a default field wall.

Any new dataset therefore needs one atomic path: provider acquisition, raw
identity, canonical normalization, typed persistence, snapshot membership,
research/market consumption where applicable, and decision-first presentation.
An upstream result rendered directly in CLI or Web would skip every owned
invariant above.

## Current gaps that external adoption must not conceal

1. **Production source policy is not implemented.**
   `DataSyncService` accepts an ordered `Sequence[DataProvider]`, and
   `tests/platform/test_data_sync_pit.py::
   test_empty_rate_limit_and_schema_drift_do_not_advance_cursor_and_fallback_attempts_remain`
   exercises multiple fixture/failure Adapters. Production
   `open_data_synchronization`, `open_provider_qualification`, and
   `open_daily_research_cycle`, however, each call `load_sync_job` and compose
   exactly `(provider,)`. `provider_config.py::load_sync_job` decodes one
   `provider_type`. There is no versioned capability/market/source policy,
   retry budget, rate limiter, circuit state, or multi-source production trace.

2. **The synchronization Module authors Tushare-shaped requests.**
   `DataSyncService.sync` hard-codes `exchange/start_date/end_date`,
   `ts_code/start_date/end_date`, and `ts_code/list_status`; the generic
   `FetchRequest.canonical_params` therefore leaks one Adapter's protocol into
   the caller. Adding `if a_stock` or `if global_stock` branches here would
   lower Depth and scatter source knowledge. A deepened Provider Interface must
   accept canonical dataset intent and let each Adapter own wire translation.

3. **Protocol decoding and canonical validation are mixed.**
   `normalize` recognizes both canonical `{"rows": ...}` and the
   Tushare-compatible `{"data":{"fields":...,"items":...}}` response. Adding
   Yahoo, Eastmoney, Tencent, Sina, CNINFO, or SEC branches to this function
   would make one source-switching parser. Provider-specific decoding must be
   inside the Adapter implementation; the canonical normalization Module should
   only validate canonical rows and quality invariants.

4. **Dataset coverage is far below the authoritative baseline.**
   Production normalization supports only `daily`, `trade_cal`,
   `market_universe`, and `forecast_actual`. Migrations have no typed
   `corporate_action`, `financial_fact`, `filing`, `industry_peer`,
   `macro_series`, or `news_event` tables, even though
   `docs/prompts/trading_platform_codex_prompt_optimized.md` lines 314-323
   require them. `tests/platform/application_task_fixture.py::
   record_official_filing_workflow_snapshot` inserts a synthetic
   `financial_statement` record directly with SQL; no production Provider path
   can create it. This test-only shortcut is evidence of a missing Module.

5. **`forecast_actual` is identity-only persistence.**
   `normalize` validates a typed-looking actual, but
   `DataRepository._persist_typed_payload` has no `forecast_actual` branch.
   Only generic record/version identity and content hash survive; the fact
   payload is not loadable from an owning typed table.
   `tests/platform/test_forecast_review_artifact.py::
   persist_review_snapshot` separately keeps the caller-authored
   `ForecastActual` and attaches the returned `normalized_version_id`. That is
   not yet a production evidence ingestion Interface.

6. **Universe normalization is incorrect for a full-universe response.**
   In the Tushare-compatible branch, every `stock_basic` source row is assigned
   the request's single `security_id`. `DataSyncService` also uses that same
   security as the cursor/scope. A multi-row market universe therefore cannot
   resolve each provider identifier to a canonical security identity.
   `test_tushare_compatible_provider_uses_same_raw_normalize_quality_pit_path`
   consequently verifies typed OHLCV but returns `SyncStatus.MISSING` and no
   snapshot members. A Security Master/identifier resolution Module must own
   this mapping before any external full-market list is adopted.

7. **Adjusted prices and corporate actions have no ingestion path.**
   `normalize` rejects `daily.adjustment_mode != "none"`;
   `ChartService.get_series` also accepts only unadjusted/no-factor series.
   Domain artifact lineage can validate adjustment/corporate-action member IDs,
   but no current provider/normalizer/persistence implementation creates those
   members. External adjusted K-lines cannot be written as a second OHLCV table
   or rendered by a second chart path.

8. **Research facts are not derived from normalized evidence.**
   `SnapshotToResearchRequestAssembler` validates caller-supplied frozen
   manifests and field semantics. It does not load normalized official filings
   or financial facts. Critical facts from a new Adapter must feed one typed
   EvidenceSnapshot-to-research assembly path; directly placing an upstream
   dictionary into `ResearchWorkflowRequest` would bypass source authority,
   availability, unit/currency, restatement, and snapshot identity.

9. **Failure typing is incomplete at the transport edge.**
   `HttpJsonProvider` distinguishes 429 from generic HTTP/transport failure, but
   has no response-size limit, timeout taxonomy, retry-after contract, schema
   identity, or circuit/rate-limit policy. `except Exception` is redacted but
   overbroad. External upstream empty/zero fallbacks must not be copied.

10. **Configuration is single-provider and source-specific.**
    `provider_config.load_sync_job` selects only `http_json` or
    `tushare_compatible`; it accepts a caller-provided `source_identity` and
    `terms_profile` without binding them to a reviewed source-policy version.
    A production policy migration must replace this schema once and delete the
    old decoder; accepting both old and new jobs would be compatibility code.

## Replacement and deletion matrix

The rows distinguish domain behavior from wire acquisition. No external
repository becomes a production runtime dependency: both upstreams are
single-file Skills, not stable libraries. “Adapt” means copy the smallest
qualified protocol/parser behavior into an owned Adapter implementation with
origin attribution and local tests.

| Capability | Current canonical implementation | External candidate | Decision | Adoption conditions and Interface placement | Required deletion / atomic migration | Rejection reason where applicable |
|---|---|---|---|---|---|---|
| Provider/PIT/raw/quality/snapshot lifecycle | `DataSynchronization` -> `DataSyncService` -> `DataRepository`; `RawEnvelope`, `NormalizedItem`, `SyncResult`; immutable object store and SQLite snapshot schema | Both Skills' orchestration, source-priority tables, caches, and free Python execution | `keep-local` | New sources occupy the existing/deepened `DataProvider` Seam only. Preserve requested/effective/as-of/published/available/retrieved times, quality, freshness, rights, hashes, cursors, and snapshot identity. | Delete no local owner. Delete any prototype Skill runner, provider-local cache, direct research fetch, or second persistence schema in the same change that introduces it; none exists now. | Upstream orchestration has no compatible transaction, rights, PIT, typed failure, snapshot, or persistence contract. |
| Tushare-compatible A-share calendar/basic/daily Adapter | `TushareCompatibleProvider`, Tushare response branch in `normalize`, typed calendar/OHLCV/universe persistence | A-share and global source snippets as a replacement for the configured gateway | `keep-local` | Retain as a separately qualified Adapter and structured-aggregator source. External Adapters may coexist only as different source-policy entries at the same Seam, never as a hidden fallback. | No deletion merely to add a different source. If the Provider Interface is deepened, atomically migrate this Adapter and delete `api_name_map`, Tushare parsing in generic `normalize`, and the old job schema. | Neither Skill proves a superior, rights-qualified replacement for the current gateway. |
| A-share daily unadjusted OHLCV wire acquisition | Canonical `daily` dataset, OHLCV validation, `ohlcv_version`, snapshot/chart/market consumers; live implementation is Tushare-compatible | `a-stock-data` TongdaXin/Tencent/Baidu/Eastmoney K-line protocol snippets | `adapt-code` | Only a later qualified endpoint/parser may become an owned A-share Adapter. It must emit canonical decimal, unit, currency, timezone, availability, adjustment, and source identity; empty is typed missing/failed. No `mootdx` runtime or Skill execution is implied. | Migrate callers through one versioned source policy. Delete copied upstream fallback chains, generic-normalizer source branches, and any temporary old job decoder. Do not delete Tushare unless a later matrix row explicitly proves full replacement. | Direct Skill adoption is rejected: unconstrained dependencies, broad egress, fallback-to-empty, and unqualified data rights. |
| US/HK daily unadjusted OHLCV wire acquisition | Same canonical `daily` contract and downstream consumers; no production US/HK Adapter | `global-stock-data` Sina/Yahoo/Eastmoney/Tencent history snippets | `adapt-code` | A qualified market-specific protocol/parser may become one owned GlobalStockData-derived Adapter. It must preserve exchange timezone, currency, units, session dates, availability, and complete failure evidence. Market routing belongs to versioned source policy, not CLI. | Delete any direct Yahoo/Sina/Eastmoney caller and any provider-specific branch in the generic normalizer. One-way migrate source-policy configuration and tests; no dual job formats. | Direct Skill/library adoption is rejected: no package/tests/lock, inconsistent endpoints, and no downstream data-rights grant. |
| Real-time quote, order book, trades, minute bars | No canonical typed entity, task, persistence, or decision-first presentation; first workflow is post-close/next-trading-day and chart reads frozen daily bars | `a-stock-data` quote/depth/trades/minute sources; `global-stock-data` US/HK quote sources | `reject` | None for this Goal's production path. A future separately specified user task would need typed identities, market-time semantics, TTL, rights, storage, and presentation before reconsideration. | Delete no local implementation. Never add a direct quote panel beside snapshot-bound chart/workspace. | Adoption now would create a second live-data path, bypass PIT snapshots, and expand product scope into intraday behavior without a domain Interface. |
| Market calendar | `trade_cal` normalization, `market_session_version`, effective-session selection in `DataRepository.build_snapshot`; Tushare-compatible Adapter | Neither Skill exposes a comparably specified canonical calendar capability | `keep-local` | Preserve authoritative calendar and cutoff semantics. A future Adapter must implement the same dataset contract. | No deletion. | K-line date presence is not a trading-calendar implementation and cannot replace session/holiday semantics. |
| Security Master, identifiers, and market universe | `security`/`security_identifier`; Watchlist named task; incomplete `market_universe` ingestion | `a-stock-data` A-share code conventions/search; `global-stock-data` stock search, ticker-to-CIK, full-market lists | `adapt-code` | Qualified identifier/search/list protocols may populate one canonical Security Master/market-universe Module. Provider identifiers must resolve per row with half-open validity and market/currency/listing semantics. Search is an Adapter input, not a new user-facing source of truth. | Delete the broken single-`security_id` universe mapping, request-scoped universe cursor, and direct-SQL universe fixtures after replacement interface tests exist. Delete any caller-owned code-format routing. | Upstream symbols and search results alone are not stable canonical identity or listing-history evidence. |
| Adjustment factors and corporate actions | Lineage and plan domains can reference adjustment/corporate-action identities, but provider normalization/persistence and chart query support only unadjusted bars | `a-stock-data` dividends/lockups/F10/announcements and adjusted K-line candidates; limited global corporate metadata | `adapt-code` | Only qualified official/structured protocols may feed typed `corporate_action` and adjustment-factor entities in the same snapshot path. Canonical code owns ex-date, record date, factor method/version, currency, supersession, and conflict quality. | Atomically add typed persistence and migrate Chart/Market/Research consumers; then delete the `adjustment_mode != "none"` source and chart rejection path where superseded, along with caller-authored adjustment evidence. Never retain separate adjusted/unadjusted provider tables. | Pre-adjusted upstream prices without action/factor lineage are rejected because they cannot prove no look-ahead or consistent reversibility. |
| Official A-share filings and announcements | No production ingestion Module; research manifest accepts frozen official sources; test fixture inserts `financial_statement` directly | `a-stock-data` CNINFO/SSE/SZSE protocol/parser fragments | `adapt-code` | Only HTTPS, endpoint-rights-qualified official document metadata/content behavior may enter an `OfficialDisclosure` Adapter at the DataProvider Seam. It must preserve document ID, issuer identity, publication/availability/retrieval times, correction/supersession, raw hash, and authority. | Delete cleartext CNINFO mapping, TLS-disabled fallback, hard-coded org-id fallback, direct PDF writes, and test-only direct SQL filing creation. Replace research caller-authored filing records with one typed EvidenceSnapshot assembler; no legacy path. | Eastmoney/mootdx mirrors cannot be upgraded to official authority; insecure transport and guessed identifiers are rejected. |
| Official US filings and XBRL facts | No production filing/financial-fact ingestion; source-manifest gate and financial semantics validation are local | `global-stock-data` SEC submissions, companyfacts, ticker-to-CIK snippets | `adapt-code` | Qualified SEC protocol/parsing code may be maintained in an OfficialDisclosure Adapter. It must use declared identification, accession/form/taxonomy/unit/period/frame semantics, filing availability, amendment/supersession, and typed missing facts. | Delete direct request dictionaries and any caller-authored `source_manifest` financial values after typed `filing`/`financial_fact` persistence and one EvidenceSnapshot assembly path replace them. Remove fixture SQL that pretends the production path exists. | Yahoo/Eastmoney statements cannot be the authority for critical US facts. SEC code is useful only after protocol, rate/UA, schema, and terms qualification. |
| Secondary A/H/US financial statements and metrics | Research source-manifest authority tiers and fail-closed critical-data rules; no provider ingestion implementation | A-stock mootdx/Sina/Eastmoney/THS statements; global Eastmoney/Yahoo statements and metrics | `reject` | They may be separately reconsidered as auxiliary cross-check evidence, never as a critical-fact authority or readiness upgrade. This ticket does not create that path. | Delete no local owner. Do not create generic “fundamentals” JSON storage or a secondary-to-official fallback. | Units, accounting scope, restatement, filing identity, publication time, rights, and authority are insufficient; unknown/empty behavior is unsafe. |
| Forecast actual evidence | `forecast_actual` normalizer plus generic record/version identity; Forecast Review accepts caller-provided typed actual referencing that identity | Financial data snippets from both Skills | `keep-local` | Deepen local typed persistence/load and official evidence assembly first. External code may later supply only a qualified Adapter, not the Forecast Review semantics. | Add a typed actual table/loader and migrate Forecast Review to load snapshot evidence; then delete the caller-authored actual-plus-ID path and tests that construct payload and object separately. | Upstream financial dictionaries do not implement forecast-target matching, comparability, calibration, or official-source gates. |
| News and issuer events | Required baseline entity but no canonical provider/persistence/presentation Module | A-stock CNINFO/news/CLS/Eastmoney/Sina; global Yahoo news | `adapt-code` | Only qualified document/event metadata may enter a typed `news_event`/filing evidence path. Official issuer events and secondary media must retain different authority. Presentation belongs under evidence/provenance disclosure, not a default feed wall. | Delete upstream topic-ranking, direct Web feeds, downloaded-file directories, and empty-on-error semantics. If a prototype feed exists during qualification, it must be removed before the canonical path is introduced. | Generic news aggregation cannot support critical facts and must never silently mean “no event.” |
| Research reports, analyst ratings, consensus targets | Formal research uses typed source manifest, Forecast, valuation router, equity bridge, and financial-output boundary; no canonical analyst-rating ingestion | A-stock report/PDF/iwencai/THS consensus; global Yahoo recommendations/targets | `reject` | None as a formal result or target-price input. At most a later discovery-only control-plane task could surface candidates with explicit non-authority, but not through production data readiness. | Delete no local implementation. Never add target/rating fields to `ResearchDecisionView` from these sources. | Secondary consensus, blanket PE anchors, rating/target language, credential redirection risk, and missing source semantics conflict with financial and data gates. |
| Institutional holders, fund flow, northbound, margin, dragon-tiger, block trade, lockup, board/limit pools | No complete canonical typed entities; Market Module derives trend/breadth/liquidity/volatility only from frozen OHLCV/universe/constraints | Broad A-stock market-flow/event snippets; global institutional holder and fund-flow snippets | `reject` | No production adoption in this Goal without a separately specified typed dataset, rights profile, point-in-time semantics, completeness definition, and decision use. | Delete no local behavior. Never map absent upstream rows to zero or inject them directly into market components. | Upstream failure-to-empty, unclear units/index meanings, current-vs-historical ambiguity, and unqualified rights would create false facts and a parallel signal stack. |
| Technical indicators and market-state calculations | `domain/market.py::compute_components`, `_trend`, `_breadth`, `_liquidity`, `_volatility`, `_price_context`; typed evidence and MarketSnapshot persistence | A-stock stockstats indicators; global MA/EMA/MACD/RSI/KDJ/Bollinger snippets | `keep-local` | Continue deterministic calculation from snapshot-bound canonical series. External formulas are comparison material only; any formula change is a versioned local domain change with golden tests. | Delete no current Module. Do not persist provider-computed indicator values or add an indicator Adapter. | An external indicator library adds no real variability Seam and would weaken lineage, model versioning, and Locality. |
| Provider selection/fallback/rate policy | Test-only ordered provider sequence inside `DataSyncService`; production singleton job | Both Skills' hard-coded source priority and fallback tables | `keep-local` | Implement one versioned local source-policy Module that selects qualified Adapters by capability/market/authority and records every attempt. It may continue after typed retryable/missing outcomes; it must never use old implementation fallback. | One-way migrate `provider_config.load_sync_job`; delete single `provider_type` dispatch and old job format in the same change. Delete all copied upstream fallback tables/branches from Adapter code. | Upstream priority tables are unversioned operational advice and treat empty/error as a fallback trigger without canonical evidence semantics. |
| Provider transport and protocol parser implementations | `HttpJsonProvider`/`TushareCompatibleProvider`; generic Tushare-aware normalizer | Narrow qualified functions from both upstream Skills | `adapt-code` | Adapt only exact protocol/parser code after endpoint qualification. Each owned Adapter must constrain host/scheme, credentials, timeout/size, request identity, status taxonomy, source headers/time, and canonical decoding. Apache attribution and modified-file records are required. | Delete the corresponding copied snippet's insecure transport, broad catches, prints, local cache/file writes, old fallback, and generic normalizer branch. No vendored Skill and no runtime dependency. | Whole-Skill adoption is rejected because neither upstream supplies a stable package Interface, tests, lock, rights, or safe failure contract. |

No application/data row supports `adopt-external`: neither upstream provides an
implementation that can become the sole production implementation while
preserving the local Interface and completing callers, tests, persistence, and
presentation cutover atomically. The only permissible external movement is
selective `adapt-code` behind the canonical Provider Seam.

## Required one-way deepening and cutover sequence

This is an architectural dependency order, not authorization to implement
ticket 02:

1. Define the versioned source-policy and canonical acquisition intent inside
   the DataSynchronization Module. Provider-specific query parameters and
   response parsing move behind each Adapter.
2. Migrate the existing Tushare-compatible and fixture Adapters to the deepened
   Interface; delete old `canonical_params` construction, `api_name_map`,
   generic Tushare decoding, and the old single-provider job decoder in the
   same migration. There must be no dual job/schema reader.
3. Add typed Security Master/universe resolution so every source row resolves
   a canonical identity. Delete request-security reuse for universe rows.
4. For each later-qualified external capability, add exactly one owned Adapter
   and the necessary typed normalized entity/persistence. Do not land an
   Adapter whose data can only be stored as an opaque generic hash.
5. Build one EvidenceSnapshot-to-research assembly path for official
   filings/facts and forecast actuals. Migrate `ResearchWorkflow` inputs and
   delete caller-authored/direct-SQL evidence construction.
6. Update only the existing CLI sync/daily results, Workspace history/evidence,
   Chart/Market consumers, and persisted `ResearchDecisionView` as appropriate.
   No external-specific CLI command or Web fetch route is permitted.
7. Replace old Interface tests with named-task journey tests and retain SQL
   assertions only for owning persistence Adapter invariants. Delete retired
   fixtures, symbols, schemas, docs, configuration examples, and dependencies
   in the same change.

## Verification evidence inspected

- `src/trading_platform/application/{__init__,bootstrap,cli_tasks,web_tasks}.py`
- `src/trading_platform/{cli,web_server,provider_config,provider_qualification}.py`
- `src/trading_platform/domain/data.py`
- `src/trading_platform/data/{service,providers,normalizer,repository}.py`
- `src/trading_platform/{market,chart}.py`
- `src/trading_platform/persistence/{market,workspace,workflow_ledger}.py`
- `src/trading_platform/research/assembler.py`
- `migrations/0001_core_identity_objects.sql`
- `migrations/0002_provider_normalized_snapshot.sql`
- `migrations/0006_market_snapshot_evaluation.sql`
- `tests/platform/test_{cli_application_tasks,web_application_tasks,data_sync_pit,provider_qualification,forecast_review_artifact,research_workflow}.py`
- `tests/platform/application_task_fixture.py`
- `README.md`
- `docs/architecture/target-architecture.md`
- `docs/prompts/trading_platform_codex_prompt_optimized.md`
- ticket-01 pinned upstream audits and the pinned `a-stock-data` and
  `global-stock-data` Skill capability headings

This was source/schema/test inspection only. No endpoint was contacted and no
endpoint correctness, rights, or production availability is asserted here.
