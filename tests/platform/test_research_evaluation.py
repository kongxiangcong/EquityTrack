from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from equity_research import ResearchEngine

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
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
from trading_platform.workflows.research import WorkflowError


def _plan() -> ResearchEvaluationPlan:
    return ResearchEvaluationPlan(
        schema_version="ResearchEvaluationPlan@1",
        purpose=EvaluationPurpose.COMPANY_OUTLOOK,
        horizon=EvaluationHorizon(
            as_of="2026-07-25",
            forecast_end="2028-12-31",
            review_by="2026-10-31",
        ),
        required_dimensions=(
            EvaluationDimension.SOURCE_QUALITY,
            EvaluationDimension.FORECAST,
            EvaluationDimension.VALUATION,
        ),
        strategy_validation=StrategyValidationSelection.NOT_REQUESTED,
    )


def test_request_v2_contains_only_snapshot_references_and_typed_plan() -> None:
    plan = _plan()
    request = ResearchWorkflowRequest(
        schema_version="ResearchWorkflowRequest@2",
        invocation_id="research-v2",
        security_id="security_yihua",
        requested_date="2026-07-25",
        effective_session_date="2026-07-25",
        data_snapshot_id="snapshot_a_share",
        evaluation_plan=plan,
    )

    assert request.evaluation_plan.identity.startswith("evaluation_plan_")
    assert not hasattr(request, "projection")
    assert not hasattr(request, "analysis_artifacts")
    assert not hasattr(request, "candidate_member_ids")
    assert not hasattr(request, "market_only_member_ids")


@pytest.mark.parametrize(
    "mutation",
    (
        {"schema_version": "ResearchEvaluationPlan@0"},
        {"required_dimensions": ()},
    ),
)
def test_plan_is_closed_typed_and_fails_before_workflow(
    mutation: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_plan(), **mutation)


def test_evaluation_horizon_rejects_future_inversion() -> None:
    with pytest.raises(ValueError):
        EvaluationHorizon(
            as_of="2026-07-25",
            forecast_end="2026-07-24",
            review_by="2026-10-31",
        )


def test_strategy_validation_is_typed_unavailable_without_runtime_selector() -> None:
    blocked = replace(
        _plan(),
        strategy_validation=StrategyValidationSelection.REQUESTED_UNAVAILABLE,
    )

    assert blocked.strategy_reason_code == (
        "STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE"
    )
    assert "provider" not in blocked.canonical_content
    assert "engine" not in blocked.canonical_content
    assert "adapter" not in blocked.canonical_content


def test_concrete_evaluation_uses_only_frozen_evidence_and_degrades_truthfully(
    tmp_path: Path,
) -> None:
    root = PlatformTaskFixture(tmp_path)
    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua",
            "SZSE",
            "002897",
            "CNY",
            "2017-09-07",
        ),
    )
    root.faults.record_official_filing_workflow_snapshot()
    request = ResearchWorkflowRequest(
        "ResearchWorkflowRequest@2",
        "research-evaluation",
        "security_yihua",
        "2026-07-11",
        "2026-07-10",
        "snapshot_filing",
        replace(
            _plan(),
            horizon=EvaluationHorizon(
                "2026-07-11",
                "2028-12-31",
                "2026-10-31",
            ),
        ),
    )
    evidence = root.inspection.snapshot(request.data_snapshot_id)

    result = ResearchEvaluation(ResearchEngine()).evaluate(request, evidence)

    assert result.status == "blocked"
    assert result.permissions["formal_per_share_valuation"] is False
    assert result.permissions["institution_style_rating"] is False
    assert result.permissions["personalized_investment_instruction"] is False
    root.close()


def test_public_workflow_accepts_only_request_v2_snapshot_reference(
    tmp_path: Path,
) -> None:
    root = PlatformTaskFixture(tmp_path)
    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua",
            "SZSE",
            "002897",
            "CNY",
            "2017-09-07",
        ),
    )
    root.faults.record_market_only_workflow_snapshot()
    plan = replace(
        _plan(),
        horizon=EvaluationHorizon(
            as_of="2026-07-11",
            forecast_end="2028-12-31",
            review_by="2026-10-31",
        ),
    )
    request = ResearchWorkflowRequest(
        "ResearchWorkflowRequest@2",
        "research-v2-public",
        "security_yihua",
        "2026-07-11",
        "2026-07-10",
        "snapshot_market_20260710",
        plan,
    )

    result = root.research.handle(StartResearchWorkflow(request))

    stored = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT request_schema_version FROM workflow_run_request "
        "WHERE workflow_run_id=?",
        (result.workflow_run_id,),
    ).fetchone()
    assert stored[0] == "ResearchWorkflowRequest@2"
    root.close()


def test_public_workflow_rejects_request_v1_shape_before_persistence(
    tmp_path: Path,
) -> None:
    root = PlatformTaskFixture(tmp_path)

    with pytest.raises(
        (TypeError, WorkflowError),
        match="ResearchWorkflowRequest@2",
    ):
        root.research.handle(
            StartResearchWorkflow(
                {
                    "schema_version": "ResearchWorkflowRequest@1",
                    "projection": {},
                }
            )
        )
    assert (
        SQLiteOwningAdapterFixture(root.data_root)
        .execute("SELECT count(*) FROM workflow_run")
        .fetchone()[0]
        == 0
    )
    root.close()
