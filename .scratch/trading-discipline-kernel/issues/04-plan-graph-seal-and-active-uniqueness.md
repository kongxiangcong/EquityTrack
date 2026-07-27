# 04 — Plan graph seal and active uniqueness

**Status:** ready-for-agent  
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
