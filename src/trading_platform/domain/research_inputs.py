from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ResearchInputs:
    """Canonical typed controls consumed by deterministic research."""

    schema_version: str = "ResearchInputs@1"
    report_version: int = 0
    company_type: str = "general"
    executive_summary: str = ""
    theses: tuple[Mapping[str, Any], ...] = ()
    risks: tuple[Mapping[str, Any], ...] = ()
    catalysts: tuple[Mapping[str, Any], ...] = ()
    scenarios: tuple[Mapping[str, Any], ...] = ()
    conditional_plan: tuple[Mapping[str, Any], ...] = ()
    analyses: Mapping[str, Any] | None = None
    debate: Mapping[str, Any] | None = None
    synthesis: Mapping[str, Any] | None = None
    dcf_case: Mapping[str, Any] | None = None
    peer_case: Mapping[str, Any] | None = None
    peer_count: int = 0
    historical_multiples: tuple[Mapping[str, Any], ...] = ()
    historical_metric: str = "pe"
    mid_cycle_case: Mapping[str, Any] | None = None
    workflow_research_member_ids: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResearchInputs":
        """Decode the external JSON representation into the sole typed contract."""

        if not isinstance(value, dict) or any(
            not isinstance(key, str) for key in value
        ):
            raise TypeError("ResearchInputs must be a JSON object with string keys")

        allowed = {
            "schema_version", "report_version", "company_type",
            "executive_summary", "theses", "risks", "catalysts", "scenarios",
            "conditional_plan", "analyses", "debate", "synthesis", "dcf_case",
            "peer_case", "peer_count", "historical_multiples",
            "historical_metric", "mid_cycle_case", "workflow_research_member_ids",
        }
        unknown = sorted(str(key) for key in value if key not in allowed)
        if unknown:
            raise ValueError("Unknown ResearchInputs fields: " + ",".join(unknown))

        def mappings(name: str) -> tuple[Mapping[str, Any], ...]:
            raw = value.get(name, [])
            if not isinstance(raw, list) or not all(
                isinstance(item, dict) for item in raw
            ):
                raise TypeError(f"ResearchInputs.{name} must be a JSON array of objects")
            return tuple(raw)

        def mapping(name: str) -> Mapping[str, Any] | None:
            raw = value.get(name)
            if raw is not None and not isinstance(raw, dict):
                raise TypeError(f"ResearchInputs.{name} must be a JSON object or null")
            return raw

        def text(name: str, default: str) -> str:
            raw = value.get(name, default)
            if not isinstance(raw, str):
                raise TypeError(f"ResearchInputs.{name} must be a string")
            return raw.strip() or default

        schema_version = text("schema_version", "ResearchInputs@1")
        if schema_version != "ResearchInputs@1":
            raise ValueError("Unsupported ResearchInputs schema")
        report_version = value.get("report_version", 0)
        peer_count = value.get("peer_count", 0)
        if type(report_version) is not int or type(peer_count) is not int:
            raise TypeError("ResearchInputs numeric fields must be integers")
        member_ids = value.get("workflow_research_member_ids", [])
        if not isinstance(member_ids, list) or not all(
            isinstance(item, str) and item for item in member_ids
        ):
            raise TypeError(
                "ResearchInputs.workflow_research_member_ids must be a JSON array of non-empty strings"
            )
        return cls(
            schema_version=schema_version,
            report_version=report_version,
            company_type=text("company_type", "general"),
            executive_summary=text("executive_summary", ""),
            theses=mappings("theses"),
            risks=mappings("risks"),
            catalysts=mappings("catalysts"),
            scenarios=mappings("scenarios"),
            conditional_plan=mappings("conditional_plan"),
            analyses=mapping("analyses"),
            debate=mapping("debate"),
            synthesis=mapping("synthesis"),
            dcf_case=mapping("dcf_case"),
            peer_case=mapping("peer_case"),
            peer_count=peer_count,
            historical_multiples=mappings("historical_multiples"),
            historical_metric=text("historical_metric", "pe"),
            mid_cycle_case=mapping("mid_cycle_case"),
            workflow_research_member_ids=tuple(member_ids),
        )

    def identity_payload(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["ResearchInputs"]
