from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_research import ResearchEngine

from tests.platform.application_task_fixture import PlatformTaskFixture
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


AS_OF = "2025-07-07"
OPENING = "2024FY"
PERIODS = ("2026E", "2027E", "2028E", "2029E", "2030E")
SEGMENT = "core"


def test_complete_frozen_model_inputs_run_all_three_financial_engines() -> None:
    request, evidence = _request_and_evidence()

    evaluator = ResearchEvaluation(ResearchEngine())
    prepared = evaluator.prepare(request, evidence)
    bundle = evaluator.evaluate(
        request,
        evidence,
        prepared,
    )

    assert bundle.forecast.status is ResearchComponentStatus.COMPLETE
    assert bundle.forecast.content["template_id"] == (
        "manufacturing_driver_graph@2"
    )
    assert bundle.scenario_valuation.status in {
        ResearchComponentStatus.COMPLETE,
        ResearchComponentStatus.LIMITED,
    }
    assert [
        item["role"]
        for item in bundle.scenario_valuation.content["scenarios"]
    ] == ["stress", "base", "improvement"]
    base = bundle.scenario_valuation.content["scenarios"][1]
    dcf = next(
        item for item in base["methods"] if item["method_id"] == "fcff_dcf"
    )
    assert dcf["status"] == "ready"
    assert dcf["conditional_value_range"] is not None
    simulation = bundle.valuation_simulation_decision
    assert simulation.status in {
        ResearchComponentStatus.COMPLETE,
        ResearchComponentStatus.LIMITED,
    }
    assert simulation.content["status"] in {"ready", "partial"}
    assert simulation.content["result"]["completed_samples"] > 0
    assert (
        simulation.content["result"]["valuation_source_identity"]
        == bundle.scenario_valuation.artifact_id
    )


def test_non_official_critical_facts_only_block_the_formal_model(
    tmp_path: Path,
) -> None:
    root = PlatformTaskFixture(tmp_path)
    try:
        root.faults.record_official_filing_workflow_snapshot()
        request = ResearchWorkflowRequest(
            schema_version="ResearchWorkflowRequest@2",
            invocation_id="non-official-model-facts",
            security_id="security_yihua",
            requested_date="2026-07-11",
            effective_session_date="2026-07-10",
            data_snapshot_id="snapshot_filing",
            evaluation_plan=ResearchEvaluationPlan(
                schema_version="ResearchEvaluationPlan@1",
                purpose=EvaluationPurpose.VALUATION_REVIEW,
                horizon=EvaluationHorizon(
                    as_of="2026-07-11",
                    forecast_end="2030-12-31",
                    review_by="2026-10-31",
                ),
                required_dimensions=(
                    EvaluationDimension.SOURCE_QUALITY,
                    EvaluationDimension.FORECAST,
                    EvaluationDimension.VALUATION,
                    EvaluationDimension.VALUATION_SIMULATION,
                ),
                strategy_validation=(
                    StrategyValidationSelection.NOT_REQUESTED
                ),
            ),
        )
        research_evidence = root.inspection.snapshot("snapshot_filing")
        _, model_evidence = _request_and_evidence()
        model_members = tuple(
            replace(
                member,
                source_authority=(
                    "structured_aggregator"
                    if member.dataset == "research_model_input"
                    and member.source_authority == "official"
                    else member.source_authority
                ),
                extracted_fields=tuple(
                    {
                        **field,
                        "subject_id": request.security_id,
                    }
                    for field in member.extracted_fields
                ),
            )
            for member in model_evidence.member_evidence
        )
        members = research_evidence.member_evidence + model_members
        evidence = replace(
            research_evidence,
            members={
                member.normalized_version_id: member.dataset
                for member in members
            },
            member_evidence=members,
            coverage_expected=len(members),
            coverage_eligible=len(members),
            coverage_excluded=0,
            coverage_missing=0,
        )

        evaluator = ResearchEvaluation(ResearchEngine())
        prepared = evaluator.prepare(request, evidence)
        bundle = evaluator.evaluate(
            request,
            evidence,
            prepared,
        )

        assert bundle.research_run["status"] == "completed_with_limits"
        assert bundle.research_run["integrity_issues"] == []
        assert (
            bundle.scenario_valuation.status
            is ResearchComponentStatus.BLOCKED
        )
        assert bundle.scenario_valuation.reason_codes == (
            "RESEARCH_MODEL_OFFICIAL_FACTS_REQUIRED",
        )
        assert (
            bundle.valuation_simulation_decision.status
            is ResearchComponentStatus.NOT_RUN
        )
    finally:
        root.close()


