from trading_platform.application.contracts import StartResearchWorkflow
from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture

import hashlib
import ast
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from trading_platform.persistence import PlatformStore
from trading_platform.persistence.locking import PersistenceError
from trading_platform.operations import PlatformOperations
from trading_platform.application.workflow_ledger import (
    BeginNode,
    ArtifactPayload,
    FailExecution,
    MarkRetryable,
    StartDisposition,
    StartWorkflow,
    IntegrityScope,
    ArtifactBundlePreviewQuery,
    ResearchArtifactBundle,
    ResearchRunIdentityQuery,
    WorkflowRunQuery,
)
from trading_platform.persistence.workflow_ledger import WorkflowLedger
from trading_platform.domain.workflow import NodeDefinition, WorkflowDefinition
from tests.platform.test_research_workflow import CountingEngine, _request, _root
from tests.platform.test_outlook_artifacts import _drafts
from test_scenario_valuation import scenario_request
from equity_research.forecast import ForecastEngine
from equity_research.scenario_valuation import ScenarioValuationEngine
from trading_platform.domain.workflow import ImmutableArtifactDraft


TEST_WORKFLOW = WorkflowDefinition(
    "ledger-test-workflow",
    "1",
    (
        NodeDefinition("test_node", "1", "Input@1", "Output@1", ("ready",), True, "none", "new_attempt_same_run", ("TEST_FAILED",)),
    ),
)


def _command(invocation_id: str = "ledger:start") -> StartWorkflow:
    return StartWorkflow(
        invocation_id=invocation_id,
        request_fingerprint="request-fingerprint",
        requested_date="2026-07-10",
        effective_session_date="2026-07-10",
        definition=TEST_WORKFLOW,
        owner_token="owner-a",
        request_payload=b'{"schema":"ResearchWorkflowRequest@1"}',
        request_schema="ResearchWorkflowRequest@1",
    )


def _ledger(tmp_path):
    migrations_root = Path(__file__).parents[2] / "migrations"
    store = PlatformStore(tmp_path / "data", migrations_root)
    store.migrate()
    return store, WorkflowLedger(store.connection, store.data_root, store.writer_lock)


def test_workflow_ledger_atomically_creates_and_exactly_replays_request(
    tmp_path,
) -> None:
    store, ledger = _ledger(tmp_path)
    command = _command()

    created = ledger.start_or_replay(command)
    replay = ledger.start_or_replay(command)

    assert created.disposition is StartDisposition.CREATED
    assert replay.disposition is StartDisposition.REPLAYED
    assert replay.workflow_run_id == created.workflow_run_id
    view = ledger.load(WorkflowRunQuery(created.workflow_run_id))
    assert view.request_payload == command.request_payload
    assert view.status == "running"
    assert ledger.audit_integrity(IntegrityScope(created.workflow_run_id)).errors == ()
    store.close()


@pytest.mark.parametrize(
    "boundary", ("object.renamed", "workflow_start.object_published", "workflow_start.before_commit")
)
def test_workflow_start_fault_leaves_no_committed_reference(tmp_path, boundary) -> None:
    store, ledger = _ledger(tmp_path)
    command = _command(f"ledger:fault:{boundary}")

    def fail(observed: str) -> None:
        if observed == boundary:
            raise RuntimeError("injected")

    ledger.fault_injector = fail
    with pytest.raises(RuntimeError, match="injected"):
        ledger.start_or_replay(command)

    assert store.connection.execute(
        "SELECT count(*) FROM workflow_run WHERE invocation_id=?",
        (command.invocation_id,),
    ).fetchone()[0] == 0
    assert store.connection.execute(
        "SELECT count(*) FROM object_blob WHERE sha256=?",
        (hashlib.sha256(command.request_payload).hexdigest(),),
    ).fetchone()[0] == 0
    store.close()


def test_workflow_start_rejects_same_invocation_with_different_request(tmp_path) -> None:
    store, ledger = _ledger(tmp_path)
    ledger.start_or_replay(_command())
    conflicting = StartWorkflow(
        **{**_command().__dict__, "request_payload": b"different"}
    )

    with pytest.raises(Exception) as caught:
        ledger.start_or_replay(conflicting)

    assert getattr(caught.value, "code", "") == "WORKFLOW_REQUEST_INTEGRITY_FAILED"
    store.close()


