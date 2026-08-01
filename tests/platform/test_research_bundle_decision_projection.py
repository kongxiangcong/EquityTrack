from __future__ import annotations

from copy import deepcopy
import io
import json
import re
from typing import Mapping

import pytest
from pypdf import PdfReader

from tests.platform.test_research_workflow import _request
from trading_platform.domain.research_evaluation import (
    ResearchDecisionViewFactory,
)
from trading_platform.identity import canonical_hash
from trading_platform.research_pdf import ResearchDecisionPdf
from trading_platform.research_presentation import (
    render_research_decision_html,
)
from trading_platform.research_view import ResearchDecisionView


COMPONENT_NAMES = (
    "forecast",
    "scenario_valuation",
    "valuation_method_route",
    "valuation_simulation_decision",
    "market_path_decision",
    "recent_trend_assessment",
)


def _quantity(value: str, unit: str = "CNY/share") -> Mapping[str, str]:
    return {
        "value": value,
        "unit": unit,
        "currency": "CNY",
        "period": "2028E",
    }


def _valuation_point(value: str) -> Mapping[str, object]:
    return {
        "basis_value": _quantity(value, "CNY"),
        "equity_value": _quantity(value, "CNY"),
        "per_share_value": _quantity(value),
        "bridge_trace": (),
    }


def _scenarios(*, ready: bool) -> tuple[Mapping[str, object], ...]:
    values = {
        "stress": ("压力情景", "8"),
        "base": ("基准情景", "10"),
        "improvement": ("改善情景", "12"),
    }
    return tuple(
        {
            "scenario_id": f"scenario_{role}",
            "role": role,
            "label": label,
            "probability_evidence": None,
            "rationale_refs": [f"source_{role}"],
            "forecast_graph": {
                "schema_version": "ForecastGraph@2",
                "graph_id": f"forecast_{role}",
            },
            "methods": [
                {
                    "method_id": "fcff_dcf",
                    "status": "ready" if ready else "blocked",
                    "applicability": (
                        "applicable"
                        if ready
                        else "required inputs unavailable"
                    ),
                    "value_basis": "per_share_value",
                    "horizon": "2028E",
                    "assumptions": [],
                    "formula_version": "fcff_dcf@1",
                    "conditional_value_range": (
                        {
                            "low": _valuation_point(str(int(value) - 1)),
                            "base": _valuation_point(value),
                            "high": _valuation_point(str(int(value) + 1)),
                        }
                        if ready
                        else None
                    ),
                    "sensitivity": [],
                    "diagnostics": (
                        []
                        if ready
                        else ["VALUATION_METHOD_INPUTS_INSUFFICIENT"]
                    ),
                    "lineage_refs": [f"source_{role}"],
                    "component_trace": [],
                }
            ],
        }
        for role, (label, value) in values.items()
    )


def _component(
    name: str,
    status: str,
    reason: str,
    content: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        "artifact_id": f"{name}_artifact",
        "schema_version": "ResearchComponentResult@1",
        "component": name,
        "status": status,
        "reason_codes": [reason],
        "content": dict(content),
        "source_member_ids": ["member_official", "member_market"],
    }


