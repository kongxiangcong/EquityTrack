# Ticket 16 canonical E2E and acceptance evidence

Captured: `2026-07-28 Asia/Shanghai`
Branch: `codex/trading-discipline-kernel`
Fixture: synthetic only (`002897.SZ`, `600183.SH`)
Canonical result: `passed`

## One-way replacement

- Replaced the pre-kernel 51-row `VerticalSliceAcceptance@1` ledger with
  `TradingDisciplineKernelAcceptance@1` and the exact 35-row TDK matrix.
- Replaced `slice_acceptance` CLI/report vocabulary with
  `trading_discipline_kernel_acceptance`.
- The acceptance runner owns four finite suite groups, exact
  pass/fail/timeout accounting, per-suite durations and first failing
  substeps, content-hashed evidence, migration hashes, and production CDP.
- The Skill command now points to the one canonical synthetic fixture
  manifest. It does not require or imply live account/provider evidence.
- Deleted no migration bytes and introduced no compatibility reader, alias,
  fallback, feature flag, second schema, or alternate renderer.

## Canonical fixture and 20-step chain

`tests/fixtures/trading_discipline_kernel/expected-manifest.json` locks five
fixture members by SHA-256:

- one known-cash, two-position synthetic account;
- `002897.SZ` with `trend_hold_break_exit@1` and a core sleeve;
- `600183.SH` with `core_plus_grid@1`, core floor, and grid sleeve;
- complete synthetic sessions for `2026-07-27` and `2026-07-31`.

`test_restart_replay_is_idempotent` executes the fixed twenty behaviors in one
persistent root: Agent snapshot draft, user snapshot confirmation, two plan
drafts, Agent confirmation denial, user challenge confirmation, active
uniqueness, core-floor preservation, multi-session review, no-change/no-task,
one grid task, execution projection, deferral/reappearance, overridden
discipline review, proposal-to-draft only, rejected-proposal isolation,
history-preserving activation, read parity, restart/replay, backup/restore
handoff, and missing-broker-evidence=`user_declared_unverified`.

The frozen identity sets and six read-model content hashes are in
`acceptance/restart-replay.json`.

## Restore and integrity defect closed

The full authority chain is backed up and restored to a distinct root, then
compared by portfolio projection hash, schema-migration ledger, account
snapshot graph hashes, plan graph hashes, discipline-review hashes, and
execution identities. The restored root passes `doctor`.

This gate exposed a real fail-closed defect: manual-review artifact manifests
were written with `canonical_hash((artifact_id,))`, while integrity audit
recomputed a canonical member object containing artifact ID, role, and
direction. That made a valid full-chain backup fail restore doctor with
`ARTIFACT_MANIFEST_HASH_MISMATCH`. The owning persistence adapter now writes
the same canonical member identity audited by recovery. Focused E2E and
restore tests passed after the repair.

Frozen proof: `acceptance/backup-restore.json`.

## Focused pre-gate verification

| Group | Result | Duration |
|---|---:|---:|
| Contract | 47 passed | 13.55s |
| Workflow and journal | 43 passed | 36.41s |
| Presentation | 25 passed | 22.66s |
| Migration and operations | 53 passed, 1 release gate deselected | 103.02s |

Additional focused checks:

- two-security E2E plus restore: `2 passed` in `6.42s`;
- architecture/status/browser/fixture/receipt checks: `5 passed` after the
  exact status test correction;
- Skill and dependency routing: `2 passed` in `3.20s`.

No focused run ended in a timeout or was counted as passing while incomplete.

## Unique canonical acceptance execution

Command (executed once):

```powershell
python -m trading_platform.cli acceptance `
  --data-root .scratch/trading-discipline-kernel/acceptance-data `
  --fixture-manifest tests/fixtures/trading_discipline_kernel/expected-manifest.json `
  --repo-root .
```

Terminal result:

```text
trading_discipline_kernel_acceptance=passed
manifest_sha256=7ce3c3637c07a34dbc80dc53bff0b75442aeb488550ebd4cc3877c0320c19968
```

Canonical suite ledger:

| Suite | Passed/collected | Duration | Status |
|---|---:|---:|---|
| contract | 47/47 | 15.488s | passed |
| workflow_and_journal | 43/43 | 36.715s | passed |
| presentation | 25/25 | 24.345s | passed |
| migration_and_operations | 53/53 | 112.193s | passed |
| production browser CDP | gate | 4.686s | passed |

The manifest reports:

- `35/35` TDK criteria passed;
- `168/168` suite tests passed;
- zero failed, skipped, xfailed, or timed-out suite results;
- four production-page screenshots, zero console errors, zero network
  failures, and retired routes returning `404`;
- migration hashes:
  - 0015:
    `ca8ac7e30bc9771c0f9b10b28bec03ee979f61c77b96e10d3cbb982ba5648305`;
  - 0016:
    `732fac8ab6dbe393e8b62595d57730247a8929f5ee271cce380c28e0ff58aa62`;
  - 0017:
    `a53804ab84ff683c457b8b2c6718572d3b604690af83e346efd68af3bc3f302c`.

The exact negative-status proof is separately frozen in
`acceptance/acceptance-f3361395d93cb876e855156f9b8fdf8866911267f90625ea0eebc5c18f71cf85.json`
and summarized by `acceptance/acceptance-status-semantics.json`; it proves
that `failed`, `timeout`, and `external_blocked` remain distinct and cannot
become a pass.

The live provider qualification check is `not_applicable` because this gate
is deliberately synthetic and offline. It is not labeled passed and no real
account, broker, order, or external-provider fact was used.

## Final removal and boundary audit

- No active runtime/Skill/Web occurrence remains for
  `open_daily_research_cycle`, `user_fixture_input`,
  `get_active_for_security`, or runtime `plan-rule-ast@1`.
- `/api/workspace`, chart/annotation/update-authorization routes, and public
  daily remain only in explicit absence tests, CDP `404` evidence, or
  immutable historical ticket evidence.
- AST@1 and `user_fixture_input` remain only as fail-closed migration inputs
  or adversarial absence tests.
- No active KLineCharts dependency or production prototype asset remains.
- The business import graph contains no LLM provider, automatic scheduler,
  order router, or broker execution surface.
- Generated pytest basetemp trees and the temporary acceptance data root were
  removed after evidence freezing; the committed acceptance directory retains
  only canonical reports, JUnit ledgers, screenshots, and required proof
  artifacts.
