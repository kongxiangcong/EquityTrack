from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from equity_research import ResearchEngine

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.data.providers import (
    TransportResponse,
    TushareCompatibleProvider,
)
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    EvaluationHorizon,
    EvaluationPurpose,
    ResearchEvaluationPlan,
    ResearchWorkflowRequest,
    StrategyValidationSelection,
)
from trading_platform.domain.data import (
    CompletenessRequirement,
    FallbackMode,
    QueryPolicy,
    SnapshotPurpose,
    SourceAuthority,
    SourceFailureDisposition,
    SourcePolicy,
    SourceRights,
    SourceRoute,
    SyncRequest,
    SyncStatus,
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

    evaluator = ResearchEvaluation(ResearchEngine())
    result = evaluator.evaluate(
        request, evidence, evaluator.prepare(request, evidence)
    )

    assert result.research_run["status"] == "completed_with_limits"
    assert result.research_run["integrity_issues"] == []
    assert result.research_run["permissions"]["formal_per_share_valuation"] is False
    assert result.research_run["permissions"]["institution_style_rating"] is False
    assert (
        result.research_run["permissions"]["personalized_investment_instruction"]
        is False
    )
    root.close()


def test_tushare_financial_snapshot_enables_limited_research_report(
    tmp_path: Path,
) -> None:
    responses = {
        "trade_cal": {
            "code": 0,
            "data": {
                "fields": ["exchange", "cal_date", "is_open"],
                "items": [["SZSE", "20260728", 1]],
            },
        },
        "stock_basic": {
            "code": 0,
            "data": {
                "fields": ["ts_code", "name", "list_date"],
                "items": [["002897.SZ", "意华股份", "20170907"]],
            },
        },
        "daily": {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ],
                "items": [
                    [
                        "002897.SZ",
                        "20260728",
                        80.0,
                        82.0,
                        79.0,
                        81.0,
                        1000.0,
                        81000.0,
                    ]
                ],
            },
        },
        "income": {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "update_flag",
                    "revenue",
                    "n_income_attr_p",
                    "operate_profit",
                    "income_tax",
                ],
                "items": [
                    [
                        "002897.SZ",
                        "20260429",
                        "20260429",
                        "20260331",
                        "1",
                        "1",
                        1_292_496_454.28,
                        40_269_539.16,
                        47_379_513.17,
                        6_497_551.90,
                    ]
                ],
            },
        },
        "balancesheet": {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "update_flag",
                    "money_cap",
                    "st_borr",
                    "lt_borr",
                    "bond_payable",
                    "non_cur_liab_due_1y",
                    "lease_liab",
                    "total_share",
                ],
                "items": [
                    [
                        "002897.SZ",
                        "20260429",
                        "20260429",
                        "20260331",
                        "1",
                        "1",
                        1_116_175_380.46,
                        500_000_000.0,
                        700_000_000.0,
                        0.0,
                        100_000_000.0,
                        20_000_000.0,
                        191_759_710.0,
                    ]
                ],
            },
        },
        "cashflow": {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "update_flag",
                    "n_cashflow_act",
                    "c_pay_acq_const_fiolta",
                ],
                "items": [
                    [
                        "002897.SZ",
                        "20260429",
                        "20260429",
                        "20260331",
                        "1",
                        "1",
                        274_473_673.57,
                        59_295_223.11,
                    ]
                ],
            },
        },
    }

    def transport(request):
        body = json.loads(request.data.decode("utf-8"))
        return TransportResponse(
            json.dumps(responses[body["api_name"]]).encode(),
            {},
        )

    provider = TushareCompatibleProvider(
        "gateway",
        "tushare-http@2",
        "http://127.0.0.1:9/",
        "secret",
        "preconfigured_tushare_compatible_non_official",
        "gateway-terms-pending@1",
        transport,
        SourceAuthority.STRUCTURED_AGGREGATOR,
    )
    datasets = (
        "trade_cal",
        "market_universe",
        "daily",
        "income",
        "balancesheet",
        "cashflow",
    )
    policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        "preconfigured_tushare_compatible_non_official",
        SourceAuthority.STRUCTURED_AGGREGATOR,
        "gateway-terms-pending@1",
        SourceRights(True, True, True, True, False, "2026-07-24"),
        tuple(
            SourceRoute(
                dataset,
                1,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            )
            for dataset in datasets
        ),
    )
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=QueryPolicy("QueryPolicy@1", 550, "L", "none"),
        source_policy=policy,
    )
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
    snapshot = root.data.sync(
        SyncRequest(
            "tushare-financial-research",
            "security_yihua",
            "002897",
            "2026-07-28",
            datetime.now(timezone.utc) + timedelta(minutes=1),
            "Asia/Shanghai",
            "SZSE",
            SnapshotPurpose.RESEARCH,
            datasets,
            True,
            False,
        )
    )
    assert snapshot.status is SyncStatus.COMPLETE
    assert snapshot.snapshot_id is not None
    result = root.research.handle(
        StartResearchWorkflow(
            ResearchWorkflowRequest(
                "ResearchWorkflowRequest@2",
                "tushare-financial-report",
                "security_yihua",
                "2026-07-28",
                "2026-07-28",
                snapshot.snapshot_id,
                replace(
                    _plan(),
                    horizon=EvaluationHorizon(
                        "2026-07-28",
                        "2028-12-31",
                        "2026-10-31",
                    ),
                ),
            )
        )
    )
    payload = root.archive.source_payload(result.research_run_id)
    assert payload["status"] == "completed_with_limits", payload
    assert payload["permissions"]["research_report"] is True
    assert payload["permissions"]["formal_per_share_valuation"] is False
    assert payload["capabilities"]["research_report"]["status"] != "blocked"
    assert payload["capabilities"]["financial_model"]["status"] == "limited"
    assert payload["permissions"]["scenario_analysis"] is True
    assert {
        item["field_name"] for item in payload["evidence"]
    } >= {
        "revenue",
        "net_income",
        "cash",
        "debt",
        "cfo",
        "capex",
        "current_price",
    }
    assert all(item["tier"] == "terminal" for item in payload["sources"])
    assert all("://" not in item["url_or_api"] for item in payload["sources"])
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
