from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from trading_platform.domain.workflow import (
    ArtifactManifestView,
    forecast_structure_identity,
    ImmutableArtifactDraft,
    ReferenceDisposition,
    ResearchArtifactView,
    ResearchProjection,
    ResearchWorkflowResult,
    WorkflowHistory,
)
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock, PersistenceError
from trading_platform.persistence.objects import ContentAddressedObjectStore
from trading_platform.research.assembler import canonical_mapping_hash
from trading_platform.workflows.registry import NodeDefinition, WorkflowDefinition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowRepository:
    def __init__(self, connection: sqlite3.Connection, objects: ContentAddressedObjectStore, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.objects = objects
        self.writer_lock = writer_lock
        self.fault_injector = None
        self._research_artifact_lock = threading.RLock()

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    def existing_result(self, invocation_id: str) -> ResearchWorkflowResult | None:
        row = self.connection.execute("SELECT workflow_run_id FROM workflow_run WHERE invocation_id=? AND status IN ('succeeded','succeeded_with_limits')", (invocation_id,)).fetchone()
        return None if row is None else self.result(row[0])

    def invocation_run(self, invocation_id: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM workflow_run WHERE invocation_id=?", (invocation_id,)).fetchone()

    def start_recoverable(self, invocation_id: str, request_fingerprint: str, requested_date: str, effective_session_date: str, definition: WorkflowDefinition, owner_token: str, request_artifact_id: str, request_hash: str, lease_seconds: int = 30) -> str:
        run_id = f"workflow_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        definition_hash = canonical_hash(definition)
        with self.connection:
            self.connection.execute("INSERT INTO workflow_run(workflow_run_id,invocation_id,workflow_id,workflow_version,request_fingerprint,requested_date,effective_session_date,status,created_at,completed_at,owner_token,lease_expires_at,heartbeat_at,definition_hash,cancellation_requested) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)", (run_id, invocation_id, definition.workflow_id, definition.version, request_fingerprint, requested_date, effective_session_date, "running", now.isoformat(), None, owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat(), definition_hash))
            self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", run_id, 1, "queued", "running", "WORKFLOW_STARTED", now.isoformat()))
            self.connection.execute("INSERT INTO workflow_run_request VALUES(?,?,?,?)", (run_id, request_artifact_id, request_hash, "ResearchWorkflowRequest@1"))
        return run_id

    def acquire_lease(self, workflow_run_id: str, owner_token: str, definition: WorkflowDefinition, lease_seconds: int) -> None:
        try:
            with self.writer_lock.acquire(f"workflow-lease:{workflow_run_id}:{owner_token}"):
                row = self.connection.execute("SELECT * FROM workflow_run WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
                if row is None:
                    raise KeyError(workflow_run_id)
                if row["definition_hash"] != canonical_hash(definition) or row["workflow_id"] != definition.workflow_id or row["workflow_version"] != definition.version:
                    raise ValueError("WORKFLOW_DEFINITION_MISMATCH")
                now = datetime.now(timezone.utc)
                lease_expired = row["lease_expires_at"] is None or datetime.fromisoformat(row["lease_expires_at"]) <= now
                if row["owner_token"] not in {None, owner_token} and not lease_expired:
                    raise ValueError("WORKFLOW_BUSY")
                if lease_expired:
                    running = self.connection.execute("SELECT a.workflow_node_attempt_id,n.workflow_node_run_id FROM workflow_node_attempt a JOIN workflow_node_run n USING(workflow_node_run_id) WHERE n.workflow_run_id=? AND a.disposition IS NULL", (workflow_run_id,)).fetchall()
                    for attempt in running:
                        self.connection.execute("UPDATE workflow_node_attempt SET disposition='abandoned',completed_at=?,retryable=1 WHERE workflow_node_attempt_id=?", (now.isoformat(), attempt["workflow_node_attempt_id"]))
                        self.connection.execute("UPDATE workflow_node_run SET status='pending',owner_token=NULL,lease_expires_at=NULL,heartbeat_at=? WHERE workflow_node_run_id=? AND status='running'", (now.isoformat(), attempt["workflow_node_run_id"]))
                    self._recovery_event(workflow_run_id, "LEASE_TAKEOVER", owner_token, "EXPIRED_OWNER_ABANDONED", now.isoformat())
                self.connection.execute("UPDATE workflow_run SET owner_token=?,lease_expires_at=?,heartbeat_at=? WHERE workflow_run_id=?", (owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat(), workflow_run_id))
                self._transition(workflow_run_id, "running", "running", "LEASE_ACQUIRED", now.isoformat())
                self.connection.commit()
        except PersistenceError as error:
            if error.code == "RUNTIME_BUSY":
                raise ValueError("WORKFLOW_BUSY") from error
            raise

    def heartbeat(self, workflow_run_id: str, owner_token: str, lease_seconds: int = 30) -> None:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        for retry in range(10):
            try:
                with self.writer_lock.acquire(f"workflow-heartbeat:{workflow_run_id}:{owner_token}"):
                    with self.connection:
                        changed = self.connection.execute("UPDATE workflow_run SET heartbeat_at=?,lease_expires_at=? WHERE workflow_run_id=? AND owner_token=? AND status='running'", (now.isoformat(), expires, workflow_run_id, owner_token)).rowcount
                        if changed != 1:
                            raise ValueError("WORKFLOW_LEASE_LOST")
                        self.connection.execute("UPDATE workflow_node_run SET heartbeat_at=?,lease_expires_at=? WHERE workflow_run_id=? AND owner_token=? AND status='running'", (now.isoformat(), expires, workflow_run_id, owner_token))
                        self.connection.execute("UPDATE workflow_node_attempt SET heartbeat_at=?,lease_expires_at=? WHERE owner_token=? AND disposition IS NULL AND workflow_node_run_id IN (SELECT workflow_node_run_id FROM workflow_node_run WHERE workflow_run_id=?)", (now.isoformat(), expires, owner_token, workflow_run_id))
                return
            except PersistenceError as error:
                if error.code != "RUNTIME_BUSY" or retry == 9:
                    raise
                time.sleep(0.05)

    def request_cancel(self, workflow_run_id: str, reason: str) -> None:
        with self.connection:
            changed = self.connection.execute("UPDATE workflow_run SET cancellation_requested=1 WHERE workflow_run_id=? AND status='running'", (workflow_run_id,)).rowcount
            if changed != 1:
                raise ValueError("WORKFLOW_NOT_CANCELLABLE")
            self._recovery_event(workflow_run_id, "CANCELLATION_REQUESTED", None, reason, _now())

    def stop_if_cancelled(self, workflow_run_id: str) -> None:
        row = self.connection.execute("SELECT cancellation_requested,status FROM workflow_run WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
        if row and row["cancellation_requested"] and row["status"] == "running":
            now = _now()
            with self.connection:
                self.connection.execute("UPDATE workflow_run SET status='cancelled',completed_at=?,owner_token=NULL,lease_expires_at=NULL WHERE workflow_run_id=?", (now, workflow_run_id))
                self._transition(workflow_run_id, "running", "cancelled", "USER_CANCELLED", now)
            raise ValueError("WORKFLOW_CANCELLED")

    def request_payload(self, workflow_run_id: str) -> bytes:
        row = self.connection.execute("SELECT a.object_sha256,o.relative_path,r.request_hash FROM workflow_run_request r JOIN artifact a ON a.artifact_id=r.request_artifact_id JOIN object_blob o ON o.sha256=a.object_sha256 WHERE r.workflow_run_id=?", (workflow_run_id,)).fetchone()
        if row is None:
            raise ValueError("WORKFLOW_REQUEST_MISSING")
        path = self.objects.data_root / row["relative_path"]
        payload = path.read_bytes() if path.is_file() else b""
        if hashlib.sha256(payload).hexdigest() != row["request_hash"]:
            raise ValueError("WORKFLOW_REQUEST_INTEGRITY_FAILED")
        return payload

    def node(self, workflow_run_id: str, node_id: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM workflow_node_run WHERE workflow_run_id=? AND node_id=?", (workflow_run_id, node_id)).fetchone()

    def begin_or_retry_node(self, workflow_run_id: str, definition: NodeDefinition, fingerprint: str, owner_token: str, lease_seconds: int = 30) -> tuple[str, str]:
        node = self.node(workflow_run_id, definition.node_id)
        now = datetime.now(timezone.utc)
        if node is None:
            node_id = f"node_{uuid.uuid4().hex}"
            attempt_no = 1
            with self.connection:
                self.connection.execute("INSERT INTO workflow_node_run(workflow_node_run_id,workflow_run_id,node_id,node_version,input_fingerprint,status,checkpoint_manifest_id,input_schema,output_schema,owner_token,lease_expires_at,heartbeat_at) VALUES(?,?,?,?,?,'running',NULL,?,?,?,?,?)", (node_id, workflow_run_id, definition.node_id, definition.version, fingerprint, definition.input_schema, definition.output_schema, owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat()))
        else:
            if node["node_version"] != definition.version or node["input_schema"] != definition.input_schema or node["output_schema"] != definition.output_schema:
                raise ValueError("WORKFLOW_DEFINITION_MISMATCH")
            if node["input_fingerprint"] != fingerprint:
                raise ValueError("WORKFLOW_FINGERPRINT_MISMATCH")
            if node["status"] == "succeeded":
                raise ValueError("WORKFLOW_NODE_ALREADY_SUCCEEDED")
            node_id = node["workflow_node_run_id"]
            attempt_no = self.connection.execute("SELECT coalesce(max(attempt_no),0)+1 FROM workflow_node_attempt WHERE workflow_node_run_id=?", (node_id,)).fetchone()[0]
            with self.connection:
                self.connection.execute("UPDATE workflow_node_run SET status='running',owner_token=?,lease_expires_at=?,heartbeat_at=? WHERE workflow_node_run_id=?", (owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat(), node_id))
        attempt_id = f"node_attempt_{uuid.uuid4().hex}"
        with self.connection:
            self.connection.execute("INSERT INTO workflow_node_attempt(workflow_node_attempt_id,workflow_node_run_id,attempt_no,disposition,started_at,completed_at,error_code,diagnostic_artifact_id,owner_token,lease_expires_at,heartbeat_at,retryable) VALUES(?,?,?,NULL,?,NULL,NULL,NULL,?,?,?,0)", (attempt_id, node_id, attempt_no, now.isoformat(), owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat()))
        return node_id, attempt_id

    def validate_checkpoint(self, workflow_run_id: str, definition: NodeDefinition, fingerprint: str) -> sqlite3.Row | None:
        node = self.node(workflow_run_id, definition.node_id)
        if node is None or node["status"] != "succeeded":
            return None
        if node["node_version"] != definition.version or node["input_schema"] != definition.input_schema or node["output_schema"] != definition.output_schema:
            raise ValueError("WORKFLOW_DEFINITION_MISMATCH")
        if node["input_fingerprint"] != fingerprint:
            raise ValueError("WORKFLOW_FINGERPRINT_MISMATCH")
        manifest = self.connection.execute("SELECT * FROM artifact_manifest WHERE artifact_manifest_id=?", (node["checkpoint_manifest_id"],)).fetchone()
        members = self.connection.execute("SELECT * FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order", (node["checkpoint_manifest_id"],)).fetchall()
        if manifest is None or manifest["member_count"] != len(members):
            raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
        identity = [{"artifact_id": item["artifact_id"], "role": item["member_role"], "direction": item["direction"]} for item in members]
        if canonical_hash(identity) != manifest["membership_hash"]:
            raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
        for item in members:
            artifact = self.connection.execute("SELECT o.* FROM artifact a JOIN object_blob o ON o.sha256=a.object_sha256 WHERE a.artifact_id=?", (item["artifact_id"],)).fetchone()
            if artifact is None:
                raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
            path = self.objects.data_root / artifact["relative_path"]
            if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
        return node

    def mark_retryable(self, node_run_id: str, attempt_id: str, code: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE workflow_node_attempt SET disposition='failed',completed_at=?,error_code=?,retryable=1 WHERE workflow_node_attempt_id=?", (_now(), code, attempt_id))
            self.connection.execute("UPDATE workflow_node_run SET status='pending' WHERE workflow_node_run_id=?", (node_run_id,))

    def commit_research_checkpoint(self, node_run_id: str, attempt_id: str, disposition: ReferenceDisposition, record_values: tuple[object, ...] | None, members: tuple[tuple[str, str, str], ...]) -> str:
        identity = [{"artifact_id": a, "role": r, "direction": d} for a, r, d in members]
        manifest_id = f"manifest_{canonical_hash({'role': 'checkpoint', 'producer_type': 'WorkflowNodeRun', 'producer_id': node_run_id, 'members': identity})[:24]}"
        completed = _now()
        with self.connection:
            if record_values is not None:
                self.connection.execute("INSERT OR IGNORE INTO research_run_record VALUES(?,?,?,?,?,?,?,?,?,?,?)", record_values)
            self.connection.execute("INSERT OR IGNORE INTO artifact_manifest(artifact_manifest_id,manifest_role,producer_type,producer_id,membership_hash,created_at,member_count) VALUES(?,?,?,?,?,?,?)", (manifest_id, "checkpoint", "WorkflowNodeRun", node_run_id, canonical_hash(identity), completed, len(members)))
            for index, (artifact_id, role, direction) in enumerate(members):
                self.connection.execute("INSERT OR IGNORE INTO artifact_manifest_member VALUES(?,?,?,?,?)", (manifest_id, index, artifact_id, role, direction))
            attempt_disposition = "reused" if disposition is ReferenceDisposition.REUSED else "succeeded"
            self.connection.execute("UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? WHERE workflow_node_run_id=?", (manifest_id, node_run_id))
            self.connection.execute("UPDATE workflow_node_attempt SET disposition=?,completed_at=? WHERE workflow_node_attempt_id=?", (attempt_disposition, completed, attempt_id))
        return manifest_id

    def persist_research_record(self, record_values: tuple[object, ...]) -> None:
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO research_run_record VALUES(?,?,?,?,?,?,?,?,?,?,?)", record_values)

    def checkpoint_members(self, node_run_id: str) -> tuple[sqlite3.Row, ...]:
        return tuple(self.connection.execute("SELECT m.*,a.schema_version FROM workflow_node_run n JOIN artifact_manifest_member m ON m.artifact_manifest_id=n.checkpoint_manifest_id JOIN artifact a USING(artifact_id) WHERE n.workflow_node_run_id=? ORDER BY m.member_order", (node_run_id,)))

    def _transition(self, workflow_run_id: str, from_status: str, to_status: str, reason: str, occurred_at: str) -> None:
        sequence = self.connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
        self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", workflow_run_id, sequence, from_status, to_status, reason, occurred_at))

    def _recovery_event(self, workflow_run_id: str, event_type: str, owner_token: str | None, detail: str, occurred_at: str) -> None:
        sequence = self.connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_recovery_event WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
        self.connection.execute("INSERT INTO workflow_recovery_event VALUES(?,?,?,?,?,?,?)", (f"recovery_{uuid.uuid4().hex}", workflow_run_id, sequence, event_type, owner_token, detail, occurred_at))

    def start(self, invocation_id: str, request_fingerprint: str, requested_date: str, effective_session_date: str) -> str:
        run_id = f"workflow_{uuid.uuid4().hex}"
        with self.connection:
            self.connection.execute("INSERT INTO workflow_run(workflow_run_id,invocation_id,workflow_id,workflow_version,request_fingerprint,requested_date,effective_session_date,status,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, invocation_id, "run_or_reuse_research", "1", request_fingerprint, requested_date, effective_session_date, "running", _now(), None))
            self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", run_id, 1, "queued", "running", "WORKFLOW_STARTED", _now()))
        return run_id

    def publish_artifact(self, payload: bytes, media_type: str, schema_version: str) -> str:
        sha256 = self.objects.publish(payload)
        artifact_id = f"artifact_{canonical_hash({'sha256': sha256, 'media': media_type, 'schema': schema_version})[:24]}"
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO artifact VALUES(?,?,?,?)", (artifact_id, sha256, media_type, schema_version))
        return artifact_id

    def persist_research_artifact_bundle(
        self,
        *,
        research_run_id: str,
        data_snapshot_id: str,
        code_identity: str,
        drafts: tuple[ImmutableArtifactDraft, ...],
        workflow_run_id: str | None = None,
    ) -> tuple[str, ...]:
        # The filesystem writer lock is deliberately fail-fast. Serialize same-process
        # replays here so identical requests can observe the first committed bundle.
        with self._research_artifact_lock:
            return self._persist_research_artifact_bundle(
                research_run_id=research_run_id,
                data_snapshot_id=data_snapshot_id,
                code_identity=code_identity,
                drafts=drafts,
                workflow_run_id=workflow_run_id,
            )

    def _persist_research_artifact_bundle(
        self,
        *,
        research_run_id: str,
        data_snapshot_id: str,
        code_identity: str,
        drafts: tuple[ImmutableArtifactDraft, ...],
        workflow_run_id: str | None = None,
    ) -> tuple[str, ...]:
        if not isinstance(drafts, tuple) or any(
            not isinstance(draft, ImmutableArtifactDraft) for draft in drafts
        ):
            raise ValueError("RESEARCH_ARTIFACT_BUNDLE_TYPE_INVALID")
        if not drafts:
            return ()
        kinds = tuple(draft.artifact_kind for draft in drafts)
        if len(kinds) != len(set(kinds)):
            raise ValueError("RESEARCH_ARTIFACT_KIND_DUPLICATE")
        seen: set[str] = set()
        for draft in drafts:
            if not set(draft.dependency_kinds).issubset(seen):
                raise ValueError("RESEARCH_ARTIFACT_DEPENDENCY_ORDER_INVALID")
            seen.add(draft.artifact_kind)
        run = self.connection.execute(
            "SELECT * FROM research_run_record WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
        snapshot = self.connection.execute(
            "SELECT * FROM data_snapshot WHERE data_snapshot_id=?",
            (data_snapshot_id,),
        ).fetchone()
        if run is None or snapshot is None:
            raise ValueError("RESEARCH_ARTIFACT_PARENT_MISSING")
        if (
            data_snapshot_id != run["research_snapshot_id"]
            or code_identity != run["engine_code_identity"]
        ):
            raise ValueError("RESEARCH_ARTIFACT_PARENT_IDENTITY_MISMATCH")
        if any(draft.as_of != run["original_cutoff_date"] for draft in drafts):
            raise ValueError("RESEARCH_ARTIFACT_AS_OF_MISMATCH")
        platform_security_id = snapshot["scope_id"]
        subject_aliases = self._platform_subject_aliases(
            platform_security_id,
            run["original_cutoff_date"],
        )
        model_data_snapshot_identity = self._validate_research_artifact_lineage(
            drafts,
            subject_aliases=subject_aliases,
        )

        record_by_kind = {
            draft.artifact_kind: (
                f"research_artifact_{canonical_hash({'run': research_run_id, 'snapshot': data_snapshot_id, 'draft': draft.content_hash, 'code': code_identity})[:24]}"
            )
            for draft in drafts
        }
        prepared: list[tuple[ImmutableArtifactDraft, str, str, str, bytes]] = []
        for draft in drafts:
            record_id = record_by_kind[draft.artifact_kind]
            dependency_ids = tuple(
                record_by_kind[kind] for kind in draft.dependency_kinds
            )
            envelope = {
                "envelope_schema": "ResearchArtifactEnvelope@1",
                "artifact_record_id": record_id,
                "artifact_kind": draft.artifact_kind,
                "artifact_schema_version": draft.schema_version,
                "research_run_id": research_run_id,
                "data_snapshot_id": data_snapshot_id,
                "model_data_snapshot_identity": model_data_snapshot_identity,
                "platform_security_id": platform_security_id,
                "subject_id": draft.subject_id,
                "as_of": draft.as_of,
                "source_identity": draft.source_identity,
                "model_identity": draft.model_identity,
                "formula_identities": list(draft.formula_identities),
                "code_identity": code_identity,
                "policy_identity": draft.policy_identity,
                "status": draft.status,
                "dependency_record_ids": list(dependency_ids),
                "summary": draft.summary,
                "payload": draft.payload,
            }
            payload = json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            artifact_id = self.publish_artifact(
                payload,
                "application/json",
                draft.schema_version,
            )
            object_hash = self.connection.execute(
                "SELECT object_sha256 FROM artifact WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()[0]
            prepared.append((draft, record_id, artifact_id, object_hash, payload))
        self._fault("research_artifact.objects_published")

        bundle_identity = canonical_hash(
            {
                "research_run_id": research_run_id,
                "data_snapshot_id": data_snapshot_id,
                "records": [item[1] for item in prepared],
            }
        )
        with self.writer_lock.acquire(f"research-artifacts:{bundle_identity}"):
            with self.connection:
                created_at = _now()
                for draft, record_id, artifact_id, object_hash, _ in prepared:
                    existed_before = self.connection.execute(
                        "SELECT 1 FROM research_artifact_record WHERE artifact_record_id=?",
                        (record_id,),
                    ).fetchone() is not None
                    values = (
                        record_id,
                        draft.artifact_kind,
                        draft.schema_version,
                        artifact_id,
                        object_hash,
                        research_run_id,
                        data_snapshot_id,
                        model_data_snapshot_identity,
                        platform_security_id,
                        draft.subject_id,
                        draft.as_of,
                        draft.source_identity,
                        draft.content_hash,
                        draft.model_identity,
                        json.dumps(list(draft.formula_identities), separators=(",", ":")),
                        code_identity,
                        draft.policy_identity,
                        draft.status,
                        draft.summary_json,
                        created_at,
                    )
                    self.connection.execute(
                        "INSERT OR IGNORE INTO research_artifact_record VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        values,
                    )
                    existing = self.connection.execute(
                        "SELECT artifact_kind,schema_version,artifact_id,content_hash,research_run_id,data_snapshot_id,model_data_snapshot_identity,platform_security_id,subject_id,as_of_date,source_identity,input_fingerprint,model_identity,formula_identities_json,code_identity,policy_identity,status,summary_json FROM research_artifact_record WHERE artifact_record_id=?",
                        (record_id,),
                    ).fetchone()
                    if existing is None or tuple(existing) != (
                        draft.artifact_kind,
                        draft.schema_version,
                        artifact_id,
                        object_hash,
                        research_run_id,
                        data_snapshot_id,
                        model_data_snapshot_identity,
                        platform_security_id,
                        draft.subject_id,
                        draft.as_of,
                        draft.source_identity,
                        draft.content_hash,
                        draft.model_identity,
                        json.dumps(list(draft.formula_identities), separators=(",", ":")),
                        code_identity,
                        draft.policy_identity,
                        draft.status,
                        draft.summary_json,
                    ):
                        raise ValueError("RESEARCH_ARTIFACT_IDENTITY_COLLISION")
                    if workflow_run_id is not None:
                        self.connection.execute(
                            "INSERT OR IGNORE INTO workflow_run_artifact_use VALUES(?,?,?)",
                            (
                                workflow_run_id,
                                record_id,
                                "reused" if existed_before else "created",
                            ),
                        )
                for draft in drafts:
                    child_id = record_by_kind[draft.artifact_kind]
                    for dependency_kind in draft.dependency_kinds:
                        self.connection.execute(
                            "INSERT OR IGNORE INTO research_artifact_relation VALUES(?,?,?)",
                            (
                                record_by_kind[dependency_kind],
                                child_id,
                                "depends_on",
                            ),
                        )
                self._fault("research_artifact.before_commit")
        self._fault("research_artifact.after_commit")
        return tuple(item[1] for item in prepared)

    @staticmethod
    def _validate_research_artifact_lineage(
        drafts: tuple[ImmutableArtifactDraft, ...],
        *,
        subject_aliases: frozenset[str],
    ) -> str:
        by_kind = {draft.artifact_kind: draft for draft in drafts}
        data_snapshot = by_kind.get("DataSnapshot")
        if data_snapshot is None:
            raise ValueError("RESEARCH_ARTIFACT_DATA_SNAPSHOT_MISSING")
        model_snapshot_identity = data_snapshot.source_identity
        snapshot_payload = data_snapshot.payload
        subjects = {draft.subject_id for draft in drafts}
        if len(subjects) != 1:
            raise ValueError("RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH")
        subject_id = next(iter(subjects))
        if (
            subject_id not in subject_aliases
            or snapshot_payload.get("snapshot_id") != model_snapshot_identity
            or snapshot_payload.get("security_id") != subject_id
            or snapshot_payload.get("as_of") != data_snapshot.as_of
        ):
            raise ValueError("RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH")

        forecast = by_kind.get("Forecast")
        if forecast is not None:
            forecast_payload = forecast.payload
            if not WorkflowRepository._forecast_payload_matches(
                forecast_payload,
                graph_identity=forecast.source_identity,
                subject_id=subject_id,
                model_snapshot_identity=model_snapshot_identity,
                as_of=forecast.as_of,
            ):
                raise ValueError("RESEARCH_ARTIFACT_FORECAST_LINEAGE_MISMATCH")
            forecast_structure = forecast_structure_identity(forecast_payload)
        else:
            forecast_structure = None

        valuation = by_kind.get("Valuation")
        if valuation is not None:
            if forecast is None:
                raise ValueError("RESEARCH_ARTIFACT_FORECAST_MISSING")
            payload = valuation.payload
            scenarios = payload.get("scenarios")
            if not isinstance(scenarios, list) or not scenarios:
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
            scenario_graphs = [
                scenario.get("forecast_graph")
                for scenario in scenarios
                if isinstance(scenario, Mapping)
            ]
            if len(scenario_graphs) != len(scenarios) or any(
                not isinstance(graph, Mapping)
                or not WorkflowRepository._forecast_payload_matches(
                    graph,
                    graph_identity=str(graph.get("graph_id", "")),
                    subject_id=subject_id,
                    model_snapshot_identity=model_snapshot_identity,
                    as_of=valuation.as_of,
                )
                for graph in scenario_graphs
            ):
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
            scenario_structures = {
                forecast_structure_identity(graph) for graph in scenario_graphs
            }
            if scenario_structures != {forecast_structure}:
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
            source_value = {
                "forecast_graph_identity": forecast.source_identity,
                "forecast_structure_identity": forecast_structure,
                "forecast_graph_ids": [graph["graph_id"] for graph in scenario_graphs],
                "model_data_snapshot_identity": model_snapshot_identity,
            }
            expected_source = "deterministic-scenario-set:" + hashlib.sha256(
                json.dumps(
                    source_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if (
                valuation.source_identity != expected_source
                or valuation.summary.get("forecast_graph_identity")
                != forecast.source_identity
                or valuation.summary.get("forecast_structure_identity")
                != forecast_structure
                or valuation.summary.get("model_data_snapshot_identity")
                != model_snapshot_identity
            ):
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
        return model_snapshot_identity

    def _platform_subject_aliases(
        self,
        platform_security_id: str,
        as_of: str,
    ) -> frozenset[str]:
        security = self.connection.execute(
            "SELECT 1 FROM security WHERE security_id=?",
            (platform_security_id,),
        ).fetchone()
        if security is None:
            raise ValueError("RESEARCH_ARTIFACT_PLATFORM_SECURITY_MISSING")
        aliases = {platform_security_id}
        suffixes = {
            "BSE": "BJ",
            "HKEX": "HK",
            "SSE": "SH",
            "SH": "SH",
            "SHSE": "SH",
            "SZ": "SZ",
            "SZSE": "SZ",
            "XSHG": "SH",
            "XSHE": "SZ",
        }
        for row in self.connection.execute(
            "SELECT market,code FROM security_identifier "
            "WHERE security_id=? AND valid_from<=? "
            "AND (valid_to IS NULL OR valid_to>=?)",
            (platform_security_id, as_of, as_of),
        ):
            market = str(row["market"]).upper()
            code = str(row["code"])
            aliases.add(code)
            suffix = suffixes.get(market)
            if suffix:
                aliases.add(f"{code}.{suffix}")
        return frozenset(aliases)

    @staticmethod
    def _forecast_payload_matches(
        payload: Mapping[str, object],
        *,
        graph_identity: str,
        subject_id: str,
        model_snapshot_identity: str,
        as_of: str,
    ) -> bool:
        nodes = payload.get("nodes")
        return (
            payload.get("graph_id") == graph_identity
            and payload.get("security_id") == subject_id
            and payload.get("data_snapshot_id") == model_snapshot_identity
            and isinstance(nodes, list)
            and bool(nodes)
            and all(
                isinstance(node, Mapping)
                and isinstance(node.get("quantity"), Mapping)
                and node["quantity"].get("as_of") == as_of
                for node in nodes
            )
        )

    def research_artifact_view(self, artifact_record_id: str) -> ResearchArtifactView:
        row = self.connection.execute(
            "SELECT r.*,a.object_sha256,o.size_bytes,o.relative_path "
            "FROM research_artifact_record r JOIN artifact a USING(artifact_id) "
            "JOIN object_blob o ON o.sha256=a.object_sha256 "
            "WHERE r.artifact_record_id=?",
            (artifact_record_id,),
        ).fetchone()
        if row is None:
            raise KeyError(artifact_record_id)
        path = self.objects.data_root / row["relative_path"]
        if (
            not path.is_file()
            or path.stat().st_size != row["size_bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != row["object_sha256"]
            or row["content_hash"] != row["object_sha256"]
        ):
            raise PersistenceError(
                "OBJECT_INTEGRITY_FAILED",
                "Research artifact content-addressed object is missing or corrupt.",
            )
        envelope = json.loads(path.read_bytes())
        expected = {
            "artifact_record_id": row["artifact_record_id"],
            "artifact_kind": row["artifact_kind"],
            "artifact_schema_version": row["schema_version"],
            "research_run_id": row["research_run_id"],
            "data_snapshot_id": row["data_snapshot_id"],
            "model_data_snapshot_identity": row["model_data_snapshot_identity"],
            "platform_security_id": row["platform_security_id"],
            "subject_id": row["subject_id"],
            "as_of": row["as_of_date"],
            "source_identity": row["source_identity"],
            "model_identity": row["model_identity"],
            "code_identity": row["code_identity"],
            "policy_identity": row["policy_identity"],
            "status": row["status"],
        }
        if envelope.get("envelope_schema") != "ResearchArtifactEnvelope@1" or any(
            envelope.get(name) != value for name, value in expected.items()
        ):
            raise PersistenceError(
                "RESEARCH_ARTIFACT_ENVELOPE_MISMATCH",
                "Research artifact envelope does not match its typed database identity.",
            )
        dependencies = tuple(
            item[0]
            for item in self.connection.execute(
                "SELECT parent_artifact_record_id FROM research_artifact_relation WHERE child_artifact_record_id=? ORDER BY parent_artifact_record_id",
                (artifact_record_id,),
            )
        )
        if tuple(envelope.get("dependency_record_ids", ())) != dependencies:
            raise PersistenceError(
                "RESEARCH_ARTIFACT_RELATION_MISMATCH",
                "Research artifact dependency envelope and relation table differ.",
            )
        return ResearchArtifactView(
            artifact_record_id=row["artifact_record_id"],
            artifact_kind=row["artifact_kind"],
            schema_version=row["schema_version"],
            research_run_id=row["research_run_id"],
            data_snapshot_id=row["data_snapshot_id"],
            model_data_snapshot_identity=row["model_data_snapshot_identity"],
            platform_security_id=row["platform_security_id"],
            subject_id=row["subject_id"],
            as_of=row["as_of_date"],
            source_identity=row["source_identity"],
            model_identity=row["model_identity"],
            formula_identities=tuple(json.loads(row["formula_identities_json"])),
            code_identity=row["code_identity"],
            policy_identity=row["policy_identity"],
            status=row["status"],
            content_hash=row["content_hash"],
            dependency_record_ids=dependencies,
            summary=json.loads(row["summary_json"]),
            payload=envelope["payload"],
        )

    def research_run_payload(self, research_run_id: str) -> Mapping[str, object]:
        row = self.connection.execute(
            "SELECT r.engine_schema_version,a.object_sha256,o.size_bytes,o.relative_path "
            "FROM research_run_record r "
            "JOIN artifact a ON a.artifact_id=r.canonical_json_artifact_id "
            "JOIN object_blob o ON o.sha256=a.object_sha256 "
            "WHERE r.research_run_id=?",
            (research_run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(research_run_id)
        path = self.objects.data_root / row["relative_path"]
        payload = path.read_bytes() if path.is_file() else b""
        if (
            len(payload) != row["size_bytes"]
            or hashlib.sha256(payload).hexdigest() != row["object_sha256"]
        ):
            raise PersistenceError(
                "OBJECT_INTEGRITY_FAILED",
                "Canonical research JSON is missing or corrupt.",
            )
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as error:
            raise PersistenceError(
                "RESEARCH_RUN_JSON_INVALID",
                "Canonical research JSON is not valid JSON.",
            ) from error
        if (
            not isinstance(decoded, Mapping)
            or decoded.get("run_id") != research_run_id
            or decoded.get("schema_version") != row["engine_schema_version"]
        ):
            raise PersistenceError(
                "RESEARCH_RUN_JSON_IDENTITY_MISMATCH",
                "Canonical research JSON identity does not match its database record.",
            )
        return decoded

    def publish_manifest(self, role: str, producer_type: str, producer_id: str, members: Iterable[tuple[str, str, str]]) -> str:
        members_tuple = tuple(members)
        identity = [{"artifact_id": artifact_id, "role": member_role, "direction": direction} for artifact_id, member_role, direction in members_tuple]
        membership_hash = canonical_hash(identity)
        manifest_id = f"manifest_{canonical_hash({'role': role, 'producer_type': producer_type, 'producer_id': producer_id, 'members': identity})[:24]}"
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO artifact_manifest(artifact_manifest_id,manifest_role,producer_type,producer_id,membership_hash,created_at,member_count) VALUES(?,?,?,?,?,?,?)", (manifest_id, role, producer_type, producer_id, membership_hash, _now(), len(members_tuple)))
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
            self.connection.execute("INSERT INTO workflow_node_run(workflow_node_run_id,workflow_run_id,node_id,node_version,input_fingerprint,status,checkpoint_manifest_id) VALUES(?,?,?,?,?,?,?)", (node_run_id, workflow_run_id, node_id, node_version, fingerprint, "running", None))
            self.connection.execute("INSERT INTO workflow_node_attempt(workflow_node_attempt_id,workflow_node_run_id,attempt_no,disposition,started_at,completed_at,error_code,diagnostic_artifact_id) VALUES(?,?,?,?,?,?,?,?)", (attempt_id, node_run_id, 1, None, _now(), None, None, None))
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
        artifact_record_ids = tuple(
            row[0]
            for row in self.connection.execute(
                "SELECT r.artifact_record_id FROM artifact_manifest_member m "
                "JOIN research_artifact_record r USING(artifact_id) "
                "WHERE m.artifact_manifest_id=? ORDER BY m.member_order",
                (final_manifest[0],),
            )
        )
        return ResearchWorkflowResult(workflow_run_id, record["research_run_id"], record["research_snapshot_id"], workflow_snapshot[0] if workflow_snapshot else None, final_manifest[0], ReferenceDisposition(decision["disposition"]), decision["reason_code"], decision["stale_by_days"], record["canonical_json_artifact_id"], record["html_artifact_id"], artifact_record_ids)

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
        run_members: tuple[tuple[str, str, str], ...],
        projection_id: str,
        workflow_snapshot_id: str | None,
        reason_code: str,
        stale_by_days: int,
        candidate_member_ids: tuple[str, ...],
        market_only_member_ids: tuple[str, ...],
        terminal_status: str,
    ) -> str:
        del run_node_id, run_attempt_id, projection_id, workflow_snapshot_id
        member_by_role = {
            member_role: artifact_id
            for artifact_id, member_role, _ in run_members
        }
        json_artifact_id = member_by_role["research_run_json"]
        html_artifact_id = member_by_role["research_report_html"]
        identity = [{"artifact_id": artifact_id, "role": role, "direction": direction} for artifact_id, role, direction in run_members]
        final_manifest = f"manifest_{canonical_hash({'role': 'workflow_final', 'producer_type': 'WorkflowRun', 'producer_id': workflow_run_id, 'members': identity})[:24]}"
        completed_at = _now()
        with self.connection:
            if record_values is not None:
                self.connection.execute("INSERT INTO research_run_record VALUES(?,?,?,?,?,?,?,?,?,?,?)", record_values)
            for manifest_id, role, producer_type, producer_id in ((final_manifest, "workflow_final", "WorkflowRun", workflow_run_id),):
                self.connection.execute("INSERT OR IGNORE INTO artifact_manifest(artifact_manifest_id,manifest_role,producer_type,producer_id,membership_hash,created_at,member_count) VALUES(?,?,?,?,?,?,?)", (manifest_id, role, producer_type, producer_id, canonical_hash(identity), completed_at, len(run_members)))
                for member_index, (artifact_id, member_role, direction) in enumerate(run_members):
                    self.connection.execute("INSERT OR IGNORE INTO artifact_manifest_member VALUES(?,?,?,?,?)", (manifest_id, member_index, artifact_id, member_role, direction))
            self.connection.execute("UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? WHERE workflow_node_run_id=?", (final_manifest, final_node_id))
            self.connection.execute("UPDATE workflow_node_attempt SET disposition='succeeded',completed_at=? WHERE workflow_node_attempt_id=?", (completed_at, final_attempt_id))
            typed_refs = tuple(
                (
                    f"{self._artifact_member_role(row['artifact_kind'])}_artifact",
                    "ResearchArtifact",
                    row["artifact_record_id"],
                    row["disposition"],
                )
                for row in self.connection.execute(
                    "SELECT r.artifact_record_id,r.artifact_kind,u.disposition "
                    "FROM workflow_run_artifact_use u JOIN research_artifact_record r USING(artifact_record_id) "
                    "WHERE u.workflow_run_id=? ORDER BY r.rowid",
                    (workflow_run_id,),
                )
            )
            refs = (
                ("research_run", "ResearchRun", str(record["research_run_id"]), disposition.value),
                ("research_json", "Artifact", json_artifact_id, disposition.value),
                ("research_html", "Artifact", html_artifact_id, disposition.value),
                *typed_refs,
                ("final_manifest", "ArtifactManifest", final_manifest, "created"),
            )
            for ref_role, ref_type, ref_id, ref_disposition in refs:
                self.connection.execute("INSERT INTO workflow_run_ref VALUES(?,?,?,?,?)", (workflow_run_id, ref_role, ref_type, ref_id, ref_disposition))
            self.connection.execute("INSERT INTO research_reuse_decision VALUES(?,?,?,?,?,?,?,?,?)", (workflow_run_id, record["research_run_id"], disposition.value, "research_input_policy@1", reason_code, record["original_cutoff_date"], stale_by_days, json.dumps(list(candidate_member_ids)), json.dumps(list(market_only_member_ids))))
            sequence = self.connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
            self.connection.execute("UPDATE workflow_run SET status=?,completed_at=? WHERE workflow_run_id=?", (terminal_status, completed_at, workflow_run_id))
            self.connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", workflow_run_id, sequence, "running", terminal_status, "WORKFLOW_COMPLETED", completed_at))
        return final_manifest

    @staticmethod
    def _artifact_member_role(artifact_kind: str) -> str:
        return {
            "DataSnapshot": "data_snapshot",
            "Forecast": "forecast",
            "Valuation": "valuation",
            "Simulation": "simulation",
            "ForecastReview": "forecast_review",
        }[artifact_kind]
