# Strategy / backtest external-capability replacement matrix

## Scope and evidence boundary

This is a ticket-02 research asset for the current checkout. It does not claim
or resolve the Wayfinder ticket, qualify an endpoint or Vibe-Trading algorithm,
lock the final `StrategyValidation` interface, or authorize production changes.
The decisions below are **candidate decisions** constrained to
`adopt-external`, `adapt-code`, `keep-local`, or `reject`.

The matrix permanently excludes all live or simulated order placement, broker
connections, order lifecycle, upstream file tools, arbitrary Web/search,
persistent memory, swarm orchestration, upstream Agent/runtime, upstream Web UI,
and parallel report/persistence paths.

Evidence read for this matrix:

- [`current-canonical-seams.md`](current-canonical-seams.md)
- [`public-equity-investing-upstream-audit.md`](public-equity-investing-upstream-audit.md)
- [`a-stock-data-upstream-audit.md`](a-stock-data-upstream-audit.md)
- [`global-stock-data-upstream-audit.md`](global-stock-data-upstream-audit.md)
- current production, migration, Web, CLI, acceptance, and test sources cited
  below.

Vibe-Trading identity/attack-surface evidence was captured from the isolated
clone at `E:\workspace\tradingSystem-upstreams\Vibe-Trading`, pinned to
`0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` (MIT; latest release `v0.1.12`).
This matrix uses only its static identity/attack-surface evidence. No Vibe
process or strategy was run.

## Current checkout: strategy and backtest reality

1. There is no `StrategyValidation`, `StrategyValidationRequest`,
   `StrategyValidationResult`, strategy table, or backtest-run table in
   `src/`, `tests/`, or `migrations/`. The current artifact constructors end
   at `ForecastReview`; valuation `Simulation` and `MarketPathSimulation` are
   already separate typed kinds
   ([`domain/workflow.py`](../../../src/trading_platform/domain/workflow.py)).
2. Acceptance explicitly records `full_trade_backtest = not_applicable` and
   explains that no execution, fee, slippage, or T+1 simulator is in scope
   ([`acceptance.py:70`](../../../src/trading_platform/acceptance.py),
   [`acceptance.py:496`](../../../src/trading_platform/acceptance.py)).
3. The canonical CLI has no strategy/backtest command. Its task routes include
   `sync`, `daily`, `research`, `serve`, `provider-qualify`, and `acceptance`,
   among other maintenance and account commands
   ([`cli.py:56`](../../../src/trading_platform/cli.py)).
4. Web calls only the named `DecisionWorkspace`, `ChartWorkspace`,
   `ChartAnnotations`, `PlanConfirmation`, and `UpdateAuthorizations`
   interfaces. Its HTTP routes are chart series, annotations, workspace,
   update authorization, and plan confirmation; there is no strategy route
   ([`application/web_tasks.py:25`](../../../src/trading_platform/application/web_tasks.py),
   [`web_server.py:55`](../../../src/trading_platform/web_server.py)).
5. Current migrations end at `0012_research_artifact_bundle.sql`; none owns
   strategy runs, folds, metrics, external-engine identity, or strategy
   artifacts ([`migrations/`](../../../migrations/)).
6. Tests deliberately protect the no-execution boundary. Runtime inventory
   rejects public broker/order/execution symbols, while trade plans say
   `records_user_rules_only_no_trade_execution`
   ([`test_runtime_skeleton.py:117`](../../../tests/platform/test_runtime_skeleton.py),
   [`test_trade_plans.py:76`](../../../tests/platform/test_trade_plans.py)).
7. The current `DataProvider -> DataSyncService -> DataRepository -> immutable
   snapshot` path is real and tested. `DataProvider` returns `FetchBatch` with
   typed raw envelopes; `DataSyncService` owns attempts, normalization, PIT,
   quality, rights, cursor, and snapshot behavior
   ([`domain/data.py:74`](../../../src/trading_platform/domain/data.py),
   [`data/service.py:16`](../../../src/trading_platform/data/service.py)).
