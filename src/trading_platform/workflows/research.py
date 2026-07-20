from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Mapping, NoReturn, Protocol, TypeAlias

from trading_platform.application.contracts import (
    CancellationAccepted,
    CancelWorkflowCommand,
    ResearchWorkflowCommand,
    ResumeWorkflowCommand,
    StartResearchWorkflow,
)
from trading_platform.application.research_request_codec import (
    decode_research_workflow_request,
)
from trading_platform.application.research_source_codec import encode_research_source_html
from trading_platform.domain.workflow import (
    ReferenceDisposition,
    ResearchProjection,
    ResearchWorkflowRequest,
    ResearchWorkflowResult,
    WorkflowDefinition,
)
from trading_platform.identity.code import build_code_identity
from trading_platform.research import ProjectionError, SnapshotToResearchRequestAssembler
from trading_platform.research_presentation import (
    render_research_decision_html,
)
from trading_platform.research_view import ResearchDecisionInput, ResearchDecisionViewBuilder

from trading_platform.domain.workflow import NodeDefinition
from trading_platform.application.workflow_ledger import (
    AcquireLease,
    ArtifactBundlePreviewQuery,
    ArtifactPayload,
    BeginNode,
    CheckpointMembersQuery,
    CheckpointQuery,
    CommitResearchNode,
    CompletedResearchQuery,
    FailExecution,
    FinalizeResearchSuccess,
    FreezeProjection,
    Heartbeat,
    MarkRetryable,
    NodeNameQuery,
    ProjectionEvidenceQuery,
    ProjectionCheckpointCommit,
    ProjectionPreviewQuery,
    PreparedProjection,
    RequestCancellation,
    RequestPayloadQuery,
    ResearchArtifactBundle,
    ResearchPayloadQuery,
    ResearchRecord,
    ResearchRecordQuery,
    ResearchViewCutoverCompleteQuery,
    SnapshotEvidenceQuery,
    StartDisposition,
    StartWorkflow,
    StopIfCancelled,
    WorkflowLedgerPort,
    WorkflowPersistenceError,
    WorkflowRunQuery,
    WorkflowReferencesQuery,
    WorkflowResultQuery,
)
from equity_research import (
    ResearchRequest,
    ResearchRun,
    validated_income_calibration_vectors,
    validate_source_manifest_runtime,
)


_RESEARCH_WORKFLOW = WorkflowDefinition(
    "research-workflow",
    "2",
    (
        NodeDefinition("freeze_research_projection", "1", "ResearchProjection@1", "ResearchSnapshotRef@1", ("security_exists", "projection_cutoff_legal", "field_semantics_complete"), True, "content_addressed", "new_attempt_same_run", ("RESEARCH_PROJECTION_INVALID", "SNAPSHOT_PURPOSE_COLLISION", "WORKFLOW_SNAPSHOT_INVALID", "WORKFLOW_PIT_INVARIANT_FAILED", "WORKFLOW_DOMAIN_REFERENCE_INVALID", "WORKFLOW_QUALITY_BLOCKED", "SNAPSHOT_CANDIDATE_CLASSIFICATION_INVALID", "SNAPSHOT_MARKET_CLASSIFICATION_INVALID", "RESEARCH_RELEVANT_SNAPSHOT_CHANGE")),
        NodeDefinition("run_or_link_research", "2", "ResearchSnapshotRef@1", "ResearchArtifactSetRef@1", ("research_snapshot_frozen",), True, "research_and_artifact_fingerprints", "new_attempt_same_run", ("RESEARCH_ENGINE_FAILED", "RESEARCH_ARTIFACT_PERSISTENCE_FAILED", "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED", "RESEARCH_ANALYSIS_PER_SHARE_GATE_FAILED", "RESEARCH_VIEW_INPUT_INCOMPLETE")),
        NodeDefinition("publish_run_manifest", "2", "ResearchArtifactSetRef@1", "ArtifactManifestRef@1", ("research_artifacts_committed",), True, "none", "new_attempt_same_run", ("MANIFEST_PUBLICATION_FAILED",)),
    ),
)


