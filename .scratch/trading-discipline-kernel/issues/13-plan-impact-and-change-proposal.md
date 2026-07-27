# 13 — PlanImpactAssessment and PlanChangeProposal

**Status:** ready-for-agent  
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