8. Formal research remains
   `ResearchWorkflow.handle(StartResearchWorkflow(request))`, and the only
   formal presentation model is `ResearchDecisionView@2`; JSON, HTML, Web, and
   XLSX derive from it
   ([`workflows/research.py:496`](../../../src/trading_platform/workflows/research.py),
   [`research_view.py:20`](../../../src/trading_platform/research_view.py)).

The absence of a strategy module is important: there is no local production
backtest engine to wrap, preserve as a fallback, or pretend to replace.

## Candidate decision matrix

| Capability / behavior | Current canonical implementation | External candidate | Candidate decision | Adoption condition | Caller impact | Persistence impact | Presentation impact | Explicit deletion object | Rejection / boundary reason |
|---|---|---|---|---|---|---|---|---|---|
| Formal company research execution and publication | Typed `ResearchWorkflow`, `ForecastGraph`, scenario valuation, source gates, `ResearchDecisionView@2` | Public Equity Investing hosted workflow | `keep-local` | It may later be compared against the same frozen, non-personal source manifest only if Plugin Management makes it genuinely available | No production caller change; Codex control plane may prepare candidate questions/drafts, then use the existing typed request route | No hosted-plugin payload, provider content, hidden prompt, or free text enters the ledger as authority | No hosted report is published; current typed view remains sole model | None: the current implementation remains canonical; delete any evaluation-only downloaded/exported plugin draft after comparison retention expires | Hosted identity has no source hash, runtime contract, or data entitlements; current availability is `external_blocked`; official examples include prohibited add/trim/exit, rating, target, and recommendation language |
| Research checklist, diligence-question, counterevidence, and quality-comparison patterns | Locally governed Codex Skill instructions plus typed Forecast/valuation inputs | Public Equity Investing control-plane behavior | `adapt-code` | Only human-readable workflow ideas demonstrated by black-box evidence may be rewritten as local control-plane instructions; no hidden prompt copying and no business-runtime LLM dependency | Codex-only instruction change; application callers remain unchanged | No new persistence schema; accepted facts still require the local source manifest and typed artifact path | No new view; local view may receive only already-typed, policy-compliant facts | Delete superseded local control-plane checklist text in the same change; never retain old and new checklist paths | Adaptation is limited to workflow knowledge. The hosted plugin itself cannot become a runtime, provider, valuation authority, or action-decider |
| Public Equity Investing as structured financial-data source | Existing qualified providers plus official-disclosure requirement | Named commercial data integrations behind the hosted plugin | `reject` | None under currently disclosed evidence | No provider or caller is added | No plugin/provider data is cached or persisted | No plugin-derived number is displayed as an accepted fact | Delete any experimental provider config, connector, or imported plugin dataset before ticket closure | Provider entitlements, PIT semantics, authority, retention, derivation, cache, and redistribution rights are unknown |
| Direct execution of the A-share Skill | No Skill execution in business runtime; CLI/Web cross named application tasks | `a-stock-data` embedded Python in `SKILL.md` | `reject` | None | No CLI, Web, research, or application caller may invoke the Skill or its snippets | No Skill-owned cache/files or raw payloads | None | Delete every prototype Skill runner, dynamic import, script wrapper, or direct endpoint call before adoption | It is a Markdown knowledge base, not a stable package; direct use bypasses `DataProvider`, typed failure, PIT, rights, provenance, and snapshot identity |
| Qualified A-share auxiliary market-data endpoint protocol and parsing | Tushare-compatible primary structured provider; generic `HttpJsonProvider`; typed normalization/snapshot path | Selected a-stock-data Eastmoney/Tencent/Sina/Baidu/THS/Baostock/mootdx protocol knowledge | `adapt-code` | Ticket 04 must qualify each endpoint's identity, authority, terms, cache/redistribution, rate limit, empty/partial/error semantics, timestamps, adjustment, calendar, suspension/limit rules, and field stability; only complete tested protocol behavior may be reimplemented | Existing `DataSynchronization` task remains the caller; CLI/Web never choose provider strings or call endpoints | The existing raw-attempt, normalized-version, quality, cursor, and snapshot schema remains the only persistence route; new dataset schema requires a one-way migration | Existing workspace/view sees only normalized typed results; no provider HTML/JSON becomes a presentation model | Delete any endpoint-specific parameter construction or parsing duplicated in callers; delete qualification scripts/prototypes when their behavior is owned by the production adapter; do **not** delete the Tushare-compatible primary path | Candidate sources are auxiliary/secondary, never official authority. Empty must not mean no event and unknown must not become zero |
| A-share critical financial/disclosure authority | Official disclosure remains mandatory; current source gates fail closed | Aggregator financial/F10 endpoints described by a-stock-data | `reject` | None for authority status; a qualified endpoint may still be auxiliary under the previous row | No source-policy caller may promote it to official | It cannot satisfy critical official coverage or upgrade a blocked valuation/research artifact | It cannot remove missing-source warnings | Delete any source-policy entry that labels an aggregator `official_disclosure` | The upstream code license does not grant data rights, and aggregator provenance cannot replace CNINFO/SSE/SZSE/BSE/company IR |
| Direct execution of the global-stock-data Skill | No Skill execution in business runtime | `global-stock-data` embedded Python in `SKILL.md` | `reject` | None | No direct CLI/Web/research invocation | No Skill-owned cookies, CIK cache, payload cache, or free-form result persistence | None | Delete any Skill runner, copied all-in-one script, wrapper, or caller-side endpoint code | The Skill has no stable package, tests, or CI and collapses failures/unknowns; direct execution is a bypass |
| SEC EDGAR/XBRL protocol knowledge for US official disclosure | Official-disclosure requirement exists, but no qualified SEC adapter is in the current production path | global-stock-data SEC submissions/companyfacts/ticker-map snippets | `adapt-code` | Ticket 05 must qualify SEC access policy, required user agent, rate limits, filed/accepted/available time, restatements, units, periods, identities, pagination, errors, and retention; code must be rewritten behind the canonical data seam with fixtures | Only the named synchronization/research task calls through the local provider policy | Raw envelopes and normalized facts must retain official URL, filed/available/retrieved times, hashes, and snapshot identity; no upstream in-memory cache is authoritative | Formal view uses only accepted typed evidence | Delete any generic HTTP/SEC calls in callers and all qualification-only scripts; no parallel SEC cache or report | Adapt only protocol/parsing knowledge. The upstream placeholder SEC contact and untyped time/identity behavior are not production-ready |
| US/HK auxiliary quote, OHLCV, holder, options, news, screening, and fund-flow protocol knowledge | No qualified global auxiliary adapters; official sources remain authoritative for critical facts | global-stock-data Yahoo/Eastmoney/Sina/Tencent snippets | `adapt-code` | Ticket 05 must resolve current field-index issue #2, endpoint rights, identity, timezone, adjustment, corporate actions, empty/partial semantics, schema drift, and PIT; each endpoint is separately admitted or rejected | Existing synchronization task remains the only caller; no fallback selected by CLI/Web | Existing snapshot path only; source authority remains `structured_aggregator`/secondary and cannot satisfy official coverage | No upstream recommendation/target/rating fields enter the view | Delete caller-owned parsers, generic Skill executor, and any duplicate cache; delete every unqualified endpoint branch rather than keeping fallback code | Auxiliary only. No HKEXnews/issuer-IR path exists, and the upstream exposes recommendation/target fields prohibited by local output policy |
| Global-stock-data recommendation, target-price, and rating fields | Local financial-output policy and typed view | Yahoo analyst recommendation/target fields exposed by the Skill | `reject` | None | No caller requests or maps these fields into a formal artifact | No schema column or source fact is created for action/rating output under default policy | Never rendered | Delete any mapping, fixture, UI element, or report field carrying these values | Violates the default financial-output boundary and is not needed for source qualification |
| Full historical strategy validation/backtest engine | No production implementation; acceptance explicitly says `not_applicable` | Vibe-Trading external backtest engine at pinned commit | `adopt-external` | This remains conditional on ticket 06 proving known-answer behavior, PIT/universe identity, no same-close look-ahead, train/test and Walk-Forward separation, adjustment/corporate actions, A-share rules, costs/slippage/unfilled events, seed reproducibility, bootstrap/Monte Carlo convergence, typed failures, artifact integrity, timeout/crash isolation, and a minimal allowlist. Failure of any required gate changes the later decision to `reject`, not a local fallback | A future **named complete application task** may call one production external adapter plus one deterministic fixture adapter. No CLI/Web direct MCP call and no adapter selector exposed to callers | A new typed artifact/migration would be required only after the result contract is proven. Raw upstream JSON, HTML, PDF, run directories, or caller-authored booleans never enter `WorkflowLedger` as authority | If decision-relevant, a versioned migration of the one local presentation model is required; upstream HTML/PDF is never embedded | Delete `full_trade_backtest:not_applicable` only in the same slice that supplies and verifies the replacement acceptance evidence. Delete all prototype launchers, raw-result readers, provisional schemas, and duplicate local runners. There is no current production backtest engine to retain | Candidate only, not qualified. Adoption means the external engine becomes the single production implementation; `temporary-both`, local fallback, and shadow execution are forbidden |
| Deterministic strategy-validation fixture/in-memory behavior | None | Vibe-Trading does not supply a local trust anchor suitable for repository tests | `keep-local` | Add only if the later strategy seam has the genuine production external adapter; it must implement observable request/result behavior, not mirror transport internals | Public-seam tests use it through the same application task | Fixture outputs are test data, not production ledger authority | No separate presentation | Delete private tests of transport internals once interface tests cover behavior; delete any fake that simply returns caller-authored success | A true external dependency requires an independently controlled deterministic adapter. This is not a second production path |
| Walk-Forward, bootstrap, and strategy-return Monte Carlo execution | No strategy validation module; valuation and market-path simulations already have separate semantics | Vibe-Trading `backtest/validation.py` and engine output | `adopt-external` | Only as part of the single qualified external strategy engine and typed strategy result, with explicit algorithm/version/seed/sample/fold identities and convergence evidence | Same future named strategy task; no standalone caller-facing Monte Carlo command | Persist only typed strategy-validation results and hashes, not numpy/free JSON or upstream run cards as authority | Render only a locally projected strategy-evidence section if the canonical view is versioned | Delete any locally duplicated production WFA/bootstrap/return-MC implementation and every generic “simulation” mapping to valuation artifacts | This simulates strategy returns, not company drivers, intrinsic value, or the existing market-price-path artifact |
| Vibe run card and artifact hashes as external evidence | Current ledger validates local typed identities/content hashes | Vibe `run_card.json`/Markdown and artifact hashes | `adapt-code` | Ticket 06 must show that engine identity, code/config/data/fold/seed identities and every authoritative artifact are bound and tamper-detected. Local code must independently validate, not trust, the upstream card | Adapter translates a minimal result into local typed evidence; callers never parse run-card files | Only validated fields/hashes are persisted in the local schema | Audit appendix may show validated identity summaries only | Delete raw run-card parser use outside the adapter and delete copied upstream Markdown from formal artifacts | Upstream cards are useful protocol knowledge but are not themselves sufficient proof or a local formal result |
| Vibe HTML/PDF report and full Web UI | Existing `ResearchDecisionView@2` -> canonical JSON/HTML/Web/XLSX | Vibe report renderer, Shadow Account report, and React frontend | `reject` | None | No caller opens or embeds the upstream app/report | No parallel report store or upstream HTML/PDF blob becomes a numeric source | Current local view remains sole presentation model | Delete copied frontend assets, iframe/report links, upstream template/render code, and report persistence | Would create a parallel Web/report model and expose unvalidated free text/numbers |
| Vibe Shadow Account, paper/simulated execution, trade journal to execution, signal scanning | Current trade plans record user rules only and explicitly perform no trade execution | Vibe Shadow Account and simulated-order lifecycle | `reject` | None | No application task, CLI command, Web action, or scheduled job | No shadow-account/order/fill store | No simulated positions/orders UI | Delete every shadow account, simulated order, fill, paper broker, or order-lifecycle symbol/config/schema/test introduced by a prototype | The Goal permanently excludes both live and simulated orders, brokers, and order lifecycle; strategy validation is historical research, not execution |
| Vibe broker connectors, live trading, place/cancel order | Runtime inventory currently rejects broker/order/execution public symbols | Vibe internal broker SDK/MCP connectors and `trading_place_order`/`trading_cancel_order` tools | `reject` | None | No caller, transport, credential, profile, mandate, kill switch, or OAuth flow | No account secret, broker profile, order, fill, or audit ledger from Vibe | No broker/order controls | Delete all broker dependencies, connector configs, credentials, routes, commands, schemas, tests, and docs if ever introduced | Explicitly out of scope and materially violates local privacy and no-execution boundaries |
| Vibe general `read_file`, `write_file`, `edit_file`, document import | Current application tasks receive typed inputs and own controlled persistence | Vibe file/document tools and configurable roots | `reject` | None | Not included in any MCP/tool allowlist | External process gets only an isolated task input/artifact directory if later adopted; never repository/data-root/home access | None | Delete all general file tool registrations and broad mount/path configuration | An external engine must not read the repo, personal data root, account snapshots, secrets, or arbitrary paths |
| Vibe arbitrary URL reading, Web search, market-data discovery, remote MCP federation | Current providers use explicit network authorization and source policy | Vibe `read_url`, `web_search`, 23 loaders, and dynamically configured MCP servers | `reject` | None for the strategy-validation process. Frozen data must be supplied by tradingSystem | Adapter receives a frozen local input contract; it cannot discover/fallback to providers or remote tools | No external cache, provider attempt, or discovered data is accepted | None | Delete URL/search tools, loader registrations, remote MCP config, network credentials, proxy forwarding, and network fallback from the adopted process image/allowlist | Strategy validation must use the frozen local snapshot. Arbitrary egress would bypass provider policy, rights, PIT, and provenance |
| Vibe persistent memory, sessions, hypotheses, goals, strategy store, user skills | Current workflow/ledger owns typed lifecycle and immutable artifacts | Vibe `~/.vibe-trading` memory/session/goal/hypothesis/strategy stores and skill writers | `reject` | None | No application caller delegates lifecycle/state to Vibe | No Vibe database, home volume, memory, goal, skill, or strategy store | None | Delete/mask all persistence paths and tools from the adopted deployment; provide an ephemeral per-run home | Would create parallel persistence and leak repository/personal context |
| Vibe swarm, Agent, LLM providers, channels, autopilot, shell/background subprocess tools | Business runtime has no LLM; Codex is control plane | Vibe Agent/LLM/swarm/channels/autopilot; opt-in `bash`/`background_run` | `reject` | None | Adapter invokes only an allowlisted deterministic validation operation; no generic tool registry | No Agent traces, channel data, swarm runs, prompts, or generated skills | None | Delete/exclude Agent, provider, channel, swarm, autopilot, shell, background-run, skill-writer, and remote-MCP packages/config from the adopted runtime surface | Runtime LLMs and general orchestration violate the control-plane boundary; shell/background tools are RCE surfaces |
| Company valuation simulation and market-price-path simulation | Local deterministic typed engines/artifacts with PIT, calibration, correlation, seed, convergence, lineage, and fail-closed gates | Vibe strategy-return simulation | `keep-local` | No substitution; external strategy diagnostics may only coexist as a separately typed strategy artifact after qualification | Existing research callers unchanged | Existing `Simulation` and `MarketPathSimulation` kinds remain semantically exclusive | Existing valuation/market-path sections remain sourced locally | Delete any adapter mapping Vibe results into current simulation kinds and any shared generic simulation dispatcher | Strategy return/bootstrap paths answer a different domain question and cannot replace enterprise/equity value uncertainty or current market paths |

