# Valuation Method Router

Use this router before every valuation. Model-enabled depth does not imply DCF,
Monte Carlo, or a formal valuation conclusion.

The formal `ResearchWorkflow` persists the typed Forecast,
ScenarioValuation, valuation-simulation decision, and market-path decision.
Inspect the persisted manifest and preserve each method's `limited`, `not_run`,
or `blocked` reason rather than claiming it ran.

## Inputs

```yaml
security_id:
as_of:
industry:
business_model:
company_archetype:
lifecycle: mature | growth | early | pre_revenue | cyclical | distressed
profitability: profitable | near_break_even | loss_making
cash_flow_stability: stable | volatile | negative | not_meaningful
source_manifest_status: sufficient | valid_with_limits
analysis_plan_identity:
capability_binding_status: bound | limited
capability_reason_codes: []
origin_coverage:
  observed_official: []
  observed_structured: []
  derived: []
  estimated: []
  missing: []
estimate_policy_identity:
data_quality_grade: A | B | C | D
user_requested_rating: true | false
```

The Tushare-compatible gateway belongs to `observed_structured`; it is not an
official filing source. Every `estimated` input must satisfy the bounded-
estimate contract below.

Formal model quantities may be consumed only from frozen
`research_model_input` members whose subject, exact model path/field name,
`typed_research_model_input` semantic role, period, unit and currency all
match. A same-named path on another dataset is not a model input. Malformed or
legacy direct evidence limits the dependent model; it does not authorize a
fallback reader.

The grade uses the canonical runtime `A | B | C | D` vocabulary. Method/report
limits remain explicit and independent; the router must not encode them as a
second quality scale.

## Outputs

```yaml
valuation_method_router_result:
  report_disposition: completed | completed_with_limits | blocked
  methods:
    - method:
      role: primary | secondary | cross_check
      status: ready | limited | caution | blocked | disabled
      reason_codes: []
      observed_inputs: []
      estimated_inputs: []
      missing_inputs: []
      conclusion_permission: formal | conditional_only | none
  scenario_partition: stress_base_improvement
  probability_mode: conditional_only | evidence_weighted
  valuation_simulation_decision:
    status: ready | partial | not_run | blocked
    reason_codes: []
  market_path_decision:
    status: ready | partial | not_run | blocked
    reason_codes: []
```

Every candidate method must appear exactly once. Do not remove a method merely
to hide missing data.

## Report-level gates

Use `blocked` only when a global identity, PIT, rights, provenance,
reproducibility, or calculation-integrity failure makes the run untrustworthy
as a whole.

`source_manifest_status = valid_with_limits` produces a structurally complete
report whose affected facts and methods carry explicit limits. Missing required
official evidence or selected-method inputs makes the dependent valuation
section a `data_insufficient_memo`; it does not authorize a formal valuation
conclusion, target, or rating. In particular:

- missing official financial coverage prevents a formal target, rating, or
  unqualified per-share valuation conclusion, but does not suppress business
  analysis, Forecast, conditional scenarios, bounded estimates, recent trend,
  or unaffected valuation methods;
- a missing critical input blocks or limits only methods that depend on it;
- fewer than three source-compatible peers blocks the comps conclusion only;
- a failed or non-converged simulation leaves the deterministic three-scenario
  valuation intact;
- unavailable market-path calibration does not erase intrinsic-value analysis.

Unknown is never zero. `missing` remains a first-class origin.

## Bounded-estimate contract

A `BoundedEstimate` is eligible only when all of the following are present:

- estimator and policy identity;
- frozen source inputs or a versioned prior;
- calibration window and as-of date;
- point, lower bound, upper bound, unit, currency, and period;
- rationale, confidence, and invalidation condition;
- no future information relative to the research cutoff.

Prefer, in order, company historical distributions, segment/driver history,
source-compatible peer or industry distributions, then an explicit user
assumption. Do not silently invent a scalar, use zero as a placeholder, or let
an estimate claim official origin. A bounded estimate may support a `limited`
conditional range; it cannot independently authorize a formal rating or target.

## Assumption challenge review (target migration)

As a research-review discipline, every material judgment used by a selected
method should record:

- supporting evidence and source refs;
- counter-evidence;
- a falsifier or observable invalidation condition;
- bounded stress/base/improvement values and dimensions;
- what evidence would change the view.

The current runtime can preserve rationale, bounds and invalidation conditions,
but it does not yet enforce a complete typed dossier or a release receipt across
all DecisionViews. Dossier completeness is therefore a review item and target
migration acceptance, not a current fail-closed router gate. Record missing
members as review gaps and let the existing source/PIT, official-evidence,
typed-input, applicability and method-math gates determine runtime permission.
Neither current nor target handling may silently promote a formal conclusion,
target or action recommendation.

