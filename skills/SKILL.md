---
name: equity-researcher
description: Operate the local personal research platform and generate evidence-constrained equity research. Use for platform bootstrap, doctor, migration, sync, daily jobs, serving, tests, backup, restore, workflow resume/history, or company research and valuation requests. Never provide personalized trading instructions.
---

# Personal Research Platform

## Platform operations route

For initialization, maintenance, recovery, or local service requests, use the single deterministic control plane below. Do not assemble ad-hoc SQLite, archive, or server commands and do not load prompts into the business runtime.

```powershell
python -m trading_platform.cli bootstrap --data-root <root>
python -m trading_platform.cli health --data-root <root>
python -m trading_platform.cli doctor --data-root <root>
python -m trading_platform.cli migrate --data-root <root>
python -m trading_platform.cli sync --data-root <root> --job-file <job.json>
python -m trading_platform.cli daily --data-root <root> --job-file <job.json>
python -m trading_platform.cli research --data-root <root> --request-file <request.json>
python -m trading_platform.cli provider-qualify --data-root <root> --job-file <job.json>
python -m trading_platform.cli acceptance --data-root <root> --fixture-manifest <manifest.json> --live-qualification-artifact-id <artifact_id>
python -m trading_platform.cli serve --data-root <root> --web-root <web/dist> --security-id <id> --snapshot-id <id>
python -m trading_platform.cli test --repo-root <repo>
python -m trading_platform.cli inventory --repo-root <repo>
python -m trading_platform.cli backup --data-root <root> --archive <outside-root.zip>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <new-root>
python -m trading_platform.cli switch-restored-root --restored-root <validated-new-root> --pointer-file <active-root.json>
python -m trading_platform.cli resume --data-root <root> --workflow-run-id <id> --owner-token <token>
python -m trading_platform.cli history --data-root <root> --workflow-run-id <id>
python -m trading_platform.cli archive --data-root <root> --kind manifest --id <id>
```

Only `ProviderJob@2` is accepted. Its provider block contains only `provider_id`, `adapter_version`, and `credential_env`; the production composition owns the fixed approved destination and transport. Immutable `QueryPolicy@1` owns typed dataset queries and `SourcePolicy@1` owns source authority, rights, freshness, completeness, retry, fallback, and failure disposition. There is no caller-supplied endpoint, provider class selector, or implicit fallback order. Keep only `credential_env = TUSHARE_TOKEN` in the job; the token value must remain in the process environment or an approved credential adapter. `provider-qualify` runs the same raw, normalization, quality, PIT, and persistence path as `sync`, persists a `ProviderQualificationReceipt@1` through the data root's authoritative object/artifact/command-receipt path, and returns its artifact ID. Acceptance resolves only that ID and rejects caller-authored qualification files.

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

The formal CLI invokes the named lifecycle task:

```python
ResearchWorkflow.handle(StartResearchWorkflow(request)) -> ResearchWorkflowResult
```

`WorkflowInspection`, `ResearchArchive`, and `ForecastReview` are separate
query/task seams. New execution uses typed request and artifact contracts; no
formal renderer reads source narrative magic keys or reconstructs valuation
semantics.

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
