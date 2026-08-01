# Research Decision Output Projection

> Active projection reference, not a second runtime schema. The formal
> presentation contract is `ResearchDecisionView@2`; do not create a standalone
> brief, validator-owned result, or parallel renderer contract.

## Wired canonical boundary

The formal research route persists one lineage-checked bundle containing typed
Forecast, ScenarioValuation, valuation-method routing,
ValuationSimulationDecision, MarketPathDecision, and RecentTrendAssessment. It
projects the same DecisionView to JSON, HTML, PDF, and one typed workbook slot.
`trade_plan.prepare_draft@1` is the separate application-owned report-to-plan
seam. It accepts only a user-readable account alias, security code, plan style,
and request time. The application selects current research, trend, account,
risk, and strategy authorities; callers never submit authority identities,
quantities, or a `TradePlanGraph`.

Consumers inspect the persisted manifest and each component's typed status. A
method that cannot run is `limited`, `not_run`, or `blocked`; its output must
not be inferred from the existence of standalone code.

## Canonical pipeline

```text
Tushare-compatible Frozen DataSnapshot
  -> ResearchInputOrigin classification
  -> BoundedEstimate
  -> Forecast
  -> stress / base / improvement ScenarioValuation
  -> ValuationSimulationDecision
  -> MarketPathDecision
  -> CompleteResearchReport
  -> RecentTrendAssessment
  -> OPEN TradePlanDraft
  -> one explicit user confirmation
```

## Canonical status vocabulary

### Wiring status

`wired`

Every component in the canonical pipeline has one formal production seam.
Runtime applicability and evidence limits belong to the component status, not
to a second wiring path.

### Research input origin

`observed_official | observed_structured | derived | estimated | missing`

- Tushare-compatible data is `observed_structured`, with its actual gateway
  identity preserved.
- `estimated` always points to a `BoundedEstimate`.
- `missing` is not zero.

### Method status

`ready | limited | caution | blocked | disabled`

### Decision status

`ready | partial | not_run | blocked`

### Report disposition

`completed | completed_with_limits | blocked`

`source_manifest_status = valid_with_limits` maps to
`completed_with_limits`. Missing required official evidence or selected-method
inputs puts the dependent valuation section in `data_insufficient_memo`
disposition and withholds formal conclusions; the remaining research structure
stays present. `blocked` is reserved for global identity, PIT, rights,
provenance, reproducibility, or calculation-integrity failure.

### Valuation-view status

`ready | limited | unavailable | blocked`

This is the aggregate valuation view. Individual methods continue to use the
method-status vocabulary above.

### Data-quality grade

`A | B | C | D`

The grade summarizes evidence quality under the canonical runtime policy.
`limits` independently records the concrete coverage, estimation, method, or
projection constraints that affect interpretation. Do not encode limits as a
second grade, infer limits solely from the grade, or retain
another named grade scale.

## Required canonical projection

The canonical DecisionView contains the following sections. This is a field
requirement of the active presentation model, not an independently versioned
JSON schema.

```yaml
identity:
  security_id:
  as_of:
  data_snapshot_id:
  research_run_id:
  workflow_run_id:
  model_identity:
  policy_identity:
  code_identity:

wiring:
  forecast: wired
  scenario_valuation: wired
  valuation_simulation: wired
  market_path: wired
  xlsx_projection: wired
  recent_trend: wired
  trade_plan_draft: wired

report:
  disposition: completed | completed_with_limits | blocked
  source_manifest_status: sufficient | valid_with_limits
  data_quality_grade: A | B | C | D
  limits: []
  valuation_view:
  risk_reward_summary:
  key_uncertainties: []
  what_would_change_the_view: []

origin_ledger: []
bounded_estimates: []
forecast: {}
scenario_valuation: {}
valuation_simulation_decision: {}
market_path_decision: {}
recent_trend_assessment: {}
trade_plan_handoff: {}
audit: {}
boundary: {}
```

Every top-level target section must be present. When a stage does not run, its
object carries status and reason codes; it is not omitted or set to an
ambiguous empty value.

## Origin entry

```yaml
field_name:
subject_id:
period:
as_of:
value:
unit:
currency:
origin: observed_official | observed_structured | derived | estimated | missing
source_refs: []
available_at:
derived_from: []
estimate_id:
missing_reason:
```

Rules:

1. `observed_official` and `observed_structured` require source identity and
   PIT timestamps.
2. `derived` requires named operands and a formula identity.
3. `estimated` requires `estimate_id` and no claim of official coverage.
4. `missing` requires `missing_reason` and has no numeric value.
5. Presentation must preserve origin; it may not collapse all non-missing
   values into “fact”.

## Bounded estimate

