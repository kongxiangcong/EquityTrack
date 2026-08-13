# DCF, Historical Band & Sensitivity — Absolute & Relative-to-Self Valuation

> **Conditional method reference** — Read only when the valuation router selects DCF or the user explicitly requests a DCF applicability assessment. The deterministic engine remains the authority for execution and output permission.
>
> **Companion file**: `comparable.md` covers relative-to-peers valuation. Together these two files form the complete valuation methodology layer.

> **Enforcement status**: Current runtime permissions use the canonical
> source/official/PIT, typed-input, applicability, FCFF/mature-state,
> method-math/units, `WACC > g`, equity-bridge and output-boundary gates.
> Assumption-dossier completeness, a complete WACC x g surface and an
> independent cross-DecisionView release receipt are research-review practices
> and target migration acceptance, not current fail-closed runtime gates.
> The implemented workbook gate reconciles raw OOXML canonical rows and
> `Decimal` values to the exporting `ResearchDecisionView`, then recomputes its
> published bridge/per-share chain. It is neither a full DCF recalculation nor
> an independent source-lineage check against the persisted ledger.

---

## DCF Applicability Gate

Run this gate before any DCF tab, WACC table, terminal value, or DCF-derived per-share value is created. DCF is one possible valuation method, not the default L2 method.

### Gate Output

```yaml
dcf_applicability:
  status: allowed | caution | disabled
  reason:
  required_source_ids:
  missing_data:
  terminal_value_risk: low | medium | high | not_applicable
```

`assumption_challenge_status` and `release_gate_status` are reserved target
migration fields. Do not emit them as current runtime-enforced status before the
typed dossier and release-receipt migration is complete.

### Allowed

DCF may be used only when all conditions are satisfied:

- Company is non-financial, or a special case where operating debt and financing debt can be cleanly separated.
- Operating FCFF is positive, stable, or has a credible and source-supported path to positive cash flow within the explicit forecast period.
- Revenue, EBIT, tax, D&A, CapEx, working capital, share count, net debt, minority interest, lease debt, preferred stock, and non-operating assets have `source_id` coverage or documented assumptions.
- Forecast period reaches a mature state where growth, margin, ROIC, and reinvestment are internally consistent.
- `WACC > terminal_growth`.
- Terminal growth does not exceed long-term nominal economic growth for the relevant currency/market.
- Terminal value share of EV is disclosed and treated as a fragility diagnostic; material concentration requires source-backed explanation and independent cross-checks.

### Caution

DCF may be used only as a secondary/cross-check method when:

- Company has volatile or cyclical cash flows but mid-cycle assumptions are source-supported.
- Company is early in profitability transition and requires explicit financing/runway assumptions.
- Terminal value, margin, or reinvestment assumptions drive most of the value.
- Peer-implied terminal multiples or reverse DCF do not corroborate the base case.

### Disabled

Do not use ordinary FCFF/WACC DCF when any condition applies:

- Banks, insurers, brokers, asset managers, and other financial firms. Use P/B x ROE/COE, DDM, residual income, or excess return models instead.
- Pre-revenue or pipeline-driven biopharma. Use rNPV/SOTP and cash runway analysis.
- Real estate developers where NAV/RNAV or project cash flow is the primary framework.
- Resource/cyclical companies where current commodity price or peak margin would be extrapolated into perpetuity without mid-cycle normalization.
- Long-term negative FCFF or funding-dependent businesses without a source-supported path to self-funding.
- Missing official-source coverage for critical DCF inputs.
- `WACC <= terminal_growth`.

If disabled, write `disabled_reason` and route to `valuation/valuation-method-router.md`. Do not output DCF implied value, DCF target price, or WACC x terminal growth sensitivity.

### Assumption challenge and release review (target migration)

Separate observed fact, deterministic calculation and judgment. Every material
assumption should bind supporting source refs, counter-evidence, a falsifier,
stress/base/improvement values, dimensions, and what would change the view as a
research-review discipline.

Current runtime DCF permission remains governed by its implemented source,
authority, PIT, typed-input, applicability, Forecast/FCFF, method-math,
`WACC > g`, equity-bridge and output-boundary checks. It does not yet have a
typed dossier-completeness gate, a guaranteed complete WACC x g surface, or one
independent release receipt spanning DecisionViews.

As target migration acceptance, a future release receipt will bind:

