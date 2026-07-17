from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from equity_research import ForecastEngine, ScenarioValuationEngine
from tests.platform.test_market_path_simulation_artifact import (
    _install_market_snapshot,
    _market_path_drafts,
)
from tests.platform.test_outlook_artifacts import _request as yihua_request
from tests.platform.test_research_workflow import CountingEngine, _artifact_bytes, _root
from tests.test_market_path_simulation import request as market_path_request
from tests.test_scenario_valuation import cyclical_request
from trading_platform import ProductionCompositionRoot
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.domain.workflow import (
    FieldSemantics,
    ResearchProjection,
    ResearchWorkflowRequest,
)


ROOT = Path(__file__).resolve().parents[2]
DFD_EXAMPLE = ROOT / "examples" / "duofuduo-002407"
FORBIDDEN = ("BUY", "HOLD", "SELL", "买入", "卖出", "持有", "目标价")


def _load_dfd(name: str):
    return json.loads((DFD_EXAMPLE / name).read_text(encoding="utf-8"))


def _dfd_projection() -> ResearchProjection:
    manifest = _load_dfd("source_manifest.json")
    semantics = tuple(
        FieldSemantics(
            source_id=source["source_id"],
            source_authority=source["tier"],
            field_name=field["field_name"],
            period=field["period"],
            statement_scope=field.get("statement_scope", "consolidated"),
            unit=field.get("unit", ""),
            currency=field.get("currency", ""),
            scale=str(field.get("scale", "1")),
            restatement_status=field.get("restatement_status", "as_reported"),
            published_at=source.get("published_at", source["report_date"]),
            available_at=source.get("available_at", source["retrieved_at"]),
            retrieved_at=source["retrieved_at"],
            supersedes_identity=source.get("supersedes_identity"),
            availability_basis=(
                "publisher_timestamp"
                if source.get("available_at")
                else "conservative_retrieval_time"
            ),
        )
        for source in manifest["sources"]
        for field in source["extracted_fields"]
    )
    return ResearchProjection(
        manifest=manifest,
        estimates=None,
        context=_load_dfd("research_context.json"),
        as_of_date="2026-07-03",
        profile="standard",
        field_semantics=semantics,
        diluted_share_identity="",
        net_debt_bridge_identity="SRC_CNINFO_2026Q1:cash+debt:2026Q1",
    )


def _dfd_request(invocation_id: str) -> ResearchWorkflowRequest:
    return ResearchWorkflowRequest(
        invocation_id=invocation_id,
        security_id="security_duofuduo",
        requested_date="2026-07-03",
        effective_session_date="2026-07-03",
        projection=_dfd_projection(),
    )


