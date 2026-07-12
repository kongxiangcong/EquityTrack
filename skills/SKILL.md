---
name: equity-researcher
description: Operate the local personal research platform and generate evidence-constrained equity research. Use for platform bootstrap, doctor, migration, sync, daily jobs, serving, tests, backup, restore, workflow resume/history, or company research and valuation requests. Never provide personalized trading instructions.
---

# Personal Research Platform

## Platform operations route

For initialization, maintenance, recovery, or local service requests, use the single deterministic control plane below. Do not assemble ad-hoc SQLite, archive, or server commands and do not load prompts into the business runtime.

```powershell
python -m trading_platform.cli bootstrap --data-root <root>
python -m trading_platform.cli doctor --data-root <root>
python -m trading_platform.cli migrate --data-root <root>
python -m trading_platform.cli sync --data-root <root> --job-file <job.json>
python -m trading_platform.cli daily --data-root <root> --job-file <job.json>
python -m trading_platform.cli serve --data-root <root> --web-root <web/dist> --security-id <id> --snapshot-id <id>
python -m trading_platform.cli test --repo-root <repo>
python -m trading_platform.cli inventory --repo-root <repo>
python -m trading_platform.cli backup --data-root <root> --archive <outside-root.zip>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <new-root>
python -m trading_platform.cli switch-restored-root --restored-root <validated-new-root> --pointer-file <active-root.json>
python -m trading_platform.cli resume --data-root <root> --workflow-run-id <id> --owner-token <token>
python -m trading_platform.cli history --data-root <root> --workflow-run-id <id>
```

Every command emits one JSON envelope and a typed error on failure. Credentials come only from the environment named by an explicit job configuration; never put credential values in job files, command lines, logs, database fields, backups, or artifacts. Backup archives are immutable and restore only into a new data root after full validation.

For company research requests, continue with the workflow below.

# Equity Research

Use one workflow for every new run:

```text
Evidence Ledger
  -> AnalysisBundle
  -> DebateResult
  -> ResearchSynthesis
  -> ResearchRun
  -> canonical JSON + professional HTML
```

The deterministic interface is:

```python
ResearchEngine.run(ResearchRequest) -> ResearchRun
```

Skills collect evidence and prepare structured research context. Python owns identity and date checks, evidence resolution, capability readiness, method routing, calculations, permissions, report mode, and rendering.

## 1. Lock the request

Before collecting data, record:

- target company, ticker, listing venue, and market;
- `as_of_date`;
- reporting and trading currencies;
- accounting standard and latest reported period;
- requested depth and output language.

Use the same workflow for concise and deep research. Depth changes the amount of evidence and narrative, not the execution architecture or safety rules.

Completion criterion: the target identity and as-of boundary are unambiguous.

## 2. Build the Evidence Ledger

Use `references/source-manifest.md` as the manifest contract.

Prioritize:

1. exchange filings and official disclosures;
2. company investor-relations materials;
3. timestamped market-data terminals or APIs;
4. reputable news and secondary research for events and cross-checking.

Every critical number must resolve to a canonical evidence item. Keep estimates separate. An estimate may support a limited scenario but cannot upgrade official coverage.

If a field is unavailable, record it as missing and continue with unaffected capabilities. Do not use a single source-status flag to stop the whole run.

Completion criterion: every accepted fact has source identity, subject, period, unit, currency, availability date, and extraction metadata.

## 3. Route valuation methods

Read `valuation/valuation-method-router.md` before valuation. Read `valuation/dcf-and-sensitivity.md` only when DCF is selected or explicitly requested.

Apply method-specific gates:

- ordinary FCFF/WACC DCF requires an explicit forecast case, auditable WACC components, `WACC > g`, and a complete equity bridge;
- financial firms use P/B–ROE/COE, DDM, residual-income, or excess-return framing;
- pre-revenue biopharma uses rNPV/SOTP and cash-runway analysis;
- cyclical and resource companies use mid-cycle, SOTP, or NAV framing;
- peer conclusions require at least three comparable, source-compatible companies.

A disabled method limits only that method. It does not erase valid company research.

Completion criterion: every candidate method is `ready`, `limited`, `caution`, `blocked`, or `disabled`, with an evidence-backed reason.

## 4. Build the seven research dimensions

