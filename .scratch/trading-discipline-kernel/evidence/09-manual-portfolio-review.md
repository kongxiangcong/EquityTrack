# Ticket 09 — Manual portfolio review evidence

## Result

- Status: passed
- Acceptance: `TDK-AC-019`
- Public workflow: `manual_portfolio_review@1`
- Migration cohort: `0017`, created but not applied to persistent roots

## Implemented contract

- `StartManualPortfolioReview`, `ResumeManualPortfolioReview`, and
  `GetManualPortfolioReview` form the named application-task interface.
- Review windows use the last successful review end as the next exclusive
  cutoff. The first run requires an explicit cutoff equal to the confirmed
  account snapshot cutoff. Failed and incomplete runs do not advance it.
- Each positive holding produces a frozen item and committed checkpoint.
  `NO_CHANGE` and `MONITOR` create no decision task; missing or blocked plan
  evidence is `REVIEW_REQUIRED`.
- Graph corruption, active-plan uniqueness violations, incomplete selected
  sessions, manifest mismatch, and ledger corruption fail closed.
- Manifest content is deterministically built by the domain and committed
  through the existing `WorkflowLedger` and `ArtifactManifest` seam.
- The SQLite adapter owns session/context proof, transactions, immutable
  persistence, invocation replay/conflict rejection, and restart reads.
- The public `daily` CLI/Skill/application portfolio-review entry was deleted.
  No alias, fallback, dual route, scheduler, broker adapter, or automatic
  trading behavior was added.

## Migration evidence

- `migrations/0016_strategy_plan_model_b.sql` SHA-256:
  `732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`
- `migrations/0017_manual_review_journal.sql` SHA-256:
  `4BC5B38496A187E04B8CE0513F6BAB387C206C45979AEDF22E5D4053C41BE579`
- Known persistent roots remained unapplied:
  - `outputs/live-tushare-qualification-20260714/data/platform.sqlite3`:
    schema 11
  - `outputs/ui-smoke-20260714/data/platform.sqlite3`: schema 11
- Contract tests cover fresh application, reserved-table preflight rejection,
  transaction rollback, and idempotent replay.

## Verification

Completed focused command:

```text
python -m compileall -q src
python -m pytest -q tests/platform/test_manual_portfolio_review.py tests/platform/test_migration_0015_0017.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py
38 passed in 29.62s
```

Completed wider relevant regression command:

```text
python -m pytest -q tests/test_research_engine.py tests/test_skill_entrypoint.py tests/platform/test_cli_application_tasks.py tests/platform/test_manual_portfolio_review.py tests/platform/test_migration_0015_0017.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_application_command_envelope.py tests/platform/test_runtime_skeleton.py tests/platform/test_secure_workspace.py tests/platform/test_account_snapshots.py tests/platform/test_estimated_account_state.py tests/platform/test_plan_confirmation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_market_evaluation.py
127 passed in 69.33s
```

One earlier invocation combined compile and the focused tests under a
five-second tool window and was terminated with exit 124. It was not counted
as passing; the focused command above is the completed rerun.

## Mechanical self-audit

- Ticket-path `git diff --check`: passed.
- Active public daily symbol/route scan: only negative assertions remain.
- Ticket implementation `TODO`/`FIXME`/compatibility/fallback/dual-path scan:
  no implementation debt marker; `COMPATIBLE_PLAN_EVALUATION_MISSING` is a
  domain evidence reason, not runtime compatibility code.
- Deep-module audit: domain owns deterministic construction and invariants;
  application owns the complete task; persistence owns SQLite protocol and
  transactions; WorkflowLedger extensions own durable manifest publication
  and terminal workflow transitions. No hypothetical port or forwarding
  module was introduced.
- The production `/api/workspace` removal remains assigned to tickets 15/16
  and is not represented as complete here.
