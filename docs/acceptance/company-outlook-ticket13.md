# Company outlook journey acceptance ledger

Status: in progress. The valuation foundation is materially stronger, but
Ticket 13 is not complete.

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
- The public workflow rejects this candidate while its hash-bound source
  manifest validation is invalid. It also rejects any injected per-share
  artifact when the frozen diluted-share identity is absent.

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

## Deliberate degradation and open blockers

The source-manifest validator remains invalid. This is expected and must not be
presented as formal valuation readiness:

- seven declared raw files are absent from the repository;
- `diluted_shares`, `pension_deficit` and
  `sbc_options_dilution` are explicitly missing critical fields;
- the official pension and dilution bridges are therefore incomplete.

Duofuduo also lacks a formal independent MarketPathSimulation. The gateway did
not yet expose a 2026-07-17 starting close during this run, and data newly
retrieved on 2026-07-17 cannot be relabeled as a snapshot frozen on an earlier
date. A future completion must bind both calibration series and starting close
to a platform market snapshot whose retrieval and availability timestamps
satisfy one research as-of boundary. Until then, the complete six-artifact
journey and value/market-path comparison remain unchecked.

## Current executable evidence

- Decision-first formal report acceptance: the five-question story is the
  initial visible hierarchy; scenario Drivers, financials and low/base/high
  ranges are present; secondary narrative and the complete audit ledger are
  progressively disclosed.
- Final real-browser report verification passed at 390 x 844 and at a 240 px
  equivalent double-zoom layout without document-level horizontal overflow.
  All native summary controls were focusable; disclosure interactions retained
  focus and exposed the expected typed audit groups.
- Full Python suite: 368 passed in 542.45 seconds.
- Focused valuation, forecast, simulation, source-gate, decision-view and
  journey suite: 130 passed in 95.03 seconds.
- Web decision-view suite: 18 passed, including an enterprise-value labeling
  regression.
- Valuation workbook suite: 4 passed with the bundled Node runtime.
- Public acceptance CLI regression: 1 passed.
- Real in-app Chromium acceptance passed for enterprise-value labeling and the
  narrow mobile wrapper, with no unintended per-share presentation.
- Final standards and specification reviews found no P0/P1 findings.
- Ruff over every changed Python source and test file: passed.
- Source-manifest validator: intentionally failed closed with 10 errors
  (seven absent raw files and three missing critical bridge fields).
- The four repository-bound Duofuduo candidate assets pass their declared hash
  checks. Final public-journey hash acceptance remains blocked by the seven
  absent raw source files; historical results are not reused as current
  completion evidence.
