# 03 — StrategyVersion and Model B ownership

**Status:** ready-for-agent  
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