@pytest.mark.parametrize("mutation", ("retry", "failure"))
def test_stale_owner_cannot_retry_or_fail_active_attempt(tmp_path, mutation) -> None:
    store, ledger = _ledger(tmp_path)
    outcome = ledger.start_or_replay(_command(f"ledger:stale:{mutation}"))
    node_definition = TEST_WORKFLOW.nodes[0]
    node_id, attempt_id = ledger.record_transition(
        BeginNode(
            outcome.workflow_run_id,
            node_definition,
            "node-fingerprint",
            "owner-a",
        )
    )
    with store.connection:
        store.connection.execute(
            "UPDATE workflow_run SET owner_token='owner-b' WHERE workflow_run_id=?",
            (outcome.workflow_run_id,),
        )
        store.connection.execute(
            "UPDATE workflow_node_run SET owner_token='owner-b' WHERE workflow_node_run_id=?",
            (node_id,),
        )
        store.connection.execute(
            "UPDATE workflow_node_attempt SET owner_token='owner-b' WHERE workflow_node_attempt_id=?",
            (attempt_id,),
        )
    command = (
        MarkRetryable(
            outcome.workflow_run_id,
            node_id,
            attempt_id,
            "owner-a",
            "TRANSIENT_FAILURE",
        )
        if mutation == "retry"
        else FailExecution(
            outcome.workflow_run_id,
            node_id,
            attempt_id,
            "owner-a",
            "NODE_FAILED",
            ArtifactPayload(b'{"error":"redacted"}', "application/json", "Diagnostic@1"),
        )
    )

    with pytest.raises(Exception) as caught:
        ledger.record_transition(command)

    assert getattr(caught.value, "code", None) == "WORKFLOW_LEASE_LOST"
    assert store.connection.execute(
        "SELECT status FROM workflow_run WHERE workflow_run_id=?",
        (outcome.workflow_run_id,),
    ).fetchone()[0] == "running"
    store.close()


def test_concurrent_writer_fails_closed_with_stable_busy_code(tmp_path) -> None:
    store, ledger = _ledger(tmp_path)

    with store.writer_lock.acquire("owning-ledger-test"):
        with pytest.raises(PersistenceError) as caught:
            ledger.start_or_replay(_command("ledger:busy"))

    assert caught.value.code == "RUNTIME_BUSY"
    assert ledger.audit_integrity(IntegrityScope()).errors == ()
    store.close()


def test_scoped_audit_detects_corrupt_workflow_object(tmp_path) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("ledger:audit")))
    row = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT o.relative_path FROM workflow_run_ref r "
        "JOIN artifact_manifest_member m ON m.artifact_manifest_id=r.ref_id "
        "JOIN artifact a USING(artifact_id) JOIN object_blob o ON o.sha256=a.object_sha256 "
        "WHERE r.workflow_run_id=? AND r.ref_role='final_manifest' LIMIT 1",
        (result.workflow_run_id,),
    ).fetchone()
    root.faults.corrupt_object(row["relative_path"], b"corrupt")

    adapter_store = PlatformStore(
        root.data_root, Path(__file__).parents[2] / "migrations"
    )
    report = adapter_store.workflow_ledger.audit_integrity(
        IntegrityScope(result.workflow_run_id)
    )
    adapter_store.close()

    assert "OBJECT_INTEGRITY_FAILED" in report.errors
    root.close()