```yaml
estimate_id:
field_name:
point:
lower_bound:
upper_bound:
unit:
currency:
period:
as_of:
estimator_identity:
estimate_policy_identity:
calibration_window:
calibration_sample_identity:
source_refs: []
confidence: high | medium | low
rationale:
invalidation_condition:
```

Bounds must be ordered and finite. The point must lie within the bounds. A
bounded estimate may support a conditional/limited method result but cannot
upgrade source authority or independently authorize a formal rating or target.

## Forecast and ScenarioValuation

Forecast records its horizon, drivers, origin mix, formulas, statement
reconciliations, limitations and artifact identity.

ScenarioValuation contains exactly `stress`, `base`, and `improvement` over the
same driver structure:

```yaml
probability_mode: conditional_only | evidence_weighted
scenarios:
  - role: stress | base | improvement
    driver_overrides: []
    forecast_summary: {}
    methods: []
weighted_method_ranges: []
```

With `conditional_only`, probability and weighted ranges are absent. With
`evidence_weighted`, all three probabilities require PIT-valid calibration and
sum exactly to one. Bull/Base/Bear aliases and default probabilities are not
allowed.

Each method result records role, status, applicability, observed/derived/
estimated/missing inputs, formula identity, conditional range, diagnostics and
conclusion permission (`formal | conditional_only | none`).

## ValuationSimulationDecision

The object always exists:

```yaml
status: ready | partial | not_run | blocked
reason_codes: []
deterministic_fallback: {}
simulation_result:
  model_identity:
  policy_identity:
  distributions: []
  dependency_model:
  constraints:
  rng_identity:
  seed:
  sample_budget:
  completed_samples:
  converged:
  invalid_path_rate:
  quantiles:
  tails:
```

`simulation_result` exists only when an actual formal simulation ran. A
non-converged result is `partial` and must withhold unstable quantiles.
`not_run` preserves the deterministic three-scenario fallback.

## MarketPathDecision

The object always exists and is separate from intrinsic value:

```yaml
status: ready | partial | not_run | blocked
reason_codes: []
interpretation: traded_price_uncertainty_only
market_path_result:
  market_data_snapshot_identity:
  adjustment_mode:
  trading_calendar_identity:
  state_model_identity:
  constraints:
  transaction_costs:
  rng_identity:
  seed:
  path_budget:
  horizon_return_quantiles:
  maximum_drawdown_quantiles:
  threshold_frequencies:
```

Do not substitute arbitrary GBM or describe market paths as target prices,
intrinsic value, or trading instructions.

## CompleteResearchReport

The report is structurally complete when it contains identity/wiring, decision
summary, origin ledger, bounded estimates/missing inputs, business/industry,
Forecast, three-scenario valuation, both simulation decisions, recent trend,
risks/monitoring, audit, financial boundary and trade-plan handoff.

A limited or blocked method remains visible in its section. A missing chart,
workbook, simulation, or official fact limits only the dependent projection or
method. Do not replace the report with a memo for `valid_with_limits`.

## RecentTrendAssessment and trade-plan handoff

Recent trend records the frozen observation window, adjustment convention,
benchmark, deterministic indicators, trend state, uncertainty and invalidation
conditions. It is neither a valuation nor a simulated path.

The handoff is returned only by `trade_plan.prepare_draft@1`. The Skill,
renderer, and workbook must not compose or submit a `TradePlanGraph`.

```yaml
trade_plan_handoff:
  status: open | not_created | blocked
  reason_codes: []
  trade_plan_draft_id:
  revision:
  content_hash:
  confirmation_challenge_id:
  confirmation_required: true
```

An `open` draft is not active. Present its readable final revision and diff,
then obtain one explicit user confirmation. Exact revision/challenge binding
remains an internal safety mechanism. A revised draft invalidates the old
challenge.

The wired drafting seam accepts a user-readable account alias, security code,
plan style, and request time. It resolves the latest complete research and bound
trend plus the confirmed account, risk policy, and active built-in strategy,
compiles and validates the graph, and persists one `OPEN` draft. A missing or
stale authority returns a typed `not_created` or `blocked` reason; callers never
supply a graph or pin an authority version.

## Projection and validation invariants

1. JSON, HTML/PDF and XLSX project the same canonical content.
2. Only persisted manifest members may be reported as produced.
3. XLSX recomputes formulas but cannot become a second valuation authority.
4. Every numeric field has an origin; every estimate has bounds and identity.
5. Every required section has a status, including `not_run` decisions.
6. Unknown is never zero and placeholders are prohibited.
7. Missing official critical inputs prohibit a formal target, rating or
   unqualified valuation conclusion, not the complete report structure.
8. Rating remains absent unless explicitly requested and every applicable
   source/method gate passes.
9. BUY/HOLD/SELL language, Chinese equivalents, target-price conclusions,
   personalized action advice and probability-weighted targets are prohibited
   by default.
