# Revenue Model Deep Dive — Equity Report Only

> **Scope**: This file is read ONLY when `output_type = EQUITY_REPORT`.
> It forces a structured, bottom-up revenue decomposition that goes far beyond
> the top-line growth rates used in the tear sheet.

---

## Purpose

The tear sheet uses top-line revenue with simple YoY growth estimates.
The equity report must build revenue from the ground up — segment by segment,
product by product — so every growth assumption is transparent and testable.
This file produces the raw data that feeds into:
- The Financial Analysis module (Section 9)
- The Projection Assumptions section
- The DCF model inputs
- The Scenario Analysis variants

---

## 1. Revenue Architecture

### Step 1: Identify Revenue Segments

Map the company's revenue into 3-6 major segments using the most recent annual filing.
For each segment, identify the **revenue driver formula**:

| Segment Type | Driver Formula | Example |
|-------------|---------------|---------|
| Product (units) | Units Sold × Average Selling Price (ASP) | iPhone: 230M units × $930 ASP |
| Subscription | Subscribers × ARPU × 12 months | Services: 1.1B subs × $8.50/mo |
| Transaction-based | GMV × Take Rate | App Store: $95B GMV × 30% take |
| Licensing/royalty | Licensed base × Royalty per unit | Patent licensing: 500M devices × $2/device |
| Project/contract | # Projects × Avg Contract Value | Enterprise deals: 50 contracts × $2M avg |
| Advertising | Impressions × CPM (or DAU × Ad load × CPM) | Search ads: XB impressions × $YY CPM |

### Step 2: Historical Decomposition Table

```
Exhibit X: Revenue Decomposition by Segment

                          FY22A    FY23A    FY24A    FY25A    CAGR
──────────────────────────────────────────────────────────────────
[Segment 1]
  Revenue ($B)            xxx      xxx      xxx      xxx      x.x%
  Volume (units/subs)     xxx      xxx      xxx      xxx      x.x%
  Price (ASP/ARPU)        $xxx     $xxx     $xxx     $xxx     x.x%
  % of Total              xx.x%    xx.x%    xx.x%    xx.x%

[Segment 2]
  Revenue ($B)            xxx      xxx      xxx      xxx      x.x%
  Volume                  xxx      xxx      xxx      xxx      x.x%
  Price                   $xxx     $xxx     $xxx     $xxx     x.x%
  % of Total              xx.x%    xx.x%    xx.x%    xx.x%

[Segment 3-6...]

──────────────────────────────────────────────────────────────────
Total Revenue ($B)        xxx      xxx      xxx      xxx      x.x%
```

---

## 2. Growth Driver Analysis

For EACH major segment (≥10% of revenue), analyze:

### Volume Drivers
- **Market growth**: What is the industry growth rate? (TAM/SAM per `../output/report-layout.md` Business and industry section)
- **Market share trajectory**: Gaining, stable, or losing? (per `../output/report-layout.md` Business and industry section)
- **Product cycle**: New product launches, replacement cycles, cannibalization
- **Geographic expansion**: New market entry, penetration increase
- **Channel expansion**: New distribution partners, DTC growth

### Price Drivers
- **ASP / ARPU trends**: Historical direction and sustainability
- **Mix shift**: Higher-end products growing faster (positive mix) or commoditization (negative mix)
- **Pricing power**: Ability to raise prices (per `../output/report-layout.md` Business and industry section)
- **Currency impact**: FX translation effects on reported ASP
- **Promotional intensity**: Discounting trends, promotional calendar

### Writing Requirement

For EACH major segment, produce a **bold-keyword paragraph** documenting:
1. The primary growth driver (volume or price) with supporting data
2. The sustainability of the current growth trajectory
3. Risks specific to this segment
4. Our base case assumption vs. consensus

**Minimum**: 150-200 words per segment. 3-6 segments = 450-1,200 words total.

---

