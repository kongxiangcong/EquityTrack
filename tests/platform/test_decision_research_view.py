from __future__ import annotations

from trading_platform.application.contracts import StartResearchWorkflow


import json
import re
import inspect
from pathlib import Path

import pytest

from tests.platform.test_outlook_artifacts import (
    _drafts,
    _request,
)
from tests.platform.test_research_workflow import (
    CountingEngine,
    _artifact_bytes,
    _root,
)
from tests.platform.research_cutover_fixture import LegacyResearchCutoverFixture
from trading_platform.research_presentation import render_research_decision_html
from trading_platform.research_view import (
    ResearchDecisionInput,
    ResearchDecisionView,
    ResearchDecisionViewBuilder,
    ResearchViewError,
)
from trading_platform.application.contracts import (
    CancelWorkflowCommand,
    ResumeWorkflowCommand,
)
from trading_platform.workflows.research import WorkflowError
from trading_platform.operations import PlatformOperations
from trading_platform.application.research_view_cutover import (
    CanonicalResearchDecisionViewMaterializer,
)
from trading_platform.persistence.locking import PersistenceError


def test_decision_view_builder_has_one_typed_input() -> None:
    parameters = tuple(
        inspect.signature(ResearchDecisionViewBuilder.build).parameters
    )

    assert parameters == ("self", "decision_input")
    assert ResearchDecisionInput.__dataclass_fields__