def test_yihua_complete_outlook_replays_after_restart(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    request = replace(
        yihua_request(
            "journey:yihua:first",
            _market_path_drafts(bound_request),
        ),
        workflow_snapshot_id=bound_request.calibration.platform_snapshot_id,
        candidate_member_ids=market_member_ids,
        market_only_member_ids=market_member_ids,
    )
    first = root.facade.run_research_workflow(request)
    research_run = root.facade.get_research_run_payload(first.research_run_id)
    assert research_run["status"] != "blocked"
    artifacts = tuple(
        root.facade.get_research_artifact(record_id)
        for record_id in first.artifact_record_ids
    )
    assert [item.artifact_kind for item in artifacts] == [
        "DataSnapshot",
        "Forecast",
        "Valuation",
        "Simulation",
        "MarketDataSnapshot",
        "MarketPathSimulation",
    ]
    assert all(item.content_hash for item in artifacts)
    manifest = root.facade.get_artifact_manifest(first.final_manifest_id)
    assert {
        "research_run_json",
        "research_report_html",
        "forecast",
        "valuation",
        "simulation",
        "market_path_simulation",
    } <= {member["member_role"] for member in manifest.members}
    view = root.facade.get_workspace(
        "security_yihua",
        first.research_snapshot_id,
    )["research_views"][0]
    assert view["story"]["what_happens"]
    assert view["key_drivers"]
    assert [item["role"] for item in view["scenarios"]] == [
        "stress",
        "base",
        "improvement",
    ]
    methods = {
        method["method_id"]
        for scenario in view["scenarios"]
        for method in scenario["methods"]
        if method["status"] == "ready"
    }
    assert {"fcff_dcf", "sotp", "reverse_dcf"} <= methods
    assert view["valuation_simulation"]["converged"] is True
    assert view["market_price_paths"]["terminal_price_quantiles"]
    assert view["value_market_divergence"]["status"] == "not_comparable_horizon"
    rendered = json.dumps(view, ensure_ascii=False)
    assert not any(term in rendered for term in FORBIDDEN)
    hashes = tuple(item.content_hash for item in artifacts)
    root.close()

    rebuilt = ProductionCompositionRoot(tmp_path, research_engine=engine)
    replay = rebuilt.facade.run_research_workflow(replace(request, invocation_id="journey:yihua:replay"))
    replayed = tuple(
        rebuilt.facade.get_research_artifact(record_id)
        for record_id in replay.artifact_record_ids
    )
    assert replay.research_run_id == first.research_run_id
    assert replay.research_snapshot_id == first.research_snapshot_id
    assert replay.artifact_record_ids == first.artifact_record_ids
    assert tuple(item.content_hash for item in replayed) == hashes
    replay_manifest = rebuilt.facade.get_artifact_manifest(replay.final_manifest_id)
    assert [item["member_role"] for item in replay_manifest.members] == [
        item["member_role"] for item in manifest.members
    ]
    first_by_role = {item["member_role"]: item for item in manifest.members}
    replay_by_role = {
        item["member_role"]: item for item in replay_manifest.members
    }
    for role in (
        "data_snapshot",
        "forecast",
        "valuation",
        "simulation",
        "market_data_snapshot",
        "market_path_simulation",
    ):
        assert replay_by_role[role]["artifact_id"] == first_by_role[role][
            "artifact_id"
        ]
    assert (
        rebuilt.facade.get_workflow_history(replay.workflow_run_id).final_manifest_id
        == replay.final_manifest_id
    )
    rebuilt.close()


def test_duofuduo_real_sources_degrade_without_inventing_dilution(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = ProductionCompositionRoot(tmp_path, research_engine=engine)
    root.facade.add_watchlist_item(
        "watch:security_duofuduo",
        SecurityIdentity("security_duofuduo", "SZSE", "002407", "CNY", "2010-05-18"),
    )
    result = root.facade.run_research_workflow(_dfd_request("journey:dfd:first"))
    payload = json.loads(_artifact_bytes(root, result.json_artifact_id))
    html = _artifact_bytes(root, result.html_artifact_id).decode("utf-8")

    assert payload["company"]["ticker"] == "002407.SZ"
    assert payload["permissions"]["formal_per_share_valuation"] is False
    assert any(item["field_name"] == "diluted_shares" for item in payload["declared_missing"])
    assert not any(item["field_name"] == "diluted_shares" for item in payload["evidence"])
    assert "选择权" in html
    assert "不能在合并收入或利润估值后再次完整叠加" in html
    assert "资本开支" in html and "资金成本" in html
    assert not any(term in html for term in FORBIDDEN)
    assert result.artifact_record_ids == ()
    root_manifest_members = root.facade.get_artifact_manifest(
        result.final_manifest_id
    ).members
    root.close()

    rebuilt = ProductionCompositionRoot(tmp_path, research_engine=engine)
    replay = rebuilt.facade.run_research_workflow(_dfd_request("journey:dfd:replay"))
    assert replay.research_run_id == result.research_run_id
    assert replay.research_snapshot_id == result.research_snapshot_id
    assert rebuilt.facade.get_research_run_payload(result.research_run_id)["permissions"]["formal_per_share_valuation"] is False
    replay_manifest = rebuilt.facade.get_artifact_manifest(replay.final_manifest_id)
    assert [item["member_role"] for item in replay_manifest.members] == [
        item["member_role"] for item in root_manifest_members
    ]
    assert (
        rebuilt.facade.get_workflow_history(replay.workflow_run_id).final_manifest_id
        == replay.final_manifest_id
    )
    rebuilt.close()


def test_cyclical_model_golden_is_separate_from_duofuduo_evidence() -> None:
    request = cyclical_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    result = ScenarioValuationEngine().run(request)

    assert graph.template_id == "cyclical_resource_driver_graph@1"
    assert request.base_forecast_request.security.security_id != "002407.SZ"
    for scenario in result.scenarios:
        assert scenario.method("fcff_dcf").status == "blocked"
        assert scenario.method("mid_cycle_ev_ebitda").status == "ready"
        assert scenario.method("resource_nav").status == "ready"
        assert scenario.method("cyclical_historical_band").status == "ready"
        assert scenario.method("resource_nav").conditional_value_range is not None
        assert scenario.method("resource_nav").conditional_value_range.base.bridge_trace
        sensitivity = {
            item.name for item in scenario.method("resource_nav").sensitivity
        }
        assert {"commodity_price", "production_volume", "unit_cost", "maintenance_capex"} <= sensitivity
