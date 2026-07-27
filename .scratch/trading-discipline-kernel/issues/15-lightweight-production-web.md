# 15 — Lightweight production Web

**Status:** ready-for-agent  
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
