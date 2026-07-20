from __future__ import annotations

import json

from trading_platform.domain.workflow import (
    FieldSemantics,
    ImmutableArtifactDraft,
    ResearchProjection,
    ResearchWorkflowRequest,
)


def decode_research_workflow_request(payload: bytes) -> ResearchWorkflowRequest:
    """Decode the one persisted ResearchWorkflowRequest contract."""
    raw = json.loads(payload)
    projection = raw["projection"]
    projection["field_semantics"] = tuple(
        FieldSemantics(**item) for item in projection["field_semantics"]
    )
    raw["projection"] = ResearchProjection(**projection)
    raw["candidate_member_ids"] = tuple(raw.get("candidate_member_ids", ()))
    raw["market_only_member_ids"] = tuple(raw.get("market_only_member_ids", ()))
    raw["analysis_artifacts"] = tuple(
        ImmutableArtifactDraft.from_serialized(item)
        for item in raw.get("analysis_artifacts", ())
    )
    return ResearchWorkflowRequest(**raw)
