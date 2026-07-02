# Industry Valuation Matrix

Use this matrix with `valuation-method-router.md`. It provides Phase 0 method routing and minimum data gates; it is not a full industry valuation manual.

| Industry | Preferred Primary Method | Secondary Cross-check | Disabled / Caution | Minimum Data Gate | Sensitivity Variables | Common Traps |
|----------|--------------------------|-----------------------|--------------------|-------------------|-----------------------|--------------|
| Consumer | PE/PEG, EV/EBITDA; DCF only for stable mature companies | Historical band, margin/revenue scenarios | PS-only; high-growth DCF without brand/channel evidence | Category revenue, price/volume, channels, gross margin, SG&A, inventory | Volume, ASP, gross margin, channel mix | Treating brand premium as permanent without evidence |
| Cyclical manufacturing | Mid-cycle PE/EV/EBITDA, P/B | Historical band, cycle-normalized margin | Peak-profit DCF; direct use of latest EPS | Capacity, utilization, ASP, cost, orders, inventory, capex | ASP, utilization, margin, capex | Using cycle highs as terminal state |
| Financial | P/B x ROE/COE, DDM, residual income, excess return | Dividend yield, stress scenarios | Ordinary FCFF/WACC DCF, EV/EBITDA | Book value, ROE, COE, capital adequacy/solvency, NIM, credit or combined ratio | ROE, COE, credit cost, NIM/combined ratio | Treating deposits/financial liabilities as normal enterprise debt |
| Mature pharma | PE/PEG, EV/EBITDA, product SOTP, DCF if gate passes | Pipeline risk table, LOE scenarios | Perpetual DCF ignoring patent cliff | Product revenue, patent/LOE, reimbursement, pipeline, R&D, sales expense | LOE timing, price, volume, margin | Ignoring patent cliff or reimbursement pressure |
| Innovative biopharma | rNPV, pipeline SOTP, comparable transactions, cash runway | Marketed product value if any | PE, ordinary consolidated DCF, unsupported PS | Asset, indication, phase, PoS, patients, price, rights ownership, license terms, cash runway | PoS, peak sales, launch timing, royalty, trial cost | Applying one PoS to all assets or double-counting license economics |
| Semiconductor | Subsector-specific PE/PEG, EV/EBITDA, P/B, cycle-normalized methods | Backlog/capex scenarios | DCF without cycle, inventory, and capex normalization | Wafer starts/shipments, ASP, utilization, inventory, backlog, capex, node/customer concentration | ASP, utilization, gross margin, capex | Missing inventory cycle or customer concentration |
| Software / SaaS | EV/Sales, Rule of 40, ARR/NRR; mature-stage FCF DCF if gate passes | Cohort/unit economics, FCF margin scenarios | DCF ignoring SBC/dilution; PS without retention data | ARR, NRR, churn, CAC payback, SBC, gross margin, FCF margin | NRR, churn, FCF margin, SBC dilution | Treating revenue growth as value without unit economics |
| Internet | SOTP, EV/GMV, EV/EBITDA, mature platform PE | Segment margin and regulatory scenarios | MAU-only/GMV-only valuation; PS without monetization | DAU/MAU, GMV, take rate, ad load, commission rate, segment profit, regulation | Take rate, ad load, GMV, segment margin | Counting GMV as revenue or ignoring regulation |
| Real estate | NAV/RNAV, project cash flow, P/B, dividend yield | Debt maturity stress, sell-through scenarios | Consolidated FCFF DCF without project/debt detail | Land bank, saleable resources, ASP, sell-through, construction cost, net debt, maturity schedule | ASP, sell-through, cost, refinancing rate | Ignoring debt maturity or restricted presale cash |
| Resources | NAV, reserve value, mid-cycle EV/EBITDA, P/B | Commodity curve and cost curve scenarios | Current commodity price perpetuity DCF | Reserves, grade, cash cost/AISC, commodity price curve, mine life, capex | Commodity price, grade, cost, capex | Extrapolating spot prices forever |

---

## Minimum Peer Gate

Comparable-company output requires:

- Target 5-10 peers.
- Minimum 3 usable peers after source/currency/accounting/lifecycle checks.
- If fewer than 3 remain, use comps only as context and degrade any comps-based valuation conclusion.

---

## DCF Gate Reminder

DCF requires the applicability gate in `dcf-and-sensitivity.md`. It is disabled for ordinary financial-company valuation and should not be primary for pre-revenue/pipeline biopharma.
