---
name: equity-researcher-v2
description: Deterministic personal equity research workflow. Skills collect and explain evidence; the Python core owns gates, method routing, calculations, run state, and report rendering.
---

# Equity Research v2

This is the default workflow for new runs. It replaces Task 1/2/3 as the top-level control plane.

## Interface

The only core call is:

```text
run(ResearchRequest) -> ResearchRun
```

The common CLI adapter is:

```powershell
python scripts\research.py run `
  --manifest <source_manifest.json> `
  --estimates <estimate_overlay.json> `
  --context <research_context.json> `
  --as-of-date YYYY-MM-DD `
  --output-dir <run_directory>
```

Outputs:

- `research_run.json`: canonical facts, capability matrix, method results, permissions, plans, and diagnostics;
- `research_report.html`: self-contained report rendered from that exact snapshot.

## Responsibility Split

### Deterministic Python core

The code under `src/equity_research/` owns:

- manifest integrity and canonical field normalization;
- fact / derived / estimate separation;
- capability-level evidence requirements;
- valuation method routing and DCF financial invariants;
- permissions and safety policy;
- conditional research plan assembly;
- canonical JSON and HTML rendering.

Do not reimplement these decisions in prose, prompts, or company-specific scripts.

### Skills and agents

Skills may:

- discover official filings and market-data candidates;
- extract evidence into the source manifest;
- write structured theses, risks, catalysts, scenarios, and review triggers;
- explain deterministic model outputs;
- identify additional evidence that could change a capability status.

Skills must not:

- change sourced financial values;
- promote estimates to official facts;
- choose a valuation method after the code router disables it;
- calculate an alternative result inside report prose;
- turn missing data into zero, neutral, or safe;
- produce personal instructions, positions, or house-style labels by default.

## Run Sequence

### 1. Lock the request

Record these once and keep them immutable for the run:

- ticker and exchange;
- company identity;
- as-of date;
- market, reporting currency, trading currency, and accounting standard;
- profile: `quick`, `standard`, or `deep`.

Do not mix facts first made public after the as-of date into a historical run. A later retrieval timestamp is valid for backtesting when the source preserves an earlier public availability date.
The engine rejects post-as-of public availability dates and future estimate overlays; the date is an enforced invariant, not a label.

### 2. Build evidence

Official disclosure remains primary for critical financial facts:

- A-share: CNINFO, SSE/SZSE/BSE, company IR;
- HK: HKEXnews and company IR;
- US: SEC EDGAR/XBRL and company IR.

Secondary and terminal sources may support market data, structure, and cross-checking. Every observed value needs a source ID, public availability date (`available_at`, `published_at`, or `report_date`), retrieval timestamp, period, unit, currency, extraction method, and confidence.

DCF sources must resolve to usable canonical evidence. Peer and historical inputs use an `evidence_ref` with `source_id`, `field_name`, and `period`; the referenced item must also match subject/ticker, semantic role, and be unique within the method. The engine reads the numeric value from that exact evidence item rather than trusting a duplicate number in context.

Write missing fields to `missing_critical_data`. Missing is a first-class state, never zero.

### 3. Add an estimate overlay only when useful

An estimate overlay is optional. Every estimate must include:

- field and period;
- explicit value or components;
- method;
- basis source IDs;
- confidence;
- `formal_gate_coverage = false`.

Estimates may enable `ready_with_estimates` for exploratory models and scenarios. They never upgrade official coverage.

### 4. Write structured research context

Use JSON with these optional sections:

```json
{
  "company_type": "general | cyclical_manufacturing | financial | biopharma | ...",
  "peer_count": 0,
  "executive_summary": "...",
  "theses": [],
  "risks": [],
  "catalysts": [],
  "scenarios": [],
  "conditional_plan": [],
  "dcf_case": null,
  "historical_multiples": null
}
```

Narrative items should reference `evidence_fields`. Scenario probabilities are omitted unless they have a documented calibration basis.

### 5. Run the engine once

Run `scripts/research.py`. Read `research_run.json`; do not infer state from prose or filenames.

Interpret the status:

- `completed`: requested capabilities completed without material limits;
- `completed_with_limits`: useful output completed, while one or more capabilities are limited, estimate-supported, blocked, or inapplicable;
- `blocked`: manifest integrity or instrument identity failed. This is not used for ordinary field gaps.

### 6. Follow the capability matrix

The current capabilities are:

| Capability | Meaning when unavailable |
|---|---|
| `research_core` | Latest official business/financial core is insufficient |
| `earnings_quality` | Cash conversion analysis is limited |
| `per_share_context` | Per-share market context is unavailable |
| `financial_model` | Linked scenario model lacks required inputs |
| `dcf` | DCF alone is unavailable |
| `peer_comps` | Peer method alone is unavailable |
| `historical_band` | Historical relative-to-self method is unavailable |
| `conditional_research_plan` | Structured review plan cannot be formed |
| `research_report` | A full research narrative is unavailable |

Never translate one blocked row into a global failure.

### 7. Only request the smallest useful supplement

If the user can provide more data, ask for evidence that unlocks the highest-value blocked capability. State the exact field, period, accepted source, and affected method. Do not repeat already covered fields.

### 8. Deliver artifacts and boundary

Deliver the canonical JSON and HTML. Summarize:

- overall run status;
- data quality grade;
- available and limited capabilities;
- selected, limited, and disabled methods;
- key uncertainties and what would change the view.

The default output is research decision support. It is not a personalized investment instruction and must not contain default institutional action labels or a house-style price conclusion.

## DCF Contract

The engine executes DCF only when `dcf_case` is explicit and the capability requirements pass. The case needs:

- at least two forecast FCFF evidence refs;
- terminal-growth evidence and a declared WACC with `WACC > g`;
- exact WACC-component evidence refs for risk-free rate, ERP, beta, pre-tax debt cost, tax rate, and equity/debt weights; declared WACC must reconcile;
- forecast currency and unit scale matching the evidence ledger;
- cash, debt, diluted shares, and applicable equity-bridge adjustments;
- explicit minority interest, preferred stock, pensions, lease debt, non-operating assets, and associates/JV values, including sourced zero values where genuinely absent;
- `source_id + field_name + period` references for every FCFF, terminal-growth, and WACC-component input.

FCFF evidence must use the target subject, `dcf_forecast_fcff` role, consistent currency/unit scaling, and strictly increasing unique forecast periods. WACC evidence uses one valuation date and role-specific decimal or beta units.

The engine calculates present values, terminal value, equity bridge, per-share result, and a 5×5 WACC/g sensitivity matrix. It does not invent WACC, growth, FCF conversion, net debt, or peer multiples.

Financial firms disable ordinary FCFF/WACC DCF. Pipeline-driven biopharma routes to rNPV/SOTP. Cyclical companies keep ordinary DCF disabled until the normalized mid-cycle builder is implemented and passes.

## Example Regression

The portable 意华股份 example is under `examples/yihua-002897/`.

Expected behavior:

- `research_core = ready`;
- `financial_model = ready_with_estimates`;
- `dcf = blocked` because an explicit, fully sourced DCF case is absent;
- `peer_comps = blocked` because no qualified peer set exists;
- `research_report = ready`;
- run status is `completed_with_limits`, not a Task 1 failure.

Run it with:

```powershell
python scripts\research.py run `
  --manifest examples\yihua-002897\source_manifest.json `
  --estimates examples\yihua-002897\estimate_overlay.json `
  --context examples\yihua-002897\research_context.json `
  --as-of-date 2026-07-07 `
  --output-dir outputs\yihua-v2
```