## Deletion-test results

The deletion test is applied to the proposed shape, not to imagined file counts:

1. **Public Equity Investing control-plane comparison earns no production
   module.** Deleting the comparison workflow should remove only a Codex-side
   evaluation aid; no business behavior may reappear in application callers.
   A runtime wrapper would therefore be shallow and is rejected.
2. **Qualified endpoint adapters can earn depth only by owning a complete
   external protocol translation**: request/auth/pagination, response parsing,
   provider-specific failure/empty/partial semantics, source time/provenance,
   and deterministic fixtures. If deleting an adapter merely moves a few HTTP
   calls into `DataSyncService`, it was shallow. The correct response is to
   delete it, not preserve it as a wrapper.
3. **A qualified external strategy adapter can earn depth** only if deletion
   would force transport isolation, input packaging, timeout/crash handling,
   schema/identity/lineage verification, artifact hashing, and typed failure
   translation into multiple callers. If it merely launches Vibe and republishes
   JSON, it fails the deletion test.
4. **The future application task must own a complete user/application
   operation**, including frozen-input policy and local result acceptance. If
   deleting it only moves one adapter call into CLI/Web, it is a mirrored
   facade and must be deleted.
5. **The deterministic fixture adapter is a test adapter, not a fallback.**
   Deleting it would duplicate deterministic scenarios across interface tests,
   so it can earn its place. It must never be selected in production.
