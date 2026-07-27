# 13 — PlanImpactAssessment and PlanChangeProposal

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 07, 09, 10, 12

## Scope

Implement Agent-authored PlanImpactAssessment from frozen Evidence/ReviewRules and PlanChangeProposal. Accepting a proposal may only create or revise a TradePlanDraft; confirmation challenge and explicit user approval remain mandatory before active-plan change.

## Exact files and symbols

- Add `src/trading_platform/domain/plan_impacts.py::{PlanImpactAssessment,PlanImpactFinding,PlanChangeProposal,ProposalDisposition}`.
- Add `src/trading_platform/application/plan_impacts.py::{CreatePlanImpactAssessment,CreatePlanChangeProposal,AcceptPlanChangeProposal,RejectPlanChangeProposal}`.
- Add `src/trading_platform/persistence/plan_impacts.py::SQLitePlanImpactRepository`.
- Reuse `src/trading_platform/application/trade_plan_authoring.py::{CreateTradePlanDraft,ReviseTradePlanDraft}`; do not create a proposal-specific plan writer.
- Update `src/trading_platform/application/manual_portfolio_review.py` to freeze assessment inputs.

## Migration

Complete assessment/proposal tables, frozen evidence references, source plan-version reference, proposal status, and produced-draft reference in 0017 before first application.

## Tests

- Add `tests/platform/test_plan_change_proposals.py` and `tests/platform/test_plan_impact_assessments.py`.
- Cover ReviewRule unable states, frozen evidence, Agent authorship, accept-to-draft only, reject, stale source plan, repeated acceptance, canonical diff/challenge reuse, and active graph immutability.

## Dependency

Requires 07, 09, 10, and 12. Ticket 14 projects assessments/proposals.

## Acceptance gate

TDK-AC-017 and TDK-AC-025 pass. Proposal acceptance cannot call activation; rejected or unconfirmed drafts leave the active plan content hash and activation history unchanged.

## Out of scope

Research auto-modifying plans, Agent approval, automatic proposal acceptance, target price/rating output, or unfrozen evidence evaluation.

## One-way cutover

Remove any path where research/evidence writes active plan content. All changes converge on the existing canonical authoring/challenge command; no proposal-specific compatibility activation exists.

## Claim record

- External seams: named create-assessment, create-proposal, accept-proposal, and
  reject-proposal application tasks. Proposal acceptance delegates only to the
  existing canonical `TradePlanAuthoring` create/revise draft operation.
- Deep-module ownership: `domain/plan_impacts.py` owns frozen assessment and
  proposal invariants, canonical patch/hash identity, lifecycle transitions,
  and stale-base rules; application owns Agent authorship/capability and
  accept-to-draft orchestration; SQLite owns frozen authority reads,
  concurrency, immutable assessment/proposal persistence, and replay.
- Old paths to replace: unfrozen review-rule summaries, evidence/research
  mutation of active plan content, caller-authored proposal diff identity, and
  any proposal acceptance that bypasses canonical draft validation/challenge.
- Superseded artifacts to delete: proposal-specific plan writer or activation
  route, direct active-plan update, automatic acceptance, Agent approval,
  mutable evidence references, duplicate canonical patch/diff calculator,
  compatibility alias, and tests of a retired direct-write seam.

## Resolution evidence

- Added evidence-bound `PlanImpactAssessment@1` and immutable
  `PlanChangeProposal@1` revisions. ReviewRule unable state remains unable with
  explicit uncertainty; Agent/system authorship cannot become user approval.
- Manual review now exposes one frozen input query that proves the immutable
  review item, manifest, referenced plan version, ReviewRule, result, and
  research/market evidence identities before assessment creation.
- Proposal creation stores a finite canonical content-replacement patch against
  the exact base graph seal. The application computes the proposed graph and
  delegates only to the existing `CreateTradePlanDraft` or
  `ReviseTradePlanDraft` task.
- Accept/reject require a user decision actor through the shared envelope.
  Acceptance stops at an open Draft; it neither issues nor consumes a
  confirmation challenge and never calls activation.
- Repeated acceptance replays both the ordinary draft receipt and proposal
  disposition. A stale active base fails before draft creation. Injected
  disposition failure rolls back the proposal revision and receipt; retry
  repairs the safe open-Draft boundary without duplication.
- TDK-AC-017 and TDK-AC-025 pass. The contract suite passed
  `8 passed in 6.51s`, the final related cohort gate passed
  `97 passed in 65.24s`, and the final wider regression passed
  `165 passed in 96.68s`.
- `0017` is content-complete for tickets 09–13 and remains unapplied to both
  known persistent roots at schema 11. Its final cohort SHA-256 is
  `A53804AB84FF683C457B8B2C6718572D3B604690AF83E346EFD68AF3BC3F302C`.
