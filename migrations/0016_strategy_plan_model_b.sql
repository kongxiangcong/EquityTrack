DROP TRIGGER IF EXISTS trade_plan_version_no_update;
DROP TRIGGER IF EXISTS trade_plan_version_no_delete;
DROP TRIGGER IF EXISTS plan_rule_no_update;
DROP TRIGGER IF EXISTS plan_rule_no_delete;
DROP TRIGGER IF EXISTS plan_condition_no_update;
DROP TRIGGER IF EXISTS plan_condition_no_delete;
DROP TRIGGER IF EXISTS plan_reference_no_update;
DROP TRIGGER IF EXISTS plan_reference_no_delete;
DROP TRIGGER IF EXISTS plan_adjusted_evidence_no_update;
DROP TRIGGER IF EXISTS plan_adjusted_evidence_no_delete;
DROP TRIGGER IF EXISTS plan_risk_no_update;
DROP TRIGGER IF EXISTS plan_risk_no_delete;
DROP TRIGGER IF EXISTS plan_transition_no_update;
DROP TRIGGER IF EXISTS plan_transition_no_delete;
DROP TRIGGER IF EXISTS plan_evaluation_no_update;
DROP TRIGGER IF EXISTS plan_evaluation_no_delete;
DROP TRIGGER IF EXISTS plan_rule_evaluation_no_update;
DROP TRIGGER IF EXISTS plan_rule_evaluation_no_delete;
DROP TRIGGER IF EXISTS plan_rule_evaluation_no_late_insert;
DROP TRIGGER IF EXISTS plan_evaluation_evidence_no_update;
DROP TRIGGER IF EXISTS plan_evaluation_evidence_no_delete;
DROP TRIGGER IF EXISTS plan_evaluation_evidence_no_late_insert;
DROP INDEX IF EXISTS one_open_draft_per_existing_plan;
DROP INDEX IF EXISTS one_open_initial_draft_per_security;
DROP INDEX IF EXISTS one_active_version_per_plan;

ALTER TABLE plan_evaluation_evidence RENAME TO plan_evaluation_evidence_legacy_0016;
ALTER TABLE plan_rule_evaluation RENAME TO plan_rule_evaluation_legacy_0016;
ALTER TABLE plan_evaluation RENAME TO plan_evaluation_legacy_0016;
ALTER TABLE trade_plan RENAME TO trade_plan_legacy_0016;
ALTER TABLE trade_plan_draft RENAME TO trade_plan_draft_legacy_0016;
ALTER TABLE trade_plan_version RENAME TO trade_plan_version_legacy_0016;
ALTER TABLE plan_rule RENAME TO plan_rule_legacy_0016;
ALTER TABLE plan_rule_condition RENAME TO plan_rule_condition_legacy_0016;
ALTER TABLE plan_version_reference RENAME TO plan_version_reference_legacy_0016;
ALTER TABLE plan_adjusted_price_evidence RENAME TO plan_adjusted_price_evidence_legacy_0016;
ALTER TABLE plan_risk_constraint RENAME TO plan_risk_constraint_legacy_0016;
ALTER TABLE plan_activation RENAME TO plan_activation_legacy_0016;
ALTER TABLE trade_plan_transition RENAME TO trade_plan_transition_legacy_0016;
ALTER TABLE plan_account_snapshot_reference RENAME TO plan_account_snapshot_reference_legacy_0016;

CREATE TABLE investment_thesis_version (
  thesis_version_id TEXT PRIMARY KEY,
  thesis_id TEXT NOT NULL,
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  schema_version TEXT NOT NULL CHECK(schema_version='InvestmentThesisVersion@1'),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  as_of_at TEXT NOT NULL,
  timezone TEXT NOT NULL CHECK(timezone='Asia/Shanghai'),
  status TEXT NOT NULL CHECK(status IN ('draft','published','superseded')),
  horizon_json TEXT NOT NULL,
  claims_json TEXT NOT NULL,
  drivers_json TEXT NOT NULL,
  risks_json TEXT NOT NULL,
  invalidation_tests_json TEXT NOT NULL,
  evidence_manifest_id TEXT NOT NULL,
  research_run_ids_json TEXT NOT NULL,
  authoring_actor TEXT NOT NULL,
  model_identity TEXT NOT NULL,
  policy_identity TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  UNIQUE(thesis_id,version_no)
);

CREATE TABLE strategy_definition (
  strategy_id TEXT PRIMARY KEY,
  strategy_key TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  purpose TEXT NOT NULL,
  market_scope TEXT NOT NULL CHECK(market_scope='CN_A_SHARE'),
  authoring_mode TEXT NOT NULL CHECK(authoring_mode='built_in'),
  created_at TEXT NOT NULL
);

CREATE TABLE strategy_version (
  strategy_version_id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL REFERENCES strategy_definition(strategy_id),
  strategy_key TEXT NOT NULL,
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  schema_version TEXT NOT NULL CHECK(schema_version='StrategyVersion@1'),
  status TEXT NOT NULL CHECK(status IN ('active','retired')),
  sleeve_contract_json TEXT NOT NULL,
  rule_templates_json TEXT NOT NULL,
  conflict_policy_version TEXT NOT NULL CHECK(conflict_policy_version='trade-plan-conflict@1'),
  ast_version TEXT NOT NULL CHECK(ast_version='plan-rule-ast@2'),
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  publicly_selectable INTEGER NOT NULL CHECK(publicly_selectable IN (0,1)),
  UNIQUE(strategy_key,version_no),
  UNIQUE(strategy_version_id,strategy_key)
);

