CREATE TABLE research_component_input_version (
  normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version,
  security_id TEXT NOT NULL REFERENCES security,
  component_dataset TEXT NOT NULL CHECK(
    component_dataset IN ('research_model_input','market_path_policy')
  ),
  extracted_fields_json TEXT NOT NULL,
  input_identity_hash TEXT NOT NULL UNIQUE
);

CREATE TRIGGER research_component_input_no_update
BEFORE UPDATE ON research_component_input_version
BEGIN SELECT RAISE(ABORT,'RESEARCH_COMPONENT_INPUT_IMMUTABLE'); END;

CREATE TRIGGER research_component_input_no_delete
BEFORE DELETE ON research_component_input_version
BEGIN SELECT RAISE(ABORT,'RESEARCH_COMPONENT_INPUT_IMMUTABLE'); END;

CREATE TABLE market_session_normalized_evidence (
  market_session_version_id TEXT NOT NULL REFERENCES market_session_version,
  normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version
);

INSERT INTO market_session_normalized_evidence
SELECT s.market_session_version_id,v.normalized_version_id
FROM market_session_version s
JOIN normalized_version v
  ON v.source_attempt_id=s.source_attempt_id
 AND v.event_at=s.session_date
JOIN normalized_record r USING(normalized_record_id)
WHERE r.dataset='trade_cal'
  AND r.natural_key=(
    s.market||':'||s.session_date||':'||s.calendar_version
  );

CREATE TRIGGER market_session_normalized_evidence_no_update
BEFORE UPDATE ON market_session_normalized_evidence
BEGIN SELECT RAISE(ABORT,'MARKET_SESSION_EVIDENCE_IMMUTABLE'); END;

CREATE TRIGGER market_session_normalized_evidence_no_delete
BEFORE DELETE ON market_session_normalized_evidence
BEGIN SELECT RAISE(ABORT,'MARKET_SESSION_EVIDENCE_IMMUTABLE'); END;

CREATE TABLE market_path_daily_evidence_version (
  normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version,
  adjustment_factor_decimal TEXT NOT NULL,
  suspended INTEGER NOT NULL CHECK(suspended IN (0,1)),
  limit_state TEXT NOT NULL CHECK(limit_state IN ('none','up','down')),
  corporate_action_identity TEXT,
  evidence_identity_hash TEXT NOT NULL UNIQUE
);

CREATE TRIGGER market_path_daily_evidence_no_update
BEFORE UPDATE ON market_path_daily_evidence_version
BEGIN SELECT RAISE(ABORT,'MARKET_PATH_DAILY_EVIDENCE_IMMUTABLE'); END;

CREATE TRIGGER market_path_daily_evidence_no_delete
BEFORE DELETE ON market_path_daily_evidence_version
BEGIN SELECT RAISE(ABORT,'MARKET_PATH_DAILY_EVIDENCE_IMMUTABLE'); END;
