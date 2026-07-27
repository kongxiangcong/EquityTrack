# 10 — DecisionTask

**Status:** ready-for-agent  
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
