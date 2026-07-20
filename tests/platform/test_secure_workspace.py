from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tests.platform.test_chart_annotations import ROOT, _root
from trading_platform.web_server import LocalChartWorkspaceServer
from trading_platform.application.market_contracts import EvaluatePlanCommand
from tests.platform.test_market_evaluation import _market_command, _root as market_root
from tests.platform.test_trade_plans import _content, _root as plan_root
from trading_platform.domain.plans import CreatePlanDraftCommand
from trading_platform.domain.chart import AnnotationCommand
from tests.platform.test_chart_annotations import _draft as annotation_draft
from tests.platform.test_data_sync_pit import _request as sync_request, _root as sync_root
from tests.platform.test_research_workflow import _request as research_request
from trading_platform.domain.chart import AnnotationLink
from trading_platform.domain.plans import ConfirmPlanDraftCommand, PlanCondition, PlanConstant, PlanDraftContent, PlanReference, PlanRule
from trading_platform.identity.code import CodeIdentity
from trading_platform.application.market_contracts import BuildMarketSnapshotCommand
from trading_platform.operations import PlatformOperations
from trading_platform.application.contracts import SecurityIdentity


def _server(tmp_path: Path):
    root = _root(tmp_path)
    server = LocalChartWorkspaceServer(root.facade, ROOT / "web/dist", "security_yihua", "snapshot_chart")
    return root, server, server.start()


def test_workspace_security_headers_and_safe_history_projection(tmp_path: Path) -> None:
    root, server, base = _server(tmp_path)
    response = urlopen(base + "/api/workspace")
    payload = json.loads(response.read())
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert payload["task"]["security_id"] == "security_yihua"
    assert payload["history"]["annotations"] == []
    serialized = json.dumps(payload)
    assert str(tmp_path) not in serialized and "csrf" not in serialized.lower()
    server.close(); root.close()


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"},
    {"Origin": "http://evil.example", "Content-Type": "application/json"},
    {"Origin": "http://127.0.0.1:1", "Content-Type": "text/plain"},
])
def test_rejects_rebinding_cross_origin_and_wrong_content_type(tmp_path: Path, headers: dict[str, str]) -> None:
    root, server, base = _server(tmp_path)
    request = Request(base + "/api/annotations", data=b"{}", method="POST", headers=headers)
    with pytest.raises(HTTPError) as rejected:
        urlopen(request)
    assert rejected.value.code in {403, 421}
    server.close(); root.close()


def test_get_cannot_mutate_and_oversized_body_is_rejected(tmp_path: Path) -> None:
    root, server, base = _server(tmp_path)
    with pytest.raises(HTTPError) as get_mutation:
        urlopen(base + "/api/annotations/delete")
    assert get_mutation.value.code == 404
    html = urlopen(base).read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    request = Request(base + "/api/annotations", data=b"x" * 32769, method="POST", headers={"Origin": base, "Content-Type": "application/json", "X-CSRF-Token": token, "X-Invocation-Id": "oversized"})
    with pytest.raises(HTTPError) as oversized:
        urlopen(request)
    assert oversized.value.code == 413
    server.close(); root.close()


def test_update_authorization_is_csrf_protected_immutable_and_replay_safe(tmp_path: Path) -> None:
    root, server, base = _server(tmp_path)
    html = urlopen(base).read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    body = json.dumps({"requested_date": "2026-07-11", "effective_session_date": "2026-07-10"}).encode()
    headers = {"Origin": base, "Content-Type": "application/json", "X-CSRF-Token": token, "X-Invocation-Id": "browser:update-auth"}
    first = json.loads(urlopen(Request(base + "/api/update-authorizations", data=body, method="POST", headers=headers)).read())
    replay = json.loads(urlopen(Request(base + "/api/update-authorizations", data=body, method="POST", headers=headers)).read())
    assert replay["update_authorization_id"] == first["update_authorization_id"]
    assert root._store.connection.execute("SELECT count(*) FROM update_authorization").fetchone()[0] == 1
    with pytest.raises(Exception, match="UPDATE_AUTHORIZATION_IMMUTABLE"):
        root._store.connection.execute("DELETE FROM update_authorization")
    server.close(); root.close()


