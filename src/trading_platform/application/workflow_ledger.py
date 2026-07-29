from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, overload, Protocol, TypeAlias

from trading_platform.domain.workflow import (
    ArtifactManifestView,
    ImmutableArtifactDraft,
    NodeDefinition,
    ReferenceDisposition,
    ResearchArtifactView,
    WorkflowDefinition,
    WorkflowHistory,
)
from trading_platform.domain.research_evaluation import (
    ResearchWorkflowRequest,
    ResearchWorkflowResult,
)


class WorkflowPersistenceError(ValueError):
    def __init__(self, code: str, operation: str, entity_ref: str) -> None:
        self.code = code
        self.operation = operation
        self.entity_ref = entity_ref
        super().__init__(code)


class StartDisposition(str, Enum):
    CREATED = "created"
    REPLAYED = "replayed"


@dataclass(frozen=True)
class StartWorkflow:
    invocation_id: str
    request_fingerprint: str
    requested_date: str
    effective_session_date: str
    definition: WorkflowDefinition
    owner_token: str
    request_payload: bytes
    request_schema: str
    lease_seconds: int = 30


@dataclass(frozen=True)
class StartOutcome:
    workflow_run_id: str
    disposition: StartDisposition


@dataclass(frozen=True)
class WorkflowLedgerView:
    workflow_run_id: str
    status: str
    request_payload: bytes


@dataclass(frozen=True)
class WorkflowRunQuery:
    workflow_run_id: str


@dataclass(frozen=True)
class ResearchRunIdentityQuery:
    research_run_id: str


@dataclass(frozen=True)
class ResearchRunIdentity:
    research_run_id: str
    code_identity: str


@dataclass(frozen=True)
class WorkflowReferencesQuery:
    workflow_run_id: str


@dataclass(frozen=True)
class CompletedEvaluationQuery:
    workflow_node_run_id: str


@dataclass(frozen=True)
class ResearchEvaluationRecordQuery:
    evaluation_fingerprint: str
    engine_code_identity: str


@dataclass(frozen=True)
class ResearchEvaluationRecord:
    research_run_id: str
    evaluation_fingerprint: str
    evaluation_plan_id: str
    data_snapshot_id: str
    request_fingerprint: str
    engine_schema_version: int
    engine_code_identity: str
    original_cutoff_date: str
    status: str
    canonical_json_artifact_id: str | None = None


@dataclass(frozen=True)
class NodeNameQuery:
    workflow_node_run_id: str


@dataclass(frozen=True)
class SnapshotEvidenceQuery:
    data_snapshot_id: str


@dataclass(frozen=True)
class WorkspaceWorkflowQuery:
    security_id: str


@dataclass(frozen=True)
class WorkspaceWorkflowEvidence:
    workflows: tuple[Mapping[str, object], ...]
    manifests: tuple[Mapping[str, object], ...]
    research_runs: tuple[Mapping[str, object], ...]
    artifact_uses: tuple[Mapping[str, object], ...]
    forecast_artifact_record_ids: tuple[str, ...]
    forecast_review_artifact_record_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompletedEvaluation:
    checkpoint: EvaluationCheckpointResult
    workflow_node_attempt_id: str


@dataclass(frozen=True)
class SnapshotEvidence:
    data_snapshot_id: str
    scope_id: str
    purpose: str
    requested_date: str
    effective_session_date: str
    as_of_at: str
    source_policy_identity: str
    freshness_status: str
    members: Mapping[str, str]
    member_evidence: tuple["SnapshotMemberEvidence", ...]
    quality_status: str
    coverage_expected: int
    coverage_eligible: int
    coverage_excluded: int
    coverage_missing: int


@dataclass(frozen=True)
class SnapshotMemberEvidence:
    normalized_version_id: str
    dataset: str
    source_identity: str
    source_authority: str
    real_source_url: str
    retrieved_at: str
    published_at: str
    available_at: str
    quality_status: str
    extracted_fields: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class RequestPayloadQuery:
    workflow_run_id: str


