ALTER TABLE workflow_run ADD COLUMN owner_token TEXT;
ALTER TABLE workflow_run ADD COLUMN lease_expires_at TEXT;
ALTER TABLE workflow_run ADD COLUMN heartbeat_at TEXT;
ALTER TABLE workflow_run ADD COLUMN definition_hash TEXT NOT NULL DEFAULT 'legacy-unverified';
ALTER TABLE workflow_run ADD COLUMN cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancellation_requested IN (0,1));
ALTER TABLE workflow_node_run ADD COLUMN input_schema TEXT NOT NULL DEFAULT 'legacy-unverified';
ALTER TABLE workflow_node_run ADD COLUMN output_schema TEXT NOT NULL DEFAULT 'legacy-unverified';
ALTER TABLE workflow_node_run ADD COLUMN owner_token TEXT;
ALTER TABLE workflow_node_run ADD COLUMN lease_expires_at TEXT;
ALTER TABLE workflow_node_run ADD COLUMN heartbeat_at TEXT;
ALTER TABLE workflow_node_attempt ADD COLUMN owner_token TEXT;
ALTER TABLE workflow_node_attempt ADD COLUMN lease_expires_at TEXT;
ALTER TABLE workflow_node_attempt ADD COLUMN heartbeat_at TEXT;
ALTER TABLE workflow_node_attempt ADD COLUMN retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0,1));
ALTER TABLE artifact_manifest ADD COLUMN member_count INTEGER;

CREATE TABLE workflow_run_request (
  workflow_run_id TEXT PRIMARY KEY REFERENCES workflow_run(workflow_run_id),
  request_artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
  request_hash TEXT NOT NULL,
  request_schema_version TEXT NOT NULL
);
CREATE TABLE workflow_recovery_event (
  workflow_recovery_event_id TEXT PRIMARY KEY,
  workflow_run_id TEXT NOT NULL REFERENCES workflow_run(workflow_run_id),
  sequence_no INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  owner_token TEXT,
  detail_code TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  UNIQUE(workflow_run_id,sequence_no)
);

CREATE TRIGGER workflow_run_identity_immutable BEFORE UPDATE ON workflow_run WHEN OLD.invocation_id!=NEW.invocation_id OR OLD.workflow_id!=NEW.workflow_id OR OLD.workflow_version!=NEW.workflow_version OR OLD.request_fingerprint!=NEW.request_fingerprint OR OLD.definition_hash!=NEW.definition_hash BEGIN SELECT RAISE(ABORT,'WORKFLOW_RUN_IDENTITY_IMMUTABLE'); END;
CREATE TRIGGER workflow_run_no_delete BEFORE DELETE ON workflow_run BEGIN SELECT RAISE(ABORT,'WORKFLOW_RUN_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER workflow_node_contract_immutable BEFORE UPDATE ON workflow_node_run WHEN OLD.workflow_run_id!=NEW.workflow_run_id OR OLD.node_id!=NEW.node_id OR OLD.node_version!=NEW.node_version OR OLD.input_fingerprint!=NEW.input_fingerprint OR OLD.input_schema!=NEW.input_schema OR OLD.output_schema!=NEW.output_schema BEGIN SELECT RAISE(ABORT,'WORKFLOW_NODE_CONTRACT_IMMUTABLE'); END;
CREATE TRIGGER workflow_node_no_delete BEFORE DELETE ON workflow_node_run BEGIN SELECT RAISE(ABORT,'WORKFLOW_NODE_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER workflow_attempt_terminal_immutable BEFORE UPDATE ON workflow_node_attempt WHEN OLD.disposition IS NOT NULL BEGIN SELECT RAISE(ABORT,'WORKFLOW_ATTEMPT_IMMUTABLE'); END;
CREATE TRIGGER workflow_attempt_no_delete BEFORE DELETE ON workflow_node_attempt BEGIN SELECT RAISE(ABORT,'WORKFLOW_ATTEMPT_IMMUTABLE'); END;
CREATE TRIGGER workflow_transition_no_update BEFORE UPDATE ON workflow_transition BEGIN SELECT RAISE(ABORT,'WORKFLOW_TRANSITION_IMMUTABLE'); END;
CREATE TRIGGER workflow_transition_no_delete BEFORE DELETE ON workflow_transition BEGIN SELECT RAISE(ABORT,'WORKFLOW_TRANSITION_IMMUTABLE'); END;
CREATE TRIGGER workflow_recovery_event_no_update BEFORE UPDATE ON workflow_recovery_event BEGIN SELECT RAISE(ABORT,'WORKFLOW_RECOVERY_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER workflow_recovery_event_no_delete BEFORE DELETE ON workflow_recovery_event BEGIN SELECT RAISE(ABORT,'WORKFLOW_RECOVERY_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER workflow_request_no_update BEFORE UPDATE ON workflow_run_request BEGIN SELECT RAISE(ABORT,'WORKFLOW_REQUEST_IMMUTABLE'); END;
CREATE TRIGGER workflow_request_no_delete BEFORE DELETE ON workflow_run_request BEGIN SELECT RAISE(ABORT,'WORKFLOW_REQUEST_IMMUTABLE'); END;
CREATE TRIGGER artifact_manifest_no_update BEFORE UPDATE ON artifact_manifest BEGIN SELECT RAISE(ABORT,'ARTIFACT_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER artifact_manifest_no_delete BEFORE DELETE ON artifact_manifest BEGIN SELECT RAISE(ABORT,'ARTIFACT_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER artifact_manifest_member_no_update BEFORE UPDATE ON artifact_manifest_member BEGIN SELECT RAISE(ABORT,'ARTIFACT_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER artifact_manifest_member_no_delete BEFORE DELETE ON artifact_manifest_member BEGIN SELECT RAISE(ABORT,'ARTIFACT_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER artifact_manifest_member_no_late_insert BEFORE INSERT ON artifact_manifest_member WHEN (SELECT member_count FROM artifact_manifest WHERE artifact_manifest_id=NEW.artifact_manifest_id) IS NOT NULL AND (SELECT count(*) FROM artifact_manifest_member WHERE artifact_manifest_id=NEW.artifact_manifest_id)>=(SELECT member_count FROM artifact_manifest WHERE artifact_manifest_id=NEW.artifact_manifest_id) AND NOT EXISTS (SELECT 1 FROM artifact_manifest_member WHERE artifact_manifest_id=NEW.artifact_manifest_id AND member_order=NEW.member_order AND artifact_id=NEW.artifact_id AND member_role=NEW.member_role AND direction=NEW.direction) BEGIN SELECT RAISE(ABORT,'ARTIFACT_MANIFEST_IMMUTABLE'); END;
CREATE TRIGGER object_blob_no_update BEFORE UPDATE ON object_blob BEGIN SELECT RAISE(ABORT,'OBJECT_BLOB_IMMUTABLE'); END;
CREATE TRIGGER object_blob_no_delete BEFORE DELETE ON object_blob BEGIN SELECT RAISE(ABORT,'OBJECT_BLOB_IMMUTABLE'); END;