## Method rules

| Company archetype | Preferred methods | Disabled or caution methods | Minimum method gate |
|---|---|---|---|
| Financial institution | P/B x ROE/COE, DDM, residual income, excess return | Ordinary FCFF/WACC DCF, EV/EBITDA | Book value, regulatory capital, ROE/COE, payout and institution operating metrics |
| Pre-revenue or pipeline biopharma | rNPV, pipeline SOTP, transactions, cash runway | Ordinary consolidated DCF, PE, unsupported PS | Asset/indication rights, event probabilities, economics and financing runway |
| Mature non-financial | DCF when gated, PE/PEG, EV/EBITDA, historical band | DCF with unstable FCFF or incomplete bridge | Forecast cash flow, diluted shares, net debt and selected-method inputs |
| Cyclical manufacturing or resource | Mid-cycle EV/EBITDA, P/B, NAV, finite resource value, historical cycle band | Peak-cycle DCF, current commodity price perpetuity | Cycle-normalized price/volume/cost and capacity/reserve evidence or bounded estimates |
| Multi-segment | SOTP plus segment-appropriate cross-checks | One blended multiple without segment reconciliation | Segment forecast, bridge and non-overlapping economic rights |
| Real estate | NAV/RNAV, project cash flow, P/B, dividend yield | Consolidated FCFF without project/debt detail | Land/project inventory, sell-through, ASP/cost and debt maturity |
| SaaS/software | EV/Sales, Rule of 40, ARR/NRR, mature FCF DCF when gated | DCF ignoring SBC/dilution; PS without retention economics | ARR, retention/churn, CAC payback, SBC and margin path |
| Internet platform | SOTP, EV/GMV, EV/EBITDA, mature-platform PE | MAU-only or GMV-only valuation | Activity, GMV, take rate, segment profit and regulatory constraints |
| Semiconductor | Subsector PE/PEG, EV/EBITDA, P/B, cycle-normalized methods | DCF without cycle/inventory/capex normalization | ASP, shipments, utilization, inventory, backlog and capex |
| Consumer | PE/PEG, EV/EBITDA, gated mature-company DCF | PS-only or unsupported high-growth DCF | Price/volume, channel, margins, inventory and brand/customer evidence |

## DCF routing

Read `valuation/dcf-and-sensitivity.md` only when ordinary DCF is selected or
the user explicitly requests its applicability assessment. Return exactly one:

- `allowed`: complete cash-flow forecast, WACC inputs and equity bridge;
- `caution`: calculation is reproducible but material bounded estimates limit
  interpretation;
- `disabled`: the company archetype or missing bridge makes ordinary DCF
  inappropriate.

Financial institutions disable ordinary FCFF/WACC DCF. Pipeline biopharma
routes to rNPV/SOTP first. Cyclical/resource companies use normalized or finite-
life economics rather than peak-price perpetuity.

## Scenario valuation

Build exactly `stress`, `base`, and `improvement` over the same driver
structure. Do not use Bull/Base/Bear aliases.

If probability evidence is absent, set `probability_mode = conditional_only`
and do not calculate a probability-weighted value. If probability evidence is
PIT-valid and complete, all three probabilities must exist and sum exactly to
one. Never assign a default base probability.

## Valuation Monte Carlo applicability

Every report includes a decision. Run Monte Carlo only when all are frozen:

- at least one deterministic valuation anchor;
- material uncertain drivers with explicit bounded distributions;
- calibration samples and a dependency matrix, or a versioned explicit
  override;
- dimensional valuation formula, constraints, RNG identity, seed and budget;
- convergence and invalid-path gates.

Otherwise return `not_run` with reason codes and the deterministic fallback.
Return `partial` when the declared convergence gate is not met and withhold
unstable stochastic quantiles. Monte Carlo is never a device for filling
missing fundamentals.

## Market-path applicability

Every report includes a separate decision. Run only with PIT-valid adjusted
OHLCV, trading-calendar identity, A-share execution constraints, current market
state, transaction costs, RNG identity, seed, path budget, and enough
state-conditioned contiguous historical blocks. Prefer state-conditioned block
bootstrap; never insert arbitrary GBM parameters.

Market paths describe traded-price uncertainty. They are not intrinsic value,
a target price, a rating, or a trading instruction.

## Output boundary

`completed_with_limits` still renders the complete report structure. Show source
gaps, disabled-method reasons, bounded estimates, simulation decisions, recent
trend, and next evidence requirements in their relevant sections instead of
replacing the report with a memo.

Never output BUY/HOLD/SELL or Chinese equivalents, a target-price conclusion,
personalized action advice, or a probability-weighted target by default.
