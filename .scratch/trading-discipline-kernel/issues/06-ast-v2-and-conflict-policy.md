# 06 — AST@2 and conflict policy

**Status:** resolved
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

## Claim record

- External seams: sealed `TradePlanRule` content, exact market/account/event
  operand input, deterministic evaluation persistence, and the application
  market evaluation task.
- Deep-module ownership: `domain/rules.py` owns the finite AST, typed
  operands/windows/grid nodes and rule evaluation; `domain/conflicts.py`
  owns the complete locked terminal resolver; `domain/plans.py` owns sealed
  rule identity; the market application task owns orchestration only.
- Old paths to replace: AST@1 condition classes/evaluator, field-path lookup,
  policy-version selection, flat rule-result tuples, and security-only
  evaluation fixtures.
- Superseded artifacts to delete: AST@1 runtime symbols/tests/schema reads,
  any arbitrary expression/function branch, duplicate core-floor logic,
  and evaluator paths that can emit execution or mutate a plan.

## Resolution

- The sealed plan graph now stores only finite AST@2 rules, exact typed
  operands/candidate intents, and the locked conflict-policy identity.
- `domain/rules.py` owns deterministic rule evaluation and replay hashes;
  `domain/conflicts.py` owns the complete terminal precedence table.
- The market named task evaluates only the exact active plan and immutable
  market snapshot. Complete evaluation hashes provide immutable replay while
  distinct typed inputs remain distinct results.
- Migration 0016 converts only representable active AST@1 rules, reseals the
  current graph, and fails closed with full rollback for non-representable
  rules. AST@1 runtime paths and automatic provider-job evaluation are absent.
- TDK-AC-005, TDK-AC-012, TDK-AC-013, and TDK-AC-014 focused evidence is
  recorded in `evidence/06-ast-v2-and-conflict-policy.md`.
