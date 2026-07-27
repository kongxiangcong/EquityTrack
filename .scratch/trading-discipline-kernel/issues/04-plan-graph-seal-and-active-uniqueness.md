# 04 — Plan graph seal and active uniqueness

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 03

## Scope

Implement immutable plan versions and full-graph sealing, explicit activation history, one active master plan per account/security, and read-only `legacy_unsleeved` preservation. Close the current singular-latest lookup and lifecycle/activation inconsistency.

## Exact files and symbols

- Replace plan aggregates in `src/trading_platform/domain/plans.py::{TradePlanDraft,TradePlanVersion,TradePlanGraph,PlanActivation,PlanGraphSeal}`.
- Refactor `src/trading_platform/plans.py::PlanService` into complete authoring/activation behavior behind the new application task interface; delete obsolete forwarding behavior.
- Replace `src/trading_platform/persistence/plans.py::{SQLitePlanRepository,get_active_for_security}` with `SQLiteTradePlanRepository::{seal_version,activate_version,get_active_master}`.
- Update `src/trading_platform/application/web_tasks.py::PlanConfirmation` callers pending ticket 07, without adding compatibility methods.

## Migration

Complete the plan/master/version/activation/legacy mapping portions of 0016 and its preflight. Active legacy rows without explicit user-approved sleeve mapping block the migration. Enforce the partial unique active index in the database.

## Tests

- Add `tests/platform/test_trade_plan_model_b.py`.
- Replace relevant cases in `tests/platform/test_trade_plans.py` and `tests/platform/test_account_workspace_plans.py`.
- Add adversarial late-child insert/update and concurrent activation cases.
- Add migration tests for duplicate active plans, missing ownership, explicit mapping, and byte-preserved historical reconstruction.

## Dependency

Requires 03. Tickets 05 and 07 require the sealed aggregate.

## Acceptance gate

TDK-AC-003, TDK-AC-009, TDK-AC-010, and TDK-AC-026 pass. Storage, not “latest row” selection, guarantees active uniqueness; activating a new version leaves all prior version and activation history unchanged.

## Out of scope

Sleeve rule semantics, AST@2, Skill challenges, manual review, or Web views.

## One-way cutover

Delete the old `get_active_for_security` semantics, `user_fixture_input` runtime discriminator, and mutable child path. Do not add a legacy query fallback or synthesize sleeve classification.

## Claim record

- External seams: the complete plan authoring/activation application task,
  SQLite transaction and graph-seal adapter, explicit
  `LegacySleeveMapping@1` preflight artifact, plan evaluation/history foreign
  keys, and callers in Web tasks, workspace, market evaluation, tests, and
  synthetic fixtures.
- Deep-module ownership: `domain/plans.py` owns draft/version/graph,
  activation, seal, and lifecycle invariants; `application/trade_plan_authoring.py`
  owns complete plan tasks; `SQLiteTradePlanRepository` owns atomic graph
  persistence, storage uniqueness, immutable reconstruction, and activation
  transitions; migration 0016 owns lossless legacy conversion and mapping
  enforcement.
- Old paths to replace: `PlanService`, `SQLitePlanRepository`,
  `get_active_for_security`, security-only ownership, latest-row selection,
  plan-ID-only confirmation, mutable child insertion, and
  `user_fixture_input` as a runtime discriminator.
- Superseded artifacts to delete: the old plan command/view aggregate,
  private-seam tests and fixtures, old repository methods, old confirmation
  forwarding calls, retired SQL column reads, and any legacy mapping guess.
  Historical legacy content survives only as sealed
  `legacy_unsleeved` reconstruction or an explicitly user-approved mapping.

## Resolution

- The named trade-plan task now owns master creation, atomic full-graph
  sealing, activation, and active/graph queries. Domain objects own graph
  identity and lifecycle invariants; SQLite owns approval verification,
  immutable reconstruction, transactional sealing, activation history, and
  storage-enforced account/security uniqueness.
- Migration 0016 fails closed for missing ownership, duplicate active
  ownership, absent or non-canonical user-approved sleeve mappings, and
  mutable/incomplete legacy graphs. Inactive legacy content bytes remain
  read-only; explicit mappings preserve ownership and install exactly one
  open activation.
- The former PlanService, security-latest lookup, Web confirmation endpoint,
  runtime `user_fixture_input` discriminator, and retired private-seam tests
  were deleted. Ticket 07 will add the locked Skill confirmation flow rather
  than restoring a browser mutation route.
- Gate evidence is recorded in
  `evidence/04-plan-graph-seal-and-active-uniqueness.md`.
