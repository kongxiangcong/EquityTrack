from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from equity_research import ResearchEngine
from trading_platform import ProductionCompositionRoot
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.domain.workflow import FieldSemantics, ReferenceDisposition, ResearchProjection, ResearchWorkflowRequest
from trading_platform.workflows.research import WorkflowError
from trading_platform.workflows.registry import RESEARCH_WORKFLOW
from trading_platform.research import SnapshotToResearchRequestAssembler


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "yihua-002897"


class CountingEngine:
    def __init__(self, failure: str | None = None) -> None:
        self.calls = 0
        self._failure = failure
        self._delegate = ResearchEngine()

    def run(self, request):
        self.calls += 1
        if self._failure:
            raise RuntimeError(self._failure)
        return self._delegate.run(request)


def _load(name: str):
    return json.loads((EXAMPLE / name).read_text(encoding="utf-8"))


def _projection(context=None) -> ResearchProjection:
    manifest = _load("source_manifest.json")
    semantics = []
    for source in manifest["sources"]:
        for field in source["extracted_fields"]:
            semantics.append(FieldSemantics(
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
                available_at=source["retrieved_at"],
                retrieved_at=source["retrieved_at"],
                supersedes_identity=source.get("supersedes_identity"),
                availability_basis="publisher_timestamp" if source.get("available_at") else "conservative_retrieval_time",
            ))
    return ResearchProjection(
        manifest=manifest,
        estimates=_load("estimate_overlay.json"),
        context=_load("research_context.json") if context is None else context,
        as_of_date="2026-07-07",
        profile="L2",
        field_semantics=tuple(semantics),
        diluted_share_identity="SRC_CNINFO_2026Q1:diluted_shares:2026Q1",
        net_debt_bridge_identity="SRC_CNINFO_2026Q1:cash+debt:2026Q1",
    )


def _request(invocation: str, projection: ResearchProjection | None = None, **changes) -> ResearchWorkflowRequest:
    values = dict(
        invocation_id=invocation,
        security_id="security_yihua",
        requested_date="2026-07-07",
        effective_session_date="2026-07-07",
        projection=projection or _projection(),
    )
    values.update(changes)
    return ResearchWorkflowRequest(**values)


def _artifact_bytes(root: ProductionCompositionRoot, artifact_id: str) -> bytes:
    sha = root._store.connection.execute("SELECT object_sha256 FROM artifact WHERE artifact_id=?", (artifact_id,)).fetchone()[0]
    relative = root._store.connection.execute("SELECT relative_path FROM object_blob WHERE sha256=?", (sha,)).fetchone()[0]
    return (root._store.objects.data_root / relative).read_bytes()


def _root(tmp_path: Path, engine: CountingEngine) -> ProductionCompositionRoot:
    root = ProductionCompositionRoot(tmp_path, research_engine=engine)
    root.facade.add_watchlist_item("watch:security_yihua", SecurityIdentity("security_yihua", "SZSE", "002897", "CNY", "2017-09-07"))
    return root


