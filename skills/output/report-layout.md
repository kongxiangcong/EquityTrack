# Complete Research Report Layout

> Active projection reference for the canonical `ResearchDecisionView@2`.
> Inspect the persisted manifest before claiming a component result, projection,
> or workbook disposition.

## Wired canonical boundary

The formal research workflow persists one lineage-checked bundle containing
Forecast, stress/base/improvement ScenarioValuation, valuation-method routing,
ValuationSimulationDecision, MarketPathDecision, and RecentTrendAssessment. It
projects one canonical DecisionView to JSON, HTML, PDF, and one typed workbook
slot. The workbook member is reconciled XLSX when rendering succeeds or one
typed limitation artifact when it does not. The separate `trade_plan.prepare_draft@1` application task accepts only a
user-readable account alias, security code, plan style, and request time. It
resolves the latest complete research and trend, confirmed account/risk
authorities, and active built-in strategy, then compiles one
`OPEN TradePlanDraft`; renderers never compose its graph.

This layout describes the canonical product sequence:

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

The manifest is the production authority. Render each persisted component's
typed result, limitation, `not_run`, or blocked reason; never reconstruct a
missing member in the presentation layer.

## Meaning of complete

A complete report is structurally complete. Every required section is present
and contains either a result or an explicit `limited`, `blocked`, or `not_run`
status with reason codes. Completeness does not assert that
every number is official, every valuation method is applicable, or every
simulation ran.

`source_manifest_status = valid_with_limits` renders the full structure with
limitations. Missing required official evidence or selected-method inputs
turns the dependent valuation section into a `data_insufficient_memo` with
research notes, exact gaps, disabled-method reasons, and next data needs; it
does not authorize a formal valuation conclusion, target, or rating. A global
identity, PIT, rights, provenance, reproducibility, or calculation-integrity
failure blocks the whole run rather than degrading it to a capability limit.

## P2 template: compact data summary

The HTML/PDF projection may place a compact data-summary page immediately after
the decision summary. Keep the existing `.data-summary-page` container and
`.ds-table-dense` table contract used by `modules/tables.md`; this preserves the
shared CSS/table seam without retaining the retired parallel report workflow.

The page may show selected historical/forecast financials, ratios and recent
observed trend. Every cell must preserve origin and status. Use `n.m.` plus a
reason for missing values, distinguish forecast/estimated columns visually, and
never force an unavailable metric into the page. The page is a projection of
canonical content; it does not read a separate Excel model or recompute
research conclusions.

If the formal manifest lacks this projection, report the typed projection
limitation; do not generate a manual P2 page as a side artifact.

## Required report order

| # | Section | Required content |
|---|---|---|
| 1 | Run identity and wiring | Security, as-of, snapshot, model/policy/code identities, actual manifest members and their typed statuses |
| 2 | Decision summary | Future story, `valuation_view`, `risk_reward_summary`, data-quality grade, key uncertainties, what would change the view |
| 3 | Evidence and origin ledger | Observed-official, observed-structured, derived, estimated, and missing inputs; Tushare gateway identity preserved |
| 4 | Business and industry | Business model, industry position, drivers, counterpoints, catalysts, governance and material risks |
| 5 | Forecast | Driver-to-financial transmission, forecast horizon, formulas, origin mix, limits and reconciliation status |
| 6 | Three-scenario valuation | Exactly stress, base, improvement; selected/limited/blocked/disabled methods and conditional ranges |
| 7 | Valuation simulation | Applicability decision; calibrated output when run, deterministic fallback and reasons when not run |
| 8 | Market path | Separate applicability decision; calibrated price-path output or explicit reasons; never presented as intrinsic value |
| 9 | Recent trend | Observed price/volume/relative-strength trend from frozen market data, separate from simulated paths |
| 10 | Risks and monitoring | Risk conditions, invalidation signals, update triggers and next evidence needs |
| 11 | Audit appendix | Sources, parameters, formulas, estimator, model, policy, code, RNG and seed identities |
| 12 | Trade-plan handoff | `OPEN TradePlanDraft` identity/status or typed `not_created`/`blocked` reason; exact confirmation boundary |
| 13 | Financial boundary | Non-advice statement and prohibited action/rating language |

Do not omit a section because its calculation is unavailable. Render its state
and reason in place.

## Origin and estimate presentation

Every displayed number carries one origin badge:

- `observed_official` — official disclosure or exchange fact;
- `observed_structured` — PIT-valid structured provider observation, including
  the qualified Tushare-compatible gateway;
