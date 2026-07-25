from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


class ResearchViewError(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code if message is None else f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class ResearchDecisionView:
    schema_version: str
    view_id: str
    workflow_run_id: str
    research_run_id: str
    data_snapshot_id: str
    model_data_snapshot_identity: str
    security_id: str
    forecast_artifact_record_id: str | None
    valuation_artifact_record_id: str | None
    simulation_artifact_record_id: str | None
    market_path_artifact_record_id: str | None
    subject_id: str
    as_of: str
    model_identity: str
    policy_identity: str
    status: str
    valuation_view: Mapping[str, Any]
    risk_reward_summary: str
    data_quality_grade: str
    key_uncertainties: tuple[str, ...]
    what_would_change_the_view: tuple[str, ...]
    story: Mapping[str, Any]
    key_drivers: tuple[Mapping[str, Any], ...]
    scenarios: tuple[Mapping[str, Any], ...]
    market_implied_expectations: tuple[Mapping[str, Any], ...]
    valuation_simulation: Mapping[str, Any] | None
    market_price_paths: Mapping[str, Any] | None
    value_market_divergence: Mapping[str, Any] | None
    audit: Mapping[str, Any]
    boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "ResearchDecisionView":
        if value.get("schema_version") != "ResearchDecisionView@2":
            raise ResearchViewError("RESEARCH_VIEW_SCHEMA_INVALID")
        if set(value) != set(cls.__dataclass_fields__):
            raise ResearchViewError("RESEARCH_VIEW_FIELDS_INVALID")
        fields = dict(value)
        for name in (
            "key_drivers",
            "scenarios",
            "market_implied_expectations",
            "key_uncertainties",
            "what_would_change_the_view",
        ):
            if not isinstance(fields[name], (list, tuple)):
                raise ResearchViewError("RESEARCH_VIEW_FIELDS_INVALID")
            fields[name] = tuple(fields[name])
        if (
            not isinstance(fields["story"], Mapping)
            or not isinstance(fields["audit"], Mapping)
            or not isinstance(fields["valuation_view"], Mapping)
        ):
            raise ResearchViewError("RESEARCH_VIEW_FIELDS_INVALID")
        return cls(**fields)


__all__ = [
    "ResearchDecisionView",
    "ResearchViewError",
]
