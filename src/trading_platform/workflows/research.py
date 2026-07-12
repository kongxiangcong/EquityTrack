from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from trading_platform.domain.workflow import ArtifactManifestView, ReferenceDisposition, ResearchWorkflowRequest, ResearchWorkflowResult, WorkflowHistory
from trading_platform.research import ProjectionError, ResearchAdapter, SnapshotToResearchRequestAssembler
from trading_platform.identity.code import build_code_identity

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
    def __init__(self, repository: WorkflowRepository, adapter: ResearchAdapter, assembler: SnapshotToResearchRequestAssembler, repo_root: Path) -> None:
        self.repository = repository
        self.adapter = adapter
        self.assembler = assembler
        self.engine_identity = research_engine_identity(repo_root)

    def run(self, request: ResearchWorkflowRequest) -> ResearchWorkflowResult:
        replay = self.repository.existing_result(request.invocation_id)
        if replay is not None:
            return replay
        raw_projection = asdict(request.projection)
        request_fingerprint = self._hash({"workflow": f"{RESEARCH_WORKFLOW.workflow_id}@{RESEARCH_WORKFLOW.version}", "request": asdict(request)})
        workflow_run_id = self.repository.start(request.invocation_id, request_fingerprint, request.requested_date, request.effective_session_date)
        freeze_contract = self._node("freeze_research_projection")
        freeze_node, freeze_attempt = self.repository.begin_node(workflow_run_id, freeze_contract.node_id, freeze_contract.version, self._hash({"node": asdict(freeze_contract), "input": raw_projection}))
        try:
            research_fingerprint = self.assembler.fingerprint(request.projection)
            projection_id, research_snapshot_id, projection_artifact_id, projection_disposition = self.repository.freeze_projection(request.security_id, request.projection, research_fingerprint)
            checkpoint = self.repository.publish_manifest("checkpoint", "WorkflowNodeRun", freeze_node, ((projection_artifact_id, "research_projection", "output"),))
            self.repository.finish_node(freeze_node, freeze_attempt, projection_disposition, checkpoint)
            self.repository.add_ref(workflow_run_id, "research_snapshot", "DataSnapshot", research_snapshot_id, projection_disposition)
            self.repository.add_ref(workflow_run_id, "research_projection", "ResearchProjection", projection_id, projection_disposition)
            if request.workflow_snapshot_id is not None:
                self._validate_workflow_snapshot(request.workflow_snapshot_id, research_snapshot_id)
                self._validate_snapshot_classification(request.workflow_snapshot_id, request.candidate_member_ids, request.market_only_member_ids, request.projection.context)
                self.repository.add_ref(workflow_run_id, "workflow_snapshot", "DataSnapshot", request.workflow_snapshot_id, ReferenceDisposition.INPUT)
        except (ProjectionError, ValueError) as error:
            self._fail_node(workflow_run_id, freeze_node, freeze_attempt, getattr(error, "code", "RESEARCH_PROJECTION_INVALID"), str(error))

        run_fingerprint = self._hash({"workflow": f"{RESEARCH_WORKFLOW.workflow_id}@{RESEARCH_WORKFLOW.version}", "node": "run_or_link_research@1", "research": research_fingerprint, "policy": self.assembler.POLICY_VERSION, "code_identity": self.engine_identity})
        run_contract = self._node("run_or_link_research")
        run_node, run_attempt = self.repository.begin_node(workflow_run_id, run_contract.node_id, run_contract.version, run_fingerprint)
        record = self.repository.connection.execute("""SELECT r.* FROM research_run_record r
            WHERE r.research_input_fingerprint=? AND r.engine_code_identity=?
              AND EXISTS (SELECT 1 FROM workflow_run_ref ref JOIN workflow_run w USING(workflow_run_id)
                          WHERE ref.ref_type='ResearchRun' AND ref.ref_id=r.research_run_id
                            AND w.status IN ('succeeded','succeeded_with_limits'))""", (research_fingerprint, self.engine_identity)).fetchone()
        record_values = None
        if record is None:
            try:
                research_request = self.assembler.assemble(request.projection)
                research_run = self.adapter.run(research_request)
                canonical_json = json.dumps(research_run.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
                if not research_run.html:
                    raise ValueError("RESEARCH_HTML_MISSING")
                json_artifact = self.repository.publish_artifact(canonical_json, "application/json", f"ResearchRun@{research_run.schema_version}")
                html_artifact = self.repository.publish_artifact(research_run.html.encode("utf-8"), "text/html", "ResearchReportHtml@1")
                research_request_fingerprint = self._hash({"manifest": research_request.manifest, "estimates": research_request.estimates, "context": research_request.context, "as_of_date": research_request.as_of_date, "profile": research_request.profile})
                record_values = (research_run.run_id, research_fingerprint, projection_id, research_snapshot_id, research_request_fingerprint, research_run.schema_version, self.engine_identity, research_request.as_of_date, research_run.status, json_artifact, html_artifact)
                record = {"research_run_id": research_run.run_id, "original_cutoff_date": research_request.as_of_date, "status": research_run.status}
                disposition = ReferenceDisposition.CREATED
            except Exception as error:
                self._fail_node(workflow_run_id, run_node, run_attempt, "RESEARCH_ENGINE_FAILED", str(error))
        else:
            disposition = ReferenceDisposition.REUSED
            json_artifact = record["canonical_json_artifact_id"]
            html_artifact = record["html_artifact_id"]
        stale_by_days = max(0, (date.fromisoformat(request.effective_session_date) - date.fromisoformat(record["original_cutoff_date"])).days)
        reason = "ROUTINE_MARKET_ONLY_INPUTS" if disposition is ReferenceDisposition.REUSED and request.market_only_member_ids else ("IDENTICAL_RESEARCH_INPUT" if disposition is ReferenceDisposition.REUSED else "RESEARCH_INPUT_CHANGED_OR_NEW")
        final_contract = self._node("publish_run_manifest")
        final_node, final_attempt = self.repository.begin_node(workflow_run_id, final_contract.node_id, final_contract.version, self._hash({"node": asdict(final_contract), "run": record["research_run_id"], "json": json_artifact, "html": html_artifact}))
        terminal_status = "succeeded" if record["status"] == "completed" else "succeeded_with_limits"
        self.repository.finalize_research_success(workflow_run_id, run_node, run_attempt, final_node, final_attempt, disposition, record_values, record, projection_artifact_id, projection_id, json_artifact, html_artifact, request.workflow_snapshot_id, reason, stale_by_days, request.candidate_member_ids, request.market_only_member_ids, terminal_status)
        return self.repository.result(workflow_run_id)

    def get_history(self, workflow_run_id: str) -> WorkflowHistory:
        return self.repository.history(workflow_run_id)

    def get_manifest(self, manifest_id: str) -> ArtifactManifestView:
        return self.repository.manifest(manifest_id)

    def _validate_workflow_snapshot(self, workflow_snapshot_id: str, research_snapshot_id: str) -> None:
        if workflow_snapshot_id == research_snapshot_id:
            raise ProjectionError("SNAPSHOT_PURPOSE_COLLISION", "Workflow and research snapshots must remain distinct.")
        row = self.repository.connection.execute("SELECT snapshot_purpose FROM data_snapshot WHERE data_snapshot_id=?", (workflow_snapshot_id,)).fetchone()
        if row is None or row[0] not in {"workflow", "market"}:
            raise ProjectionError("WORKFLOW_SNAPSHOT_INVALID", "Workflow snapshot must exist with workflow or market purpose.")

    def _validate_snapshot_classification(self, snapshot_id: str, candidates: tuple[str, ...], market_only: tuple[str, ...], projection_context: object) -> None:
        rows = self.repository.connection.execute("""SELECT m.normalized_version_id,r.dataset
            FROM data_snapshot_member m JOIN normalized_version v USING(normalized_version_id)
            JOIN normalized_record r USING(normalized_record_id) WHERE m.data_snapshot_id=?""", (snapshot_id,)).fetchall()
        actual = {row[0]: row[1] for row in rows}
        if set(candidates) != set(actual):
            raise ProjectionError("SNAPSHOT_CANDIDATE_CLASSIFICATION_INVALID", "Candidate members must exactly match frozen workflow snapshot membership.")
        derived_market = {member_id for member_id, dataset in actual.items() if dataset in {"trade_cal", "market_universe", "daily"}}
        if set(market_only) != derived_market:
            raise ProjectionError("SNAPSHOT_MARKET_CLASSIFICATION_INVALID", "Market-only members are derived from persisted typed datasets.")
        relevant = set(actual) - derived_market
        declared_relevant = set(projection_context.get("workflow_research_member_ids", ())) if isinstance(projection_context, dict) else set()
        if relevant != declared_relevant:
            raise ProjectionError("RESEARCH_RELEVANT_SNAPSHOT_CHANGE", "Research-relevant snapshot members must be incorporated into the frozen projection.")

    def _fail_node(self, workflow_run_id: str, node_run_id: str, attempt_id: str, code: str, detail: str) -> None:
        del detail
        node_id = self.repository.connection.execute("SELECT node_id FROM workflow_node_run WHERE workflow_node_run_id=?", (node_run_id,)).fetchone()[0]
        contract = self._node(node_id)
        if code not in contract.failure_codes:
            code = contract.failure_codes[0]
        diagnostic = self.repository.publish_artifact(json.dumps({"error_code": code, "detail": "See workflow error code and retry after correcting the frozen input or capability."}, ensure_ascii=False, sort_keys=True).encode("utf-8"), "application/json", "WorkflowDiagnostic@1")
        self.repository.fail_node(node_run_id, attempt_id, code, diagnostic)
        self.repository.fail(workflow_run_id, code)
        raise WorkflowError(code, workflow_run_id)

    @staticmethod
    def _node(node_id: str) -> NodeDefinition:
        return next(node for node in RESEARCH_WORKFLOW.nodes if node.node_id == node_id)

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
