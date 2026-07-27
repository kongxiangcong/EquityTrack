# Ticket 04 — Plan graph seal and active uniqueness evidence

Date: `2026-07-27 Asia/Shanghai`
Branch: `codex/trading-discipline-kernel`
Parent: `f2e340eb23000833470a300a1cca94d7f94eea6f`

## Canonical cutover

- `TradePlanTasks` is the only plan authoring/activation application seam.
  It accepts complete master, graph-seal, activation, and query tasks.
- `domain/plans.py` owns Model B master identity, immutable version/graph
  shape, deterministic full-graph seal identity, and validation.
- `SQLiteTradePlanRepository` owns the atomic version/child/seal transaction,
  approval-receipt binding, activation transitions, replay, reconstruction,
  and the database uniqueness failure translation.
- The Web and CLI no longer expose plan confirmation. Ticket 07 owns the
  locked Skill-mediated challenge and receipt route.

## Migration 0016 contract

- Active legacy rows require one canonical `LegacySleeveMapping@1` artifact
  covering the exact active-plan set with a timezone-aware user approval.
- Missing account ownership, duplicate active account/security ownership,
  missing rule scope, invalid exact values, and lifecycle/activation
  disagreement fail before schema mutation.
- Inactive legacy plan content is byte-preserved as read-only history.
  Explicitly mapped active history preserves IDs/content, gains one exact
  sleeve graph, one approval receipt, and exactly one open activation.
- Parent-version updates, late child insertion, child update/delete, version
  deletion, activation mutation/delete, and transition mutation/delete fail
  closed through database triggers.

## Verification

Contract-first and migration cohort:

```text
python -m pytest tests/platform/test_migration_0015_0017.py -q
11 passed in 5.75s

python -m pytest tests/platform/test_trade_plan_model_b.py -q
5 passed in 2.68s
```

Focused application, persistence, Web, security, and architecture group:

```text
python -m pytest tests/platform/test_runtime_skeleton.py tests/platform/test_trade_plan_model_b.py tests/platform/test_migration_0015_0017.py tests/platform/test_web_application_tasks.py tests/platform/test_secure_workspace.py tests/platform/test_account_opening.py tests/platform/test_chart_annotations.py -q
62 passed in 57.70s

python -m compileall -q src/trading_platform
exit 0
```

Production Web source gate:

```text
npm test
18 passed, 0 failed

npm run build
11 modules transformed; production build passed
```

An earlier focused run had `20 passed, 4 failed`. It exposed one stale
security lookup on `trade_plan_version.security_id` and a missing update
authorization fixture seam. Both were corrected; the failing run is not
reported as a pass.

## Mechanical audit

- Superseded `PlanService`, `SQLitePlanRepository`,
  `get_active_for_security`, old draft/confirmation commands, direct Web
  confirmation route, and their private-seam test files are deleted.
- Runtime searches found no second plan command/read path, legacy fallback,
  dual read/write, compatibility alias, feature flag, `TODO`, or `FIXME`.
- Tests cross the same named application interface as production callers.
  Migration corruption setup remains confined to the owning migration suite.
- The final Ticket-04 diff retains cohesive domain, application, transaction,
  migration, and presentation responsibilities without adding a forwarding
  module or one-class-per-file fragments.

## Acceptance mapping

| Acceptance | Current evidence |
|---|---|
| `TDK-AC-003` | exact missing-mapping test proves active legacy migration fails closed and leaves schema 15 byte-identical |
| `TDK-AC-009` | exact concurrent activation test proves the writer seam fails closed and the database permits only one active account/security master |
| `TDK-AC-010` | exact graph mutation test rejects parent mutation plus late child insert/update/delete after seal |
| `TDK-AC-026` | exact replacement activation test preserves the prior graph and immutable activation identity while appending the next version/activation |

Ticket 16 owns final canonical cross-ticket acceptance.
