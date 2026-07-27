# Ticket 11 — Action log and execution record evidence

## Result

- Status: passed
- Acceptance: `TDK-AC-006`, `TDK-AC-023`, `TDK-AC-030`
- Persistence cohort: `0017`, still unapplied to persistent roots

## Implemented contract

- `ActionLogEntry@1` is an immutable user disposition with an optional linked
  correction.
- `ExecutionRecord@1` requires positive finite decimal quantity, typed
  increase/decrease intent, exact effective time/session, three-state
  price/fee operands, currency, and explicit verification state.
- `execution_record.declare@1` is the only executed-disposition command.
  `execution_record.correct@1` appends a complete replacement linked to the
  original; neither command mutates old history.
- Defer and non-execution resolve use `DecisionTasks` only. The internal
  `RecordTaskAction` transaction command is not a second public journal task.
- Action, execution, linked task transition, and receipt commit atomically.
  Executed disposition without a valid execution cannot be persisted.
- The SQLite journal implements the production `ExecutionRecordReader`.
  Estimated state folds only executions after the confirmed snapshot cutoff,
  chooses the active correction, changes position quantity deterministically,
  and never overwrites the snapshot.
- Unknown price or fee disables dependent cash calculation without fabricating
  a value. User-declared records are `user_declared_unverified`; missing
  external matching evidence is not “not executed”.
- No broker integration, order lifecycle, automatic fill, fee inference, tax
  lot, annotation write, or account-opening dual write exists.

## Migration evidence

- `migrations/0016_strategy_plan_model_b.sql` SHA-256:
  `732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`
- Current `migrations/0017_manual_review_journal.sql` SHA-256:
  `16608B72C45F53325FCEAD6D119577EBBD307D7186AEDC572C4051F50DE2EA51`
- Both known persistent roots remain at schema 11:
  - `outputs/live-tushare-qualification-20260714/data/platform.sqlite3`
  - `outputs/ui-smoke-20260714/data/platform.sqlite3`
- The cohort contract verifies correction uniqueness, user actor constraint,
  price/fee state-value consistency, immutable triggers, fresh application,
  fail-closed preflight, rollback, and idempotent replay.

## Verification

The initial action/execution contract run failed during collection because the
named application/domain contracts did not yet exist. It was not counted as
passing.

Completed contract-focused gate during implementation:

```text
python -m compileall -q src
python -m pytest -q tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_decision_tasks.py tests/platform/test_estimated_account_state.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_application_command_envelope.py tests/platform/test_migration_0015_0017.py tests/platform/test_runtime_skeleton.py
63 passed in 44.33s
```

After the single-entry deep-module audit, the current architecture/journal/
state/restart subset passed:

```text
python -m pytest -q tests/platform/test_runtime_skeleton.py tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_decision_tasks.py tests/platform/test_estimated_account_state.py tests/platform/test_workflow_ledger_recovery.py
41 passed in 32.91s
```

Completed final wider current-state regression:

```text
python -m compileall -q src
python -m pytest -q tests/test_research_engine.py tests/test_skill_entrypoint.py tests/platform/test_cli_application_tasks.py tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_decision_tasks.py tests/platform/test_manual_portfolio_review.py tests/platform/test_migration_0015_0017.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_application_command_envelope.py tests/platform/test_runtime_skeleton.py tests/platform/test_secure_workspace.py tests/platform/test_account_snapshots.py tests/platform/test_estimated_account_state.py tests/platform/test_plan_confirmation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_market_evaluation.py tests/platform/test_skill_contract.py
149 passed in 82.79s
```

An earlier wider run reported `148 passed, 1 failed`; the failure was the
architecture scanner treating the substring `order` inside an internal
Protocol name as an execution surface. The Protocol was renamed, the focused
architecture gate passed, and the full wider command above was rerun. The
failed run is not counted as a pass.

After deleting the redundant broad repository Protocol operation, the affected
current-state group passed:

```text
python -m compileall -q src
python -m pytest -q tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_decision_tasks.py tests/platform/test_runtime_skeleton.py
32 passed in 23.83s
```

## Mechanical self-audit

- Domain owns immutable facts, correction rules, verification state, and
  deterministic decimal normalization.
- Application exposes small declare/correct/list tasks and task-disposition
  orchestration; no second `record_action` application method remains.
- Persistence owns the cross-table transaction, replay, correction lookup,
  exact SQLite conversion, and execution-reader protocol.
- Domain/application journal modules import no SQLite or outward adapter layer.
- Active source contains no broker/order adapter or transient behavior-history
  path. Account import and annotations do not receive execution truth.
- No compatibility alias, fallback, dual write, feature flag, TODO, or FIXME
  was introduced.
