from __future__ import annotations

import json

from trading_platform.domain.research_evaluation import ResearchWorkflowRequest


class ResearchRequestCodecError(ValueError):
    def __init__(self, cause_type: str) -> None:
        super().__init__("RESEARCH_REQUEST_INVALID")
        self.code = "RESEARCH_REQUEST_INVALID"
        self.substep = "research_request.decode"
        self.cause_type = cause_type


def decode_research_workflow_request(payload: bytes) -> ResearchWorkflowRequest:
    """Decode the sole active persisted research request contract."""

    try:
        raw = json.loads(payload.decode("utf-8"))
        if not isinstance(raw, dict):
            raise TypeError
        expected = {
            "schema_version",
            "invocation_id",
            "security_id",
            "requested_date",
            "effective_session_date",
            "data_snapshot_id",
            "evaluation_plan",
            "workflow_snapshot_id",
            "market_data_snapshot_id",
        }
        missing = expected - set(raw)
        if missing:
            raise KeyError(sorted(missing)[0])
        return ResearchWorkflowRequest.from_mapping(raw)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise ResearchRequestCodecError(type(error).__name__) from None


__all__ = [
    "ResearchRequestCodecError",
    "decode_research_workflow_request",
]