1. source, authority, rights and PIT integrity;
2. assumption challenge dossier completeness;
3. Forecast, FCFF and mature-state reconciliation;
4. method math, units, `WACC > g` and equity bridge;
5. a source-calibrated WACC x g parameter surface;
6. canonical workbook projection integrity;
7. independent validation across the persisted ledger and published
   DecisionViews.

Until that migration, reviewers record a missing target artifact as a review or
migration gap; it must not be described as a current runtime gate result. The
existing runtime gates still fail closed on their own source, PIT, missing-data,
method and output-boundary conditions. The implemented Python workbook gate
reconciles raw OOXML canonical rows and `Decimal` values to the exporting
`ResearchDecisionView`, then recomputes the workbook equity bridge/per-share
chain; it is not a full DCF calculation and does not independently revalidate
persisted-ledger source lineage.

Reverse DCF remains a separate market-implied-expectation diagnostic anchored
to observed PIT enterprise value. It is not a target price or action signal.

---

## Why One File

These lenses share definitions and audit evidence, but retain independent
method status:

- **DCF** is a conditional deterministic method when its gates pass.
- **Historical band** is an independent PIT-valid relative-to-self diagnostic.
- **Sensitivity** is a parameter surface for an allowed/caution method, not a
  probability model or action conclusion.

Co-location removes duplicate definitions; one lens may be disabled without
silently disabling or validating another.

---

## Part 1: DCF Methodology / 现金流折现法

### Overview

The Discounted Cash Flow model estimates intrinsic value by projecting future Free Cash Flows (FCF) and discounting them to present value. It is an **absolute** valuation method only when the applicability gate passes. The other lenses are relative-to-peers via `comparable.md`, relative-to-self via Part 2 below, and any industry-specific method selected by `valuation-method-router.md`.

### Model Structure

```
Step 1: WACC Calculation              → Discount rate
Step 2: Historical FCF Analysis       → Base year metrics
Step 3: FCF Projection (explicit N)   → Projected cash flows
Step 4: Terminal Value                → Perpetuity or exit multiple
Step 5: Enterprise Value              → Sum PV(FCF) + PV(Terminal Value)
Step 6: Equity Bridge                 → EV → Equity Value → Per Share Value
Step 7: Sensitivity Analysis          → See Part 3 below
```

### Step 1: WACC Calculation (加权平均资本成本)

**Formula:**

```
WACC = E/(E+D) × Ke + D/(E+D) × Kd × (1 - Tax Rate)
```

Use market-value weights where available. Include preferred stock when material:

```
WACC = Ke * E/V + Kd * (1 - Tax Rate) * D/V + Kps * PS/V
```

**Component details:**

| Component | Method | Source Requirement |
|-----------|--------|-------------|
| **Ke (Cost of Equity)** | CAPM: Rf + β × ERP + Size Premium | `source_id` for each component |
| **Risk-Free Rate (Rf)** | 10-year government bond yield of company's market | `source_id`, currency, date |
| **Beta (β)** | Prefer peer unlever/relever; own regression only as cross-check | raw beta source, leverage/source assumptions |
| **Equity Risk Premium (ERP)** | Market-specific | `source_id`; avoid double-counting country/size premiums |
| **Size/Country Premium** | Only if not already included in ERP | explicit rationale and `source_id` |
| **Kd (Cost of Debt)** | Weighted average interest rate on debt | financial statement/bond source_id |
| **E, D, PS** | Market cap of equity; debt; preferred stock | latest source_id and date |
| **Tax Rate** | Effective tax rate (3-year average) or statutory normalized | source_id and rationale |

**WACC reasonability check.** Calibrate the surface from frozen, source-backed
currency/date/industry inputs and source-compatible observations. Do not use a
hardcoded market-typical range. Explain material component or leverage
anomalies; unsupported anomalies leave DCF at `caution` or `disabled`.


### Step 2: Historical FCF Analysis

**Free Cash Flow definition:**

```
FCFF = EBIT × (1 - Tax Rate) + D&A - CapEx - ΔWorking Capital
```

Or equivalently:

```
FCFF = Operating Cash Flow - CapEx + Interest × (1 - Tax Rate)
```

Do not subtract interest from FCFF. If using FCFE, discount with cost of equity, not WACC, and document the switch.

**Historical metrics to calculate over a sufficient PIT-valid history:**