class WorkflowError(RuntimeError):
    def __init__(self, code: str, workflow_run_id: str) -> None:
        super().__init__(code)
        self.code = code
        self.workflow_run_id = workflow_run_id


def research_engine_identity(repo_root: Path) -> str:
    identity = build_code_identity(repo_root, {"workflow": f"{_RESEARCH_WORKFLOW.workflow_id}@{_RESEARCH_WORKFLOW.version}", "research_input_policy": SnapshotToResearchRequestAssembler.POLICY_VERSION})
    structured = asdict(identity)
    return json.dumps({name: structured[name] for name in ("source_hash", "lock_hash", "migration_hash", "workflow_hash", "package_build_hash", "model_policy_hash", "dependency_license_hash", "determinism_basis", "random_seed")}, sort_keys=True, separators=(",", ":"))


class ResearchRunner(Protocol):
    def run(self, request: ResearchRequest) -> ResearchRun: ...


@dataclass(frozen=True)
class RunResearchEngine:
    request: ResearchRequest


@dataclass(frozen=True)
class ValidateResearchInputs:
    request: ResearchWorkflowRequest


@dataclass(frozen=True)
class PrepareResearchProjection:
    request: ResearchWorkflowRequest
    freeze: FreezeProjection


@dataclass(frozen=True)
class ValidateFrozenProjection:
    request: ResearchWorkflowRequest
    references: Mapping[str, str]
    projection_artifact_id: str
    projection_fingerprint: str


ResearchNodeCommand: TypeAlias = (
    RunResearchEngine
    | ValidateResearchInputs
    | PrepareResearchProjection
    | ValidateFrozenProjection
)