@dataclass(frozen=True)
class CheckpointQuery:
    workflow_run_id: str
    definition: NodeDefinition
    fingerprint: str


@dataclass(frozen=True)
class CheckpointView:
    workflow_node_run_id: str


@dataclass(frozen=True)
class CheckpointMembersQuery:
    workflow_node_run_id: str


@dataclass(frozen=True)
class CheckpointMember:
    artifact_id: str
    member_role: str
    direction: str
    schema_version: str


@dataclass(frozen=True)
class WorkflowResultQuery:
    workflow_run_id: str


@dataclass(frozen=True)
class WorkflowHistoryQuery:
    workflow_run_id: str


@dataclass(frozen=True)
class ManifestQuery:
    artifact_manifest_id: str


@dataclass(frozen=True)
class ResearchArtifactQuery:
    artifact_record_id: str


@dataclass(frozen=True)
class ResearchPayloadQuery:
    research_run_id: str


@dataclass(frozen=True)
class DecisionViewPayloadQuery:
    workflow_run_id: str


@dataclass(frozen=True)
class DecisionViewPayload:
    manifest_id: str
    json_artifact_id: str
    html_artifact_id: str
    pdf_artifact_id: str
    json_bytes: bytes
    html_bytes: bytes
    pdf_bytes: bytes


@dataclass(frozen=True)
class NonterminalWorkflowQuery:
    pass


@dataclass(frozen=True)
class ObjectInventoryQuery:
    pass


@dataclass(frozen=True)
class WorkflowDiagnosticQuery:
    diagnostic_artifact_id: str


@dataclass(frozen=True)
class PersistenceCountsQuery:
    pass


@dataclass(frozen=True)
class AcquireLease:
    workflow_run_id: str
    owner_token: str
    definition: WorkflowDefinition
    lease_seconds: int


@dataclass(frozen=True)
class Heartbeat:
    workflow_run_id: str
    owner_token: str
    lease_seconds: int = 30


@dataclass(frozen=True)
class RequestCancellation:
    workflow_run_id: str
    reason: str


@dataclass(frozen=True)
class StopIfCancelled:
    workflow_run_id: str


@dataclass(frozen=True)
class BeginNode:
    workflow_run_id: str
    definition: NodeDefinition
    fingerprint: str
    owner_token: str
    lease_seconds: int = 30


@dataclass(frozen=True)
class MarkRetryable:
    workflow_run_id: str
    workflow_node_run_id: str
    workflow_node_attempt_id: str
    owner_token: str
    code: str


@dataclass(frozen=True)
class FailExecution:
    workflow_run_id: str
    workflow_node_run_id: str
    workflow_node_attempt_id: str
    owner_token: str
    error_code: str
    diagnostic: ArtifactPayload


@dataclass(frozen=True)
class ArtifactPayload:
    payload: bytes
    media_type: str
    schema_version: str


@dataclass(frozen=True)
class CommitEvaluationNode:
    workflow_run_id: str
    workflow_node_run_id: str
    workflow_node_attempt_id: str
    owner_token: str
    request: ResearchWorkflowRequest
    evaluation_fingerprint: str
    engine_code_identity: str
    research_json_artifact: ArtifactPayload
    decision_json_artifact: ArtifactPayload
    decision_html_artifact: ArtifactPayload
    decision_pdf_artifact: ArtifactPayload


@dataclass(frozen=True)
class EvaluationCheckpointResult:
    record: ResearchEvaluationRecord
    disposition: ReferenceDisposition
    manifest_id: str
    decision_manifest_id: str
    members: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class ForecastReviewCommit:
    draft: ImmutableArtifactDraft
    parent_record_ids: tuple[str, str, str]
    code_identity: str


@dataclass(frozen=True)
class FinalizeEvaluationSuccess:
    workflow_run_id: str
    owner_token: str
    evaluation_node_id: str
    evaluation_attempt_id: str
    final_node_id: str
    final_attempt_id: str
    checkpoint: EvaluationCheckpointResult
    data_snapshot_id: str
    workflow_snapshot_id: str | None
    terminal_status: str