- `derived` — deterministic calculation from named operands;
- `estimated` — bounded estimate with estimator identity and range;
- `missing` — no defensible value.

For `estimated`, display the point/range, estimator, calibration window,
confidence, source refs, and invalidation condition. Never style an estimate as
an observed fact. Never display an unknown as zero.

## Forecast and scenario presentation

Use exactly `stress`, `base`, and `improvement`; do not use Bull/Base/Bear
aliases. Show the same driver rows for all three scenarios so changes are
comparable.

If probability evidence is absent, label the table `conditional_only` and omit
weighted value. If complete PIT-valid calibration exists, show
`evidence_weighted`, the probability basis, sample identity, and exact sum-to-
one check. Never insert a default base probability.

For every valuation method show:

- applicability and role;
- status: `ready`, `limited`, `caution`, `blocked`, or `disabled`;
- observed, derived, estimated, and missing inputs;
- formula/model identity and conditional range when permitted;
- reason codes and what would make the method usable.

Missing official critical inputs prohibit a formal target, rating, or
unqualified valuation conclusion. They do not suppress a clearly labeled
conditional range supported by bounded estimates when the method permits it.

## Simulation decisions

Always render `ValuationSimulationDecision` and `MarketPathDecision`.

When valuation Monte Carlo runs, show distribution/calibration identities,
dependency model, seed, sample budget, convergence, invalid-path rate,
quantiles, tails and deterministic fallback. If it does not run, show
`not_run` plus missing prerequisites. If it is non-converged, show `partial`
and withhold unstable quantiles.

When market-path simulation runs, show adjusted-series/calendar identities,
state model, block length, candidate-block count, A-share constraints,
transaction costs, seed, budget, horizon returns, drawdowns and threshold
frequencies. State explicitly that market paths are traded-price uncertainty,
not intrinsic value, a target price, or a trading instruction. Never substitute
arbitrary GBM.

## Recent trend and TradePlanDraft handoff

`RecentTrendAssessment` uses only frozen observed market data and deterministic
indicators. Distinguish it from both intrinsic valuation and simulated market
paths. Show observation window, adjustment convention, benchmark, trend state,
supporting metrics, uncertainty and invalidation conditions.

Show the one `OPEN TradePlanDraft` returned by
`trade_plan.prepare_draft@1`. The caller supplies only a user-readable account
alias, security code, plan style, and request time. The application resolves the
latest complete research and trend, confirmed account snapshot and risk policy
plus the active built-in strategy, then compiles and validates the complete
`TradePlanGraph`. The renderer and Skill never compose or submit that graph.

When application drafting returns the draft, present the readable final
revision, rule summary, account constraints, and exact differences. Keep
hashes, identities, and confirmation challenge internal. Ask for one explicit
user confirmation; do not add approval gates to earlier research stages. A revision invalidates the old challenge.

## Projection rules

The product has one canonical content projection to JSON, decision-first
HTML/PDF and the typed workbook slot. A renderer must not recalculate research meaning,
invent missing values, rename statuses, or create a second valuation result.
Report only projection members actually present in the persisted manifest.

Ready XLSX is a formula-recomputable projection of the same Forecast and
Valuation artifacts. A workbook failure limits that projection only; it does
not erase the canonical report.

## Visual rules

- Put the decision summary and most material uncertainty first.
- Use progressive disclosure for provenance, calibration and audit detail.
- Keep origin/status labels visible beside tables and charts.
- Use consistent scenario columns and units.
- Show missing cells as `missing` or `n.m.` with a reason, never a placeholder.
- Charts visualize the same frozen values as adjacent tables.
- Keep recent observed trend, market-path distributions and intrinsic valuation
  visually separate.
- Do not display BUY/HOLD/SELL, Chinese equivalents, target-price conclusions,
  personalized action advice, or probability-weighted targets by default.

## Delivery checks

Before delivery verify:

1. Every required section exists and has a status.
2. `valid_with_limits` retained the complete structure.
3. Every number has an origin; every estimate has bounds and identity.
4. Scenario names and driver structures are exact and aligned.
5. Simulation/path decisions exist even when `not_run`.
6. Recent trend is observed-data analysis, not simulated prediction.
7. Manifest members match every claimed projection.
8. The TradePlanDraft remains `OPEN` until one exact user confirmation.
9. The report contains no prohibited rating, target, or action language.
