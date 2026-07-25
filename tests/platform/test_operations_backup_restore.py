from __future__ import annotations

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture

from trading_platform.application.contracts import StartResearchWorkflow


import hashlib
import json
import os
import subprocess
import sys
import time
import stat
import sqlite3
import shutil
from urllib.request import urlopen
import zipfile
import warnings
from pathlib import Path

import pytest

from tests.platform.test_chart_annotations import _root
from tests.platform.test_research_workflow import (
    _request as research_request,
    _root as research_root,
)
from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.test_workflow_ledger_recovery import (
    CrashAt,
    InjectedCrash,
    _expire_lease as _expire,
    recovery_root,
)
from trading_platform.application.workflow_ledger import GenericObjectCommit, IntegrityScope
from trading_platform.operations import OperationError, PlatformOperations
from trading_platform.credentials import CredentialAdapter
from trading_platform.persistence.presence import RuntimePresence
from trading_platform.persistence import PersistenceError, PlatformStore
from trading_platform.provider_config import load_sync_job


def test_backup_restore_new_root_preserves_database_objects_and_history(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    root = _root(live)
    before = root.workspace.build("security_yihua", "snapshot_chart")
    root.close()
    archive = tmp_path / "backups" / "platform-backup.zip"
    backup = PlatformOperations(live).backup(archive)
    assert backup["status"] == "succeeded" and archive.is_file()
    restored = tmp_path / "restored"
    report = PlatformOperations.restore(archive, restored)
    assert report["status"] == "succeeded" and report["doctor_status"] == "passed"
    rebuilt = _root(restored)
    assert (
        rebuilt.workspace.build("security_yihua", "snapshot_chart")["task"]
        == before["task"]
    )
    restored_store = PlatformStore(restored, Path.cwd() / "migrations")
    assert restored_store.workflow_ledger.audit_integrity(IntegrityScope()).errors == ()
    restored_store.close()
    rebuilt.close()
    assert (restored / "restore-report.json").is_file()


def _assert_backup_hashes(archive: Path) -> tuple[int, int]:
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("backup-manifest.json"))
        files = manifest["files"]
        assert files
        for member in files:
            payload = bundle.read(member["path"])
            assert hashlib.sha256(payload).hexdigest() == member["sha256"]
            assert len(payload) == member["size"]
        return len(files), sum(member["size"] for member in files)


def _exercise_release_root(
    tmp_path: Path,
    label: str,
    live: Path,
    workflow_result=None,
    legacy_forecast_sha256: str | None = None,
) -> None:
    operations = PlatformOperations(live)
    before = tmp_path / f"{label}-before.zip"
    before_result = operations.backup(before)
    before_counts = _assert_backup_hashes(before)
    assert before_result["status"] == "succeeded"

    assert operations.migrate()["status"] == "passed"
    assert operations.doctor()["status"] == "passed"
    if legacy_forecast_sha256 is not None:
        legacy_path = (
            live
            / "objects/sha256"
            / legacy_forecast_sha256[:2]
            / legacy_forecast_sha256
        )
        legacy_bytes = legacy_path.read_bytes()
        assert json.loads(legacy_bytes)["graph_id"].startswith("fg_")
        assert hashlib.sha256(legacy_bytes).hexdigest() == legacy_forecast_sha256
    if workflow_result is not None:
        tasks = PlatformTaskFixture(live)
        history = tasks.inspection.inspect(workflow_result.workflow_run_id)
        manifest = tasks.archive.manifest(history.final_manifest_id)
        refs = tuple(item["ref_role"] for item in history.refs)
        assert refs.count("decision_view_manifest") == 1
        assert {
            "evaluation_plan",
            "research_run",
            "research_snapshot",
            "decision_view_manifest",
            "final_manifest",
        } <= set(refs)
        view = json.loads(
            tasks.archive.decision_view(
                workflow_result.workflow_run_id
            ).json_bytes
        )
        assert view["schema_version"] == "ResearchDecisionView@2"
        assert workflow_result.artifact_record_ids == ()
        assert manifest.artifact_manifest_id == history.final_manifest_id
        tasks.close()

    after = tmp_path / f"{label}-after.zip"
    after_result = operations.backup(after)
    after_counts = _assert_backup_hashes(after)
    assert after_result["status"] == "succeeded"
    assert after_counts[0] >= before_counts[0]

    restored = tmp_path / f"{label}-restored"
    restore = PlatformOperations.restore(after, restored)
    assert restore["status"] == "succeeded"
    assert PlatformOperations(restored).doctor()["status"] == "passed"
    if legacy_forecast_sha256 is not None:
        restored_legacy = (
            restored
            / "objects/sha256"
            / legacy_forecast_sha256[:2]
            / legacy_forecast_sha256
        ).read_bytes()
        assert json.loads(restored_legacy)["graph_id"].startswith("fg_")
        assert hashlib.sha256(restored_legacy).hexdigest() == legacy_forecast_sha256
    if workflow_result is not None:
        restored_tasks = PlatformTaskFixture(restored)
        restored_history = restored_tasks.inspection.inspect(
            workflow_result.workflow_run_id
        )
        assert restored_history.final_manifest_id == workflow_result.final_manifest_id
        assert (
            restored_tasks.archive.manifest(restored_history.final_manifest_id)
            .artifact_manifest_id
            == workflow_result.final_manifest_id
        )
        restored_tasks.close()


