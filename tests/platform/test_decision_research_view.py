from __future__ import annotations

import json
from pathlib import Path

from tests.platform.test_research_workflow import _request, _root
from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application.contracts import StartResearchWorkflow


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
    assert view["valuation_view"]["status"] == "not_ready"
    assert view["key_uncertainties"]
    for forbidden in ("buy", "sell", "hold", "买入", "卖出", "持有"):
        assert forbidden not in serialized
    root.close()
