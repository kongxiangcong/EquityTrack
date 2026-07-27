from __future__ import annotations

from pathlib import Path

import pytest

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from trading_platform.application.contracts import (
    ResumeWorkflowCommand,
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    EvaluationHorizon,
    EvaluationPurpose,
    ResearchEvaluationPlan,
    ResearchWorkflowRequest,
    StrategyValidationSelection,
)
from trading_platform.application import (
    GetEstimatedAccountState,
    open_account_state_queries,
)
from tests.platform.test_account_snapshots import _draft, _ready_root
from tests.platform.test_estimated_account_state import _confirmed


class InjectedCrash(RuntimeError):
    pass


def test_estimated_account_state_rebuilds_identically_after_restart(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    _confirmed(
        data_root,
        _draft(cash_state="unknown"),
        create_invocation="restart:state:create",
        confirm_invocation="restart:state:confirm",
    )
    with open_account_state_queries(data_root) as first_process:
        before = first_process.get(GetEstimatedAccountState("account_local"))
    with open_account_state_queries(data_root) as restarted_process:
        after = restarted_process.get(GetEstimatedAccountState("account_local"))
    assert after == before
    assert after.unverified_evidence == (
        "EXECUTION_RECORD_READER_UNAVAILABLE",
    )


class CrashAt:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.triggered = False

    def __call__(self, boundary: str) -> None:
        if boundary == self.boundary and not self.triggered:
            self.triggered = True
            raise InjectedCrash(boundary)


def research_request(invocation: str) -> ResearchWorkflowRequest:
    return ResearchWorkflowRequest(
        "ResearchWorkflowRequest@2",
        invocation,
        "security_yihua",
        "2026-07-11",
        "2026-07-10",
        "snapshot_filing",
        ResearchEvaluationPlan(
            "ResearchEvaluationPlan@1",
            EvaluationPurpose.COMPANY_OUTLOOK,
            EvaluationHorizon(
                "2026-07-11",
                "2028-12-31",
                "2026-10-31",
            ),
            (
                EvaluationDimension.SOURCE_QUALITY,
                EvaluationDimension.FORECAST,
                EvaluationDimension.VALUATION,
            ),
            StrategyValidationSelection.NOT_REQUESTED,
        ),
    )


def recovery_root(
    path: Path, injector=None
) -> PlatformTaskFixture:
    root = PlatformTaskFixture(
        path,
        workflow_fault_injector=injector,
    )
    if (
        SQLiteOwningAdapterFixture(root.data_root)
        .execute(
            "SELECT 1 FROM security WHERE security_id='security_yihua'"
        )
        .fetchone()
        is None
    ):
        root.watchlist.add(
            "watch:security_yihua",
            SecurityIdentity(
                "security_yihua",
                "SZSE",
                "002897",
                "CNY",
                "2017-09-07",
            ),
        )
        root.faults.record_official_filing_workflow_snapshot()
    return root


def _expire_lease(root: PlatformTaskFixture, workflow_run_id: str) -> None:
    SQLiteOwningAdapterFixture(root.data_root).execute(
        "UPDATE workflow_run SET lease_expires_at=? "
        "WHERE workflow_run_id=?",
        ("2000-01-01T00:00:00+00:00", workflow_run_id),
    )


def test_resume_after_atomic_evaluation_checkpoint_does_not_recompute_or_duplicate(
    tmp_path: Path,
) -> None:
    root = recovery_root(
        tmp_path,
        CrashAt("workflow.research_checkpoint_committed"),
    )
    with pytest.raises(InjectedCrash):
        root.research.handle(
            StartResearchWorkflow(research_request("recovery:checkpoint"))
        )
    adapter = SQLiteOwningAdapterFixture(root.data_root)
    workflow_run_id = adapter.execute(
        "SELECT workflow_run_id FROM workflow_run"
    ).fetchone()[0]
    assert (
        adapter.execute(
            "SELECT count(*) FROM research_run_record"
        ).fetchone()[0]
        == 1
    )
    assert (
        adapter.execute(
            "SELECT count(*) FROM artifact_manifest "
            "WHERE manifest_role='workflow_decision_view@2'"
        ).fetchone()[0]
        == 1
    )
    _expire_lease(root, workflow_run_id)
    root.close()

    rebuilt = recovery_root(tmp_path)
    result = rebuilt.research.handle(
        ResumeWorkflowCommand(workflow_run_id, "recovery-owner")
    )

    adapter = SQLiteOwningAdapterFixture(rebuilt.data_root)
    assert result.workflow_run_id == workflow_run_id
    assert (
        adapter.execute(
            "SELECT count(*) FROM research_run_record"
        ).fetchone()[0]
        == 1
    )
    assert (
        adapter.execute(
            "SELECT count(*) FROM artifact_manifest "
            "WHERE manifest_role='workflow_decision_view@2'"
        ).fetchone()[0]
        == 1
    )
    rebuilt.close()


def test_replay_after_terminal_commit_returns_identical_result(
    tmp_path: Path,
) -> None:
    request = research_request("recovery:terminal")
    root = recovery_root(
        tmp_path,
        CrashAt("workflow.final_manifest_committed"),
    )
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(request))
    workflow_run_id = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT workflow_run_id FROM workflow_run"
    ).fetchone()[0]
    root.close()

    rebuilt = recovery_root(tmp_path)
    resumed = rebuilt.research.handle(
        ResumeWorkflowCommand(workflow_run_id, "terminal-owner")
    )
    replayed = rebuilt.research.handle(StartResearchWorkflow(request))

    assert resumed == replayed
    assert resumed.workflow_run_id == workflow_run_id
    assert (
        SQLiteOwningAdapterFixture(rebuilt.data_root)
        .execute(
            "SELECT count(*) FROM artifact_manifest "
            "WHERE manifest_role='workflow_decision_view@2'"
        )
        .fetchone()[0]
        == 1
    )
    rebuilt.close()


def test_recovery_payload_is_request_v2_and_contains_no_caller_facts(
    tmp_path: Path,
) -> None:
    root = recovery_root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(research_request("recovery:request-v2"))
    )
    row = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT r.request_schema_version,a.object_sha256,o.relative_path "
        "FROM workflow_run_request r JOIN artifact a "
        "ON a.artifact_id=r.request_artifact_id "
        "JOIN object_blob o ON o.sha256=a.object_sha256 "
        "WHERE r.workflow_run_id=?",
        (result.workflow_run_id,),
    ).fetchone()
    payload = (root.data_root / row["relative_path"]).read_text(
        encoding="utf-8"
    )
    assert row["request_schema_version"] == "ResearchWorkflowRequest@2"
    assert '"data_snapshot_id":"snapshot_filing"' in payload
    for retired in (
        '"projection"',
        '"manifest"',
        '"estimates"',
        '"analysis_artifacts"',
        '"candidate_member_ids"',
    ):
        assert retired not in payload
    root.close()
