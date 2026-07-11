---
name: equity-researcher-v3
description: Professional Research Narrative workflow. Company research is the primary artifact; evidence, capability, method, and runtime diagnostics remain in the audit appendix.
---

# Equity Research V3

## Interface

The deterministic seam remains:

```text
run(ResearchRequest) -> ResearchRun
```

V3 adds a professional narrative chain inside that Module:

```text
Evidence Ledger
  -> AnalysisBundle
  -> DebateResult
  -> ResearchSynthesis
  -> Professional HTML + audit appendix
```

The Skill gathers evidence and writes structured analysis. Python validates identities, dates, evidence references, capabilities, valuation methods, output permissions, and report mode.

## Research Context Contract

Set `report_version = 3` and provide all seven dimensions under `analyses`:

1. `business` — company, products, customers, business model, capital intensity;
2. `industry` — cycle, supply chain, competition, relative positioning;
3. `fundamentals` — growth, margin, cash conversion, balance sheet;
4. `technical` — trend, volume, momentum, volatility;
5. `sentiment_events` — verified events, market narrative, sentiment limits;
6. `valuation` — method-routed market context and scenarios;
7. `governance_risk` — governance, capital allocation, structural risks.

Each dimension uses:

```json
{
  "status": "ready | limited | blocked",
  "conclusion": "company-specific conclusion",
  "key_findings": [{"text": "...", "evidence_fields": ["revenue"]}],
  "counterpoints": [{"text": "...", "evidence_fields": ["cfo"]}],
  "uncertainties": [{"text": "...", "evidence_fields": ["working_capital"]}],
  "key_metrics": [
    {
      "label": "年度净利率",
      "calculation": "ratio",
      "display": "percent",
      "evidence_refs": [
        {"source_id": "SRC_ANNUAL", "field_name": "net_income", "period": "2025FY"},
        {"source_id": "SRC_ANNUAL", "field_name": "revenue", "period": "2025FY"}
      ]
    }
  ],
  "evidence_fields": ["canonical_field_name"]
}
```

A dimension without a conclusion or resolvable evidence is `blocked`. A dimension with partial or estimate-only support cannot be `ready`. Every claim must be an object that names the narrowest relevant fields; string claims are rejected. Narrative numbers are never copied from free text: direct, ratio, and difference metrics are calculated from exact `source_id + field_name + period` references with currency and unit checks. Numeric prose belongs in deterministic metrics; each qualitative claim resolves its own evidence IDs.

## Evidence-constrained challenge

`debate` contains a positive and negative case. Each argument must name `evidence_fields`; the engine resolves those fields to canonical evidence IDs. An argument without evidence is not included.

```json
{
  "bull": {
    "thesis": "...",
    "arguments": [
      {"argument_id": "B1", "claim": "...", "evidence_fields": ["revenue"]},
      {"argument_id": "B2", "response_to": "R1", "claim": "...", "evidence_fields": ["cfo"]}
    ]
  },
  "bear": {
    "thesis": "...",
    "arguments": [{"claim": "...", "evidence_fields": ["cfo"]}]
  },
  "manager_summary": "...",
  "key_disagreements": ["..."],
  "resolved_disagreements": ["..."],
  "unresolved_questions": ["..."]
}
```

Every response must point to an existing argument on the opposite side. Debate challenges assumptions; it is not a source validator and does not change financial facts or model outputs.

## Research synthesis

`synthesis` must contain:

- `core_thesis`;
- `variant_view`;
- `business_quality`;
- `earnings_outlook`;
- `market_view`;
- `valuation_view`;
- `risk_reward_summary`;
- `key_uncertainties`;
- `what_would_change_the_view`;
- `evidence_fields`.

The engine only enables the V3 professional report when multi-dimensional analysis, evidence-constrained debate, and synthesis are present. Revenue and profit alone no longer qualify as a complete report.

## Report information architecture

The public HTML body is ordered as:

1. core thesis and differentiated view;
2. company and business model;
3. industry and competition;
4. fundamentals and earnings quality;
5. technical view;
6. sentiment and events;
7. valuation view;
8. governance and risk;
9. positive/negative challenge;
10. synthesis and monitoring plan.

Capability status, method gaps, data quality, source registry, and runtime diagnostics belong in a collapsed audit appendix or canonical JSON. Do not lead the report with collection mechanics.

## Output and safety invariants

- Official disclosure remains primary for critical financial facts.
- Estimates stay separate and never upgrade official coverage.
- DCF, comps, historical bands, and industry methods retain their own gates.
- Missing technical or sentiment data limits that dimension; it does not stop fundamental research.
- Integrity errors fail closed to an audit memo and remove narrative synthesis.
- Default output uses `valuation_view`, `risk_reward_summary`, uncertainties, and view-change triggers. It does not provide personalized instructions or unsupported price conclusions.

## Regression examples

- `examples/yihua-002897/` — dual business model, limited market snapshot, limited formal valuation;
- `examples/duofuduo-002407/` — cyclical materials recovery, negative cash conversion, limited market snapshot, event-driven narrative constraints.