def test_reserved_company_segment_id_is_rejected_before_engine_dispatch() -> None:
    request, evidence = _request_and_evidence()
    members = tuple(
        replace(
            member,
            extracted_fields=tuple(
                (
                    {**field, "value": "company"}
                    if field.get("model_path") == "forecast.segment_ids"
                    else field
                )
                for field in member.extracted_fields
            ),
        )
        for member in evidence.member_evidence
    )

    changed = replace(evidence, member_evidence=members)
    evaluator = ResearchEvaluation(ResearchEngine())
    bundle = evaluator.evaluate(
        request,
        changed,
        evaluator.prepare(request, changed),
    )

    assert bundle.forecast.status is ResearchComponentStatus.BLOCKED
    assert bundle.scenario_valuation.reason_codes == (
        "FORECAST_SEGMENT_ID_RESERVED",
    )


def _request_and_evidence() -> tuple[
    ResearchWorkflowRequest,
    SnapshotEvidence,
]:
    request = ResearchWorkflowRequest(
        schema_version="ResearchWorkflowRequest@2",
        invocation_id="complete-financial-pipeline",
        security_id="security_complete_model",
        requested_date=AS_OF,
        effective_session_date=AS_OF,
        data_snapshot_id="snapshot_complete_model",
        evaluation_plan=ResearchEvaluationPlan(
            schema_version="ResearchEvaluationPlan@1",
            purpose=EvaluationPurpose.VALUATION_REVIEW,
            horizon=EvaluationHorizon(
                as_of=AS_OF,
                forecast_end="2030-12-31",
                review_by="2025-10-31",
            ),
            required_dimensions=(
                EvaluationDimension.SOURCE_QUALITY,
                EvaluationDimension.FORECAST,
                EvaluationDimension.VALUATION,
                EvaluationDimension.VALUATION_SIMULATION,
            ),
            strategy_validation=StrategyValidationSelection.NOT_REQUESTED,
        ),
    )
    facts = _fact_fields()
    assumptions = _assumption_fields()
    fact_member = SnapshotMemberEvidence(
        normalized_version_id="official_model_facts",
        dataset="research_model_input",
        source_identity="official_model_facts",
        source_authority="official",
        real_source_url="https://example.invalid/official-model-facts",
        retrieved_at=AS_OF + "T08:00:00+00:00",
        published_at=AS_OF + "T07:00:00+00:00",
        available_at=AS_OF + "T07:30:00+00:00",
        quality_status="usable",
        extracted_fields=tuple(facts),
    )
    assumption_member = SnapshotMemberEvidence(
        normalized_version_id="confirmed_model_assumptions",
        dataset="research_model_input",
        source_identity="confirmed_model_assumptions",
        source_authority="fixture",
        real_source_url="https://example.invalid/model-assumptions",
        retrieved_at=AS_OF + "T08:00:00+00:00",
        published_at=AS_OF + "T07:00:00+00:00",
        available_at=AS_OF + "T07:30:00+00:00",
        quality_status="usable",
        extracted_fields=tuple(assumptions),
    )
    members = (fact_member, assumption_member)
    return request, SnapshotEvidence(
        data_snapshot_id="snapshot_complete_model",
        scope_id="security_complete_model",
        purpose="research",
        requested_date=AS_OF,
        effective_session_date=AS_OF,
        as_of_at=AS_OF + "T08:30:00+00:00",
        source_policy_identity="SourcePolicy@complete-model-test",
        freshness_status="fresh",
        members={
            member.normalized_version_id: member.dataset
            for member in members
        },
        member_evidence=members,
        quality_status="usable",
        coverage_expected=2,
        coverage_eligible=2,
        coverage_excluded=0,
        coverage_missing=0,
    )