def test_workflow_persistence_has_one_public_owner_and_no_cross_seam_sql() -> None:
    source_root = Path(__file__).parents[2] / "src" / "trading_platform"
    ledger_tree = ast.parse(
        (source_root / "persistence" / "workflow_ledger.py").read_text(encoding="utf-8")
    )
    ledger_class = next(
        node
        for node in ledger_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WorkflowLedger"
    )
    public_methods = {
        node.name
        for node in ledger_class.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    assert public_methods == {
        "start_or_replay",
        "record_transition",
        "commit_checkpoint",
        "commit_artifacts",
        "complete",
        "load",
        "audit_integrity",
        "cutover_research_decision_views",
    }

    workflow_tables = {
        "workflow_run",
        "workflow_transition",
        "workflow_node_run",
        "workflow_node_attempt",
        "workflow_run_ref",
        "workflow_run_request",
        "workflow_run_artifact_use",
        "research_artifact_record",
        "artifact_manifest",
        "artifact_manifest_member",
    }
    violations = []
    dependency_violations = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        persistence_module = "persistence" in relative.parts
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not persistence_module and path.name != "operations.py":
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "trading_platform.persistence.workflow_ledger"
                ):
                    dependency_violations.append(
                        f"{relative}:{node.lineno}"
                    )
        if persistence_module and path.name in {
            "workflow_ledger.py",
            "research_view_cutover.py",
            "migration.py",
        }:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            normalized = " ".join(node.value.lower().split())
            if not any(keyword in normalized for keyword in ("select ", "insert ", "update ", "delete ", " join ")):
                continue
            if workflow_tables.intersection(normalized.replace(",", " ").replace("(", " ").split()):
                violations.append(f"{relative}:{node.lineno}")
    assert violations == []
    assert dependency_violations == []


def test_artifact_bundle_validation_replay_and_integrity_fail_closed(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("outlook:integrity")))
    migrations_root = Path(__file__).parents[2] / "migrations"
    adapter_store = PlatformStore(root.data_root, migrations_root)
    ledger = adapter_store.workflow_ledger
    code_identity = ledger.load(
        ResearchRunIdentityQuery(result.research_run_id)
    ).code_identity
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
        ledger.load(
            ArtifactBundlePreviewQuery(
                ResearchArtifactBundle(
                    research_run_id=result.research_run_id,
                    data_snapshot_id=result.research_snapshot_id,
                    code_identity=code_identity,
                    drafts=foreign_drafts,
                )
            )
        )

    def replay() -> None:
        outputs.append(
            ledger.load(
                ArtifactBundlePreviewQuery(
                    ResearchArtifactBundle(
                        research_run_id=result.research_run_id,
                        data_snapshot_id=result.research_snapshot_id,
                        code_identity=code_identity,
                        drafts=drafts,
                    )
                )
            ).record_ids
        )

    threads = [threading.Thread(target=replay) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert outputs == [result.artifact_record_ids, result.artifact_record_ids]
    assert ledger.load(
        ArtifactBundlePreviewQuery(
            ResearchArtifactBundle(
                research_run_id=result.research_run_id,
                data_snapshot_id=result.research_snapshot_id,
                code_identity=code_identity,
                drafts=drafts,
            )
        )
    ).record_ids == result.artifact_record_ids

    view = root.archive.artifact(result.artifact_record_ids[1])
    row = adapter_store.connection.execute(
        "SELECT o.relative_path FROM research_artifact_record r "
        "JOIN artifact a USING(artifact_id) JOIN object_blob o ON o.sha256=a.object_sha256 "
        "WHERE r.artifact_record_id=?",
        (view.artifact_record_id,),
    ).fetchone()
    adapter_store.close()
    (tmp_path / row[0]).write_bytes(b"corrupt")
    with pytest.raises(PersistenceError) as integrity:
        root.archive.artifact(view.artifact_record_id)
    assert integrity.value.code == "OBJECT_INTEGRITY_FAILED"
    doctor = PlatformOperations(root.data_root).doctor()
    assert doctor["status"] == "failed"
    assert "OBJECT_INTEGRITY_FAILED" in doctor["errors"]
    root.close()


def test_research_artifact_schema_and_rows_are_immutable(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    result = root.research.handle(StartResearchWorkflow(_request("ledger:immutability")))
    connection = SQLiteOwningAdapterFixture(root.data_root)
    assert len(connection.execute("PRAGMA table_info(research_run_record)").fetchall()) == 11
    with pytest.raises(sqlite3.IntegrityError, match="RESEARCH_ARTIFACT_IMMUTABLE"):
        connection.execute(
            "UPDATE research_artifact_record SET status='blocked' WHERE artifact_record_id=?",
            (result.artifact_record_ids[0],),
        )
    connection.close()
    root.close()