@dataclass(frozen=True)
class GenericObjectCommit:
    payload: bytes


@dataclass(frozen=True)
class ManualReviewManifestCommit:
    workflow_run_id: str
    payload: bytes
    content_hash: str


@dataclass(frozen=True)
class ManualReviewManifestCommitResult:
    object_sha256: str
    artifact_manifest_id: str


@dataclass(frozen=True)
class FinalizeManualReviewWorkflow:
    workflow_run_id: str
    terminal_status: str
    artifact_manifest_id: str
    completed_at: str


@dataclass(frozen=True)
class QualificationReceiptCommit:
    invocation_id: str
    request_hash: str
    payload: bytes


@dataclass(frozen=True)
class QualificationReceiptQuery:
    artifact_id: str


@dataclass(frozen=True)
class QualificationReceiptReplayQuery:
    invocation_id: str
    request_hash: str


@dataclass(frozen=True)
class QualificationReceiptReplay:
    artifact_id: str
    payload: bytes


@dataclass(frozen=True)
class ObjectCommitResult:
    sha256: str
    disposition: ReferenceDisposition


@dataclass(frozen=True)
class IntegrityReport:
    errors: tuple[str, ...]


@dataclass(frozen=True)
class IntegrityScope:
    workflow_run_id: str | None = None


@dataclass(frozen=True)
class DurableObject:
    sha256: str
    size_bytes: int
    relative_path: str


LedgerLoadResult: TypeAlias = (
    WorkflowLedgerView
    | ResearchRunIdentity
    | CompletedEvaluation
    | SnapshotEvidence
    | CheckpointView
    | WorkspaceWorkflowEvidence
    | ResearchWorkflowResult
    | WorkflowHistory
    | ArtifactManifestView
    | ResearchArtifactView
    | ResearchEvaluationRecord
    | Mapping[str, object]
    | tuple[Mapping[str, object], ...]
    | tuple[DurableObject, ...]
    | DecisionViewPayload
    | tuple[CheckpointMember, ...]
    | QualificationReceiptReplay
    | EvaluationCheckpointResult
    | bytes
    | str
    | bool
    | None
)

LedgerQuery: TypeAlias = (
    WorkflowRunQuery
    | ResearchRunIdentityQuery
    | WorkflowReferencesQuery
    | CompletedEvaluationQuery
    | ResearchEvaluationRecordQuery
    | NodeNameQuery
    | SnapshotEvidenceQuery
    | WorkspaceWorkflowQuery
    | RequestPayloadQuery
    | CheckpointQuery
    | CheckpointMembersQuery
    | WorkflowResultQuery
    | WorkflowHistoryQuery
    | ManifestQuery
    | ResearchArtifactQuery
    | ResearchPayloadQuery
    | DecisionViewPayloadQuery
    | NonterminalWorkflowQuery
    | ObjectInventoryQuery
    | WorkflowDiagnosticQuery
    | PersistenceCountsQuery
    | QualificationReceiptQuery
    | QualificationReceiptReplayQuery
)


TransitionCommand: TypeAlias = (
    AcquireLease | Heartbeat | RequestCancellation | StopIfCancelled
    | BeginNode | MarkRetryable | FailExecution
)
ArtifactCommit: TypeAlias = (
    ForecastReviewCommit
    | GenericObjectCommit
    | ManualReviewManifestCommit
    | QualificationReceiptCommit
)
CheckpointCommit: TypeAlias = CommitEvaluationNode
CheckpointResult: TypeAlias = (
    str | EvaluationCheckpointResult | None
)


