CREATE TABLE manual_portfolio_review_run (
  review_run_id TEXT PRIMARY KEY,
  workflow_run_id TEXT NOT NULL UNIQUE REFERENCES workflow_run(workflow_run_id),
  invocation_id TEXT NOT NULL UNIQUE,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  requested_at TEXT NOT NULL,
  selected_complete_session TEXT NOT NULL,
  timezone TEXT NOT NULL CHECK(timezone='Asia/Shanghai'),
  window_start_exclusive TEXT NOT NULL,
  window_end_inclusive TEXT NOT NULL,
  prior_successful_review_run_id TEXT REFERENCES manual_portfolio_review_run(review_run_id),
  status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','succeeded_with_limits','failed')),
  input_fingerprint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  schema_version TEXT NOT NULL CHECK(schema_version='ManualPortfolioReviewRun@1'),
  CHECK(window_start_exclusive < window_end_inclusive),
  CHECK(
    (status IN ('queued','running') AND completed_at IS NULL)
    OR (status IN ('succeeded','succeeded_with_limits','failed') AND completed_at IS NOT NULL)
  )
);
CREATE UNIQUE INDEX one_running_manual_review_per_account
ON manual_portfolio_review_run(account_id)
WHERE status IN ('queued','running');

CREATE TABLE manual_portfolio_review_item (
  review_item_id TEXT PRIMARY KEY,
  review_run_id TEXT NOT NULL REFERENCES manual_portfolio_review_run(review_run_id),
  account_id TEXT NOT NULL REFERENCES account(account_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  position_identity TEXT NOT NULL,
  account_snapshot_version_id TEXT NOT NULL REFERENCES account_snapshot_version(account_snapshot_version_id),
  account_snapshot_hash TEXT NOT NULL,
  estimated_state_hash TEXT NOT NULL,
  active_plan_id TEXT,
  plan_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  plan_evaluation_id TEXT REFERENCES plan_evaluation(plan_evaluation_id),
  evaluation_reason_code TEXT,
  strategy_version_id TEXT REFERENCES strategy_version(strategy_version_id),
  sleeve_graph_json TEXT NOT NULL,
  data_snapshot_ids_json TEXT NOT NULL,
  research_run_ids_json TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  market_snapshot_ids_json TEXT NOT NULL,
  hard_rule_evaluations_json TEXT NOT NULL,
  review_rule_routing_json TEXT NOT NULL,
  conflict_resolution_json TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('NO_CHANGE','MONITOR','REVIEW_REQUIRED','DRAFT_UPDATE_PROPOSED')),
  material_changes_json TEXT NOT NULL,
  unable_reasons_json TEXT NOT NULL,
  blocked_reasons_json TEXT NOT NULL,
  decision_task_ids_json TEXT NOT NULL,
  plan_impact_assessment_ids_json TEXT NOT NULL,
  plan_change_proposal_ids_json TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  schema_version TEXT NOT NULL CHECK(schema_version='SecurityReviewItem@1'),
  UNIQUE(review_run_id,security_id)
);

