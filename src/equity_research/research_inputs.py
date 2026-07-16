from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ResearchInputs:
    """Typed research controls after legacy context migration."""

    schema_version: str = "ResearchInputs@1"
    migration_diagnostics: tuple[str, ...] = ()
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

    def identity_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchInputMigration:
    inputs: ResearchInputs
    diagnostics: tuple[str, ...]


class LegacyResearchContextAdapter:
    """The only compatibility seam allowed to read pre-typed magic keys."""

    VERSION = "legacy_research_context_adapter@1"

    @classmethod
    def adapt(
        cls,
        context: Mapping[str, Any] | None,
    ) -> ResearchInputMigration:
        raw = context if isinstance(context, Mapping) else {}

        def mappings(name: str) -> tuple[Mapping[str, Any], ...]:
            value = raw.get(name)
            if not isinstance(value, list):
                return ()
            return tuple(item for item in value if isinstance(item, Mapping))

        def mapping(name: str) -> Mapping[str, Any] | None:
            value = raw.get(name)
            return value if isinstance(value, Mapping) else None

        historical = mappings("historical_multiples")
        consumed = {
            "report_version",
            "company_type",
            "executive_summary",
            "theses",
            "risks",
            "catalysts",
            "scenarios",
            "conditional_plan",
            "analyses",
            "debate",
            "synthesis",
            "dcf_case",
            "peer_case",
            "peer_count",
            "historical_multiples",
            "historical_metric",
            "mid_cycle_case",
        }
        ignored = tuple(sorted(str(key) for key in raw if key not in consumed))
        diagnostics = (
            (
                f"LEGACY_RESEARCH_CONTEXT_MIGRATED:{cls.VERSION}:"
                "free-form context was converted to ResearchInputs@1"
            ),
            *(
                (
                    "LEGACY_RESEARCH_CONTEXT_KEYS_IGNORED:"
                    + ",".join(ignored),
                )
                if ignored
                else ()
            ),
        )
        inputs = ResearchInputs(
            migration_diagnostics=diagnostics,
            report_version=int(raw.get("report_version", 0) or 0),
            company_type=str(raw.get("company_type", "general")).strip()
            or "general",
            executive_summary=str(raw.get("executive_summary", "")).strip(),
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
            peer_count=(
                int(raw.get("peer_count", 0))
                if isinstance(raw.get("peer_count", 0), int)
                else 0
            ),
            historical_multiples=historical,
            historical_metric=str(
                raw.get("historical_metric", "pe")
            ).strip()
            or "pe",
            mid_cycle_case=mapping("mid_cycle_case"),
        )
        return ResearchInputMigration(inputs, diagnostics)
