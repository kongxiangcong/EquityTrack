# Company outlook journey acceptance ledger

Status: in progress with all currently executable verification complete. The
real Duofuduo typed valuation/simulation chain remains disabled until its
official dilution bridge and selected-method inputs are available.

This ledger records the deterministic acceptance run for Ticket 13. It is a
research-system verification record, not an investment recommendation or a
price conclusion.

## Yihua 002897.SZ complete typed journey

- Public boundary: `ProductionCompositionRoot.facade.run_research_workflow`.
- ResearchRun: `rr_caba6d06307d38bf` (`completed_with_limits` in the platform history; canonical decision-view status `partial`).
- PIT research snapshot: `snapshot_c67dc414001ffa2a76259911`.
- Deterministic acceptance ArtifactManifest: `manifest_1f573016751e8eec9977ea8d`.
- Canonical decision JSON SHA-256: `c8f99580973d17eb85e8c243b072117905651e8905a658df5202089e7e973bed`.
- Canonical report HTML SHA-256: `3b0c0dd3d02d907528761391d82da36d53fa637f73c1b92ffe96adb601c500d9`.
- DataSnapshot: `d981853a72a271c4ef89e7dbed67c167bc33a4ec7945bef351b13c3257e909a6`.
- Forecast: `5a01775d483881cc5f4dd9f7129ff32a3afc3be327cf3f955a3e4da2a864d224`.
- Valuation: `921b281aea88aef9763265b4eddabf78741e1bf23a842053a0328bb33a028736`.
- Valuation Simulation: `321afdd120736a21d060c6eea7db3d2587a26d1a55fa60c2c3173de1286fc3db`.
- MarketDataSnapshot: `1692b594a086aec67eb08be8481be84e3d71e76bbbd36a80f7b60db12d3d7e04`.
- MarketPathSimulation: `8a928078bde7e0411f6065e0a86714403ffa5b4cb4dfbccf62d6abb52d3a7a9a`.
- Verified methods: FCFF DCF, segment SOTP and reverse DCF across stress, base and improvement scenarios.
- Verified presentation: future story, key drivers, scenario financials, valuation distribution, separate traded-price paths, non-comparable-horizon explanation and progressive audit data.
- Restart evidence: the same request after closing and reopening the composition root reuses the ResearchRun, snapshot and all six typed artifact record IDs with identical content hashes.

## Duofuduo 002407.SZ real-source degradation

- Public boundary: `ProductionCompositionRoot.facade.run_research_workflow`.
- ResearchRun: `rr_a5ffcbb3af1a3025`.
- PIT research snapshot: `snapshot_9fe70654b719a643bf99cc4f`.
- Deterministic acceptance ArtifactManifest: `manifest_c0eea6ae2bf5e7772a884c07`.
- Canonical research JSON SHA-256: `62115c835cc2392a223bc105db413d0584365d62f676e8641173b9072c5dd8b5`.
- Canonical report HTML SHA-256: `026e105dea9cafb7c3e0834f57d843f08aed8911739b052a0be6a11bd83217f9`.
- Official-source gap: no precise diluted weighted-average share count or complete dilution bridge is present in the frozen manifest.
- Subsequent-announcement check: the local 2026 Q2 announcement index contains no new equity-incentive, employee-stock-plan, repurchase-cancellation or convertible-bond disclosure that closes that bridge.
- Enforced result: `formal_per_share_valuation = false`; no diluted-share fact or typed per-share valuation artifact is invented.
- The report preserves the cycle-recovery story, long-duration business options, explicit SOTP double-counting prevention, capital-expenditure and funding-cost constraints.
- Restart evidence: the reopened composition root reuses the same ResearchRun and research snapshot and reopens the final manifest.

The independent cyclical model golden is intentionally not labelled as
Duofuduo evidence. It verifies the method family (mid-cycle EV/EBITDA,
finite-resource NAV and PIT historical band), cycle-linked sensitivities,
equity bridge and fail-closed stable-growth DCF routing using synthetic frozen
fixtures. A full typed Duofuduo valuation remains disabled until the official
dilution bridge and other method inputs listed in its source manifest are
available.

## Executable evidence

- `tests/platform/test_company_outlook_journeys.py` covers both public-facade journeys, restart/reuse, artifact hashes, decision view, prohibited-language scan and the separate cyclical golden.
- `tests/platform/test_research_workflow.py::test_missing_diluted_shares_reaches_capability_degradation` proves an explicitly declared source gap reaches capability degradation instead of failing before ResearchRun persistence.
- `tests/platform/test_market_path_simulation_artifact.py` proves market paths are independent of intrinsic-value simulation and remain bound to the frozen market snapshot.

## Verification and review results

- With `CODEX_ARTIFACT_NODE` and `CODEX_ARTIFACT_NODE_MODULES` bound to the bundled workspace runtime, the final zero-skip `py -m pytest -q` run passed all 351 tests in 577.95 seconds.
- `npm test` under `web/`: 17 passed.
- `npm run build` under `web/`: Vite 7.0.6 production build succeeded and the third-party notice/license payload was copied.
- Changed-file Ruff check passed for `research/assembler.py`, `research_view.py` and the new journey test. The repository-wide Ruff run is not a release gate today and reports 428 pre-existing findings outside this ticket.
- Real in-app Chromium: desktop 1280x720 and narrow 390x844 journeys loaded the persisted `completed_with_limits` ResearchRun, six typed artifacts, three scenarios, valuation distribution and independent market paths. The narrow document width equalled the 390px viewport (375px client width excluding the vertical scrollbar), research cards remained inside the viewport and controls were 42px high.
- Accessibility/interaction: semantic headings, regions, buttons, combobox and disclosure controls were present; reduced-motion state toggled; the provenance disclosure opened and exposed the canonical 213,207-character audit payload; disclosures were closed by default; the console had no warning or error entries; the rendered page contained none of the prohibited default-output terms scanned by the acceptance test.
- Independent Standards and Spec reviews both returned clean after the declared-gap assembler path and exact typed-artifact replay assertions were strengthened.