6. **Upstream presentation, storage, Agent, file, Web/search, memory, swarm,
   and broker modules fail the local deletion test.** Removing them removes
   unwanted capability; it does not force required strategy-validation
   complexity into callers. They must stay absent.

## Atomic caller, persistence, and presentation implications

No production interface is locked here. If later tickets prove adoption, the
implementation issue must still switch the complete slice atomically:

- one statically composed named application task, never a service locator or
  caller-selected adapter;
- one production external strategy adapter and one deterministic test adapter;
- frozen data supplied from the existing immutable snapshot path;
- typed request/result and typed external failure;
- one-way schema/artifact-lineage migration, with no old runtime reader;
- CLI/Web callers migrated only if the user task requires them;
- the one local presentation model versioned and every JSON/HTML/Web/XLSX
  consumer migrated together;
- `full_trade_backtest:not_applicable` removed only when replacement acceptance
  evidence exists;
- all prototypes, raw JSON/run-card readers, duplicate runners, upstream
  reports, upstream stores, general tools, and excluded dependencies removed in
  the same slice.

There is no permissible `temporary-both`, `legacy-fallback`,
`prefer-new-else-old`, shadow write, dual read, or generic adapter registry.

## Ticket boundaries left open

- Tickets 03–06 still own black-box/plugin, endpoint, and Vibe qualification.
  A candidate `adapt-code` or `adopt-external` row above is not proof that its
  conditions pass.
- Ticket 07 still owns the actual deep-module interface decision. This asset
  does not choose method names, request fields, result fields, adapter transport,
  artifact kind/version, or view schema.
- Rights remain unresolved for every aggregator endpoint and hosted commercial
  provider. MIT/Apache code licenses do not grant data rights.
- Vibe-Trading becomes `reject` rather than gaining a local fallback if its
  required adversarial gates fail.