## 3. Revenue Projection Build

### Forward Estimates Table

```
Exhibit X: Revenue Projection Build ($B)

                     FY25A   FY26E   FY27E   FY28E   Notes
────────────────────────────────────────────────────────────
[Segment 1]          xxx     xxx     xxx     xxx     [key assumption]
  Volume growth      +x.x%   +x.x%  +x.x%  +x.x%
  ASP/ARPU change    +x.x%   +x.x%  +x.x%  +x.x%
  Revenue growth     +x.x%   +x.x%  +x.x%  +x.x%

[Segment 2]          xxx     xxx     xxx     xxx     [key assumption]
  Volume growth      +x.x%   +x.x%  +x.x%  +x.x%
  ASP/ARPU change    +x.x%   +x.x%  +x.x%  +x.x%
  Revenue growth     +x.x%   +x.x%  +x.x%  +x.x%

[Segment 3-6...]

────────────────────────────────────────────────────────────
Total Revenue        xxx     xxx     xxx     xxx
Total Revenue Gr.    +x.x%   +x.x%  +x.x%  +x.x%
Consensus            —       xxx     xxx     xxx
Our vs Consensus     —       +/-x%  +/-x%   +/-x%
```

### Consensus Comparison

- Document the consensus revenue estimate for FY+1 and FY+2
- State our estimate vs. consensus: above, in-line, or below
- Explain the key drivers of any divergence (which segments differ and why)
- This informs the H2 dimension (market pricing) and H3 (market error) from six-dimension analysis

---

## 4. Revenue Quality Assessment

| Metric | Current | Trend | Benchmark | Assessment |
|--------|---------|-------|-----------|------------|
| Recurring vs. one-time % | xx% recurring | Improving / Stable / Declining | Industry: xx% | Good / Fair / Poor |
| Customer concentration (top 10) | xx% of revenue | — | — | Risk level |
| Contract duration (avg) | X years | — | — | Visibility |
| Backlog / Pipeline | $XXB | +xx% YoY | — | Growth support |
| Revenue recognition timing | At delivery / Over time / Upfront | — | — | Conservatism |

**Writing requirement**: 100-150 words summarizing revenue quality — is the revenue base durable, growing from high-quality sources, or vulnerable?

---

## 5. Mix Shift Impact Analysis

Analyze how the revenue mix is changing and what it means for overall margins:

| Segment | FY-2 Share | Current Share | FY+2E Share | Segment GM | Impact on Blended GM |
|---------|-----------|---------------|-------------|-----------|---------------------|
| [Seg 1] | xx% | xx% | xx% | xx% | Positive / Negative / Neutral |
| [Seg 2] | xx% | xx% | xx% | xx% | Positive / Negative / Neutral |
| [Seg 3] | xx% | xx% | xx% | xx% | Positive / Negative / Neutral |

**Writing requirement**: 100-150 words on mix shift implications. This feeds directly into the margin bridge in projection-assumptions.md.

---

## Integration with Other Analysis Files

- **TAM / Market opportunity** (`../output/report-layout.md` — Business and industry): Market size provides the ceiling for segment revenue projections
- **Competitive landscape** (`../output/report-layout.md` — Business and industry): Market share trajectory informs volume assumptions
- **Projection assumptions** (`projection-assumptions.md`): Revenue buildup feeds directly into projection documentation
- **Scenario deep dive** (`scenario-deep-dive.md`): stress/base/improvement revenue numbers must come from this decomposition

---

## Output Quality Gate

- [ ] ≥3 segments with volume × price decomposition
- [ ] Historical decomposition table (3-5 years)
- [ ] Forward projection table (3 years)
- [ ] Consensus comparison with divergence explanation
- [ ] Revenue quality assessment table
- [ ] Mix shift impact analysis
- [ ] Per-segment narrative (≥150 words each)
- [ ] Total section word count ≥800 words (target 1,000-1,500)
