# 00 — Authority baseline and branch cleanup

**Status:** resolved  
**Type:** task  
**Mode:** AFK  
**Blocked by:** none

## Scope

Capture a live, reproducible implementation baseline before any schema or runtime change. Protect user-owned dirty paths, identify the canonical application seams, inventory obsolete paths that later tickets must delete, and define the exact release cohorts for migrations 0015–0017. “Cleanup” means classification and removal of demonstrably generated/stale kernel artifacts only; it does not authorize rewriting or deleting unrelated dirty work.

## Exact files and symbols

- Read and hash `AGENTS.md`, `docs/prompts/trading_platform_codex_prompt_optimized.md`, `CONTEXT.md`, this Wayfinder directory, and `skills/SKILL.md`.
- Inventory `src/trading_platform/application/bootstrap.py::{open_trade_plan,open_decision_workspace,open_market,open_account,open_daily_research_cycle}`.
- Inventory `src/trading_platform/application/web_tasks.py::{DecisionWorkspace,PlanConfirmation}`.
- Inventory `src/trading_platform/web_server.py::LocalChartWorkspaceServer::{start,close}` including nested `Handler::{do_GET,do_POST}`, plus `web/index.html`, `web/src/app.js`, and `web/dist/`.
- Inventory `src/trading_platform/persistence/migration.py::MigrationRunner::{validate,migrate,_migrate_locked}` and migrations 0001–0014.
- Add implementation evidence only under `.scratch/trading-discipline-kernel/evidence/`.

## Migration

No schema change. Record the hashes and release-cohort ownership of the future `0015_account_snapshot_version.sql`, `0016_strategy_plan_model_b.sql`, and `0017_manual_review_journal.sql`.

## Tests

- Run the existing focused account, plan, market evaluation, Web, operations, recovery, and acceptance suites.
- Record exact commands, durations, passed/failed/skipped/timeouts, and live schema version.
- Search for `/api/workspace`, `user_fixture_input`, `open_daily_research_cycle`, direct SQLite callers, and prototype build references.

## Dependency

None. All later tickets require this evidence.

## Acceptance gate

A checked-in baseline manifest records HEAD, branch, dirty-path allowlist, authority-document hashes, database schema version, current suite results, canonical public symbols, and removal inventory. No startup dirty file outside the ticket’s evidence directory is changed.

## Out of scope

No domain, application, migration, Skill, CLI, or Web behavior changes. Do not merge, stage, commit, push, reset, or clean user work.

## One-way cutover

This ticket names the paths to be removed but retains them until their owning replacement ticket lands. It must not introduce a second authority document, compatibility plan, or alternate command path.

## Claim record

- External seams: Git HEAD/status and authority documents; the canonical
  application openers; SQLite migration ledger; production Web source/build;
  focused public-interface suites.
- Deep-module ownership: this ticket owns evidence capture only. It assigns
  account truth to ticket 01, estimated state to 02, plan graph/strategy/rules
  to 03–07, command transport to 08, review journal to 09–13, read projections
  to 14, Web presentation to 15, and final acceptance to 16.
- Old-path replacement inventory: account-opening/current-position reads,
  singular `get_active_for_security`, AST@1, `user_fixture_input`, direct
  confirmation by plan ID, `DecisionWorkspace`, `/api/workspace`, public
  `daily`, and Web-specific mutation routes.
- Superseded artifacts to delete in owner tickets: old account/plan schema
  readers and private-seam tests; AST@1 fixtures; unversioned workspace DTO and
  route tests; stale Skill/CLI instructions; retired Web source/build assets;
  prototype build references; obsolete acceptance mappings and generated
  bundles.

## Answer

The implementation baseline is recorded in
[`evidence/00-baseline-manifest.md`](../evidence/00-baseline-manifest.md).
It binds the reviewed documentation commit and feature branch, an empty
pre-claim dirty allowlist, authority/migration/Web hashes, canonical symbols,
schema evidence, focused-suite terminal results, timeout attempts, direct
SQLite inventory, future migration cohorts, and exact owner-ticket removal
targets. Ticket 00 changed no runtime behavior and performed no stage, commit,
push, reset, clean, merge, or user-data operation.
