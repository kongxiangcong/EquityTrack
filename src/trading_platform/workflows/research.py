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
from decimal import Decimal
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
from trading_platform.research_presentation import (
    render_research_decision_html,
)
from trading_platform.research_view import ResearchDecisionViewBuilder

from .registry import RESEARCH_WORKFLOW, NodeDefinition
from .repository import WorkflowRepository
from equity_research import (
    ForecastReviewEngine,
    ForecastReviewRequest,
    validated_income_calibration_vectors,
    validate_source_manifest_runtime,
)


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
        self.repo_root = repo_root.resolve()
        self.engine_identity = research_engine_identity(self.repo_root)
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
        if request.projection.as_of_date > request.effective_session_date:
            raise WorkflowError("WORKFLOW_PIT_INVARIANT_FAILED", run_id)
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
        analysis_artifact_hashes = [
            item.content_hash for item in request.analysis_artifacts
        ]
        fp = self._hash({"workflow": f"{RESEARCH_WORKFLOW.workflow_id}@{RESEARCH_WORKFLOW.version}", "node": f"{contract.node_id}@{contract.version}", "research": research_fp, "policy": self.assembler.POLICY_VERSION, "code_identity": self.engine_identity, "analysis_artifacts": analysis_artifact_hashes})
        completed = self.repository.validate_checkpoint(run_id, contract, fp)
        if completed is not None:
            member_rows = self.repository.checkpoint_members(completed["workflow_node_run_id"])
            members = {r["member_role"]: r["artifact_id"] for r in member_rows}
            record = self.repository.connection.execute("SELECT * FROM research_run_record WHERE canonical_json_artifact_id=?", (members["research_run_json"],)).fetchone()
            if record is None:
                record = self.repository.connection.execute(
                    "SELECT DISTINCT r.* FROM research_run_record r "
                    "JOIN research_artifact_record a "
                    "ON a.research_run_id=r.research_run_id "
                    "WHERE a.artifact_id IN ("
                    + ",".join("?" for _ in member_rows)
                    + ")",
                    tuple(row["artifact_id"] for row in member_rows),
                ).fetchone()
            attempt = self.repository.connection.execute("SELECT workflow_node_attempt_id FROM workflow_node_attempt WHERE workflow_node_run_id=? ORDER BY attempt_no DESC LIMIT 1", (completed["workflow_node_run_id"],)).fetchone()[0]
            decision = ReferenceDisposition.REUSED if self.repository.connection.execute("SELECT disposition FROM workflow_node_attempt WHERE workflow_node_attempt_id=?", (attempt,)).fetchone()[0] == "reused" else ReferenceDisposition.CREATED
            run_members = tuple(
                (row["artifact_id"], row["member_role"], row["direction"])
                for row in member_rows
            )
            return record, decision, run_members, completed["workflow_node_run_id"], attempt
        node, attempt = self.repository.begin_or_retry_node(run_id, contract, fp, owner)
        self._fault("workflow.node_attempt_started:run_or_link_research")
        try:
            trusted_source_validation = self._validate_analysis_artifact_gate(request)
        except ProjectionError as error:
            self._fail_node(run_id, node, attempt, error.code)
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
                typed_presentation_expected = {
                    item.artifact_kind for item in request.analysis_artifacts
                }.issuperset({"DataSnapshot", "Forecast", "Valuation"})
                json_schema = (
                    f"ResearchRunCompatibility@{produced.schema_version}"
                    if typed_presentation_expected
                    else f"ResearchRun@{produced.schema_version}"
                )
                html_schema = (
                    "ResearchReportHtmlCompatibility@1"
                    if typed_presentation_expected
                    else "ResearchReportHtml@1"
                )
                json_artifact = self.repository.publish_artifact(json.dumps(produced.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(), "application/json", json_schema)
                html_artifact = self.repository.publish_artifact(produced.html.encode(), "text/html", html_schema)
                request_fp = self._hash(
                    {
                        "manifest": assembled.manifest,
                        "estimates": assembled.estimates,
                        "research_inputs": (
                            assembled.research_inputs.identity_payload()
                        )
                        if assembled.research_inputs is not None
                        else None,
                        "as_of_date": assembled.as_of_date,
                        "profile": assembled.profile,
                    }
                )
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
                market_data_snapshot_id=request.workflow_snapshot_id,
            )
        except Exception:
            self._fail_node(
                run_id,
                node,
                attempt,
                "RESEARCH_ARTIFACT_PERSISTENCE_FAILED",
            )
        typed_views = tuple(
            self.repository.research_artifact_view(record_id)
            for record_id in artifact_record_ids
        )
        by_kind = {item.artifact_kind: item for item in typed_views}
        if {"DataSnapshot", "Forecast", "Valuation"}.issubset(by_kind):
            research_payload = (
                produced.to_dict()
                if disposition is ReferenceDisposition.CREATED
                else self.repository.research_run_payload(
                    record["research_run_id"]
                )
            )
            research_payload = self._presentation_permissions(
                research_payload,
                request,
                by_kind["Valuation"].payload,
                by_kind["DataSnapshot"].payload,
                trusted_source_validation,
            )
            decision_view = ResearchDecisionViewBuilder().build(
                workflow_run_id=run_id,
                data_snapshot=by_kind["DataSnapshot"],
                forecast=by_kind["Forecast"],
                valuation=by_kind["Valuation"],
                simulation=by_kind.get("Simulation"),
                market_data_snapshot=by_kind.get("MarketDataSnapshot"),
                market_path=by_kind.get("MarketPathSimulation"),
                research_run_payload=research_payload,
            )
            decision_payload = decision_view.to_dict()
            json_artifact = self.repository.publish_artifact(
                json.dumps(
                    decision_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode(),
                "application/json",
                decision_view.schema_version,
            )
            html_artifact = self.repository.publish_artifact(
                render_research_decision_html(decision_view).encode(),
                "text/html",
                "ResearchDecisionHtml@1",
            )
            if disposition is ReferenceDisposition.CREATED:
                with self.repository.connection:
                    self.repository.connection.execute(
                        "UPDATE research_run_record "
                        "SET canonical_json_artifact_id=?,html_artifact_id=? "
                        "WHERE research_run_id=?",
                        (
                            json_artifact,
                            html_artifact,
                            record["research_run_id"],
                        ),
                    )
                record = self.repository.connection.execute(
                    "SELECT * FROM research_run_record WHERE research_run_id=?",
                    (record["research_run_id"],),
                ).fetchone()
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

    @classmethod
    def _has_per_share_output(cls, value: object) -> bool:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key).strip().lower()
                if (
                    "per_share" in normalized_key
                    and nested not in (None, "", (), [], {})
                ):
                    return True
                if normalized_key in {"output_level", "value_level", "kind", "level"} and isinstance(nested, str) and "per_share" in nested.lower():
                    return True
                if normalized_key == "unit" and isinstance(nested, str):
                    normalized_unit = nested.strip().lower()
                    if normalized_unit.endswith("/share") or normalized_unit.endswith(
                        " per share"
                    ):
                        return True
                if cls._has_per_share_output(nested):
                    return True
        elif isinstance(value, (list, tuple)):
            return any(cls._has_per_share_output(item) for item in value)
        return False

    def _trusted_source_manifest_validation(
        self, projection: ResearchProjection
    ) -> Mapping[str, object]:
        if not projection.source_manifest_path:
            raise ProjectionError(
                "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                "Typed valuation artifacts require a repo-contained source-manifest path.",
            )
        relative = Path(projection.source_manifest_path)
        if relative.is_absolute():
            raise ProjectionError(
                "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                "Source-manifest path must be relative to the repository root.",
            )
        path = (self.repo_root / relative).resolve()
        if path != self.repo_root and self.repo_root not in path.parents:
            raise ProjectionError(
                "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                "Source-manifest path escapes the repository root.",
            )
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectionError(
                "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                "Platform could not load the frozen source manifest.",
            ) from error
        if not isinstance(manifest, Mapping):
            raise ProjectionError(
                "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                "Frozen source manifest must be an object.",
            )
        if self.assembler.fingerprint(
            ResearchProjection(
                **{
                    **asdict(projection),
                    "manifest": manifest,
                    "field_semantics": projection.field_semantics,
                }
            )
        ) != self.assembler.fingerprint(projection):
            raise ProjectionError(
                "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                "Repo source manifest does not match the frozen projection.",
            )
        result = validate_source_manifest_runtime(manifest, path)
        if (
            result.get("authority") != "platform_source_manifest_gate@1"
            or result.get("passed") is not True
            or result.get("source_manifest_status")
            not in {"sufficient", "valid_with_limits"}
        ):
            raise ProjectionError(
                "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                "Platform source-manifest validation did not authorize typed valuation publication.",
            )
        return result

    def _validate_simulation_calibration(
        self, request: ResearchWorkflowRequest
    ) -> None:
        manifest_path = (self.repo_root / str(request.projection.source_manifest_path)).resolve()
        source_by_hash = {
            str(source.get("raw_file_sha256", "")).lower(): source
            for source in request.projection.manifest.get("sources", ())
            if isinstance(source, Mapping) and source.get("raw_file_sha256")
        }
        requires_income_derivation = any(
            str(field.get("field_name", ""))
            == "historical_operating_calibration_derivation"
            for source in request.projection.manifest.get("sources", ())
            if isinstance(source, Mapping)
            for field in source.get("extracted_fields", ())
            if isinstance(field, Mapping)
        )
        for draft in request.analysis_artifacts:
            if draft.artifact_kind != "Simulation":
                continue
            dependency = draft.payload.get("dependency_model")
            calibration = (
                dependency.get("calibration")
                if isinstance(dependency, Mapping)
                else None
            )
            if not isinstance(calibration, Mapping):
                continue
            derivation_kind = calibration.get("derivation_kind")
            if requires_income_derivation and derivation_kind != "cumulative_income_quarterly":
                raise ProjectionError(
                    "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                    "Declared income calibration evidence requires repo-bound quarterly re-derivation.",
                )
            if derivation_kind == "embedded_observation_vectors":
                vectors = calibration.get("observation_vectors")
                if (
                    not isinstance(vectors, list)
                    or len(vectors) < 20
                    or any(not isinstance(row, list) or not row for row in vectors)
                ):
                    raise ProjectionError(
                        "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                        "Embedded simulation calibration requires a non-empty typed observation sample.",
                    )
                continue
            if derivation_kind != "cumulative_income_quarterly":
                raise ProjectionError(
                    "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                    "Unknown simulation calibration derivation kind fails closed.",
                )
            raw_hash = str(calibration.get("raw_observation_content_hash", "")).lower()
            ledger_hash = str(
                calibration.get("derivation_ledger_content_hash", "")
            ).lower()
            raw_source = source_by_hash.get(raw_hash)
            ledger_source = source_by_hash.get(ledger_hash)
            if raw_source is None or ledger_source is None:
                raise ProjectionError(
                    "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                    "Simulation calibration assets are not hash-bound to the source manifest.",
                )

            def load_asset(source: Mapping[str, object]) -> Mapping[str, object]:
                path = (manifest_path.parent / str(source.get("raw_file_path", ""))).resolve()
                if path != self.repo_root and self.repo_root not in path.parents:
                    raise ProjectionError(
                        "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                        "Simulation calibration asset escapes the repository root.",
                    )
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(loaded, Mapping):
                    raise ProjectionError(
                        "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                        "Simulation calibration asset must be an object.",
                    )
                return loaded

            recomputed = validated_income_calibration_vectors(
                load_asset(raw_source), load_asset(ledger_source)
            )
            stored = tuple(
                tuple(Decimal(str(value)) for value in row)
                for row in calibration.get("observation_vectors", ())
                if isinstance(row, list)
            )
            if stored != recomputed:
                raise ProjectionError(
                    "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                    "Simulation calibration vectors do not match repo-bound raw evidence.",
                )

    def _validate_analysis_artifact_gate(
        self, request: ResearchWorkflowRequest
    ) -> Mapping[str, object] | None:
        if not request.analysis_artifacts:
            return None
        if not request.projection.diluted_share_identity:
            for draft in request.analysis_artifacts:
                if draft.artifact_kind not in {"Valuation", "Simulation"}:
                    continue
                if self._has_per_share_output(draft.payload) or self._has_per_share_output(
                    draft.summary
                ):
                    raise ProjectionError(
                        "RESEARCH_ANALYSIS_PER_SHARE_GATE_FAILED",
                        "Per-share valuation cannot be published without a frozen diluted-share identity.",
                    )
        result = self._trusted_source_manifest_validation(request.projection)
        self._validate_simulation_calibration(request)
        return result

    @staticmethod
    def _diluted_share_binding(
        projection: ResearchProjection,
        data_snapshot_payload: Mapping[str, object],
    ) -> tuple[Decimal, str] | None:
        try:
            source_id, field_name, period = projection.diluted_share_identity.split(
                ":", 2
            )
        except ValueError:
            return None
        manifest_field = next(
            (
                field
                for source in projection.manifest.get("sources", ())
                if isinstance(source, Mapping)
                and str(source.get("source_id")) == source_id
                for field in source.get("extracted_fields", ())
                if isinstance(field, Mapping)
                and str(field.get("field_name")) == field_name
                and str(field.get("period")) == period
            ),
            None,
        )
        snapshot_fact = next(
            (
                fact
                for fact in data_snapshot_payload.get("facts", ())
                if isinstance(fact, Mapping)
                and str(fact.get("source_id")) == source_id
                and str(fact.get("field_name")) == field_name
                and str(fact.get("period")) == period
                and fact.get("official") is True
            ),
            None,
        )
        if manifest_field is None or snapshot_fact is None:
            return None
        try:
            expected = Decimal(str(manifest_field.get("value"))) * Decimal(
                str(manifest_field.get("scale", "1"))
            )
            observed = Decimal(str(snapshot_fact.get("value")))
        except Exception:
            return None
        if expected != observed or str(snapshot_fact.get("unit")) != str(
            manifest_field.get("unit")
        ):
            return None
        return observed, str(snapshot_fact.get("fact_id"))

    @staticmethod
    def _share_bound_ready_methods(
        valuation_payload: Mapping[str, object],
        diluted_shares: Decimal,
        diluted_share_fact_id: str,
    ) -> set[str]:
        bound: set[str] = set()
        invalid: set[str] = set()
        roles_by_method: dict[str, set[str]] = {}
        expected_ref = f"Fact:{diluted_share_fact_id}"
        expected_roles = {"stress", "base", "improvement"}
        expected_points = {"low", "base", "high"}

        def quantity_value(value: object) -> Decimal | None:
            if not isinstance(value, Mapping):
                return None
            raw = value.get("normalized_value", value.get("value"))
            try:
                return Decimal(str(raw))
            except Exception:
                return None

        for scenario in valuation_payload.get("scenarios", ()):
            if not isinstance(scenario, Mapping):
                continue
            for method in scenario.get("methods", ()):
                if not isinstance(method, Mapping) or method.get("status") != "ready":
                    continue
                method_id = str(method.get("method_id"))
                role = str(scenario.get("role"))
                value_range = method.get("conditional_value_range")
                if not isinstance(value_range, Mapping) or set(value_range) != expected_points:
                    invalid.add(method_id)
                    continue
                points_valid = True
                for point in value_range.values():
                    if not isinstance(point, Mapping):
                        points_valid = False
                        break
                    equity = quantity_value(point.get("equity_value"))
                    per_share = quantity_value(point.get("per_share_value"))
                    trace = point.get("bridge_trace")
                    divide_steps = (
                        [
                            step
                            for step in trace
                            if isinstance(step, Mapping)
                            and step.get("operation") == "divide_diluted_shares"
                        ]
                        if isinstance(trace, list)
                        else []
                    )
                    if (
                        equity is None
                        or per_share is None
                        or diluted_shares == 0
                        or per_share != equity / diluted_shares
                        or len(divide_steps) != 1
                        or expected_ref not in divide_steps[0].get("ref_ids", ())
                        or Decimal(str(divide_steps[0].get("amount")))
                        != diluted_shares
                    ):
                        points_valid = False
                        break
                if points_valid:
                    bound.add(method_id)
                    roles_by_method.setdefault(method_id, set()).add(role)
                else:
                    invalid.add(method_id)
        return {
            method_id
            for method_id in bound - invalid
            if roles_by_method.get(method_id) == expected_roles
        }

    @staticmethod
    def _presentation_permissions(
        research_payload: Mapping[str, object],
        request: ResearchWorkflowRequest,
        valuation_payload: Mapping[str, object],
        data_snapshot_payload: Mapping[str, object],
        trusted_source_validation: Mapping[str, object] | None,
    ) -> dict[str, object]:
        share_binding = ResearchWorkflowService._diluted_share_binding(
            request.projection, data_snapshot_payload
        )
        ready_methods = (
            ResearchWorkflowService._share_bound_ready_methods(
                valuation_payload, share_binding[0], share_binding[1]
            )
            if share_binding is not None
            else set()
        )
        permissions = research_payload.get("permissions")
        base_permissions = dict(permissions) if isinstance(permissions, Mapping) else {}
        platform_prerequisites = (
            research_payload.get("status") != "blocked"
            and base_permissions.get("research_report") is True
            and base_permissions.get("scenario_analysis") is True
        )
        formal_per_share = platform_prerequisites and (
            base_permissions.get("formal_per_share_valuation") is True
            and bool(request.projection.diluted_share_identity)
            and share_binding is not None
            and isinstance(trusted_source_validation, Mapping)
            and trusted_source_validation.get("passed") is True
            and len(ready_methods) >= 2
        )
        return {
            **research_payload,
            "permissions": {
                **base_permissions,
                "formal_per_share_valuation": formal_per_share,
            },
        }

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
    def review_forecast(
        self,
        request: ForecastReviewRequest,
    ) -> ResearchArtifactView:
        forecast = self.repository.research_artifact_view(
            request.forecast_artifact_record_id
        )
        valuation = self.repository.research_artifact_view(
            request.valuation_artifact_record_id
        )
        simulation = self.repository.research_artifact_view(
            request.simulation_artifact_record_id
        )
        result = ForecastReviewEngine().run(request)
        draft = ImmutableArtifactDraft.from_forecast_review(
            result,
            forecast_artifact=forecast,
            valuation_artifact=valuation,
            simulation_artifact=simulation,
        )
        record_id = self.repository.persist_forecast_review(
            draft=draft,
            parent_record_ids=(
                forecast.artifact_record_id,
                valuation.artifact_record_id,
                simulation.artifact_record_id,
            ),
            code_identity=self.engine_identity,
        )
        return self.repository.research_artifact_view(record_id)
    @staticmethod
    def _artifact_member_role(artifact_kind: str) -> str:
        return {
            "DataSnapshot": "data_snapshot",
            "Forecast": "forecast",
            "Valuation": "valuation",
            "Simulation": "simulation",
            "MarketDataSnapshot": "market_data_snapshot",
            "MarketPathSimulation": "market_path_simulation",
            "ForecastReview": "forecast_review",
        }[artifact_kind]
    def _validate_workflow_snapshot(self, workflow_snapshot_id: str, research_snapshot_id: str) -> None:
        if workflow_snapshot_id == research_snapshot_id:
            raise ProjectionError("SNAPSHOT_PURPOSE_COLLISION", "snapshots differ")
        row = self.repository.connection.execute("SELECT snapshot_purpose FROM data_snapshot WHERE data_snapshot_id=?", (workflow_snapshot_id,)).fetchone()
        if row is None or row[0] not in {"workflow", "market"}:
            raise ProjectionError("WORKFLOW_SNAPSHOT_INVALID", "snapshot invalid")
    def _validate_snapshot_classification(self, snapshot_id: str, candidates: tuple[str, ...], market_only: tuple[str, ...], context: object) -> None:
        rows = self.repository.connection.execute("SELECT m.normalized_version_id,r.dataset FROM data_snapshot_member m JOIN normalized_version v USING(normalized_version_id) JOIN normalized_record r USING(normalized_record_id) WHERE m.data_snapshot_id=?", (snapshot_id,)).fetchall()
        actual = {r[0]: r[1] for r in rows}
        if set(candidates) != set(actual):
            raise ProjectionError("SNAPSHOT_CANDIDATE_CLASSIFICATION_INVALID", "candidate mismatch")
        market = {i for i, dataset in actual.items() if dataset in {"trade_cal", "market_universe", "daily"}}
        if set(market_only) != market:
            raise ProjectionError("SNAPSHOT_MARKET_CLASSIFICATION_INVALID", "market mismatch")
        declared = set(context.get("workflow_research_member_ids", ())) if isinstance(context, dict) else set()
        if set(actual) - market != declared:
            raise ProjectionError("RESEARCH_RELEVANT_SNAPSHOT_CHANGE", "relevant mismatch")
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
