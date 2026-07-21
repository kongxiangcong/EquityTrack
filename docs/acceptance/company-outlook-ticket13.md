# Company outlook journey acceptance ledger

Status: complete.

This record verifies research-system behavior. It is not an investment
recommendation or a price conclusion.

## What is now verified

### Valuation level semantics

- Enterprise value, equity value and per-share value are separate typed levels.
- An enterprise-value method may remain usable when the equity bridge is
  incomplete.
- Missing pension adjustment blocks the enterprise-to-equity bridge instead of
  being interpreted as zero.
- Missing diluted shares or dilution instruments blocks per-share conversion.
- The Duofuduo model candidate therefore stops at a mid-cycle enterprise-value
  range; equity value and per-share value remain null.
- The public workflow now publishes the unaffected enterprise-value methods
  under `valid_with_limits`. It still rejects any injected per-share artifact
  when the frozen diluted-share identity is absent.

### Cyclical manufacturing route

- Duofuduo uses the explicit `cyclical_manufacturing` archetype.
- Mid-cycle EV/EBITDA is available for stress, base and improvement scenarios.
- Ordinary stable-growth DCF remains disabled.
- Reserve-backed NAV and the PIT historical valuation band fail independently
  when their own inputs are absent; they do not suppress the applicable
  mid-cycle method.
- Long-duration business options are scenario assumptions and are protected
  from being added twice after consolidated operating valuation.

### Calibrated valuation simulation

- The Duofuduo simulation models enterprise value in CNY, not a per-share
  result.
- Its two empirical inputs use 28 frozen single-quarter observations derived
  from 32 version-selected cumulative income-statement rows returned by the
  preconfigured non-official Tushare-compatible gateway. Raw selected rows and
  row-level derivations are separate hash-checked assets.
- The dependency correlation is estimated from the paired sample rather than
  supplied as an analyst override.
- The run records seed, RNG algorithm, sample budget, batch size, convergence
  tolerance, invalid-path ceiling, sensitivity contributions and tail
  threshold.
- This secondary calibration source does not upgrade official financial-data
  authority.

### Typed investment story

- Formal story fields are declared as typed Forecast narrative statements.
- Statements classify fact, assumption, judgment or risk bases. Fact refs bind
  to the DataSnapshot; assumption refs bind to typed assumptions with as-of,
  rationale and fact lineage.
- Analyst cycle curves are quantified assumptions, not PIT facts. Reported,
  source-extracted, calculated-from-official and model-derived evidence are
  distinct. Only values with supported deterministic formulas and verifiable
  official operands qualify as calculated-from-official.
- The decision view no longer reads legacy `analysis` or `synthesis`
  dictionaries to construct the formal story.
- The Duofuduo story covers core thesis, variant view, business quality,
  earnings path, valuation interpretation, risk/reward, uncertainties,
  double-counting guardrails and conditions that would change the view.

### Public six-artifact journey and PIT market path

- Both Yihua and Duofuduo now publish `DataSnapshot`, `Forecast`, `Valuation`,
  `Simulation`, `MarketDataSnapshot` and `MarketPathSimulation` through the
  canonical research task.
- Duofuduo uses a hash-bound 73-row daily/adjustment-factor raw asset. The
  simulation window begins after the last adjustment-factor change and ends on
  2026-07-16; the frozen starting close is the 2026-07-17 session.
- Research `as_of=2026-07-18` is distinct from
  `effective_session=2026-07-17`. Availability and retrieval timestamps remain
  separate, so no later retrieval is relabeled as an earlier PIT snapshot.
- Tick-rounded A-share limit prices are validated with a half-tick tolerance;
  nominal 10% limits are not rejected solely because the legal close is rounded
  to CNY 0.01. Tick size is an explicit typed policy input, not inferred from a
  policy-name string.
- A prior effective session is validated against the frozen market-data
  snapshot's `effective_session_date`; no weekday/weekend heuristic substitutes
  for the trading calendar.
