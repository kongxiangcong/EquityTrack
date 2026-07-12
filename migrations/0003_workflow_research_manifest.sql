CREATE TABLE workflow_run (
  workflow_run_id TEXT PRIMARY KEY,
  invocation_id TEXT NOT NULL UNIQUE,
  workflow_id TEXT NOT NULL,
  workflow_version TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  requested_date TEXT NOT NULL,
  effective_session_date TEXT,
  status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','succeeded_with_limits','failed','cancelled')),
  created_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE TABLE workflow_node_run (
  workflow_node_run_id TEXT PRIMARY KEY,
  workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id),
  node_id TEXT NOT NULL,
  node_version TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','skipped','blocked','failed')),
  checkpoint_manifest_id TEXT,
  UNIQUE(workflow_run_id,node_id)
);
CREATE TABLE workflow_node_attempt (
  workflow_node_attempt_id TEXT PRIMARY KEY,
  workflow_node_run_id TEXT NOT NULL REFERENCES workflow_node_run(workflow_node_run_id),
  attempt_no INTEGER NOT NULL CHECK(attempt_no > 0),
  disposition TEXT CHECK(disposition IN ('succeeded','reused','failed','abandoned')),
  started_at TEXT NOT NULL,
  completed_at TEXT,
  error_code TEXT,
  diagnostic_artifact_id TEXT,
  UNIQUE(workflow_node_run_id,attempt_no)
);
CREATE TABLE workflow_transition (
  workflow_transition_id TEXT PRIMARY KEY,
  workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id),
  sequence_no INTEGER NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  UNIQUE(workflow_run_id,sequence_no)
);
CREATE TABLE workflow_run_ref (
  workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id),
  ref_role TEXT NOT NULL,
  ref_type TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  disposition TEXT NOT NULL CHECK(disposition IN ('created','reused','input')),
  PRIMARY KEY(workflow_run_id,ref_role,ref_type,ref_id)
);
CREATE TABLE artifact_manifest (
  artifact_manifest_id TEXT PRIMARY KEY,
  manifest_role TEXT NOT NULL,
  producer_type TEXT NOT NULL,
  producer_id TEXT NOT NULL,
  membership_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE artifact_manifest_member (
  artifact_manifest_id TEXT NOT NULL REFERENCES artifact_manifest(artifact_manifest_id),
  member_order INTEGER NOT NULL,
  artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  member_role TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('input','output','diagnostic')),
  PRIMARY KEY(artifact_manifest_id,member_order),
  UNIQUE(artifact_manifest_id,artifact_id,member_role)
);
CREATE TABLE research_input_projection (
  research_projection_id TEXT PRIMARY KEY,
  security_id TEXT NOT NULL REFERENCES security(security_id),
  as_of_date TEXT NOT NULL,
  projection_artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  projection_hash TEXT NOT NULL UNIQUE,
  research_input_fingerprint TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  research_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id)
);
CREATE TABLE research_run_record (
  research_run_id TEXT PRIMARY KEY,
  research_input_fingerprint TEXT NOT NULL,
  research_projection_id TEXT NOT NULL REFERENCES research_input_projection(research_projection_id),
  research_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  request_fingerprint TEXT NOT NULL,
  engine_schema_version INTEGER NOT NULL,
  engine_code_identity TEXT NOT NULL,
  original_cutoff_date TEXT NOT NULL,
  status TEXT NOT NULL,
  canonical_json_artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  html_artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  UNIQUE(research_input_fingerprint,engine_code_identity)
);
CREATE TABLE research_reuse_decision (
  workflow_run_id TEXT PRIMARY KEY REFERENCES workflow_run(workflow_run_id),
  research_run_id TEXT NOT NULL REFERENCES research_run_record(research_run_id),
  disposition TEXT NOT NULL CHECK(disposition IN ('created','reused')),
  policy_version TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  original_cutoff_date TEXT NOT NULL,
  stale_by_days INTEGER NOT NULL,
  candidate_members_json TEXT NOT NULL,
  excluded_market_only_members_json TEXT NOT NULL
);
