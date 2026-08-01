from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

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
from trading_platform.domain.workflow import ReferenceDisposition
from trading_platform.workflows.research import WorkflowError


def _plan(
    strategy: StrategyValidationSelection = (
        StrategyValidationSelection.NOT_REQUESTED
    ),
) -> ResearchEvaluationPlan:
    return ResearchEvaluationPlan(
        "ResearchEvaluationPlan@1",
        EvaluationPurpose.COMPANY_OUTLOOK,
        EvaluationHorizon(
            "2026-07-11",
            "2028-12-31",
            "2026-10-31",
        ),
        (
            EvaluationDimension.SOURCE_QUALITY,
            EvaluationDimension.FORECAST,
            EvaluationDimension.VALUATION,
        ),
        strategy,
    )


def _request(
    invocation: str,
    *,
    snapshot_id: str = "snapshot_filing",
    strategy: StrategyValidationSelection = (
        StrategyValidationSelection.NOT_REQUESTED
    ),
) -> ResearchWorkflowRequest:
    return ResearchWorkflowRequest(
        "ResearchWorkflowRequest@2",
        invocation,
        "security_yihua",
        "2026-07-11",
        "2026-07-10",
        snapshot_id,
        _plan(strategy),
    )


def _root(tmp_path: Path) -> PlatformTaskFixture:
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
    root.faults.record_market_only_workflow_snapshot()
    return root


def test_request_v2_produces_one_canonical_view_manifest_and_no_trade_state(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    before = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT "
        "(SELECT count(*) FROM trade_plan_master),"
        "(SELECT count(*) FROM trade_plan_version),"
        "(SELECT count(*) FROM plan_evaluation),"
        "(SELECT count(*) FROM update_authorization)"
    ).fetchone()

    result = root.research.handle(
        StartResearchWorkflow(_request("workflow:v2"))
    )

    adapter = SQLiteOwningAdapterFixture(root.data_root)
    manifest = root.archive.manifest(result.final_manifest_id)
    decision = root.archive.decision_view(result.workflow_run_id)
    view = json.loads(decision.json_bytes)
    after = adapter.execute(
        "SELECT "
        "(SELECT count(*) FROM trade_plan_master),"
        "(SELECT count(*) FROM trade_plan_version),"
        "(SELECT count(*) FROM plan_evaluation),"
        "(SELECT count(*) FROM update_authorization)"
    ).fetchone()
    assert result.disposition is ReferenceDisposition.CREATED
    assert tuple(member["member_role"] for member in manifest.members) == (
        "research_bundle_json",
        "research_run_json",
        "forecast",
        "scenario_valuation",
        "valuation_method_route",
        "valuation_simulation_decision",
        "market_path_decision",
        "recent_trend_assessment",
        "decision_view_json",
        "decision_view_html",
        "decision_view_pdf",
        "decision_view_workbook",
    )
    assert view["data_snapshot_id"] == "snapshot_filing"
    assert view["valuation_artifact_record_id"] is None
    assert view["status"] == "completed_with_limits"
    assert before == after
    root.close()


def test_identical_evaluation_reuses_research_but_projects_per_workflow_view(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    created = root.research.handle(
        StartResearchWorkflow(_request("workflow:created"))
    )
    reused = root.research.handle(
        StartResearchWorkflow(_request("workflow:reused"))
    )

    assert reused.disposition is ReferenceDisposition.REUSED
    assert reused.research_run_id == created.research_run_id
    assert reused.workflow_run_id != created.workflow_run_id
    assert reused.json_artifact_id != created.json_artifact_id
    assert (
        SQLiteOwningAdapterFixture(root.data_root)
        .execute("SELECT count(*) FROM research_run_record")
        .fetchone()[0]
        == 1
    )
    root.close()


def test_invocation_identity_mismatch_fails_without_second_workflow(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    request = _request("workflow:identity")
    root.research.handle(StartResearchWorkflow(request))

    with pytest.raises(WorkflowError, match="INVOCATION_REQUEST_MISMATCH"):
        root.research.handle(
            StartResearchWorkflow(
                replace(request, data_snapshot_id="snapshot_market_20260710")
            )
        )

    assert (
        SQLiteOwningAdapterFixture(root.data_root)
        .execute("SELECT count(*) FROM workflow_run")
        .fetchone()[0]
        == 1
    )
    root.close()


def test_strategy_validation_unavailable_is_audit_only_and_nonblocking(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(
            _request(
                "workflow:strategy-unavailable",
                strategy=(
                    StrategyValidationSelection.REQUESTED_UNAVAILABLE
                ),
            )
        )
    )
    payload = json.loads(
        root.archive.decision_view(result.workflow_run_id).json_bytes
    )

    strategy = payload["audit"]["strategy_validation"]
    assert strategy == {
        "reason_code": "STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE",
        "status": "requested_unavailable",
    }
    assert result.research_run_id
    assert not any(
        member["member_role"] == "strategy_validation"
        for member in root.archive.manifest(
            result.final_manifest_id
        ).members
    )
    root.close()


def test_snapshot_scope_and_pit_gates_fail_before_research_persistence(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    bad_scope = replace(
        _request("workflow:bad-scope"),
        security_id="security_other",
    )

    with pytest.raises(
        WorkflowError, match="WORKFLOW_DOMAIN_REFERENCE_INVALID"
    ):
        root.research.handle(StartResearchWorkflow(bad_scope))

    assert (
        SQLiteOwningAdapterFixture(root.data_root)
        .execute("SELECT count(*) FROM research_run_record")
        .fetchone()[0]
        == 0
    )
    root.close()
