from __future__ import annotations

import json
import sqlite3
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from equity_research.scenario_valuation import ScenarioValuationEngine
from equity_research.forecast import ForecastEngine
from trading_platform import ProductionCompositionRoot
from trading_platform.application.contracts import ResumeWorkflowCommand
from trading_platform.domain.workflow import ImmutableArtifactDraft
from trading_platform.persistence import PersistenceError
from tests.platform.test_research_workflow import (
    CountingEngine,
    _request as research_request,
    _root as research_root,
)
from tests.platform.test_workflow_recovery import CrashAt, InjectedCrash, _expire

sys.path.insert(0, str(Path(__file__).parents[1]))
from test_scenario_valuation import (
    biopharma_request,
    cyclical_request,
    financial_request,
    scenario_request,
)


def _drafts(
    *,
    model_identity: str = "company-outlook-model@1",
    policy_identity: str = "company-outlook-policy@1",
) -> tuple[ImmutableArtifactDraft, ...]:
    request = scenario_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    valuation = ScenarioValuationEngine().run(request)
    return (
        ImmutableArtifactDraft.from_data_snapshot(
            request.base_forecast_request.data_snapshot,
            model_identity=model_identity,
            policy_identity=policy_identity,
        ),
        ImmutableArtifactDraft.from_forecast_graph(
            graph,
            model_identity=model_identity,
            policy_identity=policy_identity,
        ),
        ImmutableArtifactDraft.from_scenario_valuation(
            valuation,
            forecast_graph=graph,
            model_identity=model_identity,
            policy_identity=policy_identity,
        ),
    )


def _request(invocation: str, drafts=None):
    return replace(
        research_request(invocation),
        analysis_artifacts=_drafts() if drafts is None else drafts,
    )


