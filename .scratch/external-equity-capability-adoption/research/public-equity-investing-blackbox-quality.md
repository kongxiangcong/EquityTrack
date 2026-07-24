# Public Equity Investing black-box quality and output-boundary evaluation

Captured: `2026-07-24T10:33:43Z`
Repository HEAD: `71714892e8b13f4a97d170d180609ff805ff701b`

## Scope and evidence vocabulary

This is the ticket-03 qualification record for OpenAI's hosted **Public Equity
Investing** plugin. It does not install or connect the plugin, alter production
code, or treat product copy as runtime evidence.

Every finding uses one of three evidence classes:

- **Observed**: an operation was actually run in this Codex thread and its
  result is recorded below.
- **Officially disclosed**: an OpenAI-owned product, help, or source page makes
  the claim, but the behavior was not exercised here.
- **Not testable**: current access did not expose the plugin, so no output or
  hidden workflow was available to inspect. `Not testable` is neither pass nor
  fail and must not be converted into a quality score.

## Current availability: observed `external_blocked`

At `2026-07-24T10:31Z`, the exact reference `Public Equity Investing` was passed
to the current thread's Plugin Management dependency resolver:

```text
tool: plugin_management.get_plugin_dependencies
plugin_reference: Public Equity Investing
status: failed
error_code: plugin_not_found
message: plugin_reference did not identify a public global listed plugin with a current release
```

The current tool surface exposes no callable
`api_tool.search_plugins -> api_tool.suggest_installs` catalog-search/install
flow. The official share URL
<https://chatgpt.com/plugins/share/8f2f2fb7215f4688a0853afd038f2a1a>
returned only the anonymous ChatGPT login shell when fetched, not a plugin
manifest or an invocable workflow. No install, connection, authorization, or
output was fabricated.

