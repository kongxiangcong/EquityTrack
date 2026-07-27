# 02 — EstimatedAccountState

**Status:** ready-for-agent  
**Type:** task  
**Mode:** AFK  
**Blocked by:** 01

## Scope

Implement the deterministic projection `Latest Confirmed AccountSnapshotVersion + confirmed user-declared ExecutionRecords`. Make base snapshot identity, contributing executions, unverified evidence, drift, and reconciliation explicit. A later confirmed snapshot corrects the estimate without rewriting prior truth.

## Exact files and symbols

- Add `src/trading_platform/domain/account_state.py::{EstimatedAccountState,EstimatedPosition,AccountStateDrift,derive_estimated_account_state,reconcile_account_state}`.
- Add `src/trading_platform/application/account_state.py::{GetEstimatedAccountState,CompareConfirmedAccountState}`.
- Extend `src/trading_platform/persistence/account_snapshots.py::SQLiteAccountSnapshotProjection`.
- Update `src/trading_platform/application/bootstrap.py::{open_account_state_queries}`.
- Reserve the typed `ExecutionRecordReader` port in `src/trading_platform/domain/account_state.py`; its production adapter lands in ticket 11.

## Migration

Use the projection checkpoint table already defined by immutable migration 0015. Do not edit 0015 after cohort A first application. No new migration.

## Tests

- Add `tests/platform/test_estimated_account_state.py`.
- Extend `tests/platform/test_workflow_ledger_recovery.py` for restart/rebuild.
- Cover order-independent replay, duplicate suppression, unknown values, partial executability, correcting executions, new-snapshot drift, and snapshot-hash immutability.

## Dependency

Requires 01. Ticket 09 consumes quantities/unknowns; ticket 11 supplies confirmed executions and must satisfy this port.

## Acceptance gate

TDK-AC-006 and TDK-AC-007 pass. Rebuilding from persisted authority records yields the same projection ID and content hash across restart.

## Out of scope

Creating executions, broker reconciliation, plan evaluation, UI rendering, or treating the estimate as a confirmed snapshot.

## One-way cutover

Replace workspace “current positions” derived from account-opening rows with this projection. Do not retain an alternate position calculator or write estimated values into snapshot tables.
