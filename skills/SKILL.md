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
python -m trading_platform.cli provider-qualify --data-root <root> --job-file <job.json> --output <qualification.json>
python -m trading_platform.cli serve --data-root <root> --web-root <web/dist> --security-id <id> --snapshot-id <id>
python -m trading_platform.cli test --repo-root <repo>
python -m trading_platform.cli inventory --repo-root <repo>
python -m trading_platform.cli backup --data-root <root> --archive <outside-root.zip>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <new-root>
python -m trading_platform.cli switch-restored-root --restored-root <validated-new-root> --pointer-file <active-root.json>
python -m trading_platform.cli resume --data-root <root> --workflow-run-id <id> --owner-token <token>
python -m trading_platform.cli history --data-root <root> --workflow-run-id <id>
```

Use `provider_type = tushare_compatible` for the preconfigured Tushare-compatible HTTP surface. Keep only `credential_env = TUSHARE_TOKEN` in the job; the token value must remain in the process environment or an approved credential adapter. `provider-qualify` runs the same raw, normalization, quality, PIT, and persistence path as `sync` and writes redacted attempt evidence that can be supplied to `acceptance --live-qualification-file`.

Every command emits one JSON envelope and a typed error on failure. Credentials come only from the environment named by an explicit job configuration; never put credential values in job files, command lines, logs, database fields, backups, or artifacts. Backup archives are immutable and restore only into a new data root after full validation.

For company research requests, use the typed platform route below.

# Equity Research

Use one formal workflow for every new run:

```text
Frozen DataSnapshot
  -> Forecast Graph
  -> Scenario Valuation
  -> optional Monte Carlo / Market Path Simulation
  -> ResearchDecisionView@2
  -> canonical JSON + decision-first HTML + reconciled XLSX
```

The public interface is:

```python
ApplicationFacade.run_research_workflow(request) -> ResearchWorkflowResult
```

The retained deterministic compatibility seam is
`ResearchEngine.run(ResearchRequest) -> ResearchRun`; it does not define the
formal platform presentation model. Historical `ResearchSynthesis` remains a
read-compatible part of that legacy contract.

New execution must use typed request/artifact contracts. Free-form legacy
`context` is accepted only by `LegacyResearchContextAdapter`, which converts it
to `ResearchInputs@1` and emits a versioned migration diagnostic. No formal
renderer reads `analyses`, `debate`, `synthesis`, `scenarios`, or `dcf_case`
magic keys.

Python owns identity and date checks, evidence resolution, capability
readiness, method routing, calculations, simulation, immutable artifact
identity, reconciliation, permissions, and rendering.

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

## 4. Build typed Forecast and Valuation artifacts

Represent the company story as Event -> Driver -> Forecast Financial ->
Valuation transmission. Build stress, base, and improvement scenarios from
explicit driver conditions; do not create arbitrary percentage bands.

Route each scenario through every applicable method, including industry
specializations. Use Monte Carlo only after a frozen dependency model,
distributions, constraints, and valuation model exist. Keep simulated intrinsic
value and simulated market price paths as separate artifacts.

Completion criterion: typed Forecast and Valuation artifacts reconcile their
facts, formulas, diluted shares, equity bridges, identities, and source refs.

## 5. Build the decision-first view

`ResearchDecisionView@2` is the sole formal presentation model. It must expose:

- the future story and what would change it;
- key Drivers and scenario financials;
- method applicability and conditional value ranges;
- optional valuation distributions and market paths;
- value-market divergence without action language;
- a complete audit appendix with artifact, source, parameter, formula, model,
  policy, and code identities.

Formal JSON and HTML must serialize this exact view. XLSX must import the same
view, recompute every bridge step with formulas, and fail when canonical values
are hardcoded or links are broken.

## Legacy V3 narrative compatibility

The following seven-dimension/debate/synthesis contract is retained only for
historical `research_context.json` input and legacy `ResearchRun@3` reading.
Do not use it as the new platform execution contract.

### Build the seven legacy research dimensions

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

### Run legacy evidence-constrained debate

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

### Produce legacy Research Synthesis

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

### Render and validate legacy file outputs

Run the CLI through `scripts/research.py`:

```powershell
python scripts\research.py run `
  --manifest <source_manifest.json> `
  --context <research_context.json> `
  --as-of-date <YYYY-MM-DD> `
  --output-dir <output-directory>
```

Add `--estimates <estimate_overlay.json>` only when an explicit estimate overlay exists.

Legacy compatibility artifacts:

- `research_run.json` — canonical evidence, dimensions, debate, synthesis, capabilities, methods, permissions, and diagnostics;
- `research_report.html` — self-contained professional company-research report.

The HTML body leads with the company research narrative. Put capability states, method diagnostics, source registry, and claim-to-evidence mapping in a collapsed audit appendix.

Run:

```powershell
python -B -m unittest discover -s tests -v
```

The standalone `source_manifest_validator.py`, `model_validator.py`, and
`report_validator.py` are compatibility utilities only. Formal platform
authority lives in frozen projection validation, typed artifact factories,
forecast/valuation invariants, and canonical presentation reconciliation.

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
