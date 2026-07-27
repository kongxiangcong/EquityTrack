# Ticket 12 — Discipline review version evidence

## Result

- Status: passed
- Acceptance: `TDK-AC-024`
- Persistence cohort: `0017`, still unapplied to persistent roots

## Implemented contract

- `DisciplineReviewPeriod` accepts weekly and custom periods, fixes the
  timezone to `Asia/Shanghai`, and requires authoritative complete sessions at
  both boundaries. Weekly periods are bounded by seven calendar days and are
  not tied to Friday.
- `DisciplineReviewVersion` is immutable and content-hashed. Draft,
  confirmation, and later replacement are new versions; prior rows are never
  mutated.
- Exception classification is derived from canonical decision tasks, action
  log entries, active execution corrections, plan authority, and account
  snapshots. Overridden, skipped, deferred, unrecorded, and unverified remain
  distinct evidence-backed states.
- Prior open or deferred tasks remain visible in later periods. A missing
  broker match keeps a user declaration unverified and is never reclassified
  as not executed.
- `discipline_review.confirm@1` is the canonical confirmation envelope and
  requires user capability. Duplicate invocations replay the stored receipt;
  conflicting content fails closed.
- Monthly reporting aggregates confirmed immutable weekly/custom versions at
  read time. There is no monthly workflow, scheduler, monthly persistence
  table, behavioral score, or investment rating.

## Migration evidence

- `migrations/0016_strategy_plan_model_b.sql` SHA-256:
  `732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`
- `migrations/0017_manual_review_journal.sql` SHA-256 at the ticket-12
  boundary, before ticket 13 completes the same unapplied cohort:
  `60D99B746900AB19D16CC71B2F9DA9B2374ADE306EBA87D96D43AA9F26891706`
- Both known persistent roots remain below the `0017` cohort:
  - `outputs/live-tushare-qualification-20260714/data/platform.sqlite3`
  - `outputs/ui-smoke-20260714/data/platform.sqlite3`
- Fresh migration and fail-closed checks cover predecessor/version semantics,
  immutable triggers, draft invocation uniqueness, user confirmation
  capability, receipt replay, transaction rollback, and content integrity.

## Verification

The initial contract collection failed because the named review contracts did
not yet exist. It was the intended contract-first red state and is not counted
as passing.

Completed discipline-review contract gate:

```text
python -m pytest -q tests/platform/test_discipline_reviews.py
8 passed in 8.76s
```

Completed focused review/journal/task/migration/restart gate:

```text
python -m compileall -q src
python -m pytest -q tests/platform/test_discipline_reviews.py tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_decision_tasks.py tests/platform/test_migration_0015_0017.py tests/platform/test_application_command_envelope.py tests/platform/test_runtime_skeleton.py tests/platform/test_workflow_ledger_recovery.py
67 passed in 49.22s
```

Completed final wider current-state regression after adding prior-open-task
carry-forward coverage:

```text
python -m compileall -q src
python -m pytest -q tests/test_research_engine.py tests/test_skill_entrypoint.py tests/platform/test_cli_application_tasks.py tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_decision_tasks.py tests/platform/test_discipline_reviews.py tests/platform/test_manual_portfolio_review.py tests/platform/test_migration_0015_0017.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_application_command_envelope.py tests/platform/test_runtime_skeleton.py tests/platform/test_secure_workspace.py tests/platform/test_account_snapshots.py tests/platform/test_estimated_account_state.py tests/platform/test_plan_confirmation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_market_evaluation.py tests/platform/test_skill_contract.py
157 passed in 91.19s
```

## Mechanical self-audit

- Domain owns period invariants, exception classification, immutable review
  identity/content hashing, and deterministic monthly aggregation.
- Application owns complete create/confirm/get/aggregate tasks and confirmation
  capability; it does not duplicate persistence or classification.
- Persistence owns authority reads, complete-session proof, version
  concurrency, transactions, receipt replay, and SQLite conversion.
- Domain/application review modules import no persistence, SQLite, CLI, or Web
  layer.
- Searches found no active `WeeklyReview`, fixed-Friday review, monthly table,
  behavior/penalty score, compatibility alias, fallback, dual read/write,
  feature flag, TODO, or FIXME in the replacement surface.
