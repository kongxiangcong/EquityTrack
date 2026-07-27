# Ticket 14 — Versioned read-model evidence

## Result

- Status: passed
- Acceptance: `TDK-AC-027`
- Migration: none

## Implemented contract

- Six frozen application DTOs expose only versioned presentation contracts:
  `PortfolioWorkspaceView@1`, `HoldingWorkspaceView@1`,
  `TradePlanDetailView@1`, `ReviewWorkspaceView@1`,
  `ResearchIndexView@1`, and `AccountSnapshotEditorView@1`.
- `ReadModelService` is the only application read entry. It derives stable
  source identities, projection IDs, generated-at values, and content hashes
  from the SQLite projection result.
- `SQLiteReadModelProjection` owns the real protocol conversion across account
  snapshots, estimated state, plans, reviews, proposals, tasks, and persisted
  research evidence. It does not manufacture missing account or evidence
  facts.
- `encode_read_model` is the single deterministic external serialization
  codec. The Web and Skill contract test serializes the same application DTO
  through that codec and proves byte equality.
- `PortfolioWorkspaceView@1` has exactly the five permitted summary groups:
  accounts, estimated totals, positions, open tasks, and active-plan summaries.
  It contains no raw SQL rows, credentials, provider internals, diagnostics
  wall, arbitrary provenance payload, or mutable domain object.
- Detailed views preserve explicit `unknown`, `unable_to_determine`, and
  `unverified` values and retain only redacted evidence/source identities.
- Nested mappings are recursively immutable, not merely held by a frozen outer
  dataclass.

## One-way replacement

- Deleted `DecisionWorkspace`, `open_decision_workspace`,
  `EstimatedAccountWorkspace`, and the old application workspace protocol.
- Deleted the monolithic `WorkspaceService.build` projection and retained only
  the cohesive replay-safe update-authorization transaction.
- Deleted the backend `/api/workspace` route and its CLI/bootstrap composition.
  A regression proves that retired route returns 404.
- Replaced fixtures and assertions tied to the retired mapping. The production
  asset caller is the declared Ticket 15 cutover target and is not represented
  as a compatibility route or alternate backend model.
- Replaced a stale test query against retired `trade_plan` with the canonical
  `trade_plan_master` and `trade_plan_version` tables.

## Verification

Initial exact read-model gate after recursive immutability:

```text
python -m pytest -q tests/platform/test_versioned_read_models.py
3 passed in 3.55s
```

Focused application/Web/security/operations gate:

```text
python -m pytest -q tests/platform/test_versioned_read_models.py tests/platform/test_web_application_tasks.py tests/platform/test_secure_workspace.py tests/platform/test_chart_annotations.py tests/platform/test_workspace_persistence.py tests/platform/test_account_opening.py tests/platform/test_runtime_skeleton.py tests/platform/test_operations_backup_restore.py::test_backup_restore_new_root_preserves_database_objects_and_history tests/platform/test_operations_backup_restore.py::test_windows_cli_backup_restore_doctor_serve_history_and_secret_redaction
54 passed, 1 transient Windows socket abort in a cross-origin rejection case
```

The socket-abort case was not counted as a pass. Its entire parameterized
contract was immediately rerun:

```text
python -m pytest -q tests/platform/test_secure_workspace.py::test_rejects_rebinding_cross_origin_and_wrong_content_type
3 passed in 4.81s
```

After replacing the stale retired-schema assertion, the wider related
public-interface regression completed:

```text
python -m pytest -q tests/platform/test_account_snapshots.py tests/platform/test_action_log.py tests/platform/test_application_command_envelope.py tests/platform/test_discipline_reviews.py tests/platform/test_estimated_account_state.py tests/platform/test_execution_records.py tests/platform/test_manual_portfolio_review.py tests/platform/test_plan_change_proposals.py tests/platform/test_plan_confirmation.py tests/platform/test_plan_impact_assessments.py tests/platform/test_research_workflow.py tests/platform/test_trade_plan_model_b.py tests/platform/test_trade_plan_sleeves.py tests/platform/test_versioned_read_models.py tests/platform/test_web_application_tasks.py tests/platform/test_secure_workspace.py tests/platform/test_chart_annotations.py tests/platform/test_workspace_persistence.py
101 passed in 82.32s
```

`python -m compileall -q src` also completed successfully.

## Mechanical self-audit

- Application DTO/service, external codec, SQLite protocol conversion, Web
  server composition, and authorization transaction remain in distinct
  cohesive modules with inward dependency direction.
- The single SQLite projection module contains the six related authority
  projections; it does not absorb domain invariants, codec logic, Web routing,
  or application command orchestration.
- Searches found no active Python `DecisionWorkspace`,
  `open_decision_workspace`, `EstimatedAccountWorkspace`,
  `WorkspaceService.build`, `root.workspace`, or `/api/workspace` caller.
  The only Python route string is the explicit retired-route 404 assertion.
- No compatibility alias, fallback, dual read/write, feature flag, dormant
  branch, `TODO`, or `FIXME` was introduced.
