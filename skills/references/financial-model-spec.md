# Financial Model Projection Specification

> Policy-target reference. The financial model is a recomputable projection of
> canonical Forecast and Valuation artifacts, not an independent valuation
> authority or a second research workflow.

## Wired canonical boundary

The formal research workflow persists the complete typed Forecast ->
ScenarioValuation -> valuation/path decision -> RecentTrendAssessment chain and
one workbook manifest slot. That slot contains reconciled OOXML only when the
renderer succeeds; otherwise it contains one typed limitation projection.
Inspect the manifest and never assemble a manual workbook to replace that
formal member.

## Canonical sequence

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

The model owns the Forecast and deterministic valuation calculations inside
that sequence. It does not own report narrative, recent-trend interpretation,
TradePlanDraft confirmation, or application mutations.

## Input-origin model

Every input cell or typed quantity has exactly one origin:

| Origin | Meaning | Required lineage |
|---|---|---|
| `observed_official` | Official disclosure or exchange fact | Source identity, period, available/retrieved timestamps |
| `observed_structured` | PIT-valid structured provider observation | Actual provider/gateway identity and timestamps |
| `derived` | Deterministic result from named operands | Operand refs and formula identity |
| `estimated` | `BoundedEstimate` | Estimate identity, method, bounds, calibration and source refs |
| `missing` | No defensible value | Missing reason; no numeric placeholder |

Tushare-compatible observations are `observed_structured`, not official. Keep
their actual gateway identity. Unknown is never zero.

## BoundedEstimate

Use a bounded estimate only when the missing driver can be tied to frozen
observations or a versioned prior. Store:

- estimator and estimate-policy identities;
- source refs, calibration sample/window and as-of date;
- point, lower bound, upper bound, unit, currency and period;
- confidence, rationale and invalidation condition.

Allowed bases, in order of preference:

1. the company’s PIT-valid historical distribution;
2. segment/driver history with a stable definition;
3. source-compatible peer or industry distribution;
4. an explicit user assumption with identity and bounds.

Do not use an unexplained scalar, a silent default, stale/future data, or zero
as a substitute for missing. Estimates remain estimates in every formula,
scenario, report and workbook style.

## Forecast model

Build Event -> Driver -> Forecast Financial transmission. The model may include
segment revenue, operating drivers, income statement, balance sheet, cash flow
and supporting schedules as required by the company archetype. Do not force an
industrial three-statement template onto a financial institution or pipeline
biopharma company.

Each projected value must be one of:

1. an observed input linked to its frozen source;
2. a bounded estimate linked to `BoundedEstimate`;
3. a formula linked to named operands;
4. `missing`/`n.m.` with a reason.

There are no unexplained hardcoded values and no implicit zero branches.

### General non-financial reconciliation

- Segment revenue sums to total revenue.
- Income-statement revenue links to the revenue build.
- Projected cash links to the cash-flow statement.
- Balance-sheet assets equal liabilities plus equity within declared rounding.
- Cash-flow ending cash ties to balance-sheet cash.
- Working-capital changes reconcile between balance sheet and cash flow.
- Diluted shares and net-debt/equity bridge use one unit/currency/as-of basis.

### Specialized archetypes

- Financial institutions use book value, regulatory capital, clean-surplus,
  ROE/COE, payout and institution operating metrics; ordinary FCFF/WACC DCF is
  disabled.
- Pipeline biopharma uses asset/indication rights, event probabilities,
  licensing economics, rNPV/SOTP and financing-aware runway.
- Cyclical/resource companies use normalized price/volume/cost, finite reserve
  or capacity economics, mid-cycle valuation and peak-cycle diagnostics.
- Multi-segment companies reconcile non-overlapping segment economics before
  SOTP.

## Three-scenario model

Create exactly `stress`, `base`, and `improvement`. Do not use Bull/Base/Bear
aliases. All three scenarios must contain the same driver and output rows so
the differences are auditable.

For each scenario record:

- driver overrides and their origins;
- forecast financials and reconciliations;
- selected, limited, blocked and disabled valuation methods;
- method formulas, conditional ranges and diagnostics;
- assumptions, missing inputs and invalidation conditions.

Set `probability_mode = conditional_only` unless complete PIT-valid probability
calibration exists. Under `conditional_only`, show no probability-weighted
value. Under `evidence_weighted`, all three probabilities must exist, cite the
same partition/sample identity, and sum exactly to one. Never assign a default
base probability.

## Dynamic valuation projection

The workbook projects only methods selected by
`valuation/valuation-method-router.md`. It does not require a DCF tab for every
company.