class ResearchExecutionError(RuntimeError):
    def __init__(
        self, code: str, *, retryable: bool, substep: str, cause_type: str
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.substep = substep
        self.cause_type = cause_type


class ResearchExecution:
    """Executes an already selected research node without lifecycle mutations."""

    def __init__(
        self,
        engine: ResearchRunner,
        assembler: SnapshotToResearchRequestAssembler,
        repo_root: Path,
        repository: WorkflowLedgerPort,
    ) -> None:
        self._engine = engine
        self.assembler = assembler
        self.repo_root = repo_root
        self._repository = repository

    def execute(
        self, command: ResearchNodeCommand
    ) -> ResearchRun | Mapping[str, object] | PreparedProjection | None:
        if isinstance(command, ValidateResearchInputs):
            return self._validate_analysis_artifact_gate(command.request)
        if isinstance(command, PrepareResearchProjection):
            return self._prepare_projection(command)
        if isinstance(command, ValidateFrozenProjection):
            self._validate_frozen_projection(command)
            return None
        try:
            return self._engine.run(command.request)
        except (TimeoutError, ConnectionError) as error:
            raise ResearchExecutionError(
                "RESEARCH_ENGINE_TRANSIENT",
                retryable=True,
                substep="research_engine.run",
                cause_type=type(error).__name__,
            ) from error
        except (ValueError, RuntimeError) as error:
            raise ResearchExecutionError(
                "RESEARCH_ENGINE_FAILED",
                retryable=False,
                substep="research_engine.run",
                cause_type=type(error).__name__,
            ) from error
        except Exception as error:
            raise ResearchExecutionError(
                "RESEARCH_ENGINE_FAILED",
                retryable=False,
                substep="research_engine.run.unexpected",
                cause_type=type(error).__name__,
            ) from error

    def _prepare_projection(
        self, command: PrepareResearchProjection
    ) -> PreparedProjection:
        request = command.request
        if (
            request.effective_session_date > request.requested_date
            or request.projection.as_of_date > request.requested_date
        ):
            raise ProjectionError(
                "WORKFLOW_PIT_INVARIANT_FAILED", "projection cutoff is future dated"
            )
        preview = self._repository.load(ProjectionPreviewQuery(command.freeze))
        if request.workflow_snapshot_id:
            self._validate_workflow_snapshot(
                request.workflow_snapshot_id, preview.research_snapshot_id
            )
            self._validate_snapshot_classification(
                request.workflow_snapshot_id,
                request.candidate_member_ids,
                request.market_only_member_ids,
                request.projection.research_inputs.workflow_research_member_ids,
            )
        return preview

    def _validate_frozen_projection(self, command: ValidateFrozenProjection) -> None:
        request = command.request
        projection_id = command.references.get("research_projection")
        snapshot_id = command.references.get("research_snapshot")
        if projection_id is None or snapshot_id is None:
            raise ProjectionError(
                "WORKFLOW_DOMAIN_REFERENCE_INVALID", "projection reference is missing"
            )
        row = self._repository.load(ProjectionEvidenceQuery(projection_id))
        if (
            row is None
            or row.research_snapshot_id != snapshot_id
            or row.projection_artifact_id != command.projection_artifact_id
            or row.research_input_fingerprint != command.projection_fingerprint
        ):
            raise ProjectionError(
                "WORKFLOW_DOMAIN_REFERENCE_INVALID", "projection evidence does not match"
            )
        if (
            row.security_id != request.security_id
            or row.as_of_date > request.requested_date
            or row.snapshot_purpose != "research"
        ):
            raise ProjectionError(
                "WORKFLOW_PIT_INVARIANT_FAILED", "projection violates point-in-time policy"
            )
        if row.freshness_status != "valid" or row.quality_status == "blocking":
            raise ProjectionError(
                "WORKFLOW_QUALITY_BLOCKED", "projection quality blocks execution"
            )
        if request.workflow_snapshot_id:
            self._validate_workflow_snapshot(request.workflow_snapshot_id, snapshot_id)
            self._validate_snapshot_classification(
                request.workflow_snapshot_id,
                request.candidate_member_ids,
                request.market_only_member_ids,
                request.projection.research_inputs.workflow_research_member_ids,
            )

    def _validate_workflow_snapshot(
        self, workflow_snapshot_id: str, research_snapshot_id: str
    ) -> None:
        if workflow_snapshot_id == research_snapshot_id:
            raise ProjectionError("SNAPSHOT_PURPOSE_COLLISION", "snapshots differ")
        evidence = self._repository.load(SnapshotEvidenceQuery(workflow_snapshot_id))
        if evidence.purpose not in {"workflow", "market"}:
            raise ProjectionError("WORKFLOW_SNAPSHOT_INVALID", "snapshot invalid")

    def _validate_snapshot_classification(
        self,
        snapshot_id: str,
        candidates: tuple[str, ...],
        market_only: tuple[str, ...],
        declared_research_members: tuple[str, ...],
    ) -> None:
        actual = dict(self._repository.load(SnapshotEvidenceQuery(snapshot_id)).members)
        if set(candidates) != set(actual):
            raise ProjectionError(
                "SNAPSHOT_CANDIDATE_CLASSIFICATION_INVALID", "candidate mismatch"
            )
        market = {
            item
            for item, dataset in actual.items()
            if dataset in {"trade_cal", "market_universe", "daily"}
        }
        if set(market_only) != market:
            raise ProjectionError(
                "SNAPSHOT_MARKET_CLASSIFICATION_INVALID", "market mismatch"
            )
        declared = set(declared_research_members)
        if set(actual) - market != declared:
            raise ProjectionError(
                "RESEARCH_RELEVANT_SNAPSHOT_CHANGE", "relevant mismatch"
            )

    @classmethod
    def _has_per_share_output(cls, value: object) -> bool:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key).strip().lower()
                if "per_share" in normalized_key and nested not in (None, "", (), [], {}):
                    return True
                if normalized_key in {"output_level", "value_level", "kind", "level"} and isinstance(nested, str) and "per_share" in nested.lower():
                    return True
                if normalized_key == "unit" and isinstance(nested, str):
                    unit = nested.strip().lower()
                    if unit.endswith("/share") or unit.endswith(" per share"):
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
                    "research_inputs": projection.research_inputs,
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
        manifest_path = (
            self.repo_root / str(request.projection.source_manifest_path)
        ).resolve()
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
            calibration = dependency.get("calibration") if isinstance(dependency, Mapping) else None
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
                if not isinstance(vectors, list) or len(vectors) < 20 or any(not isinstance(row, list) or not row for row in vectors):
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
            ledger_hash = str(calibration.get("derivation_ledger_content_hash", "")).lower()
            raw_source = source_by_hash.get(raw_hash)
            ledger_source = source_by_hash.get(ledger_hash)
            if raw_source is None or ledger_source is None:
                raise ProjectionError(
                    "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                    "Simulation calibration assets are not hash-bound to the source manifest.",
                )

            def load_asset(source: Mapping[str, object]) -> Mapping[str, object]:
                asset_path = (manifest_path.parent / str(source.get("raw_file_path", ""))).resolve()
                if asset_path != self.repo_root and self.repo_root not in asset_path.parents:
                    raise ProjectionError(
                        "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED",
                        "Simulation calibration asset escapes the repository root.",
                    )
                loaded = json.loads(asset_path.read_text(encoding="utf-8"))
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
            tolerance = Decimal("0.000000000001")
            if (
                len(stored) != len(recomputed)
                or any(
                    len(actual) != len(expected)
                    or any(
                        abs(actual_value - expected_value) > tolerance
                        for actual_value, expected_value in zip(actual, expected, strict=True)
                    )
                    for actual, expected in zip(stored, recomputed, strict=True)
                )
            ):
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
                if self._has_per_share_output(draft.payload) or self._has_per_share_output(draft.summary):
                    raise ProjectionError(
                        "RESEARCH_ANALYSIS_PER_SHARE_GATE_FAILED",
                        "Per-share valuation cannot be published without a frozen diluted-share identity.",
                    )
        result = self._trusted_source_manifest_validation(request.projection)
        self._validate_simulation_calibration(request)
        return result


