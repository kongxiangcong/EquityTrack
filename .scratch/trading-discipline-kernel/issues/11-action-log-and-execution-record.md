# 11 — ActionLogEntry and ExecutionRecord

**Status:** ready-for-agent  
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
