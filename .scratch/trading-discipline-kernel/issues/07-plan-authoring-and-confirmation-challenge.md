# 07 — Plan authoring and confirmation challenge

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 06

## Scope

Implement draft authoring/revision/rejection, canonical diff, `PlanConfirmationChallenge`, `UserApprovalReceipt`, confirm-and-enable, and confirm-without-enable. Enforce explicit user approval and separate decision actor, interaction channel, and transport actor.

## Exact files and symbols

- Add `src/trading_platform/application/trade_plan_authoring.py::{CreateTradePlanDraft,ReviseTradePlanDraft,RejectTradePlanDraft,IssuePlanConfirmationChallenge,ConfirmTradePlanVersion}`.
- Add `src/trading_platform/domain/approvals.py::{PlanConfirmationChallenge,UserApprovalReceipt,ActivationIntent,CanonicalPlanDiff}`.
- Extend `src/trading_platform/domain/plans.py::{PlanVersionConfirmed,PlanActivated,PlanDraftRejected}`.
- Extend `src/trading_platform/persistence/plans.py::{save_challenge,consume_challenge,save_approval_receipt,confirm_and_activate}`.
- Replace `src/trading_platform/application/web_tasks.py::PlanConfirmation` and update `src/trading_platform/application/bootstrap.py::open_trade_plan`.

## Migration

Complete draft, challenge, receipt, confirmation, and activation schema/constraints in 0016 before its first application. Challenge consumption and receipt uniqueness must be storage-enforced.

## Tests

- Add `tests/platform/test_plan_confirmation.py`.
- Replace confirmation cases in `tests/platform/test_trade_plans.py`, `tests/platform/test_account_workspace_plans.py`, and `tests/platform/test_runtime_skeleton.py`.
- Cover stale revision/hash/diff/intent, expired or consumed challenge, agent denial, idempotent replay, two-event receipt, confirm-only, reject, atomic failure, and full-graph seal.

## Dependency

Requires 06. Ticket 08 exposes the command contract; ticket 13 reuses draft authoring.

## Acceptance gate

TDK-AC-010 and TDK-AC-015 through TDK-AC-017 pass. The default user operation persists `PlanVersionConfirmed` and `PlanActivated`; an Agent without explicit user confirmation cannot create either.

## Out of scope

Free strategy authoring, Web confirmation UI, automatic activation, research-driven mutation, or Agent decision authority.

## One-way cutover

Delete the old confirmation facade/path and any caller that confirms from plan ID alone. No compatibility challenge, implicit activation, or transport-actor inference is allowed.

## Claim record

- External seams: plan-authoring named commands, canonical challenge payload,
  explicit user approval receipt, and the atomic confirmation/activation
  transaction.
- Deep-module ownership: `domain/approvals.py` owns diff, intent, actor and
  challenge/receipt invariants; `application/trade_plan_authoring.py` owns the
  complete authoring tasks; `SQLiteTradePlanRepository` owns revision,
  challenge consumption, immutable events, and activation transactions.
- Old paths to replace: graph sealing that consumes a caller-seeded receipt,
  confirmation from plan identity alone, Web `PlanConfirmation`, and any
  inferred actor/channel/transport values.
- Superseded artifacts to delete: direct approval fixture SQL used as a
  production seam, old confirmation facade/tests/routes, implicit activation
  branches, and mutable or reusable challenge records.

## Resolution

- Draft create/revise/reject, challenge issue, and explicit user confirmation
  now cross one named application task seam with separate decision,
  interaction, and transport actors.
- Challenge and receipt bind the complete draft graph, canonical diff,
  activation intent, expiry, and command invocation. Storage guards challenge
  terminal transitions and receipt uniqueness.
- Default confirmation atomically writes receipt, full graph,
  `PlanVersionConfirmed`, `PlanActivated`, activation/transition, and command
  replay receipt. Confirm-only and reject preserve the active slot.
- Direct master/seal/activate commands and caller-authored approval rows are
  deleted; all current tests use the public authoring interface.
- Cohort-B migration 0016 is content-complete, passes rollback/replay and
  mapped-history reconstruction, and remains unapplied to persistent repo
  roots. Evidence is recorded in
  `evidence/07-plan-authoring-and-confirmation-challenge.md`.