def _fact_fields() -> list[dict[str, object]]:
    baseline = {
        "volume": ("100", "units", "N/A"),
        "asp": ("10", "CNY/unit", "CNY"),
        "capacity": ("120", "units", "N/A"),
        "utilization": ("1", "decimal", "N/A"),
        "unit_cost": ("6", "CNY/unit", "CNY"),
        "operating_expense": ("100", "CNY", "CNY"),
        "capex": ("50", "CNY", "CNY"),
        "working_capital": ("200", "CNY", "CNY"),
        "depreciation": ("20", "CNY", "CNY"),
        "tax_rate": ("0.25", "decimal", "N/A"),
    }
    opening = {
        "cash": "200",
        "working_capital": "200",
        "net_ppe": "1000",
        "other_assets": "100",
        "debt": "400",
        "other_liabilities": "100",
        "equity": "1000",
    }
    fields = [
        _field(
            f"forecast.baseline.{SEGMENT}.{metric}",
            value,
            unit,
            currency,
            OPENING,
        )
        for metric, (value, unit, currency) in baseline.items()
    ]
    fields.extend(
        _field(
            f"forecast.opening.{metric}",
            value,
            "CNY",
            "CNY",
            OPENING,
        )
        for metric, value in opening.items()
    )
    for name in (
        "lease_debt",
        "preferred_stock",
        "minority_interest",
        "pension_deficit",
        "associates_jv_value",
        "non_operating_assets",
    ):
        fields.append(
            _field(
                f"valuation.bridge.opening.{name}",
                "0",
                "CNY",
                "CNY",
                OPENING,
            )
        )
    fields.extend(
        (
            _field(
                "valuation.bridge.opening.diluted_shares",
                "100",
                "shares",
                "N/A",
                OPENING,
            ),
            _field(
                "valuation.reverse.enterprise_value",
                "5000",
                "CNY",
                "CNY",
                AS_OF,
            ),
        )
    )
    return fields


