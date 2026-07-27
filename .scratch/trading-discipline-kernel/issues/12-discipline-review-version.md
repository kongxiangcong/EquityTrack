# 12 — DisciplineReviewVersion

**Status:** ready-for-agent  
**Type:** task  
**Mode:** AFK  
**Blocked by:** 11

## Scope

Implement immutable `DisciplineReviewVersion` with `period_kind=weekly|custom`, Asia/Shanghai complete-session boundaries, default weekly presentation, and aggregation-ready monthly reporting without a separate workflow. Compare tasks, actions, executions, overrides, deferrals, and plan state.

## Exact files and symbols

- Add `src/trading_platform/domain/discipline_reviews.py::{DisciplineReviewVersion,DisciplineReviewPeriod,DisciplineException,DisciplineReviewService}`.
- Add `src/trading_platform/application/discipline_reviews.py::{CreateDisciplineReviewDraft,ConfirmDisciplineReviewVersion,GetDisciplineReview}`.
- Add `src/trading_platform/persistence/discipline_reviews.py::SQLiteDisciplineReviewRepository`.
- Update `src/trading_platform/application/bootstrap.py::open_discipline_reviews`.
- Use `src/trading_platform/domain/decision_tasks.py` and `src/trading_platform/domain/decision_journal.py` as authority inputs.

## Migration

Complete discipline-review tables, immutable version constraints, period semantics, and content hashes in 0017 before first application.

## Tests

- Add `tests/platform/test_discipline_reviews.py`.
- Cover weekly/custom periods, Asia/Shanghai boundaries, non-Friday execution, overridden/skipped/deferred distinctions, incomplete evidence, immutable versions, idempotency, restart, and monthly aggregation.

## Dependency

Requires 11. Ticket 13 may include discipline exceptions in impact context; ticket 14 projects the latest review.

## Acceptance gate

TDK-AC-024 passes. An overridden disposition is visible as a discipline exception with evidence links; a later review creates a new version and does not mutate the prior review.

## Out of scope

Scheduler, mandatory Friday execution, independent monthly workflow, investment scoring/rating, or automated behavioral judgment without evidence.

## One-way cutover

Replace any fixed-Friday `WeeklyReview` formal contract with `DisciplineReviewVersion`. Do not retain a runtime alias or duplicate monthly persistence.
