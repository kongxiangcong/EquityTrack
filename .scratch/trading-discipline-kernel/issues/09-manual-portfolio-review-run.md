# 09 — ManualPortfolioReviewRun

**Status:** ready-for-agent  
**Type:** task  
**Mode:** AFK  
**Blocked by:** 02, 06, 08

## Scope

Implement public workflow `manual_portfolio_review@1`, explicit selected complete A-share session, last-successful-review cutoff, frozen evidence manifest, per-holding items, outcomes, and checkpoint advancement only on successful completion. Reviews may be separated by multiple sessions.

## Exact files and symbols

- Add `src/trading_platform/domain/manual_review.py::{ManualPortfolioReviewRun,ManualPortfolioReviewItem,ManualPortfolioReviewCheckpoint,ManualPortfolioReviewManifest,ReviewOutcome}`.
- Add `src/trading_platform/application/manual_portfolio_review.py::{StartManualPortfolioReview,ResumeManualPortfolioReview,GetManualPortfolioReview}`.
- Add `src/trading_platform/persistence/manual_portfolio_review.py::SQLiteManualPortfolioReviewRepository`.
- Update `src/trading_platform/application/bootstrap.py::open_manual_portfolio_review`.
- Retire the public portfolio role of `src/trading_platform/application/cli_tasks.py::DailyResearchCycle`.

## Migration

Create the full, final cohort-C `migrations/0017_manual_review_journal.sql` and `trading_platform.persistence.migration.MigrationRunner._preflight_manual_review_0017`, including schema required by tickets 09–13. Do not apply it to a persistent root until the cohort is complete.

## Tests

- Add `tests/platform/test_manual_portfolio_review.py`.
- Update `tests/platform/test_cli_application_tasks.py`, `tests/platform/test_workflow_ledger.py`, and `tests/platform/test_workflow_ledger_recovery.py`.
- Add 0017 preflight/idempotency tests.
- Cover no prior checkpoint, multiple-session gaps, incomplete sessions, failed/resumed runs, manifest immutability, item outcomes, and checkpoint advancement.

## Dependency

Requires 02, 06, and 08. Tickets 10 and 13 consume successful review output.

## Acceptance gate

TDK-AC-019 passes. Public review never relies on a daily scheduler; a failed/incomplete run never advances the successful cutoff.

## Out of scope

Scheduler, intraday monitor, automatic plan changes, task disposition, execution entry, or independent monthly workflow.

## One-way cutover

Remove `daily` as the public portfolio review entry and update Skill/CLI callers. Daily research may remain only as an internal evidence producer; no compatibility public alias is retained.
