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
    ResearchProjection,
    ResearchWorkflowResult,
    WorkflowDefinition,
    WorkflowHistory,
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
class CompletedResearchQuery:
    workflow_node_run_id: str


@dataclass(frozen=True)
class ResearchRecordQuery:
    research_run_id: str | None = None
    research_input_fingerprint: str | None = None
    engine_code_identity: str | None = None


@dataclass(frozen=True)
class ResearchRecord:
    research_run_id: str
    research_input_fingerprint: str
    research_projection_id: str
    research_snapshot_id: str
    request_fingerprint: str
    engine_schema_version: int
    engine_code_identity: str
    original_cutoff_date: str
    status: str
    canonical_json_artifact_id: str | None = None
    html_artifact_id: str | None = None


@dataclass(frozen=True)
class NodeNameQuery:
    workflow_node_run_id: str


@dataclass(frozen=True)
class SnapshotEvidenceQuery:
    data_snapshot_id: str


@dataclass(frozen=True)
class ProjectionEvidenceQuery:
    research_projection_id: str


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
class CompletedResearch:
    record: ResearchRecord
    disposition: ReferenceDisposition
    members: tuple[tuple[str, str, str], ...]
    workflow_node_attempt_id: str


@dataclass(frozen=True)
class SnapshotEvidence:
    purpose: str
    members: Mapping[str, str]


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
class ProjectionEvidence:
    research_projection_id: str
    research_snapshot_id: str
    projection_artifact_id: str
    research_input_fingerprint: str
    security_id: str
    as_of_date: str
    snapshot_purpose: str
    freshness_status: str
    quality_status: str


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
class MaintenanceActiveQuery:
    pass


@dataclass(frozen=True)
class ObjectInventoryQuery:
    pass


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
class CommitResearchNode:
    workflow_run_id: str
    workflow_node_run_id: str
    workflow_node_attempt_id: str
    owner_token: str
    disposition: ReferenceDisposition
    new_record: ResearchRecord | None
    record: ResearchRecord
    projection_artifact_id: str
    json_artifact: ArtifactPayload | None
    html_artifact: ArtifactPayload | None
    artifact_bundle: ResearchArtifactBundle


@dataclass(frozen=True)
class ResearchCheckpointResult:
    manifest_id: str
    record: ResearchRecord
    members: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class FreezeProjection:
    security_id: str
    projection: ResearchProjection
    projection_fingerprint: str


@dataclass(frozen=True)
class PreparedProjection:
    research_projection_id: str
    research_snapshot_id: str
    projection_artifact_id: str
    disposition: ReferenceDisposition


@dataclass(frozen=True)
class ProjectionPreviewQuery:
    freeze: FreezeProjection


@dataclass(frozen=True)
class ProjectionCheckpointCommit:
    workflow_run_id: str
    workflow_node_run_id: str
    workflow_node_attempt_id: str
    owner_token: str
    freeze: FreezeProjection
    workflow_snapshot_id: str | None


@dataclass(frozen=True)
class ProjectionCheckpointResult:
    manifest_id: str
    projection: PreparedProjection


@dataclass(frozen=True)
class ForecastReviewCommit:
    draft: ImmutableArtifactDraft
    parent_record_ids: tuple[str, str, str]
    code_identity: str


@dataclass(frozen=True)
class FinalizeResearchSuccess:
    workflow_run_id: str
    owner_token: str
    run_node_id: str
    run_attempt_id: str
    final_node_id: str
    final_attempt_id: str
    disposition: ReferenceDisposition
    record: ResearchRecord
    run_members: tuple[tuple[str, str, str], ...]
    projection_id: str
    workflow_snapshot_id: str | None
    reason_code: str
    stale_by_days: int
    candidate_member_ids: tuple[str, ...]
    market_only_member_ids: tuple[str, ...]
    terminal_status: str


