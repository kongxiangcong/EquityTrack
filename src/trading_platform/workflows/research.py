from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Callable, Mapping

from trading_platform.application.contracts import CancelWorkflowCommand, ResumeWorkflowCommand
from trading_platform.domain.workflow import (
    ArtifactManifestView,
    FieldSemantics,
    ImmutableArtifactDraft,
    ReferenceDisposition,
    ResearchArtifactView,
    ResearchProjection,
    ResearchWorkflowRequest,
    ResearchWorkflowResult,
    WorkflowHistory,
)
from trading_platform.identity.code import build_code_identity
from trading_platform.research import ProjectionError, ResearchAdapter, SnapshotToResearchRequestAssembler

from .registry import RESEARCH_WORKFLOW, NodeDefinition
from .repository import WorkflowRepository


class WorkflowError(RuntimeError):
    def __init__(self, code: str, workflow_run_id: str) -> None:
        super().__init__(code)
        self.code = code
        self.workflow_run_id = workflow_run_id


def research_engine_identity(repo_root: Path) -> str:
    identity = build_code_identity(repo_root, {"workflow": f"{RESEARCH_WORKFLOW.workflow_id}@{RESEARCH_WORKFLOW.version}", "research_input_policy": SnapshotToResearchRequestAssembler.POLICY_VERSION})
    structured = asdict(identity)
    return json.dumps({name: structured[name] for name in ("source_hash", "lock_hash", "migration_hash", "workflow_hash", "package_build_hash", "model_policy_hash", "dependency_license_hash", "determinism_basis", "random_seed")}, sort_keys=True, separators=(",", ":"))