def test_incomplete_populated_root_rejects_workflow_and_workspace(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    first = root.research.handle(StartResearchWorkflow(_request("cutover:baseline")))
    LegacyResearchCutoverFixture(root.faults.legacy_store).remove_decision_reference(
        first.workflow_run_id
    )

    with pytest.raises(WorkflowError) as workflow_error:
        root.research.handle(StartResearchWorkflow(_request("cutover:blocked")))
    assert workflow_error.value.code == "RESEARCH_VIEW_CUTOVER_INCOMPLETE"
    with pytest.raises(WorkflowError) as resume_error:
        root.research.handle(
            ResumeWorkflowCommand(first.workflow_run_id, "blocked-owner")
        )
    assert resume_error.value.code == "RESEARCH_VIEW_CUTOVER_INCOMPLETE"
    with pytest.raises(WorkflowError) as cancel_error:
        root.research.handle(
            CancelWorkflowCommand(first.workflow_run_id, "blocked")
        )
    assert cancel_error.value.code == "RESEARCH_VIEW_CUTOVER_INCOMPLETE"
    with pytest.raises(ResearchViewError, match="RESEARCH_VIEW_CUTOVER_INCOMPLETE"):
        root.workspace.build("security_yihua", first.research_snapshot_id)
    root.close()

    migrated = PlatformOperations(tmp_path).migrate()
    assert migrated["status"] == "passed"
    rebuilt = _root(tmp_path, CountingEngine())
    workspace = rebuilt.workspace.build(
        "security_yihua", first.research_snapshot_id
    )
    assert workspace["research_views"][0]["view_id"] == json.loads(
        _artifact_bytes(rebuilt, first.json_artifact_id)
    )["view_id"]
    assert rebuilt.inspection.inspect(
        first.workflow_run_id
    ).final_manifest_id == first.final_manifest_id
    rebuilt.close()


def test_cutover_materializes_missing_view_identity_stably(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:materialize")))
    original_json = _artifact_bytes(root, result.json_artifact_id)
    manifest_id = LegacyResearchCutoverFixture(root.faults.legacy_store).remove_decision_manifest(
        result.workflow_run_id
    )
    root.close()

    PlatformOperations(tmp_path).migrate()
    rebuilt = _root(tmp_path, CountingEngine())
    history = rebuilt.inspection.inspect(result.workflow_run_id)
    assert history.final_manifest_id == manifest_id
    materialized = rebuilt.archive.manifest(manifest_id)
    assert [item["member_role"] for item in materialized.members] == [
        "decision_view_json",
        "decision_view_html",
    ]
    assert _artifact_bytes(rebuilt, result.json_artifact_id) == original_json
    rebuilt.close()


def test_cutover_rejects_multiple_exact_source_candidates_atomically(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:source-ambiguous")))
    legacy = LegacyResearchCutoverFixture(root.faults.legacy_store)
    legacy.add_duplicate_source_json(result.research_run_id)
    legacy.remove_decision_reference(result.workflow_run_id)
    original_pointer = legacy.source_json_artifact_id(result.research_run_id)
    root.close()

    with pytest.raises(PersistenceError) as caught:
        PlatformOperations(tmp_path).migrate()
    assert caught.value.code == "RESEARCH_SOURCE_ARTIFACT_NOT_UNIQUE"
    rebuilt = _root(tmp_path, CountingEngine())
    rebuilt_legacy = LegacyResearchCutoverFixture(rebuilt.faults.legacy_store)
    assert rebuilt_legacy.source_json_artifact_id(result.research_run_id) == original_pointer
    assert rebuilt_legacy.decision_ref_count(result.workflow_run_id) == 0
    rebuilt.close()


def test_cutover_rejects_missing_exact_source_candidate_atomically(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:source-missing")))
    legacy = LegacyResearchCutoverFixture(root.faults.legacy_store)
    source_artifact_id = legacy.hide_exact_source_json(result.research_run_id)
    legacy.remove_decision_reference(result.workflow_run_id)
    root.close()

    with pytest.raises(PersistenceError) as caught:
        PlatformOperations(tmp_path).migrate()
    assert caught.value.code == "RESEARCH_SOURCE_ARTIFACT_NOT_UNIQUE"
    rebuilt = _root(tmp_path, CountingEngine())
    rebuilt_legacy = LegacyResearchCutoverFixture(rebuilt.faults.legacy_store)
    assert rebuilt_legacy.source_json_artifact_id(result.research_run_id) == source_artifact_id
    assert rebuilt_legacy.decision_ref_count(result.workflow_run_id) == 0
    rebuilt.close()


def test_cutover_ignores_source_html_with_nonexact_run_identity(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:html-exact")))
    legacy = LegacyResearchCutoverFixture(root.faults.legacy_store)
    legacy.add_misleading_source_html(
        result.workflow_run_id, result.research_run_id
    )
    root.close()

    assert PlatformOperations(tmp_path).migrate()["status"] == "passed"
    rebuilt = _root(tmp_path, CountingEngine())
    assert rebuilt.inspection.inspect(
        result.workflow_run_id
    ).final_manifest_id == result.final_manifest_id
    rebuilt.close()


def test_cutover_ignores_source_html_with_nonexact_engine_schema(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:schema-exact")))
    LegacyResearchCutoverFixture(root.faults.legacy_store).add_misleading_source_schema(
        result.workflow_run_id, result.research_run_id
    )
    root.close()

    assert PlatformOperations(tmp_path).migrate()["status"] == "passed"
    rebuilt = _root(tmp_path, CountingEngine())
    assert rebuilt.inspection.inspect(
        result.workflow_run_id
    ).final_manifest_id == result.final_manifest_id
    rebuilt.close()


def test_conflicting_decision_ref_rolls_back_source_pointer_repair(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:conflicting-ref")))
    legacy = LegacyResearchCutoverFixture(root.faults.legacy_store)
    wrong_pointer = legacy.prepare_conflicting_decision_reference(
        result.workflow_run_id,
        result.research_run_id,
        result.json_artifact_id,
    )

    with pytest.raises(PersistenceError) as caught:
        root.faults.workflow_ledger.cutover_research_decision_views(
            CanonicalResearchDecisionViewMaterializer()
        )
    assert caught.value.code == "RESEARCH_VIEW_CUTOVER_INCOMPLETE"
    assert legacy.source_json_artifact_id(result.research_run_id) == wrong_pointer
    assert legacy.decision_ref_count(result.workflow_run_id) == 2
    root.close()


def test_noncanonical_decision_manifest_fails_completeness_gate(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:manifest-corrupt")))
    LegacyResearchCutoverFixture(root.faults.legacy_store).corrupt_decision_manifest_identity(
        result.workflow_run_id
    )
    with pytest.raises(WorkflowError) as blocked:
        root.research.handle(StartResearchWorkflow(_request("cutover:manifest-blocked")))
    assert blocked.value.code == "RESEARCH_VIEW_CUTOVER_INCOMPLETE"
    root.close()


def test_cutover_commit_fault_rolls_back_and_retry_reuses_exact_identity(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:commit-fault")))
    legacy = LegacyResearchCutoverFixture(root.faults.legacy_store)
    legacy.remove_decision_reference(result.workflow_run_id)

    def fail_before_commit(boundary: str) -> None:
        if boundary == "research_view_cutover.before_commit":
            raise RuntimeError("injected cutover commit fault")

    ledger = root.faults.workflow_ledger
    ledger.fault_injector = fail_before_commit
    with pytest.raises(RuntimeError, match="injected cutover commit fault"):
        ledger.cutover_research_decision_views(
            CanonicalResearchDecisionViewMaterializer()
        )
    assert legacy.decision_ref_count(result.workflow_run_id) == 0

    ledger.fault_injector = None
    ledger.cutover_research_decision_views(
        CanonicalResearchDecisionViewMaterializer()
    )
    restored = legacy.decision_ref_id(result.workflow_run_id)
    assert restored == result.final_manifest_id
    assert _artifact_bytes(root, result.json_artifact_id)
    root.close()


def test_cutover_object_fault_leaves_only_orphan_and_retry_is_identity_stable(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:object-fault")))
    legacy = LegacyResearchCutoverFixture(root.faults.legacy_store)
    legacy.remove_decision_graph(result.workflow_run_id)

    def fail_after_rename(boundary: str) -> None:
        if boundary == "object.renamed":
            raise RuntimeError("injected cutover object fault")

    ledger = root.faults.workflow_ledger
    ledger.fault_injector = fail_after_rename
    with pytest.raises(RuntimeError, match="injected cutover object fault"):
        ledger.cutover_research_decision_views(
            CanonicalResearchDecisionViewMaterializer()
        )
    assert legacy.decision_ref_count(result.workflow_run_id) == 0

    ledger.fault_injector = None
    ledger.cutover_research_decision_views(
        CanonicalResearchDecisionViewMaterializer()
    )
    restored = root.inspection.inspect(result.workflow_run_id)
    restored_manifest = root.archive.manifest(restored.final_manifest_id)
    restored_ids = tuple(item["artifact_id"] for item in restored_manifest.members)
    ledger.cutover_research_decision_views(
        CanonicalResearchDecisionViewMaterializer()
    )
    replayed = root.archive.manifest(restored.final_manifest_id)
    assert tuple(item["artifact_id"] for item in replayed.members) == restored_ids
    restored_json = json.loads(_artifact_bytes(root, restored_ids[0]))
    assert restored_json["workflow_run_id"] == result.workflow_run_id
    assert restored_json["research_run_id"] == result.research_run_id
    root.close()


def test_cutover_preserves_shared_source_and_creates_workflow_scoped_views(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    first = root.research.handle(StartResearchWorkflow(_request("cutover:shared:first")))
    second = root.research.handle(StartResearchWorkflow(_request("cutover:shared:second")))
    assert second.research_run_id == first.research_run_id
    assert second.workflow_run_id != first.workflow_run_id
    LegacyResearchCutoverFixture(root.faults.legacy_store).remove_decision_references(
        (first.workflow_run_id, second.workflow_run_id)
    )
    root.close()

    PlatformOperations(tmp_path).migrate()
    rebuilt = _root(tmp_path, CountingEngine())
    first_history = rebuilt.inspection.inspect(first.workflow_run_id)
    second_history = rebuilt.inspection.inspect(second.workflow_run_id)
    assert first_history.final_manifest_id != second_history.final_manifest_id
    first_view = json.loads(_artifact_bytes(rebuilt, first.json_artifact_id))
    second_view = json.loads(_artifact_bytes(rebuilt, second.json_artifact_id))
    assert first_view["research_run_id"] == second_view["research_run_id"]
    assert first_view["workflow_run_id"] != second_view["workflow_run_id"]
    source_ids = LegacyResearchCutoverFixture(rebuilt.faults.legacy_store).source_artifact_ids(
        first.research_run_id
    )
    assert all(source_ids)
    rebuilt.close()


def test_completed_v1_workflow_is_inspection_only(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("cutover:legacy-v1")))
    LegacyResearchCutoverFixture(root.faults.legacy_store).mark_completed_workflow_v1(
        result.workflow_run_id
    )

    history = root.inspection.inspect(result.workflow_run_id)
    assert history.status in {"succeeded", "succeeded_with_limits"}
    with pytest.raises(WorkflowError) as blocked:
        root.research.handle(
            ResumeWorkflowCommand(result.workflow_run_id, "legacy-owner")
        )
    assert blocked.value.code == "WORKFLOW_DEFINITION_MISMATCH"
    assert root.inspection.inspect(result.workflow_run_id) == history
    root.close()


def test_workspace_builds_decision_first_view_from_typed_artifacts_not_html(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("decision-view:v1")))

    source_html = LegacyResearchCutoverFixture(root.faults.legacy_store).source_html_path(
        result.research_run_id
    ).read_bytes()

    workspace = root.workspace.build(
        "security_yihua",
        result.research_snapshot_id,
    )
    assert len(workspace["research_views"]) == 1
    view = workspace["research_views"][0]
    assert view["html_projection"].encode() != source_html
    assert result.workflow_run_id in view["html_projection"]
    assert view["schema_version"] == "ResearchDecisionView@2"
    assert view["subject_id"] == "002897.SZ"
    assert {
        "core_thesis",
        "variant_view",
        "valuation_view",
        "valuation_guardrails",
        "what_happens",
        "why_it_matters",
        "transmission",
        "counterevidence",
        "what_would_change_the_view",
    } <= set(view["story"])
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
        assert ready and all(method["conditional_per_share_range"] is None for method in ready)
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
    result = root.research.handle(StartResearchWorkflow(_request("decision-view:canonical-presentation")))

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
    source_payload = root.archive.source_payload(result.research_run_id)
    assert source_payload["schema_version"] == 3
    assert source_payload["run_id"] == result.research_run_id
    history = root.inspection.inspect(result.workflow_run_id)
    decision_refs = [
        item for item in history.refs
        if item["ref_role"] == "decision_view_manifest"
    ]
    assert len(decision_refs) == 1
    manifest = root.archive.manifest(decision_refs[0]["ref_id"])
    assert manifest.manifest_role == "workflow_decision_view@1"
    assert [item["member_role"] for item in manifest.members] == [
        "decision_view_json",
        "decision_view_html",
    ]
    assert embedded is not None
    assert json.loads(embedded.group(1)) == payload
    assert "未来故事" in html
    assert payload["story"]["what_happens"] in html
    assert html.index("未来会发生什么") < html.index(
        "补充公司叙事与估值上下文"
    )
    assert '<details class="story-details">' in html
    assert '<details class="story-details" open>' not in html
    assert "当前价格隐含预期" in html
    assert payload["market_implied_expectations"][0]["explanation"] in html
    assert "情景 Driver" in html
    assert "关键财务结果" in html
    assert payload["scenarios"][0]["drivers"][0]["metric_id"] in html
    assert payload["scenarios"][0]["financials"][0]["metric_id"] in html
    assert "条件低值" in html and "条件高值" in html
    assert "审计附录" in html
    assert '<details class="audit-appendix">' in html
    assert '<details class="audit-appendix" open>' not in html
    assert "<summary><span>审计附录</span>" in html
    assert "事实与证据" in html
    assert "公式身份" in html
    assert "模型参数" in html
    assert "来源注册" in html
    assert "版本与权限" in html
    assert "诊断与缺口" in html
    assert payload["audit"]["fact_evidence"][0]["fact_id"] in html
    assert payload["audit"]["formula_identities"][0] in html
    assert ".audit-appendix summary:focus-visible" in html
    assert "@media(prefers-reduced-motion:reduce)" in html
    assert "ResearchReportHtml@1" not in html
    root.close()


def test_formal_html_renders_optional_value_and_market_distributions() -> None:
    html = render_research_decision_html(
        ResearchDecisionView.from_dict({
            "schema_version": "ResearchDecisionView@2",
            "view_id": "research_view_test",
            "workflow_run_id": "workflow_test",
            "research_run_id": "research_test",
            "data_snapshot_id": "snapshot_test",
            "model_data_snapshot_identity": "model_snapshot_test",
            "valuation_artifact_record_id": "valuation_test",
            "simulation_artifact_record_id": "simulation_test",
            "market_path_artifact_record_id": "market_path_test",
            "subject_id": "002407.SZ",
            "as_of": "2026-07-17",
            "model_identity": "model@1",
            "policy_identity": "policy@1",
            "status": "limited",
            "story": {},
            "key_drivers": (),
            "scenarios": (),
            "market_implied_expectations": (),
            "valuation_simulation": {
                "output_level": "basis_value",
                "converged": True,
                "quantiles": {
                    "p50": {"value": "12500000000", "unit": "CNY"},
                },
                "contributions": (
                    {"assumption_id": "mid_cycle_margin", "share": "0.61"},
                ),
                "diagnostics": ("enterprise bridge remains limited",),
            },
            "market_price_paths": {
                "interpretation": "状态条件下的市场交易价格路径。",
                "terminal_price_quantiles": {
                    "p50": {"value": "11.8", "unit": "CNY/share"},
                },
                "horizon_return_quantiles": {
                    "p50": {"value": "-0.02", "unit": "decimal"},
                },
                "maximum_drawdown_quantiles": {
                    "p50": {"value": "-0.15", "unit": "decimal"},
                },
                "diagnostics": (),
            },
            "value_market_divergence": {
                "explanation": "两类分布来自不同机制，不形成交易动作。",
            },
            "audit": {"artifact_records": ()},
            "boundary": "条件研究结果，不构成个性化投资建议。",
        })
    )

    assert "校准后的企业价值分布" in html
    assert "关键变量贡献" in html
    assert "状态条件下的市场价格与回撤分布" in html
    assert "两类分布来自不同机制，不形成交易动作。" in html
    assert "目标价" not in html


def test_workspace_exposes_parallel_historical_view_versions(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    first = root.research.handle(StartResearchWorkflow(_request("decision-view:model-v1")))
    second = root.research.handle(StartResearchWorkflow(_request(
            "decision-view:model-v2",
            _drafts(model_identity="company-outlook-model@2"),
        )))
    workspace = root.workspace.build(
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
