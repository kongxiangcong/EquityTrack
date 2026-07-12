CREATE TABLE trade_plan (
  plan_id TEXT PRIMARY KEY,
  security_id TEXT NOT NULL REFERENCES security(security_id),
  lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('inactive','active','ended')),
  transition_seq INTEGER NOT NULL CHECK(transition_seq >= 0),
  created_at TEXT NOT NULL
);
CREATE TABLE trade_plan_draft (
  draft_id TEXT PRIMARY KEY,
  plan_id TEXT REFERENCES trade_plan(plan_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  based_on_version_id TEXT,
  revision INTEGER NOT NULL CHECK(revision > 0),
  status TEXT NOT NULL CHECK(status IN ('open','discarded','confirmed')),
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_open_draft_per_existing_plan ON trade_plan_draft(plan_id) WHERE status='open' AND plan_id IS NOT NULL;
CREATE UNIQUE INDEX one_open_initial_draft_per_security ON trade_plan_draft(security_id) WHERE status='open' AND plan_id IS NULL;
CREATE TABLE trade_plan_version (
  plan_version_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES trade_plan(plan_id),
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  supersedes_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  based_on_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  horizon_start TEXT NOT NULL,
  horizon_end TEXT NOT NULL,
  review_by TEXT NOT NULL,
  market_gate_policy_version TEXT NOT NULL,
  metric_catalog_version TEXT NOT NULL,
  evaluator_policy_version TEXT NOT NULL,
  user_input_source TEXT NOT NULL CHECK(user_input_source='user_fixture_input'),
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  confirmed_at TEXT NOT NULL,
  confirmation_invocation_id TEXT NOT NULL,
  UNIQUE(plan_id,version_no),
  UNIQUE(plan_id,content_hash)
);
CREATE TABLE plan_rule (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  rule_no INTEGER NOT NULL CHECK(rule_no >= 0),
  rule_id TEXT NOT NULL,
  rule_kind TEXT NOT NULL,
  effect TEXT NOT NULL,
  applies_to TEXT NOT NULL,
  input_applicability TEXT NOT NULL CHECK(input_applicability IN ('applicable','not_applicable','unknown')),
  PRIMARY KEY(plan_version_id,rule_no),
  UNIQUE(plan_version_id,rule_id)
);
CREATE TABLE plan_rule_condition (
  plan_version_id TEXT NOT NULL,
  rule_no INTEGER NOT NULL,
  ast_version TEXT NOT NULL,
  condition_json TEXT NOT NULL,
  condition_hash TEXT NOT NULL,
  PRIMARY KEY(plan_version_id,rule_no),
  FOREIGN KEY(plan_version_id,rule_no) REFERENCES plan_rule(plan_version_id,rule_no)
);
CREATE TABLE plan_version_reference (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  ref_no INTEGER NOT NULL,
  ref_type TEXT NOT NULL CHECK(ref_type IN ('ResearchRun','Evidence')),
  ref_id TEXT NOT NULL,
  resolution_status TEXT NOT NULL CHECK(resolution_status IN ('resolved','unresolved_external')),
  PRIMARY KEY(plan_version_id,ref_no)
);
CREATE TABLE price_factor_set (
  factor_set_id TEXT PRIMARY KEY,
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  source_ref TEXT NOT NULL,
  mapping_status TEXT NOT NULL CHECK(mapping_status IN ('unique_deterministic','conflicted','unavailable')),
  algorithm_version TEXT NOT NULL
);
CREATE TABLE plan_adjusted_price_evidence (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  rule_id TEXT NOT NULL,
  condition_path TEXT NOT NULL,
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  factor_set_id TEXT NOT NULL,
  adjusted_price_decimal TEXT NOT NULL,
  canonical_unadjusted_price_decimal TEXT NOT NULL,
  factor_decimal TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  PRIMARY KEY(plan_version_id,rule_id,condition_path),
  FOREIGN KEY(factor_set_id) REFERENCES price_factor_set(factor_set_id)
);
CREATE TABLE plan_risk_constraint (
  plan_version_id TEXT PRIMARY KEY REFERENCES trade_plan_version(plan_version_id),
  currency TEXT NOT NULL,
  max_planned_notional_decimal TEXT NOT NULL,
  max_planned_loss_decimal TEXT NOT NULL,
  portfolio_feasibility TEXT NOT NULL CHECK(portfolio_feasibility IN ('not_applicable','verified'))
);
CREATE TABLE plan_activation (
  activation_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES trade_plan(plan_id),
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  started_at TEXT NOT NULL,
  ended_at TEXT,
  activation_invocation_id TEXT NOT NULL
);
CREATE UNIQUE INDEX one_active_version_per_plan ON plan_activation(plan_id) WHERE ended_at IS NULL;
CREATE TABLE trade_plan_transition (
  plan_id TEXT NOT NULL REFERENCES trade_plan(plan_id),
  transition_seq INTEGER NOT NULL CHECK(transition_seq > 0),
  from_status TEXT,
  to_status TEXT NOT NULL,
  plan_version_id TEXT REFERENCES trade_plan_version(plan_version_id),
  reason TEXT NOT NULL,
  invocation_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  PRIMARY KEY(plan_id,transition_seq)
);
CREATE TRIGGER trade_plan_version_no_update BEFORE UPDATE ON trade_plan_version BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER trade_plan_version_no_delete BEFORE DELETE ON trade_plan_version BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_no_update BEFORE UPDATE ON plan_rule BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_no_delete BEFORE DELETE ON plan_rule BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_condition_no_update BEFORE UPDATE ON plan_rule_condition BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_condition_no_delete BEFORE DELETE ON plan_rule_condition BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_reference_no_update BEFORE UPDATE ON plan_version_reference BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_reference_no_delete BEFORE DELETE ON plan_version_reference BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER price_factor_set_no_update BEFORE UPDATE ON price_factor_set BEGIN SELECT RAISE(ABORT,'PRICE_FACTOR_SET_IMMUTABLE'); END;
CREATE TRIGGER price_factor_set_no_delete BEFORE DELETE ON price_factor_set BEGIN SELECT RAISE(ABORT,'PRICE_FACTOR_SET_IMMUTABLE'); END;
CREATE TRIGGER plan_adjusted_evidence_no_update BEFORE UPDATE ON plan_adjusted_price_evidence BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_adjusted_evidence_no_delete BEFORE DELETE ON plan_adjusted_price_evidence BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_risk_no_update BEFORE UPDATE ON plan_risk_constraint BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_risk_no_delete BEFORE DELETE ON plan_risk_constraint BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_VERSION_IMMUTABLE'); END;
CREATE TRIGGER plan_transition_no_update BEFORE UPDATE ON trade_plan_transition BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_TRANSITION_IMMUTABLE'); END;
CREATE TRIGGER plan_transition_no_delete BEFORE DELETE ON trade_plan_transition BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_TRANSITION_IMMUTABLE'); END;