class ResearchWorkflow:
    def __init__(self, repository: WorkflowLedgerPort, engine: ResearchRunner, assembler: SnapshotToResearchRequestAssembler, repo_root: Path, fault_injector: Callable[[str], None] | None = None) -> None:
        self.repository = repository
        self.assembler = assembler
        self.repo_root = repo_root.resolve()
        self.execution = ResearchExecution(engine, assembler, self.repo_root, repository)
        self.engine_identity = research_engine_identity(self.repo_root)
        self.fault_injector = fault_injector

    def _fault(self, boundary: str) -> None:
        if self.fault_injector:
            self.fault_injector(boundary)

    def handle(
        self, command: ResearchWorkflowCommand
    ) -> ResearchWorkflowResult | CancellationAccepted:
        if not self.repository.load(ResearchViewCutoverCompleteQuery()):
            workflow_ref = (
                command.request.invocation_id
                if isinstance(command, StartResearchWorkflow)
                and isinstance(command.request, ResearchWorkflowRequest)
                else command.workflow_run_id
                if isinstance(command, (ResumeWorkflowCommand, CancelWorkflowCommand))
                else "unknown"
            )
            raise WorkflowError("RESEARCH_VIEW_CUTOVER_INCOMPLETE", workflow_ref)
        if isinstance(command, StartResearchWorkflow):
            if not isinstance(command.request, ResearchWorkflowRequest):
                raise TypeError("StartResearchWorkflow requires ResearchWorkflowRequest")
            return self._start(command.request)
        if isinstance(command, ResumeWorkflowCommand):
            return self._resume(command)
        if isinstance(command, CancelWorkflowCommand):
            self.repository.record_transition(
                RequestCancellation(command.workflow_run_id, command.reason)
            )
            return CancellationAccepted(command.workflow_run_id)
        raise TypeError("Unsupported research workflow command")

    def _start(self, request: ResearchWorkflowRequest) -> ResearchWorkflowResult:
        payload = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        fingerprint = self._hash({"workflow": f"{_RESEARCH_WORKFLOW.workflow_id}@{_RESEARCH_WORKFLOW.version}", "request": asdict(request)})
        owner = f"owner-{uuid.uuid4().hex}"
        try:
            started = self.repository.start_or_replay(
                StartWorkflow(
                    invocation_id=request.invocation_id,
                    request_fingerprint=fingerprint,
                    requested_date=request.requested_date,
                    effective_session_date=request.effective_session_date,
                    definition=_RESEARCH_WORKFLOW,
                    owner_token=owner,
                    request_payload=payload,
                    request_schema="ResearchWorkflowRequest@1",
                )
            )
        except WorkflowPersistenceError as error:
            code = (
                "INVOCATION_REQUEST_MISMATCH"
                if error.code in {"WORKFLOW_FINGERPRINT_MISMATCH", "WORKFLOW_REQUEST_INTEGRITY_FAILED"}
                else error.code
            )
            raise WorkflowError(code, request.invocation_id) from error
        run_id = started.workflow_run_id
        if started.disposition is StartDisposition.REPLAYED:
            if self.repository.load(WorkflowRunQuery(run_id)).status in {"succeeded", "succeeded_with_limits"}:
                return self.repository.load(WorkflowResultQuery(run_id))
            try:
                self.repository.record_transition(AcquireLease(run_id, owner, _RESEARCH_WORKFLOW, 30))
            except ValueError as error:
                raise WorkflowError(str(error), run_id) from error
        return self._execute(run_id, request, owner, acquire=False)

    def _resume(self, command: ResumeWorkflowCommand) -> ResearchWorkflowResult:
        try:
            request = decode_research_workflow_request(
                self.repository.load(RequestPayloadQuery(command.workflow_run_id))
            )
            self.repository.record_transition(AcquireLease(command.workflow_run_id, command.owner_token, _RESEARCH_WORKFLOW, command.lease_seconds))
            return self._execute(command.workflow_run_id, request, command.owner_token, acquire=False, lease_seconds=command.lease_seconds)
        except WorkflowError:
            raise
        except ValueError as error:
            raise WorkflowError(str(error), command.workflow_run_id) from error

    def _execute(self, run_id: str, request: ResearchWorkflowRequest, owner: str, acquire: bool = False, lease_seconds: int = 30) -> ResearchWorkflowResult:
        del acquire
        try:
            self.repository.record_transition(Heartbeat(run_id, owner, lease_seconds))
            self.repository.record_transition(StopIfCancelled(run_id))
            projection_id, research_snapshot_id, projection_artifact, research_fingerprint = self._freeze(run_id, request, owner)
            self.repository.record_transition(StopIfCancelled(run_id))
            self.repository.record_transition(Heartbeat(run_id, owner, lease_seconds))
            record, disposition, run_members, run_node, run_attempt = self._research(run_id, request, owner, projection_id, research_snapshot_id, projection_artifact, research_fingerprint, lease_seconds)
            self.repository.record_transition(StopIfCancelled(run_id))
            self.repository.record_transition(Heartbeat(run_id, owner, lease_seconds))
            final_contract = self._node("publish_run_manifest")
            final_fp = self._hash({"node": asdict(final_contract), "run": record.research_run_id, "members": run_members})
            completed = self.repository.load(CheckpointQuery(run_id, final_contract, final_fp))
            if completed is not None:
                return self.repository.load(WorkflowResultQuery(run_id))
            final_node, final_attempt = self.repository.record_transition(BeginNode(run_id, final_contract, final_fp, owner))
            self._fault("workflow.node_attempt_started:publish_run_manifest")
            stale = max(0, (date.fromisoformat(request.effective_session_date) - date.fromisoformat(record.original_cutoff_date)).days)
            reason = "ROUTINE_MARKET_ONLY_INPUTS" if disposition is ReferenceDisposition.REUSED and request.market_only_member_ids else ("IDENTICAL_RESEARCH_INPUT" if disposition is ReferenceDisposition.REUSED else "RESEARCH_INPUT_CHANGED_OR_NEW")
            terminal = "succeeded" if record.status == "completed" else "succeeded_with_limits"
            self._fault("workflow.before_final_manifest_commit")
            self.repository.complete(FinalizeResearchSuccess(run_id, owner, run_node, run_attempt, final_node, final_attempt, disposition, record, run_members, projection_id, request.workflow_snapshot_id, reason, stale, request.candidate_member_ids, request.market_only_member_ids, terminal))
            self._fault("workflow.final_manifest_committed")
            return self.repository.load(WorkflowResultQuery(run_id))
        except WorkflowError:
            raise
        except ProjectionError as error:
            raise WorkflowError(error.code, run_id) from error
        except ValueError as error:
            raise WorkflowError(str(error), run_id) from error

    def _freeze(self, run_id: str, request: ResearchWorkflowRequest, owner: str) -> tuple[str, str, str, str]:
        contract = self._node("freeze_research_projection")
        fp = self._hash({"node": asdict(contract), "input": asdict(request.projection)})
        completed = self.repository.load(CheckpointQuery(run_id, contract, fp))
        if completed is not None:
            research_fp = self.assembler.fingerprint(request.projection)
            refs = self.repository.load(WorkflowReferencesQuery(run_id))
            member = self.repository.load(CheckpointMembersQuery(completed.workflow_node_run_id))[0]
            self.execution.execute(
                ValidateFrozenProjection(
                    request, refs, member.artifact_id, research_fp
                )
            )
            return refs["research_projection"], refs["research_snapshot"], member.artifact_id, research_fp
        node, attempt = self.repository.record_transition(BeginNode(run_id, contract, fp, owner))
        self._fault("workflow.node_attempt_started:freeze_research_projection")
        try:
            research_fp = self.assembler.fingerprint(request.projection)
            freeze = FreezeProjection(request.security_id, request.projection, research_fp)
            preview = self.execution.execute(PrepareResearchProjection(request, freeze))
            assert isinstance(preview, PreparedProjection)
            self._fault("workflow.before_node_success:freeze_research_projection")
            checkpoint = self.repository.commit_checkpoint(
                ProjectionCheckpointCommit(
                    workflow_run_id=run_id,
                    workflow_node_run_id=node,
                    workflow_node_attempt_id=attempt,
                    owner_token=owner,
                    freeze=freeze,
                    workflow_snapshot_id=request.workflow_snapshot_id,
                )
            )
            self.repository.record_transition(Heartbeat(run_id, owner))
            self._fault("workflow.freeze_checkpoint_committed")
            projection = checkpoint.projection
            return (
                projection.research_projection_id,
                projection.research_snapshot_id,
                projection.projection_artifact_id,
                research_fp,
            )
        except (ProjectionError, ValueError) as error:
            self._fail_node(run_id, node, attempt, owner, getattr(error, "code", "RESEARCH_PROJECTION_INVALID"))

    def _research(self, run_id: str, request: ResearchWorkflowRequest, owner: str, projection_id: str, snapshot_id: str, projection_artifact: str, research_fp: str, lease_seconds: int):
        contract = self._node("run_or_link_research")
        analysis_artifact_hashes = [
            item.content_hash for item in request.analysis_artifacts
        ]
        fp = self._hash({"workflow": f"{_RESEARCH_WORKFLOW.workflow_id}@{_RESEARCH_WORKFLOW.version}", "node": f"{contract.node_id}@{contract.version}", "research": research_fp, "policy": self.assembler.POLICY_VERSION, "code_identity": self.engine_identity, "analysis_artifacts": analysis_artifact_hashes})
        completed = self.repository.load(CheckpointQuery(run_id, contract, fp))
        if completed is not None:
            restored = self.repository.load(
                CompletedResearchQuery(completed.workflow_node_run_id)
            )
            return (
                restored.record,
                restored.disposition,
                restored.members,
                completed.workflow_node_run_id,
                restored.workflow_node_attempt_id,
            )
        node, attempt = self.repository.record_transition(BeginNode(run_id, contract, fp, owner))
        self._fault("workflow.node_attempt_started:run_or_link_research")
        try:
            validated = self.execution.execute(ValidateResearchInputs(request))
            assert validated is None or isinstance(validated, Mapping)
            trusted_source_validation = validated
        except ProjectionError as error:
            self._fail_node(run_id, node, attempt, owner, error.code)
        record = self.repository.load(
            ResearchRecordQuery(
                research_input_fingerprint=research_fp,
                engine_code_identity=self.engine_identity,
            )
        )
        new_record = None
        if record is None:
            retry_count = 0
            while True:
              try:
                assembled = self.assembler.assemble(request.projection)
                with self._supervise_lease(run_id, owner, lease_seconds):
                    executed = self.execution.execute(RunResearchEngine(assembled))
                    assert isinstance(executed, ResearchRun)
                    produced = executed
                self.repository.record_transition(Heartbeat(run_id, owner, lease_seconds))
                source_json_write = ArtifactPayload(
                    json.dumps(produced.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(),
                    "application/json",
                    f"ResearchRun@{produced.schema_version}",
                )
                source_html_write = None
                request_fp = self._hash(
                    {
                        "manifest": assembled.manifest,
                        "estimates": assembled.estimates,
                        "research_inputs": assembled.research_inputs.identity_payload(),
                        "as_of_date": assembled.as_of_date,
                        "profile": assembled.profile,
                    }
                )
                new_record = ResearchRecord(
                    research_run_id=produced.run_id,
                    research_input_fingerprint=research_fp,
                    research_projection_id=projection_id,
                    research_snapshot_id=snapshot_id,
                    request_fingerprint=request_fp,
                    engine_schema_version=produced.schema_version,
                    engine_code_identity=self.engine_identity,
                    original_cutoff_date=assembled.as_of_date,
                    status=produced.status,
                )
                record = new_record
                disposition = ReferenceDisposition.CREATED
                break
              except ResearchExecutionError as error:
                if error.retryable and retry_count < 2:
                    self.repository.record_transition(MarkRetryable(run_id, node, attempt, owner, error.code))
                    retry_count += 1
                    node, attempt = self.repository.record_transition(BeginNode(run_id, contract, fp, owner))
                    self._fault("workflow.node_attempt_started:run_or_link_research")
                    time.sleep(min(0.01 * (2 ** (retry_count - 1)), 0.05))
                    continue
                self._fail_node(
                    run_id,
                    node,
                    attempt,
                    owner,
                    "RESEARCH_ENGINE_FAILED",
                    substep=error.substep,
                    cause_type=error.cause_type,
                )
              except (ProjectionError, ValueError) as error:
                self._fail_node(
                    run_id,
                    node,
                    attempt,
                    owner,
                    "RESEARCH_ENGINE_FAILED",
                    substep="research_request.assemble",
                    cause_type=type(error).__name__,
                )
              except Exception as error:
                self._fail_node(
                    run_id,
                    node,
                    attempt,
                    owner,
                    "RESEARCH_ENGINE_FAILED",
                    substep="research_node.unexpected",
                    cause_type=type(error).__name__,
                )
        else:
            disposition = ReferenceDisposition.REUSED
            source_json_write = None
            source_html_write = None
        try:
            artifact_bundle = ResearchArtifactBundle(
                research_run_id=record.research_run_id,
                data_snapshot_id=snapshot_id,
                code_identity=self.engine_identity,
                drafts=request.analysis_artifacts,
                workflow_run_id=run_id,
                market_data_snapshot_id=request.workflow_snapshot_id,
                research_record=new_record,
            )
            prepared_artifacts = self.repository.load(
                ArtifactBundlePreviewQuery(artifact_bundle)
            )
        except (WorkflowPersistenceError, ValueError, KeyError) as error:
            self._fail_node(
                run_id,
                node,
                attempt,
                owner,
                "RESEARCH_ARTIFACT_PERSISTENCE_FAILED",
                substep="research_artifact.preview",
                cause_type=type(error).__name__,
            )
        except Exception as error:
            self._fail_node(
                run_id,
                node,
                attempt,
                owner,
                "RESEARCH_ARTIFACT_PERSISTENCE_FAILED",
                substep="research_artifact.preview.unexpected",
                cause_type=type(error).__name__,
            )
        typed_views = prepared_artifacts.views
        by_kind = {item.artifact_kind: item for item in typed_views}
        if not {"DataSnapshot", "Forecast", "Valuation"}.issubset(by_kind):
            self._fail_node(
                run_id, node, attempt, owner, "RESEARCH_VIEW_INPUT_INCOMPLETE"
            )
        research_payload = (
            produced.to_dict()
            if disposition is ReferenceDisposition.CREATED
            else self.repository.load(ResearchPayloadQuery(record.research_run_id))
        )
        decision_view = ResearchDecisionViewBuilder().build(ResearchDecisionInput(
            workflow_run_id=run_id,
            data_snapshot=by_kind["DataSnapshot"],
            forecast=by_kind["Forecast"],
            valuation=by_kind["Valuation"],
            simulation=by_kind.get("Simulation"),
            market_data_snapshot=by_kind.get("MarketDataSnapshot"),
            market_path=by_kind.get("MarketPathSimulation"),
            research_run_payload=research_payload,
            projection=request.projection,
            trusted_source_validation=trusted_source_validation,
        ))
        decision_payload = decision_view.to_dict()
        decision_json_write = ArtifactPayload(
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
        decision_html_write = ArtifactPayload(
            render_research_decision_html(decision_view).encode(),
            "text/html",
            "ResearchDecisionHtml@1",
        )
        if disposition is ReferenceDisposition.CREATED:
            source_html_write = ArtifactPayload(
                encode_research_source_html(
                    record.research_run_id, record.engine_schema_version
                ),
                "text/html",
                "ResearchSourceIdentityHtml@1",
            )
        self._fault("workflow.research_artifacts_persisted")
        self._fault("workflow.before_node_success:run_or_link_research")
        checkpoint = self.repository.commit_checkpoint(
            CommitResearchNode(
                run_id,
                node,
                attempt,
                owner,
                disposition,
                new_record,
                record,
                projection_artifact,
                source_json_write,
                source_html_write,
                decision_json_write,
                decision_html_write,
                artifact_bundle,
            )
        )
        record = checkpoint.record
        run_members = checkpoint.members
        self._fault("workflow.research_checkpoint_committed")
        return record, disposition, run_members, node, attempt

    def _fail_node(
        self,
        run_id: str,
        node: str,
        attempt: str,
        owner: str,
        code: str,
        *,
        substep: str | None = None,
        cause_type: str | None = None,
    ) -> NoReturn:
        node_name = self.repository.load(NodeNameQuery(node))
        contract = self._node(node_name)
        if code not in contract.failure_codes:
            code = contract.failure_codes[0]
        evidence = {"error_code": code}
        if substep is not None:
            evidence["failing_substep"] = substep
        if cause_type is not None:
            evidence["redacted_cause_type"] = cause_type
        diagnostic = ArtifactPayload(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode(),
            "application/json",
            "WorkflowDiagnostic@1",
        )
        self.repository.record_transition(FailExecution(run_id, node, attempt, owner, code, diagnostic))
        raise WorkflowError(code, run_id)

    @staticmethod
    def _node(node_id: str) -> NodeDefinition: return next(n for n in _RESEARCH_WORKFLOW.nodes if n.node_id == node_id)
    @staticmethod
    def _hash(value: object) -> str: return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    @contextmanager
    def _supervise_lease(self, run_id: str, owner: str, lease_seconds: int):
        stopped = threading.Event()
        failures: list[Exception] = []

        def renew() -> None:
            interval = max(0.1, lease_seconds / 3)
            while not stopped.wait(interval):
                try:
                    self.repository.record_transition(Heartbeat(run_id, owner, lease_seconds))
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