def test_release_migration_matrix_covers_fresh_prior_created_and_reused_roots(
    tmp_path: Path,
) -> None:
    fresh = tmp_path / "fresh"
    PlatformOperations(fresh).bootstrap()
    _exercise_release_root(tmp_path, "fresh", fresh)

    prior_migrations = tmp_path / "prior-migrations"
    prior_migrations.mkdir()
    migration_files = sorted((Path.cwd() / "migrations").glob("*.sql"))
    for source in migration_files[:-1]:
        shutil.copyfile(source, prior_migrations / source.name)
    prior = tmp_path / "prior"
    prior_store = PlatformStore(prior, prior_migrations)
    prior_store.migrate()
    prior_store.close()
    _exercise_release_root(tmp_path, "prior", prior)

    created = tmp_path / "created"
    created_tasks = research_root(created)
    legacy_bytes = (
        Path.cwd() / "tests/fixtures/legacy_forecast_graph_fg1.json"
    ).read_bytes()
    created_store = PlatformStore(created, Path.cwd() / "migrations")
    legacy_sha = created_store.workflow_ledger.commit_artifacts(
        GenericObjectCommit(legacy_bytes)
    ).sha256
    created_store.close()
    created_result = created_tasks.research.handle(
        StartResearchWorkflow(research_request("release-matrix:created"))
    )
    created_tasks.close()
    _exercise_release_root(
        tmp_path,
        "created",
        created,
        created_result,
        legacy_sha,
    )

    reused = tmp_path / "reused"
    reused_tasks = research_root(reused)
    reused_store = PlatformStore(reused, Path.cwd() / "migrations")
    reused_legacy_sha = reused_store.workflow_ledger.commit_artifacts(
        GenericObjectCommit(legacy_bytes)
    ).sha256
    reused_store.close()
    first = reused_tasks.research.handle(
        StartResearchWorkflow(research_request("release-matrix:reused:first"))
    )
    replay = reused_tasks.research.handle(
        StartResearchWorkflow(research_request("release-matrix:reused:second"))
    )
    assert first.research_run_id == replay.research_run_id
    reused_tasks.close()
    _exercise_release_root(
        tmp_path,
        "reused",
        reused,
        replay,
        reused_legacy_sha,
    )


def test_source_policy_migration_rejects_ambiguous_attempt_lineage_atomically(
    tmp_path: Path,
) -> None:
    prior_migrations = tmp_path / "prior-migrations"
    prior_migrations.mkdir()
    migration_files = sorted((Path.cwd() / "migrations").glob("*.sql"))
    for source in migration_files[:-2]:
        shutil.copyfile(source, prior_migrations / source.name)
    live = tmp_path / "ambiguous-lineage"
    store = PlatformStore(live, prior_migrations)
    store.migrate()
    with store.connection:
        store.connection.execute(
            "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "attempt_legacy",
                "legacy-sync",
                "fixture",
                "fixture@1",
                "daily",
                "legacy-fixture",
                "fixture",
                "urn:test:legacy",
                "{}",
                "{}",
                "date",
                "fixture-terms@1",
                "complete",
                "created",
                None,
                "2026-07-10T09:00:00+00:00",
                None,
                None,
                None,
                "not_applicable",
            ),
        )
        store.connection.execute(
            "INSERT INTO fixture_rights_profile VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "fixture:daily",
                "legacy-fixture",
                1,
                1,
                0,
                0,
                "fixture-terms@1",
                "2026-07-10",
                None,
            ),
        )
        store.connection.execute(
            "INSERT INTO normalized_record VALUES(?,?,?)",
            ("record_legacy", "daily", "security:2026-07-10"),
        )
        store.connection.execute(
            "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "version_legacy",
                "record_legacy",
                1,
                "content",
                "attempt_legacy",
                "2026-07-10",
                "2026-07-10",
                "date",
                "2026-07-10T09:00:00+00:00",
                "publisher_timestamp",
                "2026-07-10T09:00:00+00:00",
                "pass",
                None,
            ),
        )
        for suffix, query_policy in (
            ("one", "query-policy@1"),
            ("two", "query-policy@2"),
        ):
            store.connection.execute(
                "INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"snapshot_{suffix}",
                    "security",
                    "workflow",
                    "2026-07-11",
                    "2026-07-10",
                    f"2026-07-11T0{1 if suffix == 'one' else 2}:00:00+00:00",
                    "Asia/Shanghai",
                    "cn-calendar@2026",
                    query_policy,
                    "source-policy@1",
                    "freshness@1",
                    f"members-{suffix}",
                    "valid",
                    "pass",
                    1,
                    1,
                    0,
                    0,
                    0,
                    "legacy fixture",
                    "2026-07-10T09:00:00+00:00",
                ),
            )
            store.connection.execute(
                "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
                (f"snapshot_{suffix}", "version_legacy", "daily", 0),
            )
    store.close()

    upgraded = PlatformStore(live, Path.cwd() / "migrations")
    with pytest.raises(PersistenceError) as raised:
        upgraded.migrate()
    assert raised.value.code == "SOURCE_POLICY_IDENTITY_UNMIGRATABLE"
    assert (
        upgraded.connection.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0]
        == len(migration_files) - 2
    )
    assert (
        upgraded.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='query_policy_record'"
        ).fetchone()
        is None
    )
    upgraded.close()


