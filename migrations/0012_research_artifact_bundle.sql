CREATE TABLE research_artifact_record (
  artifact_record_id TEXT PRIMARY KEY,
  artifact_kind TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  content_hash TEXT NOT NULL,
  research_run_id TEXT NOT NULL REFERENCES research_run_record(research_run_id),
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  model_data_snapshot_identity TEXT NOT NULL,
  platform_security_id TEXT NOT NULL REFERENCES security(security_id),
  subject_id TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  source_identity TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  model_identity TEXT NOT NULL,
  formula_identities_json TEXT NOT NULL,
  code_identity TEXT NOT NULL,
  policy_identity TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ready','partial','blocked')),
  summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(research_run_id,artifact_kind,input_fingerprint,model_identity,code_identity,policy_identity)
);

CREATE TABLE research_artifact_relation (
  parent_artifact_record_id TEXT NOT NULL REFERENCES research_artifact_record(artifact_record_id),
  child_artifact_record_id TEXT NOT NULL REFERENCES research_artifact_record(artifact_record_id),
  relation_type TEXT NOT NULL CHECK(relation_type IN ('depends_on')),
  PRIMARY KEY(parent_artifact_record_id,child_artifact_record_id,relation_type),
  CHECK(parent_artifact_record_id!=child_artifact_record_id)
);

CREATE TABLE workflow_run_artifact_use (
  workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id),
  artifact_record_id TEXT NOT NULL REFERENCES research_artifact_record(artifact_record_id),
  disposition TEXT NOT NULL CHECK(disposition IN ('created','reused')),
  PRIMARY KEY(workflow_run_id,artifact_record_id)
);

CREATE INDEX research_artifact_by_run_kind
ON research_artifact_record(research_run_id,artifact_kind,created_at);

CREATE TRIGGER research_artifact_no_update
BEFORE UPDATE ON research_artifact_record
BEGIN SELECT RAISE(ABORT,'RESEARCH_ARTIFACT_IMMUTABLE'); END;

CREATE TRIGGER research_artifact_no_delete
BEFORE DELETE ON research_artifact_record
BEGIN SELECT RAISE(ABORT,'RESEARCH_ARTIFACT_IMMUTABLE'); END;

CREATE TRIGGER research_artifact_relation_no_update
BEFORE UPDATE ON research_artifact_relation
BEGIN SELECT RAISE(ABORT,'RESEARCH_ARTIFACT_RELATION_IMMUTABLE'); END;

CREATE TRIGGER research_artifact_relation_no_delete
BEFORE DELETE ON research_artifact_relation
BEGIN SELECT RAISE(ABORT,'RESEARCH_ARTIFACT_RELATION_IMMUTABLE'); END;

CREATE TRIGGER workflow_artifact_use_no_update
BEFORE UPDATE ON workflow_run_artifact_use
BEGIN SELECT RAISE(ABORT,'WORKFLOW_ARTIFACT_USE_IMMUTABLE'); END;

CREATE TRIGGER workflow_artifact_use_no_delete
BEFORE DELETE ON workflow_run_artifact_use
BEGIN SELECT RAISE(ABORT,'WORKFLOW_ARTIFACT_USE_IMMUTABLE'); END;