def _identified_bundle(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    bundle = deepcopy(value)
    origin = bundle["origin"]
    assert isinstance(origin, dict)
    origin_content = {
        key: item for key, item in origin.items() if key != "origin_id"
    }
    origin["origin_id"] = (
        "research_origin_" + canonical_hash(origin_content)[:24]
    )
    for name in COMPONENT_NAMES:
        component = bundle[name]
        assert isinstance(component, dict)
        component_content = {
            key: item
            for key, item in component.items()
            if key != "artifact_id"
        }
        component["artifact_id"] = (
            f"{name}_" + canonical_hash(component_content)[:24]
        )
    bundle_content = {
        key: item for key, item in bundle.items() if key != "bundle_id"
    }
    bundle["bundle_id"] = (
        "research_bundle_" + canonical_hash(bundle_content)[:24]
    )
    return bundle


def _research_run(*, ready: bool) -> Mapping[str, object]:
    return {
        "schema_version": 3,
        "run_id": "research_bundle_run",
        "status": "completed" if ready else "completed_with_limits",
        "permissions": {
            "research_report": True,
            "formal_per_share_valuation": ready,
        },
        "summary": {
            "data_quality_grade": "B" if ready else "D",
            "executive_summary": (
                "经营推演由冻结证据支持。"
                if ready
                else "研究证据可用，但正式估值输入不足。"
            ),
            "evidence_counts": {"total": 2},
        },
        "analysis": {"dimensions": {}},
        "synthesis": {
            "core_thesis": "结论保持条件性并受证据边界约束。",
            "risk_reward_summary": "展示潜在改善与主要约束。",
            "key_uncertainties": ["关键输入仍需持续复核。"],
            "what_would_change_the_view": ["获得新的合格正式披露。"],
        },
        "methods": {},
        "evidence": [],
        "sources": [],
        "declared_missing": [],
        "integrity_issues": [],
        "conditional_plan": [],
        "diagnostics": [],
    }


def _bundle(*, ready: bool) -> Mapping[str, object]:
    scenario_status = "complete" if ready else "blocked"
    route_status = "complete" if ready else "blocked"
    simulation_status = "complete" if ready else "not_run"
    market_status = "complete" if ready else "not_run"
    trend_status = "complete" if ready else "blocked"
    return {
        "bundle_id": "research_bundle_projection",
        "schema_version": "ResearchEvaluationBundle@1",
        "origin": {
            "origin_id": "research_origin_projection",
            "schema_version": "ResearchEvaluationOrigin@1",
            "data_snapshot_id": "snapshot_filing",
            "source_policy_identity": "source-policy@test",
            "snapshot_member_ids": ["member_official", "member_market"],
            "research_policy_identity": "ResearchEvaluationPolicy@2",
            "estimation_policy_identity": "FrozenSnapshotEstimator@1",
        },
        "estimates": (
            None
            if ready
            else {
                "schema_version": "BoundedEstimates@1",
                "status": "limited",
                "reason_codes": ["OFFICIAL_INPUTS_PARTIAL"],
            }
        ),
        "research_run": _research_run(ready=ready),
        "forecast": _component(
            "forecast",
            "complete" if ready else "blocked",
            (
                "FORECAST_COMPLETE"
                if ready
                else "FORECAST_TYPED_INPUTS_INSUFFICIENT"
            ),
            {
                "schema_version": "ForecastGraph@2",
                "graph_id": "forecast_graph_projection",
                "template_id": (
                    "manufacturing_driver_graph@2"
                    if ready
                    else "data_insufficient@1"
                ),
                "nodes": [],
            },
        ),
        "scenario_valuation": _component(
            "scenario_valuation",
            scenario_status,
            (
                "SCENARIO_VALUATION_COMPLETE"
                if ready
                else "VALUATION_METHOD_INPUTS_INSUFFICIENT"
            ),
            {
                "probability_mode": "not_used",
                "scenarios": _scenarios(ready=ready),
                "weighted_method_ranges": [],
                "weighting_diagnostics": [],
                "cross_method_composite": None,
            },
        ),
        "valuation_method_route": _component(
            "valuation_method_route",
            route_status,
            (
                "VALUATION_METHOD_ROUTE_COMPLETE"
                if ready
                else "VALUATION_METHOD_NOT_APPLICABLE"
            ),
            {
                "schema_version": "ValuationMethodRoute@1",
                "ready_method_ids": ["fcff_dcf"] if ready else [],
                "methods": {},
                "formal_per_share_valuation": ready,
            },
        ),
        "valuation_simulation_decision": _component(
            "valuation_simulation_decision",
            simulation_status,
            (
                "VALUATION_SIMULATION_COMPLETE"
                if ready
                else "FORMAL_VALUATION_UNAVAILABLE"
            ),
            {
                "schema_version": "ValuationSimulationDecision@1",
                "status": "ready" if ready else "not_run",
                "reason_code": (
                    "VALUATION_SIMULATION_COMPLETE"
                    if ready
                    else "FORMAL_VALUATION_UNAVAILABLE"
                ),
                "result": (
                    {
                        "status": "ready",
                        "converged": True,
                        "quantiles": {"p5": "8", "p50": "10", "p95": "12"},
                        "contributions": [],
                        "diagnostics": [],
                    }
                    if ready
                    else None
                ),
                "interpretation": (
                    "Intrinsic-value uncertainty is conditional and is not "
                    "a target price."
                ),
            },
        ),
        "market_path_decision": _component(
            "market_path_decision",
            market_status,
            (
                "MARKET_PATH_COMPLETE"
                if ready
                else "MARKET_PATH_INPUTS_UNAVAILABLE"
            ),
            {
                "schema_version": "MarketPathDecision@1",
                "status": "ready" if ready else "not_run",
                "reason_code": (
                    "MARKET_PATH_COMPLETE"
                    if ready
                    else "MARKET_PATH_INPUTS_UNAVAILABLE"
                ),
                "result": (
                    {
                        "status": "ready",
                        "terminal_price_quantiles": {
                            "p5": "7",
                            "p50": "10",
                            "p95": "14",
                        },
                        "horizon_return_quantiles": {"p50": "0.08"},
                        "maximum_drawdown_quantiles": {"p50": "-0.18"},
                        "diagnostics": [],
                    }
                    if ready
                    else None
                ),
                "interpretation": (
                    "Market paths describe risk and are not trading instructions."
                ),
            },
        ),
        "recent_trend_assessment": _component(
            "recent_trend_assessment",
            trend_status,
            (
                "RECENT_TREND_COMPLETE"
                if ready
                else "RECENT_TREND_HISTORY_INSUFFICIENT"
            ),
            {
                "schema_version": "RecentTrendAssessment@1",
                "assessment_id": "recent_trend_projection",
                "status": trend_status,
                "classification": "up" if ready else None,
                "close": "10",
                "sma20": "9" if ready else None,
                "sma60": "8" if ready else None,
                "sma20_five_sessions_prior": "8.8" if ready else None,
                "window_low_20": "7.5" if ready else None,
                "observation_count": 60 if ready else 30,
                "price_basis": "unadjusted_close",
                "evidence_refs": ["member_market"],
                "reason_codes": (
                    []
                    if ready
                    else ["RECENT_TREND_HISTORY_INSUFFICIENT"]
                ),
                "content_hash": "trend_hash",
            },
        ),
    }


def _project(*, ready: bool) -> Mapping[str, object]:
    return ResearchDecisionViewFactory().build(
        workflow_run_id=(
            "workflow_bundle_ready"
            if ready
            else "workflow_bundle_degraded"
        ),
        request=_request(
            "bundle:ready" if ready else "bundle:degraded"
        ),
        evaluation_bundle=_identified_bundle(_bundle(ready=ready)),
        model_identity="engine@test",
        source_policy_identity="source-policy@test",
        expected_snapshot_member_ids=(
            "member_official",
            "member_market",
        ),
    )


def _bundle_for_valuation_state(
    expected: str,
) -> Mapping[str, object]:
    bundle = deepcopy(
        _bundle(ready=expected in {"ready", "limited", "blocked"})
    )
    research_run = bundle["research_run"]
    assert isinstance(research_run, dict)
    if expected == "limited":
        research_run["status"] = "completed_with_limits"
        permissions = research_run["permissions"]
        assert isinstance(permissions, dict)
        permissions["formal_per_share_valuation"] = False
        scenario = bundle["scenario_valuation"]
        assert isinstance(scenario, dict)
        scenario["status"] = "limited"
        scenario["reason_codes"] = ["SCENARIO_VALUATION_PARTIAL"]
        route = bundle["valuation_method_route"]
        assert isinstance(route, dict)
        route_content = route["content"]
        assert isinstance(route_content, dict)
        route_content["formal_per_share_valuation"] = False
    elif expected == "blocked":
        research_run["status"] = "blocked"
        research_run["integrity_issues"] = [
            {
                "severity": "error",
                "code": "SOURCE_MANIFEST_INTEGRITY_FAILED",
                "message": "Frozen evidence failed integrity validation.",
                "path": "sources[0]",
            }
        ]
    return _identified_bundle(bundle)


@pytest.mark.parametrize(
    "expected",
    ("ready", "limited", "unavailable", "blocked"),
)
def test_bundle_projects_only_the_four_canonical_valuation_states(
    expected: str,
) -> None:
    projected = ResearchDecisionViewFactory().build(
        workflow_run_id=f"workflow_bundle_{expected}",
        request=_request(f"bundle:{expected}"),
        evaluation_bundle=_bundle_for_valuation_state(expected),
        model_identity="engine@test",
        source_policy_identity="source-policy@test",
        expected_snapshot_member_ids=(
            "member_official",
            "member_market",
        ),
    )

    assert projected["valuation_view"]["status"] == expected
    assert projected["valuation_view"]["status"] in {
        "ready",
        "limited",
        "unavailable",
        "blocked",
    }


def test_ready_bundle_projects_exact_components_to_json_html_and_pdf() -> None:
    projected = _project(ready=True)
    view = ResearchDecisionView.from_dict(projected)
    html = render_research_decision_html(view)
    pdf = ResearchDecisionPdf().render(projected)
    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(pdf)).pages
    )

    assert [item["role"] for item in projected["scenarios"]] == [
        "stress",
        "base",
        "improvement",
    ]
    assert projected["valuation_view"]["status"] == "ready"
    assert projected["valuation_simulation"]["result"]["quantiles"]["p50"] == "10"
    assert projected["market_price_paths"]["result"][
        "terminal_price_quantiles"
    ]["p50"] == "10"
    audit = projected["audit"]["evaluation_bundle"]
    assert audit["origin"]["origin_id"].startswith("research_origin_")
    assert set(audit["components"]) == set(COMPONENT_NAMES)
    assert audit["components"]["forecast"]["status"] == "complete"
    assert "压力情景" in html
    assert "改善情景" in html
    assert "近期走势" in html
    assert "up" in html
    assert "forecast" in pdf_text
    assert "complete" in pdf_text