def test_source_policy_migration_preserves_provable_populated_lineage(
    tmp_path: Path,
) -> None:
    prior_migrations = tmp_path / "prior-migrations"
    prior_migrations.mkdir()
    migration_files = sorted((Path.cwd() / "migrations").glob("*.sql"))
    for source in migration_files[:-2]:
        shutil.copyfile(source, prior_migrations / source.name)
    live = tmp_path / "provable-populated-lineage"
    store = PlatformStore(live, prior_migrations)
    store.migrate()
    query_identity = "query_policy_" + "a" * 24
    source_identity = "source_policy_" + "b" * 24
    with store.connection:
        store.connection.execute(
            "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "attempt_provable",
                "legacy-sync",
                "fixture",
                "fixture@1",
                "daily",
                "legacy-fixture",
                "fixture",
                "urn:test:legacy",
                "{}",
                "{}",
                "date",
                "fixture-terms@1",
                "complete",
                "created",
                None,
                "2026-07-10T09:00:00+00:00",
                None,
                None,
                None,
                "not_applicable",
            ),
        )
        store.connection.execute(
            "INSERT INTO fixture_rights_profile VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "fixture:daily",
                "legacy-fixture",
                1,
                1,
                0,
                0,
                "fixture-terms@1",
                "2026-07-10",
                None,
            ),
        )
        store.connection.execute(
            "INSERT INTO normalized_record VALUES(?,?,?)",
            ("record_provable", "daily", "security:2026-07-10"),
        )
        store.connection.execute(
            "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "version_provable",
                "record_provable",
                1,
                "content",
                "attempt_provable",
                "2026-07-10",
                "2026-07-10",
                "date",
                "2026-07-10T09:00:00+00:00",
                "publisher_timestamp",
                "2026-07-10T09:00:00+00:00",
                "pass",
                None,
            ),
        )
        store.connection.execute(
            "INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "snapshot_provable",
                "security",
                "workflow",
                "2026-07-11",
                "2026-07-10",
                "2026-07-11T01:00:00+00:00",
                "Asia/Shanghai",
                "cn-calendar@2026",
                query_identity,
                source_identity,
                "freshness@1",
                "members-provable",
                "valid",
                "pass",
                1,
                1,
                0,
                0,
                0,
                "legacy fixture",
                "2026-07-10T09:00:00+00:00",
            ),
        )
        store.connection.execute(
            "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
            ("snapshot_provable", "version_provable", "daily", 0),
        )
    store.close()

    upgraded = PlatformStore(live, Path.cwd() / "migrations")
    upgraded.migrate()
    attempt = upgraded.connection.execute(
        "SELECT query_policy_identity,source_policy_identity,"
        "rights_profile_id FROM provider_attempt"
    ).fetchone()
    assert tuple(attempt[:2]) == (query_identity, source_identity)
    rights = upgraded.connection.execute(
        "SELECT automation_allowed,local_storage_allowed,"
        "derived_use_allowed,repository_redistribution_allowed,"
        "packaged_distribution_allowed FROM source_rights_profile "
        "WHERE rights_profile_id=?",
        (attempt[2],),
    ).fetchone()
    assert tuple(rights) == (1, 1, 0, 0, 0)
    snapshot_policy = upgraded.connection.execute(
        "SELECT query_policy_identity,source_policy_identity "
        "FROM data_snapshot"
    ).fetchone()
    assert tuple(snapshot_policy) == (query_identity, source_identity)
    assert (
        upgraded.connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='fixture_rights_profile'"
        ).fetchone()
        is None
    )
    assert upgraded.connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []
    upgraded.close()