class WorkflowLedgerPort(Protocol):
    def start_or_replay(self, command: StartWorkflow) -> StartOutcome: ...
    @overload
    def record_transition(self, command: BeginNode) -> tuple[str, str]: ...
    @overload
    def record_transition(self, command: AcquireLease) -> None: ...
    @overload
    def record_transition(self, command: Heartbeat | RequestCancellation | StopIfCancelled | MarkRetryable | FailExecution) -> None: ...
    def record_transition(self, command: TransitionCommand) -> tuple[str, str] | None: ...
    def commit_checkpoint(
        self, command: CommitEvaluationNode
    ) -> EvaluationCheckpointResult: ...
    def commit_checkpoint(self, command: CheckpointCommit) -> CheckpointResult: ...
    @overload
    def commit_artifacts(self, command: GenericObjectCommit) -> ObjectCommitResult: ...
    @overload
    def commit_artifacts(
        self, command: ManualReviewManifestCommit
    ) -> ManualReviewManifestCommitResult: ...
    @overload
    def commit_artifacts(self, command: ForecastReviewCommit) -> str: ...
    @overload
    def commit_artifacts(self, command: QualificationReceiptCommit) -> str: ...
    def commit_artifacts(
        self, command: ArtifactCommit
    ) -> ObjectCommitResult | ManualReviewManifestCommitResult | str: ...
    @overload
    def complete(self, command: FinalizeEvaluationSuccess) -> str: ...
    @overload
    def complete(self, command: FinalizeManualReviewWorkflow) -> str: ...
    def complete(
        self, command: FinalizeEvaluationSuccess | FinalizeManualReviewWorkflow
    ) -> str: ...
    @overload
    def load(self, query: WorkflowRunQuery) -> WorkflowLedgerView: ...
    @overload
    def load(self, query: ResearchRunIdentityQuery) -> ResearchRunIdentity: ...
    @overload
    def load(self, query: WorkflowReferencesQuery) -> Mapping[str, str]: ...
    def load(
        self, query: CompletedEvaluationQuery
    ) -> CompletedEvaluation: ...
    @overload
    def load(
        self, query: ResearchEvaluationRecordQuery
    ) -> ResearchEvaluationRecord | None: ...
    @overload
    def load(self, query: NodeNameQuery) -> str: ...
    @overload
    def load(self, query: SnapshotEvidenceQuery) -> SnapshotEvidence: ...
    @overload
    def load(self, query: WorkspaceWorkflowQuery) -> WorkspaceWorkflowEvidence: ...
    @overload
    def load(self, query: RequestPayloadQuery) -> bytes: ...
    @overload
    def load(self, query: CheckpointQuery) -> CheckpointView | None: ...
    @overload
    def load(self, query: CheckpointMembersQuery) -> tuple[CheckpointMember, ...]: ...
    @overload
    def load(self, query: WorkflowResultQuery) -> ResearchWorkflowResult: ...
    @overload
    def load(self, query: WorkflowHistoryQuery) -> WorkflowHistory: ...
    @overload
    def load(self, query: ManifestQuery) -> ArtifactManifestView: ...
    @overload
    def load(self, query: ResearchArtifactQuery) -> ResearchArtifactView: ...
    @overload
    def load(self, query: ResearchPayloadQuery) -> Mapping[str, object]: ...

    @overload
    def load(self, query: DecisionViewPayloadQuery) -> DecisionViewPayload: ...

    @overload
    def load(self, query: NonterminalWorkflowQuery) -> bool: ...
    @overload
    def load(self, query: ObjectInventoryQuery) -> tuple[DurableObject, ...]: ...
    @overload
    def load(self, query: WorkflowDiagnosticQuery) -> Mapping[str, object]: ...
    @overload
    def load(self, query: PersistenceCountsQuery) -> Mapping[str, object]: ...
    @overload
    def load(self, query: QualificationReceiptQuery) -> bytes: ...
    @overload
    def load(self, query: QualificationReceiptReplayQuery) -> QualificationReceiptReplay | None: ...
    def load(self, query: LedgerQuery) -> LedgerLoadResult: ...
    def audit_integrity(self, scope: IntegrityScope) -> IntegrityReport: ...