CREATE TABLE strategy_parameter_contract (
  strategy_version_id TEXT NOT NULL REFERENCES strategy_version(strategy_version_id),
  parameter_order INTEGER NOT NULL CHECK(parameter_order >= 0),
  parameter_key TEXT NOT NULL,
  value_type TEXT NOT NULL CHECK(value_type IN ('enum','string','integer','decimal','quantity','date','string_list','ast_condition','typed_quantity','review_rule_ids')),
  required INTEGER NOT NULL CHECK(required IN (0,1)),
  enum_values_json TEXT NOT NULL,
  minimum_value TEXT,
  maximum_value TEXT,
  item_type TEXT,
  unknown_policy TEXT NOT NULL CHECK(unknown_policy IN ('forbidden','manual_review_required')),
  content_hash TEXT NOT NULL,
  PRIMARY KEY(strategy_version_id,parameter_order),
  UNIQUE(strategy_version_id,parameter_key)
);

CREATE TABLE trade_plan_master (
  plan_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  strategy_version_id TEXT REFERENCES strategy_version(strategy_version_id),
  lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('inactive','active','ended','legacy_read_only')),
  transition_seq INTEGER NOT NULL CHECK(transition_seq >= 0),
  created_at TEXT NOT NULL,
  legacy_read_only INTEGER NOT NULL CHECK(legacy_read_only IN (0,1)),
  CHECK((legacy_read_only=1 AND strategy_version_id IS NULL AND lifecycle_status='legacy_read_only') OR (legacy_read_only=0 AND strategy_version_id IS NOT NULL)),
  UNIQUE(account_id,security_id,plan_id)
);
CREATE UNIQUE INDEX one_active_master_per_account_security
ON trade_plan_master(account_id,security_id)
WHERE lifecycle_status='active';

