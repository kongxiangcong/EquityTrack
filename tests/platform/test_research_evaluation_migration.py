from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from trading_platform.operations import PlatformOperations
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.locking import PersistenceError


def _prior_migrations(tmp_path: Path) -> Path:
    target = tmp_path / "migrations-v13"
    target.mkdir(parents=True)
    for source in sorted((Path.cwd() / "migrations").glob("*.sql"))[:13]:
        shutil.copyfile(source, target / source.name)
    return target


def _artifact(
    store: PlatformStore,
    artifact_id: str,
    payload: bytes,
    schema_version: str,
    media_type: str = "application/json",
) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    relative = f"objects/sha256/{digest[:2]}/{digest}"
    target = store.data_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    store.connection.execute(
        "INSERT INTO object_blob VALUES(?,?,?)",
        (digest, len(payload), relative),
    )
    store.connection.execute(
        "INSERT INTO artifact VALUES(?,?,?,?)",
        (artifact_id, digest, media_type, schema_version),
    )
    return artifact_id, digest


def _legacy_store(tmp_path: Path, *, populated: bool) -> PlatformStore:
    store = PlatformStore(tmp_path / "data", _prior_migrations(tmp_path))
    store.migrate()
    if not populated:
        return store
    projection_payload = json.dumps(
        {
            "schema_version": "ResearchProjection@1",
            "security_id": "security_legacy",
            "as_of_date": "2026-07-10",
            "audit_only": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    projection_id, projection_hash = _artifact(
        store,
        "artifact_legacy_projection",
        projection_payload,
        "ResearchProjection@1",
    )
    research_payload = json.dumps(
        {
            "run_id": "rr_legacy",
            "schema_version": 2,
            "status": "blocked",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    research_id, _ = _artifact(
        store,
        "artifact_legacy_research",
        research_payload,
        "ResearchRun@2",
    )
    html_id, _ = _artifact(
        store,
        "artifact_legacy_html",
        b"<!doctype html><title>legacy audit</title>",
        "ResearchSourceIdentityHtml@1",
        "text/html",
    )
    request_payload = json.dumps(
        {
            "invocation_id": "legacy-request-audit",
            "security_id": "security_legacy",
            "requested_date": "2026-07-10",
            "effective_session_date": "2026-07-10",
            "projection": {
                "research_projection_id": "projection_legacy"
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request_id, request_hash = _artifact(
        store,
        "artifact_legacy_request",
        request_payload,
        "ResearchWorkflowRequest@1",
    )
    with store.connection:
        store.connection.execute(
            "INSERT INTO security VALUES(?,?)",
            ("security_legacy", "CNY"),
        )
        store.connection.execute(
            "INSERT INTO query_policy_record VALUES(?,?,?,?,?)",
            ("query_policy_legacy", "QueryPolicy@1", "query-hash", "{}", "2026-07-10"),
        )
        store.connection.execute(
            "INSERT INTO source_policy_record VALUES(?,?,?,?,?)",
            ("source_policy_legacy", "SourcePolicy@1", "source-hash", "{}", "2026-07-10"),
        )
        store.connection.execute(
            "INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "snapshot_legacy",
                "security_legacy",
                "research",
                "2026-07-10",
                "2026-07-10",
                "2026-07-10T23:59:59+00:00",
                "Asia/Shanghai",
                "calendar@1",
                "query_policy_legacy",
                "source_policy_legacy",
                "freshness@1",
                "empty-audit",
                "valid",
                "warning",
                0,
                0,
                0,
                0,
                0,
                "legacy audit",
                "2026-07-10T23:59:59+00:00",
            ),
        )
        store.connection.execute(
            "INSERT INTO research_input_projection VALUES(?,?,?,?,?,?,?,?)",
            (
                "projection_legacy",
                "security_legacy",
                "2026-07-10",
                projection_id,
                projection_hash,
                "research-fingerprint",
                "research_input_policy@1",
                "snapshot_legacy",
            ),
        )
        store.connection.execute(
            "INSERT INTO research_run_record VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "rr_legacy",
                "research-fingerprint",
                "projection_legacy",
                "snapshot_legacy",
                "request-fingerprint",
                2,
                "engine@legacy",
                "2026-07-10",
                "blocked",
                research_id,
                html_id,
            ),
        )
        store.connection.execute(
            "INSERT INTO workflow_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "workflow_legacy_failed",
                "legacy-request-audit",
                "research-workflow",
                "2",
                request_hash,
                "2026-07-10",
                "2026-07-10",
                "failed",
                "2026-07-10T00:00:00+00:00",
                "2026-07-10T00:01:00+00:00",
                None,
                None,
                None,
                "legacy-definition",
                0,
            ),
        )
        store.connection.execute(
            "INSERT INTO workflow_run_request VALUES(?,?,?,?)",
            (
                "workflow_legacy_failed",
                request_id,
                request_hash,
                "ResearchWorkflowRequest@1",
            ),
        )
    return store


def test_0014_fresh_and_populated_history_cut_over_without_runtime_projection(
    tmp_path: Path,
) -> None:
    fresh = _legacy_store(tmp_path / "fresh", populated=False)
    fresh.migrations.migrations_root = Path.cwd() / "migrations"
    fresh.migrate()
    assert (
        fresh.connection.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0]
        == 24
    )
    with fresh.connection:
        fresh.connection.execute(
            "INSERT INTO workflow_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "workflow_new_write",
                "new-write-trigger",
                "research-workflow",
                "3",
                "fingerprint",
                "2026-07-11",
                "2026-07-10",
                "failed",
                "2026-07-11T00:00:00+00:00",
                "2026-07-11T00:01:00+00:00",
                None,
                None,
                None,
                "definition",
                0,
            ),
        )
    with pytest.raises(
        sqlite3.IntegrityError,
        match="RESEARCH_WORKFLOW_REQUEST_V2_REQUIRED",
    ):
        fresh.connection.execute(
            "INSERT INTO workflow_run_request VALUES(?,?,?,?)",
            (
                "workflow_new_write",
                "missing-artifact",
                "hash",
                "ResearchWorkflowRequest@1",
            ),
        )
    fresh.connection.rollback()
    fresh.close()

    populated = _legacy_store(tmp_path / "populated", populated=True)
    populated.migrations.migrations_root = Path.cwd() / "migrations"
    populated.migrate()
    plan = populated.connection.execute(
        "SELECT * FROM research_evaluation_plan_record"
    ).fetchone()
    run = populated.connection.execute(
        "SELECT * FROM research_run_record"
    ).fetchone()
    assert plan["schema_version"] == "ResearchEvaluationPlanAudit@1"
    assert json.loads(plan["canonical_json"])[
        "legacy_research_projection_id"
    ] == "projection_legacy"
    assert run["evaluation_plan_id"] == plan["evaluation_plan_id"]
    assert run["data_snapshot_id"] == "snapshot_legacy"
    assert (
        populated.connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='research_input_projection'"
        ).fetchone()
        is None
    )
    populated.close()


def test_0014_active_workflow_and_corrupt_artifact_fail_before_schema_change(
    tmp_path: Path,
) -> None:
    active = _legacy_store(tmp_path / "active", populated=False)
    with active.connection:
        active.connection.execute(
            "INSERT INTO workflow_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "workflow_active",
                "invocation-active",
                "research-workflow",
                "2",
                "fingerprint",
                "2026-07-10",
                "2026-07-10",
                "running",
                "2026-07-10T00:00:00+00:00",
                None,
                "owner",
                "2999-01-01T00:00:00+00:00",
                "2026-07-10T00:00:00+00:00",
                "definition",
                0,
            ),
        )
    active.migrations.migrations_root = Path.cwd() / "migrations"
    with pytest.raises(PersistenceError) as blocked:
        active.migrate()
    assert blocked.value.code == "MIGRATION_WORKFLOW_NOT_TERMINAL"
    assert (
        active.connection.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0]
        == 13
    )
    active.close()

    corrupt = _legacy_store(tmp_path / "corrupt", populated=True)
    object_path = corrupt.connection.execute(
        "SELECT o.relative_path FROM research_input_projection p "
        "JOIN artifact a ON a.artifact_id=p.projection_artifact_id "
        "JOIN object_blob o ON o.sha256=a.object_sha256"
    ).fetchone()[0]
    (corrupt.data_root / object_path).write_bytes(b"corrupt")
    corrupt.migrations.migrations_root = Path.cwd() / "migrations"
    with pytest.raises(PersistenceError) as blocked:
        corrupt.migrate()
    assert blocked.value.code == "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE"
    assert (
        corrupt.connection.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0]
        == 13
    )
    corrupt.close()


