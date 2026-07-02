---
name: equity-report-task2-model
description: "Task 2 of equity report workflow (L2 only). Builds a source-gated, method-routed financial model and valuation analysis from the Task 1 research document. Produces: (1) a linked model with only applicable valuation methods; (2) a valuation analysis or data insufficient memo. DCF is conditional on the applicability gate. This file is the entry point — do NOT read SKILL.md or Task 1's analysis framework files."
---

# Task 2: Financial Model + Valuation (L2 Only)

> **This is the entry point for Task 2 of the equity report workflow (L2 Full Version).**
> Task 1 (Research + Analysis) has already been completed and produced a research document.
> Your job: build an actual Excel financial model and perform valuation analysis only for methods that passed source and method gates.
> **If this is an L1 (streamlined) report**: Skip this file entirely. Go directly to `SKILL-task3-report.md`.

---

## ⚠️ CRITICAL RULES

### DO NOT TAKE SHORTCUTS
**Data Authenticity** All data must have real sources; strictly prohibit fabrication. No placeholders, no "TBD". 
**Data Verification** Critical data cross-verified by 2+ independent sources 
**Timeliness**  Must use latest financial reports and real-time market data 

- ✅ Build a REAL Excel model with formulas that recalculate when inputs change — not static numbers
- ✅ Load Task 1 `source_manifest`, `source_manifest_status`, and `valuation_method_router_result` before any model work
- ✅ Load Task 1 `source_manifest_validation_result` JSON before any model work
- ✅ Every historical and market number must carry a `source_id` or be marked `missing`
- ✅ All 3 financial statements (IS → BS → CF) must link and balance
- ✅ Balance Sheet: Assets = Liabilities + Equity on EVERY projected year (BALANCE CHECK row mandatory)
- ✅ Cash Flow: Ending Cash must tie to BS Cash on every year (CASH TIE-OUT row mandatory)
- ✅ Revenue must link from Revenue Model tab to Income Statement tab (not typed twice)
- ✅ DCF, if allowed: WACC calculated from CAPM, not hardcoded. FCFF discounted with formulas and source IDs for every input.
- ✅ Sensitivity matrix: Use formulas tied to the selected method. WACC × Terminal Growth applies only when DCF is allowed.
- ✅ Comps table: ≥5 peers with statistical summary (Max/75th/Median/25th/Min)
- ✅ Financial firms: ordinary FCFF/WACC DCF is disabled; use equity-model methods such as P/B x ROE/COE, DDM, residual income, or excess return
- ✅ Pre-revenue or pipeline-driven biopharma: use rNPV/SOTP; do not use ordinary consolidated DCF/PE as the primary method
- ❌ Do not hardcode projected numbers — every projection must flow from Operating Drivers
- ❌ Do not create a DCF tab when `dcf_applicability = disabled`
- ❌ Do not create a full three-statement model, DCF tab, target price, rating, or valuation conclusion when source manifest validation failed
- ❌ Do not output a rating, target price, upside/downside, or buy/sell conclusion unless `user_requested_rating = true` and all data gates pass
- ❌ Do not calculate probability-weighted price unless probability basis is sourced; otherwise show scenario range only
- ❌ Do not fabricate comparable company data — use real market data

### Font Color Convention
- 🔵 Blue font = hardcoded input / assumption
- ⚫ Black font = formula (calculated from other cells)
- 🟢 Green font = cross-sheet link (references another tab)

### Task Boundary
- ✅ If source validation passes: deliver Excel model (.xlsx) + Valuation Analysis document (.md) — then STOP
- ✅ If source validation fails: deliver only `data_insufficient_memo` / `model_blocked_reason` — then STOP
- ❌ **Do not continue to Task 3.** Wait for user's continuation signal.
- ❌ **Do not create summary documents or extra files.** Deliver only the applicable output set for the validation state.

---

## Prerequisites

### Automatic File Loading (Session Context)

When the user says "下一步"/"继续"/"continue" to enter Task 2, the Task 1 files exist in the **current session context**. **Do NOT ask the user to provide files.**

1. **Auto-locate Task 1 Research Document**: Search the session for the most recent file matching `*_Research_Document_*.md`. Read it directly.
2. **Extract from the research document**:
   - Company name, ticker, market, currency
   - Historical financial data (§VI)
   - Revenue segment breakdown (§VII)
   - Source manifest summary (§XI)
   - Source manifest path and source manifest validation result path
   - Source manifest validation result (`passed`, `source_manifest_status`, `data_insufficient_memo_required`, errors/warnings, blocking issue codes)
   - Valuation method router result and comparable companies (§XII)
   - Operating assumptions mentioned in the analysis
   - `source_manifest_status`, `data_quality_grade`, `dcf_applicability`, `selected_methods`, `disabled_methods`, `missing_data`
