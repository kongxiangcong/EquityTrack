# Ticket 13 — Plan impact and change proposal evidence

## Result

- Status: passed
- Acceptance: `TDK-AC-017`, `TDK-AC-025`
- Persistence cohort: `0017`, content-complete and still unapplied

## Implemented contract

- `FrozenPlanImpactEvidence@1` binds one immutable manual-review run/item and
  manifest to the referenced plan version and ReviewRule result. The
  application does not accept caller-supplied evidence truth or a caller hash.
- `PlanImpactAssessment@1` is content-addressed and immutable. Agent/system
  authorship is explicit. An `unable_to_determine` ReviewRule requires unable
  materiality, explicit uncertainty, and cannot be promoted to a determined
  finding.
- `PlanChangeProposal@1` stores append-only revisions, the assessment/base-plan
  lineage, exact base graph seal, a finite `PlanContentReplacementPatch@1`,
  and deterministic proposal diff hash.
- Agent-authored create-assessment/create-proposal commands and user-only
  accept/reject commands cross the closed shared envelope registry and persist
  canonical command receipts.
- Acceptance checks that the source plan version is still active, derives a
  proposed graph from the sealed base, and calls the existing canonical
  `CreateTradePlanDraft` or `ReviseTradePlanDraft`. It has no challenge,
  confirmation, activation, or direct plan-writer operation.
- Accepted and rejected proposal revisions leave the active graph hash and
  activation history unchanged. The resulting open Draft must still pass the
  existing validation, canonical diff, confirmation challenge, and explicit
  user confirmation path.
- Same-invocation acceptance replays. If proposal disposition storage fails,
  its revision and receipt roll back; retry reuses the already-safe ordinary
  Draft receipt and appends exactly one accepted proposal revision.

## Migration evidence

- `migrations/0016_strategy_plan_model_b.sql` remains unchanged at SHA-256:
  `732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`
- Final ticket-09–13 `migrations/0017_manual_review_journal.sql` SHA-256:
  `A53804AB84FF683C457B8B2C6718572D3B604690AF83E346EFD68AF3BC3F302C`
- Both known persistent roots remain at schema 11, so `0017` was not edited
  after first application:
  - `outputs/live-tushare-qualification-20260714/data/platform.sqlite3`
  - `outputs/ui-smoke-20260714/data/platform.sqlite3`
- Fresh cohort tests prove frozen authority hashes, actor constraints,
  immutable triggers, proposal predecessor revisions, invocation uniqueness,
  active-base checks, fail-closed migration, rollback, and idempotent replay.

## Verification

The initial contract run failed during collection because the required public
application/domain symbols did not exist. It was the required contract-first
red state and is not counted as passing.

Completed impact/proposal contract gate:

```text
python -m pytest -q tests/platform/test_plan_impact_assessments.py tests/platform/test_plan_change_proposals.py
8 passed in 6.51s
```

Completed final related review/plan/0017/restart/architecture gate:

```text
python -m compileall -q src
python -m pytest -q tests/platform/test_plan_impact_assessments.py tests/platform/test_plan_change_proposals.py tests/platform/test_manual_portfolio_review.py tests/platform/test_discipline_reviews.py tests/platform/test_decision_tasks.py tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_plan_confirmation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_application_command_envelope.py tests/platform/test_migration_0015_0017.py tests/platform/test_runtime_skeleton.py tests/platform/test_workflow_ledger_recovery.py
97 passed in 65.24s
```

Completed final wider current-state regression:

```text
python -m compileall -q src
python -m pytest -q tests/test_research_engine.py tests/test_skill_entrypoint.py tests/platform/test_cli_application_tasks.py tests/platform/test_action_log.py tests/platform/test_execution_records.py tests/platform/test_decision_tasks.py tests/platform/test_discipline_reviews.py tests/platform/test_plan_impact_assessments.py tests/platform/test_plan_change_proposals.py tests/platform/test_manual_portfolio_review.py tests/platform/test_migration_0015_0017.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_application_command_envelope.py tests/platform/test_runtime_skeleton.py tests/platform/test_secure_workspace.py tests/platform/test_account_snapshots.py tests/platform/test_estimated_account_state.py tests/platform/test_plan_confirmation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_market_evaluation.py tests/platform/test_skill_contract.py
165 passed in 96.68s
```

## Mechanical self-audit

- Domain owns frozen-evidence identity, unable-state invariants, assessment and
  proposal content hashes, finite patch semantics, immutable disposition, and
  deterministic proposed graph construction.
- Application owns complete author/create/accept/reject tasks, actor
  capability, stale-base ordering, and delegation to canonical plan
  authoring.
- SQLite owns immutable authority reads, active-base proof, proposal revision
  concurrency, transactions, receipts, exact JSON conversion, and replay.
- Domain/application modules import no SQLite or outward adapter layer and
  contain no SQL.
- Production plan-impact code has no confirmation/challenge/activation call,
  direct active-plan update, research write path, automatic acceptance,
  proposal-specific plan writer, compatibility alias, fallback, dual path,
  feature flag, TODO, or FIXME.
