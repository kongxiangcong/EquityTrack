# Trading discipline kernel acceptance matrix

Status: canonical implementation ledger  
Criterion text: `trading-discipline-kernel-spec.md`, section 26  
Fixture: synthetic only; never user account data

Every row is closed only by a passing public-interface test plus its required persistence or browser evidence. A skipped, timed-out, externally blocked, or manually uninspected gate is not a pass.

| ID | Owner | Primary verification | Required evidence |
|---|---:|---|---|
| TDK-AC-001 | 01, 16 | `tests/platform/test_migration_0015_0017.py::test_fresh_and_populated_roots_upgrade_idempotently` | schema/hash manifest |
| TDK-AC-002 | 01, 16 | `tests/platform/test_migration_0015_0017.py::test_legacy_account_values_unknowns_and_refs_migrate_losslessly` | source/target comparison |
| TDK-AC-003 | 04, 16 | `tests/platform/test_migration_0015_0017.py::test_active_legacy_plan_requires_explicit_sleeve_mapping` | preflight block + unchanged DB |
| TDK-AC-004 | 01 | `tests/platform/test_account_snapshots.py::test_agent_draft_and_user_confirmation_capabilities` | draft, denial, version/transition |
| TDK-AC-005 | 01, 06 | `tests/platform/test_account_snapshots.py::test_optional_unknowns_only_disable_dependent_capabilities` | three-state operand evidence |
| TDK-AC-006 | 02, 11 | `tests/platform/test_estimated_account_state.py::test_projection_uses_latest_snapshot_and_confirmed_executions_only` | authority input identities |
| TDK-AC-007 | 02 | `tests/platform/test_estimated_account_state.py::test_new_snapshot_assesses_drift_without_rewriting_history` | drift + historical hashes |
| TDK-AC-008 | 03 | `tests/platform/test_strategy_catalog.py::test_only_two_builtin_strategy_versions_are_available` | catalog projection |
| TDK-AC-009 | 04 | `tests/platform/test_trade_plan_model_b.py::test_database_allows_one_active_master_per_account_security` | constraint failure/result code |
| TDK-AC-010 | 04, 07 | `tests/platform/test_trade_plan_model_b.py::test_confirmed_plan_graph_rejects_late_mutation` | adversarial graph-write results |
| TDK-AC-011 | 05 | `tests/platform/test_trade_plan_sleeves.py::test_only_strategy_compatible_core_and_grid_sleeves_are_accepted` | typed validation failures |
| TDK-AC-012 | 05, 06 | `tests/platform/test_trade_plan_sleeves.py::test_grid_sell_cannot_cross_core_floor` | blocked conflict result |
| TDK-AC-013 | 06 | `tests/platform/test_rule_ast_v2.py::test_ast_v2_operands_sessions_events_and_grid_replay` | evaluation replay hash |
| TDK-AC-014 | 06 | `tests/platform/test_conflict_resolver.py::test_conflict_precedence_table` | seven terminal outcomes |
| TDK-AC-015 | 07 | `tests/platform/test_plan_confirmation.py::test_agent_denied_and_stale_or_mismatched_challenge_rejected` | capability/challenge failures |
| TDK-AC-016 | 07 | `tests/platform/test_plan_confirmation.py::test_confirm_and_enable_emits_events_and_receipt_atomically` | two events + receipt |
| TDK-AC-017 | 07, 13 | `tests/platform/test_plan_confirmation.py::test_confirm_only_and_rejected_draft_leave_active_slot_unchanged` | active hash + draft transition |
| TDK-AC-018 | 08 | `tests/platform/test_application_command_envelope.py::test_skill_cli_and_web_codecs_share_request_hash_and_result_schema` | three-channel codec evidence |
| TDK-AC-019 | 09 | `tests/platform/test_manual_portfolio_review.py::test_window_uses_last_successful_cutoff_to_selected_complete_session` | run/checkpoint/manifest |
| TDK-AC-020 | 10 | `tests/platform/test_decision_tasks.py::test_no_change_creates_no_task` | zero task rows |
| TDK-AC-021 | 10 | `tests/platform/test_decision_tasks.py::test_single_grid_trigger_creates_one_persistent_task` | deterministic task identity |
| TDK-AC-022 | 10 | `tests/platform/test_decision_tasks.py::test_all_deferral_conditions_reopen_the_same_task` | transition + reopened projection |
| TDK-AC-023 | 11 | `tests/platform/test_execution_records.py::test_executed_disposition_updates_estimated_state` | execution + projection |
| TDK-AC-024 | 12 | `tests/platform/test_discipline_reviews.py::test_overridden_is_identified_and_unrecorded_is_not_skipped` | immutable review version |
| TDK-AC-025 | 13 | `tests/platform/test_plan_change_proposals.py::test_accept_or_reject_proposal_has_only_draft_side_effects` | active activation unchanged |
| TDK-AC-026 | 04, 07 | `tests/platform/test_trade_plan_model_b.py::test_new_activation_preserves_old_version_history` | old graph hash |
| TDK-AC-027 | 14 | `tests/platform/test_versioned_read_models.py::test_web_and_skill_serialize_identical_application_dtos` | read-model ID + content hash |
| TDK-AC-028 | 16 | `tests/platform/test_trading_discipline_kernel_e2e.py::test_restart_replay_is_idempotent` | no duplicate identity set |
| TDK-AC-029 | 16 | `tests/platform/test_trading_discipline_kernel_backup_restore.py::test_full_chain_rebuilds_after_restore` | restored chain manifest |
| TDK-AC-030 | 11, 16 | `tests/platform/test_execution_records.py::test_missing_broker_evidence_is_unverified_not_not_executed` | verification state |
| TDK-AC-031 | 15 | `tests/platform/test_production_web.py::test_navigation_home_allowlist_progressive_disclosure_and_accessibility` | CDP DOM/screenshots |
| TDK-AC-032 | 15, 16 | `tests/platform/test_production_web.py::test_unversioned_workspace_and_public_daily_routes_are_absent` | route scan + 404 results |
| TDK-AC-033 | 16 | `tests/platform/test_architecture_boundaries.py::test_business_import_graph_has_no_llm_order_or_scheduler_surface` | import graph report |
| TDK-AC-034 | 08, 16 | `tests/platform/test_application_command_envelope.py::test_all_mutations_cross_named_tasks_and_envelope` | mutation inventory |
| TDK-AC-035 | 16 | `tests/platform/test_acceptance_evidence.py::test_report_preserves_exact_failure_timeout_and_external_status` | canonical acceptance report |

