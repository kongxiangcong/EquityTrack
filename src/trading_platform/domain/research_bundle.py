from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from trading_platform.identity import canonical_hash


class ResearchComponentStatus(str, Enum):
    COMPLETE = "complete"
    LIMITED = "limited"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


_COMPONENTS = frozenset(
    {
        "forecast",
        "scenario_valuation",
        "valuation_method_route",
        "valuation_simulation_decision",
        "market_path_decision",
        "recent_trend_assessment",
    }
)


@dataclass(frozen=True)
class ResearchEvaluationOrigin:
    data_snapshot_id: str
    source_policy_identity: str
    snapshot_member_ids: tuple[str, ...]
    research_policy_identity: str
    estimation_policy_identity: str
    schema_version: str = "ResearchEvaluationOrigin@1"

    def __post_init__(self) -> None:
        if (
            self.schema_version != "ResearchEvaluationOrigin@1"
            or not self.data_snapshot_id
            or not self.source_policy_identity
            or not self.snapshot_member_ids
            or len(self.snapshot_member_ids)
            != len(set(self.snapshot_member_ids))
            or not self.research_policy_identity
            or not self.estimation_policy_identity
        ):
            raise ValueError("RESEARCH_EVALUATION_ORIGIN_INVALID")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "data_snapshot_id": self.data_snapshot_id,
            "source_policy_identity": self.source_policy_identity,
            "snapshot_member_ids": list(self.snapshot_member_ids),
            "research_policy_identity": self.research_policy_identity,
            "estimation_policy_identity": self.estimation_policy_identity,
        }

    @property
    def origin_id(self) -> str:
        return "research_origin_" + canonical_hash(self.canonical_content)[:24]

    def to_dict(self) -> Mapping[str, object]:
        return {"origin_id": self.origin_id, **self.canonical_content}


@dataclass(frozen=True)
class ResearchComponentResult:
    component: str
    status: ResearchComponentStatus
    reason_codes: tuple[str, ...]
    content: Mapping[str, object]
    source_member_ids: tuple[str, ...]
    schema_version: str = "ResearchComponentResult@1"

    def __post_init__(self) -> None:
        if (
            self.schema_version != "ResearchComponentResult@1"
            or self.component not in _COMPONENTS
            or not isinstance(self.status, ResearchComponentStatus)
            or not self.reason_codes
            or len(self.reason_codes) != len(set(self.reason_codes))
            or any(not item for item in self.reason_codes)
            or not isinstance(self.content, Mapping)
            or not self.content
            or len(self.source_member_ids)
            != len(set(self.source_member_ids))
            or (
                self.status
                in {
                    ResearchComponentStatus.COMPLETE,
                    ResearchComponentStatus.LIMITED,
                }
                and not self.source_member_ids
            )
        ):
            raise ValueError("RESEARCH_COMPONENT_RESULT_INVALID")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "component": self.component,
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "content": dict(self.content),
            "source_member_ids": list(self.source_member_ids),
        }

    @property
    def artifact_id(self) -> str:
        return (
            f"{self.component}_"
            + canonical_hash(self.canonical_content)[:24]
        )

    def to_dict(self) -> Mapping[str, object]:
        return {
            "artifact_id": self.artifact_id,
            **self.canonical_content,
        }


