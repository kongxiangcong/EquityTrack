from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import stat
import sqlite3
from urllib.request import urlopen
import zipfile
import warnings
from pathlib import Path

import pytest

from tests.platform.test_chart_annotations import _root
from tests.platform.test_research_workflow import _request as research_request
from tests.platform.test_research_workflow import CountingEngine
from tests.platform.test_workflow_recovery import (
    CrashAt,
    InjectedCrash,
    _expire,
    _root as recovery_root,
)
from trading_platform.operations import OperationError, PlatformOperations
from trading_platform.credentials import CredentialAdapter
from trading_platform.persistence.presence import RuntimePresence
from trading_platform.cli import _load_sync_job


def test_backup_restore_new_root_preserves_database_objects_and_history(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    root = _root(live)
    before = root.facade.get_workspace("security_yihua", "snapshot_chart")
    root.close()
    archive = tmp_path / "backups" / "platform-backup.zip"
    backup = PlatformOperations(live).backup(archive)
    assert backup["status"] == "succeeded" and archive.is_file()
    restored = tmp_path / "restored"
    report = PlatformOperations.restore(archive, restored)
    assert report["status"] == "succeeded" and report["doctor_status"] == "passed"
    rebuilt = _root(restored)
    assert (
        rebuilt.facade.get_workspace("security_yihua", "snapshot_chart")["task"]
        == before["task"]
    )
    assert rebuilt._store.objects.verify_all() == ()
    rebuilt.close()
    assert (restored / "restore-report.json").is_file()


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
    root = _root(live)
    root._store.publish_object(b"backup-object")
    root.close()
    operations = PlatformOperations(live)
    archive = tmp_path / "immutable.zip"
    operations.backup(archive)
    with pytest.raises(OperationError, match="BACKUP_TARGET_EXISTS"):
        operations.backup(archive)
    migrated = operations.migrate()
    full_backup = tmp_path / f"live-pre-migrate-v0012.zip"
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


def test_maintenance_rejects_live_workflow_and_doctor_detects_manifest_corruption(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    root = recovery_root(
        live, CountingEngine(), CrashAt("workflow.final_manifest_committed")
    )
    with pytest.raises(InjectedCrash):
        root.facade.run_research_workflow(research_request("operations:maintenance"))
    run_id = root._store.connection.execute(
        "SELECT workflow_run_id FROM workflow_run LIMIT 1"
    ).fetchone()[0]
    root._store.connection.execute(
        "UPDATE workflow_run SET status='running',completed_at=NULL,lease_expires_at='2999-01-01T00:00:00+00:00' WHERE workflow_run_id=?",
        (run_id,),
    )
    root._store.connection.commit()
    root.close()
    with pytest.raises(OperationError, match="MAINTENANCE_WORKFLOW_ACTIVE"):
        PlatformOperations(live).migrate()
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
                "provider": {
                    "provider_id": "configured",
                    "adapter_version": "1",
                    "endpoint": "https://provider.invalid",
                    "credential_env": "ISSUE10_MISSING_CREDENTIAL",
                    "source_identity": "configured-provider",
                    "terms_profile": "configured",
                },
                "request": {},
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
    workflow = root.facade.run_research_workflow(research_request("operations:e2e"))
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
        data_root, CountingEngine(), CrashAt("workflow.freeze_checkpoint_committed")
    )
    with pytest.raises(InjectedCrash):
        root.facade.run_research_workflow(research_request("operations:resume"))
    run_id = root._store.connection.execute(
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
            return "secret" if scope == "configured" else None

    adapter: CredentialAdapter = FakeCredentialAdapter()
    assert adapter.get("configured") == "secret" and adapter.get("missing") is None
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        job_path = Path(directory) / "job.json"
        job_path.write_text(
            json.dumps(
                {
                    "provider": {
                        "provider_type": "tushare_compatible",
                        "provider_id": "p",
                        "adapter_version": "1",
                        "endpoint": "https://provider.invalid",
                        "credential_env": "configured",
                        "source_identity": "scope",
                        "terms_profile": "terms",
                    },
                    "request": {
                        "invocation_id": "i",
                        "security_id": "s",
                        "provider_security_code": "s",
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
        _, provider, _ = _load_sync_job(job_path, adapter)
        from trading_platform.data.providers import TushareCompatibleProvider

        assert isinstance(provider, TushareCompatibleProvider)
        assert provider._credential == "secret"
        doctor_root = Path(directory) / "doctor-root"
        PlatformOperations(doctor_root).bootstrap()
        readiness = PlatformOperations(doctor_root, credential_adapter=adapter).doctor(
            job_path
        )["provider_readiness"]
        assert readiness["status"] == "configured"
        assert readiness["provider_type"] == "tushare_compatible"
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
