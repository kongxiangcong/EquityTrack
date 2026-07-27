# 03 — StrategyVersion and Model B ownership

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 00, 01

## Scope

Implement immutable `InvestmentThesisVersion`, the two built-in versioned strategies, their finite parameter contracts, and account/security-owned `TradePlanMaster` identity. Free strategy authoring is impossible in the public application interface.

## Exact files and symbols

- Add `src/trading_platform/domain/strategies.py::{InvestmentThesisVersion,StrategyDefinition,StrategyVersion,StrategyParameterContract,StrategyCatalog}`.
- Add `src/trading_platform/application/strategy_catalog.py::{GetStrategyCatalog,GetStrategyVersion}`.
- Add `src/trading_platform/persistence/strategies.py::{SQLiteStrategyRepository,install_builtin_strategy_versions}`.
- Add `src/trading_platform/domain/plans.py::{TradePlanMasterId,TradePlanMaster}` and require `account_id` plus canonical `security_id`.
- Update `src/trading_platform/application/bootstrap.py::{open_strategy_queries}`.

## Migration

Create the full, final cohort-B `migrations/0016_strategy_plan_model_b.sql`, including tables needed by tickets 03–07. Own `trading_platform.persistence.migration.MigrationRunner._preflight_strategy_plan_0016`. Do not apply 0016 to a persistent root until the cohort schema and tests are complete.

## Tests

- Add `tests/platform/test_strategy_catalog.py`.
- Add ownership/catalog cases to `tests/platform/test_trade_plan_model_b.py`.
- Add 0016 install/idempotency cases to `tests/platform/test_migration_0015_0017.py`.
- Verify immutable version hashes, exactly two public built-ins, rejected unknown parameters, and no create-strategy command.

## Dependency

Requires 00 and 01. Tickets 04–07 build on the cohort-B schema.

## Acceptance gate

TDK-AC-008 passes. The catalog exposes only `trend_hold_break_exit@1` and `core_plus_grid@1`; every plan master has an account and security owner.

## Out of scope

Sleeve behavior, AST evaluation, plan confirmation, review workflow, custom strategy authoring, or a generic DSL.

## One-way cutover

Replace unversioned strategy identifiers at the plan seam with immutable strategy-version references. Do not keep aliases or accept legacy strings at runtime; migration owns conversion.

## Claim record

- External seams: the read-only named strategy catalog queries, immutable
  SQLite registry installation/loading, exact `strategy_version_id` references
  from plan ownership, migration-0016 preflight, and later tickets 04–07 that
  complete the same sealed cohort schema before first rollout.
- Deep-module ownership: `domain/strategies.py` owns the finite built-in
  strategy identities and parameter contracts; `application/strategy_catalog.py`
  owns complete catalog/get tasks; `persistence/strategies.py` owns immutable
  registry protocol conversion and installation; `domain/plans.py` owns the
  account/security `TradePlanMaster` identity invariant; migration 0016 owns
  one-way legacy classification and the complete cohort-B storage graph.
- Old paths to replace: unversioned strategy strings at the plan seam,
  security-only plan ownership, singular latest-plan selection, and runtime
  dependence on `user_fixture_input` as a strategy discriminator. Tickets
  04–07 consume the schema and finish caller removal before cohort rollout.
- Superseded artifacts to delete: any public create/edit/upload-strategy
  command, legacy strategy aliases, security-only master identity helpers,
  duplicate catalog fixtures, and any runtime AST@1 or mutable-plan columns
  once their owning cohort tickets replace them. No compatibility reader or
  dual schema will be retained.

## Answer

Implemented the closed `StrategyVersion@1` registry, finite parameter
contracts, immutable SQLite adapter, named catalog queries, minimal immutable
`InvestmentThesisVersion@1`, and deterministic account/security-owned
`TradePlanMasterId`. The public catalog exposes exactly
`trend_hold_break_exit@1` and `core_plus_grid@1`; no create/edit/upload
strategy application or CLI command exists.

Migration 0016 now contains the complete cohort-B table and constraint
inventory required by tickets 03–07, installs the exact built-ins inside the
migration transaction, converts provable inactive legacy plan history to
read-only `legacy_unsleeved`, and fails closed for missing ownership, mutable
legacy drafts, corrupt rule graphs, lifecycle/activation disagreement, or an
active legacy plan without explicit user-approved sleeve mapping. The
migration was exercised only against disposable test roots and has not been
applied to a persistent development or production root. Tickets 04–07 own the
remaining runtime plan cutover before cohort-B first application.

Evidence: `evidence/03-strategy-version-and-model-b-ownership.md`.
