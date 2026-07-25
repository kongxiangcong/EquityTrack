CREATE TABLE research_evaluation_plan_record (
  evaluation_plan_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  canonical_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO research_evaluation_plan_record
SELECT
  'evaluation_plan_legacy_' || substr(canonical_sha256(
    p.research_projection_id || char(0) || p.projection_artifact_id
  ),1,24),
  'ResearchEvaluationPlanAudit@1',
  canonical_sha256(json_object(
    'schema_version','ResearchEvaluationPlanAudit@1',
    'legacy_research_projection_id',p.research_projection_id,
    'legacy_projection_artifact_id',p.projection_artifact_id,
    'legacy_research_input_fingerprint',p.research_input_fingerprint,
    'security_id',p.security_id,
    'as_of',p.as_of_date
  )),
  json_object(
    'schema_version','ResearchEvaluationPlanAudit@1',
    'legacy_research_projection_id',p.research_projection_id,
    'legacy_projection_artifact_id',p.projection_artifact_id,
    'legacy_research_input_fingerprint',p.research_input_fingerprint,
    'security_id',p.security_id,
    'as_of',p.as_of_date
  ),
  'migration-0014'
FROM research_input_projection p;

ALTER TABLE research_run_record RENAME TO research_run_record_0013;

CREATE TABLE research_run_record (
  research_run_id TEXT PRIMARY KEY,
  evaluation_fingerprint TEXT NOT NULL,
  evaluation_plan_id TEXT NOT NULL REFERENCES research_evaluation_plan_record(evaluation_plan_id),
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  request_fingerprint TEXT NOT NULL,
  engine_schema_version INTEGER NOT NULL,
  engine_code_identity TEXT NOT NULL,
  original_cutoff_date TEXT NOT NULL,
  status TEXT NOT NULL,
  canonical_json_artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  UNIQUE(evaluation_fingerprint,engine_code_identity)
);

INSERT INTO research_run_record
SELECT
  r.research_run_id,
  r.research_input_fingerprint,
  'evaluation_plan_legacy_' || substr(canonical_sha256(
    p.research_projection_id || char(0) || p.projection_artifact_id
  ),1,24),
  r.research_snapshot_id,
  r.request_fingerprint,
  r.engine_schema_version,
  r.engine_code_identity,
  r.original_cutoff_date,
  r.status,
  r.canonical_json_artifact_id
FROM research_run_record_0013 r
JOIN research_input_projection p
  ON p.research_projection_id=r.research_projection_id;

DROP TABLE research_run_record_0013;

ALTER TABLE research_reuse_decision RENAME TO research_reuse_decision_0013;

CREATE TABLE research_reuse_decision (
  workflow_run_id TEXT PRIMARY KEY REFERENCES workflow_run(workflow_run_id),
  research_run_id TEXT NOT NULL REFERENCES research_run_record(research_run_id),
  disposition TEXT NOT NULL CHECK(disposition IN ('created','reused')),
  policy_version TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  original_cutoff_date TEXT NOT NULL,
  stale_by_days INTEGER NOT NULL
);

INSERT INTO research_reuse_decision
SELECT
  workflow_run_id,
  research_run_id,
  disposition,
  policy_version,
  reason_code,
  original_cutoff_date,
  stale_by_days
FROM research_reuse_decision_0013;

DROP TABLE research_reuse_decision_0013;

INSERT OR IGNORE INTO workflow_run_ref(
  workflow_run_id,ref_role,ref_type,ref_id,disposition
)
SELECT
  r.workflow_run_id,
  'evaluation_plan',
  'ResearchEvaluationPlan',
  'evaluation_plan_legacy_' || substr(canonical_sha256(
    p.research_projection_id || char(0) || p.projection_artifact_id
  ),1,24),
  'input'
FROM workflow_run_ref r
JOIN research_input_projection p ON p.research_projection_id=r.ref_id
WHERE r.ref_role='research_projection'
  AND r.ref_type='ResearchProjection';

DELETE FROM workflow_run_ref
WHERE ref_role='research_projection' AND ref_type='ResearchProjection';

DROP TABLE research_input_projection;

CREATE TRIGGER research_evaluation_plan_no_update
BEFORE UPDATE ON research_evaluation_plan_record
BEGIN SELECT RAISE(ABORT,'RESEARCH_EVALUATION_PLAN_IMMUTABLE'); END;

CREATE TRIGGER research_evaluation_plan_no_delete
BEFORE DELETE ON research_evaluation_plan_record
BEGIN SELECT RAISE(ABORT,'RESEARCH_EVALUATION_PLAN_IMMUTABLE'); END;

CREATE TRIGGER research_run_no_update
BEFORE UPDATE ON research_run_record
BEGIN SELECT RAISE(ABORT,'RESEARCH_RUN_IMMUTABLE'); END;

CREATE TRIGGER research_run_no_delete
BEFORE DELETE ON research_run_record
BEGIN SELECT RAISE(ABORT,'RESEARCH_RUN_IMMUTABLE'); END;

CREATE TRIGGER workflow_request_v2_only
BEFORE INSERT ON workflow_run_request
WHEN (
  SELECT workflow_id FROM workflow_run
  WHERE workflow_run_id=NEW.workflow_run_id
)='research-workflow'
AND NEW.request_schema_version!='ResearchWorkflowRequest@2'
BEGIN SELECT RAISE(ABORT,'RESEARCH_WORKFLOW_REQUEST_V2_REQUIRED'); END;