@dataclass(frozen=True)
class ResearchEvaluationBundle:
    origin: ResearchEvaluationOrigin
    estimates: Mapping[str, object] | None
    research_run: Mapping[str, object]
    forecast: ResearchComponentResult
    scenario_valuation: ResearchComponentResult
    valuation_method_route: ResearchComponentResult
    valuation_simulation_decision: ResearchComponentResult
    market_path_decision: ResearchComponentResult
    recent_trend_assessment: ResearchComponentResult
    schema_version: str = "ResearchEvaluationBundle@1"

    def __post_init__(self) -> None:
        expected = {
            "forecast": self.forecast,
            "scenario_valuation": self.scenario_valuation,
            "valuation_method_route": self.valuation_method_route,
            "valuation_simulation_decision": (
                self.valuation_simulation_decision
            ),
            "market_path_decision": self.market_path_decision,
            "recent_trend_assessment": self.recent_trend_assessment,
        }
        origin_member_ids = set(self.origin.snapshot_member_ids)
        if (
            self.schema_version != "ResearchEvaluationBundle@1"
            or (
                self.estimates is not None
                and not isinstance(self.estimates, Mapping)
            )
            or not isinstance(self.research_run, Mapping)
            or not self.research_run.get("run_id")
            or any(
                component.component != name
                for name, component in expected.items()
            )
            or any(
                not set(component.source_member_ids).issubset(
                    origin_member_ids
                )
                for component in expected.values()
            )
        ):
            raise ValueError("RESEARCH_EVALUATION_BUNDLE_INVALID")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "origin": self.origin.to_dict(),
            "estimates": (
                dict(self.estimates)
                if self.estimates is not None
                else None
            ),
            "research_run": dict(self.research_run),
            "forecast": self.forecast.to_dict(),
            "scenario_valuation": self.scenario_valuation.to_dict(),
            "valuation_method_route": self.valuation_method_route.to_dict(),
            "valuation_simulation_decision": (
                self.valuation_simulation_decision.to_dict()
            ),
            "market_path_decision": self.market_path_decision.to_dict(),
            "recent_trend_assessment": (
                self.recent_trend_assessment.to_dict()
            ),
        }

    @property
    def bundle_id(self) -> str:
        return "research_bundle_" + canonical_hash(
            self.canonical_content
        )[:24]

    def to_dict(self) -> Mapping[str, object]:
        return {"bundle_id": self.bundle_id, **self.canonical_content}


_ORIGIN_FIELDS = frozenset(
    {
        "origin_id",
        "schema_version",
        "data_snapshot_id",
        "source_policy_identity",
        "snapshot_member_ids",
        "research_policy_identity",
        "estimation_policy_identity",
    }
)
_COMPONENT_FIELDS = frozenset(
    {
        "artifact_id",
        "schema_version",
        "component",
        "status",
        "reason_codes",
        "content",
        "source_member_ids",
    }
)
_BUNDLE_FIELDS = frozenset(
    {
        "bundle_id",
        "schema_version",
        "origin",
        "estimates",
        "research_run",
        *_COMPONENTS,
    }
)


@dataclass(frozen=True)
class VerifiedResearchEvaluationBundle:
    bundle_id: str
    origin: Mapping[str, Any]
    estimates: Mapping[str, Any] | None
    research_run: Mapping[str, Any]
    components: Mapping[str, Mapping[str, Any]]