- Enterprise-value simulation (`CNY`) and market-price paths (`CNY/share`) may
  coexist. The decision view marks them `not_comparable` and does not compute a
  false numerical divergence.
- Restart/replay reuses the same six core artifact record IDs and content
  hashes.

## Deliberate degradation

The source-manifest validator now returns `valid_with_limits`, with 11 raw
assets hash-checked and no integrity errors. Formal per-share readiness remains
disabled because:

- `diluted_shares`, `pension_deficit` and
  `sbc_options_dilution` are explicitly missing critical fields;
- the official pension and dilution bridges are therefore incomplete.

The previously declared Eastmoney IR PDF was removed after verification showed
that it belonged to another listed company. The same 65,000-ton LiPF6 capacity
fact is now bound to the official 2025 annual report. The abnormal-volatility
evidence now uses the official CNINFO filing rather than a secondary mirror.
The official Q1, annual-report, disposal and abnormal-volatility records carry
separate `published_at`, `available_at` and `retrieved_at` timestamps.

## Current executable evidence

- Decision-first formal report acceptance: the five-question story is the
  initial visible hierarchy; scenario Drivers, financials and low/base/high
  ranges are present; secondary narrative and the complete audit ledger are
  progressively disclosed.
- Current-HEAD real-browser verification was refreshed on 2026-07-19 from the
  public six-artifact journey, not from the older four-artifact report or the
  enterprise-value label fixture. The report was reproduced with
  `test_duofuduo_real_sources_degrade_without_inventing_dilution` and materialized
  from the persisted `ResearchDecisionHtml@1` object at
  `.scratch/ticket13-browser-current/report-current.html` (SHA-256
  `F70DE0D390F4650C7F4AC38FFFCEDF3BFFCA171ED08FF66BCF854BC328C73554`).
- The embedded `ResearchDecisionView@2` has `as_of=2026-07-18` and exactly six
  audit records: `DataSnapshot`, `Forecast`, `Valuation`, `Simulation`,
  `MarketDataSnapshot` and `MarketPathSimulation`; each record exposes a
  64-character content hash. Valuation and market-path simulations are ready,
  divergence is `not_comparable`, and formal per-share permission is false.
- At the 390 x 844 mobile override, the current report had no document-level
  horizontal overflow. It exposed nine native summary controls; clicking the
  first retained focus on `SUMMARY`, opened exactly one disclosure and revealed
  the expected secondary narrative. The default desktop viewport also had no
  horizontal overflow. No forbidden action/rating term was present.
- Final-code full Python suite: 374 passed, 3 skipped in 589.95 seconds.
- Web decision-view suite: 18 passed, including an enterprise-value labeling
  regression.
- Valuation workbook suite: 4 passed with the bundled Node runtime.
- Public acceptance CLI regression: 1 passed.
- Real in-app Chromium acceptance passed for enterprise-value labeling and the
  narrow mobile wrapper, with no unintended per-share presentation.
- Specification review found a caller-controlled calibration-gate tolerance;
  the gate now uses a platform-owned `1e-12` serialization tolerance and a
  canonical research-task negative test proves a forged artifact tolerance cannot mask
  changed vectors.
- Standards review found the weekend heuristic, implicit tick-size policy and
  missing official PIT timestamps. Each finding is resolved as described above.
- Python compile check passed. Ruff is not installed in either the system or
  repository virtual environment, so no new Ruff result is claimed.
- Source-manifest validator: `valid_with_limits`, 11 hash checks, zero errors,
  three explicit capability warnings.
- Focused source, market-path, workflow, journey and research-engine regression:
  92 passed in 77.86 seconds.
- Post-review focused market-path, artifact, journey and manifest regression:
  45 passed in 59.91 seconds.
- Post-review adversarial tick-size regression: 5 passed, covering NaN,
  Infinity, zero, negative and valid prior-session behavior.
- Duofuduo public six-artifact journey and restart replay: 1 passed in 8.96
  seconds.