CREATE TABLE manual_portfolio_review_checkpoint (
  checkpoint_id TEXT PRIMARY KEY,
  review_run_id TEXT NOT NULL REFERENCES manual_portfolio_review_run(review_run_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  stage TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','running','committed','failed')),
  manifest_id TEXT REFERENCES manual_portfolio_review_manifest(manifest_id),
  attempt_no INTEGER NOT NULL CHECK(attempt_no > 0),
  committed_at TEXT,
  schema_version TEXT NOT NULL CHECK(schema_version='ReviewCheckpoint@1'),
  UNIQUE(review_run_id,security_id,stage),
  CHECK((status='committed' AND manifest_id IS NOT NULL AND committed_at IS NOT NULL) OR status<>'committed')
);

CREATE TABLE manual_portfolio_review_manifest (
  manifest_id TEXT PRIMARY KEY,
  review_run_id TEXT NOT NULL UNIQUE REFERENCES manual_portfolio_review_run(review_run_id),
  object_sha256 TEXT NOT NULL REFERENCES object_blob(sha256),
  artifact_manifest_id TEXT REFERENCES artifact_manifest(artifact_manifest_id),
  cutoff_identity TEXT NOT NULL,
  calendar_identity TEXT NOT NULL,
  policy_identities_json TEXT NOT NULL,
  account_snapshot_version_id TEXT NOT NULL REFERENCES account_snapshot_version(account_snapshot_version_id),
  estimated_state_hash TEXT NOT NULL,
  active_plan_version_ids_json TEXT NOT NULL,
  data_snapshot_ids_json TEXT NOT NULL,
  research_run_ids_json TEXT NOT NULL,
  market_snapshot_ids_json TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  rule_evaluator_conflict_versions_json TEXT NOT NULL,
  review_item_ids_json TEXT NOT NULL,
  checkpoint_ids_json TEXT NOT NULL,
  decision_task_ids_json TEXT NOT NULL,
  assessment_ids_json TEXT NOT NULL,
  proposal_ids_json TEXT NOT NULL,
  code_identity TEXT NOT NULL,
  config_identity TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  schema_version TEXT NOT NULL CHECK(schema_version='ManualPortfolioReviewManifest@1')
);

CREATE TABLE decision_task (
  decision_task_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  review_run_id TEXT NOT NULL REFERENCES manual_portfolio_review_run(review_run_id),
  review_item_id TEXT NOT NULL REFERENCES manual_portfolio_review_item(review_item_id),
  plan_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  plan_evaluation_id TEXT REFERENCES plan_evaluation(plan_evaluation_id),
  task_kind TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  priority TEXT NOT NULL,
  initial_status TEXT NOT NULL CHECK(initial_status='open'),
  condition_identity TEXT NOT NULL,
  evidence_manifest_id TEXT NOT NULL REFERENCES manual_portfolio_review_manifest(manifest_id),
  created_at TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL CHECK(schema_version='DecisionTask@1'),
  UNIQUE(account_id,security_id,condition_identity)
);

CREATE TABLE decision_task_transition (
  transition_id TEXT PRIMARY KEY,
  decision_task_id TEXT NOT NULL REFERENCES decision_task(decision_task_id),
  transition_seq INTEGER NOT NULL CHECK(transition_seq > 0),
  from_status TEXT NOT NULL CHECK(from_status IN ('open','deferred','resolved','superseded')),
  to_status TEXT NOT NULL CHECK(to_status IN ('open','deferred','resolved','superseded')),
  trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('user_disposition','date_or_session','next_review','evidence_trigger','plan_superseded','condition_invalidated')),
  disposition TEXT CHECK(disposition IN ('executed','deferred','skipped','overridden','not_applicable')),
  defer_target_type TEXT CHECK(defer_target_type IN ('specific_date_or_session','next_manual_review','evidence_trigger')),
  defer_target_value TEXT,
  evidence_ref TEXT,
  action_log_entry_id TEXT REFERENCES action_log_entry(action_log_entry_id),
  decision_actor TEXT NOT NULL,
  interaction_channel TEXT NOT NULL,
  transport_actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL CHECK(schema_version='DecisionTaskTransition@1'),
  UNIQUE(decision_task_id,transition_seq),
  CHECK((to_status='deferred' AND defer_target_type IS NOT NULL) OR to_status<>'deferred'),
  CHECK(
    (from_status='open' AND to_status='deferred' AND trigger_kind='user_disposition' AND disposition='deferred')
    OR (from_status='open' AND to_status='resolved' AND trigger_kind='user_disposition' AND disposition IN ('executed','skipped','overridden','not_applicable'))
    OR (from_status='deferred' AND to_status='open' AND trigger_kind IN ('date_or_session','next_review','evidence_trigger') AND disposition IS NULL)
    OR (from_status IN ('open','deferred') AND to_status='superseded' AND trigger_kind IN ('plan_superseded','condition_invalidated') AND disposition IS NULL)
  )
);

CREATE TABLE action_log_entry (
  action_log_entry_id TEXT PRIMARY KEY,
  decision_task_id TEXT NOT NULL REFERENCES decision_task(decision_task_id),
  decision_actor TEXT NOT NULL CHECK(decision_actor LIKE 'user:%'),
  interaction_channel TEXT NOT NULL,
  transport_actor TEXT NOT NULL,
  disposition TEXT NOT NULL CHECK(disposition IN ('executed','deferred','skipped','overridden','not_applicable')),
  reason TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  corrects_entry_id TEXT UNIQUE REFERENCES action_log_entry(action_log_entry_id),
  content_hash TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL CHECK(schema_version='ActionLogEntry@1')
);

