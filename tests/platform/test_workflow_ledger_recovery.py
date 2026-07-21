from __future__ import annotations

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture

from trading_platform.application.contracts import StartResearchWorkflow

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application.contracts import CancelWorkflowCommand, ResumeWorkflowCommand, SecurityIdentity
from trading_platform.workflows.research import WorkflowError
from trading_platform.application.workflow_ledger import IntegrityScope
from trading_platform.persistence import PlatformStore
from tests.platform.test_data_sync_pit import _request as sync_request, _root as sync_root
from tests.platform.test_research_workflow import CountingEngine, _request as research_request


class InjectedCrash(BaseException):
    pass


class CrashAt:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.hits: list[str] = []
        self.triggered = False

    def __call__(self, boundary: str) -> None:
        self.hits.append(boundary)
        if boundary == self.boundary and not self.triggered:
            self.triggered = True
            raise InjectedCrash(boundary)


def _root(path: Path, engine, injector=None) -> PlatformTaskFixture:
    root = PlatformTaskFixture(path, research_engine=engine, workflow_fault_injector=injector)
    if not root.watchlist.list():
        root.watchlist.add("watch:recovery", SecurityIdentity("security_yihua", "SZSE", "002897", "CNY", "2017-09-07"))
    return root


def _expire(root: PlatformTaskFixture, run_id: str) -> None:
    adapter = SQLiteOwningAdapterFixture(root.data_root)
    with adapter.transaction():
        adapter.execute("UPDATE workflow_run SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE workflow_run_id=?", (run_id,))
    adapter.close()


@pytest.mark.parametrize(
    "boundary,records_before_resume",
    [
        ("research_artifact.before_commit", 0),
        ("workflow.research_artifacts_persisted", 0),
    ],
)
def test_artifact_bundle_crash_recovery_has_no_partial_typed_commit(
    tmp_path: Path,
    boundary: str,
    records_before_resume: int,
) -> None:
    from tests.platform.test_outlook_artifacts import _request as outlook_request

    engine = CountingEngine()
    injector = CrashAt(boundary)
    root = _root(tmp_path, engine, injector)
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(outlook_request("outlook:crash")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT workflow_run_id FROM workflow_run WHERE invocation_id='outlook:crash'"
    ).fetchone()[0]
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM research_artifact_record"
    ).fetchone()[0] == records_before_resume
    if boundary == "research_artifact.before_commit":
        assert SQLiteOwningAdapterFixture(root.data_root).execute(
            "SELECT count(*) FROM research_run_record"
        ).fetchone()[0] == 0
        assert SQLiteOwningAdapterFixture(root.data_root).execute(
            "SELECT count(*) FROM workflow_run_artifact_use WHERE workflow_run_id=?",
            (run_id,),
        ).fetchone()[0] == 0
        assert SQLiteOwningAdapterFixture(root.data_root).execute(
            "SELECT count(*) FROM workflow_node_run WHERE workflow_run_id=? "
            "AND node_id='run_or_link_research' AND checkpoint_manifest_id IS NOT NULL",
            (run_id,),
        ).fetchone()[0] == 0

    _expire(root, run_id)
    resumed = root.research.handle(ResumeWorkflowCommand(run_id, "resume-owner"))
    assert len(resumed.artifact_record_ids) == 3
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM research_artifact_record"
    ).fetchone()[0] == 3
    assert engine.calls == 2
    root.close()


@pytest.mark.parametrize("boundary", ["object.temp_fsynced", "object.renamed", "object.before_db_registration", "object.db_registered"])
def test_object_publication_crash_replay_is_orphan_or_complete_object(tmp_path: Path, boundary: str) -> None:
    engine = CountingEngine()
    injector = CrashAt(boundary)
    root = _root(tmp_path, engine, injector)
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("recovery:object")))
    root.close()

    rebuilt = _root(tmp_path, engine)
    result = rebuilt.research.handle(StartResearchWorkflow(research_request("recovery:object")))
    assert result.research_run_id
    adapter_store = PlatformStore(
        rebuilt.data_root, Path(__file__).parents[2] / "migrations"
    )
    assert adapter_store.workflow_ledger.audit_integrity(IntegrityScope()).errors == ()
    adapter_store.close()
    assert not tuple((tmp_path / "objects").rglob(".*.tmp"))
    rebuilt.close()


