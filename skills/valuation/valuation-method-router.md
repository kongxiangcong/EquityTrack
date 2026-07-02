# Valuation Method Router

Use this router before any valuation work. L2 means "model-enabled depth"; it does not mean DCF by default.

---

## Inputs

```yaml
market:
industry:
business_model:
lifecycle: mature | growth | early | pre_revenue | cyclical | distressed
profitability: profitable | near_break_even | loss_making
cash_flow_stability: stable | volatile | negative | not_meaningful
leverage_or_debt_type:
official_filings_available: true | false
source_manifest_status: sufficient | insufficient | draft
data_quality_grade: High | Medium | Low | Insufficient
user_requested_rating: true | false
```

---

## Outputs

```yaml
valuation_method_router_result:
  selected_methods:
    - method:
      role: primary | secondary | cross_check
      reason:
  caution_methods:
    - method:
      reason:
      required_checks:
  disabled_methods:
    - method:
      reason:
  required_data:
  missing_data:
  data_insufficient_memo_required: true | false
```

---

## Hard Gates

- If `source_manifest_status = insufficient`, do not output valuation conclusion. Produce `data_insufficient_memo`.
- If latest financial statements do not have official-source coverage, do not output target price, rating, or per-share valuation.
- If fewer than 3 usable peers survive source/currency/accounting checks, comps cannot support a valuation conclusion.
- If a selected method has missing critical data, either remove the method or degrade to `data_insufficient_memo`.

---

## Method Rules

| Company Type | Selected / Preferred Methods | Disabled / Caution Methods | Minimum Gate |
|--------------|------------------------------|-----------------------------|--------------|
| Financial firms | P/B x ROE/COE, DDM, residual income, excess return | Ordinary FCFF/WACC DCF, EV/EBITDA | Book value, ROE, COE, regulatory/solvency and credit/underwriting metrics |
| Pre-revenue / pipeline biopharma | rNPV, pipeline SOTP, comparable transactions, cash runway | Ordinary consolidated DCF, PE, unsupported PS | Asset/indication/phase, PoS basis, rights ownership, cash runway, license economics |
| Mature non-financials | DCF if gate passes, PE/PEG, EV/EBITDA, historical band | DCF if unstable FCFF or missing bridge data | Official financials, share count, net debt, WACC inputs |
| Cyclical / resources | Mid-cycle EV/EBITDA, P/B, NAV, reserve/cost curve | Peak-cycle DCF, current commodity price perpetuity | Cycle-normalized volume/price/cost, reserves or capacity data |
| Real estate | NAV/RNAV, project cash flow, P/B, dividend yield | Consolidated FCFF DCF without project/debt maturity detail | Land bank, sell-through, ASP/cost, net debt, debt maturity |
| SaaS / software | EV/Sales, Rule of 40, ARR/NRR, mature-stage FCF DCF if gate passes | DCF ignoring SBC/dilution; PS without retention/unit economics | ARR, NRR/churn, CAC payback, SBC, gross/FCF margin |
| Internet platforms | SOTP, EV/GMV, EV/EBITDA, mature-platform PE | MAU-only or GMV-only valuation | DAU/MAU, GMV, take rate, segment profit, regulatory risks |
| Semiconductor | Subsector-specific PE/PEG, EV/EBITDA, P/B, cycle-normalized methods | DCF without cycle/inventory/capex normalization | ASP, shipments, utilization, inventory, backlog, capex |
| Consumer | PE/PEG, EV/EBITDA, DCF for stable mature companies | PS-only, high-growth DCF without channel/brand support | Category revenue, price/volume, channels, margins, inventory |

---

## DCF Routing

Route to `valuation/dcf-and-sensitivity.md` only when DCF is selected or requested. The DCF file then returns:

- `allowed`
- `caution`
- `disabled`

Financial firms must disable ordinary FCFF/WACC DCF. Pre-revenue or pipeline-driven biopharma should route to rNPV/SOTP first.

---

## Degraded Output

When `data_insufficient_memo_required = true`, allowed output is:

- Research notes.
- Source gap table.
- Disabled-method reasons.
- Next data requirements.

Prohibited output is:

- BUY/HOLD/SELL or Chinese equivalents.
- Target price.
- Buy/sell/hold advice.
- Probability-weighted target.
