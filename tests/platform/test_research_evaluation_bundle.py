from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from equity_research import ResearchEngine

from trading_platform.application.workflow_ledger import (
    SnapshotEvidence,
    SnapshotMemberEvidence,
)
from trading_platform.domain.research_bundle import (
    ResearchComponentStatus,
)
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    EvaluationHorizon,
    EvaluationPurpose,
    ResearchEvaluationPlan,
    ResearchWorkflowRequest,
    StrategyValidationSelection,
)
from trading_platform.research import ResearchEvaluation


def _request() -> ResearchWorkflowRequest:
    return ResearchWorkflowRequest(
        schema_version="ResearchWorkflowRequest@2",
        invocation_id="bundle-evaluation",
        security_id="security_bundle",
        requested_date="2026-03-01",
        effective_session_date="2026-03-01",
        data_snapshot_id="snapshot_bundle",
        evaluation_plan=ResearchEvaluationPlan(
            schema_version="ResearchEvaluationPlan@1",
            purpose=EvaluationPurpose.COMPANY_OUTLOOK,
            horizon=EvaluationHorizon(
                as_of="2026-03-01",
                forecast_end="2028-12-31",
                review_by="2026-06-01",
            ),
            required_dimensions=(
                EvaluationDimension.SOURCE_QUALITY,
                EvaluationDimension.FORECAST,
                EvaluationDimension.VALUATION,
                EvaluationDimension.VALUATION_SIMULATION,
                EvaluationDimension.MARKET_PATH,
            ),
            strategy_validation=StrategyValidationSelection.NOT_REQUESTED,
        ),
    )


def _evidence() -> SnapshotEvidence:
    first = date(2026, 1, 1)
    members = tuple(
        SnapshotMemberEvidence(
            normalized_version_id=f"daily_{index:03d}",
            dataset="daily",
            source_identity="tushare_compatible_test",
            source_authority="structured_aggregator",
            real_source_url="https://example.invalid",
            retrieved_at="2026-03-01T16:00:00+00:00",
            published_at=(first + timedelta(days=index)).isoformat(),
            available_at=(
                first + timedelta(days=index)
            ).isoformat()
            + "T08:00:00+00:00",
            quality_status="usable",
            extracted_fields=(
                {
                    "field_name": "current_price",
                    "subject_id": "security_bundle",
                    "semantic_role": "current_price",
                    "period": (first + timedelta(days=index)).isoformat(),
                    "value": str(Decimal(index + 1)),
                    "unit": "CNY/share",
                    "currency": "CNY",
                    "extraction_method": "normalized_ohlcv:close",
                    "confidence": "medium",
                },
            ),
        )
        for index in range(60)
    )
    return SnapshotEvidence(
        data_snapshot_id="snapshot_bundle",
        scope_id="security_bundle",
        purpose="research",
        requested_date="2026-03-01",
        effective_session_date="2026-03-01",
        as_of_at="2026-03-01T23:59:59+00:00",
        source_policy_identity="SourcePolicy@test",
        freshness_status="fresh",
        members={
            member.normalized_version_id: member.dataset
            for member in members
        },
        member_evidence=members,
        quality_status="usable",
        coverage_expected=60,
        coverage_eligible=60,
        coverage_excluded=0,
        coverage_missing=0,
    )