@pytest.mark.parametrize(
    "boundary,expected_engine_calls",
    [
        ("workflow.before_node_success:freeze_research_projection", 1),
        ("projection_checkpoint.before_commit", 1),
        ("workflow.freeze_checkpoint_committed", 1),
        ("workflow.before_node_success:run_or_link_research", 2),
        ("workflow.research_checkpoint_committed", 1),
        ("workflow.before_final_manifest_commit", 1),
        ("workflow_complete.before_commit", 1),
        ("workflow.final_manifest_committed", 1),
    ],
)
def test_resume_reuses_committed_nodes_and_never_duplicates_research(
    tmp_path: Path, boundary: str, expected_engine_calls: int
) -> None:
    engine = CountingEngine()
    injector = CrashAt(boundary)
    root = _root(tmp_path, engine, injector)
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("recovery:nodes")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT workflow_run_id FROM workflow_run WHERE invocation_id='recovery:nodes'").fetchone()[0]
    if boundary == "workflow.final_manifest_committed":
        assert root.research.handle(StartResearchWorkflow(research_request("recovery:nodes"))).workflow_run_id == run_id
    else:
        _expire(root, run_id)
        result = root.research.handle(ResumeWorkflowCommand(run_id, "resume-owner"))
        assert result.workflow_run_id == run_id
    assert engine.calls == expected_engine_calls
    attempts = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT node_id,count(*) count FROM workflow_node_run JOIN workflow_node_attempt USING(workflow_node_run_id) WHERE workflow_run_id=? GROUP BY node_id", (run_id,)).fetchall()
    assert all(row["count"] <= 2 for row in attempts)
    adapter_store = PlatformStore(
        root.data_root, Path(__file__).parents[2] / "migrations"
    )
    assert adapter_store.workflow_ledger.audit_integrity(IntegrityScope()).errors == ()
    adapter_store.close()
    root.close()


def test_projection_checkpoint_failure_rolls_back_the_whole_projection_aggregate(
    tmp_path: Path,
) -> None:
    root = _root(
        tmp_path,
        CountingEngine(),
        CrashAt("projection_checkpoint.before_commit"),
    )

    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("recovery:projection-tx")))

    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM research_input_projection"
    ).fetchone()[0] == 0
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM data_snapshot WHERE snapshot_purpose='research'"
    ).fetchone()[0] == 0
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM provider_attempt WHERE provider_id='frozen_projection'"
    ).fetchone()[0] == 0
    root.close()


def test_finalization_failure_rolls_back_manifest_refs_decision_and_terminal_state(
    tmp_path: Path,
) -> None:
    root = _root(
        tmp_path,
        CountingEngine(),
        CrashAt("workflow_complete.before_commit"),
    )

    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("recovery:finalize-tx")))

    run_id = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT workflow_run_id FROM workflow_run "
        "WHERE invocation_id='recovery:finalize-tx'"
    ).fetchone()[0]
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT status FROM workflow_run WHERE workflow_run_id=?", (run_id,)
    ).fetchone()[0] == "running"
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM research_reuse_decision WHERE workflow_run_id=?",
        (run_id,),
    ).fetchone()[0] == 0
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM workflow_run_ref WHERE workflow_run_id=? "
        "AND ref_role='final_manifest'",
        (run_id,),
    ).fetchone()[0] == 0
    assert SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT count(*) FROM artifact_manifest WHERE producer_type='WorkflowRun' "
        "AND producer_id=? AND manifest_role='workflow_final'",
        (run_id,),
    ).fetchone()[0] == 0
    root.close()