3. **Auto-locate and read source manifest validation JSON**: Prefer the explicit path in the Research Document. If absent, search for the most recent `*_source_manifest_validation_*.json` beside the Research Document.
4. **Do NOT read**: `SKILL.md`, `analysis/*.md`, `modules/*.md` — these were consumed in Task 1.

**If the research document cannot be found in session**: Ask the user to confirm the filename. Do NOT start Task 2 without it.

**Source validation hard gate**: If the validation JSON cannot be found, cannot be parsed, has `passed = false`, has `source_manifest_status != sufficient`, or has `data_insufficient_memo_required = true`, do not start workbook construction. Do not generate a full three-statement model, DCF, target price, rating, upside/downside, or valuation conclusion. Produce only a `data_insufficient_memo` / `model_blocked_reason` listing validator issues and next source requirements, then STOP.

---

## Files to Read

| # | File | Purpose |
|---|------|---------|
| 1 | Task 1 Research Document | Source of all analytical content and historical data |
| 2 | Source manifest validation result JSON | Executable pass/fail gate before any model construction |
| 3 | Source manifest JSON | Source records referenced by Raw Data and valuation inputs |
| 4 | `references/source-manifest.md` | Source manifest schema and critical-number coverage gate |
| 5 | `valuation/valuation-method-router.md` | Determines selected/caution/disabled valuation methods |
| 6 | `valuation/industry-valuation-matrix.md` | Industry-specific method rules, minimum data gates, sensitivities |
| 7 | `references/financial-model-spec.md` | **SOLE SOURCE** for Excel model structure — tab specs, line items, formula patterns, formatting |
| 8 | `valuation/dcf-and-sensitivity.md` | Conditional reference — read only if DCF is `allowed` or `caution` |
| 9 | `valuation/comparable.md` | Comps methodology — peer selection, metric selection by industry, analysis framework |
| 10 | `references/data-sources.md` | Official-first data source priority and fallback rules |

**Do not read DCF mechanics just because this is L2.** Read `valuation/dcf-and-sensitivity.md` only after the router says DCF is `allowed` or `caution`.

---

## Step 1: Collect Financial Data

### 1.1 Extract from Research Document

The Task 1 research document §VI contains 3-5 years of historical financials. Extract:
- Income Statement: Revenue, COGS, Gross Profit, R&D, SG&A, D&A, EBIT, Interest, Tax, Net Income, EPS, Shares
- Balance Sheet: Cash, AR, Inventory, PP&E, Total Assets, AP, Debt, Total Liabilities, Equity
- Cash Flow: CFO, CapEx, FCF, Dividends
- Key ratios: Margins, ROE, ROA

### 1.2 Fetch Additional Data (if needed)

If the research document's financial data is incomplete, first check whether the missing item is critical. Critical missing data must be resolved from official sources or marked `missing` in the source manifest; do not bridge it with unsourced assumptions.

Official-first fallback:
- **A-shares**: CNINFO, SSE/SZSE/BSE announcements, company IR annual/interim/quarterly reports. iFind is optional secondary structuring/cross-check.
- **HK**: HKEXnews and company IR reports. iFind/Yahoo are optional secondary/cross-check sources.
- **US**: SEC EDGAR filings, companyfacts/companyconcept XBRL APIs, company IR reports. Yahoo is acceptable for price/market data, not as sole financial-statement authority.
- **Comparable companies**: official filings for financials; exchange/terminal/Yahoo for market data with timestamp and field definition.

If an official route or required API/tool is unavailable, record `tool_unavailable` and `missing_data` in the source manifest. If the missing item is required for the selected method, degrade to `data_insufficient_memo`.

Data to fetch that may not be in the research document:
- [ ] 5-year historical PE/PB weekly data (for historical band, if selected and sourceable)
- [ ] Comparable company financial metrics (for comps tab)
- [ ] Beta, risk-free rate (for WACC, only if DCF is allowed/caution)
- [ ] Consensus estimates for FY+1 and FY+2 (for sanity-checking projections)
- [ ] Detailed segment-level revenue (if research document only has top-line)

### 1.3 Record Everything in Raw Data Tab