CREATE TABLE trade_plan_draft (
  draft_id TEXT PRIMARY KEY,
  plan_id TEXT REFERENCES trade_plan_master(plan_id),
  account_id TEXT NOT NULL REFERENCES account(account_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  strategy_version_id TEXT NOT NULL REFERENCES strategy_version(strategy_version_id),
  based_on_version_id TEXT,
  revision INTEGER NOT NULL CHECK(revision > 0),
  status TEXT NOT NULL CHECK(status IN ('open','rejected','confirmed')),
  parameters_json TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  decision_actor TEXT NOT NULL,
  interaction_channel TEXT NOT NULL,
  transport_actor TEXT NOT NULL
);
CREATE UNIQUE INDEX one_open_model_b_draft_per_plan
ON trade_plan_draft(plan_id) WHERE status='open' AND plan_id IS NOT NULL;
CREATE UNIQUE INDEX one_open_model_b_initial_draft_per_owner
ON trade_plan_draft(account_id,security_id) WHERE status='open' AND plan_id IS NULL;

CREATE TABLE user_approval_receipt (
  user_approval_receipt_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK(schema_version='UserApprovalReceipt@1'),
  challenge_id TEXT NOT NULL UNIQUE,
  plan_id TEXT NOT NULL REFERENCES trade_plan_master(plan_id),
  draft_id TEXT NOT NULL REFERENCES trade_plan_draft(draft_id),
  expected_revision INTEGER NOT NULL CHECK(expected_revision > 0),
  expected_content_hash TEXT NOT NULL,
  canonical_diff_hash TEXT NOT NULL,
  activation_intent TEXT NOT NULL CHECK(activation_intent IN ('confirm_and_enable','confirm_without_enable')),
  decision_actor TEXT NOT NULL,
  interaction_channel TEXT NOT NULL,
  transport_actor TEXT NOT NULL,
  command_invocation_id TEXT NOT NULL UNIQUE,
  approved_at TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE trade_plan_version (
  plan_version_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES trade_plan_master(plan_id),
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  supersedes_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  strategy_version_id TEXT REFERENCES strategy_version(strategy_version_id),
  investment_thesis_version_id TEXT REFERENCES investment_thesis_version(thesis_version_id),
  account_snapshot_version_id TEXT NOT NULL REFERENCES account_snapshot_version(account_snapshot_version_id),
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  horizon_start TEXT NOT NULL,
  horizon_end TEXT NOT NULL,
  review_by TEXT NOT NULL,
  risk_policy_version_id TEXT,
  metric_catalog_version TEXT NOT NULL,
  evaluator_policy_version TEXT NOT NULL,
  conflict_policy_version TEXT NOT NULL,
  ast_version TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  graph_seal_hash TEXT NOT NULL,
  graph_sealed INTEGER NOT NULL CHECK(graph_sealed IN (0,1)),
  confirmed_at TEXT NOT NULL,
  user_approval_receipt_id TEXT REFERENCES user_approval_receipt(user_approval_receipt_id),
  legacy_read_only INTEGER NOT NULL CHECK(legacy_read_only IN (0,1)),
  CHECK((legacy_read_only=1 AND strategy_version_id IS NULL AND user_approval_receipt_id IS NULL) OR (legacy_read_only=0 AND strategy_version_id IS NOT NULL AND user_approval_receipt_id IS NOT NULL AND ast_version='plan-rule-ast@2' AND conflict_policy_version='trade-plan-conflict@1')),
  UNIQUE(plan_id,version_no),
  UNIQUE(plan_id,content_hash)
);

CREATE TABLE grid_constraint (
  grid_constraint_id TEXT PRIMARY KEY,
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  lower_price TEXT NOT NULL,
  upper_price TEXT NOT NULL,
  level_count INTEGER NOT NULL CHECK(level_count BETWEEN 2 AND 100),
  quantity_per_level TEXT NOT NULL,
  total_quantity_budget TEXT NOT NULL,
  price_basis TEXT NOT NULL CHECK(price_basis IN ('unadjusted','adjusted')),
  trigger_mode TEXT NOT NULL CHECK(trigger_mode IN ('crosses_level','closes_at_or_beyond_level')),
  cooldown_trading_sessions INTEGER NOT NULL CHECK(cooldown_trading_sessions >= 0),
  lot_size TEXT NOT NULL,
  generated_levels_hash TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  UNIQUE(plan_version_id)
);

CREATE TABLE trade_plan_sleeve (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  sleeve_id TEXT NOT NULL,
  sleeve_kind TEXT NOT NULL CHECK(sleeve_kind IN ('core','grid','legacy_unsleeved')),
  quantity_budget_state TEXT NOT NULL CHECK(quantity_budget_state IN ('known','unknown','not_applicable')),
  quantity_budget_value TEXT,
  core_floor_state TEXT NOT NULL CHECK(core_floor_state IN ('known','unknown','not_applicable')),
  core_floor_value TEXT,
  max_notional_state TEXT NOT NULL CHECK(max_notional_state IN ('known','unknown','not_applicable')),
  max_notional_value TEXT,
  max_loss_state TEXT NOT NULL CHECK(max_loss_state IN ('known','unknown','not_applicable')),
  max_loss_value TEXT,
  grid_constraint_id TEXT REFERENCES grid_constraint(grid_constraint_id),
  content_hash TEXT NOT NULL,
  PRIMARY KEY(plan_version_id,sleeve_id),
  UNIQUE(plan_version_id,sleeve_kind),
  CHECK((sleeve_kind='grid' AND grid_constraint_id IS NOT NULL) OR (sleeve_kind<>'grid' AND grid_constraint_id IS NULL))
);

CREATE TABLE trade_plan_rule (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  rule_order INTEGER NOT NULL CHECK(rule_order >= 0),
  rule_id TEXT NOT NULL,
  rule_class TEXT NOT NULL CHECK(rule_class IN ('hard','review','legacy_read_only')),
  rule_kind TEXT NOT NULL,
  priority TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('master','core','grid','legacy_unsleeved')),
  sleeve_id TEXT,
  effect TEXT NOT NULL,
  applies_to TEXT NOT NULL CHECK(applies_to IN ('entry','increase','decrease','exit','plan')),
  candidate_intent_json TEXT,
  input_applicability_json TEXT NOT NULL,
  ast_version TEXT NOT NULL,
  condition_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  CHECK((scope='master' AND sleeve_id IS NULL) OR (scope<>'master' AND sleeve_id IS NOT NULL)),
  PRIMARY KEY(plan_version_id,rule_order),
  UNIQUE(plan_version_id,rule_id)
);

CREATE TABLE trade_plan_evidence_reference (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  ref_order INTEGER NOT NULL CHECK(ref_order >= 0),
  ref_type TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  resolution_status TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  PRIMARY KEY(plan_version_id,ref_order)
);

CREATE TABLE trade_plan_adjusted_price_evidence (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  rule_id TEXT NOT NULL,
  condition_path TEXT NOT NULL,
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  factor_set_id TEXT NOT NULL REFERENCES price_factor_set(factor_set_id),
  adjusted_price_decimal TEXT NOT NULL,
  canonical_unadjusted_price_decimal TEXT NOT NULL,
  factor_decimal TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  PRIMARY KEY(plan_version_id,rule_id,condition_path)
);

CREATE TABLE plan_evaluation (
  plan_evaluation_id TEXT PRIMARY KEY,
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  market_snapshot_id TEXT NOT NULL REFERENCES market_snapshot(market_snapshot_id),
  evaluator_version TEXT NOT NULL,
  evaluation_policy_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('completed','blocked')),
  resolution_outcome TEXT NOT NULL CHECK(resolution_outcome IN ('blocked','manual_review_required','decision_task','no_action')),
  resolution_reason_code TEXT NOT NULL,
  resolution_json TEXT NOT NULL,
  resolution_hash TEXT NOT NULL,
  completeness TEXT NOT NULL CHECK(completeness IN ('complete','partial')),
  rule_count INTEGER NOT NULL CHECK(rule_count >= 0),
  evaluation_hash TEXT NOT NULL UNIQUE,
  legacy_read_only INTEGER NOT NULL CHECK(legacy_read_only IN (0,1)),
  created_at TEXT NOT NULL,
  CHECK(
    (legacy_read_only=0 AND evaluator_version='plan-evaluator@2'
      AND evaluation_policy_version='trade-plan-conflict@1')
    OR legacy_read_only=1
  ),
  UNIQUE(evaluation_hash)
);

CREATE TABLE plan_rule_evaluation (
  plan_evaluation_id TEXT NOT NULL REFERENCES plan_evaluation(plan_evaluation_id),
  rule_order INTEGER NOT NULL CHECK(rule_order >= 0),
  rule_id TEXT NOT NULL,
  result TEXT NOT NULL CHECK(result IN ('triggered','not_triggered','unable_to_determine','blocked','not_applicable')),
  reason_code TEXT NOT NULL,
  evaluation_json TEXT NOT NULL,
  replay_hash TEXT NOT NULL,
  evidence_count INTEGER NOT NULL CHECK(evidence_count >= 0),
  PRIMARY KEY(plan_evaluation_id,rule_order)
);

CREATE TABLE plan_evaluation_evidence (
  plan_evaluation_id TEXT NOT NULL,
  rule_order INTEGER NOT NULL,
  evidence_order INTEGER NOT NULL,
  evidence_ref TEXT NOT NULL,
  PRIMARY KEY(plan_evaluation_id,rule_order,evidence_order),
  FOREIGN KEY(plan_evaluation_id,rule_order)
    REFERENCES plan_rule_evaluation(plan_evaluation_id,rule_order)
);