def test_lease_takeover_abandons_attempt_and_rejects_live_second_owner(tmp_path: Path) -> None:
    engine = CountingEngine()
    injector = CrashAt("workflow.node_attempt_started:run_or_link_research")
    root = _root(tmp_path, engine, injector)
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("recovery:lease")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT workflow_run_id FROM workflow_run WHERE invocation_id='recovery:lease'").fetchone()[0]
    with pytest.raises(WorkflowError) as busy:
        root.research.handle(ResumeWorkflowCommand(run_id, "other-owner"))
    assert busy.value.code == "WORKFLOW_BUSY" and busy.value.workflow_run_id == run_id
    _expire(root, run_id)
    result = root.research.handle(ResumeWorkflowCommand(run_id, "other-owner"))
    assert result.workflow_run_id == run_id and engine.calls == 1
    attempts = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT attempt_no,disposition FROM workflow_node_attempt a JOIN workflow_node_run n USING(workflow_node_run_id) WHERE n.workflow_run_id=? AND n.node_id='run_or_link_research' ORDER BY attempt_no", (run_id,)).fetchall()
    assert [tuple(row) for row in attempts] == [(1, "abandoned"), (2, "succeeded")]
    root.close()


def test_live_invocation_replay_cannot_adopt_current_owner(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine(), CrashAt("workflow.node_attempt_started:run_or_link_research"))
    request = research_request("recovery:live-replay")
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(request))
    with pytest.raises(WorkflowError) as busy:
        root.research.handle(StartResearchWorkflow(request))
    assert busy.value.code == "WORKFLOW_BUSY"
    root.close()


