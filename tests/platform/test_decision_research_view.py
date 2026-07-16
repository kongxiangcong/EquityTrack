from __future__ import annotations

import json
import re
from pathlib import Path

from tests.platform.test_outlook_artifacts import (
    _drafts,
    _request,
)
from tests.platform.test_research_workflow import (
    CountingEngine,
    _artifact_bytes,
    _root,
)


def test_workspace_builds_decision_first_view_from_typed_artifacts_not_html(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.facade.run_research_workflow(_request("decision-view:v1"))

    html_path = root._store.connection.execute(
        "SELECT o.relative_path FROM research_run_record r "
        "JOIN artifact a ON a.artifact_id=r.html_artifact_id "
        "JOIN object_blob o ON o.sha256=a.object_sha256 "
        "WHERE r.research_run_id=?",
        (result.research_run_id,),
    ).fetchone()[0]
    (tmp_path / html_path).write_bytes(b"<script>not-authoritative()</script>")

    workspace = root.facade.get_workspace(
        "security_yihua",
        result.research_snapshot_id,
    )
    assert len(workspace["research_views"]) == 1
    view = workspace["research_views"][0]
    assert view["schema_version"] == "ResearchDecisionView@2"
    assert view["subject_id"] == "002897.SZ"
    assert tuple(view["story"]) == (
        "what_happens",
        "why_it_matters",
        "transmission",
        "counterevidence",
        "what_would_change_the_view",
    )
    assert view["key_drivers"]
    assert [scenario["role"] for scenario in view["scenarios"]] == [
        "stress",
        "base",
        "improvement",
    ]
    for scenario in view["scenarios"]:
        assert scenario["drivers"]
        assert {item["metric_id"] for item in scenario["financials"]} >= {
            "company.revenue",
            "company.ebit",
            "company.fcff",
        }
        ready = [method for method in scenario["methods"] if method["status"] == "ready"]
        assert ready and all(method["conditional_per_share_range"] for method in ready)
        assert all(
            method["reconciliation"]["base"]["bridge_trace"]
            for method in ready
        )
        assert all(method["horizon"] and method["value_basis"] for method in ready)
        assert all("display_diagnostics" in method for method in ready)
    assert all("blocked:" not in item for item in view["story"]["counterevidence"])
    assert view["market_implied_expectations"]
    assert all(
        item["metric_id"] == "implied_terminal_growth"
        for item in view["market_implied_expectations"]
    )
    assert view["audit"]["artifact_records"]
    assert view["audit"]["fact_evidence"]
    assert view["audit"]["formula_identities"]
    assert "<script>" not in json.dumps(view)
    forbidden = ("BUY", "HOLD", "SELL", "买入", "卖出", "持有", "目标价")
    rendered = json.dumps(view, ensure_ascii=False)
    assert not any(term in rendered for term in forbidden)
    root.close()


def test_formal_json_and_html_share_the_exact_decision_view(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.facade.run_research_workflow(
        _request("decision-view:canonical-presentation")
    )

    payload = json.loads(
        _artifact_bytes(root, result.json_artifact_id)
    )
    html = _artifact_bytes(root, result.html_artifact_id).decode("utf-8")
    embedded = re.search(
        r'<script type="application/json" '
        r'id="research-decision-view">(.*?)</script>',
        html,
    )

    assert payload["schema_version"] == "ResearchDecisionView@2"
    assert embedded is not None
    assert json.loads(embedded.group(1)) == payload
    assert "未来故事" in html
    assert payload["story"]["what_happens"] in html
    assert "审计附录" in html
    assert "ResearchReportHtml@1" not in html
    root.close()


def test_workspace_exposes_parallel_historical_view_versions(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    first = root.facade.run_research_workflow(_request("decision-view:model-v1"))
    second = root.facade.run_research_workflow(
        _request(
            "decision-view:model-v2",
            _drafts(model_identity="company-outlook-model@2"),
        )
    )
    workspace = root.facade.get_workspace(
        "security_yihua",
        first.research_snapshot_id,
    )
    views = workspace["research_views"]
    assert len(views) == 2
    assert first.research_run_id == second.research_run_id
    assert [view["workflow_run_id"] for view in views] == [
        first.workflow_run_id,
        second.workflow_run_id,
    ]
    assert [view["model_identity"] for view in views] == [
        "company-outlook-model@1",
        "company-outlook-model@2",
    ]
    assert len({view["view_id"] for view in views}) == 2
    assert len({view["valuation_artifact_record_id"] for view in views}) == 2
    second_payload = json.loads(
        _artifact_bytes(root, second.json_artifact_id)
    )
    assert second_payload["model_identity"] == "company-outlook-model@2"
    root.close()
