# Agent Rules for Equity Research Skill

These rules apply to work under `skills/` and especially the `equity-researcher` skill.

## Financial Output Boundary

- Do not provide personalized investment advice.
- Do not tell a user to buy, sell, hold, add, reduce, or avoid a security.
- Default outputs must not contain BUY/HOLD/SELL, 买入/卖出/持有, 可以买, 不能买, target-price conclusion, or house-style rating language.
- Use research-language fields by default: `valuation_view`, `risk_reward_summary`, `data_quality_grade`, `key_uncertainties`, and `what_would_change_the_view`.
- Rating language is allowed only when `user_requested_rating = true`, all data gates pass, and the output includes a non-investment-advice boundary.

## Data Rules

- Do not fabricate financial data, market data, consensus data, citations, or source metadata.
- Official disclosure is primary for critical financial data:
  - A-share: CNINFO, SSE/SZSE/BSE announcements, company IR reports.
  - HK: HKEXnews and company IR reports.
  - US: SEC EDGAR/XBRL and company IR reports.
- iFind, Yahoo, and other terminals are optional secondary sources for structuring, market data, or cross-checking. They cannot be the sole authority for critical financial statements.
- Every critical number must be in `source_manifest` with `source_id`, or explicitly marked `missing`.
- Missing official source for critical financial data means no valuation conclusion, target price, or rating.

## Valuation Rules

- Do not default to DCF for L2.
- Run `valuation/valuation-method-router.md` before valuation.
- Run `valuation/dcf-and-sensitivity.md` applicability gate before any DCF tab, WACC table, or DCF-derived value.
- Financial firms disable ordinary FCFF/WACC DCF; use P/B x ROE/COE, DDM, residual income, or excess return.
- Pre-revenue or pipeline-driven biopharma should route to rNPV/SOTP and cash runway analysis.
- Cyclical/resource companies require mid-cycle or NAV framing; do not extrapolate peak commodity prices into perpetuity.
- If fewer than 3 usable peers remain after source/currency/accounting checks, comps cannot support a valuation conclusion.

## Degradation Rules

- If critical data, required official sources, selected-method inputs, or required tools/APIs are unavailable, produce `data_insufficient_memo`.
- A data insufficient memo may include research notes, source gaps, disabled-method reasons, and next data requirements.
- A data insufficient memo must not include target price, rating, buy/sell advice, or probability-weighted target.
- Tool/API unavailability must be recorded; never invent data to keep the workflow moving.

## Phase 0 Scope

- Do not implement full `model_validator.py` or `source_manifest_validator.py` as part of Phase 0.
- Do not generate stock reports while patching this skill.
- Keep changes scoped to safety boundaries, source gates, valuation method routing, DCF applicability, source manifest schema, and degradation behavior.
