from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from equity_research import ResearchEngine

from trading_platform.application.workflow_ledger import (
    SnapshotEvidence,
    SnapshotMemberEvidence,
)
from trading_platform.domain.research_bundle import ResearchComponentStatus
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    EvaluationHorizon,
    EvaluationPurpose,
    ResearchEvaluationPlan,
    ResearchWorkflowRequest,
    StrategyValidationSelection,
)
from trading_platform.research import ResearchEvaluation


def test_complete_typed_market_evidence_runs_the_canonical_path_engine() -> None:
    request, evidence = _request_and_evidence()

    evaluator = ResearchEvaluation(ResearchEngine())
    prepared = evaluator.prepare(request, evidence)
    bundle = evaluator.evaluate(
        request,
        evidence,
        prepared,
    )

    decision = bundle.market_path_decision
    assert decision.status is ResearchComponentStatus.COMPLETE
    assert decision.reason_codes == ("MARKET_PATH_COMPLETE",)
    assert decision.content["status"] == "ready"
    assert decision.content["missing_gates"] == []
    assert decision.content["result"]["completed_paths"] == 1000
    assert (
        decision.content["result"]["interpretation"]
        == decision.content["interpretation"]
    )


def test_ordinary_unadjusted_snapshot_enumerates_every_missing_gate() -> None:
    request, evidence = _request_and_evidence()
    ordinary_daily = tuple(
        replace(
            member,
            extracted_fields=tuple(
                {
                    key: value
                    for key, value in field.items()
                    if key
                    not in {
                        "adjustment_factor",
                        "suspended",
                        "limit_state",
                        "corporate_action_identity",
                    }
                }
                for field in member.extracted_fields
            ),
        )
        for member in evidence.member_evidence
        if member.dataset == "daily"
    )
    ordinary = replace(
        evidence,
        members={
            member.normalized_version_id: member.dataset
            for member in ordinary_daily
        },
        member_evidence=ordinary_daily,
        coverage_expected=len(ordinary_daily),
        coverage_eligible=len(ordinary_daily),
    )

    evaluator = ResearchEvaluation(ResearchEngine())
    prepared = evaluator.prepare(request, ordinary)
    bundle = evaluator.evaluate(
        request,
        ordinary,
        prepared,
    )

    decision = bundle.market_path_decision
    assert decision.status is ResearchComponentStatus.NOT_RUN
    assert decision.reason_codes == (
        "MARKET_PATH_HISTORY_INSUFFICIENT",
        "MARKET_PATH_ADJUSTMENT_STATE_EVIDENCE_INCOMPLETE",
        "MARKET_PATH_TRADING_CALENDAR_UNAVAILABLE",
        "MARKET_PATH_CONSTRAINT_POLICY_UNAVAILABLE",
    )
    assert decision.content["missing_gates"] == list(decision.reason_codes)
    assert decision.content["result"] is None


def _request_and_evidence() -> tuple[
    ResearchWorkflowRequest,
    SnapshotEvidence,
]:
    first = date(2026, 1, 1)
    final = first + timedelta(days=61)
    request = ResearchWorkflowRequest(
        schema_version="ResearchWorkflowRequest@2",
        invocation_id="market-path-applicable",
        security_id="security_market_path",
        requested_date=final.isoformat(),
        effective_session_date=final.isoformat(),
        data_snapshot_id="snapshot_market_path",
        evaluation_plan=ResearchEvaluationPlan(
            schema_version="ResearchEvaluationPlan@1",
            purpose=EvaluationPurpose.VALUATION_REVIEW,
            horizon=EvaluationHorizon(
                as_of=final.isoformat(),
                forecast_end="2028-12-31",
                review_by="2026-06-30",
            ),
            required_dimensions=(
                EvaluationDimension.SOURCE_QUALITY,
                EvaluationDimension.MARKET_PATH,
            ),
            strategy_validation=StrategyValidationSelection.NOT_REQUESTED,
        ),
    )
    daily: list[SnapshotMemberEvidence] = []
    calendars: list[SnapshotMemberEvidence] = []
    for index in range(62):
        session = (first + timedelta(days=index)).isoformat()
        available = session + "T08:00:00+00:00"
        daily.append(
            SnapshotMemberEvidence(
                normalized_version_id=f"daily_path_{index:03d}",
                dataset="daily",
                source_identity="typed_adjusted_daily",
                source_authority="structured_aggregator",
                real_source_url="https://example.invalid/daily",
                retrieved_at=available,
                published_at=session,
                available_at=available,
                quality_status="usable",
                extracted_fields=(
                    {
                        "field_name": "current_price",
                        "subject_id": "security_market_path",
                        "semantic_role": "current_price",
                        "period": session,
                        "value": str(
                            Decimal("10")
                            + Decimal(index) * Decimal("0.01")
                        ),
                        "unit": "CNY/share",
                        "currency": "CNY",
                        "extraction_method": "typed_adjusted_close",
                        "confidence": "high",
                        "adjustment_factor": "1",
                        "suspended": False,
                        "limit_state": "none",
                        "corporate_action_identity": None,
                    },
                ),
            )
        )
        calendars.append(
            SnapshotMemberEvidence(
                normalized_version_id=f"calendar_path_{index:03d}",
                dataset="trade_cal",
                source_identity="typed_trading_calendar",
                source_authority="structured_aggregator",
                real_source_url="https://example.invalid/calendar",
                retrieved_at=available,
                published_at=session,
                available_at=available,
                quality_status="usable",
                extracted_fields=(
                    {
                        "field_name": "trading_session",
                        "subject_id": "SZSE",
                        "semantic_role": "trading_session",
                        "period": session,
                        "value": "1",
                        "unit": "boolean",
                        "currency": "N/A",
                        "extraction_method": "typed_calendar",
                        "confidence": "high",
                    },
                ),
            )
        )
    policy_fields = tuple(
        {
            "field_name": name,
            "subject_id": "security_market_path",
            "semantic_role": "market_path_constraint",
            "period": final.isoformat(),
            "value": value,
            "unit": unit,
            "currency": "N/A",
            "extraction_method": "confirmed_policy",
            "confidence": "high",
        }
        for name, value, unit in (
            ("one_way_transaction_cost_bps", "10", "bps"),
            ("price_limit_fraction", "0.10", "decimal"),
            ("price_tick_size", "0.01", "CNY/share"),
            (
                "market_path_policy_identity",
                "MarketPathPolicy@test",
                "identity",
            ),
        )
    )
    policy = SnapshotMemberEvidence(
        normalized_version_id="market_path_policy_confirmed",
        dataset="market_path_policy",
        source_identity="confirmed_market_path_policy",
        source_authority="fixture",
        real_source_url="https://example.invalid/policy",
        retrieved_at=final.isoformat() + "T07:00:00+00:00",
        published_at=final.isoformat(),
        available_at=final.isoformat() + "T07:00:00+00:00",
        quality_status="usable",
        extracted_fields=policy_fields,
    )
    members = tuple((*daily, *calendars, policy))
    return request, SnapshotEvidence(
        data_snapshot_id="snapshot_market_path",
        scope_id="security_market_path",
        purpose="research",
        requested_date=final.isoformat(),
        effective_session_date=final.isoformat(),
        as_of_at=final.isoformat() + "T08:30:00+00:00",
        source_policy_identity="SourcePolicy@market-path-test",
        freshness_status="fresh",
        members={
            member.normalized_version_id: member.dataset
            for member in members
        },
        member_evidence=members,
        quality_status="usable",
        coverage_expected=len(members),
        coverage_eligible=len(members),
        coverage_excluded=0,
        coverage_missing=0,
    )