Every number fetched goes into the Raw Data tab with `source_id`, currency, unit, reporting period, retrieved_at, and field definition. No data should be used in the model without first being recorded in Raw Data and source manifest. Critical missing fields remain `missing`; do not fill them with estimates to keep the model moving.

---

## Step 2: Build the Financial Model (Excel)

### ⚠️ TOOL AND SKILL DISCOVERY (READ FIRST)

Before building the model yourself, discover what spreadsheet/xlsx tools are available in the current Codex environment. Do not assume a fixed path or a preinstalled finance skill.

**Integration Rules:**
- ✅ Use available spreadsheet/xlsx tooling when it can build linked formulas and preserve source IDs.
- ✅ Feed it only data extracted from the Task 1 Research Document and `source_manifest`.
- ✅ After any tool finishes, verify that its output passes the integrity checks in Step 5.
- ✅ Perform additional cross-verification on latest-period critical numbers against official sources to detect corruption or mock data.
- ✅ Combine all outputs into a single workbook where feasible. DCF, rNPV, residual income, NAV, or other method tabs appear only when selected by the router.
- ✅ If no spreadsheet skill is available, fall back to Python/openpyxl or another available local spreadsheet library using `references/financial-model-spec.md`.
- ❌ Do NOT let external tools write the Valuation Analysis document; that stays in this framework.
- ❌ Do NOT let tools fabricate missing fields, invent sources, or silently convert units/currencies.
- ❌ Do NOT create a DCF tab just because a DCF helper exists; DCF requires the applicability gate.

If required tools are not available for a selected valuation method, record the gap in `source_manifest`/model notes. If the gap prevents a required calculation, degrade to `data_insufficient_memo`.

### Build Order

Whether using environment skills or building manually, the model must contain these tabs in this order:

```
PHASE A — Source and Method Gate
  0. Source Manifest          → source_id coverage, official source status, missing critical data
  0b. Valuation Method Router → selected/caution/disabled methods and reasons

PHASE B — Operating Model (3-statement when applicable; industry-adapted otherwise)
  1. Raw Data          → Populate with historical financials from Task 1
  2. Operating Drivers → Set all forward-looking assumptions with Source + Rationale
  3. Revenue Model     → Bottom-up segment revenue buildup (Volume × Price)
  4. Income Statement  → Full P&L driven by Drivers and Revenue Model
  5. Balance Sheet     → Full BS driven by Drivers, with balance check
  6. Cash Flow         → Full CF driven by IS and BS changes, cash tie-out

PHASE C — Valuation Tabs (only selected methods)
  7. Valuation Method Rationale → why each method is selected/caution/disabled
  8. Comps / Multiples          → 5-10 peers where applicable; minimum 3 or downgrade
  9. DCF                        → only if `dcf_applicability = allowed` or documented `caution`
  10. rNPV / SOTP / NAV / Residual Income / DDM → only when selected by router
  11. Sensitivity               → method-specific sensitivity variables
  12. Scenarios                 → Bull/Base/Bear ranges; probability-weighted only with sourced probability basis
```

**If using environment skills**: After the operating model completes, verify BS balance + cash tie-out BEFORE starting valuation tabs. After valuation tabs, verify all integrity checks (Step 5). If `source_manifest_status = insufficient`, stop at a data insufficient memo.

### Operating Drivers — Key Assumptions to Set

For each projected year (FY+1 through FY+5), set these assumptions:

| Category | Assumptions | Guidance |
|----------|------------|----------|
| **Revenue** | YoY growth rate per segment | Start with consensus for Y1-2, converge to industry long-term for Y3-5 |
| **Margins** | Gross margin, R&D%, SG&A%, D&A% | Historical trend ± justified adjustments (operating leverage, mix shift) |
| **Tax** | Effective tax rate | Normalize to statutory rate unless structural reason |
| **Working Capital** | DSO, DIO, DPO | Use historical averages unless structural change expected |
| **CapEx** | CapEx % of revenue | Management guidance or historical trend |
| **Valuation** | Method-specific inputs | Use `valuation-method-router.md`; WACC/terminal growth only if DCF is allowed |

**CRITICAL**: Every assumption MUST have:
1. A **Source** (e.g., "Management guidance Q4 2025 call", "3Y historical average", "Consensus Bloomberg")
2. A **Rationale** (e.g., "Margin recovery from 4680 cell manufacturing efficiency gains")

---

## Step 3: Perform Valuation Analysis

### 3.0 Method Router Check

Before any valuation calculation, confirm:

- `source_manifest_validation_result.passed = true`.
- `source_manifest_status = sufficient` for the selected method's critical inputs.
- `source_manifest_validation_result.data_insufficient_memo_required = false`.
- `valuation_method_router_result.selected_methods` is populated.
- `disabled_methods` includes explicit reasons.
- `missing_data` is empty for every selected method, or the method is removed/degraded.

If this check fails, skip workbook valuation tabs and write `data_insufficient_memo` / `model_blocked_reason`.

### 3.1 DCF Valuation (conditional)

Read `valuation/dcf-and-sensitivity.md` only if DCF is `allowed` or `caution`. Execute Steps 1-7 only after the DCF applicability gate passes:
1. Calculate WACC (check reasonability vs. market range)
2. Project 5 years of UFCF from the model
3. Calculate Terminal Value (Gordon Growth + check TV/EV ratio)
4. Discount to present value
5. Equity Bridge: EV → Net Debt → Equity Value → Per Share
6. Build sensitivity matrix (WACC × Terminal Growth)

If DCF is disabled, create a `Valuation Method Rationale` section with `disabled_reason` and do not output DCF implied value.

### 3.2 Comparable Companies

Read `valuation/comparable.md` for peer selection and metric guidance.
- Select 5-10 peers (same industry, similar scale ±50%)
- Populate: Market Cap, Revenue, EBITDA, NI, key multiples
- **MANDATORY**: Statistical summary row with Max/75th/Median/25th/Min
- Calculate implied valuation range (25th to 75th percentile applied to target)

### 3.3 Historical Valuation Band

Read `valuation/dcf-and-sensitivity.md` §Part 2 for historical band methodology.
- Collect 5Y PE/PB data (weekly)
- Calculate: Max, Min, Mean, Median, ±1σ, Current, Percentile
- Interpretation: Where does current valuation sit vs. history?

### 3.4 Cross-Method Synthesis

Compare all valuation methods and identify convergence/divergence:
- DCF, if allowed, implies a valuation range with source-linked assumptions
- Comps median implies a valuation range when peers are sourceable and comparable
- Historical band median implies a valuation range only when historical data is sourceable
- rNPV/SOTP/NAV/residual income/DDM methods are included when selected by router
- **Final valuation view**: a range and key assumptions, not a default target price or rating

### 3.5 Scenario Analysis

Build Bull/Base/Bear scenarios:
- Different revenue growth + margin assumptions
- Different WACC (if macro risk differs)
- Probability-weighted value is allowed only when probability basis is sourced; otherwise show scenario range without probability-weighted target

---

## Step 4: Write Valuation Analysis Document

Produce: `{Company}_{Ticker}_Valuation_Analysis_{Date}.md`

### Structure

```markdown
# {Company} ({Ticker}) Valuation Analysis

> Date: YYYY-MM-DD
> Analyst: Kimi Research (AI-Assisted)
> Current Price: $XXX.XX
> user_requested_rating: false
> data_quality_grade: [High / Medium / Low / Insufficient]
> source_manifest_status: [sufficient / insufficient]
> valuation_method_router_result: [selected / caution / disabled summary]

---

## I. Valuation View Summary

[2-3 sentences: valuation range/view, key drivers, key limitations. Do not provide buy/sell advice or target-price conclusion by default.]

## II. Method Router Result

| Method | Status | Reason | Required Data | Missing Data |
|--------|--------|--------|---------------|--------------|
| DCF | allowed/caution/disabled | | | |
| Comps | selected/caution/disabled | | | |
| rNPV/SOTP/NAV/Residual Income/DDM | selected/caution/disabled | | | |

## III. DCF Analysis (only if allowed/caution)

[WACC: X.X%, Terminal Growth: X.X%, Implied value: $XXX]
[Key sensitivity: ±1% WACC = ±$XX per share]
[TV as % of EV: XX% — comment if high]

If DCF is disabled, replace this section with `disabled_reason` and the method selected instead.

## IV. Comparable Companies

[Peer set: [list], Selection rationale: [1 sentence]]
[Target trades at Xth percentile of peers on P/E]
[Implied range from comps: $XX — $XX]

## V. Historical Valuation Band

[PE currently at Xth percentile of 5Y range]
[PB currently at Xth percentile of 5Y range]
[Historical context: re-rating/de-rating drivers]

## VI. Cross-Method Synthesis

[Do methods converge? Which to weight more?]
[Final valuation range: $XX — $XX when data gates pass]
[Base case view: method weighting and confidence]

## VII. Scenario Analysis

### Bull Case ([probability only if sourced])
[Assumptions + implied price + what triggers this]

### Base Case ([probability only if sourced])
[Assumptions + implied price + default path]

### Bear Case ([probability only if sourced])
[Assumptions + implied price + what triggers this]

Probability-weighted value is omitted unless `probability_basis` is sourced.

## VIII. Key Catalysts

[Top 3-5 catalysts that could move the stock toward bull or bear case]

## IX. Key Risks to Valuation View

[Top 3-5 risks that could invalidate the valuation, with quantified impact where possible]

## X. Optional Rating Section

Include only when `user_requested_rating = true` and all data gates pass. Add non-investment-advice boundary. Otherwise omit.
```

