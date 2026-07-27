# Ticket 03 — StrategyVersion and Model B ownership evidence

Date: `2026-07-27 Asia/Shanghai`
Branch: `codex/trading-discipline-kernel`
Parent: `ea1a5a04a0e5c5f4f97921a0fc6d1295eabcda7b`

## Closed strategy catalog

- `StrategyCatalog` accepts only the two active public identities
  `trend_hold_break_exit@1` and `core_plus_grid@1`.
- Each immutable `StrategyVersion@1` binds `CN_A_SHARE`, `built_in`,
  `plan-rule-ast@2`, `trade-plan-conflict@1`, a closed sleeve contract,
  finite ordered parameter contracts, rule-template identities, and a
  canonical content hash.
- The named `GetStrategyCatalog` and `GetStrategyVersion` application queries
  are the only public catalog interface. Repository loading revalidates the
  canonical version hash before returning a domain object.
- Unknown and missing parameters fail with stable typed codes. Repository,
  application, CLI, Skill, and Web searches found no create/edit/upload or
  custom-strategy command.
- Registry tables reject update/delete. A restart reads the same exact
  version identity and hash from SQLite.

## Model B ownership and cohort schema

- `TradePlanMasterId.derive(account_id, security_id)` deterministically binds
  both owners; either missing identity fails. `TradePlanMaster.validate`
  requires an exact strategy-version reference for every new master.
- Migration 0016 defines the entire cohort-B storage graph: thesis and
  strategy registry, parameter contracts, account/security plan master,
  draft/version, sleeves, grid constraint, AST@2 rule storage, evidence refs,
  challenge, approval receipt, activation, transition, account snapshot ref,
  active uniqueness, graph immutability, and migration manifest.
- The 0016 preflight fails closed for missing account/security ownership,
  unapproved active legacy plans, mutable legacy drafts, incomplete rules,
  empty content identities, and lifecycle/activation disagreement.
- Provable inactive history keeps exact plan/version/content IDs and bytes as
  `legacy_unsleeved` read-only history. No legacy strategy alias is exposed by
  the catalog.
- Built-ins install within the migration transaction. Injected failure rolls
  back all schema and registry rows; replay reaches one schema-16 ledger entry
  and two public versions.
- All 0016 applications in this ticket used pytest temporary roots. No
  persistent development or production root was selected or mutated.

Current pre-first-application SHA-256 for
`migrations/0016_strategy_plan_model_b.sql`:

```text
2533245F5D5FF1B1269C242203C9C9E788DE4683F04728851FDB6CCB34771326
```

Tickets 04–07 may complete their declared behavior against this same
unapplied cohort file. Ticket 07 must record the byte-final first-application
hash before the cohort gate.

## Verification

Contract-first red evidence:

```text
python -m pytest tests/platform/test_migration_0015_0017.py::test_strategy_plan_0016_installs_full_cohort_schema_idempotently -q
1 failed: expected schema 16, observed schema 15
```

Terminal passing commands:

```text
python -m pytest tests/platform/test_strategy_catalog.py tests/platform/test_trade_plan_model_b.py tests/platform/test_migration_0015_0017.py -q
12 passed in 5.01s

python -m pytest tests/platform/test_runtime_skeleton.py -q
11 passed in 8.25s

python -m pytest tests/platform/test_project_verification.py tests/platform/test_operations_backup_restore.py::test_release_migration_matrix_covers_fresh_prior_created_and_reused_roots -q
5 passed in 31.72s

python -m compileall -q src/trading_platform
exit 0

git diff --exit-code HEAD -- migrations/0015_account_snapshot_version.sql
exit 0
```

An intermediate combined run had `20 passed, 1 failed`: the repository-wide
forbidden-runtime-surface check rejected the local variable name `order`.
It was renamed to `position`; the exact failed runtime suite then passed
11/11. The failed run is not counted as a pass.

## Mechanical audit

- Following the deep-module vocabulary, the catalog module hides identity,
  hash, finite-contract, and parameter validation behind two read queries;
  the SQLite adapter owns schema-to-domain protocol conversion and registry
  installation.
- Dependency direction is persistence/bootstrap -> application query ->
  strategy and plan domain modules. Tests cross the same named application or
  domain interface used by callers.
- Migration 0015 is byte-for-byte unchanged. Migration 0016 has not been
  applied outside isolated pytest roots.
- Searches found no public strategy-authoring command, alias, second catalog,
  free DSL, feature flag, dual read/write, compatibility path, `TODO`, or
  `FIXME` in the Ticket-03 surface.
- Security-only legacy plan lookup and AST@1 runtime removal remain explicit
  owned work for tickets 04 and 06 inside the same not-yet-applied cohort;
  they are not exposed through the new Model B interface.

## Acceptance mapping

| Acceptance | Current evidence |
|---|---|
| `TDK-AC-008` | exact acceptance-matrix test name proves only two built-ins, immutable hashes, finite parameter rejection, and absence of authoring commands |

Ticket 16 owns final canonical cross-ticket acceptance.