| Metric | Purpose |
|--------|---------|
| Revenue growth rate | Projection base |
| EBIT margin | Profitability trend |
| CapEx / Revenue ratio | Investment intensity |
| D&A / Revenue ratio | Asset base |
| Working capital / Revenue ratio | Capital efficiency |
| FCFF margin | Cash conversion |
| FCFF / Net Income ratio | Earnings-to-cash conversion quality |

### Step 3: FCF Projection (Explicit Horizon)

**Projection framework:**

| Year | Revenue Growth | EBIT Margin | CapEx/Rev | ΔWC/Rev | Tax Rate |
|------|---------------|-------------|-----------|---------|----------|
| Year 1 | PIT-valid source or bounded estimate | | | | |
| Year 2 | Gradual convergence | | | | |
| Year 3 | Mid-cycle normalization | | | | |
| Year 4 | Approaching steady state | | | | |
| Year N | Source-supported mature state | | | | |

**Projection principles:**

1. **Revenue growth**: Licensed, PIT-valid consensus may be a structured or estimated input; otherwise use frozen observations or a bounded estimate, then converge only with source-backed mature-state logic.
2. **Margin expansion/contraction**: Must be justified (operating leverage, mix shift, pricing power).
3. **CapEx intensity**: Align with management guidance and historical patterns.
4. **Working capital**: Use historical days ratios unless structural change expected.
5. **No hockey-stick projections**: Growth acceleration in later years requires explicit justification.

**Key assumption documentation.** Every projection must document:

```
Assumption:       [What is assumed; fact/calculation/judgment class]
Support:          [Frozen source refs or versioned prior]
Counter-evidence: [What weakens the assumption]
Falsifier:        [Observable condition that would invalidate it]
Range:            [Stress/base/improvement values, units and periods]
Risk:             [What could make this wrong]
What changes it:  [Evidence that would change the view]
```

### Step 4: Terminal Value

**Method A: Gordon Growth Model (preferred)**

```
Terminal Value = FCF_YearN × (1 + g) / (WACC - g)
```

Where `g` = terminal growth rate:

Calibrate `g` from frozen long-term nominal evidence for the relevant currency
and market, together with mature-state ROIC and reinvestment consistency. There
is no hardcoded market default, and `WACC > g` remains mandatory.

**Method B: Exit Multiple**

```
Terminal Value = EBITDA_YearN × Exit Multiple
```

Exit multiple based on comparable company current trading multiples, with potential mean-reversion adjustment.

**Terminal value sanity check:**

- Disclose terminal value share of EV as a fragility diagnostic; concentration
  increases the need for source-backed explanation and cross-method checks.
- Reconcile the exit-multiple-implied growth rate to the same frozen mature-
  state economics. Do not judge it against an unsupported universal range.

### Steps 5-6: Enterprise Value → Equity Value

```
Enterprise Value = Σ PV(FCF_Year1-N) + PV(Terminal Value)
```

**Equity bridge:**

```
Equity Value = Enterprise Value
  - Gross Debt
  - Lease Debt
  - Preferred Stock
  - Minority Interest
  - Pension Deficit
  + Cash & Equivalents
  + Associates & JVs (at fair value)
  + Excess Cash (if identified)
  + Non-operating Assets (at fair value)

Equity Value per Share = Equity Value / Fully Diluted Shares Outstanding
```

Handle stock options/SBC dilution where material. Every bridge item must have `source_id` or be marked `missing`; missing critical bridge items prohibit per-share valuation.

### Step 7: Sensitivity Analysis

For the target governed DCF package, an `allowed` or `caution` method should
produce at minimum:

1. **WACC vs. Terminal Growth Rate** matrix (primary target surface)
2. **Revenue Growth vs. EBIT Margin** matrix (secondary — optional)

Full specification in **Part 3** below.

Current runtime does not yet fail closed on publication of the complete primary
surface. Review available scenario/sensitivity output and record a migration
gap when the complete surface is absent; do not fabricate cells or report that
a runtime release receipt passed.

### DCF Output Format (for report inclusion)

The target governed DCF section should include:

1. **Assumption Challenge Table**: Key inputs, support, counter-evidence, falsifiers and bounds
2. **FCF Projection Table**: governed explicit horizon + terminal value
3. **Equity Bridge Table**: EV → Equity Value → Per Share
4. **Sensitivity Matrix**: WACC × Terminal Growth (from Part 3)
5. **Narrative**: method status, parameter fragility, evidence limits and what would change the view; no action conclusion