def test_one_evaluation_call_returns_a_complete_structural_bundle() -> None:
    request = _request()
    evidence = _evidence()
    evaluator = ResearchEvaluation(ResearchEngine())
    prepared = evaluator.prepare(request, evidence)
    result = evaluator.evaluate(
        request,
        evidence,
        prepared,
    )

    payload = result.to_dict()
    assert payload["schema_version"] == "ResearchEvaluationBundle@1"
    assert payload["bundle_id"].startswith("research_bundle_")
    assert set(payload) == {
        "bundle_id",
        "schema_version",
        "origin",
        "estimates",
        "research_run",
        "forecast",
        "scenario_valuation",
        "valuation_method_route",
        "valuation_simulation_decision",
        "market_path_decision",
        "recent_trend_assessment",
    }
    assert [
        item["role"]
        for item in result.scenario_valuation.content["scenarios"]
    ] == ["stress", "base", "improvement"]
    assert (
        result.forecast.content["template_id"]
        == "data_insufficient@1"
    )
    assert (
        result.valuation_simulation_decision.status
        is ResearchComponentStatus.NOT_RUN
    )
    assert (
        result.market_path_decision.status
        is ResearchComponentStatus.NOT_RUN
    )
    assert (
        result.recent_trend_assessment.status
        is ResearchComponentStatus.COMPLETE
    )
    assert (
        result.recent_trend_assessment.content["classification"]
        == "up"
    )
    assert (
        result.recent_trend_assessment.content["schema_version"]
        == "RecentTrendAssessment@1"
    )


def test_bundle_identity_replays_from_the_same_frozen_snapshot() -> None:
    evaluator = ResearchEvaluation(ResearchEngine())
    request = _request()
    evidence = _evidence()
    prepared = evaluator.prepare(request, evidence)

    first = evaluator.evaluate(request, evidence, prepared)
    second = evaluator.evaluate(request, evidence, prepared)

    assert first.bundle_id == second.bundle_id
    assert first.to_dict() == second.to_dict()

def test_partial_snapshot_uses_only_bounded_traceable_estimates() -> None:
    base = _evidence()
    target = SnapshotMemberEvidence(
        normalized_version_id="income_target_20260331",
        dataset="income",
        source_identity="cninfo_test",
        source_authority="official",
        real_source_url="https://example.invalid/target",
        retrieved_at="2026-03-01T16:00:00+00:00",
        published_at="2026-03-01",
        available_at="2026-03-01T08:00:00+00:00",
        quality_status="usable",
        extracted_fields=(
            {
                "field_name": "revenue",
                "period": "20260331",
                "value": "1200",
                "unit": "CNY",
                "currency": "CNY",
            },
        ),
    )
    comparable = SnapshotMemberEvidence(
        normalized_version_id="cashflow_comparable_20250331",
        dataset="cashflow",
        source_identity="cninfo_test",
        source_authority="official",
        real_source_url="https://example.invalid/comparable",
        retrieved_at="2026-03-01T16:00:00+00:00",
        published_at="2025-04-30",
        available_at="2025-04-30T08:00:00+00:00",
        quality_status="usable",
        extracted_fields=(
            {
                "field_name": "d_and_a",
                "period": "20250331",
                "value": "100",
                "unit": "CNY",
                "currency": "CNY",
            },
        ),
    )
    evidence = SnapshotEvidence(
        **{
            **base.__dict__,
            "members": {
                **base.members,
                target.normalized_version_id: target.dataset,
                comparable.normalized_version_id: comparable.dataset,
            },
            "member_evidence": base.member_evidence + (target, comparable),
            "coverage_expected": base.coverage_expected + 3,
            "coverage_eligible": base.coverage_eligible + 2,
            "coverage_missing": 1,
        }
    )

    request = _request()
    evaluator = ResearchEvaluation(ResearchEngine())
    result = evaluator.evaluate(
        request,
        evidence,
        evaluator.prepare(request, evidence),
    )

    assert result.estimates is not None
    estimates = {
        item["field_name"]: item
        for item in result.estimates["estimates"]
    }
    assert set(estimates) == {"d_and_a"}
    assert estimates["d_and_a"]["estimate_value"] == "100"
    assert estimates["d_and_a"]["lower_bound"] == "80"
    assert estimates["d_and_a"]["upper_bound"] == "120"
    assert estimates["d_and_a"]["basis_sources"]
    assert estimates["d_and_a"]["formal_gate_coverage"] is False
    assert result.research_run["status"] == "completed_with_limits"