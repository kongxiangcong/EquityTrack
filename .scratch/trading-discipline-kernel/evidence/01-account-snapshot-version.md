# Ticket 01 — AccountSnapshotVersion evidence

Date: `2026-07-27 Asia/Shanghai`  
Branch: `codex/trading-discipline-kernel`  
Baseline: `8aa69c9826a11133c39425ff6214052e387c747c`

## Authority and cutover

- The latest confirmed `AccountSnapshotVersion` is the only current account
  truth. `account_position`, `portfolio_snapshot`, and broker history remain
  immutable legacy/source evidence and have no runtime current-truth readers.
- A qualified current export enters through
  `account-current-export-draft`; it atomically persists source evidence and an
  open `AccountSnapshotDraft` and does not create a confirmed version.
- Draft create/update may carry `decision_actor_type=agent`. Confirmation
  fails unless the decision actor is a non-empty user identity. Account
  confirmation has no plan challenge or approval-receipt dependency.
- Confirmation atomically writes Version, Cash, Position, Capability,
  Transition, `AccountSnapshotConfirmed`, command receipt, and the latest
  projection checkpoint. Confirmed graph tables, events, receipts, and
  migration provenance reject update/delete.
- Optional cash, NAV, fees, available quantity, cost, and market value use
  paired `known|unknown|not_applicable` states. Unknown values persist as SQL
  `NULL`; only dependent capability keys become `unable`.

## Migration 0015

- Fresh root: migration ledger reaches version `15`; repeated migrate is a
  no-op.
- Populated schema-14 root: explicit legacy opening confirmation becomes one
  confirmed version with `as_of_precision=date`,
  `timezone=Asia/Shanghai`, `session_semantics=legacy_unknown`, exact known
  quantities/cash/market value, unknown optional cost/NAV/fees, transition,
  event, receipt, projection, and hashed source-row provenance.
- Exact `PortfolioSnapshot` plan references are rewritten to
  `AccountSnapshotVersion` while `context_json` and `context_hash` remain
  byte-for-byte unchanged.
- Missing confirmation provenance fails with
  `ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE`; the ledger remains at 14 and no
  0015 table exists.
- Injected statement failure rolls the whole migration back. Re-running the
  same root succeeds once and produces one version.
- Existing migration backup/restore and fresh/prior/reused-root matrix pass
  with migration 0015.

## Verification

Contract-first red evidence:

- Initial account contract collection failed because the new public exports
  did not exist.
- First implemented run had one expected assertion mismatch in the preflight
  error check; the test was corrected to assert the typed `PersistenceError`
  code rather than its redacted message.

Terminal passing commands:

```text
python -m pytest tests/platform/test_account_snapshots.py tests/platform/test_migration_0015_0017.py tests/platform/test_account_opening.py tests/platform/test_account_history_import.py tests/platform/test_account_workspace_plans.py tests/platform/test_runtime_skeleton.py tests/platform/test_cli_application_tasks.py tests/platform/test_project_verification.py -q
52 passed in 39.94s

python -m pytest tests/platform/test_operations_backup_restore.py::test_backup_restore_new_root_preserves_database_objects_and_history tests/platform/test_operations_backup_restore.py::test_release_migration_matrix_covers_fresh_prior_created_and_reused_roots -q
2 passed in 34.23s

python -m compileall -q src/trading_platform
exit 0
```

One earlier command that combined the account group with the complete
operations file timed out after 64 seconds. It was not counted as a pass; the
account group and the two relevant operations nodes were rerun separately to
terminal results above.

## Acceptance mapping

| Acceptance | Current evidence |
|---|---|
| `TDK-AC-001` account/0015 portion | fresh and populated idempotent migration test plus migration matrix |
| `TDK-AC-002` | lossless values, unknowns, provenance, and exact plan-reference rewrite test |
| `TDK-AC-004` | agent draft, user-only confirmation, transition/event/receipt/projection test |
| `TDK-AC-005` account portion | three-state SQL checks and capability-specific unable/available assertions |

Ticket 16 still owns the final cross-ticket canonical acceptance proof; this
ticket evidence closes only the declared account/0015 portions.
