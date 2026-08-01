from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_research_workflow import _request, _root
from trading_platform.application.contracts import StartResearchWorkflow
from trading_platform.persistence.locking import PersistenceError
from tests.platform.test_manual_portfolio_review import (
    _complete_session,
    _start as _start_manual_review,
)
from tests.platform.test_plan_confirmation import _authority_root


def test_ledger_persists_only_request_v2_and_one_bound_view_manifest(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("ledger:request-v2"))
    )
    adapter = SQLiteOwningAdapterFixture(root.data_root)

    request = adapter.execute(
        "SELECT r.request_schema_version,a.schema_version "
        "FROM workflow_run_request r JOIN artifact a "
        "ON a.artifact_id=r.request_artifact_id"
    ).fetchone()
    view = adapter.execute(
        "SELECT manifest_role,producer_id,member_count "
        "FROM artifact_manifest "
        "WHERE manifest_role='workflow_decision_view@3'"
    ).fetchone()
    assert tuple(request) == (
        "ResearchWorkflowRequest@2",
        "ResearchWorkflowRequest@2",
    )
    assert tuple(view) == (
        "workflow_decision_view@3",
        result.workflow_run_id,
        4,
    )
    root.close()


def test_checkpoint_members_are_content_addressed_and_role_complete(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("ledger:content-addressed"))
    )
    manifest = root.archive.manifest(result.final_manifest_id)
    adapter = SQLiteOwningAdapterFixture(root.data_root)

    for member in manifest.members:
        row = adapter.execute(
            "SELECT a.object_sha256,o.relative_path FROM artifact a "
            "JOIN object_blob o ON o.sha256=a.object_sha256 "
            "WHERE a.artifact_id=?",
            (member["artifact_id"],),
        ).fetchone()
        payload = (root.data_root / row["relative_path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == row["object_sha256"]
    assert {member["member_role"] for member in manifest.members} == {
        "research_bundle_json",
        "research_run_json",
        "forecast",
        "scenario_valuation",
        "valuation_method_route",
        "valuation_simulation_decision",
        "market_path_decision",
        "recent_trend_assessment",
        "decision_view_json",
        "decision_view_html",
        "decision_view_pdf",
        "decision_view_workbook",
    }
    root.close()


def test_manual_review_uses_workflow_artifact_manifest_not_a_second_ledger(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-27")
    review = _start_manual_review(
        data_root,
        invocation_id="ledger:manual-review",
        selected_session="2026-07-27",
    )
    adapter = SQLiteOwningAdapterFixture(data_root)
    row = adapter.execute(
        "SELECT m.manifest_role,m.producer_id,m.member_count,r.ref_type "
        "FROM artifact_manifest m JOIN workflow_run_ref r "
        "ON r.ref_id=m.artifact_manifest_id "
        "WHERE r.workflow_run_id=? AND r.ref_role='manual_review_manifest'",
        (review.workflow_run_id,),
    ).fetchone()
    assert tuple(row) == (
        "manual_portfolio_review",
        review.workflow_run_id,
        1,
        "ArtifactManifest",
    )
    adapter.close()


def test_archive_fails_closed_when_a_persisted_view_object_is_corrupt(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("ledger:integrity"))
    )
    adapter = SQLiteOwningAdapterFixture(root.data_root)
    row = adapter.execute(
        "SELECT o.relative_path FROM artifact_manifest m "
        "JOIN artifact_manifest_member mm USING(artifact_manifest_id) "
        "JOIN artifact a USING(artifact_id) "
        "JOIN object_blob o ON o.sha256=a.object_sha256 "
        "WHERE m.producer_id=? AND mm.member_role='decision_view_json'",
        (result.workflow_run_id,),
    ).fetchone()
    root.faults.corrupt_object(row["relative_path"], b"corrupt")

    with pytest.raises(
        PersistenceError, match="Decision view artifact failed"
    ):
        root.archive.decision_view(result.workflow_run_id)
    root.close()


def test_retired_research_persistence_surfaces_are_absent() -> None:
    import trading_platform.application.workflow_ledger as contracts
    import trading_platform.persistence.workflow_ledger as adapter

    for name in (
        "ArtifactBundlePreviewQuery",
        "ResearchArtifactBundle",
        "ResearchProjectionQuery",
    ):
        assert not hasattr(contracts, name)
        assert not hasattr(adapter, name)
