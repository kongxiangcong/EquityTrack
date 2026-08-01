DROP TRIGGER manual_review_item_no_update;
DROP TRIGGER manual_review_item_no_delete;
DROP INDEX one_running_manual_review_per_account;

ALTER TABLE manual_portfolio_review_item
RENAME TO manual_portfolio_review_item_v1;

ALTER TABLE manual_portfolio_review_run
RENAME TO manual_portfolio_review_run_v1;

CREATE TABLE manual_portfolio_review_run (
  review_run_id TEXT PRIMARY KEY,
  workflow_run_id TEXT NOT NULL UNIQUE REFERENCES workflow_run(workflow_run_id),
  invocation_id TEXT NOT NULL UNIQUE,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  requested_at TEXT NOT NULL,
  session_selection TEXT NOT NULL
    CHECK(session_selection='latest_proven_complete_session'),
  selected_complete_session TEXT NOT NULL,
  timezone TEXT NOT NULL CHECK(timezone='Asia/Shanghai'),
  window_start_exclusive TEXT NOT NULL,
  window_end_inclusive TEXT NOT NULL,
  prior_successful_review_run_id TEXT
    REFERENCES manual_portfolio_review_run(review_run_id),
  status TEXT NOT NULL
    CHECK(status IN (
      'queued','running','succeeded','succeeded_with_limits','failed'
    )),
  input_fingerprint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  schema_version TEXT NOT NULL
    CHECK(schema_version='ManualPortfolioReviewRun@2'),
  CHECK(window_start_exclusive < window_end_inclusive),
  CHECK(
    (status IN ('queued','running') AND completed_at IS NULL)
    OR (
      status IN ('succeeded','succeeded_with_limits','failed')
      AND completed_at IS NOT NULL
    )
  )
);

CREATE UNIQUE INDEX one_running_manual_review_per_account
ON manual_portfolio_review_run(account_id)
WHERE status IN ('queued','running');

INSERT INTO manual_portfolio_review_run(
  review_run_id,
  workflow_run_id,
  invocation_id,
  account_id,
  requested_at,
  session_selection,
  selected_complete_session,
  timezone,
  window_start_exclusive,
  window_end_inclusive,
  prior_successful_review_run_id,
  status,
  input_fingerprint,
  created_at,
  completed_at,
  schema_version
)
SELECT
  review_run_id,
  workflow_run_id,
  invocation_id,
  account_id,
  requested_at,
  'latest_proven_complete_session',
  selected_complete_session,
  timezone,
  window_start_exclusive,
  window_end_inclusive,
  prior_successful_review_run_id,
  status,
  input_fingerprint,
  created_at,
  completed_at,
  'ManualPortfolioReviewRun@2'
FROM manual_portfolio_review_run_v1;

CREATE TABLE manual_portfolio_review_item (
  review_item_id TEXT PRIMARY KEY,
  review_run_id TEXT NOT NULL
    REFERENCES manual_portfolio_review_run(review_run_id),
  account_id TEXT NOT NULL REFERENCES account(account_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  universe_member_identity TEXT NOT NULL,
  universe_roles_json TEXT NOT NULL
    CHECK(
      universe_roles_json IN (
        '["holding"]',
        '["watchlist"]',
        '["holding","watchlist"]'
      )
    ),
  account_snapshot_version_id TEXT NOT NULL
    REFERENCES account_snapshot_version(account_snapshot_version_id),
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
  outcome TEXT NOT NULL
    CHECK(outcome IN (
      'NO_CHANGE','MONITOR','REVIEW_REQUIRED','DRAFT_UPDATE_PROPOSED'
    )),
  material_changes_json TEXT NOT NULL,
  unable_reasons_json TEXT NOT NULL,
  blocked_reasons_json TEXT NOT NULL,
  decision_task_ids_json TEXT NOT NULL,
  plan_impact_assessment_ids_json TEXT NOT NULL,
  plan_change_proposal_ids_json TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  schema_version TEXT NOT NULL CHECK(schema_version='SecurityReviewItem@2'),
  UNIQUE(review_run_id,security_id)
);

INSERT INTO manual_portfolio_review_item(
  review_item_id,
  review_run_id,
  account_id,
  security_id,
  universe_member_identity,
  universe_roles_json,
  account_snapshot_version_id,
  account_snapshot_hash,
  estimated_state_hash,
  active_plan_id,
  plan_version_id,
  plan_evaluation_id,
  evaluation_reason_code,
  strategy_version_id,
  sleeve_graph_json,
  data_snapshot_ids_json,
  research_run_ids_json,
  evidence_ids_json,
  market_snapshot_ids_json,
  hard_rule_evaluations_json,
  review_rule_routing_json,
  conflict_resolution_json,
  outcome,
  material_changes_json,
  unable_reasons_json,
  blocked_reasons_json,
  decision_task_ids_json,
  plan_impact_assessment_ids_json,
  plan_change_proposal_ids_json,
  content_hash,
  created_at,
  schema_version
)
SELECT
  review_item_id,
  review_run_id,
  account_id,
  security_id,
  position_identity,
  '["holding"]',
  account_snapshot_version_id,
  account_snapshot_hash,
  estimated_state_hash,
  active_plan_id,
  plan_version_id,
  plan_evaluation_id,
  evaluation_reason_code,
  strategy_version_id,
  sleeve_graph_json,
  data_snapshot_ids_json,
  research_run_ids_json,
  evidence_ids_json,
  market_snapshot_ids_json,
  hard_rule_evaluations_json,
  review_rule_routing_json,
  conflict_resolution_json,
  outcome,
  material_changes_json,
  unable_reasons_json,
  blocked_reasons_json,
  decision_task_ids_json,
  plan_impact_assessment_ids_json,
  plan_change_proposal_ids_json,
  content_hash,
  created_at,
  'SecurityReviewItem@2'
FROM manual_portfolio_review_item_v1;

DROP TABLE manual_portfolio_review_item_v1;
DROP TABLE manual_portfolio_review_run_v1;
