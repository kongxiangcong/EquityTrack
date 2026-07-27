# Ticket 05 — Core and grid sleeve evidence

Date: `2026-07-27 Asia/Shanghai`
Branch: `codex/trading-discipline-kernel`
Parent: `1dac17dfddc303c7dc88df5db2746747201ca99c`

## Closed sleeve contract

- `PositionSleeveKind` accepts only `core`, `grid`, and the migration-only
  `legacy_unsleeved`; public graph validation rejects the latter.
- `trend_hold_break_exit@1` accepts exactly one core sleeve.
  `core_plus_grid@1` accepts exactly one core and at most one grid sleeve.
- Core floor is a mandatory, non-negative, whole-share exact decimal.
  Known sleeve allocations cannot exceed proved total quantity.
- Grid constraints require positive ordered CNY bounds, `2..100` levels,
  positive standard A-share 100-share lots, a non-negative whole-share
  budget, a closed price basis/trigger mode, and non-negative cooldown.
- A candidate grid decrease is rejected whenever exact remaining quantity
  would fall below the shared core floor. Unknown total quantity is not
  fabricated and does not block quantity-independent graph validation.

## Persistence and migration

- The graph-seal transaction inserts `grid_constraint` before its typed
  sleeve reference and seals the complete graph only after all child rows
  succeed.
- Reconstruction converts stored decimal text back to `Decimal`, rebuilds
  typed sleeves, and verifies both sleeve and grid content hashes.
- Sealed grid constraints reject update/delete and late insert through the
  same graph immutability policy.
- Migration 0016 converts explicit mapping rows through the domain sleeve
  contract before SQL execution. Mapped grid sleeves must carry their exact
  constraint; core rows cannot carry one. The persisted mapping manifest
  continues to hash the original canonical user-approved artifact bytes.

## Verification

Contract-first red evidence:

```text
python -m pytest tests/platform/test_trade_plan_sleeves.py -q
collection error: CoreFloor was not yet implemented
```

Terminal passing commands:

```text
python -m pytest tests/platform/test_trade_plan_sleeves.py tests/platform/test_strategy_catalog.py tests/platform/test_trade_plan_model_b.py tests/platform/test_migration_0015_0017.py -q
28 passed in 9.22s

python -m pytest tests/platform/test_trade_plan_sleeves.py tests/platform/test_strategy_catalog.py tests/platform/test_trade_plan_model_b.py tests/platform/test_migration_0015_0017.py tests/platform/test_runtime_skeleton.py -q
39 passed in 16.98s

python -m compileall -q src/trading_platform
exit 0
```

One intermediate run had `11 passed, 1 failed`: the fixture allocated 100
core shares plus 20 grid shares against a proved 100-share position. The
implementation correctly rejected it; the fixture was corrected to an
80/20 allocation and the exact test passed. The failed run is not counted
as a pass.

## Mechanical audit

- Sleeve behavior lives in the sealed plan aggregate; persistence performs
  real decimal/schema protocol conversion and no caller authors hashes.
- Strategy objects own cross-field parameter meaning rather than duplicating
  it in Web, CLI, tests, or migration SQL.
- Searches found no tactical sleeve, second sleeve taxonomy, flat current
  plan quantity source, compatibility alias, dual read/write, feature flag,
  `TODO`, or `FIXME` in the Ticket-05 surface.
- The focused tests use the same plan task and catalog query interfaces as
  production callers. Direct SQL is limited to migration corruption setup
  and adversarial immutable-storage assertions.

## Acceptance mapping

| Acceptance | Current evidence |
|---|---|
| `TDK-AC-011` | exact acceptance test covers core requirement, duplicate core/grid, tactical rejection, optional grid, strategy mismatch, bounds, lot, floor, persistence, and sealed mutation |
| `TDK-AC-012` | exact acceptance test proves 20-share decrease reaches but does not cross floor, 21-share decrease fails closed, and unknown total remains unknown |

Ticket 16 owns final canonical cross-ticket acceptance.
