# 12 — DisciplineReviewVersion

**Status:** resolved
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

## Claim record

- External seams: named create-draft, confirm-version, and get-review
  application tasks; confirmation uses the reserved
  `discipline_review.confirm@1` shared envelope.
- Deep-module ownership: `domain/discipline_reviews.py` owns complete-session
  period semantics, evidence-derived exception classification, immutable
  version identity, and monthly aggregation; application owns complete
  draft/confirm/get orchestration and user capability; SQLite owns authoritative
  task/journal/plan/snapshot reads, version concurrency, immutable persistence,
  and receipt replay.
- Old paths to replace: fixed-Friday or scheduler-shaped weekly review,
  free-form behavior summaries, caller-classified overridden/unrecorded/
  unverified states, and monthly review persistence.
- Superseded artifacts to delete: any `WeeklyReview` runtime symbol/route/schema,
  Friday-only fixture, penalty/rating field, duplicate monthly workflow/table,
  compatibility alias, and tests of retired transient summaries.

## Resolution evidence

- Added immutable `DisciplineReviewVersion`, complete-session weekly/custom
  period semantics in `Asia/Shanghai`, evidence-linked discipline exceptions,
  and confirmed-review monthly aggregation without a second workflow/table.
- The domain classifies overridden, skipped, deferred, unrecorded, and
  unverified outcomes from task/action/execution authority. It does not score
  behavior or infer execution from missing broker evidence.
- Named application tasks own draft, confirm, get, and aggregate operations.
  Confirmation requires user capability and crosses the canonical
  `discipline_review.confirm@1` command envelope.
- SQLite proves complete start/end sessions, collects plan/snapshot/task/journal
  authority (including prior open/deferred tasks), appends immutable versions,
  and atomically persists confirmation receipts with replay protection.
- A later draft/confirmation appends a new version and preserves all prior
  versions. Weekly periods are not Friday-bound; custom periods use the same
  complete-session proof.
- The discipline-review contract suite passed `8 passed in 8.76s`; the final
  current wider regression passed `157 passed in 91.19s`.
- `0017` remained unapplied to both known persistent roots. Its SHA-256 at the
  ticket-12 boundary, before ticket 13 completes the cohort in place, was
  `60D99B746900AB19D16CC71B2F9DA9B2374ADE306EBA87D96D43AA9F26891706`;
  `0016` remained unchanged.