Set `report_version = 3` and provide all dimensions under `analyses`:

1. `business` — products, customers, business model, segment economics, capital intensity;
2. `industry` — cycle, supply chain, competition, barriers, relative position;
3. `fundamentals` — growth, margins, cash conversion, balance sheet, earnings quality;
4. `technical` — price, volume, momentum, volatility, and market structure when supported;
5. `sentiment_events` — verified events, expectations, narrative, and sentiment limits;
6. `valuation` — method-routed market context and scenarios;
7. `governance_risk` — capital allocation, governance, structural risks, thesis breakers.

Each non-blocked dimension must contain:

- a company-specific conclusion;
- at least one evidence-bound finding;
- at least one evidence-bound counterpoint;
- at least one evidence-bound uncertainty;
- deterministic metrics where numeric evidence exists.

Use explicit qualitative claims:

```json
{
  "text": "Latest reported profit improved while cash conversion remained weak.",
  "evidence_fields": ["net_income", "cfo"]
}
```

String-only claims are not accepted. Put numeric facts in deterministic metrics, not prose.

Use exact metric references:

```json
{
  "label": "Annual net margin",
  "calculation": "ratio",
  "display": "percent",
  "evidence_refs": [
    {"source_id": "SRC_ANNUAL", "field_name": "net_income", "period": "2025FY"},
    {"source_id": "SRC_ANNUAL", "field_name": "revenue", "period": "2025FY"}
  ]
}
```

The engine supports `direct`, `ratio`, and `difference` calculations only after exact source, subject, semantic-role, unit, and currency checks.

Missing price history limits the technical dimension to a market snapshot. Missing sentiment samples limits sentiment analysis. Neither blocks supported fundamental research.

Completion criterion: every non-blocked dimension has conclusion, finding, counterpoint, uncertainty, and resolved evidence IDs.

## 5. Run evidence-constrained debate

Build positive and negative cases. Every argument needs:

- a unique `argument_id`;
- a qualitative `claim` without unbound numbers;
- explicit `evidence_fields`;
- `response_to` when challenging an argument on the opposite side.

Require both sides to respond to the opposing case. Record:

- `manager_summary`;
- `key_disagreements`;
- `resolved_disagreements`;
- `unresolved_questions`.

Reject missing, same-side, or dangling response links.

Completion criterion: both cases have sourced arguments and a valid cross-side challenge-response chain.

## 6. Produce Research Synthesis

Synthesis must include:

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

Use research language. Keep all numeric facts in deterministic metric or method outputs.

Completion criterion: synthesis resolves all declared evidence fields and remains consistent with dimension and debate results.

## 7. Render and validate

Run the CLI through `scripts/research.py`:

```powershell
python scripts\research.py run `
  --manifest <source_manifest.json> `
  --context <research_context.json> `
  --as-of-date <YYYY-MM-DD> `
  --output-dir <output-directory>
```

Add `--estimates <estimate_overlay.json>` only when an explicit estimate overlay exists.

Required artifacts:

- `research_run.json` — canonical evidence, dimensions, debate, synthesis, capabilities, methods, permissions, and diagnostics;
- `research_report.html` — self-contained professional company-research report.

The HTML body leads with the company research narrative. Put capability states, method diagnostics, source registry, and claim-to-evidence mapping in a collapsed audit appendix.

Run:

```powershell
python -B -m unittest discover -s tests -v
```

Completion criterion: JSON and HTML come from the same `ResearchRun`, validation passes, and the report contains no unsupported numeric or action language.

## Financial boundary

- Provide educational company research, not personalized investment instructions.
- Use `valuation_view`, `risk_reward_summary`, `data_quality_grade`, `key_uncertainties`, and `what_would_change_the_view`.
- Do not publish a formal per-share valuation when its selected method or critical official inputs are blocked.
- Integrity errors fail closed to an audit memo and remove professional synthesis.
- A `completed_with_limits` run is a valid outcome when useful research is complete but some dimensions or methods remain limited.

## On-demand references

- Source schema and evidence rules: `references/source-manifest.md`
- Valuation routing: `valuation/valuation-method-router.md`
- Industry method matrix: `valuation/industry-valuation-matrix.md`
- Conditional DCF rules: `valuation/dcf-and-sensitivity.md`