def test_public_workflow_creates_canonical_research_artifacts_and_replays_invocation(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    result = root.facade.run_research_workflow(_request("research:one"))
    replay = root.facade.run_research_workflow(_request("research:one"))

    assert replay == result
    assert result.disposition is ReferenceDisposition.CREATED
    assert engine.calls == 1
    payload = json.loads(_artifact_bytes(root, result.json_artifact_id))
    direct = ResearchEngine().run(SnapshotToResearchRequestAssembler().assemble(_projection())).to_dict()
    assert payload == direct
    assert payload["schema_version"] == direct["schema_version"]
    assert payload["capabilities"] == direct["capabilities"]
    assert payload["permissions"] == direct["permissions"]
    assert payload["run_id"] == result.research_run_id
    assert payload["as_of_date"] == "2026-07-07"
    assert _artifact_bytes(root, result.html_artifact_id).lower().startswith(b"<!doctype html>")
    history = root.facade.get_workflow_history(result.workflow_run_id)
    assert history.status in {"succeeded", "succeeded_with_limits"}
    assert [item["node_id"] for item in history.attempts] == ["freeze_research_projection", "run_or_link_research", "publish_run_manifest"]
    assert {item["ref_role"] for item in history.refs} >= {"research_snapshot", "research_projection", "research_run", "research_json", "research_html", "final_manifest"}
    assert history.reuse_decision["reason_code"] == "RESEARCH_INPUT_CHANGED_OR_NEW"
    assert tuple(root._store.connection.execute("SELECT quality_status,coverage_expected,coverage_eligible,coverage_excluded,coverage_missing FROM data_snapshot WHERE data_snapshot_id=?", (result.research_snapshot_id,)).fetchone()) == ("warning", 1, 1, 0, 0)
    manifest = root.facade.get_artifact_manifest(history.final_manifest_id)
    assert manifest.producer_id == result.workflow_run_id
    assert [(item["member_role"], item["direction"]) for item in manifest.members] == [
        ("research_projection", "input"),
        ("research_run_json", "output"),
        ("research_report_html", "output"),
    ]
    root.close()


def test_new_invocation_reuses_immutable_research_and_market_only_snapshot(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    first = root.facade.run_research_workflow(_request("research:first"))
    connection = root._store.connection
    with connection:
        connection.execute("INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "snapshot_market_20260710", "security_yihua", "workflow", "2026-07-11", "2026-07-10", "2026-07-11T00:00:00+00:00", "Asia/Shanghai", "cn-calendar@2026", "query@1", "source@1", "freshness@1", "market-members", "valid", "pass", 0, 0, 0, 0, 0, "test workflow snapshot", "2026-07-11T00:00:00+00:00",
        ))
        connection.execute("INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("attempt_market", "market-refresh", "fixture", "fixture@1", "daily", "derived-fixture", "fixture", "urn:test:daily", "{}", "{}", "date", "test-terms", "complete", "created", None, "2026-07-10T09:00:00+00:00", None, None, None, "not_applicable"))
        connection.execute("INSERT INTO normalized_record VALUES(?,?,?)", ("record_market", "daily", "security_yihua:2026-07-10"))
        connection.execute("INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ("daily:2026-07-10", "record_market", 1, "market-content", "attempt_market", "2026-07-10", "2026-07-10", "date", "2026-07-10T09:00:00+00:00", "publisher_timestamp", "2026-07-10T09:00:00+00:00", "pass", None))
        connection.execute("INSERT INTO data_snapshot_member VALUES(?,?,?,?)", ("snapshot_market_20260710", "daily:2026-07-10", "daily", 0))
    second = root.facade.run_research_workflow(_request(
        "research:market-refresh",
        requested_date="2026-07-11",
        effective_session_date="2026-07-10",
        workflow_snapshot_id="snapshot_market_20260710",
        candidate_member_ids=("daily:2026-07-10",),
        market_only_member_ids=("daily:2026-07-10",),
    ))

    assert engine.calls == 1
    assert second.workflow_run_id != first.workflow_run_id
    assert second.research_run_id == first.research_run_id
    assert second.research_snapshot_id == first.research_snapshot_id
    assert (second.json_artifact_id, second.html_artifact_id) == (first.json_artifact_id, first.html_artifact_id)
    assert second.workflow_snapshot_id == "snapshot_market_20260710"
    assert second.disposition is ReferenceDisposition.REUSED
    assert second.reason_code == "ROUTINE_MARKET_ONLY_INPUTS"
    assert second.stale_by_days == 3
    root.close()


def test_changed_research_input_creates_new_run_and_old_artifacts_remain_readable(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    first = root.facade.run_research_workflow(_request("research:first"))
    old_json = _artifact_bytes(root, first.json_artifact_id)
    context = _load("research_context.json")
    context["workflow_test_marker"] = "changed research input"
    second = root.facade.run_research_workflow(_request("research:changed", _projection(context)))

    assert engine.calls == 2
    assert second.research_run_id != first.research_run_id
    assert second.research_snapshot_id != first.research_snapshot_id
    assert _artifact_bytes(root, first.json_artifact_id) == old_json
    root.close()


def test_typed_research_relevant_snapshot_member_requires_and_accepts_updated_projection(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    first = root.facade.run_research_workflow(_request("research:before-disclosure"))
    connection = root._store.connection
    with connection:
        connection.execute("INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("attempt_filing", "filing-refresh", "official", "official@1", "financial_statement", "CNINFO", "official", "urn:test:filing", "{}", "{}", "timestamp", "official-terms", "complete", "created", None, "2026-07-10T09:00:00+00:00", None, None, None, "not_applicable"))
        connection.execute("INSERT INTO normalized_record VALUES(?,?,?)", ("record_filing", "financial_statement", "security_yihua:2026Q2"))
        connection.execute("INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ("filing:2026Q2", "record_filing", 1, "filing-content", "attempt_filing", "2026-06-30", "2026-07-10T08:00:00+00:00", "timestamp", "2026-07-10T08:00:00+00:00", "publisher_timestamp", "2026-07-10T09:00:00+00:00", "pass", None))
        connection.execute("INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("snapshot_filing", "security_yihua", "workflow", "2026-07-11", "2026-07-10", "2026-07-11T00:00:00+00:00", "Asia/Shanghai", "cn-calendar@2026", "query@1", "source@1", "freshness@1", "filing-members", "valid", "pass", 1, 1, 0, 0, 0, "official filing candidate", "2026-07-11T00:00:00+00:00"))
        connection.execute("INSERT INTO data_snapshot_member VALUES(?,?,?,?)", ("snapshot_filing", "filing:2026Q2", "financial_statement", 0))
    context = _load("research_context.json"); context["workflow_research_member_ids"] = ["filing:2026Q2"]
    changed = root.facade.run_research_workflow(_request("research:after-disclosure", _projection(context), requested_date="2026-07-11", effective_session_date="2026-07-10", workflow_snapshot_id="snapshot_filing", candidate_member_ids=("filing:2026Q2",)))
    assert engine.calls == 2 and changed.research_run_id != first.research_run_id
    assert changed.research_snapshot_id != first.research_snapshot_id
    root.close()


@pytest.mark.parametrize("mutation", ["unit", "currency", "scale", "period", "scope", "restatement", "authority", "future", "bridge", "wrong_bridge", "wrong_diluted"])
def test_projection_semantics_and_cutoff_fail_closed(tmp_path: Path, mutation: str) -> None:
    projection = _projection()
    if mutation == "unit":
        projection = replace(projection, field_semantics=(replace(projection.field_semantics[0], unit="wrong"), *projection.field_semantics[1:]))
    elif mutation in {"currency", "scale", "period", "scope", "restatement"}:
        field_name = {"scope": "statement_scope", "restatement": "restatement_status"}.get(mutation, mutation)
        projection = replace(projection, field_semantics=(replace(projection.field_semantics[0], **{field_name: "wrong"}), *projection.field_semantics[1:]))
    elif mutation == "authority":
        projection = replace(projection, field_semantics=(replace(projection.field_semantics[0], source_authority="secondary"), *projection.field_semantics[1:]))
    elif mutation == "future":
        manifest = json.loads(json.dumps(projection.manifest)); manifest["sources"][0]["retrieved_at"] = "2026-07-08T00:00:00+08:00"
        projection = replace(projection, manifest=manifest)
    elif mutation == "bridge":
        projection = replace(projection, net_debt_bridge_identity="")
    elif mutation == "wrong_bridge":
        projection = replace(projection, net_debt_bridge_identity="SRC_CNINFO_2026Q1:cash+debt:2025A")
    else:
        projection = replace(projection, diluted_share_identity="SRC_CNINFO_2026Q1:diluted_shares:2025A")
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    with pytest.raises(WorkflowError) as caught:
        root.facade.run_research_workflow(_request(f"invalid:{mutation}", projection))
    assert engine.calls == 0
    history = root._store.connection.execute("SELECT status FROM workflow_run WHERE workflow_run_id=?", (caught.value.workflow_run_id,)).fetchone()
    diagnostic = root._store.connection.execute("SELECT diagnostic_artifact_id FROM workflow_node_attempt WHERE disposition='failed'").fetchone()
    assert history[0] == "failed" and diagnostic[0]
    assert root._store.connection.execute("SELECT count(*) FROM research_run_record").fetchone()[0] == 0
    root.close()


def test_engine_failure_publishes_diagnostic_not_empty_research_run(tmp_path: Path) -> None:
    engine = CountingEngine("expected engine failure")
    root = _root(tmp_path, engine)
    with pytest.raises(WorkflowError) as caught:
        root.facade.run_research_workflow(_request("research:failure"))
    connection = root._store.connection
    assert connection.execute("SELECT status FROM workflow_run WHERE workflow_run_id=?", (caught.value.workflow_run_id,)).fetchone()[0] == "failed"
    assert connection.execute("SELECT count(*) FROM research_run_record").fetchone()[0] == 0
    attempt = connection.execute("SELECT error_code,diagnostic_artifact_id FROM workflow_node_attempt WHERE disposition='failed'").fetchone()
    assert attempt[0] == "RESEARCH_ENGINE_FAILED" and b"RESEARCH_ENGINE_FAILED" in _artifact_bytes(root, attempt[1])
    root.close()


def test_registry_contracts_are_versioned_and_diagnostics_are_redacted(tmp_path: Path) -> None:
    assert all(node.preconditions and node.required and node.cache_policy and node.retry_policy and node.failure_codes for node in RESEARCH_WORKFLOW.nodes)
    engine = CountingEngine("token=super-secret C:\\Users\\person\\private.txt https://private.example/path")
    root = _root(tmp_path, engine)
    with pytest.raises(WorkflowError):
        root.facade.run_research_workflow(_request("research:redaction"))
    artifact_id = root._store.connection.execute("SELECT diagnostic_artifact_id FROM workflow_node_attempt WHERE disposition='failed'").fetchone()[0]
    diagnostic = _artifact_bytes(root, artifact_id)
    assert b"super-secret" not in diagnostic and b"private.example" not in diagnostic and b"Users" not in diagnostic
    assert b"RESEARCH_ENGINE_FAILED" in diagnostic
    root.close()
