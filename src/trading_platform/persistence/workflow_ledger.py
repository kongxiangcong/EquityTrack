from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

from trading_platform.domain.workflow import (
    ArtifactManifestView,
    ImmutableArtifactDraft,
    ReferenceDisposition,
    ResearchArtifactView,
    ResearchWorkflowResult,
    WorkflowHistory,
    NodeDefinition,
    WorkflowDefinition,
)
from trading_platform.domain.artifact_lineage import (
    ArtifactLineage,
    ArtifactSubmission,
    FrozenLineageEvidence,
    MarketCalibrationEvidence,
    ReviewFactEvidence,
    ReviewSnapshotEvidence,
    artifact_member_role,
)
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock, PersistenceError
from trading_platform.persistence.research_view_cutover import (
    ResearchDecisionViewCutover,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _durable_replace(source: Path, target: Path) -> None:
    if os.name == "nt":
        import ctypes

        move_file_ex = ctypes.windll.kernel32.MoveFileExW
        move_file_ex.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        move_file_ex.restype = ctypes.c_int
        if not move_file_ex(str(source), str(target), 0x1 | 0x8):
            raise ctypes.WinError()
    else:
        os.replace(source, target)
    if os.name != "nt":
        with target.open("rb") as stream:
            os.fsync(stream.fileno())
        descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class _PreparedResearchBundle:
    result: PreparedArtifactBundle
    published_by_record_id: Mapping[str, DurableObject]


def _research_record(row: Mapping[str, object]) -> ResearchRecord:
    return ResearchRecord(
        research_run_id=str(row["research_run_id"]),
        research_input_fingerprint=str(row["research_input_fingerprint"]),
        research_projection_id=str(row["research_projection_id"]),
        research_snapshot_id=str(row["research_snapshot_id"]),
        request_fingerprint=str(row["request_fingerprint"]),
        engine_schema_version=int(row["engine_schema_version"]),
        engine_code_identity=str(row["engine_code_identity"]),
        original_cutoff_date=str(row["original_cutoff_date"]),
        status=str(row["status"]),
        canonical_json_artifact_id=(
            None
            if row["canonical_json_artifact_id"] is None
            else str(row["canonical_json_artifact_id"])
        ),
        html_artifact_id=(
            None if row["html_artifact_id"] is None else str(row["html_artifact_id"])
        ),
    )


def _research_record_values(record: ResearchRecord) -> tuple[object, ...]:
    return (
        record.research_run_id,
        record.research_input_fingerprint,
        record.research_projection_id,
        record.research_snapshot_id,
        record.request_fingerprint,
        record.engine_schema_version,
        record.engine_code_identity,
        record.original_cutoff_date,
        record.status,
        record.canonical_json_artifact_id,
        record.html_artifact_id,
    )


# The application owns the command/query contract; this adapter only implements it.
from trading_platform.application.workflow_ledger import (
    AcquireLease,
    ArtifactBundlePreviewQuery,
    BeginNode,
    CheckpointMembersQuery,
    CheckpointMember,
    CheckpointQuery,
    CheckpointView,
    CommitResearchNode,
    CompletedResearch,
    CompletedResearchQuery,
    DurableObject,
    FailExecution,
    FinalizeResearchSuccess,
    ForecastReviewCommit,
    FreezeProjection,
    GenericObjectCommit,
    Heartbeat,
    IntegrityReport,
    IntegrityScope,
    LedgerLoadResult,
    NonterminalWorkflowQuery,
    ManifestQuery,
    MarkRetryable,
    NodeNameQuery,
    ObjectInventoryQuery,
    ObjectCommitResult,
    PersistenceCountsQuery,
    ProjectionCheckpointCommit,
    ProjectionCheckpointResult,
    ProjectionEvidence,
    ProjectionEvidenceQuery,
    ProjectionPreviewQuery,
    PreparedProjection,
    PreparedArtifactBundle,
    RequestCancellation,
    RequestPayloadQuery,
    ResearchArtifactQuery,
    ResearchArtifactBundle,
    ResearchPayloadQuery,
    ResearchDecisionMaterialization,
    ResearchDecisionViewMaterializerPort,
    DecisionViewPayload,
    DecisionViewPayloadQuery,
    ResearchViewCutoverCompleteQuery,
    ResearchRecord,
    ResearchRecordQuery,
    ResearchCheckpointResult,
    ResearchRunIdentity,
    ResearchRunIdentityQuery,
    SnapshotEvidence,
    SnapshotEvidenceQuery,
    StartDisposition,
    StartOutcome,
    StartWorkflow,
    StopIfCancelled,
    WorkflowHistoryQuery,
    WorkflowLedgerView,
    WorkflowPersistenceError,
    WorkflowReferencesQuery,
    WorkflowResultQuery,
    WorkflowRunQuery,
    WorkspaceWorkflowEvidence,
    WorkspaceWorkflowQuery,
)


class WorkflowLedger:
    def __init__(self, connection: sqlite3.Connection, data_root: Path, writer_lock: DataRootWriterLock) -> None:
        self.__connection = connection
        self.__data_root = data_root.resolve()
        self.__object_root = self.__data_root / "objects" / "sha256"
        self.__object_root.mkdir(parents=True, exist_ok=True)
        self.__writer_lock = writer_lock
        self.fault_injector = None
        self._research_artifact_lock = threading.RLock()

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    def start_or_replay(self, command: StartWorkflow) -> StartOutcome:
        definition_hash = canonical_hash(command.definition)
        request_hash = hashlib.sha256(command.request_payload).hexdigest()
        with self.__writer_lock.acquire(f"workflow:{command.invocation_id}"):
            existing = self._invocation_run(command.invocation_id)
            if existing is not None:
                self.__connection.execute("BEGIN IMMEDIATE")
                try:
                    if (
                        existing["request_fingerprint"] != command.request_fingerprint
                        or existing["workflow_id"] != command.definition.workflow_id
                        or existing["workflow_version"] != command.definition.version
                        or existing["definition_hash"] != definition_hash
                    ):
                        raise WorkflowPersistenceError(
                            "WORKFLOW_FINGERPRINT_MISMATCH",
                            "start_or_replay",
                            command.invocation_id,
                        )
                    if self._request_payload(existing["workflow_run_id"]) != command.request_payload:
                        raise WorkflowPersistenceError(
                            "WORKFLOW_REQUEST_INTEGRITY_FAILED",
                            "start_or_replay",
                            command.invocation_id,
                        )
                    self.__connection.commit()
                    return StartOutcome(existing["workflow_run_id"], StartDisposition.REPLAYED)
                except BaseException:
                    self.__connection.rollback()
                    raise
            published = self._publish_durable(command.request_payload)
            self._fault("workflow_start.object_published")
            self.__connection.execute("BEGIN IMMEDIATE")
            try:
                artifact_id = self._register_artifact(
                    published,
                    "application/json",
                    command.request_schema,
                )
                run_id = self._insert_started_run(command, artifact_id, request_hash)
                self._fault("workflow_start.before_commit")
                self.__connection.commit()
                return StartOutcome(run_id, StartDisposition.CREATED)
            except BaseException:
                self.__connection.rollback()
                raise

    def load(
        self,
        query: WorkflowRunQuery
        | ResearchRunIdentityQuery
        | WorkflowReferencesQuery
        | CompletedResearchQuery
        | ResearchRecordQuery
        | NodeNameQuery
        | SnapshotEvidenceQuery
        | ProjectionEvidenceQuery
        | WorkspaceWorkflowQuery
        | RequestPayloadQuery
        | CheckpointQuery
        | CheckpointMembersQuery
        | WorkflowResultQuery
        | WorkflowHistoryQuery
        | ManifestQuery
        | ResearchArtifactQuery
        | ResearchPayloadQuery
        | NonterminalWorkflowQuery
        | ObjectInventoryQuery
        | PersistenceCountsQuery
        | ArtifactBundlePreviewQuery,
    ) -> LedgerLoadResult:
        if isinstance(query, ProjectionPreviewQuery):
            return self._projection_plan(query.freeze)[0]
        if isinstance(query, ArtifactBundlePreviewQuery):
            return self._preview_artifact_bundle(query.bundle)
        if isinstance(query, NonterminalWorkflowQuery):
            table = self.__connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_run'"
            ).fetchone()
            return bool(
                table
                and self.__connection.execute(
                    "SELECT 1 FROM workflow_run WHERE status IN ('queued','running') LIMIT 1"
                ).fetchone()
            )
        if isinstance(query, ObjectInventoryQuery):
            return tuple(
                DurableObject(row["sha256"], row["size_bytes"], row["relative_path"])
                for row in self.__connection.execute(
                    "SELECT sha256,size_bytes,relative_path FROM object_blob ORDER BY sha256"
                )
            )
        if isinstance(query, PersistenceCountsQuery):
            return {
                "object_count": self.__connection.execute(
                    "SELECT count(*) FROM object_blob"
                ).fetchone()[0],
                "manifest_count": self.__connection.execute(
                    "SELECT count(*) FROM artifact_manifest"
                ).fetchone()[0],
            }
        if isinstance(query, RequestPayloadQuery):
            return self._request_payload(query.workflow_run_id)
        if isinstance(query, CheckpointQuery):
            checkpoint = self._validate_checkpoint(
                query.workflow_run_id, query.definition, query.fingerprint
            )
            return (
                None
                if checkpoint is None
                else CheckpointView(str(checkpoint["workflow_node_run_id"]))
            )
        if isinstance(query, CheckpointMembersQuery):
            return tuple(
                CheckpointMember(
                    str(row["artifact_id"]),
                    str(row["member_role"]),
                    str(row["direction"]),
                    str(row["schema_version"]),
                )
                for row in self._checkpoint_members(query.workflow_node_run_id)
            )
        if isinstance(query, WorkflowResultQuery):
            return self._result(query.workflow_run_id)
        if isinstance(query, WorkflowHistoryQuery):
            return self._history(query.workflow_run_id)
        if isinstance(query, ManifestQuery):
            return self._manifest(query.artifact_manifest_id)
        if isinstance(query, ResearchArtifactQuery):
            return self._research_artifact_view(query.artifact_record_id)
        if isinstance(query, ResearchPayloadQuery):
            return self._research_run_payload(query.research_run_id)
        if isinstance(query, DecisionViewPayloadQuery):
            return self._decision_view_payload(query.workflow_run_id)
        if isinstance(query, ResearchViewCutoverCompleteQuery):
            return self._research_view_cutover_complete()
        if isinstance(query, ResearchRunIdentityQuery):
            identity = self.__connection.execute(
                "SELECT engine_code_identity FROM research_run_record WHERE research_run_id=?",
                (query.research_run_id,),
            ).fetchone()
            if identity is None:
                raise WorkflowPersistenceError(
                    "RESEARCH_RUN_NOT_FOUND", "load", query.research_run_id
                )
            return ResearchRunIdentity(query.research_run_id, identity[0])
        if isinstance(query, WorkflowReferencesQuery):
            return {
                row["ref_role"]: row["ref_id"]
                for row in self.__connection.execute(
                    "SELECT ref_role,ref_id FROM workflow_run_ref WHERE workflow_run_id=?",
                    (query.workflow_run_id,),
                )
            }
        if isinstance(query, CompletedResearchQuery):
            members = self._checkpoint_members(query.workflow_node_run_id)
            by_role = {row["member_role"]: row["artifact_id"] for row in members}
            record = self.__connection.execute(
                "SELECT * FROM research_run_record WHERE canonical_json_artifact_id=?",
                (by_role["research_run_json"],),
            ).fetchone()
            if record is None:
                placeholders = ",".join("?" for _ in members)
                record = self.__connection.execute(
                    "SELECT DISTINCT r.* FROM research_run_record r JOIN research_artifact_record a ON a.research_run_id=r.research_run_id WHERE a.artifact_id IN ("
                    + placeholders
                    + ")",
                    tuple(row["artifact_id"] for row in members),
                ).fetchone()
            attempt = self.__connection.execute(
                "SELECT workflow_node_attempt_id,disposition FROM workflow_node_attempt WHERE workflow_node_run_id=? ORDER BY attempt_no DESC LIMIT 1",
                (query.workflow_node_run_id,),
            ).fetchone()
            if record is None or attempt is None:
                raise WorkflowPersistenceError(
                    "CHECKPOINT_INTEGRITY_FAILED", "load", query.workflow_node_run_id
                )
            return CompletedResearch(
                record=_research_record(record),
                disposition=(ReferenceDisposition.REUSED if attempt["disposition"] == "reused" else ReferenceDisposition.CREATED),
                members=tuple((row["artifact_id"], row["member_role"], row["direction"]) for row in members),
                workflow_node_attempt_id=attempt["workflow_node_attempt_id"],
            )
        if isinstance(query, ResearchRecordQuery):
            if query.research_run_id is not None:
                row = self.__connection.execute(
                    "SELECT * FROM research_run_record WHERE research_run_id=?",
                    (query.research_run_id,),
                ).fetchone()
            else:
                row = self.__connection.execute(
                    "SELECT * FROM research_run_record WHERE research_input_fingerprint=? AND engine_code_identity=?",
                    (query.research_input_fingerprint, query.engine_code_identity),
                ).fetchone()
            return None if row is None else _research_record(row)
        if isinstance(query, NodeNameQuery):
            row = self.__connection.execute(
                "SELECT node_id FROM workflow_node_run WHERE workflow_node_run_id=?",
                (query.workflow_node_run_id,),
            ).fetchone()
            if row is None:
                raise WorkflowPersistenceError("WORKFLOW_NODE_NOT_FOUND", "load", query.workflow_node_run_id)
            return row[0]
        if isinstance(query, SnapshotEvidenceQuery):
            snapshot = self.__connection.execute(
                "SELECT snapshot_purpose,quality_status,coverage_expected,coverage_eligible,coverage_excluded,coverage_missing FROM data_snapshot WHERE data_snapshot_id=?",
                (query.data_snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise WorkflowPersistenceError("WORKFLOW_SNAPSHOT_INVALID", "load", query.data_snapshot_id)
            rows = self.__connection.execute(
                "SELECT m.normalized_version_id,r.dataset FROM data_snapshot_member m JOIN normalized_version v USING(normalized_version_id) JOIN normalized_record r USING(normalized_record_id) WHERE m.data_snapshot_id=?",
                (query.data_snapshot_id,),
            ).fetchall()
            return SnapshotEvidence(
                purpose=str(snapshot["snapshot_purpose"]),
                members={row[0]: row[1] for row in rows},
                quality_status=str(snapshot["quality_status"]),
                coverage_expected=int(snapshot["coverage_expected"]),
                coverage_eligible=int(snapshot["coverage_eligible"]),
                coverage_excluded=int(snapshot["coverage_excluded"]),
                coverage_missing=int(snapshot["coverage_missing"]),
            )
        if isinstance(query, ProjectionEvidenceQuery):
            row = self.__connection.execute(
                "SELECT p.*,s.snapshot_purpose,s.freshness_status,s.quality_status FROM research_input_projection p JOIN data_snapshot s ON s.data_snapshot_id=p.research_snapshot_id WHERE p.research_projection_id=?",
                (query.research_projection_id,),
            ).fetchone()
            return None if row is None else ProjectionEvidence(
                research_projection_id=str(row["research_projection_id"]),
                research_snapshot_id=str(row["research_snapshot_id"]),
                projection_artifact_id=str(row["projection_artifact_id"]),
                research_input_fingerprint=str(row["research_input_fingerprint"]),
                security_id=str(row["security_id"]),
                as_of_date=str(row["as_of_date"]),
                snapshot_purpose=str(row["snapshot_purpose"]),
                freshness_status=str(row["freshness_status"]),
                quality_status=str(row["quality_status"]),
            )
        if isinstance(query, WorkspaceWorkflowQuery):
            workflows = [
                dict(row)
                for row in self.__connection.execute(
                    "SELECT w.workflow_run_id,w.status,w.requested_date,w.effective_session_date,w.created_at,w.completed_at,d.disposition AS research_disposition,d.reason_code AS research_reuse_reason,d.policy_version AS research_reuse_policy FROM workflow_run w LEFT JOIN research_reuse_decision d USING(workflow_run_id) WHERE EXISTS (SELECT 1 FROM workflow_run_ref r JOIN research_input_projection p ON p.research_projection_id=r.ref_id WHERE r.workflow_run_id=w.workflow_run_id AND r.ref_role='research_projection' AND p.security_id=?) ORDER BY w.created_at DESC",
                    (query.security_id,),
                )
            ]
            refs = self.__connection.execute(
                "SELECT r.workflow_run_id,r.ref_role,r.ref_type,r.ref_id,r.disposition FROM workflow_run_ref r WHERE EXISTS (SELECT 1 FROM workflow_run_ref scope_ref JOIN research_input_projection p ON p.research_projection_id=scope_ref.ref_id WHERE scope_ref.workflow_run_id=r.workflow_run_id AND scope_ref.ref_role='research_projection' AND p.security_id=?) ORDER BY r.workflow_run_id,r.ref_role",
                (query.security_id,),
            ).fetchall()
            by_run: dict[str, list[dict[str, object]]] = {}
            for row in refs:
                values = dict(row)
                by_run.setdefault(values.pop("workflow_run_id"), []).append(values)
            for workflow in workflows:
                workflow["refs"] = by_run.get(workflow["workflow_run_id"], [])
            manifests = [
                dict(row)
                for row in self.__connection.execute(
                    "SELECT DISTINCT m.artifact_manifest_id,m.manifest_role,m.producer_type,m.producer_id,m.membership_hash,m.created_at FROM artifact_manifest m JOIN workflow_run_ref r ON r.ref_type='ArtifactManifest' AND r.ref_id=m.artifact_manifest_id JOIN workflow_run w USING(workflow_run_id) JOIN research_reuse_decision d USING(workflow_run_id) JOIN research_run_record rr ON rr.research_run_id=d.research_run_id JOIN research_input_projection p ON p.research_projection_id=rr.research_projection_id WHERE p.security_id=? ORDER BY m.created_at",
                    (query.security_id,),
                )
            ]
            for manifest in manifests:
                manifest["members"] = [
                    dict(row)
                    for row in self.__connection.execute(
                        "SELECT member_order,artifact_id,member_role,direction FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order",
                        (manifest["artifact_manifest_id"],),
                    )
                ]
            research_runs = tuple(
                dict(row)
                for row in self.__connection.execute(
                    "SELECT r.research_run_id,r.research_snapshot_id,r.original_cutoff_date,r.status,r.engine_schema_version,r.engine_code_identity,r.canonical_json_artifact_id,r.html_artifact_id FROM research_run_record r JOIN research_input_projection p ON p.research_projection_id=r.research_projection_id WHERE p.security_id=? ORDER BY r.original_cutoff_date",
                    (query.security_id,),
                )
            )
            artifact_uses = tuple(
                dict(row)
                for row in self.__connection.execute(
                    "SELECT u.workflow_run_id,w.created_at,d.research_run_id,r.artifact_kind,r.artifact_record_id FROM workflow_run_artifact_use u JOIN workflow_run w USING(workflow_run_id) JOIN research_reuse_decision d USING(workflow_run_id) JOIN research_artifact_record r USING(artifact_record_id) WHERE r.platform_security_id=? ORDER BY w.created_at,r.rowid",
                    (query.security_id,),
                )
            )
            artifact_rows = self.__connection.execute(
                "SELECT artifact_record_id,artifact_kind FROM research_artifact_record WHERE platform_security_id=? AND artifact_kind IN ('Forecast','ForecastReview') ORDER BY created_at,artifact_record_id",
                (query.security_id,),
            ).fetchall()
            return WorkspaceWorkflowEvidence(
                workflows=tuple(workflows),
                manifests=tuple(manifests),
                research_runs=research_runs,
                artifact_uses=artifact_uses,
                forecast_artifact_record_ids=tuple(row[0] for row in artifact_rows if row[1] == "Forecast"),
                forecast_review_artifact_record_ids=tuple(row[0] for row in artifact_rows if row[1] == "ForecastReview"),
            )
        workflow_run_id = query.workflow_run_id
        row = self.__connection.execute(
            "SELECT status FROM workflow_run WHERE workflow_run_id=?",
            (workflow_run_id,),
        ).fetchone()
        if row is None:
            raise WorkflowPersistenceError("WORKFLOW_NOT_FOUND", "load", workflow_run_id)
        return WorkflowLedgerView(
            workflow_run_id=workflow_run_id,
            status=row["status"],
            request_payload=self._request_payload(workflow_run_id),
        )

    def audit_integrity(self, scope: IntegrityScope) -> IntegrityReport:
        errors: list[str] = []
        if scope.workflow_run_id is not None:
            try:
                self.load(WorkflowRunQuery(scope.workflow_run_id))
            except (ValueError, WorkflowPersistenceError) as error:
                errors.append(getattr(error, "code", str(error)))
                return IntegrityReport(tuple(sorted(set(errors))))
        tables = {row[0] for row in self.__connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "artifact_manifest" in tables:
            for manifest in self.__connection.execute("SELECT * FROM artifact_manifest"):
                members = tuple(self.__connection.execute("SELECT artifact_id,member_role,direction FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order", (manifest["artifact_manifest_id"],)))
                identity = [{"artifact_id": row["artifact_id"], "role": row["member_role"], "direction": row["direction"]} for row in members]
                if manifest["member_count"] is not None and manifest["member_count"] != len(members):
                    errors.append("ARTIFACT_MANIFEST_INCOMPLETE")
                if canonical_hash(identity) != manifest["membership_hash"]:
                    errors.append("ARTIFACT_MANIFEST_HASH_MISMATCH")
        if "workflow_transition" in tables and self.__connection.execute("SELECT workflow_run_id FROM workflow_transition GROUP BY workflow_run_id HAVING min(sequence_no)!=1 OR max(sequence_no)!=count(*) LIMIT 1").fetchone():
            errors.append("WORKFLOW_HISTORY_NON_MONOTONIC")
        if "workflow_node_run" in tables:
            if self.__connection.execute("SELECT n.workflow_node_run_id FROM workflow_node_run n LEFT JOIN artifact_manifest m ON m.artifact_manifest_id=n.checkpoint_manifest_id WHERE n.status='succeeded' AND m.artifact_manifest_id IS NULL LIMIT 1").fetchone():
                errors.append("WORKFLOW_CHECKPOINT_MISSING")
            if self.__connection.execute("SELECT workflow_node_run_id FROM workflow_node_attempt GROUP BY workflow_node_run_id HAVING min(attempt_no)!=1 OR max(attempt_no)!=count(*) LIMIT 1").fetchone():
                errors.append("WORKFLOW_ATTEMPT_NON_MONOTONIC")
            ref_targets = {"Artifact": ("artifact", "artifact_id"), "ResearchArtifact": ("research_artifact_record", "artifact_record_id"), "ResearchRun": ("research_run_record", "research_run_id"), "DataSnapshot": ("data_snapshot", "data_snapshot_id"), "ResearchProjection": ("research_input_projection", "research_projection_id"), "ArtifactManifest": ("artifact_manifest", "artifact_manifest_id")}
            for ref in self.__connection.execute("SELECT ref_type,ref_id FROM workflow_run_ref"):
                target = ref_targets.get(ref["ref_type"])
                if target is None or self.__connection.execute(f"SELECT 1 FROM {target[0]} WHERE {target[1]}=?", (ref["ref_id"],)).fetchone() is None:
                    errors.append("WORKFLOW_REFERENCE_MISSING")
        for blob in self.__connection.execute("SELECT sha256,size_bytes,relative_path FROM object_blob"):
            relative = PurePosixPath(blob["relative_path"])
            expected = f"objects/sha256/{blob['sha256'][:2]}/{blob['sha256']}"
            path = self.__data_root / blob["relative_path"]
            if relative.is_absolute() or any(part in {"", ".", ".."} or ":" in part for part in relative.parts) or relative.as_posix() != expected:
                errors.append("OBJECT_PATH_INVALID")
            elif not path.is_file() or path.stat().st_size != blob["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != blob["sha256"]:
                errors.append("OBJECT_INTEGRITY_FAILED")
        return IntegrityReport(tuple(sorted(set(errors))))

    def record_transition(
        self,
        command: AcquireLease
        | Heartbeat
        | RequestCancellation
        | StopIfCancelled
        | BeginNode
        | MarkRetryable
        | FailExecution,
    ) -> tuple[str, str] | None:
        if isinstance(command, AcquireLease):
            return self._acquire_lease(command.workflow_run_id, command.owner_token, command.definition, command.lease_seconds)
        if isinstance(command, Heartbeat):
            return self._heartbeat(command.workflow_run_id, command.owner_token, command.lease_seconds)
        if isinstance(command, RequestCancellation):
            return self._request_cancel(command.workflow_run_id, command.reason)
        if isinstance(command, StopIfCancelled):
            return self._stop_if_cancelled(command.workflow_run_id)
        if isinstance(command, BeginNode):
            return self._begin_or_retry_node(command.workflow_run_id, command.definition, command.fingerprint, command.owner_token, command.lease_seconds)
        if isinstance(command, MarkRetryable):
            return self._mark_retryable(command)
        if isinstance(command, FailExecution):
            return self._fail_execution(command)
        raise TypeError("WORKFLOW_TRANSITION_TYPE_INVALID")

    def commit_artifacts(
        self, command: ForecastReviewCommit | GenericObjectCommit
    ) -> ObjectCommitResult | str:
        if isinstance(command, GenericObjectCommit):
            published = self._publish_durable(command.payload)
            with self.__writer_lock.acquire(f"object:{published.sha256}"):
                self.__connection.execute("BEGIN IMMEDIATE")
                try:
                    existed = self.__connection.execute(
                        "SELECT 1 FROM object_blob WHERE sha256=?",
                        (published.sha256,),
                    ).fetchone() is not None
                    self._fault("object.before_db_registration")
                    self.__connection.execute(
                        "INSERT OR IGNORE INTO object_blob VALUES(?,?,?)",
                        (published.sha256, published.size_bytes, published.relative_path),
                    )
                    self._fault("object.db_registered")
                    self.__connection.commit()
                except BaseException:
                    self.__connection.rollback()
                    raise
            return ObjectCommitResult(
                published.sha256,
                ReferenceDisposition.REUSED
                if existed
                else ReferenceDisposition.CREATED,
            )
        if isinstance(command, ForecastReviewCommit):
            return self._persist_forecast_review(
                draft=command.draft,
                parent_record_ids=command.parent_record_ids,
                code_identity=command.code_identity,
            )
        raise TypeError("WORKFLOW_ARTIFACT_COMMIT_TYPE_INVALID")

    def commit_checkpoint(
        self,
        command: CommitResearchNode
        | ProjectionCheckpointCommit,
    ) -> str | ProjectionCheckpointResult | ResearchCheckpointResult | None:
        if isinstance(command, CommitResearchNode):
            return self._commit_research_checkpoint(command)
        if isinstance(command, ProjectionCheckpointCommit):
            return self._commit_projection_checkpoint(command)
        raise TypeError("WORKFLOW_CHECKPOINT_TYPE_INVALID")

    def complete(self, command: FinalizeResearchSuccess) -> str:
        return self._finalize_research_success(
            command.workflow_run_id,
            command.owner_token,
            command.run_node_id,
            command.run_attempt_id,
            command.final_node_id,
            command.final_attempt_id,
            command.disposition,
            command.record,
            command.run_members,
            command.projection_id,
            command.workflow_snapshot_id,
            command.reason_code,
            command.stale_by_days,
            command.candidate_member_ids,
            command.market_only_member_ids,
            command.terminal_status,
        )

    def _insert_started_run(
        self, command: StartWorkflow, request_artifact_id: str, request_hash: str
    ) -> str:
        run_id = f"workflow_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        self.__connection.execute(
            "INSERT INTO workflow_run(workflow_run_id,invocation_id,workflow_id,workflow_version,request_fingerprint,requested_date,effective_session_date,status,created_at,completed_at,owner_token,lease_expires_at,heartbeat_at,definition_hash,cancellation_requested) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (run_id, command.invocation_id, command.definition.workflow_id, command.definition.version, command.request_fingerprint, command.requested_date, command.effective_session_date, "running", now.isoformat(), None, command.owner_token, (now + timedelta(seconds=command.lease_seconds)).isoformat(), now.isoformat(), canonical_hash(command.definition)),
        )
        self.__connection.execute(
            "INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)",
            (f"transition_{uuid.uuid4().hex}", run_id, 1, "queued", "running", "WORKFLOW_STARTED", now.isoformat()),
        )
        self.__connection.execute(
            "INSERT INTO workflow_run_request VALUES(?,?,?,?)",
            (run_id, request_artifact_id, request_hash, command.request_schema),
        )
        return run_id

    def _invocation_run(self, invocation_id: str) -> sqlite3.Row | None:
        return self.__connection.execute("SELECT * FROM workflow_run WHERE invocation_id=?", (invocation_id,)).fetchone()

    def _acquire_lease(self, workflow_run_id: str, owner_token: str, definition: WorkflowDefinition, lease_seconds: int) -> None:
        try:
            with self.__writer_lock.acquire(f"workflow-lease:{workflow_run_id}:{owner_token}"):
                row = self.__connection.execute("SELECT * FROM workflow_run WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
                if row is None:
                    raise KeyError(workflow_run_id)
                if row["definition_hash"] != canonical_hash(definition) or row["workflow_id"] != definition.workflow_id or row["workflow_version"] != definition.version:
                    raise ValueError("WORKFLOW_DEFINITION_MISMATCH")
                now = datetime.now(timezone.utc)
                lease_expired = row["lease_expires_at"] is None or datetime.fromisoformat(row["lease_expires_at"]) <= now
                if row["owner_token"] not in {None, owner_token} and not lease_expired:
                    raise ValueError("WORKFLOW_BUSY")
                if lease_expired:
                    running = self.__connection.execute("SELECT a.workflow_node_attempt_id,n.workflow_node_run_id FROM workflow_node_attempt a JOIN workflow_node_run n USING(workflow_node_run_id) WHERE n.workflow_run_id=? AND a.disposition IS NULL", (workflow_run_id,)).fetchall()
                    for attempt in running:
                        self.__connection.execute("UPDATE workflow_node_attempt SET disposition='abandoned',completed_at=?,retryable=1 WHERE workflow_node_attempt_id=?", (now.isoformat(), attempt["workflow_node_attempt_id"]))
                        self.__connection.execute("UPDATE workflow_node_run SET status='pending',owner_token=NULL,lease_expires_at=NULL,heartbeat_at=? WHERE workflow_node_run_id=? AND status='running'", (now.isoformat(), attempt["workflow_node_run_id"]))
                    self._recovery_event(workflow_run_id, "LEASE_TAKEOVER", owner_token, "EXPIRED_OWNER_ABANDONED", now.isoformat())
                self.__connection.execute("UPDATE workflow_run SET owner_token=?,lease_expires_at=?,heartbeat_at=? WHERE workflow_run_id=?", (owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat(), workflow_run_id))
                self._transition(workflow_run_id, "running", "running", "LEASE_ACQUIRED", now.isoformat())
                self.__connection.commit()
        except PersistenceError as error:
            if error.code == "RUNTIME_BUSY":
                raise ValueError("WORKFLOW_BUSY") from error
            raise

    def _heartbeat(self, workflow_run_id: str, owner_token: str, lease_seconds: int = 30) -> None:
        for retry in range(40):
            try:
                with self.__writer_lock.acquire(f"workflow-heartbeat:{workflow_run_id}:{owner_token}"):
                    now = datetime.now(timezone.utc)
                    expires = (now + timedelta(seconds=lease_seconds)).isoformat()
                    with self.__connection:
                        changed = self.__connection.execute("UPDATE workflow_run SET heartbeat_at=?,lease_expires_at=? WHERE workflow_run_id=? AND owner_token=? AND status='running'", (now.isoformat(), expires, workflow_run_id, owner_token)).rowcount
                        if changed != 1:
                            raise ValueError("WORKFLOW_LEASE_LOST")
                        self.__connection.execute("UPDATE workflow_node_run SET heartbeat_at=?,lease_expires_at=? WHERE workflow_run_id=? AND owner_token=? AND status='running'", (now.isoformat(), expires, workflow_run_id, owner_token))
                        self.__connection.execute("UPDATE workflow_node_attempt SET heartbeat_at=?,lease_expires_at=? WHERE owner_token=? AND disposition IS NULL AND workflow_node_run_id IN (SELECT workflow_node_run_id FROM workflow_node_run WHERE workflow_run_id=?)", (now.isoformat(), expires, owner_token, workflow_run_id))
                return
            except PersistenceError as error:
                if error.code != "RUNTIME_BUSY" or retry == 39:
                    raise
                time.sleep(0.05)

    def _request_cancel(self, workflow_run_id: str, reason: str) -> None:
        with self.__connection:
            changed = self.__connection.execute("UPDATE workflow_run SET cancellation_requested=1 WHERE workflow_run_id=? AND status='running'", (workflow_run_id,)).rowcount
            if changed != 1:
                raise ValueError("WORKFLOW_NOT_CANCELLABLE")
            self._recovery_event(workflow_run_id, "CANCELLATION_REQUESTED", None, reason, _now())

    def _stop_if_cancelled(self, workflow_run_id: str) -> None:
        row = self.__connection.execute("SELECT cancellation_requested,status FROM workflow_run WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
        if row and row["cancellation_requested"] and row["status"] == "running":
            now = _now()
            with self.__connection:
                self.__connection.execute("UPDATE workflow_run SET status='cancelled',completed_at=?,owner_token=NULL,lease_expires_at=NULL WHERE workflow_run_id=?", (now, workflow_run_id))
                self._transition(workflow_run_id, "running", "cancelled", "USER_CANCELLED", now)
            raise ValueError("WORKFLOW_CANCELLED")

    def _request_payload(self, workflow_run_id: str) -> bytes:
        row = self.__connection.execute("SELECT a.object_sha256,o.relative_path,r.request_hash FROM workflow_run_request r JOIN artifact a ON a.artifact_id=r.request_artifact_id JOIN object_blob o ON o.sha256=a.object_sha256 WHERE r.workflow_run_id=?", (workflow_run_id,)).fetchone()
        if row is None:
            raise ValueError("WORKFLOW_REQUEST_MISSING")
        path = self.__data_root / row["relative_path"]
        payload = path.read_bytes() if path.is_file() else b""
        if hashlib.sha256(payload).hexdigest() != row["request_hash"]:
            raise ValueError("WORKFLOW_REQUEST_INTEGRITY_FAILED")
        return payload

    def _node(self, workflow_run_id: str, node_id: str) -> sqlite3.Row | None:
        return self.__connection.execute("SELECT * FROM workflow_node_run WHERE workflow_run_id=? AND node_id=?", (workflow_run_id, node_id)).fetchone()

    def _begin_or_retry_node(self, workflow_run_id: str, definition: NodeDefinition, fingerprint: str, owner_token: str, lease_seconds: int = 30) -> tuple[str, str]:
        with self.__writer_lock.acquire(f"workflow-node:{workflow_run_id}"):
            self.__connection.execute("BEGIN IMMEDIATE")
            try:
                owner = self.__connection.execute(
                    "SELECT owner_token,status FROM workflow_run WHERE workflow_run_id=?",
                    (workflow_run_id,),
                ).fetchone()
                if owner is None or owner["status"] != "running" or owner["owner_token"] != owner_token:
                    raise WorkflowPersistenceError(
                        "WORKFLOW_LEASE_LOST", "record_transition", workflow_run_id
                    )
                node = self._node(workflow_run_id, definition.node_id)
                now = datetime.now(timezone.utc)
                if node is None:
                    node_id = f"node_{uuid.uuid4().hex}"
                    attempt_no = 1
                    self.__connection.execute("INSERT INTO workflow_node_run(workflow_node_run_id,workflow_run_id,node_id,node_version,input_fingerprint,status,checkpoint_manifest_id,input_schema,output_schema,owner_token,lease_expires_at,heartbeat_at) VALUES(?,?,?,?,?,'running',NULL,?,?,?,?,?)", (node_id, workflow_run_id, definition.node_id, definition.version, fingerprint, definition.input_schema, definition.output_schema, owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat()))
                else:
                    if node["node_version"] != definition.version or node["input_schema"] != definition.input_schema or node["output_schema"] != definition.output_schema:
                        raise WorkflowPersistenceError("WORKFLOW_DEFINITION_MISMATCH", "record_transition", workflow_run_id)
                    if node["input_fingerprint"] != fingerprint:
                        raise WorkflowPersistenceError("WORKFLOW_FINGERPRINT_MISMATCH", "record_transition", workflow_run_id)
                    if node["status"] == "succeeded":
                        raise WorkflowPersistenceError("WORKFLOW_NODE_ALREADY_SUCCEEDED", "record_transition", workflow_run_id)
                    node_id = node["workflow_node_run_id"]
                    attempt_no = self.__connection.execute("SELECT coalesce(max(attempt_no),0)+1 FROM workflow_node_attempt WHERE workflow_node_run_id=?", (node_id,)).fetchone()[0]
                    self.__connection.execute("UPDATE workflow_node_run SET status='running',owner_token=?,lease_expires_at=?,heartbeat_at=? WHERE workflow_node_run_id=?", (owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat(), node_id))
                attempt_id = f"node_attempt_{uuid.uuid4().hex}"
                self.__connection.execute("INSERT INTO workflow_node_attempt(workflow_node_attempt_id,workflow_node_run_id,attempt_no,disposition,started_at,completed_at,error_code,diagnostic_artifact_id,owner_token,lease_expires_at,heartbeat_at,retryable) VALUES(?,?,?,NULL,?,NULL,NULL,NULL,?,?,?,0)", (attempt_id, node_id, attempt_no, now.isoformat(), owner_token, (now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat()))
                self.__connection.commit()
                return node_id, attempt_id
            except BaseException:
                self.__connection.rollback()
                raise

    def _validate_checkpoint(self, workflow_run_id: str, definition: NodeDefinition, fingerprint: str) -> sqlite3.Row | None:
        node = self._node(workflow_run_id, definition.node_id)
        if node is None or node["status"] != "succeeded":
            return None
        if node["node_version"] != definition.version or node["input_schema"] != definition.input_schema or node["output_schema"] != definition.output_schema:
            raise ValueError("WORKFLOW_DEFINITION_MISMATCH")
        if node["input_fingerprint"] != fingerprint:
            raise ValueError("WORKFLOW_FINGERPRINT_MISMATCH")
        manifest = self.__connection.execute("SELECT * FROM artifact_manifest WHERE artifact_manifest_id=?", (node["checkpoint_manifest_id"],)).fetchone()
        members = self.__connection.execute("SELECT * FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order", (node["checkpoint_manifest_id"],)).fetchall()
        if manifest is None or manifest["member_count"] != len(members):
            raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
        identity = [{"artifact_id": item["artifact_id"], "role": item["member_role"], "direction": item["direction"]} for item in members]
        if canonical_hash(identity) != manifest["membership_hash"]:
            raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
        for item in members:
            artifact = self.__connection.execute("SELECT o.* FROM artifact a JOIN object_blob o ON o.sha256=a.object_sha256 WHERE a.artifact_id=?", (item["artifact_id"],)).fetchone()
            if artifact is None:
                raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
            path = self.__data_root / artifact["relative_path"]
            if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError("CHECKPOINT_INTEGRITY_FAILED")
        return node

    def _mark_retryable(self, command: MarkRetryable) -> None:
        with self.__writer_lock.acquire(f"workflow-retry:{command.workflow_run_id}"):
            self.__connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_mutation_owner(
                    command.workflow_run_id,
                    command.workflow_node_run_id,
                    command.workflow_node_attempt_id,
                    command.owner_token,
                    "record_transition",
                )
                attempt = self.__connection.execute(
                    "UPDATE workflow_node_attempt SET disposition='failed',completed_at=?,error_code=?,retryable=1 "
                    "WHERE workflow_node_attempt_id=? AND owner_token=? AND completed_at IS NULL",
                    (_now(), command.code, command.workflow_node_attempt_id, command.owner_token),
                )
                node = self.__connection.execute(
                    "UPDATE workflow_node_run SET status='pending' "
                    "WHERE workflow_node_run_id=? AND owner_token=? AND status='running'",
                    (command.workflow_node_run_id, command.owner_token),
                )
                if attempt.rowcount != 1 or node.rowcount != 1:
                    raise WorkflowPersistenceError(
                        "WORKFLOW_LEASE_LOST", "record_transition", command.workflow_run_id
                    )
                self.__connection.commit()
            except BaseException:
                self.__connection.rollback()
                raise

    def _assert_mutation_owner(
        self,
        workflow_run_id: str,
        node_run_id: str,
        attempt_id: str,
        owner_token: str,
        operation: str,
    ) -> None:
        row = self.__connection.execute(
            "SELECT w.status AS workflow_status,w.owner_token AS workflow_owner,"
            "n.status AS node_status,n.owner_token AS node_owner,"
            "a.owner_token AS attempt_owner,a.completed_at "
            "FROM workflow_run w JOIN workflow_node_run n USING(workflow_run_id) "
            "JOIN workflow_node_attempt a USING(workflow_node_run_id) "
            "WHERE w.workflow_run_id=? AND n.workflow_node_run_id=? "
            "AND a.workflow_node_attempt_id=?",
            (workflow_run_id, node_run_id, attempt_id),
        ).fetchone()
        if (
            row is None
            or row["workflow_status"] != "running"
            or row["node_status"] != "running"
            or row["completed_at"] is not None
            or row["workflow_owner"] != owner_token
            or row["node_owner"] != owner_token
            or row["attempt_owner"] != owner_token
        ):
            raise WorkflowPersistenceError(
                "WORKFLOW_LEASE_LOST", operation, workflow_run_id
            )

    def _commit_research_checkpoint(
        self, command: CommitResearchNode
    ) -> ResearchCheckpointResult:
        completed = _now()
        with self.__writer_lock.acquire(
            f"research-checkpoint:{command.workflow_run_id}"
        ):
            if (command.source_json_artifact is None) != (command.source_html_artifact is None):
                raise WorkflowPersistenceError(
                    "RESEARCH_PRESENTATION_INCOMPLETE",
                    "commit_checkpoint",
                    command.workflow_run_id,
                )
            published_source_json = (
                None
                if command.source_json_artifact is None
                else self._publish_durable(command.source_json_artifact.payload)
            )
            published_source_html = (
                None
                if command.source_html_artifact is None
                else self._publish_durable(command.source_html_artifact.payload)
            )
            published_decision_json = self._publish_durable(command.decision_json_artifact.payload)
            published_decision_html = self._publish_durable(command.decision_html_artifact.payload)
            bundle = command.artifact_bundle
            prepared_bundle = self._prepare_research_artifact_bundle(
                research_run_id=bundle.research_run_id,
                data_snapshot_id=bundle.data_snapshot_id,
                code_identity=bundle.code_identity,
                drafts=bundle.drafts,
                workflow_run_id=bundle.workflow_run_id,
                market_data_snapshot_id=bundle.market_data_snapshot_id,
                research_record=bundle.research_record,
                publish_objects=True,
            )
            self.__connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_mutation_owner(
                    command.workflow_run_id,
                    command.workflow_node_run_id,
                    command.workflow_node_attempt_id,
                    command.owner_token,
                    "commit_checkpoint",
                )
                if command.source_json_artifact is not None:
                    if published_source_json is None or published_source_html is None or command.source_html_artifact is None:
                        raise WorkflowPersistenceError(
                            "RESEARCH_PRESENTATION_INCOMPLETE",
                            "commit_checkpoint",
                            command.workflow_run_id,
                        )
                    source_json_artifact_id = self._register_artifact(
                        published_source_json,
                        command.source_json_artifact.media_type,
                        command.source_json_artifact.schema_version,
                    )
                    source_html_artifact_id = self._register_artifact(
                        published_source_html,
                        command.source_html_artifact.media_type,
                        command.source_html_artifact.schema_version,
                    )
                else:
                    if (
                        command.record.canonical_json_artifact_id is None
                        or command.record.html_artifact_id is None
                    ):
                        raise WorkflowPersistenceError(
                            "RESEARCH_PRESENTATION_INCOMPLETE",
                            "commit_checkpoint",
                            command.workflow_run_id,
                        )
                    source_json_artifact_id = command.record.canonical_json_artifact_id
                    source_html_artifact_id = command.record.html_artifact_id
                decision_json_artifact_id = self._register_artifact(
                    published_decision_json,
                    command.decision_json_artifact.media_type,
                    command.decision_json_artifact.schema_version,
                )
                decision_html_artifact_id = self._register_artifact(
                    published_decision_html,
                    command.decision_html_artifact.media_type,
                    command.decision_html_artifact.schema_version,
                )
                if command.new_record is not None:
                    record = replace(
                        command.new_record,
                        canonical_json_artifact_id=source_json_artifact_id,
                        html_artifact_id=source_html_artifact_id,
                    )
                    self.__connection.execute(
                        "INSERT OR IGNORE INTO research_run_record VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        _research_record_values(record),
                    )
                else:
                    record = command.record
                self._register_prepared_research_bundle(prepared_bundle)
                committed_bundle = prepared_bundle.result
                members = (
                    (
                        command.projection_artifact_id,
                        "research_projection",
                        "input",
                    ),
                    (source_json_artifact_id, "research_run_json", "output"),
                    (source_html_artifact_id, "research_source_identity_html", "output"),
                    (decision_json_artifact_id, "decision_view_json", "output"),
                    (decision_html_artifact_id, "decision_view_html", "output"),
                    *(
                        (artifact_id, member_role, "output")
                        for artifact_id, member_role in committed_bundle.members
                    ),
                )
                identity = [
                    {"artifact_id": artifact_id, "role": role, "direction": direction}
                    for artifact_id, role, direction in members
                ]
                manifest_id = "manifest_" + canonical_hash(
                    {
                        "role": "checkpoint",
                        "producer_type": "WorkflowNodeRun",
                        "producer_id": command.workflow_node_run_id,
                        "members": identity,
                    }
                )[:24]
                for artifact_record_id in committed_bundle.record_ids:
                    self.__connection.execute(
                        "INSERT OR IGNORE INTO workflow_run_artifact_use VALUES(?,?,?)",
                        (
                            command.workflow_run_id,
                            artifact_record_id,
                            "reused"
                            if command.disposition is ReferenceDisposition.REUSED
                            else "created",
                        ),
                    )
                self.__connection.execute(
                    "INSERT OR IGNORE INTO artifact_manifest(artifact_manifest_id,manifest_role,producer_type,producer_id,membership_hash,created_at,member_count) VALUES(?,?,?,?,?,?,?)",
                    (
                        manifest_id,
                        "checkpoint",
                        "WorkflowNodeRun",
                        command.workflow_node_run_id,
                        canonical_hash(identity),
                        completed,
                        len(members),
                    ),
                )
                for index, (artifact_id, role, direction) in enumerate(members):
                    self.__connection.execute(
                        "INSERT OR IGNORE INTO artifact_manifest_member VALUES(?,?,?,?,?)",
                        (manifest_id, index, artifact_id, role, direction),
                    )
                attempt_disposition = (
                    "reused"
                    if command.disposition is ReferenceDisposition.REUSED
                    else "succeeded"
                )
                node = self.__connection.execute(
                    "UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? "
                    "WHERE workflow_node_run_id=? AND owner_token=? AND status='running'",
                    (
                        manifest_id,
                        command.workflow_node_run_id,
                        command.owner_token,
                    ),
                )
                attempt = self.__connection.execute(
                    "UPDATE workflow_node_attempt SET disposition=?,completed_at=? "
                    "WHERE workflow_node_attempt_id=? AND owner_token=? AND completed_at IS NULL",
                    (
                        attempt_disposition,
                        completed,
                        command.workflow_node_attempt_id,
                        command.owner_token,
                    ),
                )
                if node.rowcount != 1 or attempt.rowcount != 1:
                    raise WorkflowPersistenceError(
                        "WORKFLOW_LEASE_LOST",
                        "commit_checkpoint",
                        command.workflow_run_id,
                    )
                self.__connection.commit()
                self._fault("research_artifact.after_commit")
            except BaseException:
                self.__connection.rollback()
                raise
        return ResearchCheckpointResult(manifest_id, record, members)

    def _checkpoint_members(self, node_run_id: str) -> tuple[sqlite3.Row, ...]:
        return tuple(self.__connection.execute("SELECT m.*,a.schema_version FROM workflow_node_run n JOIN artifact_manifest_member m ON m.artifact_manifest_id=n.checkpoint_manifest_id JOIN artifact a USING(artifact_id) WHERE n.workflow_node_run_id=? ORDER BY m.member_order", (node_run_id,)))

    def _transition(self, workflow_run_id: str, from_status: str, to_status: str, reason: str, occurred_at: str) -> None:
        sequence = self.__connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
        self.__connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", workflow_run_id, sequence, from_status, to_status, reason, occurred_at))

    def _recovery_event(self, workflow_run_id: str, event_type: str, owner_token: str | None, detail: str, occurred_at: str) -> None:
        sequence = self.__connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_recovery_event WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
        self.__connection.execute("INSERT INTO workflow_recovery_event VALUES(?,?,?,?,?,?,?)", (f"recovery_{uuid.uuid4().hex}", workflow_run_id, sequence, event_type, owner_token, detail, occurred_at))

    def _register_artifact(
        self, published: DurableObject, media_type: str, schema_version: str
    ) -> str:
        artifact_id = f"artifact_{canonical_hash({'sha256': published.sha256, 'media': media_type, 'schema': schema_version})[:24]}"
        self._fault("object.before_db_registration")
        self.__connection.execute(
            "INSERT OR IGNORE INTO object_blob VALUES(?,?,?)",
            (published.sha256, published.size_bytes, published.relative_path),
        )
        self.__connection.execute(
            "INSERT OR IGNORE INTO artifact VALUES(?,?,?,?)",
            (artifact_id, published.sha256, media_type, schema_version),
        )
        self._fault("object.db_registered")
        return artifact_id

    def _publish_durable(self, payload: bytes) -> DurableObject:
        digest = hashlib.sha256(payload).hexdigest()
        target = self.__object_root / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != len(payload) or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise PersistenceError("OBJECT_HASH_MISMATCH", "Existing content-addressed object is corrupt.")
        else:
            descriptor, temp_name = tempfile.mkstemp(prefix=f".{digest}.", dir=target.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._fault("object.temp_fsynced")
                temporary = Path(temp_name)
                if temporary.stat().st_size != len(payload) or hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                    raise PersistenceError("OBJECT_HASH_MISMATCH", "Temporary object hash mismatch.")
                _durable_replace(temporary, target)
                self._fault("object.renamed")
            finally:
                Path(temp_name).unlink(missing_ok=True)
        return DurableObject(
            sha256=digest,
            size_bytes=len(payload),
            relative_path=target.relative_to(self.__data_root).as_posix(),
        )

    def _preview_artifact_bundle(
        self, bundle: ResearchArtifactBundle
    ) -> PreparedArtifactBundle:
        with self._research_artifact_lock:
            return self._prepare_research_artifact_bundle(
                research_run_id=bundle.research_run_id,
                data_snapshot_id=bundle.data_snapshot_id,
                code_identity=bundle.code_identity,
                drafts=bundle.drafts,
                workflow_run_id=bundle.workflow_run_id,
                market_data_snapshot_id=bundle.market_data_snapshot_id,
                research_record=bundle.research_record,
            ).result

    def _persist_forecast_review(
        self,
        *,
        draft: ImmutableArtifactDraft,
        parent_record_ids: tuple[str, str, str],
        code_identity: str,
        _owns_writer: bool = False,
    ) -> str:
        if not _owns_writer:
            with self._research_artifact_lock:
                with self.__writer_lock.acquire(
                    f"forecast-review:{draft.content_hash}"
                ):
                    return self._persist_forecast_review(
                        draft=draft,
                        parent_record_ids=parent_record_ids,
                        code_identity=code_identity,
                        _owns_writer=True,
                    )
        parents = tuple(
            self._research_artifact_view(record_id)
            for record_id in parent_record_ids
        )
        research_run_id = parents[0].research_run_id
        data_snapshot_id = str(draft.payload.get("review_data_snapshot_id") or "")
        review_snapshot, review_facts = self._load_forecast_review_evidence(draft)
        validated = ArtifactLineage.validate(
            ArtifactSubmission(
                research_run_id=research_run_id,
                workflow_run_id=None,
                data_snapshot_id=data_snapshot_id,
                code_identity=code_identity,
                drafts=(draft,),
                artifact_mode="forecast_review",
                parent_record_ids=parent_record_ids,
            ),
            FrozenLineageEvidence(
                research_run_id=research_run_id,
                workflow_run_id=None,
                platform_security_id=parents[0].platform_security_id,
                subject_aliases=frozenset({parents[0].subject_id}),
                research_snapshot_id=data_snapshot_id,
                model_data_snapshot_identity=parents[0].model_data_snapshot_identity,
                original_cutoff_date=draft.as_of,
                engine_code_identity=code_identity,
                parent_artifacts=parents,
                review_snapshot=review_snapshot,
                review_facts=review_facts,
            ),
        )
        envelope = validated.envelopes[0]
        record_id = envelope.record_id
        payload = envelope.payload
        artifact_id = envelope.artifact_id
        published = self._publish_durable(payload)
        object_hash = published.sha256
        with self._research_artifact_lock:
            with nullcontext():
                self.__connection.execute("BEGIN IMMEDIATE")
                with self.__connection:
                    registered_artifact_id = self._register_artifact(
                        published, "application/json", draft.schema_version
                    )
                    if registered_artifact_id != artifact_id:
                        raise ValueError("RESEARCH_ARTIFACT_IDENTITY_COLLISION")
                    created_at = _now()
                    values = (
                        record_id,
                        draft.artifact_kind,
                        draft.schema_version,
                        artifact_id,
                        object_hash,
                        research_run_id,
                        data_snapshot_id,
                        parents[0].model_data_snapshot_identity,
                        parents[0].platform_security_id,
                        draft.subject_id,
                        draft.as_of,
                        draft.source_identity,
                        draft.content_hash,
                        draft.model_identity,
                        json.dumps(
                            list(draft.formula_identities),
                            separators=(",", ":"),
                        ),
                        code_identity,
                        draft.policy_identity,
                        draft.status,
                        draft.summary_json,
                        created_at,
                    )
                    self.__connection.execute(
                        "INSERT OR IGNORE INTO research_artifact_record "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        values,
                    )
                    existing = self.__connection.execute(
                        "SELECT artifact_kind,schema_version,artifact_id,"
                        "content_hash,research_run_id,data_snapshot_id,"
                        "model_data_snapshot_identity,platform_security_id,"
                        "subject_id,as_of_date,source_identity,input_fingerprint,"
                        "model_identity,formula_identities_json,code_identity,"
                        "policy_identity,status,summary_json "
                        "FROM research_artifact_record "
                        "WHERE artifact_record_id=?",
                        (record_id,),
                    ).fetchone()
                    if existing is None or tuple(existing) != values[1:-1]:
                        raise ValueError("RESEARCH_ARTIFACT_IDENTITY_COLLISION")
                    for parent_id in parent_record_ids:
                        self.__connection.execute(
                            "INSERT OR IGNORE INTO research_artifact_relation "
                            "VALUES(?,?,?)",
                            (parent_id, record_id, "depends_on"),
                        )
                    workflow_ids = tuple(
                        row[0]
                        for row in self.__connection.execute(
                            "SELECT workflow_run_id "
                            "FROM workflow_run_artifact_use "
                            "WHERE artifact_record_id=?",
                            (parents[-1].artifact_record_id,),
                        )
                    )
                    for workflow_run_id in workflow_ids:
                        self.__connection.execute(
                            "INSERT OR IGNORE INTO workflow_run_artifact_use "
                            "VALUES(?,?,?)",
                            (workflow_run_id, record_id, "created"),
                        )
                        parent_artifacts = tuple(
                            self.__connection.execute(
                                "SELECT artifact_id FROM "
                                "research_artifact_record "
                                "WHERE artifact_record_id=?",
                                (parent_id,),
                            ).fetchone()[0]
                            for parent_id in parent_record_ids
                        )
                        manifest_members = (
                            (parent_artifacts[0], "forecast", "input"),
                            (parent_artifacts[1], "valuation", "input"),
                            (parent_artifacts[2], "simulation", "input"),
                            (artifact_id, "forecast_review", "output"),
                        )
                        identity = [
                            {
                                "artifact_id": item[0],
                                "role": item[1],
                                "direction": item[2],
                            }
                            for item in manifest_members
                        ]
                        manifest_id = (
                            "manifest_"
                            + canonical_hash(
                                {
                                    "role": "forecast_review_append",
                                    "producer_type": "WorkflowRun",
                                    "producer_id": workflow_run_id,
                                    "members": identity,
                                }
                            )[:24]
                        )
                        self.__connection.execute(
                            "INSERT OR IGNORE INTO artifact_manifest("
                            "artifact_manifest_id,manifest_role,producer_type,"
                            "producer_id,membership_hash,created_at,member_count"
                            ") VALUES(?,?,?,?,?,?,?)",
                            (
                                manifest_id,
                                "forecast_review_append",
                                "WorkflowRun",
                                workflow_run_id,
                                canonical_hash(identity),
                                created_at,
                                len(manifest_members),
                            ),
                        )
                        for index, member in enumerate(manifest_members):
                            self.__connection.execute(
                                "INSERT OR IGNORE INTO "
                                "artifact_manifest_member VALUES(?,?,?,?,?)",
                                (manifest_id, index, *member),
                            )
                        self.__connection.execute(
                            "INSERT OR IGNORE INTO workflow_run_ref "
                            "VALUES(?,?,?,?,?)",
                            (
                                workflow_run_id,
                                "forecast_review_manifest",
                                "ArtifactManifest",
                                manifest_id,
                                "created",
                            ),
                        )
                        self.__connection.execute(
                            "INSERT OR IGNORE INTO workflow_run_ref "
                            "VALUES(?,?,?,?,?)",
                            (
                                workflow_run_id,
                                "forecast_review_snapshot",
                                "DataSnapshot",
                                data_snapshot_id,
                                "input",
                            ),
                        )
                    self._fault("forecast_review.before_commit")
        return record_id

    def _load_forecast_review_evidence(
        self,
        draft: ImmutableArtifactDraft,
    ) -> tuple[ReviewSnapshotEvidence | None, tuple[ReviewFactEvidence, ...]]:
        snapshot_id = str(draft.payload.get("review_data_snapshot_id") or "")
        snapshot = self.__connection.execute(
            "SELECT * FROM data_snapshot WHERE data_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        snapshot_evidence = None if snapshot is None else ReviewSnapshotEvidence(
            data_snapshot_id=snapshot_id,
            scope_id=str(snapshot["scope_id"]),
            snapshot_purpose=str(snapshot["snapshot_purpose"]),
            freshness_status=str(snapshot["freshness_status"]),
            quality_status=str(snapshot["quality_status"]),
            as_of_at=str(snapshot["as_of_at"]),
        )
        facts = []
        actual_evidence = draft.payload.get("actual_evidence")
        for evidence in actual_evidence if isinstance(actual_evidence, list) else ():
            if not isinstance(evidence, Mapping):
                continue
            row = self.__connection.execute(
                "SELECT nv.*,pa.source_identity,pa.source_authority,"
                "pa.status AS attempt_status,"
                "pa.retrieved_at AS attempt_retrieved_at "
                "FROM data_snapshot_member sm "
                "JOIN normalized_version nv USING(normalized_version_id) "
                "JOIN provider_attempt pa "
                "ON pa.attempt_id=nv.source_attempt_id "
                "WHERE sm.data_snapshot_id=? "
                "AND sm.normalized_version_id=?",
                (snapshot_id, evidence.get("normalized_version_id")),
            ).fetchone()
            if row is not None:
                facts.append(
                    ReviewFactEvidence(
                        normalized_version_id=str(row["normalized_version_id"]),
                        content_hash=str(row["content_hash"]),
                        source_identity=str(row["source_identity"]),
                        source_authority=str(row["source_authority"]),
                        attempt_status=str(row["attempt_status"]),
                        quality_status=str(row["quality_status"]),
                        retrieved_at=str(row["retrieved_at"]),
                        attempt_retrieved_at=str(row["attempt_retrieved_at"]),
                        published_at=None if row["published_at"] is None else str(row["published_at"]),
                        available_at=str(row["available_at"]),
                    )
                )
        return snapshot_evidence, tuple(facts)

    def _prepare_research_artifact_bundle(
        self,
        *,
        research_run_id: str,
        data_snapshot_id: str,
        code_identity: str,
        drafts: tuple[ImmutableArtifactDraft, ...],
        workflow_run_id: str | None = None,
        market_data_snapshot_id: str | None = None,
        research_record: ResearchRecord | None = None,
        publish_objects: bool = False,
    ) -> _PreparedResearchBundle:
        if not isinstance(drafts, tuple) or any(
            not isinstance(draft, ImmutableArtifactDraft) for draft in drafts
        ):
            raise ValueError("RESEARCH_ARTIFACT_BUNDLE_TYPE_INVALID")
        if not drafts:
            return _PreparedResearchBundle(
                PreparedArtifactBundle(record_ids=(), views=(), members=()), {}
            )
        kinds = tuple(draft.artifact_kind for draft in drafts)
        if len(kinds) != len(set(kinds)):
            raise ValueError("RESEARCH_ARTIFACT_KIND_DUPLICATE")
        seen: set[str] = set()
        for draft in drafts:
            if not set(draft.dependency_kinds).issubset(seen):
                raise ValueError("RESEARCH_ARTIFACT_DEPENDENCY_ORDER_INVALID")
            seen.add(draft.artifact_kind)
        run = self.__connection.execute(
            "SELECT * FROM research_run_record WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
        if run is None and research_record is not None:
            run = {
                "research_run_id": research_record.research_run_id,
                "research_input_fingerprint": research_record.research_input_fingerprint,
                "research_projection_id": research_record.research_projection_id,
                "research_snapshot_id": research_record.research_snapshot_id,
                "request_fingerprint": research_record.request_fingerprint,
                "engine_schema_version": research_record.engine_schema_version,
                "engine_code_identity": research_record.engine_code_identity,
                "original_cutoff_date": research_record.original_cutoff_date,
                "status": research_record.status,
                "canonical_json_artifact_id": research_record.canonical_json_artifact_id,
                "html_artifact_id": research_record.html_artifact_id,
            }
        snapshot = self.__connection.execute(
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
        by_kind = {draft.artifact_kind: draft for draft in drafts}
        data_snapshot_draft = by_kind.get("DataSnapshot")
        if data_snapshot_draft is None:
            raise ValueError("RESEARCH_ARTIFACT_DATA_SNAPSHOT_MISSING")
        model_data_snapshot_identity = data_snapshot_draft.source_identity
        market_data_draft = by_kind.get("MarketDataSnapshot")
        market_calibration = (
            None
            if market_data_draft is None
            else self._load_frozen_market_calibration(
                market_data_draft.payload,
                subject_aliases=subject_aliases,
                market_data_snapshot_id=market_data_snapshot_id,
                market_path=by_kind.get("MarketPathSimulation"),
            )
        )
        validated = ArtifactLineage.validate(
            ArtifactSubmission(
                research_run_id=research_run_id,
                workflow_run_id=workflow_run_id,
                data_snapshot_id=data_snapshot_id,
                code_identity=code_identity,
                drafts=drafts,
                market_data_snapshot_id=market_data_snapshot_id,
            ),
            FrozenLineageEvidence(
                research_run_id=research_run_id,
                workflow_run_id=workflow_run_id,
                platform_security_id=platform_security_id,
                subject_aliases=subject_aliases,
                research_snapshot_id=run["research_snapshot_id"],
                model_data_snapshot_identity=model_data_snapshot_identity,
                original_cutoff_date=run["original_cutoff_date"],
                engine_code_identity=run["engine_code_identity"],
                market_calibration=market_calibration,
            ),
        )
        result = PreparedArtifactBundle(
            record_ids=validated.record_ids,
            views=tuple(
                ResearchArtifactView(
                    artifact_record_id=envelope.record_id,
                    artifact_kind=envelope.draft.artifact_kind,
                    schema_version=envelope.draft.schema_version,
                    research_run_id=research_run_id,
                    data_snapshot_id=data_snapshot_id,
                    model_data_snapshot_identity=model_data_snapshot_identity,
                    platform_security_id=platform_security_id,
                    subject_id=envelope.draft.subject_id,
                    as_of=envelope.draft.as_of,
                    source_identity=envelope.draft.source_identity,
                    model_identity=envelope.draft.model_identity,
                    formula_identities=envelope.draft.formula_identities,
                    code_identity=code_identity,
                    policy_identity=envelope.draft.policy_identity,
                    status=envelope.draft.status,
                    content_hash=envelope.draft.content_hash,
                    dependency_record_ids=envelope.dependency_record_ids,
                    summary=envelope.draft.summary,
                    payload=envelope.draft.payload,
                )
                for envelope in validated.envelopes
            ),
            members=tuple(
                (envelope.artifact_id, artifact_member_role(envelope.draft.artifact_kind))
                for envelope in validated.envelopes
            ),
        )
        published_by_record_id = (
            {
                envelope.record_id: self._publish_durable(envelope.payload)
                for envelope in validated.envelopes
            }
            if publish_objects
            else {}
        )
        if publish_objects:
            self._fault("research_artifact.objects_published")
        return _PreparedResearchBundle(result, published_by_record_id)

    def _register_prepared_research_bundle(
        self, prepared: _PreparedResearchBundle
    ) -> None:
        created_at = _now()
        record_by_kind = {
            view.artifact_kind: view.artifact_record_id
            for view in prepared.result.views
        }
        for view in prepared.result.views:
                    published = prepared.published_by_record_id[view.artifact_record_id]
                    artifact_id = next(
                        artifact_id
                        for artifact_id, role in prepared.result.members
                        if role == artifact_member_role(view.artifact_kind)
                    )
                    registered_artifact_id = self._register_artifact(
                        published, "application/json", view.schema_version
                    )
                    if registered_artifact_id != artifact_id:
                        raise ValueError("RESEARCH_ARTIFACT_IDENTITY_COLLISION")
                    object_hash = published.sha256
                    values = (
                        view.artifact_record_id,
                        view.artifact_kind,
                        view.schema_version,
                        artifact_id,
                        object_hash,
                        view.research_run_id,
                        view.data_snapshot_id,
                        view.model_data_snapshot_identity,
                        view.platform_security_id,
                        view.subject_id,
                        view.as_of,
                        view.source_identity,
                        view.content_hash,
                        view.model_identity,
                        json.dumps(list(view.formula_identities), separators=(",", ":")),
                        view.code_identity,
                        view.policy_identity,
                        view.status,
                        json.dumps(view.summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        created_at,
                    )
                    self.__connection.execute(
                        "INSERT OR IGNORE INTO research_artifact_record VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        values,
                    )
                    existing = self.__connection.execute(
                        "SELECT artifact_kind,schema_version,artifact_id,content_hash,research_run_id,data_snapshot_id,model_data_snapshot_identity,platform_security_id,subject_id,as_of_date,source_identity,input_fingerprint,model_identity,formula_identities_json,code_identity,policy_identity,status,summary_json FROM research_artifact_record WHERE artifact_record_id=?",
                        (view.artifact_record_id,),
                    ).fetchone()
                    if existing is None or tuple(existing) != (
                        view.artifact_kind,
                        view.schema_version,
                        artifact_id,
                        object_hash,
                        view.research_run_id,
                        view.data_snapshot_id,
                        view.model_data_snapshot_identity,
                        view.platform_security_id,
                        view.subject_id,
                        view.as_of,
                        view.source_identity,
                        view.content_hash,
                        view.model_identity,
                        json.dumps(list(view.formula_identities), separators=(",", ":")),
                        view.code_identity,
                        view.policy_identity,
                        view.status,
                        json.dumps(view.summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    ):
                        raise ValueError("RESEARCH_ARTIFACT_IDENTITY_COLLISION")
        for view in prepared.result.views:
                    child_id = record_by_kind[view.artifact_kind]
                    for parent_id in view.dependency_record_ids:
                        self.__connection.execute(
                            "INSERT OR IGNORE INTO research_artifact_relation VALUES(?,?,?)",
                            (
                                parent_id,
                                child_id,
                                "depends_on",
                            ),
                        )
        self._fault("research_artifact.before_commit")


    def _load_frozen_market_calibration(
        self,
        payload: Mapping[str, object],
        *,
        subject_aliases: frozenset[str],
        market_data_snapshot_id: str | None,
        market_path: ImmutableArtifactDraft | None,
    ) -> MarketCalibrationEvidence | None:
        if market_data_snapshot_id is None or market_path is None:
            return None
        snapshot = self.__connection.execute(
            "SELECT * FROM data_snapshot WHERE data_snapshot_id=?",
            (market_data_snapshot_id,),
        ).fetchone()
        calendar_ids = tuple(payload.get("calendar_member_ids", ()))
        next_calendar_id = payload.get("next_session_calendar_member_id")
        series_ids = tuple(payload.get("series_member_ids", ()))
        adjustment_ids = tuple(payload.get("adjustment_member_ids", ()))
        corporate_action_ids = tuple(payload.get("corporate_action_member_ids", ()))
        member_ids = (
            *calendar_ids,
            next_calendar_id,
            *series_ids,
            *adjustment_ids,
            *corporate_action_ids,
        )
        members = ()
        if member_ids:
            placeholders = ",".join("?" for _ in member_ids)
            members = tuple(
                dict(row)
                for row in self.__connection.execute(
                    "SELECT m.normalized_version_id,nr.dataset,nv.event_at,"
                    "nv.available_at,nv.quality_status,pa.source_identity,"
                    "pa.source_authority,pa.retrieved_at "
                    "FROM data_snapshot_member m "
                    "JOIN normalized_version nv USING(normalized_version_id) "
                    "JOIN normalized_record nr USING(normalized_record_id) "
                    "JOIN provider_attempt pa ON pa.attempt_id=nv.source_attempt_id "
                    f"WHERE m.data_snapshot_id=? AND m.normalized_version_id IN ({placeholders})",
                    (market_data_snapshot_id, *member_ids),
                )
            )
        calendar_rows = ()
        if calendar_ids:
            calendar_rows = tuple(
                dict(row)
                for row in self.__connection.execute(
                    "SELECT nv.normalized_version_id,nv.event_at,ms.market,ms.session_date,ms.is_open,ms.calendar_version "
                    "FROM normalized_version nv JOIN market_session_version ms "
                    "ON ms.source_attempt_id=nv.source_attempt_id AND ms.session_date=nv.event_at "
                    f"WHERE nv.normalized_version_id IN ({','.join('?' for _ in calendar_ids)})",
                    calendar_ids,
                )
            )
        snapshot_calendar_rows = tuple(
            dict(row)
            for row in self.__connection.execute(
                "SELECT nv.normalized_version_id,ms.session_date FROM data_snapshot_member m "
                "JOIN normalized_version nv USING(normalized_version_id) "
                "JOIN normalized_record nr USING(normalized_record_id) "
                "JOIN market_session_version ms ON ms.source_attempt_id=nv.source_attempt_id AND ms.session_date=nv.event_at "
                "WHERE m.data_snapshot_id=? AND nr.dataset='trade_cal' AND ms.market=? "
                "AND ms.calendar_version=? AND ms.is_open=1 AND ms.session_date BETWEEN ? AND ?",
                (
                    market_data_snapshot_id,
                    payload.get("market"),
                    payload.get("trading_calendar_identity"),
                    payload.get("window_start"),
                    payload.get("window_end"),
                ),
            )
        )
        next_calendar_rows = tuple(
            dict(row)
            for row in self.__connection.execute(
                "SELECT nv.normalized_version_id,ms.market,ms.session_date,ms.is_open,ms.calendar_version "
                "FROM data_snapshot_member m JOIN normalized_version nv USING(normalized_version_id) "
                "JOIN market_session_version ms ON ms.source_attempt_id=nv.source_attempt_id AND ms.session_date=nv.event_at "
                "WHERE m.data_snapshot_id=? AND ms.market=? AND ms.calendar_version=? AND ms.is_open=1 "
                "AND ms.session_date>? AND ms.session_date<=?",
                (
                    market_data_snapshot_id,
                    payload.get("market"),
                    payload.get("trading_calendar_identity"),
                    payload.get("window_end"),
                    market_path.payload.get("starting_price_session"),
                ),
            )
        )
        known_open_rows = tuple(
            dict(row)
            for row in self.__connection.execute(
                "SELECT session_date,available_at FROM market_session_version "
                "WHERE market=? AND calendar_version=? AND is_open=1 AND session_date>? AND session_date<=?",
                (
                    payload.get("market"),
                    payload.get("trading_calendar_identity"),
                    payload.get("window_end"),
                    market_path.payload.get("starting_price_session"),
                ),
            )
        )
        series_rows = ()
        if series_ids:
            series_rows = tuple(
                dict(row)
                for row in self.__connection.execute(
                    "SELECT o.* FROM ohlcv_version o "
                    f"WHERE o.normalized_version_id IN ({','.join('?' for _ in series_ids)})",
                    series_ids,
                )
            )
        snapshot_series_rows = ()
        if subject_aliases:
            snapshot_series_rows = tuple(
                dict(row)
                for row in self.__connection.execute(
                    "SELECT o.normalized_version_id,o.session_date FROM data_snapshot_member m "
                    "JOIN normalized_version nv USING(normalized_version_id) "
                    "JOIN normalized_record nr USING(normalized_record_id) "
                    "JOIN ohlcv_version o USING(normalized_version_id) "
                    "WHERE m.data_snapshot_id=? AND nr.dataset='daily' AND o.security_id IN "
                    f"({','.join('?' for _ in subject_aliases)}) AND o.session_date BETWEEN ? AND ?",
                    (
                        market_data_snapshot_id,
                        *subject_aliases,
                        payload.get("window_start"),
                        payload.get("window_end"),
                    ),
                )
            )
        starting_row = self.__connection.execute(
            "SELECT nr.dataset,nv.available_at,nv.quality_status,pa.source_identity,pa.source_authority,o.* "
            "FROM data_snapshot_member m JOIN normalized_version nv USING(normalized_version_id) "
            "JOIN normalized_record nr USING(normalized_record_id) "
            "JOIN provider_attempt pa ON pa.attempt_id=nv.source_attempt_id "
            "JOIN ohlcv_version o USING(normalized_version_id) "
            "WHERE m.data_snapshot_id=? AND m.normalized_version_id=?",
            (market_data_snapshot_id, market_path.payload.get("starting_price_member_id")),
        ).fetchone()
        return MarketCalibrationEvidence(
            snapshot=None if snapshot is None else dict(snapshot),
            members=members,
            calendar_rows=calendar_rows,
            snapshot_calendar_rows=snapshot_calendar_rows,
            next_calendar_rows=next_calendar_rows,
            known_open_rows=known_open_rows,
            series_rows=series_rows,
            snapshot_series_rows=snapshot_series_rows,
            starting_row=None if starting_row is None else dict(starting_row),
        )


    def _platform_subject_aliases(
        self,
        platform_security_id: str,
        as_of: str,
    ) -> frozenset[str]:
        security = self.__connection.execute(
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
        for row in self.__connection.execute(
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

    def _research_artifact_view(self, artifact_record_id: str) -> ResearchArtifactView:
        row = self.__connection.execute(
            "SELECT r.*,a.object_sha256,o.size_bytes,o.relative_path "
            "FROM research_artifact_record r JOIN artifact a USING(artifact_id) "
            "JOIN object_blob o ON o.sha256=a.object_sha256 "
            "WHERE r.artifact_record_id=?",
            (artifact_record_id,),
        ).fetchone()
        if row is None:
            raise KeyError(artifact_record_id)
        path = self.__data_root / row["relative_path"]
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
            for item in self.__connection.execute(
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

    def _research_run_payload(self, research_run_id: str) -> Mapping[str, object]:
        row = self.__connection.execute(
            "SELECT a.object_sha256,o.size_bytes,o.relative_path,r.engine_schema_version "
            "FROM research_run_record r "
            "JOIN artifact a ON a.artifact_id=r.canonical_json_artifact_id "
            "JOIN object_blob o ON o.sha256=a.object_sha256 "
            "WHERE r.research_run_id=?",
            (research_run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(research_run_id)
        path = self.__data_root / row["relative_path"]
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
        source_identity = (
            isinstance(decoded, Mapping)
            and decoded.get("run_id") == research_run_id
            and decoded.get("schema_version") == row["engine_schema_version"]
        )
        if not source_identity:
            raise PersistenceError(
                "RESEARCH_RUN_JSON_IDENTITY_MISMATCH",
                "Canonical research JSON identity does not match its database record.",
            )
        return decoded

    def _research_view_persistence(self) -> ResearchDecisionViewCutover:
        return ResearchDecisionViewCutover(
            self.__connection,
            self.__data_root,
            self.__writer_lock,
            self._publish_durable,
            self._register_artifact,
            self._research_artifact_view,
            self._research_run_payload,
            self._fault,
        )

    def _decision_view_payload(self, workflow_run_id: str) -> DecisionViewPayload:
        return self._research_view_persistence().decision_payload(workflow_run_id)

    def _research_view_cutover_complete(self) -> bool:
        return self._research_view_persistence().complete()

    def cutover_research_decision_views(
        self,
        materializer: ResearchDecisionViewMaterializerPort,
        *,
        acquire_lock: bool = True,
    ) -> None:
        self._research_view_persistence().run(
            materializer, acquire_lock=acquire_lock
        )

    def _commit_projection_checkpoint(
        self, command: ProjectionCheckpointCommit
    ) -> ProjectionCheckpointResult:
        completed_at = _now()
        with self.__writer_lock.acquire(
            f"projection-checkpoint:{command.workflow_run_id}"
        ):
            projection, payload = self._projection_plan(command.freeze)
            published = (
                self._publish_durable(payload)
                if projection.disposition is ReferenceDisposition.CREATED
                else None
            )
            members = ((projection.projection_artifact_id, "research_projection", "output"),)
            identity = [
                {"artifact_id": artifact_id, "role": role, "direction": direction}
                for artifact_id, role, direction in members
            ]
            manifest_id = f"manifest_{canonical_hash({'role': 'checkpoint', 'producer_type': 'WorkflowNodeRun', 'producer_id': command.workflow_node_run_id, 'members': identity})[:24]}"
            self.__connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_mutation_owner(
                    command.workflow_run_id,
                    command.workflow_node_run_id,
                    command.workflow_node_attempt_id,
                    command.owner_token,
                    "commit_checkpoint",
                )
                if published is not None:
                    self._register_projection_plan(
                        command.freeze, projection, payload, published
                    )
                self.__connection.execute(
                    "INSERT OR IGNORE INTO artifact_manifest(artifact_manifest_id,manifest_role,producer_type,producer_id,membership_hash,created_at,member_count) VALUES(?,?,?,?,?,?,?)",
                    (manifest_id, "checkpoint", "WorkflowNodeRun", command.workflow_node_run_id, canonical_hash(identity), completed_at, 1),
                )
                self.__connection.execute(
                    "INSERT OR IGNORE INTO artifact_manifest_member VALUES(?,?,?,?,?)",
                    (manifest_id, 0, *members[0]),
                )
                attempt_disposition = "reused" if projection.disposition is ReferenceDisposition.REUSED else "succeeded"
                node = self.__connection.execute(
                    "UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? WHERE workflow_node_run_id=? AND owner_token=? AND status='running'",
                    (manifest_id, command.workflow_node_run_id, command.owner_token),
                )
                attempt = self.__connection.execute(
                    "UPDATE workflow_node_attempt SET disposition=?,completed_at=? WHERE workflow_node_attempt_id=? AND owner_token=? AND completed_at IS NULL",
                    (attempt_disposition, completed_at, command.workflow_node_attempt_id, command.owner_token),
                )
                if node.rowcount != 1 or attempt.rowcount != 1:
                    raise WorkflowPersistenceError(
                        "WORKFLOW_LEASE_LOST",
                        "commit_checkpoint",
                        command.workflow_run_id,
                    )
                refs = [
                    ("research_snapshot", "DataSnapshot", projection.research_snapshot_id, projection.disposition.value),
                    ("research_projection", "ResearchProjection", projection.research_projection_id, projection.disposition.value),
                ]
                if command.workflow_snapshot_id is not None:
                    refs.append(("workflow_snapshot", "DataSnapshot", command.workflow_snapshot_id, ReferenceDisposition.INPUT.value))
                for role, ref_type, ref_id, disposition in refs:
                    self.__connection.execute(
                        "INSERT OR IGNORE INTO workflow_run_ref VALUES(?,?,?,?,?)",
                        (command.workflow_run_id, role, ref_type, ref_id, disposition),
                    )
                self._fault("projection_checkpoint.before_commit")
                self.__connection.commit()
            except BaseException:
                self.__connection.rollback()
                raise
        return ProjectionCheckpointResult(manifest_id, projection)

    def _projection_plan(
        self, command: FreezeProjection
    ) -> tuple[PreparedProjection, bytes]:
        projection = command.projection
        payload = json.dumps({"manifest": projection.manifest, "estimates": projection.estimates, "research_inputs": projection.research_inputs.identity_payload(), "as_of_date": projection.as_of_date, "profile": projection.profile, "field_semantics": [item.__dict__ for item in projection.field_semantics], "diluted_share_identity": projection.diluted_share_identity, "net_debt_bridge_identity": projection.net_debt_bridge_identity, "source_manifest_validation_result": projection.source_manifest_validation_result, "source_manifest_path": projection.source_manifest_path}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        projection_hash = hashlib.sha256(payload).hexdigest()
        existing = self.__connection.execute("SELECT research_projection_id,research_snapshot_id,projection_artifact_id FROM research_input_projection WHERE projection_hash=?", (projection_hash,)).fetchone()
        if existing:
            return (
                PreparedProjection(
                    str(existing[0]),
                    str(existing[1]),
                    str(existing[2]),
                    ReferenceDisposition.REUSED,
                ),
                payload,
            )
        artifact_id = f"artifact_{canonical_hash({'sha256': projection_hash, 'media': 'application/json', 'schema': 'ResearchProjection@1'})[:24]}"
        version_id = f"version_{projection_hash[:24]}"
        snapshot_id = f"snapshot_{canonical_hash({'purpose': 'research', 'cutoff': projection.as_of_date, 'member': version_id, 'policy': 'research_input_policy@1'})[:24]}"
        return (
            PreparedProjection(
                f"projection_{projection_hash[:24]}",
                snapshot_id,
                artifact_id,
                ReferenceDisposition.CREATED,
            ),
            payload,
        )

    def _register_projection_plan(
        self,
        command: FreezeProjection,
        projection_plan: PreparedProjection,
        payload: bytes,
        published: DurableObject,
    ) -> None:
        projection = command.projection
        projection_hash = hashlib.sha256(payload).hexdigest()
        attempt_id = f"attempt_{projection_hash[:24]}"
        record_id = f"record_{canonical_hash({'dataset': 'research_input', 'security': command.security_id, 'as_of': projection.as_of_date})[:24]}"
        version_id = f"version_{projection_hash[:24]}"
        retrieved = _now()
        source_ids = sorted(
            str(source.get("source_id", ""))
            for source in projection.manifest.get("sources", ())
        )
        source_identity = "frozen-research-projection:" + hashlib.sha256(
            json.dumps(
                source_ids,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        published_at = max(item.published_at for item in projection.field_semantics)
        available_at = max(item.available_at for item in projection.field_semantics)
        source_retrieved_at = max(
            item.retrieved_at for item in projection.field_semantics
        )
        availability_basis = (
            "conservative_retrieval_time"
            if any(
                item.availability_basis == "conservative_retrieval_time"
                for item in projection.field_semantics
            )
            else "publisher_timestamp"
        )
        registered_artifact_id = self._register_artifact(
            published, "application/json", "ResearchProjection@1"
        )
        if registered_artifact_id != projection_plan.projection_artifact_id:
            raise WorkflowPersistenceError(
                "RESEARCH_PROJECTION_IDENTITY_COLLISION",
                "commit_checkpoint",
                projection_plan.research_projection_id,
            )
        self.__connection.execute(
            "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                attempt_id,
                projection_plan.research_projection_id,
                "frozen_projection",
                "projection@1",
                "research_input",
                source_identity,
                "imported",
                "urn:local:frozen-research-projection",
                json.dumps({"source_ids": source_ids}),
                "{}",
                "date",
                "terms_unknown",
                "complete",
                "created",
                published.sha256,
                retrieved,
                None,
                None,
                None,
                "not_applicable",
            ),
        )
        self.__connection.execute(
            "INSERT OR IGNORE INTO normalized_record VALUES(?,?,?)",
            (record_id, "research_input", f"{command.security_id}:{projection.as_of_date}"),
        )
        previous = self.__connection.execute(
            "SELECT normalized_version_id,revision_no FROM normalized_version "
            "WHERE normalized_record_id=? ORDER BY revision_no DESC LIMIT 1",
            (record_id,),
        ).fetchone()
        revision = 1 if previous is None else previous["revision_no"] + 1
        self.__connection.execute(
            "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version_id,
                record_id,
                revision,
                projection_hash,
                attempt_id,
                projection.as_of_date,
                published_at,
                "timestamp",
                available_at,
                availability_basis,
                source_retrieved_at,
                "warning",
                previous["normalized_version_id"] if previous else None,
            ),
        )
        self.__connection.execute(
            "INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                projection_plan.research_snapshot_id,
                command.security_id,
                "research",
                projection.as_of_date,
                projection.as_of_date,
                f"{projection.as_of_date}T23:59:59+00:00",
                "Asia/Shanghai",
                "not_applicable",
                "research-query@1",
                "research-source@1",
                "research-freshness@1",
                canonical_hash([version_id]),
                "valid",
                "warning",
                1,
                1,
                0,
                0,
                0,
                "frozen_research_projection",
                retrieved,
            ),
        )
        self.__connection.execute(
            "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
            (
                projection_plan.research_snapshot_id,
                version_id,
                "research_input_projection",
                0,
            ),
        )
        self.__connection.execute(
            "INSERT INTO research_input_projection VALUES(?,?,?,?,?,?,?,?)",
            (
                projection_plan.research_projection_id,
                command.security_id,
                projection.as_of_date,
                projection_plan.projection_artifact_id,
                projection_hash,
                command.projection_fingerprint,
                "research_input_policy@1",
                projection_plan.research_snapshot_id,
            ),
        )

    def _fail_execution(self, command: FailExecution) -> None:
        completed_at = _now()
        with self.__writer_lock.acquire(f"workflow-failure:{command.workflow_run_id}"):
            published_diagnostic = self._publish_durable(command.diagnostic.payload)
            self.__connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_mutation_owner(
                    command.workflow_run_id,
                    command.workflow_node_run_id,
                    command.workflow_node_attempt_id,
                    command.owner_token,
                    "record_transition",
                )
                diagnostic_artifact_id = self._register_artifact(
                    published_diagnostic,
                    command.diagnostic.media_type,
                    command.diagnostic.schema_version,
                )
                node = self.__connection.execute(
                    "UPDATE workflow_node_run SET status='failed' WHERE workflow_node_run_id=? AND owner_token=? AND status='running'",
                    (command.workflow_node_run_id, command.owner_token),
                )
                attempt = self.__connection.execute(
                    "UPDATE workflow_node_attempt SET disposition='failed',completed_at=?,error_code=?,diagnostic_artifact_id=? "
                    "WHERE workflow_node_attempt_id=? AND owner_token=? AND completed_at IS NULL",
                    (completed_at, command.error_code, diagnostic_artifact_id, command.workflow_node_attempt_id, command.owner_token),
                )
                workflow = self.__connection.execute(
                    "UPDATE workflow_run SET status='failed',completed_at=? WHERE workflow_run_id=? AND owner_token=? AND status='running'",
                    (completed_at, command.workflow_run_id, command.owner_token),
                )
                if node.rowcount != 1 or attempt.rowcount != 1 or workflow.rowcount != 1:
                    raise WorkflowPersistenceError("WORKFLOW_LEASE_LOST", "record_transition", command.workflow_run_id)
                sequence = self.__connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (command.workflow_run_id,)).fetchone()[0]
                self.__connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", command.workflow_run_id, sequence, "running", "failed", command.error_code, completed_at))
                self.__connection.commit()
            except BaseException:
                self.__connection.rollback()
                raise

    def _result(self, workflow_run_id: str) -> ResearchWorkflowResult:
        decision = self.__connection.execute("SELECT * FROM research_reuse_decision WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
        record = self.__connection.execute("SELECT * FROM research_run_record WHERE research_run_id=?", (decision["research_run_id"],)).fetchone()
        workflow_snapshot = self.__connection.execute("SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? AND ref_role='workflow_snapshot'", (workflow_run_id,)).fetchone()
        final_manifest = self.__connection.execute("SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? AND ref_role='final_manifest'", (workflow_run_id,)).fetchone()
        decision_manifest = self.__connection.execute("SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? AND ref_role='decision_view_manifest'", (workflow_run_id,)).fetchone()
        presentation_artifacts = {
            row["member_role"]: row["artifact_id"]
            for row in self.__connection.execute(
                "SELECT member_role,artifact_id "
                "FROM artifact_manifest_member "
                "WHERE artifact_manifest_id=? "
                "AND member_role IN "
                "('decision_view_json','decision_view_html')",
                (decision_manifest[0],),
            )
        }
        artifact_record_ids = tuple(
            row[0]
            for row in self.__connection.execute(
                "SELECT r.artifact_record_id FROM artifact_manifest_member m "
                "JOIN research_artifact_record r USING(artifact_id) "
                "WHERE m.artifact_manifest_id=? ORDER BY m.member_order",
                (final_manifest[0],),
            )
        )
        return ResearchWorkflowResult(workflow_run_id, record["research_run_id"], record["research_snapshot_id"], workflow_snapshot[0] if workflow_snapshot else None, decision_manifest[0], ReferenceDisposition(decision["disposition"]), decision["reason_code"], decision["stale_by_days"], presentation_artifacts["decision_view_json"], presentation_artifacts["decision_view_html"], artifact_record_ids)

    def _history(self, workflow_run_id: str) -> WorkflowHistory:
        run = self.__connection.execute("SELECT * FROM workflow_run WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
        refs = tuple(dict(row) for row in self.__connection.execute("SELECT ref_role,ref_type,ref_id,disposition FROM workflow_run_ref WHERE workflow_run_id=? ORDER BY ref_role,ref_id", (workflow_run_id,)))
        attempts = tuple(dict(row) for row in self.__connection.execute("SELECT n.node_id,n.node_version,a.attempt_no,a.disposition,a.error_code,a.diagnostic_artifact_id FROM workflow_node_run n JOIN workflow_node_attempt a USING(workflow_node_run_id) WHERE n.workflow_run_id=? ORDER BY n.rowid", (workflow_run_id,)))
        transitions = tuple(dict(row) for row in self.__connection.execute("SELECT sequence_no,from_status,to_status,reason_code,occurred_at FROM workflow_transition WHERE workflow_run_id=? ORDER BY sequence_no", (workflow_run_id,)))
        decision_row = self.__connection.execute("SELECT * FROM research_reuse_decision WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()
        decision = {} if decision_row is None else dict(decision_row)
        final_manifest = next((ref["ref_id"] for ref in refs if ref["ref_role"] == "decision_view_manifest"), None)
        return WorkflowHistory(workflow_run_id, run["status"], refs, attempts, transitions, decision, final_manifest)

    def _manifest(self, manifest_id: str) -> ArtifactManifestView:
        row = self.__connection.execute("SELECT * FROM artifact_manifest WHERE artifact_manifest_id=?", (manifest_id,)).fetchone()
        if row is None:
            raise KeyError(manifest_id)
        members = tuple(dict(member) for member in self.__connection.execute(
            "SELECT member_order,artifact_id,member_role,direction FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order",
            (manifest_id,),
        ))
        return ArtifactManifestView(row["artifact_manifest_id"], row["manifest_role"], row["producer_type"], row["producer_id"], row["membership_hash"], members)

    def _finalize_research_success(
        self,
        workflow_run_id: str,
        owner_token: str,
        run_node_id: str,
        run_attempt_id: str,
        final_node_id: str,
        final_attempt_id: str,
        disposition: ReferenceDisposition,
        record: ResearchRecord,
        run_members: tuple[tuple[str, str, str], ...],
        projection_id: str,
        workflow_snapshot_id: str | None,
        reason_code: str,
        stale_by_days: int,
        candidate_member_ids: tuple[str, ...],
        market_only_member_ids: tuple[str, ...],
        terminal_status: str,
    ) -> str:
        completed_at = _now()
        with self.__writer_lock.acquire(f"workflow-complete:{workflow_run_id}"):
            self.__connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_mutation_owner(
                    workflow_run_id,
                    final_node_id,
                    final_attempt_id,
                    owner_token,
                    "complete",
                )
                completed_run = self.__connection.execute(
                    "SELECT n.checkpoint_manifest_id,n.status,a.completed_at "
                    "FROM workflow_node_run n JOIN workflow_node_attempt a "
                    "USING(workflow_node_run_id) WHERE n.workflow_run_id=? "
                    "AND n.workflow_node_run_id=? AND a.workflow_node_attempt_id=?",
                    (workflow_run_id, run_node_id, run_attempt_id),
                ).fetchone()
                if (
                    completed_run is None
                    or completed_run["status"] != "succeeded"
                    or completed_run["completed_at"] is None
                    or completed_run["checkpoint_manifest_id"] is None
                ):
                    raise WorkflowPersistenceError(
                        "WORKFLOW_CHECKPOINT_INVALID", "complete", workflow_run_id
                    )
                committed_members = tuple(
                    (row["artifact_id"], row["member_role"], row["direction"])
                    for row in self.__connection.execute(
                        "SELECT artifact_id,member_role,direction FROM "
                        "artifact_manifest_member WHERE artifact_manifest_id=? "
                        "ORDER BY member_order",
                        (completed_run["checkpoint_manifest_id"],),
                    )
                )
                if committed_members != run_members:
                    raise WorkflowPersistenceError(
                        "WORKFLOW_CHECKPOINT_INVALID", "complete", workflow_run_id
                    )
                refs_by_role = {
                    row["ref_role"]: row["ref_id"]
                    for row in self.__connection.execute(
                        "SELECT ref_role,ref_id FROM workflow_run_ref "
                        "WHERE workflow_run_id=?",
                        (workflow_run_id,),
                    )
                }
                if refs_by_role.get("research_projection") != projection_id or (
                    workflow_snapshot_id is not None
                    and refs_by_role.get("workflow_snapshot") != workflow_snapshot_id
                ):
                    raise WorkflowPersistenceError(
                        "WORKFLOW_REFERENCE_INVALID", "complete", workflow_run_id
                    )
                member_by_role = {
                    member_role: artifact_id
                    for artifact_id, member_role, _ in committed_members
                }
                decision_members = (
                    (member_by_role["decision_view_json"], "decision_view_json", "output"),
                    (member_by_role["decision_view_html"], "decision_view_html", "output"),
                )
                identity = [
                    {"artifact_id": artifact_id, "role": role, "direction": direction}
                    for artifact_id, role, direction in committed_members
                ]
                final_manifest = f"manifest_{canonical_hash({'role': 'workflow_final', 'producer_type': 'WorkflowRun', 'producer_id': workflow_run_id, 'members': identity})[:24]}"
                decision_identity = [
                    {"artifact_id": artifact_id, "role": role, "direction": direction}
                    for artifact_id, role, direction in decision_members
                ]
                decision_manifest = f"manifest_{canonical_hash({'role': 'workflow_decision_view@1', 'producer_type': 'WorkflowRun', 'producer_id': workflow_run_id, 'members': decision_identity})[:24]}"
                persisted_record = self.__connection.execute(
                    "SELECT * FROM research_run_record WHERE research_run_id=?",
                    (record.research_run_id,),
                ).fetchone()
                if persisted_record is None:
                    raise WorkflowPersistenceError(
                        "RESEARCH_RUN_NOT_FOUND", "complete", workflow_run_id
                    )
                record = _research_record(persisted_record)
                self.__connection.execute("INSERT OR IGNORE INTO artifact_manifest(artifact_manifest_id,manifest_role,producer_type,producer_id,membership_hash,created_at,member_count) VALUES(?,?,?,?,?,?,?)", (final_manifest, "workflow_final", "WorkflowRun", workflow_run_id, canonical_hash(identity), completed_at, len(committed_members)))
                for member_index, (artifact_id, member_role, direction) in enumerate(committed_members):
                    self.__connection.execute("INSERT OR IGNORE INTO artifact_manifest_member VALUES(?,?,?,?,?)", (final_manifest, member_index, artifact_id, member_role, direction))
                self.__connection.execute("INSERT INTO artifact_manifest(artifact_manifest_id,manifest_role,producer_type,producer_id,membership_hash,created_at,member_count) VALUES(?,?,?,?,?,?,?)", (decision_manifest, "workflow_decision_view@1", "WorkflowRun", workflow_run_id, canonical_hash(decision_identity), completed_at, 2))
                for member_index, (artifact_id, member_role, direction) in enumerate(decision_members):
                    self.__connection.execute("INSERT INTO artifact_manifest_member VALUES(?,?,?,?,?)", (decision_manifest, member_index, artifact_id, member_role, direction))
                final_node = self.__connection.execute("UPDATE workflow_node_run SET status='succeeded',checkpoint_manifest_id=? WHERE workflow_node_run_id=? AND owner_token=? AND status='running'", (final_manifest, final_node_id, owner_token))
                final_attempt = self.__connection.execute("UPDATE workflow_node_attempt SET disposition='succeeded',completed_at=? WHERE workflow_node_attempt_id=? AND owner_token=? AND completed_at IS NULL", (completed_at, final_attempt_id, owner_token))
                if final_node.rowcount != 1 or final_attempt.rowcount != 1:
                    raise WorkflowPersistenceError("WORKFLOW_LEASE_LOST", "complete", workflow_run_id)
                typed_refs = tuple(
                    (
                        f"{artifact_member_role(row['artifact_kind'])}_artifact",
                        "ResearchArtifact",
                        row["artifact_record_id"],
                        row["disposition"],
                    )
                    for row in self.__connection.execute(
                        "SELECT r.artifact_record_id,r.artifact_kind,u.disposition "
                        "FROM workflow_run_artifact_use u JOIN research_artifact_record r USING(artifact_record_id) "
                        "WHERE u.workflow_run_id=? ORDER BY r.rowid",
                        (workflow_run_id,),
                    )
                )
                refs = (
                    ("research_run", "ResearchRun", record.research_run_id, disposition.value),
                    ("research_json", "Artifact", record.canonical_json_artifact_id, disposition.value),
                    ("research_source_identity_html", "Artifact", record.html_artifact_id, disposition.value),
                    *typed_refs,
                    ("decision_view_manifest", "ArtifactManifest", decision_manifest, "created"),
                    ("final_manifest", "ArtifactManifest", final_manifest, "created"),
                )
                for ref_role, ref_type, ref_id, ref_disposition in refs:
                    self.__connection.execute("INSERT INTO workflow_run_ref VALUES(?,?,?,?,?)", (workflow_run_id, ref_role, ref_type, ref_id, ref_disposition))
                self.__connection.execute("INSERT INTO research_reuse_decision VALUES(?,?,?,?,?,?,?,?,?)", (workflow_run_id, record.research_run_id, disposition.value, "research_input_policy@1", reason_code, record.original_cutoff_date, stale_by_days, json.dumps(list(candidate_member_ids)), json.dumps(list(market_only_member_ids))))
                sequence = self.__connection.execute("SELECT coalesce(max(sequence_no),0)+1 FROM workflow_transition WHERE workflow_run_id=?", (workflow_run_id,)).fetchone()[0]
                workflow = self.__connection.execute("UPDATE workflow_run SET status=?,completed_at=? WHERE workflow_run_id=? AND owner_token=? AND status='running'", (terminal_status, completed_at, workflow_run_id, owner_token))
                if workflow.rowcount != 1:
                    raise WorkflowPersistenceError("WORKFLOW_LEASE_LOST", "complete", workflow_run_id)
                self.__connection.execute("INSERT INTO workflow_transition VALUES(?,?,?,?,?,?,?)", (f"transition_{uuid.uuid4().hex}", workflow_run_id, sequence, "running", terminal_status, "WORKFLOW_COMPLETED", completed_at))
                self._fault("workflow_complete.before_commit")
                self.__connection.commit()
            except BaseException:
                self.__connection.rollback()
                raise
        return final_manifest