def test_source_policy_migration_fault_rolls_back_schema_and_ledger(
    tmp_path: Path,
) -> None:
    prior_migrations = tmp_path / "prior-migrations"
    prior_migrations.mkdir()
    migration_files = sorted((Path.cwd() / "migrations").glob("*.sql"))
    for source in migration_files[:-2]:
        shutil.copyfile(source, prior_migrations / source.name)
    live = tmp_path / "faulted-migration"
    prior = PlatformStore(live, prior_migrations)
    prior.migrate()
    prior.close()

    upgraded = PlatformStore(live, Path.cwd() / "migrations")
    with pytest.raises(PersistenceError) as raised:
        upgraded.migrate(fail_after=5)
    assert raised.value.code == "MIGRATION_INJECTED_FAILURE"
    assert (
        upgraded.connection.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0]
        == len(migration_files) - 2
    )
    assert (
        upgraded.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='query_policy_record'"
        ).fetchone()
        is None
    )
    assert (
        upgraded.connection.execute("PRAGMA foreign_key_check").fetchall()
        == []
    )
    upgraded.close()


def test_source_policy_migration_rejects_unproved_legacy_source_rights(
    tmp_path: Path,
) -> None:
    prior_migrations = tmp_path / "prior-migrations"
    prior_migrations.mkdir()
    migration_files = sorted((Path.cwd() / "migrations").glob("*.sql"))
    for source in migration_files[:-2]:
        shutil.copyfile(source, prior_migrations / source.name)
    live = tmp_path / "unproved-source-rights"
    prior = PlatformStore(live, prior_migrations)
    prior.migrate()
    with prior.connection:
        prior.connection.execute(
            "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "attempt_unproved",
                "legacy-live-sync",
                "legacy-provider",
                "legacy@1",
                "daily",
                "legacy-source",
                "structured_aggregator",
                "urn:legacy:redacted",
                "{}",
                "{}",
                "date",
                "unreviewed-terms",
                "complete",
                "created",
                None,
                "2026-07-10T09:00:00+00:00",
                None,
                None,
                None,
                "not_applicable",
            ),
        )
    prior.close()

    upgraded = PlatformStore(live, Path.cwd() / "migrations")
    with pytest.raises(PersistenceError) as raised:
        upgraded.migrate()
    assert raised.value.code == "SOURCE_POLICY_IDENTITY_UNMIGRATABLE"
    assert (
        upgraded.connection.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0]
        == len(migration_files) - 2
    )
    assert (
        upgraded.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='source_rights_profile'"
        ).fetchone()
        is None
    )
    upgraded.close()


def test_backup_rejects_target_inside_live_root(tmp_path: Path) -> None:
    live = tmp_path / "live"
    root = _root(live)
    root.close()
    with pytest.raises(OperationError, match="BACKUP_TARGET_INSIDE_LIVE_ROOT"):
        PlatformOperations(live).backup(live / "backup.zip")


