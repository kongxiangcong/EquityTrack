from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class WorkflowStatus(str, Enum):
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_LIMITS = "succeeded_with_limits"
    FAILED = "failed"


class ReferenceDisposition(str, Enum):
    CREATED = "created"
    REUSED = "reused"
    INPUT = "input"


@dataclass(frozen=True)
class FieldSemantics:
    source_id: str
    source_authority: str
    field_name: str
    period: str
    statement_scope: str
    unit: str
    currency: str
    scale: str
    restatement_status: str
    published_at: str
    available_at: str
    retrieved_at: str
    supersedes_identity: str | None = None
    availability_basis: str = "publisher_timestamp"


@dataclass(frozen=True)
class ResearchProjection:
    manifest: Mapping[str, Any]
    estimates: Mapping[str, Any] | None
    context: Mapping[str, Any] | None
    as_of_date: str
    profile: str
    field_semantics: tuple[FieldSemantics, ...]
    diluted_share_identity: str
    net_debt_bridge_identity: str


@dataclass(frozen=True)
class ResearchWorkflowRequest:
    invocation_id: str
    security_id: str
    requested_date: str
    effective_session_date: str
    projection: ResearchProjection
    workflow_snapshot_id: str | None = None
    candidate_member_ids: tuple[str, ...] = ()
    market_only_member_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchWorkflowResult:
    workflow_run_id: str
    research_run_id: str
    research_snapshot_id: str
    workflow_snapshot_id: str | None
    final_manifest_id: str
    disposition: ReferenceDisposition
    reason_code: str
    stale_by_days: int
    json_artifact_id: str
    html_artifact_id: str


@dataclass(frozen=True)
class WorkflowHistory:
    workflow_run_id: str
    status: str
    refs: tuple[Mapping[str, str], ...]
    attempts: tuple[Mapping[str, Any], ...]
    transitions: tuple[Mapping[str, Any], ...]
    reuse_decision: Mapping[str, Any]
    final_manifest_id: str


@dataclass(frozen=True)
class ArtifactManifestView:
    artifact_manifest_id: str
    manifest_role: str
    producer_type: str
    producer_id: str
    membership_hash: str
    members: tuple[Mapping[str, Any], ...]
