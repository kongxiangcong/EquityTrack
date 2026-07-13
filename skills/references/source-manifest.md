# Source Manifest Schema

The active research workflow uses `source_manifest_version: 2`. Version 1 remains supported for legacy report gates.

This file defines the minimum source manifest required before an equity research output can contain valuation conclusions.

The manifest may be written as Markdown, YAML, or JSON, but it must preserve the fields below. Every critical number used in research, modeling, charts, or valuation must either reference a `source_id` or be marked `missing`.

---

## Manifest Schema

```yaml
source_manifest_version: 1
company:
  name:
  ticker:
  market:
  reporting_currency:
  trading_currency:
  accounting_standard:
  latest_financial_period:
sources:
  - source_id:
    tier: official | terminal | secondary | news | estimate | missing
    market:
    publisher:
    title:
    official_or_secondary: official | secondary
    url_or_api:
    retrieved_at:
    query_params:
    filing_period:
    report_date:
    currency:
    unit:
    raw_file_path:
    raw_file_sha256:
    page_or_table:
    extracted_fields:
      - field_name:
        period:
        value:
        unit:
        currency:
        extraction_method:
        confidence: high | medium | low | missing
        notes:
    cross_checks:
      - source_id:
        status: match | mismatch | not_checked
        notes:
missing_critical_data:
  - field_name:
    required_for:
    missing_reason:
    next_data_required:
unavailable_tools:
  - tool_name:
    attempted_use:
    fallback_used:
```

---

## Official Source Requirements

Critical financial statement data must prioritize official disclosure:

| Market | Official Sources |
|--------|------------------|
| A-share | CNINFO, SSE/SZSE/BSE announcements, company IR annual/interim/quarterly reports |
| HK | HKEXnews, company IR annual/interim reports |
| US | SEC EDGAR filings, companyfacts/companyconcept XBRL APIs, company IR annual/quarterly reports |

iFind, Yahoo, Kimi Code CLI / `kimi-datasource`, and other terminals are optional secondary sources for structure, market data, gap filling, and cross-checking. They cannot be the sole source for critical financial statement history.

For Kimi-assisted gap filling:
- Set `tier: terminal` when Kimi retrieves terminal-style structured data, otherwise set `tier: secondary`.
- Set `official_or_secondary: secondary` unless the manifest also stores the underlying official filing artifact and page/table reference.
- Set `url_or_api` to `kimi-datasource:<dataset/tool/query>` when Kimi does not provide a public URL.
- Set `raw_file_path` and `raw_file_sha256` to the saved raw Kimi response, and keep parsed JSON/QA notes beside it.
- Add `cross_checks` against official filings when the field is critical. If the cross-check is `mismatch`, `conflict`, or `not_checked` for a critical field that requires official support, keep the field in `missing_critical_data`.

---

## Critical Number Coverage Gate

The following must be `source_id` covered or explicitly `missing`:

- Revenue, EBIT/operating income, net income, EPS, tax, D&A, CapEx, CFO, FCF, working capital.
- Cash, debt, lease debt, preferred stock, minority interest, pension deficit, associates/JV value, non-operating assets.
- Diluted shares, SBC/options dilution, market cap, current price, FX rate when applicable.
- Peer market cap/EV, multiples, reporting period, currency, unit.
- DCF inputs if DCF is allowed: WACC components, terminal growth basis, terminal state assumptions.
- Financial firm inputs: book value, ROE, COE, regulatory capital, credit/underwriting quality.
- Biopharma rNPV inputs: asset, indication, phase, geography, rights ownership, PoS basis, launch/peak sales, license terms, cash runway.

---

## Version 2 capability degradation

For version 2, declared or uncovered critical fields limit only the capabilities and methods that depend on them. The standalone validator returns `passed: true` with `source_manifest_status: valid_with_limits`; `limitations.missing_critical_fields` records the exact gaps. ResearchEngine then determines `completed_with_limits`, method blocks, and output permissions.

Integrity failures remain global failures: invalid identity or time metadata, malformed numeric evidence, broken raw hashes when supplied, unresolved source conflicts, or provenance classification conflicts return `passed: false` and fail closed.

## Version 1 Data Insufficient Memo Trigger

For version 1 legacy gates, set `source_manifest_status = insufficient` and produce `data_insufficient_memo` when:

- Latest critical financial statements lack official-source coverage.
- Per-share valuation bridge fields are missing.
- Selected valuation method inputs are missing.
- Required tool/API access fails and no official fallback is available.
- Source conflicts remain unresolved for critical fields.

When this trigger fires, the skill must not output target price, rating, buy/sell advice, or probability-weighted target.

---

## Executable Validation

Run the validator before method execution and before publishing any research report:

```bash
python skills/scripts/source_manifest_validator.py --manifest path/to/source_manifest.json --pretty
```

The validator always prints a validation result JSON object:

```json
{
  "validator": "source_manifest_validator",
  "passed": true,
  "source_manifest_status": "sufficient | valid_with_limits",
  "data_insufficient_memo_required": false,
  "limitations": {
    "missing_critical_fields": [],
    "declared_missing_fields": []
  },
  "summary": {
    "sources_total": 2,
    "critical_fields_required": 23,
    "critical_fields_source_covered": 23,
    "hash_checks": 2,
    "errors": 0,
    "warnings": 0
  },
  "issues": []
}
```

Exit code is `0` only when there are no error-severity issues. Any error means the workflow must stop before valuation conclusions. If the result sets `data_insufficient_memo_required = true`, produce `data_insufficient_memo` and do not output target price, rating, buy/sell advice, or probability-weighted target.

### Supported Inputs

- JSON is the default supported format.
- YAML is supported when PyYAML is installed. If PyYAML is unavailable, the validator returns structured JSON with `YAML_SUPPORT_UNAVAILABLE` instead of crashing.
- Markdown files are supported when they contain a fenced `json`, `yaml`, or `yml` source manifest block.

### Checks Performed

The validator checks:

- Required root, company, source, and extracted-field schema fields.
- `source_id` uniqueness and cross-check references.
- Critical field coverage by `source_id` or explicit `missing_critical_data`.
- Official-source coverage for critical financial statement fields.
- `raw_file_path` existence and `raw_file_sha256` match.
- Currency, unit, and period consistency.
- Unresolved source conflicts (`mismatch`, `conflict`, or `unresolved` cross-check status).

### Fixture Smoke Tests

Use the included fixtures to verify the validator itself:

```bash
python skills/scripts/source_manifest_validator.py --manifest skills/scripts/fixtures/source_manifest/pass_manifest.json --pretty
python skills/scripts/source_manifest_validator.py --manifest skills/scripts/fixtures/source_manifest/fail_manifest.json --pretty
```

The first command should pass with `source_manifest_status = sufficient`. The second command should fail and report representative hard errors.