@dataclass(frozen=True)
class ResearchArtifactBundle:
    research_run_id: str
    data_snapshot_id: str
    code_identity: str
    drafts: tuple[ImmutableArtifactDraft, ...]
    workflow_run_id: str | None = None
    market_data_snapshot_id: str | None = None
    research_record: ResearchRecord | None = None


@dataclass(frozen=True)
class PreparedArtifactBundle:
    record_ids: tuple[str, ...]
    views: tuple[ResearchArtifactView, ...]
    members: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ArtifactBundlePreviewQuery:
    bundle: ResearchArtifactBundle


@dataclass(frozen=True)
class GenericObjectCommit:
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
    | CompletedResearch
    | SnapshotEvidence
    | CheckpointView
    | ProjectionEvidence
    | WorkspaceWorkflowEvidence
    | ResearchWorkflowResult
    | WorkflowHistory
    | ArtifactManifestView
    | ResearchArtifactView
    | ResearchRecord
    | Mapping[str, object]
    | tuple[Mapping[str, object], ...]
    | tuple[DurableObject, ...]
    | PreparedArtifactBundle
    | PreparedProjection
    | bytes
    | str
    | bool
    | None
)

LedgerQuery: TypeAlias = (
    WorkflowRunQuery
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
    | MaintenanceActiveQuery
    | ObjectInventoryQuery
    | PersistenceCountsQuery
    | ArtifactBundlePreviewQuery
    | ProjectionPreviewQuery
)


TransitionCommand: TypeAlias = (
    AcquireLease | Heartbeat | RequestCancellation | StopIfCancelled
    | BeginNode | MarkRetryable | FailExecution
)
ArtifactCommit: TypeAlias = ForecastReviewCommit | GenericObjectCommit
CheckpointCommit: TypeAlias = (
    CommitResearchNode | ProjectionCheckpointCommit
)
CheckpointResult: TypeAlias = (
    str | ProjectionCheckpointResult | ResearchCheckpointResult | None
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
    @overload
    def commit_checkpoint(self, command: CommitResearchNode) -> ResearchCheckpointResult: ...
    @overload
    def commit_checkpoint(self, command: ProjectionCheckpointCommit) -> ProjectionCheckpointResult: ...
    def commit_checkpoint(self, command: CheckpointCommit) -> CheckpointResult: ...
    @overload
    def commit_artifacts(self, command: GenericObjectCommit) -> ObjectCommitResult: ...
    @overload
    def commit_artifacts(self, command: ForecastReviewCommit) -> str: ...
    def commit_artifacts(self, command: ArtifactCommit) -> ObjectCommitResult | str: ...
    def complete(self, command: FinalizeResearchSuccess) -> str: ...
    @overload
    def load(self, query: WorkflowRunQuery) -> WorkflowLedgerView: ...
    @overload
    def load(self, query: ResearchRunIdentityQuery) -> ResearchRunIdentity: ...
    @overload
    def load(self, query: WorkflowReferencesQuery) -> Mapping[str, str]: ...
    @overload
    def load(self, query: CompletedResearchQuery) -> CompletedResearch: ...
    @overload
    def load(self, query: ResearchRecordQuery) -> ResearchRecord | None: ...
    @overload
    def load(self, query: NodeNameQuery) -> str: ...
    @overload
    def load(self, query: SnapshotEvidenceQuery) -> SnapshotEvidence: ...
    @overload
    def load(self, query: ProjectionEvidenceQuery) -> ProjectionEvidence | None: ...
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
    def load(self, query: MaintenanceActiveQuery) -> bool: ...
    @overload
    def load(self, query: ObjectInventoryQuery) -> tuple[DurableObject, ...]: ...
    @overload
    def load(self, query: PersistenceCountsQuery) -> Mapping[str, object]: ...
    @overload
    def load(self, query: ArtifactBundlePreviewQuery) -> PreparedArtifactBundle: ...
    @overload
    def load(self, query: ProjectionPreviewQuery) -> PreparedProjection: ...
    def load(self, query: LedgerQuery) -> LedgerLoadResult: ...
    def audit_integrity(self, scope: IntegrityScope) -> IntegrityReport: ...
