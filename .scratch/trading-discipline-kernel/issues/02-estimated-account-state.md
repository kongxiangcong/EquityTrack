# 02 — EstimatedAccountState

**Status:** resolved
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

## Claim record

- External seams: latest-confirmed `AccountSnapshotVersion` projection,
  future ticket-11 confirmed `ExecutionRecordReader`, version-1 projection
  checkpoint rows, restart/rebuild, and the workspace read model.
- Deep-module ownership: `domain/account_state.py` owns order-independent
  execution replay, duplicate suppression, unknown propagation, correction and
  drift calculations; `application/account_state.py` owns the complete query
  and comparison tasks; `SQLiteAccountSnapshotProjection` owns authority-record
  loading and checkpoint persistence/rebuild.
- Old paths to replace: workspace `current_positions` assembled directly from
  confirmed snapshot rows, account-opening aliases in the workspace read
  model, and any caller-side quantity/cash replay.
- Superseded artifacts to delete: the Ticket-01 interim workspace position
  shape, duplicate position calculators, tests that bind the workspace to raw
  snapshot SQL, and any estimated values written into immutable snapshot
  tables. The confirmed snapshot graph and execution history remain immutable
  authority inputs.

## Answer

Implemented the canonical deterministic estimated-state projection and drift
assessment behind named application queries. The projection records the exact
confirmed snapshot seal and contributing confirmed execution identities,
deduplicates and orders replay deterministically, replaces corrected records,
propagates unknown cash/position operands without inventing zeroes, and blocks
conflicting or impossible records. A later confirmed snapshot is compared with
the prior estimate while both immutable snapshot history and the prior estimate
hash remain unchanged.

The workspace now receives only `EstimatedAccountState` values from the
application task. Its old raw-snapshot position query, `account_opening_state`
alias, Ticket-01 interim field shape, and production Web reads of those retired
fields were removed. Until ticket 11 installs the production execution reader,
the state explicitly reports `EXECUTION_RECORD_READER_UNAVAILABLE` and remains
partial rather than pretending that no executions exist.

Evidence: `evidence/02-estimated-account-state.md`.