| Method family | Include when | Key checks |
|---|---|---|
| Ordinary FCFF/WACC DCF | Router returns allowed or documented caution | Explicit FCF forecast, WACC components, `WACC > g`, terminal-value diagnostic and complete equity bridge |
| Relative valuation | At least three source-compatible peers survive | Period, accounting, currency/unit and denominator compatibility |
| Historical band | PIT-valid history has enough comparable observations | Regime/cycle break and denominator quality |
| Financial institution | Typed institution inputs exist | Book/regulatory capital, clean surplus, ROE/COE and payout reconcile |
| Biopharma rNPV/SOTP | Typed asset/event/rights/runway inputs exist | Event probabilities, rights counted once and financing dilution |
| Cyclical/NAV/mid-cycle | Normalized or finite-life inputs exist | No peak-price perpetuity; reserve/capacity/cost identity |
| Multi-segment SOTP | Segment economics are non-overlapping | Segment-to-consolidated bridge and double-count prevention |

If an input is missing, limit or block only the dependent method. A bounded-
estimate method may publish a conditional range with `limited` status. Missing
official critical inputs still prohibit a formal target, rating or unqualified
valuation conclusion.

## ValuationSimulationDecision projection

Always include the decision object, whether or not Monte Carlo runs.

Run only with:

- at least one deterministic valuation anchor;
- material uncertain drivers with bounded calibrated distributions;
- dependency calibration or a versioned explicit override;
- dimensional valuation formula and hard constraints;
- RNG identity, seed, sample/batch budget, convergence and invalid-path gates.

When run, project distributions, dependency matrix, seed, budget, convergence,
invalid-path rate, quantiles, tails, contributions and deterministic fallback.
When prerequisites are missing, show `not_run` and reason codes. When the gate
does not converge, show `partial` and withhold unstable stochastic quantiles.
Monte Carlo never fills missing financial facts.

## MarketPathDecision projection

Market paths are separate from intrinsic value and from valuation Monte Carlo.
Always project the applicability decision.

Run only with PIT-valid adjusted OHLCV, trading-calendar identity, current
state, A-share execution constraints, transaction costs, RNG identity, seed,
path budget and enough state-conditioned contiguous historical blocks. Project
horizon returns, drawdowns and threshold frequencies only when the formal run
exists. Never create arbitrary GBM drift/volatility inputs.

## Workbook structure

Use the smallest set of tabs that preserves the canonical model. Recommended
target tabs are:

1. `Audit & Origins` — identities, source refs, origin ledger, estimates,
   missing inputs and statuses;
2. `Drivers` — observed and estimated assumptions with bounds/rationale;
3. `Forecast` — driver build and archetype-appropriate financial outputs;
4. `Scenarios` — stress/base/improvement with aligned rows;
5. `Valuation` — selected method calculations and reconciliation;
6. `Simulation Decision` — Monte Carlo result or `not_run` reasons;
7. `Market Path Decision` — market-path result or `not_run` reasons;
8. `Recent Trend` — read-only projection of the canonical assessment;
9. `Reconciliation` — formula checks and canonical artifact hashes.

Split statements or specialized schedules into additional tabs only when they
own meaningful calculations. Do not create empty DCF, comps, simulation or
market-path tabs as compatibility placeholders.

## Formula and display conventions

- Observed inputs: one consistent observed-input style with origin label.
- Estimated inputs: a distinct editable-assumption style plus bounds and
  estimator identity.
- Formulas: formula style; never hardcode canonical calculated outputs.
- Cross-tab links: separate link style.
- Missing: `n.m.` plus reason; no numeric value.
- Units, currency, period and as-of appear in every table header.
- Negative values use a consistent parenthetical format.

## Projection integrity

The workbook must reconcile to the canonical DecisionView and typed artifacts:

1. Security, as-of and data-snapshot identities match.
2. Forecast and scenario structures/hashes match.
3. Method status, formulas and conditional ranges match.
4. Origin/estimate/missing classifications are preserved.
5. Statement, cash, revenue, shares and equity-bridge checks pass when
   applicable.
6. Probability mode and sum-to-one gate match.
7. Simulation/path result identities, RNG and seeds match when run.
8. `not_run`, `partial` and `blocked` remain explicit.
9. No formula errors, unexplained constants, placeholders or hidden fallback
   paths remain.

A workbook projection failure blocks XLSX delivery only. It does not create a
second research result and does not erase a structurally complete canonical
report. `valid_with_limits` remains structurally complete with method-level
limits. When required official evidence or selected-method inputs are missing,
the dependent valuation section is a `data_insufficient_memo` and cannot carry
a formal valuation conclusion, target, or rating.

## Trade-plan boundary

The workbook may display the canonical recent-trend and `TradePlanDraft`
handoff read-only. It must not create, confirm, activate, or compose a plan.
The application-owned `trade_plan.prepare_draft@1` seam accepts only a
user-readable account alias, security code, plan style, and request time. It
resolves the canonical report and trend, latest confirmed account snapshot and
risk policy, and active built-in strategy, then compiles and validates the full
`TradePlanGraph` and persists the `OPEN` draft. The workbook and Skill never
supply a caller-authored graph or authority-version pin.

After application authoring returns one `OPEN TradePlanDraft`, it becomes an
immutable confirmed version only after one explicit user confirmation of the
exact revision/challenge.