def test_0014_fault_rolls_back_retry_is_stable_and_backup_restores_new_root(
    tmp_path: Path,
) -> None:
    store = _legacy_store(tmp_path / "retry", populated=True)
    store.migrations.migrations_root = Path.cwd() / "migrations"
    with pytest.raises(PersistenceError) as injected:
        store.migrations.migrate(fail_after_statement=6)
    assert injected.value.code == "MIGRATION_INJECTED_FAILURE"
    assert (
        store.connection.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0]
        == 13
    )
    assert (
        store.connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='research_input_projection'"
        ).fetchone()
        is not None
    )
    store.migrate()
    first_identity = tuple(store.connection.execute(
        "SELECT evaluation_plan_id,content_hash "
        "FROM research_evaluation_plan_record"
    ).fetchone())
    store.migrate()
    assert (
        tuple(store.connection.execute(
            "SELECT evaluation_plan_id,content_hash "
            "FROM research_evaluation_plan_record"
        ).fetchone())
        == first_identity
    )
    store.close()

    live = tmp_path / "retry" / "data"
    archive = tmp_path / "research-evaluation-v14.zip"
    PlatformOperations(live).backup(archive)
    restored = tmp_path / "restored"
    report = PlatformOperations.restore(archive, restored)
    assert report["status"] == "succeeded"
    restored_store = PlatformStore(restored, Path.cwd() / "migrations")
    assert (
        tuple(restored_store.connection.execute(
            "SELECT evaluation_plan_id,content_hash "
            "FROM research_evaluation_plan_record"
        ).fetchone())
        == first_identity
    )
    restored_store.close()
