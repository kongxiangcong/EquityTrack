from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyResearchRequestAudit:
    invocation_id: str
    security_id: str
    requested_date: str
    effective_session_date: str
    research_projection_id: str


def decode_request_v1_for_audit(payload: bytes) -> LegacyResearchRequestAudit:
    """Decode only identity fields needed to prove a safe schema-0014 migration."""
    try:
        raw = json.loads(payload)
        projection = raw["projection"]
        if not isinstance(raw, dict) or not isinstance(projection, dict):
            raise TypeError
        return LegacyResearchRequestAudit(
            invocation_id=_required_text(raw, "invocation_id"),
            security_id=_required_text(raw, "security_id"),
            requested_date=_required_text(raw, "requested_date"),
            effective_session_date=_required_text(
                raw, "effective_session_date"
            ),
            research_projection_id=_required_text(
                projection, "research_projection_id"
            ),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("LEGACY_RESEARCH_REQUEST_AUDIT_INVALID") from error


def _required_text(value: dict[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item:
        raise ValueError(key)
    return item


__all__ = ["LegacyResearchRequestAudit", "decode_request_v1_for_audit"]
