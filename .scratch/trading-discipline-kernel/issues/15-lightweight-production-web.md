# 15 — Lightweight production Web

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 08, 14

## Scope

Replace the current production Web with the four-item information architecture (`总览`, `组合`, `复核`, `研究`), versioned read-model routes, and AccountSnapshot draft editor. Keep Web a lightweight formal read model and account editing surface; plan confirmation, task handling, execution, and review remain Skills-first.

## Exact files and symbols

- Update `src/trading_platform/web_server.py::LocalChartWorkspaceServer::start` and its nested `Handler::{do_GET,do_POST}` with explicit versioned read routes and the shared account snapshot commands.
- Replace `web/index.html`, `web/src/app.js`, `web/src/styles.css`, and production build assets under `web/dist/`.
- Use `src/trading_platform/application/bootstrap.py::{open_read_models,open_application_commands}`; do not create a Web-specific application opener.
- Remove the unversioned `/api/workspace` route and stale prototype/legacy bundle references.

## Migration

No schema change. Web consumes the 0015–0017 read models/commands. It cannot introduce direct SQLite access, a Web-only command, or a compatibility endpoint.

## Tests

- Update `tests/platform/test_web_application_tasks.py`, `tests/platform/test_secure_workspace.py`, `tests/platform/test_chart_annotations.py`, and `tests/platform/test_account_workspace_plans.py`.
- Add `tests/platform/test_production_web.py`.
- Run build, asset hash verification, server integration, and CDP inspection of navigation, required/forbidden home fields, editor validation, console, network failures, and accessibility basics.

## Dependency

Requires 08 and 14. Ticket 16 runs the canonical fixture through the production asset tree.

## Acceptance gate

TDK-AC-031 and TDK-AC-032 pass. Primary navigation is exactly four items; the home view exposes only decision-relevant summaries; diagnostics remain behind detail views; account confirmation still requires user capability.

## Out of scope

Plan confirmation UI, task disposition UI, execution entry UI, scheduler, real-time quotes, A/B/C prototype merge, large readiness dashboards, or a Web-only workflow.

## One-way cutover

Replace and remove old `/api/workspace` callers, legacy navigation, hard-coded holding content, and superseded production bundles in the same change. Never copy A/B/C prototype business or build files into production.

## Claim record

- External seams: six explicit versioned GET routes backed by
  `open_read_models`, and the existing shared application command envelope for
  AccountSnapshot draft create/revise/confirm; static production assets remain
  the only browser shell.
- Deep-module ownership: application read models own presentation truth and
  serialization; the Web server owns HTTP security/protocol conversion only;
  the browser source owns navigation, progressive disclosure, form interaction,
  and accessible rendering without business decisions.
- Old paths to replace: `/api/workspace`, `chartGateway.workspace`, the
  single-security chart/research shell, old workspace DOM IDs, and direct
  annotation/update-authorization mutations exposed by the production page.
- Superseded artifacts to delete: stale navigation and hard-coded holding
  layout, chart/research prototype rendering modules no longer imported,
  retired workspace payload tests, hashed bundles/CSS/maps not referenced by
  the rebuilt production index, and every `/api/workspace` occurrence outside
  explicit absence assertions.

## Resolution evidence

- Production navigation is exactly `总览`, `组合`, `复核`, and `研究`.
  AccountSnapshot editing and read-only plan detail are progressive
  disclosures, not primary destinations.
- The server exposes six explicit versioned read routes and one shared
  application-command-envelope POST route. Web account mutation is restricted
  to the explicit local user and the existing AccountSnapshot named tasks.
- Removed the retired workspace/chart/update-authorization routes, chart and
  research prototype modules, KLineCharts runtime dependency and licenses,
  stale private-seam tests, and superseded hashed bundles.
- `TDK-AC-031` and `TDK-AC-032` passed in Python integration tests and the
  production CDP verifier. The acceptance validator independently verified the
  evidence and all four screenshot hashes.
- Detailed current evidence:
  `.scratch/trading-discipline-kernel/evidence/15-lightweight-production-web.md`
  and `.scratch/trading-discipline-kernel/evidence/15-browser-cdp.json`.
