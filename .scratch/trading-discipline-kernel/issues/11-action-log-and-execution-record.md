# 11 — ActionLogEntry and ExecutionRecord

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 02, 10

## Scope

Implement immutable action log entries and first-version user-declared execution records. An executed disposition records what the user declares happened and updates EstimatedAccountState; it never overwrites the confirmed snapshot. Broker evidence has explicit verification state.

## Exact files and symbols

- Add `src/trading_platform/domain/decision_journal.py::{ActionLogEntry,ExecutionRecord,ExecutionCorrection,ExecutionVerificationState}`.
- Add `src/trading_platform/application/decision_journal.py::{RecordTaskAction,DeclareExecution,CorrectExecution,ListDecisionJournal}`.
- Add `src/trading_platform/persistence/decision_journal.py::SQLiteDecisionJournalRepository`.
- Implement `ExecutionRecordReader` consumed by `src/trading_platform/domain/account_state.py`.
- Update `src/trading_platform/application/decision_tasks.py::ResolveDecisionTask` for atomic action/disposition linking.

## Migration

Complete action/execution tables, correction links, idempotency constraints, and verification-state constraints in 0017 before first application. Broker reconciliation columns may be reserved but cannot create authority.

## Tests

- Add `tests/platform/test_execution_records.py` and `tests/platform/test_action_log.py`.
- Extend `tests/platform/test_estimated_account_state.py`, `tests/platform/test_decision_tasks.py`, and `tests/platform/test_workflow_ledger_recovery.py`.
- Cover user-declared minimum fields, unknown fees/cash, execution correction, duplicate envelope, atomic task resolution, estimate update, snapshot immutability, and unverified missing broker evidence.

## Dependency

Requires 02 and 10. Ticket 12 reviews the resulting behavior history.

## Acceptance gate

TDK-AC-006, TDK-AC-023, and TDK-AC-030 pass for execution projection. A confirmed execution deterministically changes the estimate; absent broker evidence renders `unverified`, never “not executed”.

## Out of scope

Broker transaction import as authority, automatic fills, order lifecycle, fee inference, tax lots, or snapshot mutation.

## One-way cutover

Replace any free-form/transient behavior history used for formal discipline decisions. Do not dual-write action/execution facts to annotations or account-opening tables.

## Claim record

- External seams: the shared `execution_record.declare@1` and
  `execution_record.correct@1` envelopes plus named journal list/action tasks;
  executed task disposition crosses the same application transaction.
- Deep-module ownership: `domain/decision_journal.py` owns immutable action and
  execution facts, correction rules, verification state, decimal quantity/
  price/fee invariants, and deterministic projection inputs;
  `application/decision_journal.py` owns complete record/declare/correct/list
  operations and user capability; the SQLite adapter owns atomic
  action/execution/task-transition/receipt persistence and
  `ExecutionRecordReader` protocol conversion.
- Old paths to replace: free-form behavior history, transient execution truth,
  account-state execution-reader unavailability as the normal production path,
  and task resolution that writes a transition without its action log.
- Superseded artifacts to delete: annotation/account-opening execution facts,
  direct task-only executed resolution, inferred fees/fills, broker-evidence
  fallback, duplicate execution DTO/schema, compatibility aliases, and private
  tests for retired transient seams.

## Resolution evidence

- Added immutable `ActionLogEntry@1`, `ExecutionRecord@1`, linked correction,
  verification-state, and decimal quantity/price/fee domain contracts.
- `DecisionJournal` is the sole declare/correct/list execution task.
  `DecisionTasks` writes defer/resolve actions through one narrow transaction
  port, so no duplicate application entry exists.
- SQLite atomically commits action, optional execution, task transition, and
  canonical command receipt. Fault injection proves all four roll back
  together; duplicate envelope replay returns the same record and conflicting
  content fails closed.
- The production `ExecutionRecordReader` now feeds every account-state,
  manual-review, and decision-workspace composition. Corrections replace the
  original projection input without changing confirmed snapshots.
- Unknown fee/price leaves dependent cash unknown. User declarations remain
  `user_declared_unverified`; absent broker evidence never becomes
  `not_executed`. No broker adapter, automatic fill, order lifecycle, fee
  inference, or account-opening/annotation dual write was added.
- Current focused architecture/journal/state/restart gate passed
  `41 passed in 32.91s`; the final wider regression passed
  `149 passed in 82.79s`; after removal of the duplicate application Protocol
  surface, the affected compile/architecture/journal/task group passed
  `32 passed in 23.83s`.
- `0017` remains unapplied to both known persistent roots. Its current SHA-256
  is `16608B72C45F53325FCEAD6D119577EBBD307D7186AEDC572C4051F50DE2EA51`;
  `0016` remains unchanged.