def _assumption_fields() -> list[dict[str, object]]:
    fields = [
        _field(
            "forecast.archetype",
            "general_manufacturing",
            "identity",
            "N/A",
            AS_OF,
        ),
        _field(
            "forecast.company_name",
            "Complete Model Co",
            "identity",
            "N/A",
            AS_OF,
        ),
        _field(
            "forecast.segment_ids",
            SEGMENT,
            "identity",
            "N/A",
            AS_OF,
        ),
        _field(
            "forecast.opening_period",
            OPENING,
            "identity",
            "N/A",
            OPENING,
        ),
    ]
    settings = {
        "stress": ("0", "0", "0.02"),
        "base": ("0.05", "0.02", "0.01"),
        "improvement": ("0.15", "0.05", "-0.02"),
    }
    for role, (demand, asp, unit_cost) in settings.items():
        for period in PERIODS:
            values = {
                "demand_growth": demand,
                "asp_growth": asp,
                "capacity_growth": "0.10",
                "target_utilization": "0.95",
                "unit_cost_growth": unit_cost,
                "operating_expense_growth": "0.02",
                "capex_growth": "0.03",
                "depreciation_growth": "0.02",
                "working_capital_to_revenue": "0.15",
                "tax_rate": "0.25",
                "debt_change": "0",
                "event_probability": "1",
            }
            fields.extend(
                _field(
                    f"scenario.{role}.{period}.{SEGMENT}.{metric}",
                    value,
                    "decimal",
                    "N/A",
                    period,
                )
                for metric, value in values.items()
            )
    for name in (
        "lease_debt",
        "preferred_stock",
        "minority_interest",
        "pension_deficit",
        "associates_jv_value",
        "non_operating_assets",
    ):
        fields.append(
            _field(
                f"valuation.bridge.terminal.{name}",
                "0",
                "CNY",
                "CNY",
                PERIODS[-1],
            )
        )
    fields.append(
        _field(
            "valuation.bridge.terminal.diluted_shares",
            "100",
            "shares",
            "N/A",
            PERIODS[-1],
        )
    )
    dcf = {
        "status": ("allowed", "identity", AS_OF),
        "reason": ("Industrial FCFF inputs are complete.", "text", AS_OF),
        "discount_rate_low": ("0.09", "decimal", AS_OF),
        "discount_rate_base": ("0.10", "decimal", AS_OF),
        "discount_rate_high": ("0.11", "decimal", AS_OF),
        "terminal_growth_low": ("0.02", "decimal", PERIODS[-1]),
        "terminal_growth_base": ("0.025", "decimal", PERIODS[-1]),
        "terminal_growth_high": ("0.03", "decimal", PERIODS[-1]),
    }
    fields.extend(
        _field(
            f"valuation.dcf.{name}",
            value,
            unit,
            "N/A",
            period,
        )
        for name, (value, unit, period) in dcf.items()
    )
    fields.extend(
        (
            _field(
                "valuation.reverse.discount_rate",
                "0.10",
                "decimal",
                "N/A",
                AS_OF,
            ),
            _field(
                f"valuation.sotp.{SEGMENT}.metric",
                "ebit",
                "identity",
                "N/A",
                PERIODS[-1],
            ),
            _field(
                f"valuation.sotp.{SEGMENT}.multiple_low",
                "8",
                "x",
                "N/A",
                PERIODS[-1],
            ),
            _field(
                f"valuation.sotp.{SEGMENT}.multiple_base",
                "10",
                "x",
                "N/A",
                PERIODS[-1],
            ),
            _field(
                f"valuation.sotp.{SEGMENT}.multiple_high",
                "12",
                "x",
                "N/A",
                PERIODS[-1],
            ),
        )
    )
    simulation = {
        "policy_identity": ("ValuationSimulationPolicy@test", "identity"),
        "hard_min": ("0.1", "CNY/share"),
        "hard_max": ("1000000", "CNY/share"),
        "tail_threshold": ("0", "CNY/share"),
        "sample_budget": ("2000", "count"),
        "batch_size": ("200", "count"),
        "convergence_tolerance": ("0.20", "decimal"),
        "stable_batches_required": ("1", "count"),
        "maximum_invalid_path_rate": ("0.05", "decimal"),
        "minimum_tail_observations": ("10", "count"),
    }
    fields.extend(
        _field(
            f"simulation.{name}",
            value,
            unit,
            "N/A" if unit != "CNY/share" else "CNY",
            AS_OF,
        )
        for name, (value, unit) in simulation.items()
    )
    start = date(2020, 1, 1)
    fields.extend(
        _field(
            f"simulation.calibration.{index:03d}",
            str(index + 1),
            "CNY/share",
            "CNY",
            (start + timedelta(days=index)).isoformat(),
        )
        for index in range(20)
    )
    return fields


def _field(
    model_path: str,
    value: object,
    unit: str,
    currency: str,
    period: str,
) -> dict[str, object]:
    return {
        "model_path": model_path,
        "field_name": model_path,
        "subject_id": "security_complete_model",
        "semantic_role": "typed_research_model_input",
        "period": period,
        "value": value,
        "unit": unit,
        "currency": currency,
        "extraction_method": "frozen_typed_model_input",
        "confidence": "high",
    }