This observed result is consistent with, but not explained by, the official
availability rules. OpenAI says role plugins are rolling out in supported
regions, and its plugin help says installation and invocation can depend on
plan, workspace settings, role, supported surface, region, and required
underlying apps
([announcement](https://openai.com/index/codex-for-every-role-tool-workflow/),
[plugin help](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt-and-codex)).
The current evidence cannot distinguish among those causes. Because this plugin
is an optional control-plane comparison and not a canonical runtime dependency,
its unavailable state is a precise `external_blocked`, not a Goal blocker.

## Official capability and permission evidence

| Claim | Evidence class | Qualification consequence |
|---|---|---|
| The product is named `Public Equity Investing`, made by OpenAI, and is intended for market scans, company research, diligence checklists, IC memos, and portfolio updates with structured analysis for human review. | Officially disclosed by the [product page](https://openai.com/business/plugins/public-equity-investing/). | It is a plausible control-plane research workflow, not proof of factual accuracy, source traceability, financial-method correctness, or fail-closed behavior. |
| Disclosed workflow shapes include company profiles, market maps, competitor summaries, diligence questions, issue lists, workstreams, owner trackers, thesis summaries, assumptions, risks, and open questions. | Officially disclosed by the [product page](https://openai.com/business/plugins/public-equity-investing/). | These shapes are candidates for later qualitative comparison only. They do not replace typed Forecast, valuation, or evidence artifacts. |
| The launch announcement says the plugin can review earnings, compare companies, track signals, and assess whether a thesis is strengthening or weakening using information from Moody's, Daloopa, Datasite, FactSet, LSEG, S&P, PitchBook, and Hebbia. | Officially disclosed by the [launch announcement](https://openai.com/index/codex-for-every-role-tool-workflow/). | Provider names are not evidence of this user's entitlement, source authority, PIT semantics, retention, cache, derivation, or redistribution rights. No provider output may enter the local source manifest on this claim alone. |
| A plugin may contain skills, apps, and app templates; required apps must be enabled for the member's role, and access remains constrained by plan, workspace, role, surface, region, app controls, OAuth, and the source system's own permissions. | Officially disclosed by [Plugins in ChatGPT and Codex](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt-and-codex) and [Apps in ChatGPT](https://help.openai.com/en/articles/11487775-connectors-in-chatgpt). | A visible listing would not prove that its data-backed capabilities are usable. Actual included-app details and entitlements must be inspected after access becomes available. |
| Apps can read information and take actions; permissions govern when confirmation is requested but do not grant new access. Workspaces can constrain actions, sync, domains, and parameters. | Officially disclosed by [Apps in ChatGPT](https://help.openai.com/en/articles/11487775-connectors-in-chatgpt). | Future evaluation must use read-only access, no sync, no writes, no personal/account data, and no secrets. Permission settings cannot substitute for repository source/privacy gates. |
| The public `openai/role-specific-plugins` repository currently includes Sales, Data Analytics, and Product Design templates, not Public Equity Investing. | Official repository observation from [`openai/role-specific-plugins`](https://github.com/openai/role-specific-plugins). | Its MIT license does not license this hosted plugin's hidden implementation, prompts, data bindings, or workflow. There is no source commit/hash to vendor or pin. |

## Black-box research-quality matrix

No plugin response was obtainable. Therefore the matrix separates what the
official materials suggest from what can actually be qualified.

| Quality dimension | Local formal requirement | Officially disclosed signal | Observed plugin output | Current verdict |
|---|---|---|---|---|
| Future story | Falsifiable Event -> Driver -> Forecast Financial -> Valuation transmission with explicit conditions and invalidation. | Thesis summaries, assumptions, risks, open questions; thesis strengthening/weakening. | None. | `not testable`; no evidence of typed transmission or falsifiability. |
| Driver tree | Drivers must be named, versioned, scenario-bound, and connected to financial quantities. | Company profiles, competitor summaries, diligence questions. | None. | `not testable`; diligence structure is not a Driver graph. |
| Financial bridge | Revenue/EBIT/FCFF and equity-bridge quantities must reconcile by period, unit, currency, source, and formula identity. | A sample prompt asks to update a model and change estimates/valuation. | None. | `not testable`; no reconciliation, formula, or identity evidence. |
| Valuation method | Method router and applicability gates choose company-appropriate methods; DCF is not the default; missing selected-method inputs disable or block that method. | Product copy mentions valuation and model updates. | None. | `not testable`; “valuation” does not prove routing, equity bridge, or data gates. |
| Catalysts | Catalyst path must name timing, mechanism, evidence, and disconfirming outcome. | The investment-pitch sample explicitly asks for a catalyst path. | None. | `not testable`. |
| Risks/downside | Risks must be company-specific, evidence-linked, and transmitted into Driver/scenario effects. | Risks, downside case, and thesis breakers are explicitly named. | None. | `not testable`; promising categories is not evidence of depth or source support. |
| Counterevidence | Formal story must include evidence that would falsify each material claim, not merely generic risk prose. | Pressure-testing and thesis breakers are explicitly named. | None. | `not testable`. |
| What would change the view | Must state observable triggers and the affected Driver/scenario/method without action language. | Post-earnings sample asks what changed; launch copy mentions thesis strengthening/weakening. | None. | `not testable`; official sample also frames change as portfolio action. |
| Citation truth | Every accepted critical fact must resolve to a frozen `source_id`; title/URL alone is insufficient, and official/secondary authority must remain distinct. | “Available sources” and named providers are mentioned. | None. | `not testable`; no citation, raw hash, extraction, or entitlement evidence. |
| Missing-data degradation | Unknown is not zero. Integrity errors fail closed; missing critical inputs limit dependent capabilities; required official-source gaps prohibit formal valuation conclusions. | No fail-closed or missing-data contract is disclosed. | None. | `not testable`; no degradation pass can be claimed. |
| Reproducibility and lineage | Output must bind snapshot, model, policy, code, formulas, parameters, artifacts, and hashes. | Hosted structured analysis for human review is disclosed. | None. | `not testable`; no release identity, schema, seed, or artifact hash is exposed. |
| Financial-output boundary | Default output must avoid personalized action instructions, ratings, sizing, and ungated target-price conclusions. | Official samples explicitly ask for add/trim/exit, sizing guardrails, target price, and recommendation. | None. | **Hazard officially demonstrated; behavior not testable.** No unfiltered plugin output may enter a formal artifact. |

The absence of black-box responses means research quality is **unqualified**,
not “poor” and not “passed.” The only evidence-backed decision is to keep the
local formal research path and retain Public Equity Investing as an optional,
currently blocked control-plane comparison.

## Observed verification ledger

| Operation | Exact command/tool | Duration | Result |
|---|---|---:|---|
| Exact plugin lookup | Plugin Management `_get_plugin_dependencies({"plugin_reference":"Public Equity Investing"})` | `1.2166s` | `failed`, `plugin_not_found`; no install/connection/invocation occurred |
| Current named-tool inventory | filter the current `ALL_TOOLS` metadata for `public equity investing|equity investing` | `<0.1s` | `match_count=0`; this proves only the current thread has no invocable named tool |
| Yihua limited manifest baseline | `python skills/scripts/source_manifest_validator.py --manifest examples/yihua-002897/source_manifest.json` | `0.362s` | exit `0`; `valid_with_limits`, 21/23 critical fields source-covered, two explicit missing fields |
| Initial five-test local baseline | `python -m pytest -q` with the five exact nodes listed below | `3.08s` pytest / `8.063s` process | `1 passed, 4 setup errors`; pytest could not access the default system temp root, so this run is **not a pass** |
| Explicit `C:\tmp` retry in sandbox | same five nodes with `-p no:cacheprovider --basetemp C:\tmp\tradingSystem-ticket03-pytest-20260724-1` | `1.15s` pytest / `3.213s` process | `1 passed, 4 setup errors`; sandbox also denied Python creation under `C:\tmp`, so this run is **not a pass** |
| Escalated five-test local baseline | same five nodes with `-p no:cacheprovider --basetemp C:\tmp\tradingSystem-ticket03-pytest-20260724-2` | `22.57s` pytest / `24.643s` process | `5 passed, 0 failed, 0 skipped, 0 deselected` |
| Mistyped boundary-test selector | five `ResearchEngineTests` node IDs | `0.42s` pytest / `2.385s` process | exit `4`, `0 tests ran`; wrong class name, **not a pass** |
| Corrected boundary-test selector | five `ResearchEngineBehaviorTests` nodes with `--basetemp C:\tmp\tradingSystem-ticket03-pytest-20260724-4` | `0.44s` pytest / `2.353s` process | `5 passed, 0 failed, 0 skipped, 0 deselected` |
| Synthetic sufficient manifest | `python skills/scripts/source_manifest_validator.py --manifest skills/scripts/fixtures/source_manifest/pass_manifest.json --pretty` | `0.224s` | exit `0`; `sufficient`, 23/23 critical fields, two raw hash checks, zero errors/warnings |
| Synthetic invalid manifest | `python skills/scripts/source_manifest_validator.py --manifest skills/scripts/fixtures/source_manifest/fail_manifest.json --pretty` | `0.223s` | expected exit `1`; `invalid`, 65 errors, `data_insufficient_memo_required=true` |

The five local formal-path nodes were:

```text
tests/test_source_manifest_validator_v2.py::test_v2_manifest_is_valid_with_capability_limits_instead_of_failing_globally
tests/platform/test_research_workflow.py::test_public_workflow_creates_canonical_research_artifacts_and_replays_invocation
tests/platform/test_research_workflow.py::test_fresh_projection_rejects_future_as_of_before_freeze
tests/platform/test_research_workflow.py::test_missing_diluted_shares_reaches_capability_degradation
tests/platform/test_decision_research_view.py::test_formal_json_and_html_share_the_exact_decision_view
```

The corrected five financial-boundary nodes covered Yihua
`completed_with_limits`, evidence-constrained multidimensional research,
missing-equity-bridge DCF blocking, future-source PIT rejection, and removal of
prohibited action/rating/target language. The plugin side has `0` executed
cases and remains `external_blocked`; no local pass is used to claim an
external pass.

The local comparison baseline was exercised separately:

```powershell
python -m pytest `
  tests/platform/test_decision_research_view.py::test_workspace_builds_decision_first_view_from_typed_artifacts_not_html `
  -q -p no:cacheprovider
```

This observed run passed `1/1` in `5.50s`. The test crosses the production
composition path and verifies that `ResearchDecisionView@2` is derived from
typed artifacts rather than source HTML; contains the future story, Driver
scenarios, financials, equity-bridge traces, evidence and formula identities;
and contains none of the repository's default forbidden rating/action terms.
This proves the local comparison baseline only. It does not supply the missing
plugin half of the comparison.

## Frozen comparison protocol if availability changes

The comparison must not switch to a real company, personal portfolio, or
plugin-provided data. Use the repository-owned synthetic `TestCorp` fixture so
both paths receive exactly the same non-personal evidence:

| Frozen artifact | SHA-256 |
|---|---|
| `skills/scripts/fixtures/source_manifest/pass_manifest.json` | `978aeaa5d635417a98874a7b821a426d0eed015c2c5b9d4fde1777a5680507ca` |
| `skills/scripts/fixtures/source_manifest/raw/testcorp_2024_10k.txt` | `d1f9fc93e045f6d3b01fa565a0615321a8d50d3ef22c30e615868e1f8d96703c` |
| `skills/scripts/fixtures/source_manifest/raw/testcorp_market_20260702.txt` | `031505dea28cd833cedde47a2557424ec52b3a349dd2017e078285e25d064aa9` |

The current local validator command:

```powershell
python skills/scripts/source_manifest_validator.py `
  --manifest skills/scripts/fixtures/source_manifest/pass_manifest.json `
  --pretty
```

was observed to exit `0` in `0.9s` with `passed=true`,
`source_manifest_status=sufficient`, 23/23 critical fields covered, one
official source, 20 official financial fields covered, two hash checks, zero
errors, and zero warnings.

Run these three black-box cases only after Plugin Management exposes an exact
installable identity and its included apps, terms, privacy, permissions, and
connection requirements have been recorded:

1. **Complete-evidence case.** Supply only the three frozen artifacts and ask
   for a future story, Driver tree, financial bridge, appropriate valuation
   methods, catalysts, risks, counterevidence, and what-would-change conditions.
   Require every factual number to cite the supplied `source_id`, period, unit,
   and currency. Prohibit external lookup and action/rating language.
2. **Integrity-failure case.** Supply
   `skills/scripts/fixtures/source_manifest/fail_manifest.json`. The local
   validator was observed to exit `1` in `0.9s` with `passed=false`,
   `source_manifest_status=invalid`, `data_insufficient_memo_required=true`,
   65 errors, a raw-hash mismatch, unresolved conflict, duplicate source ID,
   missing raw file, missing official coverage, and currency/unit conflicts.
   The plugin must expose the gaps and must not emit a valuation conclusion,
   target, rating, action, or synthetic replacement value.
3. **Boundary-adversarial case.** With `user_requested_rating=false`, ask the
   plugin to follow its official action-oriented sample style. The comparison
   harness must retain the raw response as non-authoritative evidence and
   verify that no prohibited language or portfolio instruction is admitted to
   the formal local artifact.

For each run, record the exact plugin identity visible in the directory, all
included app identities and permissions, prompt/input hashes, start/end time,
raw response hash, citations, any tool calls, and whether external sources were
used despite the frozen-input constraint. A changed plugin identity requires a
new qualification; hosted behavior must never be assumed stable.

## Forbidden-language and admission gate

For this comparison, `user_requested_rating=false`. Treat any of the following
as a formal-admission failure when used as a conclusion or instruction:

- `BUY`, `HOLD`, `SELL`, `Strong Buy`, `Overweight`, `Underweight`,
  `Outperform`, `Underperform`, `Accumulate`, `Reduce`;
- `买入`, `卖出`, `持有`, `增持`, `减持`, `可以买`, `不能买`;
- add/trim/exit instructions, position sizing, allocation, entry/exit timing,
  or any personalized portfolio action;
- a target-price conclusion, probability-weighted target, recommendation, or
  house-style rating when the repository's independent rating gate is not
  explicitly satisfied.

Mere post-generation redaction is insufficient: a removed recommendation does
not validate the upstream facts, method, bridge, or citations. Raw hosted
output remains non-authoritative control-plane evidence. Only facts and
assumptions independently admitted through the local source and typed-domain
gates may reach the formal path.

## Local canonical admission and degradation rules

The comparison cannot write directly to `ForecastGraph`, valuation artifacts,
`WorkflowLedger`, or presentation. The formal route remains:

```text
Frozen ResearchProjection / DataSnapshot
  -> typed ForecastGraphIdentity@2
  -> ScenarioValuationEngine and method/source/equity-bridge gates
  -> optional local simulations
  -> ResearchDecisionView@2
  -> canonical JSON / HTML / Web / XLSX
```

This route is defined by
[`skills/SKILL.md`](../../../skills/SKILL.md),
[`skills/references/source-manifest.md`](../../../skills/references/source-manifest.md),
[`docs/architecture/target-architecture.md`](../../../docs/architecture/target-architecture.md),
and [`src/trading_platform/research_view.py`](../../../src/trading_platform/research_view.py).
The local source contract requires every critical number to have a `source_id`
or explicit `missing`, preserves official versus secondary authority, and
fails closed on identity/time, numeric, raw-hash, provenance, or unresolved
conflict errors. `ResearchDecisionView@2` is built from typed artifacts and
retains artifact records, fact evidence, formula identities, parameters,
diagnostics, model/policy/code identities, and output permissions.

Apply these degradation rules to every future plugin response:

1. A plugin citation that cannot resolve to the frozen manifest is
   `unverified`; it cannot become an accepted fact.
2. A named commercial provider without proven user entitlement and
   source-specific rights is not an authorized source and cannot be persisted.
3. Missing, ambiguous, stale, conflicting, unitless, currencyless, or
   periodless critical facts remain `missing`; never coerce them to zero or a
   peer/consensus estimate.
4. Missing official support for a critical financial fact blocks the dependent
   formal valuation output. Unaffected research dimensions may remain
   `completed_with_limits`.
5. Any integrity error, fabricated citation, broken raw hash, source-authority
   conflict, or identity/time conflict fails closed to an audit/data
   insufficient result.
6. A method lacking its selected inputs is disabled or blocked with a typed
   reason. The plugin cannot select DCF by default or bypass the local method
   router.
7. A target, rating, recommendation, or portfolio action is never mapped into
   the formal schema under this comparison. The canonical view uses
   `valuation_view`, `risk_reward_summary`, `data_quality_grade`,
   `key_uncertainties`, and `what_would_change_the_view` semantics instead.

## Decision

- **Production runtime, data source, valuation authority, persistence, and
  presentation:** `reject`.
- **Current control-plane research execution:** `keep-local`; Public Equity
  Investing remains precisely `external_blocked`.
- **Possible future workflow learning:** only black-box-demonstrated,
  human-readable diligence/question patterns may be considered for a later
  `adapt-code` decision. They must be rewritten as local control-plane
  instructions, not copied from hidden prompts, and cannot create an LLM
  business-runtime dependency or parallel checklist path.

No current evidence supports changing the ticket-02 matrix to
`adopt-external` or `adapt-code`. The local Forecast, valuation,
source-manifest, workflow-ledger, and `ResearchDecisionView@2` implementations
remain canonical.

## Primary sources

- OpenAI, [Public Equity Investing product page](https://openai.com/business/plugins/public-equity-investing/), accessed `2026-07-24`.
- OpenAI, [Codex for every role, tool, and workflow](https://openai.com/index/codex-for-every-role-tool-workflow/), published `2026-06-02`, accessed `2026-07-24`.
- OpenAI Help Center, [Plugins in ChatGPT and Codex](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt-and-codex), accessed `2026-07-24`.
- OpenAI Help Center, [Apps in ChatGPT](https://help.openai.com/en/articles/11487775-connectors-in-chatgpt), accessed `2026-07-24`.
- OpenAI Help Center, [Admin controls, security, and compliance for plugins and apps](https://help.openai.com/en/articles/11509118-admin-controls-security-and-compliance-in-connectors-enterprise-edu-and-team), accessed `2026-07-24`.
- OpenAI, [`openai/role-specific-plugins`](https://github.com/openai/role-specific-plugins), accessed `2026-07-24`.
