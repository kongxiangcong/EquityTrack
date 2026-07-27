# Ticket 02 — EstimatedAccountState evidence

Date: `2026-07-27 Asia/Shanghai`
Branch: `codex/trading-discipline-kernel`
Parent: `97c6614`

## Authority and projection

- `GetEstimatedAccountState` loads the latest confirmed
  `AccountSnapshotVersion` and only the records returned by the typed
  `ExecutionRecordReader.read_confirmed` port.
- The deterministic domain fold records the base snapshot ID, graph seal,
  ordered active execution IDs, three-state operands, blocking reasons,
  unverified evidence, content hash, and derived-state ID.
- Exact duplicate execution IDs are suppressed. Conflicting duplicate IDs,
  ambiguous or out-of-window corrections, invalid records, negative
  quantities, and negative cash fail closed with typed reasons.
- Correcting records replace the corrected record inside the projection
  window. Unknown price, fee, cash, available quantity, cost, or market value
  remains unknown; it is never coerced to zero.
- `CompareConfirmedAccountState` derives the pre-confirmation estimate through
  the new snapshot cutoff and creates a hashed `DriftAssessment@1`. It does not
  mutate either confirmed snapshot or the historical estimate identity.
- The production execution reader intentionally lands in ticket 11. Until
  then, the named query emits
  `EXECUTION_RECORD_READER_UNAVAILABLE` as unverified evidence and a partial
  state instead of assuming an empty execution history.

## One-way workspace cutover

- The application workspace task derives all confirmed accounts through
  `AccountStateQueries.list_current` before invoking the persistence read
  model.
- The persistence workspace no longer reads current positions directly from
  snapshot tables and no longer emits `account_opening_state`.
- The production Web source reads only the estimated-state field set:
  `derived_from_snapshot_*`, `total_quantity`, paired `*_state`/`*_value`,
  `state_status`, `blocking_reasons`, and `unverified_evidence`.
- The retired Ticket-01 workspace fields have no runtime reads or aliases.
  Negative assertions cover their absence.

## Verification

```text
python -m pytest tests/platform/test_estimated_account_state.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_account_workspace_plans.py tests/platform/test_account_opening.py tests/platform/test_runtime_skeleton.py tests/platform/test_account_snapshots.py -q
37 passed in 34.27s

python -m pytest tests/platform/test_migration_0015_0017.py -q
4 passed in 2.07s

python -m pytest tests/platform/test_runtime_skeleton.py::test_production_web_index_references_tracked_build_assets -q
1 passed in 0.82s

npm test
18 passed, 0 failed

npm run build
11 modules transformed; production assets built successfully

python -m compileall -q src/trading_platform
exit 0

git diff --exit-code HEAD -- migrations/0015_account_snapshot_version.sql
exit 0
```

The first combined Python run produced `36 passed, 1 failed` because the
production build contract correctly rejected the newly generated asset before
it was added to the Git index. After explicitly staging only the Ticket-02
`web/dist` asset replacement, the failed node passed and the complete focused
group passed. It was not counted as an earlier pass.

## Mechanical audit

- Dependency direction is adapter -> application query -> account-state
  domain. The persistence adapter owns authority loading; the Web consumes only
  the application-produced read model.
- The new domain module owns the full replay, unknown propagation, correction,
  drift, and deterministic identity behavior. The application interface stays
  at task granularity.
- Searches found no runtime `account_opening_state` or retired interim Web
  position-field read. Their only remaining occurrences are negative
  regression assertions.
- No Ticket-02 migration, alternate calculator, compatibility path, fallback,
  feature flag, dual read/write, dormant branch, `TODO`, or `FIXME` was added.
- Immutable migration 0015 is byte-for-byte unchanged and its fresh/reuse/
  failure/idempotency cohort remains green.

## Acceptance mapping

| Acceptance | Current evidence |
|---|---|
| `TDK-AC-006` ticket-02 portion | exact authority IDs, confirmed-record port, deterministic replay, duplicate/correction/unknown tests, and restart equality |
| `TDK-AC-007` | new-snapshot drift test plus historical snapshot seal/hash equality |

Ticket 11 must supply and prove the production confirmed-execution adapter for
the remaining `TDK-AC-006` integration portion. Ticket 16 owns final canonical
cross-ticket acceptance.
