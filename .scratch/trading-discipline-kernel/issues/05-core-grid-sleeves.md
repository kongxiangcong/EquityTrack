# 05 — Core and grid sleeves

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 04

## Scope

Implement the closed `PositionSleeve` taxonomy (`core`, optional `grid`), sleeve allocation invariants, core floor, and strategy-to-sleeve parameter binding. The master plan remains the single account/security strategy instance.

## Exact files and symbols

- Add to `src/trading_platform/domain/plans.py::{PositionSleeveKind,PositionSleeve,CoreSleeve,GridSleeve,CoreFloor}`.
- Add `src/trading_platform/domain/strategies.py::{TrendHoldBreakExitParameters,CorePlusGridParameters}`.
- Extend `src/trading_platform/persistence/plans.py::SQLiteTradePlanRepository` to persist sealed sleeve rows.
- Add deterministic validation in `src/trading_platform/domain/plans.py::{validate_sleeve_contract,validate_sleeve_quantities}`; ticket 07 invokes it through the complete authoring task.

## Migration

Complete sleeve tables, constraints, and explicit legacy mapping columns in 0016 before its first application. `legacy_unsleeved` is historical/read-only and cannot be activated.

## Tests

- Add `tests/platform/test_trade_plan_sleeves.py`.
- Extend `tests/platform/test_strategy_catalog.py` for parameter/sleeve compatibility.
- Cover missing core, duplicate core/grid, tactical rejection, negative/unknown floor, grid bounds, strategy mismatch, sealed mutation, and explicit legacy mapping.

## Dependency

Requires 04. Ticket 06 evaluates sleeve-scoped rules; ticket 07 authors valid drafts.

## Acceptance gate

TDK-AC-011 and TDK-AC-012 pass. A `trend_hold_break_exit@1` plan has one core sleeve; `core_plus_grid@1` has core plus optional grid; no grid candidate can reduce remaining quantity below core floor.

## Out of scope

Tactical sleeves, multiple active masters, tax-lot accounting, order generation, or broker positions.

## One-way cutover

Move sleeve behavior completely into the sealed plan graph. Delete any flat-plan quantity fields that duplicate the new source of truth; do not mirror sleeve state in a compatibility column.

## Claim record

- External seams: Model B graph construction/validation, immutable strategy
  parameter contracts, SQLite sleeve/grid rows, and explicit 0016 legacy
  mapping input.
- Deep-module ownership: `domain/plans.py` owns sleeve taxonomy, exact share
  quantities, allocation/core-floor invariants, and candidate floor checks;
  `domain/strategies.py` owns the two closed parameter contracts;
  `SQLiteTradePlanRepository` owns exact decimal protocol conversion and
  sealed sleeve/grid persistence.
- Old paths to replace: untyped sleeve mappings, caller-authored content
  hashes, flat plan loss/quantity fields, and any rule-side duplicate
  core-floor decision.
- Superseded artifacts to delete: mapping-shaped sleeve fixtures, duplicated
  quantity fields/tests, any tactical/legacy authoring branch, and stale
  schema/docs that present flat plan quantities as current truth.

## Resolution

- The closed typed sleeve graph now owns exact core/grid allocation,
  mandatory known core floor, grid bounds/levels/lot/cooldown, and the
  deterministic decrease floor check.
- Built-in strategy parameter objects enforce their cross-field contracts;
  catalog validation invokes them after the finite field contracts.
- SQLite persists and reconstructs typed sleeve and grid rows inside the
  graph-seal transaction. Migration 0016 validates the same domain contract
  for explicit mappings and installs exact mapped grid constraints.
- Mapping-shaped runtime sleeves and flat-plan quantity tests are absent.
  Evidence is recorded in
  `evidence/05-core-grid-sleeves.md`.
