# 06 — AST@2 and conflict policy

**Status:** ready-for-agent  
**Type:** task  
**Mode:** AFK  
**Blocked by:** 05

## Scope

Replace AST@1 with the finite AST@2 contract, deterministic HardRule evaluation, typed ReviewRule references, three-state operands, grid constraints, candidate intents, and the locked conflict resolver. Hard rules produce outcomes/tasks, never trades.

## Exact files and symbols

- Replace `src/trading_platform/domain/market.py::evaluate_rules`.
- Add `src/trading_platform/domain/rules.py::{RuleClass,RulePriority,RuleScope,CandidateIntent,OperandValue,EventWindow,GridConstraint,RuleAstV2,RuleEvaluation}`.
- Add `src/trading_platform/domain/conflicts.py::{ConflictPolicyV1,ConflictResolution,resolve_conflicts}`.
- Update `src/trading_platform/domain/plans.py::TradePlanRule` to store `ast_version=2` and sealed rule content.
- Update `src/trading_platform/market.py` application behavior to call the new evaluator through the canonical market/review task seam.

## Migration

Complete the AST@2 rule schema and `conflict_policy_version` constraints inside 0016 before first application. Convert only representable legacy rules; preflight blocks active non-representable rules instead of running AST@1.

## Tests

- Add `tests/platform/test_rule_ast_v2.py` and `tests/platform/test_conflict_resolver.py`.
- Replace AST@1 assertions in `tests/platform/test_market_evaluation.py`.
- Property-test known/unknown/not-applicable, quantities/notional, trading-session elapsed time, typed windows, grid constraints, corruption, invalidation/core-floor precedence, buy/sell conflict, resource conflict, unique grid level, and no action.

## Dependency

Requires 05. Tickets 07 and 09 use its typed evaluation result.

## Acceptance gate

TDK-AC-005, TDK-AC-012, TDK-AC-013, and TDK-AC-014 pass for rule evaluation. Every evaluation terminates in one locked resolver outcome with stable typed reason codes; no path emits or submits an order.

## Out of scope

Generic DSL, arbitrary functions, tactical scopes, Agent execution of HardRules, or direct plan mutation by ReviewRules.

## One-way cutover

Delete AST@1 parser/evaluator/runtime branches and fixtures after migration. Do not version-dispatch between AST@1 and AST@2 at runtime.
