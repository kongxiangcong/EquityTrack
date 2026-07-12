from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from trading_platform.domain.workflow import ArtifactManifestView, ReferenceDisposition, ResearchProjection, ResearchWorkflowResult, WorkflowHistory
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock
from trading_platform.persistence.objects import ContentAddressedObjectStore
from trading_platform.research.assembler import canonical_mapping_hash


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowRepository:
    def __init__(self, connection: sqlite3.Connection, objects: ContentAddressedObjectStore, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.objects = objects
        self.writer_lock = writer_lock

    def existing_result(self, invocation_id: str) -> ResearchWorkflowResult | None:
        row = self.connection.execute("SELECT workflow_run_id FROM workflow_run WHERE invocation_id=? AND status IN ('succeeded','succeeded_with_limits')", (invocation_id,)).fetchone()
        return None if row is None else self.result(row[0])

    def start(self, invocation_id: str, request_fingerprint: str, requested_date: str, effective_session_date: str) -> str:
        run_id = f"workflow_{uuid.uuid4().hex}"
        with self.connection:
            self.connection.execute("INSERT INTO workflow_run VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, invocation_id, "run_or_reuse_research", "1", request_fingerprint, requested_date, effective_session_date, "running", _now(), None))
            self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", run_id, 1, "queued", "running", "WORKFLOW_STARTED", _now()))
        return run_id

    def publish_artifact(self, payload: bytes, media_type: str, schema_version: str) -> str:
        sha256 = self.objects.publish(payload)
        artifact_id = f"artifact_{canonical_hash({'sha256': sha256, 'media': media_type, 'schema': schema_version})[:24]}"
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO artifact VALUES(?,?,?,?)", (artifact_id, sha256, media_type, schema_version))
        return artifact_id

    def publish_manifest(self, role: str, producer_type: str, producer_id: str, members: Iterable[tuple[str, str, str]]) -> str:
        members_tuple = tuple(members)
        identity = [{"artifact_id": artifact_id, "role": member_role, "direction": direction} for artifact_id, member_role, direction in members_tuple]
        membership_hash = canonical_hash(identity)
        manifest_id = f"manifest_{canonical_hash({'role': role, 'producer_type': producer_type, 'producer_id': producer_id, 'members': identity})[:24]}"
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO artifact_manifest VALUES(?,?,?,?,?,?)", (manifest_id, role, producer_type, producer_id, membership_hash, _now()))
            for ordinal, (artifact_id, member_role, direction) in enumerate(members_tuple):
                self.connection.execute("INSERT OR IGNORE INTO artifact_manifest_member VALUES(?,?,?,?,?)", (manifest_id, ordinal, artifact_id, member_role, direction))
        return manifest_id

    def freeze_projection(self, security_id: str, projection: ResearchProjection, projection_fingerprint: str) -> tuple[str, str, str, ReferenceDisposition]:
        payload = json.dumps({"manifest": projection.manifest, "estimates": projection.estimates, "context": projection.context, "as_of_date": projection.as_of_date, "profile": projection.profile, "field_semantics": [item.__dict__ for item in projection.field_semantics], "diluted_share_identity": projection.diluted_share_identity, "net_debt_bridge_identity": projection.net_debt_bridge_identity}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        projection_hash = hashlib.sha256(payload).hexdigest()
        existing = self.connection.execute("SELECT research_projection_id,research_snapshot_id,projection_artifact_id FROM research_input_projection WHERE projection_hash=?", (projection_hash,)).fetchone()
        if existing:
            return existing[0], existing[1], existing[2], ReferenceDisposition.REUSED
        artifact_id = self.publish_artifact(payload, "application/json", "ResearchProjection@1")
        attempt_id = f"attempt_{projection_hash[:24]}"
        record_id = f"record_{canonical_hash({'dataset': 'research_input', 'security': security_id, 'as_of': projection.as_of_date})[:24]}"
        version_id = f"version_{projection_hash[:24]}"
        snapshot_id = f"snapshot_{canonical_hash({'purpose': 'research', 'cutoff': projection.as_of_date, 'member': version_id, 'policy': 'research_input_policy@1'})[:24]}"
        projection_id = f"projection_{projection_hash[:24]}"
        retrieved = _now()
        source_ids = sorted(str(source.get("source_id", "")) for source in projection.manifest.get("sources", ()))
        source_identity = "frozen-research-projection:" + canonical_mapping_hash(source_ids)
        published_at = max(item.published_at for item in projection.field_semantics)
        available_at = max(item.available_at for item in projection.field_semantics)
        source_retrieved_at = max(item.retrieved_at for item in projection.field_semantics)
        availability_basis = "conservative_retrieval_time" if any(item.availability_basis == "conservative_retrieval_time" for item in projection.field_semantics) else "publisher_timestamp"
        with self.writer_lock.acquire(f"projection:{projection_id}"):
            with self.connection:
                self.connection.execute("INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (attempt_id, projection_id, "frozen_projection", "projection@1", "research_input", source_identity, "imported", "urn:local:frozen-research-projection", json.dumps({"source_ids": source_ids}), "{}", "date", "terms_unknown", "complete", "created", self.connection.execute("SELECT object_sha256 FROM artifact WHERE artifact_id=?", (artifact_id,)).fetchone()[0], retrieved, None, None, None, "not_applicable"))
                self.connection.execute("INSERT OR IGNORE INTO normalized_record VALUES(?,?,?)", (record_id, "research_input", f"{security_id}:{projection.as_of_date}"))
                previous = self.connection.execute("SELECT normalized_version_id,revision_no FROM normalized_version WHERE normalized_record_id=? ORDER BY revision_no DESC LIMIT 1", (record_id,)).fetchone()
                revision = 1 if previous is None else previous["revision_no"] + 1
                self.connection.execute("INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (version_id, record_id, revision, projection_hash, attempt_id, projection.as_of_date, published_at, "timestamp", available_at, availability_basis, source_retrieved_at, "warning", previous["normalized_version_id"] if previous else None))
                self.connection.execute("INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (snapshot_id, security_id, "research", projection.as_of_date, projection.as_of_date, f"{projection.as_of_date}T23:59:59+00:00", "Asia/Shanghai", "not_applicable", "research-query@1", "research-source@1", "research-freshness@1", canonical_hash([version_id]), "valid", "warning", 1, 1, 0, 0, 0, "frozen_research_projection", retrieved))
                self.connection.execute("INSERT INTO data_snapshot_member VALUES(?,?,?,?)", (snapshot_id, version_id, "research_input_projection", 0))
                self.connection.execute("INSERT INTO research_input_projection VALUES(?,?,?,?,?,?,?,?)", (projection_id, security_id, projection.as_of_date, artifact_id, projection_hash, projection_fingerprint, "research_input_policy@1", snapshot_id))
        return projection_id, snapshot_id, artifact_id, ReferenceDisposition.CREATED

    def begin_node(self, workflow_run_id: str, node_id: str, node_version: str, fingerprint: str) -> tuple[str, str]:
        node_run_id = f"node_{uuid.uuid4().hex}"
        attempt_id = f"node_attempt_{uuid.uuid4().hex}"
        with self.connection:
            self.connection.execute("INSERT INTO workflow_node_run VALUES(?,?,?,?,?,?,?)", (node_run_id, workflow_run_id, node_id, node_version, fingerprint, "running", None))
            self.connection.execute("INSERT INTO workflow_node_attempt VALUES(?,?,?,?,?,?,?,?)", (attempt_id, node_run_id, 1, None, _now(), None, None, None))
        return node_run_id, attempt_id

    def finish_node(self, node_run_id: str, attempt_id: str, disposition: ReferenceDisposition, manifest_id: str) -> None:
        attempt_disposition = "reused" if disposition is ReferenceDisposition.REUSED else "succeeded"
        with self.connection:
            self.connection.execute("UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? WHERE workflow_node_run_id=?", (manifest_id, node_run_id))
            self.connection.execute("UPDATE workflow_node_attempt SET disposition=?,completed_at=? WHERE workflow_node_attempt_id=?", (attempt_disposition, _now(), attempt_id))

    def fail_node(self, node_run_id: str, attempt_id: str, error_code: str, diagnostic_artifact_id: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE workflow_node_run SET status='failed' WHERE workflow_node_run_id=?", (node_run_id,))
            self.connection.execute("UPDATE workflow_node_attempt SET disposition='failed',completed_at=?,error_code=?,diagnostic_artifact_id=? WHERE workflow_node_attempt_id=?", (_now(), error_code, diagnostic_artifact_id, attempt_id))

    def add_ref(self, workflow_run_id: str, role: str, ref_type: str, ref_id: str, disposition: ReferenceDisposition) -> None:
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO workflow_run_ref VALUES(?,?,?,?,?)", (workflow_run_id, role, ref_type, ref_id, disposition.value))

    def complete(self, workflow_run_id: str, status: str, final_manifest_id: str) -> None:
        sequence = self.connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
        with self.connection:
            self.connection.execute("UPDATE workflow_run SET status=?,completed_at=? WHERE workflow_run_id=?", (status, _now(), workflow_run_id))
            self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", workflow_run_id, sequence, "running", status, "WORKFLOW_COMPLETED", _now()))
            self.add_ref(workflow_run_id, "final_manifest", "ArtifactManifest", final_manifest_id, ReferenceDisposition.CREATED)

    def fail(self, workflow_run_id: str, error_code: str) -> None:
        sequence = self.connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
        with self.connection:
            self.connection.execute("UPDATE workflow_run SET status='failed',completed_at=? WHERE workflow_run_id=?", (_now(), workflow_run_id))
            self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", workflow_run_id, sequence, "running", "failed", error_code, _now()))

    def result(self, workflow_run_id: str) -> ResearchWorkflowResult:
        decision = self.connection.execute("SELECT * FROM research_reuse_decision WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
        record = self.connection.execute("SELECT * FROM research_run_record WHERE research_run_id=?", (decision["research_run_id"],)).fetchone()
        workflow_snapshot = self.connection.execute("SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? AND ref_role='workflow_snapshot'", (workflow_run_id,)).fetchone()
        final_manifest = self.connection.execute("SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? AND ref_role='final_manifest'", (workflow_run_id,)).fetchone()
        return ResearchWorkflowResult(workflow_run_id, record["research_run_id"], record["research_snapshot_id"], workflow_snapshot[0] if workflow_snapshot else None, final_manifest[0], ReferenceDisposition(decision["disposition"]), decision["reason_code"], decision["stale_by_days"], record["canonical_json_artifact_id"], record["html_artifact_id"])

    def history(self, workflow_run_id: str) -> WorkflowHistory:
        run = self.connection.execute("SELECT * FROM workflow_run WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
        refs = tuple(dict(row) for row in self.connection.execute("SELECT ref_role,ref_type,ref_id,disposition FROM workflow_run_ref WHERE workflow_run_id=? ORDER BY ref_role,ref_id", (workflow_run_id,)))
        attempts = tuple(dict(row) for row in self.connection.execute("SELECT n.node_id,n.node_version,a.attempt_no,a.disposition,a.error_code,a.diagnostic_artifact_id FROM workflow_node_run n JOIN workflow_node_attempt a USING(workflow_node_run_id) WHERE n.workflow_run_id=? ORDER BY n.rowid", (workflow_run_id,)))
        transitions = tuple(dict(row) for row in self.connection.execute("SELECT sequence_no,from_status,to_status,reason_code,occurred_at FROM workflow_transition WHERE workflow_run_id=? ORDER BY sequence_no", (workflow_run_id,)))
        decision = dict(self.connection.execute("SELECT * FROM research_reuse_decision WHERE workflow_run_id=?", (workflow_run_id,)).fetchone())
        final_manifest = next(ref["ref_id"] for ref in refs if ref["ref_role"] == "final_manifest")
        return WorkflowHistory(workflow_run_id, run["status"], refs, attempts, transitions, decision, final_manifest)

    def manifest(self, manifest_id: str) -> ArtifactManifestView:
        row = self.connection.execute("SELECT * FROM artifact_manifest WHERE artifact_manifest_id=?", (manifest_id,)).fetchone()
        if row is None:
            raise KeyError(manifest_id)
        members = tuple(dict(member) for member in self.connection.execute(
            "SELECT member_order,artifact_id,member_role,direction FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order",
            (manifest_id,),
        ))
        return ArtifactManifestView(row["artifact_manifest_id"], row["manifest_role"], row["producer_type"], row["producer_id"], row["membership_hash"], members)

    def finalize_research_success(
        self,
        workflow_run_id: str,
        run_node_id: str,
        run_attempt_id: str,
        final_node_id: str,
        final_attempt_id: str,
        disposition: ReferenceDisposition,
        record_values: tuple[object, ...] | None,
        record: Mapping[str, object],
        projection_artifact_id: str,
        projection_id: str,
        json_artifact_id: str,
        html_artifact_id: str,
        workflow_snapshot_id: str | None,
        reason_code: str,
        stale_by_days: int,
        candidate_member_ids: tuple[str, ...],
        market_only_member_ids: tuple[str, ...],
        terminal_status: str,
    ) -> str:
        run_members = ((projection_artifact_id, "research_projection", "input"), (json_artifact_id, "research_run_json", "output"), (html_artifact_id, "research_report_html", "output"))
        identity = [{"artifact_id": artifact_id, "role": role, "direction": direction} for artifact_id, role, direction in run_members]
        run_manifest = f"manifest_{canonical_hash({'role': 'checkpoint', 'producer_type': 'WorkflowNodeRun', 'producer_id': run_node_id, 'members': identity})[:24]}"
        final_manifest = f"manifest_{canonical_hash({'role': 'workflow_final', 'producer_type': 'WorkflowRun', 'producer_id': workflow_run_id, 'members': identity})[:24]}"
        completed_at = _now()
        with self.connection:
            if record_values is not None:
                self.connection.execute("INSERT INTO research_run_record VALUES(?,?,?,?,?,?,?,?,?,?,?)", record_values)
            for manifest_id, role, producer_type, producer_id in ((run_manifest, "checkpoint", "WorkflowNodeRun", run_node_id), (final_manifest, "workflow_final", "WorkflowRun", workflow_run_id)):
                self.connection.execute("INSERT INTO artifact_manifest VALUES(?,?,?,?,?,?)", (manifest_id, role, producer_type, producer_id, canonical_hash(identity), completed_at))
                for member_index, (artifact_id, member_role, direction) in enumerate(run_members):
                    self.connection.execute("INSERT INTO artifact_manifest_member VALUES(?,?,?,?,?)", (manifest_id, member_index, artifact_id, member_role, direction))
            attempt_disposition = "reused" if disposition is ReferenceDisposition.REUSED else "succeeded"
            self.connection.execute("UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? WHERE workflow_node_run_id=?", (run_manifest, run_node_id))
            self.connection.execute("UPDATE workflow_node_attempt SET disposition=?,completed_at=? WHERE workflow_node_attempt_id=?", (attempt_disposition, completed_at, run_attempt_id))
            self.connection.execute("UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? WHERE workflow_node_run_id=?", (final_manifest, final_node_id))
            self.connection.execute("UPDATE workflow_node_attempt SET disposition='succeeded',completed_at=? WHERE workflow_node_attempt_id=?", (completed_at, final_attempt_id))
            refs = (("research_run", "ResearchRun", str(record["research_run_id"]), disposition.value), ("research_json", "Artifact", json_artifact_id, disposition.value), ("research_html", "Artifact", html_artifact_id, disposition.value), ("final_manifest", "ArtifactManifest", final_manifest, "created"))
            for ref_role, ref_type, ref_id, ref_disposition in refs:
                self.connection.execute("INSERT INTO workflow_run_ref VALUES(?,?,?,?,?)", (workflow_run_id, ref_role, ref_type, ref_id, ref_disposition))
            self.connection.execute("INSERT INTO research_reuse_decision VALUES(?,?,?,?,?,?,?,?,?)", (workflow_run_id, record["research_run_id"], disposition.value, "research_input_policy@1", reason_code, record["original_cutoff_date"], stale_by_days, json.dumps(list(candidate_member_ids)), json.dumps(list(market_only_member_ids))))
            sequence = self.connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
            self.connection.execute("UPDATE workflow_run SET status=?,completed_at=? WHERE workflow_run_id=?", (terminal_status, completed_at, workflow_run_id))
            self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", workflow_run_id, sequence, "running", terminal_status, "WORKFLOW_COMPLETED", completed_at))
        return final_manifest