def test_invocation_replay_rejects_different_request_payload(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    original = research_request("recovery:request-mismatch")
    root.research.handle(StartResearchWorkflow(original))
    changed = research_request("recovery:request-mismatch")
    changed = type(changed)(**{**changed.__dict__, "effective_session_date": "2026-07-08"})
    with pytest.raises(WorkflowError) as mismatch:
        root.research.handle(StartResearchWorkflow(changed))
    assert mismatch.value.code == "INVOCATION_REQUEST_MISMATCH"
    root.close()


class TransientEngine(CountingEngine):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def run(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("temporary network timeout")
        return self._delegate.run(request)


class SlowEngine(CountingEngine):
    def run(self, request):
        self.calls += 1
        time.sleep(1.5)
        return self._delegate.run(request)


def test_transient_failure_creates_bounded_monotonic_attempts(tmp_path: Path) -> None:
    engine = TransientEngine(2)
    root = _root(tmp_path, engine)
    result = root.research.handle(StartResearchWorkflow(research_request("recovery:retry")))
    attempts = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT attempt_no,disposition,retryable FROM workflow_node_attempt a JOIN workflow_node_run n USING(workflow_node_run_id) WHERE n.workflow_run_id=? AND n.node_id='run_or_link_research' ORDER BY attempt_no", (result.workflow_run_id,)).fetchall()
    assert [tuple(row) for row in attempts] == [(1, "failed", 1), (2, "failed", 1), (3, "succeeded", 0)]
    root.close()


def test_nonretryable_failure_is_terminal_after_one_attempt(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine("invalid input"))
    with pytest.raises(WorkflowError):
        root.research.handle(StartResearchWorkflow(research_request("recovery:nonretryable")))
    attempts = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT attempt_no,retryable FROM workflow_node_attempt a JOIN workflow_node_run n USING(workflow_node_run_id) WHERE n.node_id='run_or_link_research'").fetchall()
    assert [tuple(row) for row in attempts] == [(1, 0)]
    root.close()


def test_periodic_heartbeat_prevents_takeover_during_slow_engine_call(tmp_path: Path) -> None:
    root = _root(tmp_path, SlowEngine(), CrashAt("workflow.node_attempt_started:run_or_link_research"))
    request = research_request("recovery:slow-heartbeat")
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(request))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT workflow_run_id FROM workflow_run LIMIT 1").fetchone()[0]
    contender = _root(tmp_path, CountingEngine())
    _expire(root, run_id)
    results: list[object] = []

    def resume() -> None:
        try:
            results.append(root.research.handle(ResumeWorkflowCommand(run_id, "slow-owner", 1)))
        except BaseException as error:
            results.append(error)

    worker = threading.Thread(target=resume)
    worker.start()
    time.sleep(1.1)
    with pytest.raises(WorkflowError) as busy:
        contender.research.handle(ResumeWorkflowCommand(run_id, "contender", 1))
    assert busy.value.code == "WORKFLOW_BUSY"
    worker.join(timeout=5)
    assert len(results) == 1 and not isinstance(results[0], BaseException)
    contender.close()
    root.close()


@pytest.mark.parametrize("corruption,code", [("quality", "WORKFLOW_QUALITY_BLOCKED"), ("domain_ref", "WORKFLOW_DOMAIN_REFERENCE_INVALID")])
def test_resume_revalidates_quality_and_domain_references(tmp_path: Path, corruption: str, code: str) -> None:
    root = _root(tmp_path, CountingEngine(), CrashAt("workflow.freeze_checkpoint_committed"))
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request(f"recovery:domain:{corruption}")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT workflow_run_id FROM workflow_run LIMIT 1").fetchone()[0]
    if corruption == "quality":
        SQLiteOwningAdapterFixture(root.data_root).execute("UPDATE data_snapshot SET quality_status='blocking' WHERE snapshot_purpose='research'")
    else:
        SQLiteOwningAdapterFixture(root.data_root).execute("DELETE FROM research_input_projection")
    _expire(root, run_id)
    with pytest.raises(WorkflowError) as failed:
        root.research.handle(ResumeWorkflowCommand(run_id, "domain-owner"))
    assert failed.value.code == code
    root.close()


@pytest.mark.parametrize("corruption,code", [("workflow_definition", "WORKFLOW_DEFINITION_MISMATCH"), ("node_version", "WORKFLOW_DEFINITION_MISMATCH"), ("schema", "WORKFLOW_DEFINITION_MISMATCH"), ("input_fingerprint", "WORKFLOW_FINGERPRINT_MISMATCH"), ("artifact", "CHECKPOINT_INTEGRITY_FAILED"), ("missing_artifact", "CHECKPOINT_INTEGRITY_FAILED")])
def test_resume_fails_closed_on_definition_fingerprint_or_artifact_corruption(tmp_path: Path, corruption: str, code: str) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine, CrashAt("workflow.freeze_checkpoint_committed"))
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request(f"recovery:corrupt:{corruption}")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT workflow_run_id FROM workflow_run ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    if corruption == "workflow_definition":
        SQLiteOwningAdapterFixture(root.data_root).execute("DROP TRIGGER workflow_run_identity_immutable")
        SQLiteOwningAdapterFixture(root.data_root).execute("UPDATE workflow_run SET definition_hash='old' WHERE workflow_run_id=?", (run_id,))
    if corruption in {"node_version", "schema", "input_fingerprint"}:
        # Simulate an older/tampered database while production triggers keep history immutable.
        SQLiteOwningAdapterFixture(root.data_root).execute("DROP TRIGGER workflow_node_contract_immutable")
    if corruption == "node_version":
        SQLiteOwningAdapterFixture(root.data_root).execute("UPDATE workflow_node_run SET node_version='old' WHERE workflow_run_id=? AND node_id='freeze_research_projection'", (run_id,))
    elif corruption == "schema":
        SQLiteOwningAdapterFixture(root.data_root).execute("UPDATE workflow_node_run SET output_schema='old' WHERE workflow_run_id=? AND node_id='freeze_research_projection'", (run_id,))
    elif corruption == "input_fingerprint":
        SQLiteOwningAdapterFixture(root.data_root).execute("UPDATE workflow_node_run SET input_fingerprint='tampered' WHERE workflow_run_id=? AND node_id='freeze_research_projection'", (run_id,))
    elif corruption in {"artifact", "missing_artifact"}:
        artifact = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT a.object_sha256,o.relative_path FROM workflow_node_run n JOIN artifact_manifest_member m ON m.artifact_manifest_id=n.checkpoint_manifest_id JOIN artifact a USING(artifact_id) JOIN object_blob o ON o.sha256=a.object_sha256 WHERE n.workflow_run_id=? LIMIT 1", (run_id,)).fetchone()
        path = tmp_path / artifact["relative_path"]
        path.unlink() if corruption == "missing_artifact" else path.write_bytes(b"corrupt")
    _expire(root, run_id)
    with pytest.raises(WorkflowError) as caught:
        root.research.handle(ResumeWorkflowCommand(run_id, "resume-corrupt"))
    assert caught.value.code == code and engine.calls == 0
    root.close()