CREATE TABLE execution_record (
  execution_record_id TEXT PRIMARY KEY,
  action_log_entry_id TEXT NOT NULL UNIQUE REFERENCES action_log_entry(action_log_entry_id),
  account_id TEXT NOT NULL REFERENCES account(account_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  plan_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  decision_task_id TEXT REFERENCES decision_task(decision_task_id),
  effective_at TEXT NOT NULL,
  effective_session TEXT NOT NULL,
  intent_type TEXT NOT NULL CHECK(intent_type IN ('increase','decrease')),
  quantity TEXT NOT NULL,
  price_state TEXT NOT NULL CHECK(price_state IN ('known','unknown','not_applicable')),
  price_value TEXT,
  fee_state TEXT NOT NULL CHECK(fee_state IN ('known','unknown','not_applicable')),
  fee_value TEXT,
  currency TEXT NOT NULL CHECK(length(currency)=3),
  verification_status TEXT NOT NULL CHECK(verification_status IN ('user_declared_unverified','broker_matched','conflicted')),
  corrects_execution_record_id TEXT UNIQUE REFERENCES execution_record(execution_record_id),
  content_hash TEXT NOT NULL UNIQUE,
  confirmed_at TEXT NOT NULL,
  schema_version TEXT NOT NULL CHECK(schema_version='ExecutionRecord@1'),
  CHECK(
    (price_state='known' AND price_value IS NOT NULL)
    OR (price_state IN ('unknown','not_applicable') AND price_value IS NULL)
  ),
  CHECK(
    (fee_state='known' AND fee_value IS NOT NULL)
    OR (fee_state IN ('unknown','not_applicable') AND fee_value IS NULL)
  )
);

CREATE TABLE discipline_review_version (
  discipline_review_id TEXT NOT NULL,
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  supersedes_version_no INTEGER,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  period_kind TEXT NOT NULL CHECK(period_kind IN ('weekly','custom')),
  period_start_session TEXT NOT NULL,
  period_end_session TEXT NOT NULL,
  timezone TEXT NOT NULL CHECK(timezone='Asia/Shanghai'),
  status TEXT NOT NULL CHECK(status IN ('draft','confirmed','superseded')),
  review_run_ids_json TEXT NOT NULL,
  decision_task_ids_json TEXT NOT NULL,
  action_log_entry_ids_json TEXT NOT NULL,
  execution_record_ids_json TEXT NOT NULL,
  plan_version_ids_json TEXT NOT NULL,
  account_snapshot_version_ids_json TEXT NOT NULL,
  exceptions_json TEXT NOT NULL,
  overridden_items_json TEXT NOT NULL,
  unrecorded_items_json TEXT NOT NULL,
  unverified_items_json TEXT NOT NULL,
  drift_assessment_ids_json TEXT NOT NULL,
  evidence_gap_summary_json TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  draft_invocation_id TEXT UNIQUE,
  confirmed_at TEXT,
  confirmation_command_receipt_id TEXT REFERENCES application_command_receipt(invocation_id),
  schema_version TEXT NOT NULL CHECK(schema_version='DisciplineReviewVersion@1'),
  PRIMARY KEY(discipline_review_id,version_no),
  FOREIGN KEY(discipline_review_id,supersedes_version_no)
    REFERENCES discipline_review_version(discipline_review_id,version_no),
  CHECK(period_start_session <= period_end_session),
  CHECK(
    (version_no=1 AND supersedes_version_no IS NULL)
    OR (version_no>1 AND supersedes_version_no=version_no-1)
  ),
  CHECK(
    (status='draft' AND draft_invocation_id IS NOT NULL AND confirmed_at IS NULL AND confirmation_command_receipt_id IS NULL)
    OR (status='confirmed' AND draft_invocation_id IS NULL AND confirmed_at IS NOT NULL AND confirmation_command_receipt_id IS NOT NULL)
    OR (status='superseded' AND draft_invocation_id IS NULL AND confirmed_at IS NULL AND confirmation_command_receipt_id IS NULL)
  )
);

CREATE TABLE plan_impact_assessment (
  assessment_id TEXT PRIMARY KEY,
  review_run_id TEXT NOT NULL REFERENCES manual_portfolio_review_run(review_run_id),
  review_item_id TEXT NOT NULL REFERENCES manual_portfolio_review_item(review_item_id),
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  review_rule_id TEXT NOT NULL,
  evidence_manifest_id TEXT NOT NULL REFERENCES manual_portfolio_review_manifest(manifest_id),
  research_refs_json TEXT NOT NULL,
  market_refs_json TEXT NOT NULL,
  industry_refs_json TEXT NOT NULL,
  sector_refs_json TEXT NOT NULL,
  impact_kind TEXT NOT NULL,
  materiality TEXT NOT NULL,
  uncertainties_json TEXT NOT NULL,
  what_changed TEXT NOT NULL,
  what_would_change_the_view TEXT NOT NULL,
  model_identity TEXT NOT NULL,
  policy_identity TEXT NOT NULL,
  prompt_identity TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_by TEXT NOT NULL CHECK(created_by IN ('agent','system')),
  created_at TEXT NOT NULL,
  schema_version TEXT NOT NULL CHECK(schema_version='PlanImpactAssessment@1')
);

CREATE TABLE plan_change_proposal (
  proposal_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision > 0),
  status TEXT NOT NULL CHECK(status IN ('open','accepted','rejected','superseded')),
  assessment_id TEXT NOT NULL REFERENCES plan_impact_assessment(assessment_id),
  base_plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  proposed_canonical_patch_json TEXT NOT NULL,
  proposed_diff_hash TEXT NOT NULL,
  created_by TEXT NOT NULL CHECK(created_by IN ('agent','system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  accepted_draft_id TEXT REFERENCES trade_plan_draft(draft_id),
  content_hash TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL CHECK(schema_version='PlanChangeProposal@1'),
  PRIMARY KEY(proposal_id,revision),
  CHECK((status='accepted' AND accepted_draft_id IS NOT NULL) OR (status<>'accepted' AND accepted_draft_id IS NULL))
);

CREATE TRIGGER manual_review_item_no_update BEFORE UPDATE ON manual_portfolio_review_item BEGIN SELECT RAISE(ABORT,'MANUAL_REVIEW_ITEM_IMMUTABLE'); END;
CREATE TRIGGER manual_review_item_no_delete BEFORE DELETE ON manual_portfolio_review_item BEGIN SELECT RAISE(ABORT,'MANUAL_REVIEW_ITEM_IMMUTABLE'); END;
CREATE TRIGGER manual_review_manifest_no_update BEFORE UPDATE ON manual_portfolio_review_manifest BEGIN SELECT RAISE(ABORT,'MANUAL_REVIEW_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER manual_review_manifest_no_delete BEFORE DELETE ON manual_portfolio_review_manifest BEGIN SELECT RAISE(ABORT,'MANUAL_REVIEW_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER decision_task_no_update BEFORE UPDATE ON decision_task BEGIN SELECT RAISE(ABORT,'DECISION_TASK_IMMUTABLE'); END;
CREATE TRIGGER decision_task_no_delete BEFORE DELETE ON decision_task BEGIN SELECT RAISE(ABORT,'DECISION_TASK_IMMUTABLE'); END;
CREATE TRIGGER decision_task_transition_no_update BEFORE UPDATE ON decision_task_transition BEGIN SELECT RAISE(ABORT,'DECISION_TASK_TRANSITION_IMMUTABLE'); END;
CREATE TRIGGER decision_task_transition_no_delete BEFORE DELETE ON decision_task_transition BEGIN SELECT RAISE(ABORT,'DECISION_TASK_TRANSITION_IMMUTABLE'); END;
CREATE TRIGGER action_log_entry_no_update BEFORE UPDATE ON action_log_entry BEGIN SELECT RAISE(ABORT,'ACTION_LOG_ENTRY_IMMUTABLE'); END;
CREATE TRIGGER action_log_entry_no_delete BEFORE DELETE ON action_log_entry BEGIN SELECT RAISE(ABORT,'ACTION_LOG_ENTRY_IMMUTABLE'); END;
CREATE TRIGGER execution_record_no_update BEFORE UPDATE ON execution_record BEGIN SELECT RAISE(ABORT,'EXECUTION_RECORD_IMMUTABLE'); END;
CREATE TRIGGER execution_record_no_delete BEFORE DELETE ON execution_record BEGIN SELECT RAISE(ABORT,'EXECUTION_RECORD_IMMUTABLE'); END;
CREATE TRIGGER discipline_review_no_update BEFORE UPDATE ON discipline_review_version BEGIN SELECT RAISE(ABORT,'DISCIPLINE_REVIEW_IMMUTABLE'); END;
CREATE TRIGGER discipline_review_no_delete BEFORE DELETE ON discipline_review_version BEGIN SELECT RAISE(ABORT,'DISCIPLINE_REVIEW_IMMUTABLE'); END;
CREATE TRIGGER plan_impact_no_update BEFORE UPDATE ON plan_impact_assessment BEGIN SELECT RAISE(ABORT,'PLAN_IMPACT_IMMUTABLE'); END;
CREATE TRIGGER plan_impact_no_delete BEFORE DELETE ON plan_impact_assessment BEGIN SELECT RAISE(ABORT,'PLAN_IMPACT_IMMUTABLE'); END;
CREATE TRIGGER plan_change_proposal_no_update BEFORE UPDATE ON plan_change_proposal BEGIN SELECT RAISE(ABORT,'PLAN_CHANGE_PROPOSAL_IMMUTABLE'); END;
CREATE TRIGGER plan_change_proposal_no_delete BEFORE DELETE ON plan_change_proposal BEGIN SELECT RAISE(ABORT,'PLAN_CHANGE_PROPOSAL_IMMUTABLE'); END;