def test_frozen_timeline_traverses_plan_market_evaluation_and_policy_versions(tmp_path: Path) -> None:
    root, plan = market_root(tmp_path)
    market = root.facade.build_market_snapshot(_market_command())
    evaluation = root.facade.evaluate_plan(EvaluatePlanCommand("workspace:evaluate", plan.plan_version_id, market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    upgraded = root.facade.evaluate_plan(EvaluatePlanCommand("workspace:evaluate:v2", plan.plan_version_id, market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@2"))
    projected = root.facade.get_workspace("security_yihua", "snapshot_market")
    assert projected["history"]["plans"][0]["user_input_source"] == "user_fixture_input"
    assert projected["history"]["market_snapshots"][0]["market_snapshot_id"] == market.market_snapshot_id
    assert [item["plan_evaluation_id"] for item in projected["history"]["evaluations"]] == [evaluation.plan_evaluation_id, upgraded.plan_evaluation_id]
    assert [item["evaluation_policy_version"] for item in projected["history"]["evaluations"]] == ["evaluation-policy@1", "evaluation-policy@2"]
    assert projected["history"]["evaluations"][0]["rules"][0]["operands_json"]
    assert projected["history"]["research_runs"] and projected["history"]["data_snapshots"] and projected["history"]["artifact_manifests"]
    root.close()


def test_connected_golden_journey_records_one_graph_on_one_data_root(tmp_path: Path) -> None:
    assert PlatformOperations(tmp_path).bootstrap()["status"] == "passed"
    assert PlatformOperations(tmp_path).bootstrap()["status"] == "passed"
    root = sync_root(tmp_path)
    root.facade.add_watchlist_item("golden:benchmark", SecurityIdentity("security_benchmark", "SZSE", "000300", "CNY", "2010-01-01"))
    original = root.facade.run_research_workflow(research_request("golden:research:2026-07-07"))
    root.close()

    root = sync_root(tmp_path)
    sync = root.facade.sync_data(sync_request("golden:sync:2026-07-11"))
    member_ids = tuple(item.normalized_version_id for item in root.facade.get_data_snapshot_members(sync.snapshot_id))
    research = root.facade.run_research_workflow(research_request("golden:outer-workflow:2026-07-11", requested_date="2026-07-11", effective_session_date="2026-07-10", workflow_snapshot_id=sync.snapshot_id, candidate_member_ids=member_ids, market_only_member_ids=member_ids))
    assert research.research_run_id == original.research_run_id
    assert research.research_snapshot_id == original.research_snapshot_id
    assert research.json_artifact_id != original.json_artifact_id
    assert research.html_artifact_id != original.html_artifact_id
    assert research.disposition.value == "reused" and research.reason_code == "ROUTINE_MARKET_ONLY_INPUTS" and research.stale_by_days == 3
    annotation_input = replace(annotation_draft(), data_snapshot_id=sync.snapshot_id, links=(AnnotationLink("ResearchRun", research.research_run_id, "resolved"),))
    annotation = root.facade.create_annotation(AnnotationCommand("golden:annotation", None, 0, annotation_input))
    content = PlanDraftContent("security_yihua", None, (PlanReference("ResearchRun", research.research_run_id), PlanReference("Evidence", "golden:fixture", "unresolved_external")), sync.snapshot_id, "2026-07-11", "2026-10-11", "2026-08-11", (PlanRule("golden:price", "entry_review", "prompt_review", "entry", PlanCondition("leaf", "security.close_unadjusted", "lte", PlanConstant("decimal", "80", "CNY_per_share", "CNY"), "current_complete_session")),), "10000", "500", "CNY", "market-gate@1", "metric-catalog@1", "plan-evaluator@1", "user_fixture_input", "用户明确输入的验收规则，不构成平台建议。")
    draft = root.facade.create_plan_draft(CreatePlanDraftCommand("golden:plan-draft", content))
    plan = root.facade.confirm_plan_draft(ConfirmPlanDraftCommand("golden:plan-confirm", draft.draft_id, 1, "activate"))
    identity = CodeIdentity("fixture", "source", "lock", "migration", "workflow", "frontend", "config", "package", "model-policy", "licenses")
    market = root.facade.build_market_snapshot(BuildMarketSnapshotCommand("golden:market", "security_yihua", "SZSE", sync.snapshot_id, "cn-a-share-market@1", "freshness@1", identity))
    evaluation = root.facade.evaluate_plan(EvaluatePlanCommand("golden:evaluation", plan.plan_version_id, market.market_snapshot_id, "plan-evaluator@1", "evaluation-policy@1"))
    root.close()

    rebuilt = sync_root(tmp_path)
    history = rebuilt.facade.get_workflow_history(research.workflow_run_id)
    manifest = rebuilt.facade.get_artifact_manifest(history.final_manifest_id)
    workspace = rebuilt.facade.get_workspace("security_yihua", sync.snapshot_id)
    doctor = PlatformOperations(tmp_path).doctor()
    assert manifest.producer_id == research.workflow_run_id and doctor["status"] == "passed"
    assert rebuilt.facade.get_annotation_history(annotation.annotation_id)[0].annotation_version_id == annotation.annotation_version_id
    assert rebuilt.facade.get_plan_version(plan.plan_version_id).content.references[0].ref_id == research.research_run_id
    assert rebuilt.facade.get_market_snapshot_detail(market.market_snapshot_id).data_snapshot_id == sync.snapshot_id
    assert rebuilt.facade.get_plan_evaluation_detail(evaluation.plan_evaluation_id).market_snapshot_id == market.market_snapshot_id
    assert workspace["history"]["research_runs"] and workspace["history"]["plans"] and workspace["history"]["evaluations"]
    evidence = {"schema_version": "GoldenJourneyEvidence@1", "workflow_run_id": research.workflow_run_id, "original_workflow_run_id": original.workflow_run_id, "data_snapshot_id": sync.snapshot_id, "research_snapshot_id": original.research_snapshot_id, "research_run_id": research.research_run_id, "research_json_artifact_id": original.json_artifact_id, "research_html_artifact_id": original.html_artifact_id, "annotation_version_id": annotation.annotation_version_id, "plan_version_id": plan.plan_version_id, "market_snapshot_id": market.market_snapshot_id, "plan_evaluation_id": evaluation.plan_evaluation_id, "final_artifact_manifest_id": history.final_manifest_id, "reuse_reason_code": research.reason_code, "stale_by_days": research.stale_by_days, "dispositions": {"research": research.disposition.value, "annotation": "created", "plan": "created", "market": "created", "evaluation": "created"}}
    if destination := os.environ.get("TRADING_PLATFORM_GOLDEN_EVIDENCE"):
        Path(destination).write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    rebuilt.close()


def test_browser_plan_confirmation_preserves_user_fixture_source_and_old_history(tmp_path: Path) -> None:
    root = plan_root(tmp_path)
    draft = root.facade.create_plan_draft(CreatePlanDraftCommand("workspace:draft", _content(root)))
    server = LocalChartWorkspaceServer(root.facade, ROOT / "web/dist", "security_yihua", "snapshot_chart")
    base = server.start(); html = urlopen(base).read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    body = json.dumps({"draft_id": draft.draft_id, "expected_revision": 1, "activation_intent": "activate"}).encode()
    headers = {"Origin": base, "Content-Type": "application/json", "X-CSRF-Token": token, "X-Invocation-Id": "browser:confirm-plan"}
    confirmed = json.loads(urlopen(Request(base + "/api/plan-confirmations", data=body, method="POST", headers=headers)).read())
    revised_content = replace(_content(root), based_on_version_id=confirmed["plan_version_id"], rationale="用户补充了新的复核理由。")
    revised_draft = root.facade.create_plan_draft(CreatePlanDraftCommand("workspace:draft:v2", revised_content))
    revised_body = json.dumps({"draft_id": revised_draft.draft_id, "expected_revision": 1, "activation_intent": "activate"}).encode()
    revised_headers = {**headers, "X-Invocation-Id": "browser:confirm-plan:v2"}
    revised = json.loads(urlopen(Request(base + "/api/plan-confirmations", data=revised_body, method="POST", headers=revised_headers)).read())
    workspace = json.loads(urlopen(base + "/api/workspace").read())
    assert confirmed["content"]["user_input_source"] == "user_fixture_input"
    assert revised["content"]["rationale"] == "用户补充了新的复核理由。"
    assert [item["plan_version_id"] for item in workspace["history"]["plans"]] == [confirmed["plan_version_id"], revised["plan_version_id"]]
    assert all(item["status"] == "confirmed" for item in workspace["plan_drafts"])
    server.close(); root.close()


def test_script_shaped_annotation_and_path_inputs_cannot_execute_or_escape(tmp_path: Path) -> None:
    root, server, base = _server(tmp_path)
    html_response = urlopen(base)
    html = html_response.read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    attack = json.dumps({"kind": "<script>alert(1)</script>", "style": "accent", "anchors": [{"market_timestamp": "2026-07-10T15:00:00+08:00", "exact_price_decimal": "82.33"}]}).encode()
    headers = {"Origin": base, "Content-Type": "application/json", "X-CSRF-Token": token, "X-Invocation-Id": "browser:script-attack"}
    with pytest.raises(HTTPError) as rejected:
        urlopen(Request(base + "/api/annotations", data=attack, method="POST", headers=headers))
    assert rejected.value.code == 422
    with pytest.raises(HTTPError) as traversal:
        urlopen(base + "/..%2f..%2fAGENTS.md")
    assert traversal.value.code == 404
    assert "sandbox" in html and "allow-scripts" not in html and "allow-same-origin" not in html
    server.close(); root.close()


def test_secret_and_personal_paths_never_reach_dom_logs_or_artifacts(tmp_path: Path, monkeypatch, capsys) -> None:
    marker = "sk-test-DO-NOT-LEAK-issue09"
    monkeypatch.setenv("OPENAI_API_KEY", marker)
    root, server, base = _server(tmp_path)
    html = urlopen(base).read()
    workspace = urlopen(base + "/api/workspace").read()
    artifact_payloads = b"".join(path.read_bytes() for path in (tmp_path / "objects").rglob("*") if path.is_file())
    output = capsys.readouterr()
    combined = html + workspace + artifact_payloads + output.out.encode() + output.err.encode()
    assert marker.encode() not in combined and str(tmp_path).encode() not in html + workspace
    request = Request(base + "/api/provider-destination", data=json.dumps({"url": "https://evil.example"}).encode(), method="POST", headers={"Origin": base, "Content-Type": "application/json"})
    with pytest.raises(HTTPError) as blocked:
        urlopen(request)
    assert blocked.value.code == 403
    server.close(); root.close()
