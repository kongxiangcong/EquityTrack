# Decision Core rebuild baseline

Captured from `8a74d822` on 2026-08-29. This inventory describes the retired live runtime, not the target implementation.

## Live surface

- Public command: `trading-platform` / `python -m trading_platform.cli`, with the command set assembled in `src/trading_platform/cli.py`.
- Application seam: the task classes and command envelopes under `src/trading_platform/application/`.
- Domain records: the overlapping records under `src/trading_platform/domain/`, `src/trading_platform/research/`, and `src/equity_research/`.
- Persistence: one SQLite data root plus 25 incremental SQL files in `migrations/` and specialized repositories under `src/trading_platform/persistence/`.
- Skill: `skills/SKILL.md` routes the old account status, cycle review, equity research, and trade plan tasks.
- Presentation/artifacts: persisted JSON/HTML/PDF/workbook/chart bundles, `web/`, report renderers, examples, and lineage/manifest records.
- Dependencies: runtime `reportlab`; optional `websocket-client`; browser assets and their npm dependency graph.

## Retirement matrix

| Retired ownership | Production callers / records | Persistence | Tests / fixtures | Control plane / artifacts | Disposition |
| --- | --- | --- | --- | --- | --- |
| research runs and snapshots | `workflows/research.py`, research task/publication/bundle code, `equity_research` | research request/run, snapshot, bundle, evaluation and workflow tables | research workflow, publication, bundle, component-input and model tests | equity-research task, source manifest, reports and examples | replace through `research.commit`; delete |
| portfolio snapshots and account workflows | account state/history/import, read models | account history, portfolio/read-model tables | account opening/history/state and read-model tests | account-status task and Web | replace through `account.confirm/show`; delete |
| thesis and valuation report variants | `equity_research`, workbook and PDF modules | research/valuation artifact tables | scenario, simulation, workbook and PDF tests | valuation workbook, HTML/PDF/chart assets | replace through `valuation.assess`; delete |
| plan versions, graph, AST and sleeves | plan compiler/drafting/authoring and strategies | plan graph/version/sleeve/activation tables | plan graph, compiler, sleeve, confirmation and migration tests | trade-plan task and Web | replace through `planning.prepare/confirm`; delete |
| workflow ledger and generic orchestration | workflow domain/application/persistence | workflow ledger tables | workflow ledger/recovery tests | platform control-plane docs | replace with application transaction; delete |
| artifact manifests and lineage | publication, chart, workbook, PDF, presentation | artifact/bundle/lineage tables | artifact, publication, chart and workbook tests | report layouts, CSS, Web dist and examples | SQLite-only truth; delete |
| review versions and manual-review runtime | discipline/manual review and decision journal | manual review, discipline review and journal tables | action log, review, journal and product tests | cycle-review task | replace through `review.commit`; delete |
| confirmation and approval receipts | approvals and plan confirmation code | challenge, approval and qualification receipt tables | confirmation/receipt/migration tests | trade-plan task | confirmation metadata moves to `TradePlan`; delete |
| plan impact/proposal/action logs | plan impacts and decision journal | impact/proposal/action tables | impact/proposal/action-log tests | Web and review docs | replace with evaluation/task/review; delete |

## Old-test disposition

- **Preserve behavior through the new Interface:** account immutability and unknown propagation; deterministic valuation and risk; mutation idempotency/rollback/restart; SQLite backup/restore/doctor; finite plan evaluation; two-stage review.
- **Replace at a higher Interface:** CLI/Web task tests, repository tests, workflow-ledger tests, publication/rendering tests, command-envelope tests, and private plan/research application tests.
- **Delete with retired behavior:** chart annotation, generic workflow, report/workbook/PDF, strategy catalogue/simulation, plan graph/AST/sleeve, impact/proposal/action log, confirmation challenge/receipt, and multi-format artifact tests.

## Baseline verification

`python -X utf8 -B -m pytest -q` and the same command with this worktree's `src` first on `PYTHONPATH` both stopped during collection with **24 errors**, **0 passed**, **1 deselected**, **0 skipped**, and **0 timeouts** in 7.73 s and 8.52 s respectively. Every error was the missing retired `TushareCompatibleProvider`; the first run also demonstrated a stale editable import path. These failures are baseline facts, not passes.

No network, credential, external Provider, or real data-root check was run. No generated artifact was created.
