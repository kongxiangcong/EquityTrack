# Ticket 10 — Decision task evidence

## Result

- Status: passed
- Acceptance: `TDK-AC-020`, `TDK-AC-021`, `TDK-AC-022`
- Persistence cohort: `0017`, still unapplied to persistent roots

## Implemented contract

- `DecisionTasks` exposes named list, defer, resolve, supersede, and typed
  workflow-reopen operations.
- `DecisionTask@1` identity freezes account/security, plan version, rule,
  candidate intent, review window, and normalized evidence identity.
- Eligible `REVIEW_REQUIRED` results materialize one persistent task in the
  manual-review commit transaction. `NO_CHANGE` and `MONITOR` materialize none.
- State is derived only from immutable, contiguous
  `DecisionTaskTransition@1` history.
- User disposition requires a user decision actor and an allowed
  channel/transport. Web and agent disposition fail closed. System workflow
  authority is limited to typed reopen and supersede edges.
- Specific date/session, next manual review, and evidence trigger deferrals
  reopen the same task. Plan replacement or condition invalidation supersedes
  it.
- `executed` without the ticket-11 execution record is rejected as
  `EXECUTION_RECORD_REQUIRED`; broker evidence never resolves a task.
- Same-invocation replay returns the historical transition projection and
  receipt. Different content under the same invocation is rejected.
- Concurrent initial materialization permits one writer, reports
  `RUNTIME_BUSY` for a colliding live writer, and replays to one task after the
  writer completes.

## Migration evidence

- `migrations/0016_strategy_plan_model_b.sql` SHA-256:
  `732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`
- Current `migrations/0017_manual_review_journal.sql` SHA-256:
  `6A8D9F2DAA222DACDF07D7CA6BB4F3AF1B92538A2BEEFAE7AF320E10F7757DA2`
- Both known persistent roots remain at schema 11:
  - `outputs/live-tushare-qualification-20260714/data/platform.sqlite3`
  - `outputs/ui-smoke-20260714/data/platform.sqlite3`
- Temporary migration tests continue to prove fresh application, fail-closed
  preflight, rollback, and replay.

## Verification

Initial contract run failed during collection because the named task did not
yet exist. That red result was not counted as passing.

Completed focused gate:

```text
python -m compileall -q src
python -m pytest -q tests/platform/test_decision_tasks.py tests/platform/test_manual_portfolio_review.py tests/platform/test_application_command_envelope.py tests/platform/test_migration_0015_0017.py tests/platform/test_workflow_ledger_recovery.py
49 passed in 32.74s
```

Completed final lifecycle/manual/restart gate after the last domain-invariant
change:

```text
python -m pytest -q tests/platform/test_decision_tasks.py tests/platform/test_manual_portfolio_review.py tests/platform/test_workflow_ledger_recovery.py
29 passed in 24.11s
```

Completed wider current-state regression gate:

```text
python -m compileall -q src
python -m pytest -q tests/test_research_engine.py tests/test_skill_entrypoint.py tests/platform/test_cli_application_tasks.py tests/platform/test_decision_tasks.py tests/platform/test_manual_portfolio_review.py tests/platform/test_migration_0015_0017.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_application_command_envelope.py tests/platform/test_runtime_skeleton.py tests/platform/test_secure_workspace.py tests/platform/test_account_snapshots.py tests/platform/test_estimated_account_state.py tests/platform/test_plan_confirmation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_market_evaluation.py tests/platform/test_skill_contract.py
140 passed in 76.96s
```

## Mechanical self-audit

- Domain and application decision-task modules import no SQLite or outward
  adapter layer.
- Domain owns identity/state-machine invariants; application owns complete
  task operations and capability; persistence owns unique materialization,
  transactions, append-only replay, and SQLite conversion.
- No transient Web task projection or in-memory task list exists.
- No alias, fallback, dual path, feature flag, broker-derived resolution,
  TODO, or FIXME was introduced. `COMPATIBLE_PLAN_EVALUATION_MISSING` is a
  domain evidence reason, not compatibility runtime code.
- Ticket diff, exact old-path scans, manifest/task/checkpoint rollback, receipt
  replay, and immutable transition checks pass.