def test_legacy_forecast_bytes_remain_inspectable_without_regeneration() -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "legacy_forecast_graph_fg1.json"
    immutable_bytes = fixture_path.read_bytes()

    inspected = json.loads(immutable_bytes.decode("utf-8"))
    replayed_bytes = json.dumps(
        inspected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert inspected["graph_id"] == "fg_9fe1b77610eb130d2e94aa78"
    assert inspected["template_id"] == "financial_institution_valuation_shell@1"
    assert replayed_bytes == immutable_bytes.rstrip(b"\r\n")


def test_cyclical_methods_are_preserved_in_immutable_valuation_artifact() -> None:
    request = cyclical_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    result = ScenarioValuationEngine().run(request)

    draft = ImmutableArtifactDraft.from_scenario_valuation(
        result,
        forecast_graph=graph,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )

    methods = {
        method["method_id"]: method
        for scenario in draft.payload["scenarios"]
        for method in scenario["methods"]
    }
    assert methods["mid_cycle_ev_ebitda"]["status"] == "ready"
    assert methods["resource_nav"]["status"] == "ready"
    assert methods["cyclical_historical_band"]["status"] == "ready"
    assert {
        "cycle_normalized_ev_ebitda@1",
        "finite_resource_nav_after_tax@1",
        "pit_cycle_band_derived_peak@2",
    } <= set(draft.formula_identities)


def test_financial_methods_are_preserved_without_industrial_fallback() -> None:
    request = financial_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    result = ScenarioValuationEngine().run(request)

    draft = ImmutableArtifactDraft.from_scenario_valuation(
        result,
        forecast_graph=graph,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )

    methods = {
        method["method_id"]: method
        for scenario in draft.payload["scenarios"]
        for method in scenario["methods"]
    }
    assert methods["fcff_dcf"]["status"] == "blocked"
    assert methods["justified_pb"]["status"] == "ready"
    assert methods["dividend_discount_model"]["status"] == "ready"
    assert methods["residual_income"]["status"] == "ready"
    assert {
        "justified_pb_roe_coe_act365@3",
        "financial_ddm_clean_surplus_act365@3",
        "residual_income_clean_surplus_act365@3",
    } <= set(draft.formula_identities)


def test_biopharma_event_tree_and_runway_are_preserved_without_fcff() -> None:
    request = biopharma_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    result = ScenarioValuationEngine().run(request)

    draft = ImmutableArtifactDraft.from_scenario_valuation(
        result,
        forecast_graph=graph,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )

    methods = {
        method["method_id"]: method
        for scenario in draft.payload["scenarios"]
        for method in scenario["methods"]
    }
    assert methods["fcff_dcf"]["status"] == "blocked"
    assert methods["pipeline_rnpv"]["status"] == "ready"
    assert methods["pipeline_sotp"]["status"] == "ready"
    assert {
        "pipeline_rnpv_event_tree_act365@1",
        "pipeline_sotp_unique_rights_act365@1",
    } <= set(draft.formula_identities)
    assert any(
        "cash runway" in diagnostic.lower()
        for scenario in draft.payload["scenarios"]
        for method in scenario["methods"]
        if method["method_id"] == "pipeline_rnpv"
        for diagnostic in method["diagnostics"]
    )
    trace = methods["pipeline_rnpv"]["component_trace"]
    model = next(
        item for item in trace if item["kind"] == "biopharma_model_spec"
    )["model_spec"]
    selected = next(
        item
        for item in trace
        if item["kind"] == "biopharma_selected_projection"
    )
    assert model["events"][1]["parent_event_ids"]
    assert model["assets"][0]["economic_right_id"]
    assert model["assets"][0]["periods"][0]["development_cost"]
    assert model["assets"][0]["periods"][0]["milestone_cash"]
    assert model["runway_periods"][2]["financing"]["issue_price"]
    assert selected["asset_cash_flows"]
    assert any(
        item["cash_flow_type"] == "corporate_cash_burn"
        for item in selected["corporate_cash_flows"]
    )
    assert any(
        item["record_id"] == "financing_2028"
        for item in selected["corporate_cash_flows"]
        if item["cash_flow_type"] == "committed_financing"
    )
    assert selected["runway_paths"]
    assert selected["runway_paths"][0]["period_ledger"]
    assert {
        "opening_cash",
        "asset_cash_flow",
        "corporate_cash_burn",
        "committed_financing",
        "ending_cash",
        "minimum_buffer",
        "above_buffer",
    } <= set(selected["runway_paths"][0]["period_ledger"][0])


def test_workflow_persists_restarts_and_reuses_typed_sibling_artifacts(
    tmp_path: Path,
) -> None:
    engine = CountingEngine()
    root = research_root(tmp_path, engine)
    first = root.facade.run_research_workflow(_request("outlook:first"))

    assert len(first.artifact_record_ids) == 3
    views = tuple(
        root.facade.get_research_artifact(record_id)
        for record_id in first.artifact_record_ids
    )
    assert tuple(view.artifact_kind for view in views) == (
        "DataSnapshot",
        "Forecast",
        "Valuation",
    )
    assert all(view.research_run_id == first.research_run_id for view in views)
    assert all(view.data_snapshot_id == first.research_snapshot_id for view in views)
    assert all(
        view.model_data_snapshot_identity == views[0].source_identity
        for view in views
    )
    assert all(view.code_identity and view.policy_identity for view in views)
    assert all(view.formula_identities for view in views)
    assert views[1].dependency_record_ids == (views[0].artifact_record_id,)
    assert views[2].dependency_record_ids == (views[1].artifact_record_id,)
    manifest = root.facade.get_artifact_manifest(first.final_manifest_id)
    assert [member["member_role"] for member in manifest.members] == [
        "research_projection",
        "research_run_json",
        "research_report_html",
        "data_snapshot",
        "forecast",
        "valuation",
    ]
    assert len(
        root._store.connection.execute("PRAGMA table_info(research_run_record)").fetchall()
    ) == 11
    with pytest.raises(sqlite3.IntegrityError, match="RESEARCH_ARTIFACT_IMMUTABLE"):
        root._store.connection.execute(
            "UPDATE research_artifact_record SET status='blocked' WHERE artifact_record_id=?",
            (views[0].artifact_record_id,),
        )
    root._store.connection.rollback()
    root.close()

    rebuilt = ProductionCompositionRoot(tmp_path, research_engine=engine)
    restarted = tuple(
        rebuilt.facade.get_research_artifact(record_id)
        for record_id in first.artifact_record_ids
    )
    replay = rebuilt.facade.run_research_workflow(_request("outlook:replay"))
    assert replay.research_run_id == first.research_run_id
    assert replay.artifact_record_ids == first.artifact_record_ids
    assert tuple(item.content_hash for item in restarted) == tuple(
        item.content_hash for item in views
    )
    assert engine.calls == 1
    rebuilt.close()


def test_model_and_policy_identity_create_parallel_versions_without_rewriting_history(
    tmp_path: Path,
) -> None:
    engine = CountingEngine()
    root = research_root(tmp_path, engine)
    first = root.facade.run_research_workflow(_request("outlook:v1"))
    old_payloads = {
        record_id: root.facade.get_research_artifact(record_id).payload
        for record_id in first.artifact_record_ids
    }
    second = root.facade.run_research_workflow(
        _request("outlook:v2", _drafts(model_identity="company-outlook-model@2"))
    )
    third = root.facade.run_research_workflow(
        _request(
            "outlook:policy-v2",
            _drafts(
                model_identity="company-outlook-model@2",
                policy_identity="company-outlook-policy@2",
            ),
        )
    )

    assert second.research_run_id == first.research_run_id
    assert second.artifact_record_ids != first.artifact_record_ids
    assert third.research_run_id == first.research_run_id
    assert third.artifact_record_ids != second.artifact_record_ids
    assert root._store.connection.execute(
        "SELECT count(*) FROM research_artifact_record"
    ).fetchone()[0] == 9
    assert {
        record_id: root.facade.get_research_artifact(record_id).payload
        for record_id in first.artifact_record_ids
    } == old_payloads
    root.close()


@pytest.mark.parametrize(
    "boundary,records_before_resume",
    [
        ("research_artifact.before_commit", 0),
        ("workflow.research_artifacts_persisted", 3),
    ],
)
def test_artifact_bundle_crash_recovery_has_no_partial_typed_commit(
    tmp_path: Path,
    boundary: str,
    records_before_resume: int,
) -> None:
    engine = CountingEngine()
    injector = CrashAt(boundary)
    root = research_root(tmp_path, engine)
    root._workflow_repository.fault_injector = injector
    root._workflow_repository.objects.fault_injector = injector
    root._research_workflow.fault_injector = injector
    with pytest.raises(InjectedCrash):
        root.facade.run_research_workflow(_request("outlook:crash"))
    run_id = root._store.connection.execute(
        "SELECT workflow_run_id FROM workflow_run WHERE invocation_id='outlook:crash'"
    ).fetchone()[0]
    assert root._store.connection.execute(
        "SELECT count(*) FROM research_artifact_record"
    ).fetchone()[0] == records_before_resume

    root._workflow_repository.fault_injector = None
    root._workflow_repository.objects.fault_injector = None
    root._research_workflow.fault_injector = None
    _expire(root, run_id)
    resumed = root.facade.resume_workflow(ResumeWorkflowCommand(run_id, "resume-owner"))
    assert len(resumed.artifact_record_ids) == 3
    assert root._store.connection.execute(
        "SELECT count(*) FROM research_artifact_record"
    ).fetchone()[0] == 3
    assert engine.calls == 1
    root.close()


def test_corrupt_artifact_fails_closed_and_concurrent_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    root = research_root(tmp_path, CountingEngine())
    result = root.facade.run_research_workflow(_request("outlook:integrity"))
    drafts = _drafts()
    outputs: list[tuple[str, ...]] = []

    source_request = scenario_request()
    source_graph = ForecastEngine().build(source_request.base_forecast_request)
    unrelated_graph = replace(
        source_graph,
        graph_id="graph_unrelated_same_snapshot",
        template_id="unrelated-template@999",
    )
    with pytest.raises(ValueError, match="RESEARCH_ARTIFACT_VALUATION_LINEAGE_INVALID"):
        ImmutableArtifactDraft.from_scenario_valuation(
            ScenarioValuationEngine().run(source_request),
            forecast_graph=unrelated_graph,
            model_identity="company-outlook-model@1",
            policy_identity="company-outlook-policy@1",
        )
    foreign_graph = replace(source_graph, security_id="OTHER.SECURITY")
    foreign_drafts = (
        drafts[0],
        ImmutableArtifactDraft.from_forecast_graph(
            foreign_graph,
            model_identity="company-outlook-model@1",
            policy_identity="company-outlook-policy@1",
        ),
    )
    with pytest.raises(ValueError, match="RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH"):
        root._workflow_repository.persist_research_artifact_bundle(
            research_run_id=result.research_run_id,
            data_snapshot_id=result.research_snapshot_id,
            code_identity=root._workflow_repository.connection.execute(
                "SELECT engine_code_identity FROM research_run_record WHERE research_run_id=?",
                (result.research_run_id,),
            ).fetchone()[0],
            drafts=foreign_drafts,
        )

    def replay() -> None:
        outputs.append(
            root._workflow_repository.persist_research_artifact_bundle(
                research_run_id=result.research_run_id,
                data_snapshot_id=result.research_snapshot_id,
                code_identity=root._workflow_repository.connection.execute(
                    "SELECT engine_code_identity FROM research_run_record WHERE research_run_id=?",
                    (result.research_run_id,),
                ).fetchone()[0],
                drafts=drafts,
            )
        )

    threads = [threading.Thread(target=replay) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert outputs == [result.artifact_record_ids, result.artifact_record_ids]
    assert root._store.connection.execute(
        "SELECT count(*) FROM research_artifact_record"
    ).fetchone()[0] == 3

    view = root.facade.get_research_artifact(result.artifact_record_ids[1])
    row = root._store.connection.execute(
        "SELECT o.relative_path FROM research_artifact_record r "
        "JOIN artifact a USING(artifact_id) JOIN object_blob o ON o.sha256=a.object_sha256 "
        "WHERE r.artifact_record_id=?",
        (view.artifact_record_id,),
    ).fetchone()
    (tmp_path / row[0]).write_bytes(b"corrupt")
    with pytest.raises(PersistenceError) as integrity:
        root.facade.get_research_artifact(view.artifact_record_id)
    assert integrity.value.code == "OBJECT_INTEGRITY_FAILED"
    doctor = root.facade.doctor()
    assert doctor.status == "failed"
    assert "OBJECT_INTEGRITY_FAILED" in doctor.errors
    root.close()