## Required suite groups

### Contract

- `tests/platform/test_account_snapshots.py`
- `tests/platform/test_estimated_account_state.py`
- `tests/platform/test_strategy_catalog.py`
- `tests/platform/test_trade_plan_model_b.py`
- `tests/platform/test_trade_plan_sleeves.py`
- `tests/platform/test_rule_ast_v2.py`
- `tests/platform/test_conflict_resolver.py`
- `tests/platform/test_plan_confirmation.py`
- `tests/platform/test_application_command_envelope.py`

### Workflow and journal

- `tests/platform/test_manual_portfolio_review.py`
- `tests/platform/test_decision_tasks.py`
- `tests/platform/test_execution_records.py`
- `tests/platform/test_discipline_reviews.py`
- `tests/platform/test_plan_change_proposals.py`

### Presentation

- `tests/platform/test_versioned_read_models.py`
- existing `tests/platform/test_web_application_tasks.py`
- existing `tests/platform/test_secure_workspace.py`
- `tests/platform/test_production_web.py`
- `tests/platform/test_skill_contract.py`

### Migration and operations

- `tests/platform/test_migration_0015_0017.py`
- `tests/platform/test_trading_discipline_kernel_e2e.py`
- `tests/platform/test_trading_discipline_kernel_backup_restore.py`
- existing `tests/platform/test_operations_backup_restore.py`
- existing `tests/platform/test_workflow_ledger_recovery.py`
- existing `tests/platform/test_acceptance_evidence.py`

## Evidence rules

- Database evidence includes schema version, row identities, immutable content hashes, and constraint results.
- Browser evidence is produced against the production asset tree using CDP and includes DOM assertions, console output, network failures, and screenshots for the four primary pages.
- Restart evidence uses the same persistent root across process restarts.
- Replay evidence repeats the same command envelopes and review inputs with stable idempotency keys.
- Restore evidence uses a distinct temporary root and verifies the authority chain from snapshot through discipline review.
- The final acceptance command reports suite identity, per-suite duration, pass/fail/skip/timeout counts, artifact paths, and the first failing substep.