Before migration, these items are a research-review checklist rather than proof
of one runtime-enforced formal DCF release gate.

---

## Part 2: Historical Valuation Band / 历史估值区间分析

### Overview

Historical valuation band analysis plots a stock's valuation multiples over time to identify whether the current valuation sits at a premium or discount relative to its **own history**. This is a **relative-to-self** valuation method, complementing the **relative-to-peers** (comparable companies in `comparable.md`) and **absolute** (DCF above) methods.

### Methodology

**Step 1: Select valuation metrics**

Choose 2-3 metrics based on industry (refer to `comparable.md` §Valuation Metric Selection Guide):

| Priority | Metrics | Applicable Industries |
|----------|---------|----------------------|
| Primary | PE (TTM) | Most industries with stable earnings |
| Primary | PB | Financials, cyclicals, asset-heavy |
| Secondary | PS | Tech, high-growth, loss-making |
| Secondary | EV/EBITDA | Capital-intensive, cross-border comparison |

**Step 2: Historical data collection**

| Parameter | Specification |
|-----------|---------------|
| **Time period** | Sufficient PIT-valid observations for the relevant regime/cycle; disclose exclusions and breaks |
| **Frequency** | Weekly closing values preferred; monthly acceptable |
| **Adjustment** | Forward-adjusted (前复权) prices for PE/PB calculations |
| **Outlier handling** | Exclude periods where PE is negative or >200x (label as "N/M") |

Data source: exchange/terminal/Yahoo/iFind or another market data source with retrieval timestamp, adjustment method, field definition, and `source_id`. Historical market data does not replace official financial statement sources.

**Step 3: Calculate statistical bands**

For each metric, calculate:

| Statistic | Calculation | Purpose |
|-----------|-------------|---------|
| **Maximum** | Max over period | Cycle peak valuation |
| **Minimum** | Min over period (excl. outliers) | Cycle trough valuation |
| **Mean** | Arithmetic average | Valuation center |
| **Median** | 50th percentile | Robust center (less outlier-sensitive) |
| **+1 Std Dev** | Mean + 1σ | Upper statistical band |
| **-1 Std Dev** | Mean - 1σ | Lower statistical band |
| **Current** | Frozen PIT value | Position at the research cutoff |
| **Current Percentile** | % of observations below current | Relative positioning |

**Step 4: Percentile interpretation**

| Percentile Range | Interpretation | Suggested Label |
|-----------------|----------------|-----------------|
| 0-20% | Lower tail of frozen window | 历史窗口较低分位 / Lower Tail |
| 20-40% | Below window center | 低于窗口中枢 / Below Window Center |
| 40-60% | Central window | 历史窗口中部 / Central Window |
| 60-80% | Above window center | 高于窗口中枢 / Above Window Center |
| 80-100% | Upper tail of frozen window | 历史窗口较高分位 / Upper Tail |

**Important caveat.** A percentile is relative positioning, not a cheap/fair/expensive conclusion or action signal. Compare independently with selected DCF, comparable and industry methods, and project conflicts through `../output/report-layout.md`.

### Band Output Format

**Summary table:**

```markdown
| Metric | Window High | Window Low | Mean | Median | +1σ | -1σ | Current | Percentile |
|--------|---------|--------|------|--------|-----|-----|---------|------------|
| PE(TTM) | 35.2x | 12.8x | 22.5x | 21.3x | 28.7x | 16.3x | 18.5x | 32% |
| PB | 5.8x | 2.1x | 3.8x | 3.6x | 4.9x | 2.7x | 3.2x | 38% |
```

The displayed values illustrate layout only; use the frozen window identity.

**Narrative template:**

```
Historical Valuation Analysis:
• Over frozen window [identity], [Company] is at the [N]th percentile of the
  comparable range ([low]x–[high]x).
• The current multiple is at a [premium/discount] to the window mean of [mean]x;
  this is a relative-to-self observation, not an action conclusion.
• Regime breaks/exclusions and the evidence for current [above/below] average:
  [source-backed explanation].
• The historical-band and DCF lenses are [consistent/in conflict] on [assumption
  or diagnostic]; neither automatically validates the other.
```

### Visual Specification (for chart generation)

If a renderer generates a valuation band chart:

1. **Chart type**: Line chart with shaded bands
2. **X-axis**: Time (5 years, monthly ticks)
3. **Y-axis**: Valuation multiple (PE or PB)
4. **Bands**: Mean (solid line), ±1σ (shaded area), ±2σ (lighter shaded area)
5. **Current point**: Highlighted dot with label
6. **Colors**: Use blue tones consistent with the report's CSS color scheme (#003366 primary)