CREATE TABLE plan_confirmation_challenge (
  challenge_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK(schema_version='PlanConfirmationChallenge@1'),
  plan_id TEXT NOT NULL REFERENCES trade_plan_master(plan_id),
  draft_id TEXT NOT NULL REFERENCES trade_plan_draft(draft_id),
  expected_revision INTEGER NOT NULL CHECK(expected_revision > 0),
  expected_content_hash TEXT NOT NULL,
  canonical_diff_json TEXT NOT NULL,
  canonical_diff_hash TEXT NOT NULL,
  allowed_activation_intents_json TEXT NOT NULL,
  decision_actor TEXT NOT NULL,
  interaction_channel TEXT NOT NULL,
  transport_actor TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  consumed_by_receipt_id TEXT UNIQUE,
  content_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE plan_activation (
  activation_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES trade_plan_master(plan_id),
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  activated_event_id TEXT NOT NULL,
  activated_at TEXT NOT NULL,
  ended_event_id TEXT,
  ended_at TEXT,
  end_reason TEXT,
  user_approval_receipt_id TEXT REFERENCES user_approval_receipt(user_approval_receipt_id),
  command_invocation_id TEXT NOT NULL UNIQUE,
  CHECK((ended_at IS NULL AND ended_event_id IS NULL AND end_reason IS NULL) OR (ended_at IS NOT NULL AND ended_event_id IS NOT NULL AND end_reason IS NOT NULL))
);
CREATE UNIQUE INDEX one_open_activation_per_master
ON plan_activation(plan_id) WHERE ended_at IS NULL;

CREATE TABLE trade_plan_transition (
  transition_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES trade_plan_master(plan_id),
  transition_seq INTEGER NOT NULL CHECK(transition_seq > 0),
  from_status TEXT,
  to_status TEXT NOT NULL,
  plan_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  reason TEXT NOT NULL,
  command_invocation_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  UNIQUE(plan_id,transition_seq),
  UNIQUE(command_invocation_id)
);

CREATE TABLE plan_account_snapshot_reference (
  plan_version_id TEXT PRIMARY KEY REFERENCES trade_plan_version(plan_version_id),
  snapshot_type TEXT NOT NULL CHECK(snapshot_type='AccountSnapshotVersion'),
  snapshot_id TEXT NOT NULL REFERENCES account_snapshot_version(account_snapshot_version_id),
  account_id TEXT NOT NULL REFERENCES account(account_id),
  snapshot_as_of TEXT NOT NULL,
  reconciliation_status TEXT NOT NULL,
  context_json TEXT NOT NULL,
  context_hash TEXT NOT NULL,
  UNIQUE(plan_version_id,snapshot_type,snapshot_id)
);

CREATE TABLE strategy_plan_migration_manifest (
  migration_manifest_id TEXT PRIMARY KEY,
  source_plan_count INTEGER NOT NULL,
  source_version_count INTEGER NOT NULL,
  mapping_artifact_hash TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

INSERT INTO trade_plan_master
SELECT p.plan_id,r.account_id,p.security_id,m.strategy_version_id,
       CASE WHEN m.plan_id IS NULL THEN 'legacy_read_only' ELSE 'active' END,
       p.transition_seq + CASE WHEN m.plan_id IS NULL THEN 0 ELSE 1 END,
       p.created_at,CASE WHEN m.plan_id IS NULL THEN 1 ELSE 0 END
FROM trade_plan_legacy_0016 p
JOIN (
  SELECT v.plan_id,min(r.account_id) AS account_id
  FROM trade_plan_version_legacy_0016 v
  JOIN plan_account_snapshot_reference_legacy_0016 r USING(plan_version_id)
  GROUP BY v.plan_id
) r USING(plan_id)
LEFT JOIN migration_0016_legacy_mapping m USING(plan_id);

INSERT INTO trade_plan_draft
SELECT
  'trade_plan_draft_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  m.plan_id,r.account_id,p.security_id,m.strategy_version_id,NULL,1,'confirmed',
  '{}',v.content_json,qv.content_hash,v.confirmed_at,v.confirmed_at,
  meta.approved_by,'migration','system:migration-0016'
FROM migration_0016_legacy_mapping m
JOIN trade_plan_legacy_0016 p USING(plan_id)
JOIN trade_plan_version_legacy_0016 v USING(plan_id)
JOIN migration_0016_version_conversion qv USING(plan_version_id)
JOIN plan_account_snapshot_reference_legacy_0016 r USING(plan_version_id)
JOIN migration_0016_mapping_meta meta
GROUP BY m.plan_id;

INSERT INTO plan_confirmation_challenge
SELECT
  'plan_confirmation_challenge_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  'PlanConfirmationChallenge@1',m.plan_id,
  'trade_plan_draft_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  1,qv.content_hash,
  '{"migration":"0016","legacy_mapping":"explicit"}',
  canonical_sha256('0016-diff:' || m.plan_id || ':' || qv.content_hash),
  '["confirm_and_enable"]',
  meta.approved_by,'migration','system:migration-0016',
  meta.approved_at,meta.approved_at,meta.approved_at,
  'user_approval_receipt_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  canonical_sha256('0016-challenge:' || m.plan_id || ':' || qv.content_hash || ':' || meta.artifact_hash)
FROM migration_0016_legacy_mapping m
JOIN trade_plan_version_legacy_0016 v USING(plan_id)
JOIN migration_0016_version_conversion qv USING(plan_version_id)
JOIN migration_0016_mapping_meta meta
GROUP BY m.plan_id;

INSERT INTO user_approval_receipt
SELECT
  'user_approval_receipt_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  'UserApprovalReceipt@1',
  'plan_confirmation_challenge_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  m.plan_id,
  'trade_plan_draft_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  1,qv.content_hash,
  canonical_sha256('0016-diff:' || m.plan_id || ':' || qv.content_hash),
  'confirm_and_enable',
  meta.approved_by,'migration','system:migration-0016',
  'migration-0016:approve:' || m.plan_id,meta.approved_at,
  canonical_sha256('0016-receipt:' || m.plan_id || ':' || qv.content_hash || ':' || meta.artifact_hash)
FROM migration_0016_legacy_mapping m
JOIN trade_plan_version_legacy_0016 v USING(plan_id)
JOIN migration_0016_version_conversion qv USING(plan_version_id)
JOIN migration_0016_mapping_meta meta
GROUP BY m.plan_id;

INSERT INTO trade_plan_version
SELECT v.plan_version_id,v.plan_id,v.version_no,v.supersedes_version_id,
       m.strategy_version_id,NULL,r.snapshot_id,v.data_snapshot_id,
       v.horizon_start,v.horizon_end,
       v.review_by,v.market_gate_policy_version,v.metric_catalog_version,
       v.evaluator_policy_version,
       CASE WHEN m.plan_id IS NULL THEN 'legacy_read_only' ELSE 'trade-plan-conflict@1' END,
       CASE WHEN m.plan_id IS NULL THEN coalesce(c.ast_version,'plan-condition-ast@1') ELSE 'plan-rule-ast@2' END,
       v.content_json,coalesce(qv.content_hash,v.content_hash),
       coalesce(
         qv.graph_seal_hash,
         canonical_sha256(
           '0016-graph:' || v.plan_version_id || ':' || v.content_hash
           || ':legacy-read-only'
         )
       ),
       1,v.confirmed_at,
       CASE WHEN m.plan_id IS NULL THEN NULL
            ELSE 'user_approval_receipt_migration_' || substr(canonical_sha256(m.plan_id),1,24)
       END,
       CASE WHEN m.plan_id IS NULL THEN 1 ELSE 0 END
FROM trade_plan_version_legacy_0016 v
JOIN plan_account_snapshot_reference_legacy_0016 r USING(plan_version_id)
LEFT JOIN plan_rule_condition_legacy_0016 c USING(plan_version_id)
LEFT JOIN migration_0016_legacy_mapping m USING(plan_id)
LEFT JOIN migration_0016_mapping_meta meta
LEFT JOIN migration_0016_version_conversion qv USING(plan_version_id)
GROUP BY v.plan_version_id;

INSERT INTO trade_plan_sleeve
SELECT v.plan_version_id,'legacy_unsleeved','legacy_unsleeved',
       'unknown',NULL,'unknown',NULL,
       CASE WHEN k.max_planned_notional_decimal IS NULL THEN 'unknown' ELSE 'known' END,
       k.max_planned_notional_decimal,
       CASE WHEN k.max_planned_loss_decimal IS NULL THEN 'unknown' ELSE 'known' END,
       k.max_planned_loss_decimal,NULL,
       canonical_sha256('0016-legacy-sleeve:' || v.plan_version_id || ':' || v.content_hash)
FROM trade_plan_version_legacy_0016 v
LEFT JOIN plan_risk_constraint_legacy_0016 k USING(plan_version_id)
LEFT JOIN migration_0016_legacy_mapping m USING(plan_id)
WHERE m.plan_id IS NULL;

INSERT INTO grid_constraint
SELECT
  json_extract(s.value,'$.grid_constraint.grid_constraint_id'),
  v.plan_version_id,
  json_extract(s.value,'$.grid_constraint.lower_price'),
  json_extract(s.value,'$.grid_constraint.upper_price'),
  json_extract(s.value,'$.grid_constraint.level_count'),
  json_extract(s.value,'$.grid_constraint.quantity_per_level'),
  json_extract(s.value,'$.grid_constraint.total_quantity_budget'),
  json_extract(s.value,'$.grid_constraint.price_basis'),
  json_extract(s.value,'$.grid_constraint.trigger_mode'),
  json_extract(s.value,'$.grid_constraint.cooldown_trading_sessions'),
  json_extract(s.value,'$.grid_constraint._migration_lot_size'),
  json_extract(s.value,'$.grid_constraint._migration_levels_hash'),
  json_extract(s.value,'$.grid_constraint._migration_content_hash')
FROM migration_0016_legacy_mapping m
JOIN trade_plan_version_legacy_0016 v USING(plan_id)
JOIN json_each(m.sleeves_json) s
WHERE json_extract(s.value,'$.sleeve_kind')='grid';

INSERT INTO trade_plan_sleeve
SELECT
  v.plan_version_id,
  json_extract(s.value,'$.sleeve_id'),
  json_extract(s.value,'$.sleeve_kind'),
  json_extract(s.value,'$.quantity_budget_state'),
  json_extract(s.value,'$.quantity_budget_value'),
  json_extract(s.value,'$.core_floor_state'),
  json_extract(s.value,'$.core_floor_value'),
  json_extract(s.value,'$.max_notional_state'),
  json_extract(s.value,'$.max_notional_value'),
  json_extract(s.value,'$.max_loss_state'),
  json_extract(s.value,'$.max_loss_value'),
  json_extract(s.value,'$.grid_constraint.grid_constraint_id'),
  json_extract(s.value,'$._migration_content_hash')
FROM migration_0016_legacy_mapping m
JOIN trade_plan_version_legacy_0016 v USING(plan_id)
JOIN json_each(m.sleeves_json) s;

INSERT INTO trade_plan_rule
SELECT r.plan_version_id,r.rule_no,r.rule_id,
       CASE WHEN m.plan_id IS NULL THEN 'legacy_read_only' ELSE 'hard' END,
       r.rule_kind,
       'ordinary',
       CASE WHEN m.plan_id IS NULL THEN 'legacy_unsleeved'
            ELSE (
              SELECT json_extract(s.value,'$.sleeve_kind')
              FROM json_each(m.sleeves_json) s
              WHERE json_extract(s.value,'$.sleeve_id')
                    =json_extract(m.rule_scopes_json,'$.' || r.rule_id)
            ) END,
       CASE WHEN m.plan_id IS NULL THEN 'legacy_unsleeved'
            ELSE json_extract(m.rule_scopes_json,'$.' || r.rule_id) END,
       r.effect,r.applies_to,NULL,json_array(r.input_applicability),
       CASE WHEN m.plan_id IS NULL THEN c.ast_version ELSE 'plan-rule-ast@2' END,
       CASE WHEN m.plan_id IS NULL THEN c.condition_json ELSE q.condition_json END,
       CASE WHEN m.plan_id IS NULL
            THEN canonical_sha256('0016-legacy-rule:' || r.plan_version_id || ':' || r.rule_id || ':' || c.condition_hash)
            ELSE q.content_hash END
FROM plan_rule_legacy_0016 r
JOIN plan_rule_condition_legacy_0016 c USING(plan_version_id,rule_no)
JOIN trade_plan_version_legacy_0016 v USING(plan_version_id)
LEFT JOIN migration_0016_legacy_mapping m USING(plan_id)
LEFT JOIN migration_0016_rule_conversion q USING(plan_version_id,rule_no);

INSERT INTO trade_plan_evidence_reference
SELECT plan_version_id,ref_no,ref_type,ref_id,resolution_status,
       canonical_sha256('0016-legacy-ref:' || plan_version_id || ':' || ref_no || ':' || ref_type || ':' || ref_id)
FROM plan_version_reference_legacy_0016;

INSERT INTO trade_plan_adjusted_price_evidence
SELECT plan_version_id,rule_id,condition_path,data_snapshot_id,factor_set_id,
       adjusted_price_decimal,canonical_unadjusted_price_decimal,factor_decimal,
       algorithm_version,
       canonical_sha256('0016-legacy-adjusted:' || plan_version_id || ':' || rule_id || ':' || condition_path)
FROM plan_adjusted_price_evidence_legacy_0016;

INSERT INTO plan_evaluation
SELECT
  plan_evaluation_id,plan_version_id,market_snapshot_id,
  evaluator_version,evaluation_policy_version,status,
  CASE
    WHEN status='blocked' THEN 'blocked'
    WHEN outcome='not_triggered' THEN 'no_action'
    ELSE 'manual_review_required'
  END,
  CASE
    WHEN status='blocked' THEN 'LEGACY_EVALUATION_BLOCKED'
    WHEN outcome='not_triggered' THEN 'LEGACY_NO_TRIGGER'
    ELSE 'LEGACY_EVALUATION_REQUIRES_REVIEW'
  END,
  json_object(
    'legacy_outcome',outcome,
    'legacy_status',status,
    'migration','0016'
  ),
  canonical_sha256('0016-legacy-resolution:' || plan_evaluation_id),
  completeness,rule_count,
  canonical_sha256('0016-legacy-evaluation:' || plan_evaluation_id),
  1,created_at
FROM plan_evaluation_legacy_0016;

INSERT INTO plan_rule_evaluation
SELECT
  plan_evaluation_id,rule_order,rule_id,result,reason_code,
  json_object(
    'legacy_operands',json(operands_json),
    'legacy_effect',effect,
    'legacy_applies_to',applies_to,
    'legacy_observed_at',observed_at
  ),
  canonical_sha256(
    '0016-legacy-rule-evaluation:' || plan_evaluation_id || ':' || rule_order
  ),
  evidence_count
FROM plan_rule_evaluation_legacy_0016;

INSERT INTO plan_evaluation_evidence
SELECT * FROM plan_evaluation_evidence_legacy_0016;

INSERT INTO plan_account_snapshot_reference
SELECT * FROM plan_account_snapshot_reference_legacy_0016;

INSERT INTO plan_activation
SELECT a.activation_id,a.plan_id,a.plan_version_id,
       'legacy-activation:' || a.activation_id,a.started_at,
       CASE WHEN a.ended_at IS NULL THEN NULL ELSE 'legacy-end:' || a.activation_id END,
       a.ended_at,
       CASE WHEN a.ended_at IS NULL THEN NULL ELSE 'legacy_ended' END,
       CASE
         WHEN a.ended_at IS NULL AND m.plan_id IS NOT NULL
         THEN 'user_approval_receipt_migration_' || substr(canonical_sha256(m.plan_id),1,24)
         ELSE NULL
       END,
       a.activation_invocation_id
FROM plan_activation_legacy_0016 a
LEFT JOIN migration_0016_legacy_mapping m USING(plan_id);

INSERT INTO plan_activation
SELECT
  'plan_activation_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  m.plan_id,v.plan_version_id,
  'application_event_migration_activation_' || substr(canonical_sha256(m.plan_id),1,24),
  meta.approved_at,NULL,NULL,NULL,
  'user_approval_receipt_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  'migration-0016:activate:' || m.plan_id
FROM migration_0016_legacy_mapping m
JOIN trade_plan_version_legacy_0016 v USING(plan_id)
JOIN migration_0016_mapping_meta meta
WHERE NOT EXISTS(
  SELECT 1 FROM plan_activation_legacy_0016 a
  WHERE a.plan_id=m.plan_id AND a.ended_at IS NULL
)
GROUP BY m.plan_id;

INSERT INTO trade_plan_transition
SELECT
  'trade_plan_transition_' || substr(canonical_sha256('0016:' || plan_id || ':' || transition_seq),1,24),
  plan_id,transition_seq,from_status,'legacy_read_only',plan_version_id,reason,
  invocation_id,occurred_at,
  canonical_sha256('0016-transition:' || plan_id || ':' || transition_seq || ':' || coalesce(plan_version_id,''))
FROM trade_plan_transition_legacy_0016;

INSERT INTO trade_plan_transition
SELECT
  'trade_plan_transition_migration_' || substr(canonical_sha256(m.plan_id),1,24),
  m.plan_id,p.transition_seq+1,p.lifecycle_status,'active',v.plan_version_id,
  'explicit_legacy_mapping_activated',
  'migration-0016:activate:' || m.plan_id,meta.approved_at,
  canonical_sha256('0016-mapped-transition:' || m.plan_id || ':' || meta.artifact_hash)
FROM migration_0016_legacy_mapping m
JOIN trade_plan_legacy_0016 p USING(plan_id)
JOIN trade_plan_version_legacy_0016 v USING(plan_id)
JOIN migration_0016_mapping_meta meta
GROUP BY m.plan_id;

INSERT INTO strategy_plan_migration_manifest
SELECT
  'strategy_plan_migration_manifest_0016',
  (SELECT count(*) FROM trade_plan_legacy_0016),
  (SELECT count(*) FROM trade_plan_version_legacy_0016),
  (SELECT artifact_hash FROM migration_0016_mapping_meta),
  canonical_sha256(
    '0016:' || (SELECT count(*) FROM trade_plan_legacy_0016) || ':'
    || (SELECT count(*) FROM trade_plan_version_legacy_0016) || ':'
    || (SELECT artifact_hash FROM migration_0016_mapping_meta)
  ),
  '2026-07-27T00:00:00+08:00';

DROP TABLE plan_account_snapshot_reference_legacy_0016;
DROP TABLE plan_evaluation_evidence_legacy_0016;
DROP TABLE plan_rule_evaluation_legacy_0016;
DROP TABLE plan_evaluation_legacy_0016;
DROP TABLE trade_plan_transition_legacy_0016;
DROP TABLE plan_activation_legacy_0016;
DROP TABLE plan_risk_constraint_legacy_0016;
DROP TABLE plan_adjusted_price_evidence_legacy_0016;
DROP TABLE plan_version_reference_legacy_0016;
DROP TABLE plan_rule_condition_legacy_0016;
DROP TABLE plan_rule_legacy_0016;
DROP TABLE trade_plan_draft_legacy_0016;
DROP TABLE trade_plan_version_legacy_0016;
DROP TABLE trade_plan_legacy_0016;
DROP TABLE migration_0016_legacy_mapping;
DROP TABLE migration_0016_mapping_meta;
DROP TABLE migration_0016_rule_conversion;
DROP TABLE migration_0016_version_conversion;

CREATE TRIGGER investment_thesis_version_no_update BEFORE UPDATE ON investment_thesis_version
BEGIN SELECT RAISE(ABORT,'INVESTMENT_THESIS_VERSION_IMMUTABLE'); END;
CREATE TRIGGER investment_thesis_version_no_delete BEFORE DELETE ON investment_thesis_version
BEGIN SELECT RAISE(ABORT,'INVESTMENT_THESIS_VERSION_IMMUTABLE'); END;
CREATE TRIGGER strategy_definition_no_update BEFORE UPDATE ON strategy_definition
BEGIN SELECT RAISE(ABORT,'STRATEGY_REGISTRY_IMMUTABLE'); END;
CREATE TRIGGER strategy_definition_no_delete BEFORE DELETE ON strategy_definition
BEGIN SELECT RAISE(ABORT,'STRATEGY_REGISTRY_IMMUTABLE'); END;
CREATE TRIGGER strategy_version_no_update BEFORE UPDATE ON strategy_version
BEGIN SELECT RAISE(ABORT,'STRATEGY_REGISTRY_IMMUTABLE'); END;
CREATE TRIGGER strategy_version_no_delete BEFORE DELETE ON strategy_version
BEGIN SELECT RAISE(ABORT,'STRATEGY_REGISTRY_IMMUTABLE'); END;
CREATE TRIGGER strategy_parameter_contract_no_update BEFORE UPDATE ON strategy_parameter_contract
BEGIN SELECT RAISE(ABORT,'STRATEGY_REGISTRY_IMMUTABLE'); END;
CREATE TRIGGER strategy_parameter_contract_no_delete BEFORE DELETE ON strategy_parameter_contract
BEGIN SELECT RAISE(ABORT,'STRATEGY_REGISTRY_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_draft_closed_no_update BEFORE UPDATE ON trade_plan_draft
WHEN OLD.status<>'open'
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_DRAFT_CLOSED'); END;
CREATE TRIGGER trade_plan_draft_closed_no_delete BEFORE DELETE ON trade_plan_draft
WHEN OLD.status<>'open'
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_DRAFT_CLOSED'); END;
CREATE TRIGGER trade_plan_version_sealed_update BEFORE UPDATE ON trade_plan_version
WHEN OLD.graph_sealed=1 OR NEW.graph_sealed<>1 OR NOT (
  OLD.plan_version_id IS NEW.plan_version_id
  AND OLD.plan_id IS NEW.plan_id
  AND OLD.version_no IS NEW.version_no
  AND OLD.supersedes_version_id IS NEW.supersedes_version_id
  AND OLD.strategy_version_id IS NEW.strategy_version_id
  AND OLD.investment_thesis_version_id IS NEW.investment_thesis_version_id
  AND OLD.account_snapshot_version_id IS NEW.account_snapshot_version_id
  AND OLD.data_snapshot_id IS NEW.data_snapshot_id
  AND OLD.horizon_start IS NEW.horizon_start
  AND OLD.horizon_end IS NEW.horizon_end
  AND OLD.review_by IS NEW.review_by
  AND OLD.risk_policy_version_id IS NEW.risk_policy_version_id
  AND OLD.metric_catalog_version IS NEW.metric_catalog_version
  AND OLD.evaluator_policy_version IS NEW.evaluator_policy_version
  AND OLD.conflict_policy_version IS NEW.conflict_policy_version
  AND OLD.ast_version IS NEW.ast_version
  AND OLD.content_json IS NEW.content_json
  AND OLD.content_hash IS NEW.content_hash
  AND OLD.graph_seal_hash IS NEW.graph_seal_hash
  AND OLD.confirmed_at IS NEW.confirmed_at
  AND OLD.user_approval_receipt_id IS NEW.user_approval_receipt_id
  AND OLD.legacy_read_only IS NEW.legacy_read_only
)
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_version_no_delete BEFORE DELETE ON trade_plan_version
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_sleeve_no_late_insert BEFORE INSERT ON trade_plan_sleeve
WHEN (SELECT graph_sealed FROM trade_plan_version WHERE plan_version_id=NEW.plan_version_id)=1
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_sleeve_no_update BEFORE UPDATE ON trade_plan_sleeve
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_sleeve_no_delete BEFORE DELETE ON trade_plan_sleeve
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER grid_constraint_no_late_insert BEFORE INSERT ON grid_constraint
WHEN (SELECT graph_sealed FROM trade_plan_version WHERE plan_version_id=NEW.plan_version_id)=1
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER grid_constraint_no_update BEFORE UPDATE ON grid_constraint
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER grid_constraint_no_delete BEFORE DELETE ON grid_constraint
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_rule_no_late_insert BEFORE INSERT ON trade_plan_rule
WHEN (SELECT graph_sealed FROM trade_plan_version WHERE plan_version_id=NEW.plan_version_id)=1
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_rule_no_update BEFORE UPDATE ON trade_plan_rule
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_rule_no_delete BEFORE DELETE ON trade_plan_rule
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_evidence_no_late_insert BEFORE INSERT ON trade_plan_evidence_reference
WHEN (SELECT graph_sealed FROM trade_plan_version WHERE plan_version_id=NEW.plan_version_id)=1
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_evidence_no_update BEFORE UPDATE ON trade_plan_evidence_reference
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_evidence_no_delete BEFORE DELETE ON trade_plan_evidence_reference
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_adjusted_no_late_insert BEFORE INSERT ON trade_plan_adjusted_price_evidence
WHEN (SELECT graph_sealed FROM trade_plan_version WHERE plan_version_id=NEW.plan_version_id)=1
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_adjusted_no_update BEFORE UPDATE ON trade_plan_adjusted_price_evidence
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_adjusted_no_delete BEFORE DELETE ON trade_plan_adjusted_price_evidence
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_no_update BEFORE UPDATE ON plan_evaluation
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_no_delete BEFORE DELETE ON plan_evaluation
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_evaluation_no_update BEFORE UPDATE ON plan_rule_evaluation
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_evaluation_no_delete BEFORE DELETE ON plan_rule_evaluation
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_evaluation_no_late_insert BEFORE INSERT ON plan_rule_evaluation
WHEN (SELECT count(*) FROM plan_rule_evaluation WHERE plan_evaluation_id=NEW.plan_evaluation_id)
  >= (SELECT rule_count FROM plan_evaluation WHERE plan_evaluation_id=NEW.plan_evaluation_id)
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_evidence_no_update BEFORE UPDATE ON plan_evaluation_evidence
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_evidence_no_delete BEFORE DELETE ON plan_evaluation_evidence
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_evidence_no_late_insert BEFORE INSERT ON plan_evaluation_evidence
WHEN (SELECT count(*) FROM plan_evaluation_evidence
      WHERE plan_evaluation_id=NEW.plan_evaluation_id AND rule_order=NEW.rule_order)
  >= (SELECT evidence_count FROM plan_rule_evaluation
      WHERE plan_evaluation_id=NEW.plan_evaluation_id AND rule_order=NEW.rule_order)
BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_confirmation_challenge_no_delete BEFORE DELETE ON plan_confirmation_challenge
BEGIN SELECT RAISE(ABORT,'PLAN_CONFIRMATION_CHALLENGE_IMMUTABLE'); END;
CREATE TRIGGER user_approval_receipt_no_update BEFORE UPDATE ON user_approval_receipt
BEGIN SELECT RAISE(ABORT,'USER_APPROVAL_RECEIPT_IMMUTABLE'); END;
CREATE TRIGGER user_approval_receipt_no_delete BEFORE DELETE ON user_approval_receipt
BEGIN SELECT RAISE(ABORT,'USER_APPROVAL_RECEIPT_IMMUTABLE'); END;
CREATE TRIGGER plan_activation_no_update BEFORE UPDATE ON plan_activation
WHEN NOT (
  OLD.ended_at IS NULL AND NEW.ended_at IS NOT NULL
  AND OLD.activation_id=NEW.activation_id
  AND OLD.plan_id=NEW.plan_id
  AND OLD.plan_version_id=NEW.plan_version_id
  AND OLD.activated_event_id=NEW.activated_event_id
  AND OLD.activated_at=NEW.activated_at
  AND OLD.user_approval_receipt_id IS NEW.user_approval_receipt_id
  AND OLD.command_invocation_id=NEW.command_invocation_id
)
BEGIN SELECT RAISE(ABORT,'PLAN_ACTIVATION_IMMUTABLE'); END;
CREATE TRIGGER plan_activation_no_delete BEFORE DELETE ON plan_activation
BEGIN SELECT RAISE(ABORT,'PLAN_ACTIVATION_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_transition_no_update BEFORE UPDATE ON trade_plan_transition
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_TRANSITION_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_transition_no_delete BEFORE DELETE ON trade_plan_transition
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_TRANSITION_IMMUTABLE'); END;
CREATE TRIGGER strategy_plan_manifest_no_update BEFORE UPDATE ON strategy_plan_migration_manifest
BEGIN SELECT RAISE(ABORT,'STRATEGY_PLAN_MIGRATION_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER strategy_plan_manifest_no_delete BEFORE DELETE ON strategy_plan_migration_manifest
BEGIN SELECT RAISE(ABORT,'STRATEGY_PLAN_MIGRATION_MANIFEST_IMMUTABLE'); END;
