# Capability Matrix

The v2 workflow separates source integrity from method/output readiness.

## Statuses

| Status | Meaning |
|---|---|
| `ready` | All required sourced inputs are present |
| `limited` | Required inputs are present; optional enrichment is missing |
| `ready_with_estimates` | Explicit estimates support exploratory use only |
| `blocked` | A direct dependency is missing or conflicted |
| `disabled` | The method is inapplicable by company type or policy |
| `caution` | Runnable only as a cross-check because of company type or estimates |

## Integrity vs. Readiness

Manifest integrity covers object shape, company identity, source IDs, source tiers, field period/unit/currency/value, finite numeric payloads, as-of availability, overlay identity, and unresolved conflicts. Integrity errors fail-closed before numeric method execution and render a data-insufficient memo.

Readiness covers whether a specific capability has enough evidence. Ordinary field gaps change only dependent capability statuses.

## Estimate Invariant

An estimate may satisfy an `estimate_allowed` dependency and produce `ready_with_estimates`. It remains `official = false`, keeps its basis sources, and does not change formal source coverage.

## Structured Method Inputs

- DCF assumption sources must resolve to role-specific canonical evidence with compatible subject, period, currency, and unit. Peer and historical inputs must resolve a unique `subject + semantic_role + source_id + field_name + period` evidence reference; `missing` and `estimate` tiers never satisfy formal method provenance.
- Peers require explicit period, currency check, and accounting check flags before they count toward the minimum three.
- Historical bands require at least 12 dated, pre-as-of observations.
- DCF requires a reconciled WACC and explicit equity-bridge evidence; unknown adjustments never become zero.
