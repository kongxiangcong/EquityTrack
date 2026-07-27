# 00 — Authority baseline and branch cleanup

**Status:** ready-for-agent  
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