def test_non_model_dataset_cannot_inject_financial_model_fields() -> None:
    request, evidence = _request_and_evidence()
    foreign_member = SnapshotMemberEvidence(
        normalized_version_id="market_path_policy_with_model_field",
        dataset="market_path_policy",
        source_identity="confirmed_market_path_policy",
        source_authority="fixture",
        real_source_url="https://example.invalid/market-path-policy",
        retrieved_at=AS_OF + "T08:00:00+00:00",
        published_at=AS_OF + "T07:00:00+00:00",
        available_at=AS_OF + "T07:30:00+00:00",
        quality_status="usable",
        extracted_fields=(
            _field(
                "forecast.archetype",
                "financial_institution",
                "identity",
                "N/A",
                AS_OF,
            ),
        ),
    )
    changed = replace(
        evidence,
        members={
            **evidence.members,
            foreign_member.normalized_version_id: foreign_member.dataset,
        },
        member_evidence=(*evidence.member_evidence, foreign_member),
    )

    evaluator = ResearchEvaluation(ResearchEngine())
    bundle = evaluator.evaluate(
        request, changed, evaluator.prepare(request, changed)
    )

    assert bundle.forecast.status is ResearchComponentStatus.COMPLETE
    assert bundle.forecast.content["template_id"] == "manufacturing_driver_graph@2"


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    (
        (
            {"model_path": ""},
            "RESEARCH_MODEL_INPUT_PATH_INVALID",
        ),
        (
            {"model_path": " forecast.archetype"},
            "RESEARCH_MODEL_INPUT_PATH_INVALID",
        ),
        (
            {"field_name": "forecast.other"},
            "RESEARCH_MODEL_INPUT_SCHEMA_INVALID",
        ),
        (
            {"subject_id": "security_other"},
            "RESEARCH_COMPONENT_INPUT_SUBJECT_INVALID",
        ),
        (
            {"semantic_role": "market_path_constraint"},
            "RESEARCH_MODEL_INPUT_SCHEMA_INVALID",
        ),
        ({"period": ""}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"unit": ""}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"currency": ""}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"value": None}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"value": True}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
    ),
)
def test_malformed_scenario_field_degrades_only_typed_model_outputs(
    changes: dict[str, object],
    reason_code: str,
) -> None:
    request, evidence = _request_and_evidence()
    members = tuple(
        replace(
            member,
            extracted_fields=tuple(
                (
                    {**field, **changes}
                    if field.get("model_path") == "forecast.archetype"
                    else field
                )
                for field in member.extracted_fields
            ),
        )
        for member in evidence.member_evidence
    )

    changed = replace(evidence, member_evidence=members)
    evaluator = ResearchEvaluation(ResearchEngine())
    bundle = evaluator.evaluate(
        request,
        changed,
        evaluator.prepare(request, changed),
    )

    assert bundle.research_run["integrity_issues"] == []
    assert bundle.scenario_valuation.reason_codes == (reason_code,)


def test_malformed_simulation_field_does_not_block_scenario_valuation() -> None:
    request, evidence = _request_and_evidence()
    members = tuple(
        replace(
            member,
            extracted_fields=tuple(
                (
                    {**field, "unit": ""}
                    if field.get("model_path") == "simulation.batch_size"
                    else field
                )
                for field in member.extracted_fields
            ),
        )
        for member in evidence.member_evidence
    )

    changed = replace(evidence, member_evidence=members)
    evaluator = ResearchEvaluation(ResearchEngine())
    bundle = evaluator.evaluate(
        request,
        changed,
        evaluator.prepare(request, changed),
    )

    assert bundle.scenario_valuation.status in {
        ResearchComponentStatus.COMPLETE,
        ResearchComponentStatus.LIMITED,
    }
    assert bundle.valuation_simulation_decision.reason_codes == (
        "RESEARCH_MODEL_INPUT_SCHEMA_INVALID",
    )


def test_evaluation_fingerprint_binds_the_compiled_capability_contract() -> None:
    request, evidence = _request_and_evidence()
    member = evidence.member_evidence[0]
    changed_member = replace(
        member,
        extracted_fields=tuple(
            (
                {**field, "period": "2023FY"}
                if index == 0
                else field
            )
            for index, field in enumerate(member.extracted_fields)
        ),
    )
    changed = replace(
        evidence,
        member_evidence=(changed_member, *evidence.member_evidence[1:]),
    )
    evaluator = ResearchEvaluation(ResearchEngine())

    assert (
        evaluator.prepare(request, evidence).evaluation_fingerprint
        != evaluator.prepare(request, changed).evaluation_fingerprint
    )