### Common Pitfalls

1. **Cyclical trap**: For cyclical stocks (周期股), PE is lowest at cycle peak (high earnings) and highest at cycle trough (low earnings). Use PB instead.
2. **Structural change**: If company underwent major M&A, spin-off, or business transformation mid-period, historical bands before the event are not comparable. Truncate to post-event period.
3. **Share dilution**: Large equity issuance or buyback programs can distort historical PE/PB. Use per-share metrics consistently.
4. **Accounting changes**: IFRS/CAS transitions can affect reported earnings. Note any standard changes in the analysis period.

---

## Part 3: Sensitivity Analysis / 敏感性分析

### Overview

Sensitivity analysis quantifies how changes in key assumptions affect a conditional valuation output. It exposes fragility and non-linearity; it does not automatically turn a point into a defensible range or probability distribution.

### Matrix Types

**Primary matrix: WACC × Terminal Growth Rate (target governed DCF package)**

This is the target sensitivity surface for an allowed/caution DCF. The current
runtime does not yet treat publication of the complete surface as a fail-closed
formal-release gate. Until migration, use it for research review and disclose
its absence or incomplete coverage without inventing unsupported cells.
All numeric tables below illustrate layout only. Their values are never defaults.


```markdown
| Equity Value/Share | g = 1.5% | g = 2.0% | g = 2.5% | g = 3.0% | g = 3.5% |
|--------------------|----------|----------|----------|----------|----------|
| **WACC = 8.0%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
| **WACC = 8.5%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
| **WACC = 9.0%** | ¥XX.XX | **¥XX.XX** | ¥XX.XX | ¥XX.XX | ¥XX.XX |
| **WACC = 9.5%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
| **WACC = 10.0%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
```

Formatting rules:

- Highlight the frozen base case wherever it falls; it need not be the center.
- Derive bounds and steps from source-backed inputs and the assumption dossier.
- Preserve `WACC > g`; invalid or unsupported cells remain unavailable.
- A fixed symmetric range or fixed grid size is not required.
- Currency symbol matches company's primary listing market

**Secondary matrix: Revenue Growth × EBIT Margin (optional)**

```markdown
| Equity Value/Share | Margin = 12% | Margin = 14% | Margin = 16% | Margin = 18% | Margin = 20% |
|--------------------|-------------|-------------|-------------|-------------|-------------|
| **Growth = 5%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
| **Growth = 8%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
| **Growth = 10%** | ¥XX.XX | ¥XX.XX | **¥XX.XX** | ¥XX.XX | ¥XX.XX |
| **Growth = 12%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
| **Growth = 15%** | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX | ¥XX.XX |
```

**Tertiary matrix: PE × EPS (scenario-linked)**

Useful for connecting to scenario analysis in `scenario-deep-dive.md`:

```markdown
| Implied Market Cap (亿) | EPS = ¥3.50 | EPS = ¥4.00 | EPS = ¥4.50 | EPS = ¥5.00 |
|--------------------------|-------------|-------------|-------------|-------------|
| **PE = 12x** | | | | |
| **PE = 15x** | | **Base** | | |
| **PE = 18x** | | | | |
| **PE = 20x** | | | | |
```

### Construction Guidelines

**Variable selection.** Choose the 2 variables with the **highest impact on valuation** and the **highest uncertainty**:

| Company Type | Recommended Primary Pair | Recommended Secondary Pair |
|-------------|--------------------------|---------------------------|
| Mature/Stable | WACC × Terminal Growth | PE × EPS |
| High Growth | Revenue Growth × EBIT Margin | WACC × Terminal Growth |
| Cyclical | Commodity Price × Volume | PB × ROE |
| Financial | NIM × Loan Growth | PB × ROE |
| Loss-making | Revenue Growth × Path to Profitability | PS × Revenue |

**Range calibration:**

1. **Bounds**: Use frozen evidence or challenged bounded assumptions; symmetry is optional.
2. **Step size**: Use enough resolution to expose material non-linearity; no fixed grid is a default.
3. **Constraint check**: Every cell satisfies units, mature-state economics and `WACC > g`.
4. **Scenario linking**: Stress/base/improvement scenarios map to specific cells when their drivers are comparable.