def test_degraded_bundle_preserves_local_fail_closed_reasons_without_advice() -> None:
    projected = _project(ready=False)
    view = ResearchDecisionView.from_dict(projected)
    html = render_research_decision_html(view)
    pdf = ResearchDecisionPdf().render(projected)
    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    serialized = json.dumps(projected, ensure_ascii=False).lower()

    assert [item["role"] for item in projected["scenarios"]] == [
        "stress",
        "base",
        "improvement",
    ]
    assert projected["valuation_view"]["status"] == "unavailable"
    assert projected["valuation_simulation"]["status"] == "not_run"
    assert projected["market_price_paths"]["status"] == "not_run"
    audit = projected["audit"]["evaluation_bundle"]
    assert audit["estimates"]["status"] == "limited"
    assert audit["components"]["forecast"]["reason_codes"] == (
        "FORECAST_TYPED_INPUTS_INSUFFICIENT",
    )
    assert audit["components"]["recent_trend_assessment"][
        "source_member_ids"
    ] == ("member_official", "member_market")
    assert "FORECAST_TYPED_INPUTS_INSUFFICIENT" in html
    assert "RECENT_TREND_HISTORY_INSUFFICIENT" in html
    assert "recent_trend_assessment" in pdf_text
    assert re.search(
        r"(?<![a-z])(?:buy|sell|hold)(?![a-z])",
        serialized,
    ) is None
    for forbidden in ("买入", "卖出", "持有"):
        assert forbidden not in serialized
