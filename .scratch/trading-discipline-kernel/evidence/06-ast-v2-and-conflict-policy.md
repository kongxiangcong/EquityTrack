# Ticket 06 — AST@2 and conflict policy evidence

Date: `2026-07-27 Asia/Shanghai`
Branch: `codex/trading-discipline-kernel`
Parent: `58615f11c661500d516e441ac1fd5dbe0ff11825`

## Closed rule contract

- `RuleAstV2` is a finite recursive contract limited to boolean composition,
  typed comparison, complete-session elapsed time, typed event windows, and
  the unified grid constraint. Operand and event identities are closed
  taxonomies; arbitrary field lookup and function execution are absent.
- Operands preserve `known`, `unknown`, and `not_applicable` as distinct
  states. Exact candidate quantity, remaining quantity, and notional values
  use validated decimal/unit contracts and cannot become execution records.
- Sealed `TradePlanRule` rows carry class, priority, master/core/grid scope,
  typed candidate intent, applicability references, AST@2, and a deterministic
  content hash. Review rules route to assessment rather than executing the
  deterministic hard-rule path.
- Market evaluation has one application task. It derives market-price
  operands from the immutable snapshot, accepts typed non-market inputs,
  rejects duplicate or caller-forged market operands, evaluates the exact
  active graph, and persists one complete typed result.

## Locked conflict resolver

- `trade-plan-conflict@1` terminates in exactly one of `blocked`,
  `manual_review_required`, `decision_task`, or `no_action`.
- Precedence is corruption/blocker, invalidation/risk/core-floor, opposing
  intents, resource uncertainty, exact core-floor protection, unique legal
  grid level, cardinality conflict, then no valid trigger.
- A unique candidate produces only a decision-task identity. No rule,
  resolver, application service, adapter, or schema in this path creates or
  submits an order.
- Evaluation idempotency is keyed by the complete evaluation hash. Replaying
  identical inputs returns the immutable row; different resource/account
  inputs against the same plan and market snapshot persist a distinct result
  instead of silently reusing stale output.

## Migration and one-way cutover

- Migration 0016 stores only the AST@2 rule schema and the locked conflict
  policy for current rows. It has no runtime AST version dispatch.
- Explicitly mapped active AST@1 rules pass through the finite conversion
  function. Representable rules are resealed with current sleeve/rule/content
  hashes and a current graph seal, then reconstruct through
  `SQLiteTradePlanRepository.get_graph`.
- A non-representable active AST@1 rule fails
  `STRATEGY_PLAN_HISTORY_UNMIGRATABLE`; the migration transaction and ledger
  remain byte-for-byte unchanged.
- The old evaluator, condition classes, policy selection fields, provider-job
  evaluation template, automatic daily evaluation branch, and legacy
  evaluation tables are deleted. Historical pre-TDK audit documents are
  explicitly frozen evidence and are not callable instructions.

## Verification

Contract-first migration evidence:

```text
python -m pytest tests/platform/test_migration_0015_0017.py -q
12 passed in 6.68s
```

Terminal focused gate:

```text
python -m pytest tests/platform/test_rule_ast_v2.py tests/platform/test_conflict_resolver.py tests/platform/test_market_evaluation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_trade_plan_sleeves.py tests/platform/test_migration_0015_0017.py tests/platform/test_runtime_skeleton.py tests/platform/test_provider_qualification.py tests/platform/test_cli_application_tasks.py -q
66 passed in 28.78s

python -m compileall -q src/trading_platform
exit 0
```

One intermediate focused run had `62 passed, 4 failed`: three Ticket-05
fixtures correctly showed that total grid budget may be a whole-share
quantity smaller than one board lot, while quantity per candidate level must
remain lot-aligned; one shared codec assertion required an unknown top-level
field to classify as `TypeError`. The contracts were corrected and the full
focused gate was rerun. The failed run is not counted as a pass.

## Mechanical audit

- Cohesive behavior is separated between the finite rule evaluator, terminal
  conflict resolver, sealed plan aggregate, application task, and SQLite
  transaction/protocol adapters. No forwarding-only module was introduced.
- Runtime searches found no AST@1 evaluator/parser, retired condition class,
  evaluator policy selector, automatic evaluation template, compatibility
  alias, dual read/write, feature flag, `TODO`, or `FIXME`.
- Remaining AST@1 strings exist only in adversarial migration fixtures and a
  codec rejection test. Frozen pre-TDK audits retain historical symbol names
  but identify themselves as non-current evidence.
- `git diff --check` passed for the Ticket-06 scope. Ticket-00's three
  deliberately dirty authority paths remained excluded and unstaged.

## Acceptance mapping

| Acceptance | Current evidence |
|---|---|
| `TDK-AC-005` | current sealed Model-B graph owns only AST@2 rules and the locked conflict policy |
| `TDK-AC-012` | resolver contract proves exact core-floor precedence for grid decreases |
| `TDK-AC-013` | exact test replays known/unknown/not-applicable, sessions, events, and grid nodes with the same hash |
| `TDK-AC-014` | exact seven-case precedence table proves one stable terminal outcome and typed reason per case |

Ticket 16 owns final canonical cross-ticket acceptance.