class ResearchWorkflowService:
    def __init__(self, repository: WorkflowRepository, adapter: ResearchAdapter, assembler: SnapshotToResearchRequestAssembler, repo_root: Path, fault_injector: Callable[[str], None] | None = None) -> None:
        self.repository = repository
        self.adapter = adapter
        self.assembler = assembler
        self.engine_identity = research_engine_identity(repo_root)
        self.fault_injector = fault_injector

    def _fault(self, boundary: str) -> None:
        if self.fault_injector:
            self.fault_injector(boundary)

    def run(self, request: ResearchWorkflowRequest) -> ResearchWorkflowResult:
        row = self.repository.invocation_run(request.invocation_id)
        if row is not None:
            request_fingerprint = self._hash({"workflow": f"{RESEARCH_WORKFLOW.workflow_id}@{RESEARCH_WORKFLOW.version}", "request": asdict(request)})
            if request_fingerprint != row["request_fingerprint"]:
                raise WorkflowError("INVOCATION_REQUEST_MISMATCH", row["workflow_run_id"])
            if row["status"] in {"succeeded", "succeeded_with_limits"}:
                return self.repository.result(row["workflow_run_id"])
            owner = f"owner-{uuid.uuid4().hex}"
            try:
                self.repository.acquire_lease(row["workflow_run_id"], owner, RESEARCH_WORKFLOW, 30)
            except ValueError as error:
                raise WorkflowError(str(error), row["workflow_run_id"]) from error
            return self._execute(row["workflow_run_id"], request, owner, acquire=False)
        payload = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        artifact = self.repository.publish_artifact(payload, "application/json", "ResearchWorkflowRequest@1")
        fingerprint = self._hash({"workflow": f"{RESEARCH_WORKFLOW.workflow_id}@{RESEARCH_WORKFLOW.version}", "request": asdict(request)})
        owner = f"owner-{uuid.uuid4().hex}"
        run_id = self.repository.start_recoverable(request.invocation_id, fingerprint, request.requested_date, request.effective_session_date, RESEARCH_WORKFLOW, owner, artifact, hashlib.sha256(payload).hexdigest())
        return self._execute(run_id, request, owner, acquire=False)

    def resume(self, command: ResumeWorkflowCommand) -> ResearchWorkflowResult:
        try:
            request = self._decode_request(self.repository.request_payload(command.workflow_run_id))
            self.repository.acquire_lease(command.workflow_run_id, command.owner_token, RESEARCH_WORKFLOW, command.lease_seconds)
            return self._execute(command.workflow_run_id, request, command.owner_token, acquire=False, lease_seconds=command.lease_seconds)
        except WorkflowError:
            raise
        except ValueError as error:
            raise WorkflowError(str(error), command.workflow_run_id) from error

    def cancel(self, command: CancelWorkflowCommand) -> None:
        self.repository.request_cancel(command.workflow_run_id, command.reason)

    def _execute(self, run_id: str, request: ResearchWorkflowRequest, owner: str, acquire: bool = False, lease_seconds: int = 30) -> ResearchWorkflowResult:
        del acquire
        try:
            self.repository.heartbeat(run_id, owner, lease_seconds)
            self.repository.stop_if_cancelled(run_id)
            projection_id, research_snapshot_id, projection_artifact, research_fingerprint = self._freeze(run_id, request, owner)
            self.repository.stop_if_cancelled(run_id)
            self.repository.heartbeat(run_id, owner, lease_seconds)
            record, disposition, run_members, run_node, run_attempt = self._research(run_id, request, owner, projection_id, research_snapshot_id, projection_artifact, research_fingerprint, lease_seconds)
            self.repository.stop_if_cancelled(run_id)
            self.repository.heartbeat(run_id, owner, lease_seconds)
            final_contract = self._node("publish_run_manifest")
            final_fp = self._hash({"node": asdict(final_contract), "run": record["research_run_id"], "members": run_members})
            completed = self.repository.validate_checkpoint(run_id, final_contract, final_fp)
            if completed is not None:
                return self.repository.result(run_id)
            final_node, final_attempt = self.repository.begin_or_retry_node(run_id, final_contract, final_fp, owner)
            self._fault("workflow.node_attempt_started:publish_run_manifest")
            stale = max(0, (date.fromisoformat(request.effective_session_date) - date.fromisoformat(record["original_cutoff_date"])).days)
            reason = "ROUTINE_MARKET_ONLY_INPUTS" if disposition is ReferenceDisposition.REUSED and request.market_only_member_ids else ("IDENTICAL_RESEARCH_INPUT" if disposition is ReferenceDisposition.REUSED else "RESEARCH_INPUT_CHANGED_OR_NEW")
            terminal = "succeeded" if record["status"] == "completed" else "succeeded_with_limits"
            self._fault("workflow.before_final_manifest_commit")
            self.repository.finalize_research_success(run_id, run_node, run_attempt, final_node, final_attempt, disposition, None, record, run_members, projection_id, request.workflow_snapshot_id, reason, stale, request.candidate_member_ids, request.market_only_member_ids, terminal)
            self._fault("workflow.final_manifest_committed")
            return self.repository.result(run_id)
        except WorkflowError:
            raise
        except ValueError as error:
            raise WorkflowError(str(error), run_id) from error

    def _freeze(self, run_id: str, request: ResearchWorkflowRequest, owner: str) -> tuple[str, str, str, str]:
        contract = self._node("freeze_research_projection")
        fp = self._hash({"node": asdict(contract), "input": asdict(request.projection)})
        completed = self.repository.validate_checkpoint(run_id, contract, fp)
        if completed is not None:
            research_fp = self.assembler.fingerprint(request.projection)
            refs = {row["ref_role"]: row["ref_id"] for row in self.repository.connection.execute("SELECT * FROM workflow_run_ref WHERE workflow_run_id=?", (run_id,))}
            member = self.repository.checkpoint_members(completed["workflow_node_run_id"])[0]
            self._validate_completed_projection_refs(request, refs, member["artifact_id"], research_fp)
            return refs["research_projection"], refs["research_snapshot"], member["artifact_id"], research_fp
        node, attempt = self.repository.begin_or_retry_node(run_id, contract, fp, owner)
        self._fault("workflow.node_attempt_started:freeze_research_projection")
        try:
            research_fp = self.assembler.fingerprint(request.projection)
            projection_id, snapshot_id, artifact, disposition = self.repository.freeze_projection(request.security_id, request.projection, research_fp)
            if request.workflow_snapshot_id:
                self._validate_workflow_snapshot(request.workflow_snapshot_id, snapshot_id)
                self._validate_snapshot_classification(request.workflow_snapshot_id, request.candidate_member_ids, request.market_only_member_ids, request.projection.context)
            manifest = self.repository.publish_manifest("checkpoint", "WorkflowNodeRun", node, ((artifact, "research_projection", "output"),))
            self._fault("workflow.before_node_success:freeze_research_projection")
            self.repository.finish_node(node, attempt, disposition, manifest)
            self.repository.add_ref(run_id, "research_snapshot", "DataSnapshot", snapshot_id, disposition)
            self.repository.add_ref(run_id, "research_projection", "ResearchProjection", projection_id, disposition)
            if request.workflow_snapshot_id:
                self.repository.add_ref(run_id, "workflow_snapshot", "DataSnapshot", request.workflow_snapshot_id, ReferenceDisposition.INPUT)
            self.repository.heartbeat(run_id, owner)
            self._fault("workflow.freeze_checkpoint_committed")
            return projection_id, snapshot_id, artifact, research_fp
        except (ProjectionError, ValueError) as error:
            self._fail_node(run_id, node, attempt, getattr(error, "code", "RESEARCH_PROJECTION_INVALID"))

    def _research(self, run_id: str, request: ResearchWorkflowRequest, owner: str, projection_id: str, snapshot_id: str, projection_artifact: str, research_fp: str, lease_seconds: int):
        contract = self._node("run_or_link_research")
        fp = self._hash({"workflow": f"{RESEARCH_WORKFLOW.workflow_id}@{RESEARCH_WORKFLOW.version}", "node": f"{contract.node_id}@{contract.version}", "research": research_fp, "policy": self.assembler.POLICY_VERSION, "code_identity": self.engine_identity, "analysis_artifacts": [item.content_hash for item in request.analysis_artifacts]})
        completed = self.repository.validate_checkpoint(run_id, contract, fp)
        if completed is not None:
            member_rows = self.repository.checkpoint_members(completed["workflow_node_run_id"])
            members = {r["member_role"]: r["artifact_id"] for r in member_rows}
            record = self.repository.connection.execute("SELECT * FROM research_run_record WHERE canonical_json_artifact_id=?", (members["research_run_json"],)).fetchone()
            attempt = self.repository.connection.execute("SELECT workflow_node_attempt_id FROM workflow_node_attempt WHERE workflow_node_run_id=? ORDER BY attempt_no DESC LIMIT 1", (completed["workflow_node_run_id"],)).fetchone()[0]
            decision = ReferenceDisposition.REUSED if self.repository.connection.execute("SELECT disposition FROM workflow_node_attempt WHERE workflow_node_attempt_id=?", (attempt,)).fetchone()[0] == "reused" else ReferenceDisposition.CREATED
            run_members = tuple(
                (row["artifact_id"], row["member_role"], row["direction"])
                for row in member_rows
            )
            return record, decision, run_members, completed["workflow_node_run_id"], attempt
        node, attempt = self.repository.begin_or_retry_node(run_id, contract, fp, owner)
        self._fault("workflow.node_attempt_started:run_or_link_research")
        record = self.repository.connection.execute("SELECT r.* FROM research_run_record r WHERE r.research_input_fingerprint=? AND r.engine_code_identity=?", (research_fp, self.engine_identity)).fetchone()
        values = None
        if record is None:
            retry_count = 0
            while True:
              try:
                assembled = self.assembler.assemble(request.projection)
                with self._periodic_heartbeat(run_id, owner, lease_seconds):
                    produced = self.adapter.run(assembled)
                self.repository.heartbeat(run_id, owner, lease_seconds)
                if not produced.html:
                    raise ValueError("RESEARCH_HTML_MISSING")
                json_artifact = self.repository.publish_artifact(json.dumps(produced.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(), "application/json", f"ResearchRun@{produced.schema_version}")
                html_artifact = self.repository.publish_artifact(produced.html.encode(), "text/html", "ResearchReportHtml@1")
                request_fp = self._hash({"manifest": assembled.manifest, "estimates": assembled.estimates, "context": assembled.context, "as_of_date": assembled.as_of_date, "profile": assembled.profile})
                values = (produced.run_id, research_fp, projection_id, snapshot_id, request_fp, produced.schema_version, self.engine_identity, assembled.as_of_date, produced.status, json_artifact, html_artifact)
                self.repository.persist_research_record(values)
                record = self.repository.connection.execute(
                    "SELECT * FROM research_run_record WHERE research_run_id=?",
                    (produced.run_id,),
                ).fetchone()
                disposition = ReferenceDisposition.CREATED
                values = None
                break
              except Exception as error:
                if self._is_retryable(error) and retry_count < 2:
                    self.repository.mark_retryable(node, attempt, self._retry_code(error))
                    retry_count += 1
                    node, attempt = self.repository.begin_or_retry_node(run_id, contract, fp, owner)
                    self._fault("workflow.node_attempt_started:run_or_link_research")
                    self._retry_delay(error, retry_count)
                    continue
                self._fail_node(run_id, node, attempt, "RESEARCH_ENGINE_FAILED")
        else:
            disposition = ReferenceDisposition.REUSED
            json_artifact, html_artifact = record["canonical_json_artifact_id"], record["html_artifact_id"]
        try:
            artifact_record_ids = self.repository.persist_research_artifact_bundle(
                research_run_id=record["research_run_id"],
                data_snapshot_id=snapshot_id,
                code_identity=self.engine_identity,
                drafts=request.analysis_artifacts,
                workflow_run_id=run_id,
            )
        except Exception:
            self._fail_node(
                run_id,
                node,
                attempt,
                "RESEARCH_ARTIFACT_PERSISTENCE_FAILED",
            )
        typed_members = tuple(
            (
                row["artifact_id"],
                self._artifact_member_role(row["artifact_kind"]),
                "output",
            )
            for record_id in artifact_record_ids
            for row in (
                self.repository.connection.execute(
                    "SELECT artifact_id,artifact_kind FROM research_artifact_record WHERE artifact_record_id=?",
                    (record_id,),
                ).fetchone(),
            )
        )
        run_members = (
            (projection_artifact, "research_projection", "input"),
            (json_artifact, "research_run_json", "output"),
            (html_artifact, "research_report_html", "output"),
            *typed_members,
        )
        self._fault("workflow.research_artifacts_persisted")
        self._fault("workflow.before_node_success:run_or_link_research")
        self.repository.commit_research_checkpoint(node, attempt, disposition, values, run_members)
        self._fault("workflow.research_checkpoint_committed")
        return record, disposition, run_members, node, attempt

    def _fail_node(self, run_id: str, node: str, attempt: str, code: str) -> None:
        node_name = self.repository.connection.execute("SELECT node_id FROM workflow_node_run WHERE workflow_node_run_id=?", (node,)).fetchone()[0]
        contract = self._node(node_name)
        if code not in contract.failure_codes:
            code = contract.failure_codes[0]
        diagnostic = self.repository.publish_artifact(json.dumps({"error_code": code}).encode(), "application/json", "WorkflowDiagnostic@1")
        self.repository.fail_node(node, attempt, code, diagnostic)
        self.repository.fail(run_id, code)
        raise WorkflowError(code, run_id)

    def get_history(self, workflow_run_id: str) -> WorkflowHistory: return self.repository.history(workflow_run_id)
    def get_manifest(self, manifest_id: str) -> ArtifactManifestView: return self.repository.manifest(manifest_id)
    def get_research_artifact(self, artifact_record_id: str) -> ResearchArtifactView: return self.repository.research_artifact_view(artifact_record_id)
    def get_research_run_payload(self, research_run_id: str) -> Mapping[str, object]: return self.repository.research_run_payload(research_run_id)
    @staticmethod
    def _artifact_member_role(artifact_kind: str) -> str:
        return {
            "DataSnapshot": "data_snapshot",
            "Forecast": "forecast",
            "Valuation": "valuation",
            "Simulation": "simulation",
            "ForecastReview": "forecast_review",
        }[artifact_kind]
    def _validate_workflow_snapshot(self, workflow_snapshot_id: str, research_snapshot_id: str) -> None:
        if workflow_snapshot_id == research_snapshot_id: raise ProjectionError("SNAPSHOT_PURPOSE_COLLISION", "snapshots differ")
        row = self.repository.connection.execute("SELECT snapshot_purpose FROM data_snapshot WHERE data_snapshot_id=?", (workflow_snapshot_id,)).fetchone()
        if row is None or row[0] not in {"workflow", "market"}: raise ProjectionError("WORKFLOW_SNAPSHOT_INVALID", "snapshot invalid")
    def _validate_snapshot_classification(self, snapshot_id: str, candidates: tuple[str, ...], market_only: tuple[str, ...], context: object) -> None:
        rows = self.repository.connection.execute("SELECT m.normalized_version_id,r.dataset FROM data_snapshot_member m JOIN normalized_version v USING(normalized_version_id) JOIN normalized_record r USING(normalized_record_id) WHERE m.data_snapshot_id=?", (snapshot_id,)).fetchall()
        actual = {r[0]: r[1] for r in rows}
        if set(candidates) != set(actual): raise ProjectionError("SNAPSHOT_CANDIDATE_CLASSIFICATION_INVALID", "candidate mismatch")
        market = {i for i, dataset in actual.items() if dataset in {"trade_cal", "market_universe", "daily"}}
        if set(market_only) != market: raise ProjectionError("SNAPSHOT_MARKET_CLASSIFICATION_INVALID", "market mismatch")
        declared = set(context.get("workflow_research_member_ids", ())) if isinstance(context, dict) else set()
        if set(actual) - market != declared: raise ProjectionError("RESEARCH_RELEVANT_SNAPSHOT_CHANGE", "relevant mismatch")
    def _validate_completed_projection_refs(self, request: ResearchWorkflowRequest, refs: dict[str, str], artifact_id: str, fingerprint: str) -> None:
        projection_id = refs.get("research_projection")
        snapshot_id = refs.get("research_snapshot")
        row = self.repository.connection.execute("SELECT p.*,s.snapshot_purpose,s.freshness_status,s.quality_status FROM research_input_projection p JOIN data_snapshot s ON s.data_snapshot_id=p.research_snapshot_id WHERE p.research_projection_id=?", (projection_id,)).fetchone()
        if row is None or row["research_snapshot_id"] != snapshot_id or row["projection_artifact_id"] != artifact_id or row["research_input_fingerprint"] != fingerprint:
            raise ValueError("WORKFLOW_DOMAIN_REFERENCE_INVALID")
        if row["security_id"] != request.security_id or row["as_of_date"] > request.effective_session_date or row["snapshot_purpose"] != "research":
            raise ValueError("WORKFLOW_PIT_INVARIANT_FAILED")
        if row["freshness_status"] != "valid" or row["quality_status"] == "blocking":
            raise ValueError("WORKFLOW_QUALITY_BLOCKED")
        if request.workflow_snapshot_id:
            self._validate_workflow_snapshot(request.workflow_snapshot_id, snapshot_id)
            self._validate_snapshot_classification(request.workflow_snapshot_id, request.candidate_member_ids, request.market_only_member_ids, request.projection.context)
    @staticmethod
    def _node(node_id: str) -> NodeDefinition: return next(n for n in RESEARCH_WORKFLOW.nodes if n.node_id == node_id)
    @staticmethod
    def _hash(value: object) -> str: return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        if isinstance(error, sqlite3.OperationalError) and any(token in str(error).lower() for token in ("busy", "locked")):
            return True
        status = getattr(error, "status_code", None)
        return status == 429 or (isinstance(status, int) and 500 <= status < 600) or isinstance(error, (TimeoutError, ConnectionError))
    @staticmethod
    def _retry_code(error: Exception) -> str:
        if isinstance(error, sqlite3.OperationalError):
            return "SQLITE_BUSY"
        if getattr(error, "status_code", None) == 429:
            return "RATE_LIMITED"
        return "TRANSIENT_NETWORK_FAILURE"
    @staticmethod
    def _retry_delay(error: Exception, retry_count: int) -> None:
        retry_after = getattr(error, "retry_after", None)
        if retry_after is None:
            headers = getattr(error, "headers", {}) or {}
            retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
        try:
            delay = float(retry_after) if retry_after is not None else 0.05 * (2 ** (retry_count - 1))
        except (TypeError, ValueError):
            delay = 0.05 * (2 ** (retry_count - 1))
        time.sleep(min(max(delay, 0.0), 1.0))
    @contextmanager
    def _periodic_heartbeat(self, run_id: str, owner: str, lease_seconds: int):
        stopped = threading.Event()
        failures: list[Exception] = []

        def renew() -> None:
            interval = max(0.1, lease_seconds / 3)
            while not stopped.wait(interval):
                try:
                    self.repository.heartbeat(run_id, owner, lease_seconds)
                except Exception as error:
                    failures.append(error)
                    return

        worker = threading.Thread(target=renew, name=f"workflow-heartbeat-{run_id}", daemon=True)
        worker.start()
        try:
            yield
        finally:
            stopped.set()
            worker.join(timeout=max(1.0, lease_seconds))
        if failures:
            raise failures[0]
    @staticmethod
    def _decode_request(payload: bytes) -> ResearchWorkflowRequest:
        return decode_research_workflow_request(payload)


def decode_research_workflow_request(payload: bytes) -> ResearchWorkflowRequest:
    raw = json.loads(payload)
    projection = raw["projection"]
    projection["field_semantics"] = tuple(FieldSemantics(**item) for item in projection["field_semantics"])
    raw["projection"] = ResearchProjection(**projection)
    raw["candidate_member_ids"] = tuple(raw.get("candidate_member_ids", ()))
    raw["market_only_member_ids"] = tuple(raw.get("market_only_member_ids", ()))
    raw["analysis_artifacts"] = tuple(
        ImmutableArtifactDraft.from_serialized(item)
        for item in raw.get("analysis_artifacts", ())
    )
    return ResearchWorkflowRequest(**raw)