### Interpretation Narrative

After each matrix, include a brief interpretation:

```markdown
**Sensitivity Interpretation:**
• Under the frozen base assumptions (WACC [X]%, terminal growth [Y]%), the
  conditional method output is ¥[Z] per share with status [ready/limited].
• The output is [more/less] sensitive to [variable A] than [variable B]:
  a 1% change in [A] moves equity value by [±X]%, while a 1% change in [B]
  moves it by [±Y]%.
• [N] cells satisfy all method constraints. The result becomes unavailable or
  materially changes when [falsifier/evidence condition] occurs.
```

### HTML Formatting for Report

```html
<div class="exhibit-label">
  <span class="exhibit-number">Exhibit X:</span>
  <span class="exhibit-desc">DCF Sensitivity: WACC vs. Terminal Growth Rate</span>
</div>
<table class="report-table">
  <thead>
    <tr>
      <th>Equity Value/Share</th>
      <th>g = 1.5%</th><th>g = 2.0%</th><th>g = 2.5%</th><th>g = 3.0%</th><th>g = 3.5%</th>
    </tr>
  </thead>
  <tbody>
    <tr><td class="col-text"><b>WACC = 9.0%</b></td>
        <td class="col-number">¥XX</td>
        <td class="col-number"><b>¥XX</b></td>  <!-- base case highlighted -->
        <td class="col-number">¥XX</td>
        <td class="col-number">¥XX</td>
        <td class="col-number">¥XX</td></tr>
    <!-- ... more rows ... -->
  </tbody>
</table>
<div class="data-source">Frozen model inputs and source IDs</div>
```

Use `.row-highlight` class for the base case row, and `<b>` for the base case cell.

---

## Combined Review and Migration Checklist

- [ ] **Current DCF gate**: Source/official/PIT and typed input-origin coverage pass
- [ ] **Current DCF gate**: Explicit Forecast/FCFF, source-calibrated WACC, `WACC > g` and equity bridge reconcile
- [ ] **Current DCF gate**: Terminal value share of EV is disclosed as a fragility diagnostic
- [ ] **Current XLSX delivery gate**: Raw OOXML canonical rows/`Decimal` values reconcile to the exporting `ResearchDecisionView`, and bridge/per-share recomputation passes; no full-DCF or independent persisted-ledger lineage validation claim
- [ ] **Target migration review**: Assumption challenge dossier includes support, counter-evidence, falsifier and bounds
- [ ] **Target migration review**: Complete WACC x terminal-growth surface is source-calibrated and every published cell passes constraints
- [ ] **Target migration review**: Independent cross-DecisionView release receipt exists
- [ ] **Historical Band**: Selected metrics use a sufficient PIT-valid comparable regime/window
- [ ] **Historical Band**: Narrative interpreting current position vs. own history, with cyclical-trap check
- [ ] **Sensitivity review**: Available surface highlights the base and discloses unsupported or absent cells
- [ ] **Sensitivity**: Interpretation states fragility, evidence limits and falsifiers without action language
- [ ] **Cross-method synthesis** (selected methods only): Projected through the three-scenario valuation section of `../output/report-layout.md`

---

## Data Sources

| Data Type | Source | API / Retrieval |
|-----------|--------|-----------------|
| Financial statements | Official filings/company IR first | SEC EDGAR/XBRL, CNINFO/SSE/SZSE/BSE, HKEXnews, company reports |
| Beta | Peer set / market data | terminal/Yahoo/iFind/exchange data with source_id |
| Historical PE/PB/PS | Market data source with timestamp | terminal/Yahoo/iFind/exchange data |
| Historical stock prices | Market data source with timestamp | terminal/Yahoo/iFind/exchange data |
| Risk-free rate | Government bond source | country-specific 10Y bond yield with source_id |
| Consensus estimates | Licensed/clearly labeled consensus source | iFind/terminal/secondary; estimate tier |
| Share count | Official filings/company IR first | SEC/CNINFO/HKEX/company reports; terminal cross-check |

---

## Integration With Other Files

- **`comparable.md`** — Relative-to-peers method selection.
- **`valuation-method-router.md`** — Applicability and method-state authority.
- **`industry-valuation-matrix.md`** — Industry-specific method constraints.
- **`../references/research-analysis-plan.md`** — Frozen capability and analysis-node binding.
- **`../references/financial-model-spec.md`** — Canonical model/workbook projection and reconciliation.
