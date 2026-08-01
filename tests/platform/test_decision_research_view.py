from __future__ import annotations

import json
from pathlib import Path
import re

from tests.platform.test_research_workflow import _request, _root
from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application.contracts import StartResearchWorkflow
from trading_platform.research_presentation import (
    _render_estimate_boundary,
    render_research_decision_html,
)
from trading_platform.research_view import ResearchDecisionView


def test_json_html_and_pdf_are_persisted_projections_of_one_view_v2(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("view:canonical"))
    )
    payload = root.archive.decision_view(result.workflow_run_id)
    view = json.loads(payload.json_bytes)

    assert view["schema_version"] == "ResearchDecisionView@2"
    assert view["view_id"].startswith("research_view_")
    assert view["workflow_run_id"] == result.workflow_run_id
    assert view["research_run_id"] == result.research_run_id
    assert b"ResearchDecisionView@2" in payload.html_bytes
    assert payload.pdf_bytes.startswith(b"%PDF-")
    assert payload.json_artifact_id == result.json_artifact_id
    root.close()


def test_view_v2_reloads_without_recomputing_research_semantics(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("view:restart"))
    )
    expected = root.archive.decision_view(result.workflow_run_id)
    root.close()

    rebuilt = PlatformTaskFixture(tmp_path)
    actual = rebuilt.archive.decision_view(result.workflow_run_id)
    assert actual == expected
    rebuilt.close()


def test_limited_view_exposes_unknowns_without_rating_or_target_language(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("view:financial-boundary"))
    )
    view = json.loads(
        root.archive.decision_view(result.workflow_run_id).json_bytes
    )
    serialized = json.dumps(view, ensure_ascii=False).lower()

    assert view["status"] == "completed_with_limits"
    assert view["data_quality_grade"] in {"A", "B", "C", "D"}
    assert view["valuation_view"]["status"] == "unavailable"
    assert view["story"]["what_happens"]
    assert view["key_drivers"]
    assert view["key_uncertainties"]
    assert view["valuation_simulation"]["status"] == "not_run"
    assert view["market_price_paths"]["status"] == "not_run"
    assert re.search(
        r"(?<![a-z])(?:buy|sell|hold)(?![a-z])",
        serialized,
    ) is None
    for forbidden in ("买入", "卖出", "持有"):
        assert forbidden not in serialized
    root.close()


def test_estimate_boundary_renders_range_policy_basis_and_invalidation() -> None:
    html = _render_estimate_boundary(
        {
            "estimate_metadata": {
                "basis_sources": ["source_prior_q2"],
                "policy": "FrozenSnapshotEstimator@1",
                "range_policy": "RelativeUncertaintyBand20Percent@1",
                "lower_bound": "8000000",
                "upper_bound": "12000000",
                "rationale": "使用同口径上年同期来源观测形成有界估算。",
                "invalidation_condition": "目标期正式值出现时失效。",
            }
        }
    )

    assert "8000000 – 12000000" in html
    assert "RelativeUncertaintyBand20Percent@1" in html
    assert "source_prior_q2" in html
    assert "目标期正式值出现时失效" in html
