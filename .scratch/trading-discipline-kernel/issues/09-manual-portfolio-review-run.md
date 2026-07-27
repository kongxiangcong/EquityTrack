# 09 — ManualPortfolioReviewRun

**Status:** resolved
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

## Claim record

- External seams: `manual_portfolio_review.run@1` through the shared
  `ApplicationCommandEnvelope@1`, plus named start/resume/get tasks and the
  existing WorkflowLedger/ArtifactManifest evidence seam.
- Deep-module ownership: `domain/manual_review.py` owns run/window/outcome/
  checkpoint/manifest invariants; `application/manual_portfolio_review.py`
  owns the complete manual review orchestration and item-level continuation;
  `persistence/manual_portfolio_review.py` owns cohort-C transactions,
  uniqueness, replay, checkpoint advancement, and SQLite protocol conversion.
- Old paths to replace: public CLI/Skill `daily`, `DailyResearchCycle` as a
  portfolio-review entry, scheduler-shaped daily assumptions, and any
  review caller that derives its own cutoff or writes review artifacts.
- Superseded artifacts to delete: the public `daily` parser/dispatch/export/
  Skill instructions, daily portfolio tests or examples, duplicate run ledger
  or manifest storage, implicit latest-success cutoff logic outside the
  repository transaction, and compatibility aliases for the retired route.

## Resolution evidence

- Added the ticket-09 cohort-C baseline `0017_manual_review_journal.sql` with
  fail-closed preflight, immutable journal constraints, rollback, and replay
  coverage. Its SHA-256 at the ticket-09 boundary was
  `4BC5B38496A187E04B8CE0513F6BAB387C206C45979AEDF22E5D4053C41BE579`;
  tickets 10–13 complete that same unapplied cohort in place. `0016` remained
  unchanged and both known persistent roots remained at schema 11.
- `ManualPortfolioReview` now owns the named start/resume/get task while the
  domain owns review window, outcomes, checkpoints, and deterministic manifest
  construction. SQLite owns context proof, transactions, invocation replay,
  immutable reads, and successful-cutoff advancement.
- Removed the public CLI/Skill/application `daily` portfolio-review path with
  no alias or fallback. The shared command envelope uses the same canonical
  request hash as the persisted receipt.
- `TDK-AC-019` and the ticket-focused migration/workflow group passed:
  `38 passed in 29.62s`. The wider relevant regression group passed:
  `127 passed in 69.33s`.
- An earlier short-window test process was terminated by the tool after about
  five seconds and was not counted as a pass; the same focused group was then
  rerun to completion.
- Mechanical audit passed for the ticket diff, dependency direction, retired
  daily symbols, compatibility/debt markers, and public-interface regression.
  Detailed current evidence is recorded in
  `evidence/09-manual-portfolio-review.md`.