def _verified_mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _verified_strings(
    value: object,
    *,
    code: str,
    require_nonempty: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (require_nonempty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(code)
    return tuple(value)


def verify_research_evaluation_bundle(
    value: Mapping[str, Any],
    *,
    expected_data_snapshot_id: str,
    expected_source_policy_identity: str,
    expected_snapshot_member_ids: tuple[str, ...],
) -> VerifiedResearchEvaluationBundle:
    """Verify structural identity and frozen-snapshot lineage in one place."""

    expected_members = _verified_strings(
        expected_snapshot_member_ids,
        code="RESEARCH_BUNDLE_EXPECTED_MEMBERS_INVALID",
        require_nonempty=True,
    )
    if (
        not isinstance(value, Mapping)
        or set(value) != _BUNDLE_FIELDS
        or value.get("schema_version") != "ResearchEvaluationBundle@1"
        or not isinstance(value.get("bundle_id"), str)
    ):
        raise ValueError("RESEARCH_EVALUATION_BUNDLE_REQUIRED")

    origin = _verified_mapping(
        value.get("origin"),
        "RESEARCH_BUNDLE_ORIGIN_INVALID",
    )
    if set(origin) != _ORIGIN_FIELDS:
        raise ValueError("RESEARCH_BUNDLE_ORIGIN_INVALID")
    origin_members = _verified_strings(
        origin.get("snapshot_member_ids"),
        code="RESEARCH_BUNDLE_ORIGIN_INVALID",
        require_nonempty=True,
    )
    if (
        origin.get("schema_version") != "ResearchEvaluationOrigin@1"
        or origin.get("data_snapshot_id") != expected_data_snapshot_id
        or origin.get("source_policy_identity")
        != expected_source_policy_identity
        or origin_members != expected_members
        or not isinstance(origin.get("research_policy_identity"), str)
        or not origin["research_policy_identity"]
        or not isinstance(origin.get("estimation_policy_identity"), str)
        or not origin["estimation_policy_identity"]
    ):
        raise ValueError("RESEARCH_BUNDLE_ORIGIN_MISMATCH")
    origin_content = {
        "schema_version": origin["schema_version"],
        "data_snapshot_id": origin["data_snapshot_id"],
        "source_policy_identity": origin["source_policy_identity"],
        "snapshot_member_ids": list(origin_members),
        "research_policy_identity": origin["research_policy_identity"],
        "estimation_policy_identity": origin["estimation_policy_identity"],
    }
    if origin.get("origin_id") != (
        "research_origin_" + canonical_hash(origin_content)[:24]
    ):
        raise ValueError("RESEARCH_BUNDLE_ORIGIN_IDENTITY_MISMATCH")

    estimates = value.get("estimates")
    if estimates is not None and not isinstance(estimates, Mapping):
        raise ValueError("RESEARCH_BUNDLE_ESTIMATES_INVALID")
    research_run = _verified_mapping(
        value.get("research_run"),
        "RESEARCH_BUNDLE_RESEARCH_RUN_INVALID",
    )
    if (
        not isinstance(research_run.get("run_id"), str)
        or not research_run["run_id"]
    ):
        raise ValueError("RESEARCH_BUNDLE_RESEARCH_RUN_INVALID")

    origin_member_set = set(origin_members)
    components: dict[str, Mapping[str, Any]] = {}
    for name in sorted(_COMPONENTS):
        component = _verified_mapping(
            value.get(name),
            "RESEARCH_BUNDLE_COMPONENT_INVALID",
        )
        if (
            set(component) != _COMPONENT_FIELDS
            or component.get("schema_version")
            != "ResearchComponentResult@1"
            or component.get("component") != name
            or component.get("status")
            not in {item.value for item in ResearchComponentStatus}
            or not isinstance(component.get("artifact_id"), str)
        ):
            raise ValueError("RESEARCH_BUNDLE_COMPONENT_INVALID")
        reasons = _verified_strings(
            component.get("reason_codes"),
            code="RESEARCH_BUNDLE_COMPONENT_INVALID",
            require_nonempty=True,
        )
        source_members = _verified_strings(
            component.get("source_member_ids"),
            code="RESEARCH_BUNDLE_COMPONENT_INVALID",
            require_nonempty=component["status"] in {"complete", "limited"},
        )
        content = _verified_mapping(
            component.get("content"),
            "RESEARCH_BUNDLE_COMPONENT_INVALID",
        )
        if not content or not set(source_members).issubset(origin_member_set):
            raise ValueError("RESEARCH_BUNDLE_COMPONENT_LINEAGE_INVALID")
        component_content = {
            "schema_version": component["schema_version"],
            "component": name,
            "status": component["status"],
            "reason_codes": list(reasons),
            "content": dict(content),
            "source_member_ids": list(source_members),
        }
        if component["artifact_id"] != (
            f"{name}_" + canonical_hash(component_content)[:24]
        ):
            raise ValueError("RESEARCH_BUNDLE_COMPONENT_IDENTITY_MISMATCH")
        components[name] = dict(component)

    scenario_content = _verified_mapping(
        components["scenario_valuation"]["content"],
        "RESEARCH_BUNDLE_SCENARIO_PARTITION_INVALID",
    )
    scenarios = scenario_content.get("scenarios")
    if (
        not isinstance(scenarios, (list, tuple))
        or tuple(
            item.get("role") if isinstance(item, Mapping) else None
            for item in scenarios
        )
        != ("stress", "base", "improvement")
    ):
        raise ValueError("RESEARCH_BUNDLE_SCENARIO_PARTITION_INVALID")

    bundle_content = {
        "schema_version": value["schema_version"],
        "origin": dict(origin),
        "estimates": dict(estimates) if isinstance(estimates, Mapping) else None,
        "research_run": dict(research_run),
        **{name: dict(components[name]) for name in _COMPONENTS},
    }
    expected_bundle_id = (
        "research_bundle_" + canonical_hash(bundle_content)[:24]
    )
    if value["bundle_id"] != expected_bundle_id:
        raise ValueError("RESEARCH_EVALUATION_BUNDLE_IDENTITY_MISMATCH")
    return VerifiedResearchEvaluationBundle(
        bundle_id=expected_bundle_id,
        origin=dict(origin),
        estimates=(
            dict(estimates) if isinstance(estimates, Mapping) else None
        ),
        research_run=dict(research_run),
        components=components,
    )


__all__ = [
    "ResearchComponentResult",
    "ResearchComponentStatus",
    "ResearchEvaluationBundle",
    "ResearchEvaluationOrigin",
    "VerifiedResearchEvaluationBundle",
    "verify_research_evaluation_bundle",
]