def test_backup_is_immutable_validates_object_path_and_migrate_is_full_backup_first(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    prior_migrations = tmp_path / "prior-migrations"
    prior_migrations.mkdir()
    for source in sorted((Path.cwd() / "migrations").glob("*.sql"))[:-1]:
        shutil.copyfile(source, prior_migrations / source.name)
    object_store = PlatformStore(live, prior_migrations)
    object_store.migrate()
    object_store.workflow_ledger.commit_artifacts(
        GenericObjectCommit(b"backup-object")
    )
    object_store.close()
    operations = PlatformOperations(live)
    archive = tmp_path / "immutable.zip"
    operations.backup(archive)
    with pytest.raises(OperationError, match="BACKUP_TARGET_EXISTS"):
        operations.backup(archive)
    migrated = operations.migrate()
    full_backup = tmp_path / "live-pre-migrate-v0013.zip"
    assert migrated["status"] == "passed" and full_backup.is_file()
    with zipfile.ZipFile(full_backup) as bundle:
        assert "platform.sqlite3" in bundle.namelist() and any(
            name.startswith("objects/sha256/") for name in bundle.namelist()
        )
    connection = sqlite3.connect(live / "platform.sqlite3")
    try:
        connection.execute("DROP TRIGGER object_blob_no_update")
        connection.execute(
            "UPDATE object_blob SET relative_path='objects/sha256/aa/wrong' WHERE rowid=(SELECT min(rowid) FROM object_blob)"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(OperationError, match="BACKUP_OBJECT_PATH"):
        operations.backup(tmp_path / "bad-object.zip")


def test_maintenance_rejects_active_server_presence(tmp_path: Path) -> None:
    live = tmp_path / "live"
    root = _root(live)
    root.close()
    with RuntimePresence(live, "server").acquire():
        with pytest.raises(Exception) as blocked:
            PlatformOperations(live).migrate()
        assert getattr(blocked.value, "code", None) == "MAINTENANCE_RUNTIME_ACTIVE"


@pytest.mark.parametrize("nonterminal_status", ["queued", "running"])
def test_maintenance_rejects_live_workflow_and_doctor_detects_manifest_corruption(
    tmp_path: Path, nonterminal_status: str,
) -> None:
    live = tmp_path / "live"
    root = recovery_root(
        live, CrashAt("workflow.final_manifest_committed")
    )
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("operations:maintenance")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT workflow_run_id FROM workflow_run LIMIT 1"
    ).fetchone()[0]
    SQLiteOwningAdapterFixture(root.data_root).execute(
        "UPDATE workflow_run SET status=?,completed_at=NULL,lease_expires_at='2999-01-01T00:00:00+00:00' WHERE workflow_run_id=?",
        (nonterminal_status, run_id),
    )
    root.close()
    with pytest.raises(OperationError, match="MIGRATION_WORKFLOW_NOT_TERMINAL"):
        PlatformOperations(live).migrate()
    assert not tuple(tmp_path.glob("live-pre-migrate-*.zip"))
    connection = sqlite3.connect(live / "platform.sqlite3")
    try:
        connection.execute("DROP TRIGGER artifact_manifest_no_update")
        connection.execute(
            "UPDATE artifact_manifest SET membership_hash='corrupt' WHERE rowid=(SELECT min(rowid) FROM artifact_manifest)"
        )
        connection.commit()
    finally:
        connection.close()
    report = PlatformOperations(live).doctor()
    assert "ARTIFACT_MANIFEST_HASH_MISMATCH" in report["errors"]


def test_empty_existing_database_migrates_backup_first(tmp_path: Path) -> None:
    live = tmp_path / "empty"
    live.mkdir()
    (live / "platform.sqlite3").touch()
    result = PlatformOperations(live).migrate()
    backup = tmp_path / "empty-pre-migrate-v0000.zip"
    assert result["status"] == "passed" and backup.is_file()
    with zipfile.ZipFile(backup) as bundle:
        manifest = json.loads(bundle.read("backup-manifest.json"))
        assert manifest["database_schema_version"] == 0
    assert PlatformOperations(live).doctor()["status"] == "passed"


def test_restore_rejects_safe_named_junk_not_referenced_by_database(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    root = _root(live)
    root.close()
    original = tmp_path / "original.zip"
    PlatformOperations(live).backup(original)
    attack = tmp_path / "attack-junk.zip"
    with (
        zipfile.ZipFile(original) as source,
        zipfile.ZipFile(attack, "w", compression=zipfile.ZIP_DEFLATED) as target,
    ):
        manifest = json.loads(source.read("backup-manifest.json"))
        payload = b"junk"
        digest = hashlib.sha256(payload).hexdigest()
        path = f"objects/sha256/{digest[:2]}/{digest}"
        manifest["files"].append({"path": path, "sha256": digest, "size": len(payload)})
        target.writestr("backup-manifest.json", json.dumps(manifest))
        target.writestr("platform.sqlite3", source.read("platform.sqlite3"))
        target.writestr(path, payload)
    with pytest.raises(OperationError, match="RESTORE_OBJECT_GRAPH_MISMATCH"):
        PlatformOperations.restore(attack, tmp_path / "junk-target")


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "C:/ads", "safe:ads", "objects/../escape"]
)
def test_restore_rejects_malicious_paths_without_writing_outside_target(
    tmp_path: Path, name: str
) -> None:
    archive = tmp_path / "attack.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "backup-manifest.json",
            json.dumps({"schema_version": "PlatformBackup@1", "files": []}),
        )
        bundle.writestr(name, b"attack")
    target = tmp_path / "target"
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("safe", encoding="utf-8")
    with pytest.raises(OperationError):
        PlatformOperations.restore(archive, target)
    assert (
        sentinel.read_text(encoding="utf-8") == "safe"
        and not (tmp_path / "escape").exists()
    )


