# 01 — AccountSnapshotVersion

**Status:** ready-for-agent  
**Type:** task  
**Mode:** AFK  
**Blocked by:** 00

## Scope

Implement `AccountSnapshotDraft`, immutable `AccountSnapshotVersion`, positions, transitions, confirmation, and current confirmed projection. Enforce the minimum required capability while preserving optional fields as unknown. Agent may create a draft; only a user-capable command may confirm it.

## Exact files and symbols

- Add `src/trading_platform/domain/account_snapshots.py::{AccountSnapshotDraft,AccountSnapshotVersion,AccountSnapshotPosition,AccountSnapshotTransition,AccountSnapshotService}`.
- Add `src/trading_platform/application/account_snapshots.py::{CreateAccountSnapshotDraft,UpdateAccountSnapshotDraft,ConfirmAccountSnapshot,GetAccountSnapshot}`.
- Add `src/trading_platform/persistence/account_snapshots.py::{SQLiteAccountSnapshotRepository,SQLiteAccountSnapshotProjection}`.
- Update `src/trading_platform/application/bootstrap.py::{open_account_snapshot_commands,open_account_snapshot_queries}` and `src/trading_platform/application/__init__.py`.
- Replace current-truth use in `src/trading_platform/account.py::{AccountOpeningService}` and `src/trading_platform/account_history.py::{AccountHistoryImportService}`.

## Migration

Own `migrations/0015_account_snapshot_version.sql` and `trading_platform.persistence.migration.MigrationRunner._preflight_account_snapshot_0015`. Follow cohort A and the exact preflight/transform rules in `migration-plan.md`.

## Tests

- Add `tests/platform/test_account_snapshots.py`.
- Add 0015 cases to `tests/platform/test_migration_0015_0017.py`.
- Update `tests/platform/test_account_opening.py`, `tests/platform/test_account_history_import.py`, and `tests/platform/test_runtime_skeleton.py`.
- Cover required identities, complete-session/as-of semantics, unknown optional fields, actor denial, immutable confirmation, idempotency, and preflight no-op on failure.

## Dependency

Requires ticket 00. Ticket 02 and all plan ownership work depend on its confirmed projection.

## Acceptance gate

TDK-AC-001, TDK-AC-002, TDK-AC-004, and TDK-AC-005 pass for the 0015/account portions. Broker history cannot create current truth; a qualified current export can create only a draft; confirmation creates one immutable version and transition.

## Out of scope

Estimated state, execution projection, broker transaction reconciliation, strategy or plan behavior, Web page implementation.

## One-way cutover

Remove application reads that treat account-opening rows or broker history as current truth in the same change. Preserve source evidence; do not add fallback readers, dual writes, or unknown-to-zero conversion.
