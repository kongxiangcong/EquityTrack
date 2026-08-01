from __future__ import annotations

from equity_research.evidence import build_evidence
from trading_platform.domain.research_decision_projection import (
    project_research_decision,
)
from trading_platform.research.estimation import FrozenSnapshotEstimator


def _field(
    field_name: str,
    period: str,
    value: object,
    unit: str = "CNY",
) -> dict[str, object]:
    return {
        "field_name": field_name,
        "period": period,
        "value": value,
        "unit": unit,
        "currency": "CNY",
    }


def test_frozen_estimator_uses_bounded_period_comparable_carry_forwards() -> None:
    manifest = {
        "company": {
            "name": "示例公司",
            "ticker": "000001.SZ",
            "latest_financial_period": "20260331",
        },
        "sources": [
            {
                "source_id": "source_latest",
                "tier": "terminal",
                "extracted_fields": [
                    _field("revenue", "20260331", "1200"),
                    _field("working_capital", "20260331", "300"),
                ],
            },
            {
                "source_id": "source_prior_q1",
                "tier": "official",
                "extracted_fields": [
                    _field("d_and_a", "20250331", "100"),
                    _field("lease_debt", "20250331", "200"),
                    _field("ebit", "20250331", "50"),
                    _field("tax", "20250331", "10"),
                    _field("diluted_shares", "20250331", "1000", "shares"),
                ],
            },
            {
                "source_id": "source_prior_year",
                "tier": "terminal",
                "extracted_fields": [
                    _field("cfo", "20251231", "400"),
                ],
            },
        ],
    }

    overlay = FrozenSnapshotEstimator().build(
        manifest,
        as_of_date="2026-07-30",
    )

    assert overlay is not None
    estimates = {item["field_name"]: item for item in overlay["estimates"]}
    assert set(estimates) == {
        "d_and_a",
        "diluted_shares",
        "ebit",
        "lease_debt",
        "tax",
    }
    assert estimates["d_and_a"]["estimate_method"] == (
        "same_period_prior_year_carry_forward@1"
    )
    assert estimates["lease_debt"]["estimate_method"] == (
        "latest_balance_carry_forward@1"
    )
    assert estimates["ebit"]["estimate_method"] == (
        "same_period_prior_year_carry_forward@1"
    )
    assert estimates["diluted_shares"]["estimate_method"] == (
        "latest_balance_carry_forward@1"
    )
    assert estimates["d_and_a"]["basis_sources"] == ["source_prior_q1"]
    assert estimates["d_and_a"]["lower_bound"] == "80"
    assert estimates["d_and_a"]["upper_bound"] == "120"
    assert estimates["d_and_a"]["formal_gate_coverage"] is False

    assert estimates["d_and_a"]["policy"] == "FrozenSnapshotEstimator@1"
    assert estimates["d_and_a"]["range_policy"] == (
        "RelativeUncertaintyBand20Percent@1"
    )
    assert estimates["d_and_a"]["calibration_window"] == {
        "basis_period": "20250331",
        "target_period": "20260331",
        "maximum_basis_age_days": 550,
    }
    assert estimates["d_and_a"]["rationale"].startswith(
        "No sourced target-period value exists"
    )
    assert "sourced target-period value" in (
        estimates["d_and_a"]["invalidation_condition"]
    )

    evidence_build = build_evidence(
        manifest,
        overlay,
        as_of_date="2026-07-30",
    )
    estimate_evidence = next(
        item
        for item in evidence_build.items
        if item.field_name == "d_and_a" and item.estimated
    )
    serialized_evidence = estimate_evidence.to_dict()
    expected_metadata = {
        "basis_sources": ["source_prior_q1"],
        "policy": "FrozenSnapshotEstimator@1",
        "range_policy": "RelativeUncertaintyBand20Percent@1",
        "basis_period": "20250331",
        "lower_bound": "80",
        "upper_bound": "120",
        "calibration_window": {
            "basis_period": "20250331",
            "target_period": "20260331",
            "maximum_basis_age_days": 550,
        },
        "rationale": estimates["d_and_a"]["rationale"],
        "invalidation_condition": estimates["d_and_a"]["invalidation_condition"],
        "formal_gate_coverage": False,
    }
    assert serialized_evidence["estimate_metadata"] == expected_metadata

    projection, audit = project_research_decision(
        as_of="2026-07-30",
        required_dimensions=(),
        research_payload={
            "schema_version": 3,
            "run_id": "research_estimate_metadata",
            "status": "completed_with_limits",
            "permissions": {"research_report": True},
            "summary": {"data_quality_grade": "C"},
            "evidence": [serialized_evidence],
        },
    )
    assert projection["key_drivers"][0]["value_origin"] == "estimated"
    projected_metadata = {
        **expected_metadata,
        "basis_sources": ("source_prior_q1",),
    }
    assert projection["key_drivers"][0]["estimate_metadata"] == projected_metadata
    assert audit["fact_evidence"][0]["estimate_metadata"] == projected_metadata


def test_frozen_estimator_does_not_invent_without_comparable_basis() -> None:
    manifest = {
        "company": {
            "name": "示例公司",
            "ticker": "000001.SZ",
            "latest_financial_period": "20260331",
        },
        "sources": [
            {
                "source_id": "source_latest",
                "tier": "terminal",
                "extracted_fields": [
                    _field("revenue", "20260331", "1200"),
                ],
            }
        ],
    }

    assert (
        FrozenSnapshotEstimator().build(
            manifest,
            as_of_date="2026-07-30",
        )
        is None
    )