def test_restore_rejects_symlink_hash_mismatch_and_bombs(tmp_path: Path) -> None:
    for attack in ("symlink", "hash", "bomb"):
        archive = tmp_path / f"{attack}.zip"
        payload = b"database"
        manifest = {
            "schema_version": "PlatformBackup@1",
            "files": [
                {
                    "path": "platform.sqlite3",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            ],
        }
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("backup-manifest.json", json.dumps(manifest))
            if attack == "symlink":
                info = zipfile.ZipInfo("platform.sqlite3")
                info.external_attr = 0o120777 << 16
                bundle.writestr(info, payload)
            elif attack == "hash":
                bundle.writestr("platform.sqlite3", b"tampered")
            else:
                bundle.writestr("platform.sqlite3", b"0" * (65 * 1024 * 1024))
        with pytest.raises(OperationError):
            PlatformOperations.restore(archive, tmp_path / f"restore-{attack}")


def test_restore_rejects_duplicate_count_total_and_nonregular_entries(
    tmp_path: Path, monkeypatch
) -> None:
    payload = b"db"
    base_manifest = {
        "schema_version": "PlatformBackup@1",
        "app_version": "platform-skeleton@1",
        "database_schema_version": 8,
        "journal_mode": "delete",
        "configuration_schema_version": "local-env-scopes@1",
        "files": [
            {
                "path": "platform.sqlite3",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
        ],
    }
    duplicate = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(duplicate, "w") as bundle:
            bundle.writestr("backup-manifest.json", json.dumps(base_manifest))
            bundle.writestr("platform.sqlite3", payload)
            bundle.writestr("platform.sqlite3", payload)
    with pytest.raises(OperationError, match="RESTORE_DUPLICATE_PATH"):
        PlatformOperations.restore(duplicate, tmp_path / "duplicate-target")
    monkeypatch.setattr(PlatformOperations, "MAX_FILES", 1)
    with pytest.raises(OperationError, match="RESTORE_FILE_COUNT_LIMIT"):
        PlatformOperations.restore(duplicate, tmp_path / "count-target")
    monkeypatch.setattr(PlatformOperations, "MAX_FILES", 100_000)
    monkeypatch.setattr(PlatformOperations, "MAX_TOTAL_SIZE", 1)
    total = tmp_path / "total.zip"
    with zipfile.ZipFile(total, "w") as bundle:
        bundle.writestr("backup-manifest.json", json.dumps(base_manifest))
        bundle.writestr("platform.sqlite3", payload)
    with pytest.raises(OperationError, match="RESTORE_TOTAL_SIZE_LIMIT"):
        PlatformOperations.restore(total, tmp_path / "total-target")
    special = tmp_path / "special.zip"
    with zipfile.ZipFile(special, "w") as bundle:
        bundle.writestr("backup-manifest.json", json.dumps(base_manifest))
        info = zipfile.ZipInfo("platform.sqlite3")
        info.external_attr = stat.S_IFBLK << 16
        bundle.writestr(info, payload)
    with pytest.raises(OperationError, match="RESTORE_LINK_FORBIDDEN"):
        PlatformOperations.restore(special, tmp_path / "special-target")


def test_windows_cli_returns_stable_json_envelopes_and_exit_codes(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "cli-root"
    command = [
        sys.executable,
        "-m",
        "trading_platform.cli",
        "bootstrap",
        "--data-root",
        str(data_root),
    ]
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    envelope = json.loads(completed.stdout)
    assert (
        completed.returncode == 0
        and envelope["ok"] is True
        and envelope["operation"] == "bootstrap"
    )
    doctor = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "doctor",
            "--data-root",
            str(data_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        doctor.returncode == 0
        and json.loads(doctor.stdout)["result"]["status"] == "passed"
    )
    failed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "restore",
            "--archive",
            str(tmp_path / "missing.zip"),
            "--target-root",
            str(tmp_path / "new"),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    error = json.loads(failed.stdout)
    assert (
        failed.returncode != 0
        and error["ok"] is False
        and error["error"]["code"] == "BACKUP_NOT_FOUND"
    )
    job = tmp_path / "sync-job.json"
    job.write_text(
        json.dumps(
            {
                "schema_version": "ProviderJob@2",
                "provider": {
                    "provider_id": "tushare-compatible",
                    "adapter_version": "tushare-http@2",
                    "credential_env": "TUSHARE_TOKEN",
                },
                "query_policy": {"schema_version": "QueryPolicy@1", "lookback_days": 7, "market_universe_list_status": "L", "adjustment_mode": "none"},
                "source_policy": {
                    "schema_version": "SourcePolicy@1", "provider_id": "tushare-compatible", "adapter_version": "tushare-http@2",
                    "source_identity": "preconfigured_tushare_compatible_non_official", "source_authority": "structured_aggregator", "terms_profile": "gateway-terms-pending@1",
                    "rights": {"automation_allowed": True, "local_storage_allowed": True, "deterministic_replay_allowed": True, "derived_use_allowed": True, "redistribution_allowed": False, "reviewed_on": "2026-07-24", "evidence_sha256": None},
                    "routes": [{"dataset": dataset, "freshness_max_stale_days": 1, "completeness": "required", "retry_max_attempts": 1, "fallback": "no_fallback", "failure_disposition": "block"} for dataset in ("trade_cal", "market_universe", "daily")],
                },
                "request": {
                    "invocation_id": "missing-credential",
                    "security_id": "security-test",
                    "security_code": "000001",
                    "requested_date": "2026-01-01",
                    "as_of_at": "2026-01-01T00:00:00+00:00",
                    "market_timezone": "Asia/Shanghai",
                    "market": "SZSE",
                    "snapshot_purpose": "workflow",
                    "datasets": ["daily"],
                    "network_authorized": False,
                    "offline": True,
                },
            }
        ),
        encoding="utf-8",
    )
    missing_credential = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "sync",
            "--data-root",
            str(data_root),
            "--job-file",
            str(job),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        env={key: value for key, value in os.environ.items() if key != "TUSHARE_TOKEN"},
        text=True,
        check=False,
    )
    missing = json.loads(missing_credential.stdout)
    assert (
        missing_credential.returncode == 2
        and missing["error"]["code"] == "CREDENTIAL_MISSING"
    )


def test_windows_cli_backup_restore_doctor_serve_history_and_secret_redaction(
    tmp_path: Path, monkeypatch
) -> None:
    repo = Path(__file__).resolve().parents[2]
    live = tmp_path / "live"
    root = _root(live)
    root.faults.record_official_filing_workflow_snapshot()
    workflow = root.research.handle(StartResearchWorkflow(research_request("operations:e2e")))
    root.close()
    secret = "secret-value-that-must-never-leak"
    monkeypatch.setenv("TUSHARE_TOKEN", secret)
    archive = tmp_path / "backup.zip"
    restored = tmp_path / "restored"

    def run(*arguments: str):
        return subprocess.run(
            [sys.executable, "-m", "trading_platform.cli", *arguments],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )

    backup = run("backup", "--data-root", str(live), "--archive", str(archive))
    assert backup.returncode == 0
    restore = run("restore", "--archive", str(archive), "--target-root", str(restored))
    assert restore.returncode == 0
    pointer = tmp_path / "config" / "active-root.json"
    switched = run(
        "switch-restored-root",
        "--restored-root",
        str(restored),
        "--pointer-file",
        str(pointer),
    )
    assert switched.returncode == 0 and pointer.is_file()
    doctor = run("doctor", "--data-root", str(restored))
    assert doctor.returncode == 0
    history = run(
        "history",
        "--data-root",
        str(restored),
        "--workflow-run-id",
        workflow.workflow_run_id,
    )
    assert history.returncode == 0
    combined = (
        backup.stdout
        + backup.stderr
        + restore.stdout
        + restore.stderr
        + doctor.stdout
        + doctor.stderr
        + history.stdout
        + history.stderr
    )
    restored_payloads = b"".join(
        path.read_bytes() for path in restored.rglob("*") if path.is_file()
    )
    assert (
        secret not in combined
        and secret.encode() not in archive.read_bytes() + restored_payloads
    )
    assert (
        json.loads(history.stdout)["result"]["workflow_run_id"]
        == workflow.workflow_run_id
    )
    inventory = run("inventory", "--repo-root", str(repo))
    assert (
        inventory.returncode == 0
        and json.loads(inventory.stdout)["result"]["status"] == "passed"
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "serve",
            "--data-root",
            str(restored),
            "--web-root",
            str(repo / "web/dist"),
            "--security-id",
            "security_yihua",
            "--snapshot-id",
            "snapshot_chart",
        ],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stdout.readline().strip()
        envelope = json.loads(line)
        assert envelope["ok"] is True
        workspace = json.loads(
            urlopen(envelope["result"]["url"] + "/api/workspace", timeout=5).read()
        )
        assert (
            workspace["task"]["snapshot_id"] == "snapshot_chart"
            and workspace["history"]["workflows"]
        )
        assert secret not in json.dumps(workspace) and secret not in line
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_windows_cli_resume_executes_recovery_and_returns_refs(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    data_root = tmp_path / "resume"
    root = recovery_root(
        data_root, CrashAt("workflow.research_checkpoint_committed")
    )
    with pytest.raises(InjectedCrash):
        root.research.handle(StartResearchWorkflow(research_request("operations:resume")))
    run_id = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT workflow_run_id FROM workflow_run LIMIT 1"
    ).fetchone()[0]
    _expire(root, run_id)
    root.close()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "resume",
            "--data-root",
            str(data_root),
            "--workflow-run-id",
            run_id,
            "--owner-token",
            "windows-cli-owner",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    envelope = json.loads(completed.stdout)
    assert completed.returncode == 0 and envelope["result"]["workflow_run_id"] == run_id
    assert envelope["result"]["final_manifest_id"].startswith("manifest_")


def test_dependency_locks_offline_assets_skill_routing_and_runtime_separation() -> None:
    repo = Path(__file__).resolve().parents[2]
    inventory = PlatformOperations.dependency_inventory(repo)

    class FakeCredentialAdapter:
        def get(self, scope: str) -> str | None:
            return "secret" if scope == "TUSHARE_TOKEN" else None

    adapter: CredentialAdapter = FakeCredentialAdapter()
    assert adapter.get("TUSHARE_TOKEN") == "secret" and adapter.get("missing") is None
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        job_path = Path(directory) / "job.json"
        job_path.write_text(
            json.dumps(
                {
                    "schema_version": "ProviderJob@2",
                    "provider": {
                        "provider_id": "tushare-compatible",
                        "adapter_version": "tushare-http@2",
                        "credential_env": "TUSHARE_TOKEN",
                    },
                    "query_policy": {"schema_version": "QueryPolicy@1", "lookback_days": 7, "market_universe_list_status": "L", "adjustment_mode": "none"},
                    "source_policy": {
                        "schema_version": "SourcePolicy@1", "provider_id": "tushare-compatible", "adapter_version": "tushare-http@2",
                        "source_identity": "preconfigured_tushare_compatible_non_official", "source_authority": "structured_aggregator", "terms_profile": "gateway-terms-pending@1",
                        "rights": {"automation_allowed": True, "local_storage_allowed": True, "deterministic_replay_allowed": True, "derived_use_allowed": True, "redistribution_allowed": False, "reviewed_on": "2026-07-24", "evidence_sha256": None},
                        "routes": [{"dataset": dataset, "freshness_max_stale_days": 1, "completeness": "required", "retry_max_attempts": 1, "fallback": "no_fallback", "failure_disposition": "block"} for dataset in ("trade_cal", "market_universe", "daily")],
                    },
                    "request": {
                        "invocation_id": "i",
                        "security_id": "s",
                        "security_code": "s",
                        "requested_date": "2026-01-01",
                        "as_of_at": "2026-01-01T00:00:00+00:00",
                        "market_timezone": "Asia/Shanghai",
                        "market": "SZSE",
                        "snapshot_purpose": "workflow",
                        "datasets": ["daily"],
                        "network_authorized": False,
                        "offline": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        loaded = load_sync_job(job_path, adapter)
        from trading_platform.data.providers import TushareCompatibleProvider

        assert isinstance(loaded.provider, TushareCompatibleProvider)
        assert loaded.provider._credential == "secret"
        doctor_root = Path(directory) / "doctor-root"
        PlatformOperations(doctor_root).bootstrap()
        readiness = PlatformOperations(doctor_root, credential_adapter=adapter).doctor(
            job_path
        )["provider_readiness"]
        assert readiness["status"] == "configured"
        assert readiness["job_schema_version"] == "ProviderJob@2"
        assert readiness["adapter_version"] == "tushare-http@2"
    assert (
        inventory["status"] == "passed"
        and inventory["python_lock_basis"]
        == "requirements.lock+requirements-build.lock"
    )
    assert all(item["integrity"] and item["license"] for item in inventory["packages"])
    web_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (repo / "web").glob("*.html")
    ) + (repo / "web/src/app.js").read_text(encoding="utf-8")
    assert (
        "https://" not in web_sources
        and "http://" not in web_sources
        and "telemetry" not in web_sources.casefold()
    )
    skill = (repo / "skills/SKILL.md").read_text(encoding="utf-8")
    for command in (
        "bootstrap",
        "doctor",
        "migrate",
        "sync",
        "daily",
        "serve",
        "test",
        "inventory",
        "backup",
        "restore",
        "switch-restored-root",
        "resume",
        "history",
    ):
        assert f"trading_platform.cli {command}" in skill
    for path in (repo / "src/trading_platform").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "skills/SKILL" not in source and "docs/prompts" not in source
