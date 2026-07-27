# 01 — AccountSnapshotVersion

**Status:** resolved  
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

## Claim record

- External seams: actor type/id, interaction-channel and transport-actor
  metadata compatible with the locked `ApplicationCommandEnvelope@1`;
  qualified current-export draft input; legacy opening/history evidence;
  SQLite migration 0015; and named snapshot command and query openers. Ticket
  08 will decode the shared envelope into these task inputs rather than
  introducing an account-specific actor or envelope model.
- Deep-module ownership: `domain/account_snapshots.py` owns draft/version
  validation, three-state financial values, immutable transitions and
  capability derivation; `application/account_snapshots.py` owns complete
  create/update/confirm/query tasks and actor policy; the SQLite adapter owns
  transactionality, idempotency, constraints, preflight and one-way legacy
  conversion.
- Old paths to replace: application reads that use `AccountOpeningService`,
  `AccountHistoryImportService`, `portfolio_snapshot`,
  `account_opening_position`, or broker history as current account truth.
- Superseded artifacts to delete: old current-position projection callers,
  private-seam tests that assert opening rows are current truth, stale opening
  documentation, and any duplicate snapshot DTO/repository introduced during
  migration. Source import evidence and immutable historical references remain.

## Answer

Implemented the account snapshot graph and migration 0015 as the sole current
account truth. Qualified current exports now create only an open draft; user
confirmation advances the immutable projection atomically. Legacy opening
rows and broker history remain evidence only, and all runtime current-truth
reads were moved to the confirmed snapshot projection.

Evidence: [`../evidence/01-account-snapshot-version.md`](../evidence/01-account-snapshot-version.md)