---

## Step 5: Model Integrity Verification

Run the applicable checks from `references/financial-model-spec.md` §Model Integrity Checks plus the executable source validation gate below. `source_manifest_validator.py` must already have produced a passed validation JSON before this step; full `model_validator.py` is still out of scope, so workbook formula checks remain manual for now.

| # | Check | Pass? |
|---|-------|-------|
| 1 | Source manifest validation JSON exists, was read, and has `passed = true` | ☐ |
| 2 | Validation JSON has `source_manifest_status = sufficient` and `data_insufficient_memo_required = false` | ☐ |
| 3 | Source manifest exists and every critical number has `source_id` or `missing` | ☐ |
| 4 | Official-source coverage exists for latest critical financial statements | ☐ |
| 5 | `valuation_method_router_result` exists with selected/caution/disabled methods | ☐ |
| 6 | Disabled methods are not accidentally modeled as valuation conclusions | ☐ |
| 7 | BS balances (all periods, if 3-statement model is applicable) | ☐ |
| 8 | Cash ties (CF ending = BS cash, if 3-statement model is applicable) | ☐ |
| 9 | Revenue ties (Rev Model = IS, if applicable) | ☐ |
| 10 | Historical accuracy vs Raw Data <1% and source IDs match | ☐ |
| 11 | DCF checks pass only if DCF allowed: WACC in range or explained, WACC > g, TV/EV disclosed | ☐ |
| 12 | Sensitivity center equals base case for selected method | ☐ |
| 13 | Comps stats no errors; minimum 3 usable peers or downgrade | ☐ |
| 14 | Scenario probabilities have `probability_basis`; otherwise no probability-weighted value | ☐ |

**All applicable checks must pass before delivery to Task 3.** If a critical source/method check fails, do not fix by inventing data; deliver `data_insufficient_memo` and STOP.

---

## Step 6: Deliver

If source manifest validation failed, deliver only `{Company}_{Ticker}_Data_Insufficient_Memo_{Date}.md` or `{Company}_{Ticker}_Model_Blocked_Reason_{Date}.md`; do not create a full model workbook or valuation analysis.

If source manifest validation passed:

1. Save `{Company}_{Ticker}_Financial_Model_{Date}.xlsx` to output directory
2. Save `{Company}_{Ticker}_Valuation_Analysis_{Date}.md` to output directory
3. Report:
   - Model summary (# tabs, # years projected)
   - Key outputs: Revenue CAGR, selected valuation methods, method-specific ranges, data quality grade
   - Source manifest validation result path and source/method/model integrity checks passed, or data insufficient memo delivered
4. Provide **continuation-ready message** to user:

   **Chinese:**
   > ✅ Step 2 完成 — 财务模型与估值分析已生成。
   > - Excel 模型: {N} 张工作表, {M} 年预测
   > - 选用估值方法: {selected_methods}
   > - 估值视角区间: ¥XX — ¥XX（如数据门禁通过）
   > - 来源/方法/模型检查通过
   >
   > 接下来进入 Step 3：生成最终 PDF 研报（≥25页）。
   > 你只需要说 **"下一步"**、**"继续"** 或 **"continue"**，我将自动读取本步骤和前面步骤生成的所有文件并继续。

   **English:**
   > ✅ Step 2 complete — Financial model and valuation analysis generated.
   > - Excel model: {N} tabs, {M} years projected
   > - Selected valuation methods: {selected_methods}
   > - Valuation view range: $XX — $XX (if data gates pass)
   > - Source/method/model checks passed
   >
   > Next: Step 3 — Generate final PDF report (≥25 pages).
   > Just say **"next"**, **"continue"**, or **"下一步"** and I'll automatically proceed using all files generated in this session.

5. **STOP.** Wait for user's continuation signal. Do not continue until user says "下一步"/"继续"/"continue"/"next".

---
