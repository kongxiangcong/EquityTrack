CREATE TABLE data_snapshot_universe_ref (
  data_snapshot_id TEXT PRIMARY KEY REFERENCES data_snapshot(data_snapshot_id),
  market_universe_version_id TEXT NOT NULL REFERENCES market_universe_version(market_universe_version_id),
  market_scope_id TEXT NOT NULL
);
CREATE TABLE security_market_constraint (
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  session_date TEXT NOT NULL,
  suspended INTEGER NOT NULL CHECK(suspended IN (0,1)),
  limit_up_decimal TEXT NOT NULL,
  limit_down_decimal TEXT NOT NULL,
  corporate_action_conflict INTEGER NOT NULL CHECK(corporate_action_conflict IN (0,1)),
  evidence_refs_json TEXT NOT NULL,
  PRIMARY KEY(data_snapshot_id,security_id,session_date)
);
CREATE TABLE market_snapshot (
  market_snapshot_id TEXT PRIMARY KEY,
  security_id TEXT NOT NULL REFERENCES security(security_id),
  market_scope_id TEXT NOT NULL,
  requested_date TEXT NOT NULL,
  effective_session_date TEXT NOT NULL,
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  market_universe_version_id TEXT NOT NULL REFERENCES market_universe_version(market_universe_version_id),
  market_model_version TEXT NOT NULL,
  freshness_policy_version TEXT NOT NULL,
  code_identity_hash TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('complete','limited','blocked')),
  component_count INTEGER NOT NULL CHECK(component_count > 0),
  created_at TEXT NOT NULL
);
CREATE TABLE market_snapshot_component (
  market_snapshot_id TEXT NOT NULL REFERENCES market_snapshot(market_snapshot_id),
  component_order INTEGER NOT NULL,
  component_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('complete','limited','blocked','unsupported')),
  classification TEXT,
  values_json TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  coverage_expected INTEGER NOT NULL,
  coverage_eligible INTEGER NOT NULL,
  coverage_excluded INTEGER NOT NULL,
  coverage_missing INTEGER NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  PRIMARY KEY(market_snapshot_id,component_order),
  UNIQUE(market_snapshot_id,component_id)
);
CREATE TABLE plan_evaluation (
  plan_evaluation_id TEXT PRIMARY KEY,
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  market_snapshot_id TEXT NOT NULL REFERENCES market_snapshot(market_snapshot_id),
  evaluator_version TEXT NOT NULL,
  evaluation_policy_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('completed','blocked')),
  outcome TEXT CHECK(outcome IN ('triggered','not_triggered','unable_to_determine')),
  completeness TEXT NOT NULL CHECK(completeness IN ('complete','partial')),
  rule_count INTEGER NOT NULL CHECK(rule_count > 0),
  created_at TEXT NOT NULL,
  UNIQUE(plan_version_id,market_snapshot_id,evaluator_version,evaluation_policy_version)
);
CREATE TABLE plan_rule_evaluation (
  plan_evaluation_id TEXT NOT NULL REFERENCES plan_evaluation(plan_evaluation_id),
  rule_order INTEGER NOT NULL,
  rule_id TEXT NOT NULL,
  result TEXT NOT NULL CHECK(result IN ('triggered','not_triggered','unable_to_determine','blocked','not_applicable')),
  reason_code TEXT NOT NULL,
  operands_json TEXT NOT NULL,
  effect TEXT NOT NULL,
  applies_to TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  evidence_count INTEGER NOT NULL CHECK(evidence_count >= 0),
  PRIMARY KEY(plan_evaluation_id,rule_order)
);
CREATE TABLE plan_evaluation_evidence (
  plan_evaluation_id TEXT NOT NULL,
  rule_order INTEGER NOT NULL,
  evidence_order INTEGER NOT NULL,
  evidence_ref TEXT NOT NULL,
  PRIMARY KEY(plan_evaluation_id,rule_order,evidence_order),
  FOREIGN KEY(plan_evaluation_id,rule_order) REFERENCES plan_rule_evaluation(plan_evaluation_id,rule_order)
);
CREATE TRIGGER market_snapshot_no_update BEFORE UPDATE ON market_snapshot BEGIN SELECT RAISE(ABORT,'MARKET_SNAPSHOT_IMMUTABLE'); END;
CREATE TRIGGER market_snapshot_no_delete BEFORE DELETE ON market_snapshot BEGIN SELECT RAISE(ABORT,'MARKET_SNAPSHOT_IMMUTABLE'); END;
CREATE TRIGGER market_component_no_update BEFORE UPDATE ON market_snapshot_component BEGIN SELECT RAISE(ABORT,'MARKET_SNAPSHOT_IMMUTABLE'); END;
CREATE TRIGGER market_component_no_delete BEFORE DELETE ON market_snapshot_component BEGIN SELECT RAISE(ABORT,'MARKET_SNAPSHOT_IMMUTABLE'); END;
CREATE TRIGGER market_component_no_late_insert BEFORE INSERT ON market_snapshot_component WHEN (SELECT count(*) FROM market_snapshot_component WHERE market_snapshot_id=NEW.market_snapshot_id) >= (SELECT component_count FROM market_snapshot WHERE market_snapshot_id=NEW.market_snapshot_id) BEGIN SELECT RAISE(ABORT,'MARKET_SNAPSHOT_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_no_update BEFORE UPDATE ON plan_evaluation BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_no_delete BEFORE DELETE ON plan_evaluation BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_evaluation_no_update BEFORE UPDATE ON plan_rule_evaluation BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_evaluation_no_delete BEFORE DELETE ON plan_rule_evaluation BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_rule_evaluation_no_late_insert BEFORE INSERT ON plan_rule_evaluation WHEN (SELECT count(*) FROM plan_rule_evaluation WHERE plan_evaluation_id=NEW.plan_evaluation_id) >= (SELECT rule_count FROM plan_evaluation WHERE plan_evaluation_id=NEW.plan_evaluation_id) BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_evidence_no_update BEFORE UPDATE ON plan_evaluation_evidence BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_evidence_no_delete BEFORE DELETE ON plan_evaluation_evidence BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER plan_evaluation_evidence_no_late_insert BEFORE INSERT ON plan_evaluation_evidence WHEN (SELECT count(*) FROM plan_evaluation_evidence WHERE plan_evaluation_id=NEW.plan_evaluation_id AND rule_order=NEW.rule_order) >= (SELECT evidence_count FROM plan_rule_evaluation WHERE plan_evaluation_id=NEW.plan_evaluation_id AND rule_order=NEW.rule_order) BEGIN SELECT RAISE(ABORT,'PLAN_EVALUATION_IMMUTABLE'); END;
CREATE TRIGGER data_snapshot_universe_ref_no_update BEFORE UPDATE ON data_snapshot_universe_ref BEGIN SELECT RAISE(ABORT,'DATA_SNAPSHOT_UNIVERSE_IMMUTABLE'); END;
CREATE TRIGGER data_snapshot_universe_ref_no_delete BEFORE DELETE ON data_snapshot_universe_ref BEGIN SELECT RAISE(ABORT,'DATA_SNAPSHOT_UNIVERSE_IMMUTABLE'); END;
CREATE TRIGGER security_market_constraint_no_update BEFORE UPDATE ON security_market_constraint BEGIN SELECT RAISE(ABORT,'MARKET_CONSTRAINT_IMMUTABLE'); END;
CREATE TRIGGER security_market_constraint_no_delete BEFORE DELETE ON security_market_constraint BEGIN SELECT RAISE(ABORT,'MARKET_CONSTRAINT_IMMUTABLE'); END;
CREATE TRIGGER market_universe_version_no_update BEFORE UPDATE ON market_universe_version BEGIN SELECT RAISE(ABORT,'MARKET_UNIVERSE_IMMUTABLE'); END;
CREATE TRIGGER market_universe_version_no_delete BEFORE DELETE ON market_universe_version BEGIN SELECT RAISE(ABORT,'MARKET_UNIVERSE_IMMUTABLE'); END;
CREATE TRIGGER market_universe_member_no_update BEFORE UPDATE ON market_universe_member BEGIN SELECT RAISE(ABORT,'MARKET_UNIVERSE_IMMUTABLE'); END;
CREATE TRIGGER market_universe_member_no_delete BEFORE DELETE ON market_universe_member BEGIN SELECT RAISE(ABORT,'MARKET_UNIVERSE_IMMUTABLE'); END;
CREATE TRIGGER market_universe_member_no_late_insert BEFORE INSERT ON market_universe_member WHEN EXISTS (SELECT 1 FROM data_snapshot_universe_ref WHERE market_universe_version_id=NEW.market_universe_version_id) AND NOT EXISTS (SELECT 1 FROM market_universe_member old WHERE old.market_universe_version_id=NEW.market_universe_version_id AND old.security_id=NEW.security_id AND old.listed_from=NEW.listed_from AND old.delisted_after IS NEW.delisted_after AND old.st_from IS NEW.st_from AND old.st_to IS NEW.st_to AND old.source_ref=NEW.source_ref) BEGIN SELECT RAISE(ABORT,'MARKET_UNIVERSE_IMMUTABLE'); END;