def test_cancellation_and_retry_history_are_monotonic(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = _root(tmp_path / "cancel", engine, CrashAt("workflow.freeze_checkpoint_committed"))
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("recovery:cancel")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT workflow_run_id FROM workflow_run LIMIT 1").fetchone()[0]
    root.research.handle(CancelWorkflowCommand(run_id, "user_cancelled"))
    _expire(root, run_id)
    with pytest.raises(WorkflowError) as cancelled:
        root.research.handle(ResumeWorkflowCommand(run_id, "resume-cancelled"))
    assert cancelled.value.code == "WORKFLOW_CANCELLED"
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT status FROM workflow_run WHERE workflow_run_id=?", (run_id,)).fetchone()[0] == "cancelled"
    with pytest.raises(sqlite3.IntegrityError, match="WORKFLOW_TRANSITION_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute("DELETE FROM workflow_transition WHERE workflow_run_id=?", (run_id,))
    root.close()


def test_cursor_and_normalized_transaction_roll_back_then_replay_once(tmp_path: Path) -> None:
    root = sync_root(tmp_path)
    injector = CrashAt("data.before_commit")
    root.faults.set_workflow_fault_injector(injector)
    root.faults.set_data_fault_injector(injector)
    with pytest.raises(InjectedCrash):
        root.data.sync(sync_request("recovery:cursor"))
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM sync_cursor").fetchone()[0] == 0
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM normalized_version").fetchone()[0] == 0
    root.faults.set_workflow_fault_injector(None)
    root.faults.set_data_fault_injector(None)
    result = root.data.sync(sync_request("recovery:cursor"))
    assert result.snapshot_id
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM sync_cursor").fetchone()[0] == 3
    version_count = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM normalized_version").fetchone()[0]
    replay = root.data.sync(sync_request("recovery:cursor:replay"))
    assert replay.snapshot_id == result.snapshot_id
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM normalized_version").fetchone()[0] == version_count
    root.close()


def test_cursor_response_loss_after_commit_replays_without_duplicate_versions(tmp_path: Path) -> None:
    root = sync_root(tmp_path)
    injector = CrashAt("data.after_commit")
    root.faults.set_data_fault_injector(injector)
    request = sync_request("recovery:cursor-response-loss")
    with pytest.raises(InjectedCrash):
        root.data.sync(request)
    committed_cursors = {tuple(row) for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT provider_id,adapter_version,dataset,scope_id,cursor_value FROM sync_cursor")}
    committed_versions = {row[0] for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT normalized_version_id FROM normalized_version")}
    root.faults.set_data_fault_injector(None)
    result = root.data.sync(request)
    assert result.snapshot_id
    final_cursors = {tuple(row) for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT provider_id,adapter_version,dataset,scope_id,cursor_value FROM sync_cursor")}
    final_versions = {row[0] for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT normalized_version_id FROM normalized_version")}
    assert committed_cursors <= final_cursors and len(final_cursors) == 3
    assert committed_versions <= final_versions
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM normalized_version").fetchone()[0] == len(final_versions)
    root.close()
