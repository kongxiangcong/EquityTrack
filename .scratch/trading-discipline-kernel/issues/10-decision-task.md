# 10 — DecisionTask

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 09

## Scope

Implement persistent decision tasks with states `open`, `deferred`, `resolved`, `superseded`; deterministic identity; deferral by date/session, next manual review, or evidence trigger; and user dispositions `executed`, `deferred`, `skipped`, `overridden`, `not_applicable`.

## Exact files and symbols

- Add `src/trading_platform/domain/decision_tasks.py::{DecisionTask,DecisionTaskState,DecisionTaskTransition,DeferralCondition,UserDisposition,derive_task_identity}`.
- Add `src/trading_platform/application/decision_tasks.py::{ListDecisionTasks,DeferDecisionTask,ResolveDecisionTask,SupersedeDecisionTask}`.
- Add `src/trading_platform/persistence/decision_tasks.py::SQLiteDecisionTaskRepository`.
- Update `src/trading_platform/application/manual_portfolio_review.py` to materialize tasks only from eligible results.
- Update `src/trading_platform/application/bootstrap.py::open_decision_tasks`.

## Migration

Complete task/transition tables and deterministic unique constraints in 0017 before first application.

## Tests

- Add `tests/platform/test_decision_tasks.py`.
- Extend `tests/platform/test_manual_portfolio_review.py` and `tests/platform/test_workflow_ledger_recovery.py`.
- Cover `NO_CHANGE` zero-task, unique grid trigger, buy/sell manual review, persistence, all deferral forms, invalidation/supersession, dispositions, restart/replay, and concurrent materialization.

## Dependency

Requires 09. Ticket 11 attaches action/execution records; ticket 14 projects unresolved tasks.

## Acceptance gate

TDK-AC-020 through TDK-AC-022 pass. A task survives until disposition, supersession, or invalidation; the same review input never creates a duplicate.

## Out of scope

Automatic execution, broker orders, notification scheduler, plan mutation, or hiding unresolved tasks after a restart.

## One-way cutover

Replace transient evaluation-task presentation with persisted DecisionTask identity. Do not retain a parallel in-memory task list or infer resolution from broker evidence.

## Claim record

- External seams: named `ListDecisionTasks`, `DeferDecisionTask`,
  `ResolveDecisionTask`, and `SupersedeDecisionTask` application operations;
  task materialization remains internal to the successful
  `manual_portfolio_review@1` transaction.
- Deep-module ownership: `domain/decision_tasks.py` owns deterministic identity,
  state derivation, deferral conditions, dispositions, and transition
  invariants; `application/decision_tasks.py` owns complete list/defer/resolve/
  supersede tasks and actor/capability policy; the SQLite adapter owns unique
  materialization, append-only transitions, concurrency, replay, and restart
  projection.
- Old paths to replace: transient `PlanEvaluation` decision-task presentation,
  any review-result-only task inference, and caller-side open/deferred state
  calculation.
- Superseded artifacts to delete: in-memory task lists, duplicate task DTOs,
  direct table writes, broker-evidence-derived resolution, compatibility
  aliases, and tests of retired transient/private task seams.

## Resolution evidence

- Eligible manual-review items now materialize deterministic `DecisionTask@1`
  rows in the same transaction as their frozen review item and manifest.
  `NO_CHANGE` and `MONITOR` remain zero-task outcomes.
- Domain invariants own task identity and the only valid lifecycle edges.
  SQLite owns unique materialization, append-only transitions, historical
  receipt replay, restart projection, concurrent-writer fail-closed behavior,
  and transaction rollback.
- Named list/defer/resolve/supersede/reopen application operations enforce the
  actor/channel/transport matrix. Shared-envelope defer/resolve receipts use
  the canonical application-command hash. `executed` fails closed until ticket
  11 supplies the required atomic execution record.
- All three deferral forms reopen the same task identity. User terminal
  dispositions, plan/condition supersession, immutable history, concurrent
  materialization, restart, and invocation conflicts have public-interface
  regression coverage.
- The focused gate passed `49 passed in 32.74s`; the final task/manual/restart
  gate passed `29 passed in 24.11s`; the final wider current-state regression
  passed `140 passed in 76.96s`.
- Cohort `0017` remains unapplied to both known persistent roots. Its current
  SHA-256 is
  `6A8D9F2DAA222DACDF07D7CA6BB4F3AF1B92538A2BEEFAE7AF320E10F7757DA2`;
  `0016` remains unchanged.
