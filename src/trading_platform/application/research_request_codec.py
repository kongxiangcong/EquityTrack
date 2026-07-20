from __future__ import annotations

import json

from trading_platform.domain.workflow import (
    FieldSemantics,
    ImmutableArtifactDraft,
    ResearchProjection,
    ResearchWorkflowRequest,
)
from trading_platform.domain.research_inputs import ResearchInputs


class ResearchRequestCodecError(ValueError):
    def __init__(self, cause_type: str) -> None:
        super().__init__("RESEARCH_REQUEST_INVALID")
        self.code = "RESEARCH_REQUEST_INVALID"
        self.substep = "research_request.decode"
        self.cause_type = cause_type


def decode_research_workflow_request(payload: bytes) -> ResearchWorkflowRequest:
    """Decode the one persisted ResearchWorkflowRequest contract."""
    try:
        raw = json.loads(payload)
        projection = raw["projection"]
        projection["research_inputs"] = ResearchInputs.from_mapping(
            projection["research_inputs"]
        )
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
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ResearchRequestCodecError(type(error).__name__) from None


__all__ = ["ResearchRequestCodecError", "decode_research_workflow_request"]
