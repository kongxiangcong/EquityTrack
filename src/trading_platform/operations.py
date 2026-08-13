from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from trading_platform.persistence import PlatformStore
from trading_platform.persistence.locking import DataRootWriterLock
from trading_platform.persistence.presence import assert_maintenance_available
from trading_platform.persistence.workflow_ledger import WorkflowLedger
from trading_platform.application.workflow_ledger import (
    NonterminalWorkflowQuery,
    ObjectInventoryQuery,
    PersistenceCountsQuery,
)
from trading_platform.credentials import CredentialAdapter, LocalCredentialAdapter
from trading_platform.account_import import personal_source_privacy_errors


class OperationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        substep: str | None = None,
        cause_type: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.substep = substep
        self.cause_type = cause_type


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_no_reparse_components(path: Path) -> None:
    candidate = path.absolute()
    for component in (candidate, *candidate.parents):
        if not component.exists(): continue
        metadata = os.lstat(component)
        if stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400):
            raise OperationError("REPARSE_POINT_FORBIDDEN", "Operation paths cannot traverse links or reparse points.")


class PlatformOperations:
    SCHEMA = "PlatformBackup@1"
    MAX_FILES = 100_000
    MAX_FILE_SIZE = 128 * 1024 * 1024
    MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024

    def __init__(self, data_root: Path, migrations_root: Path | None = None, credential_adapter: CredentialAdapter | None = None) -> None:
        self.data_root = data_root.resolve()
        self.repo_root = Path(__file__).resolve().parents[2]
        self.migrations_root = (migrations_root or self.repo_root / "migrations").resolve()
        self.credential_adapter = credential_adapter or LocalCredentialAdapter()

    def bootstrap(self) -> dict[str, Any]:
        if (self.data_root / "platform.sqlite3").is_file():
            return self.migrate()
        self.data_root.mkdir(parents=True, exist_ok=True)
        with DataRootWriterLock(self.data_root).acquire("maintenance:bootstrap"):
            assert_maintenance_available(self.data_root); self._assert_no_live_workflow()
            store = PlatformStore(self.data_root, self.migrations_root)
            try:
                store.migrations.migrate(acquire_lock=False)
                report = store.doctor()
                return {"status": report.status, "data_root_scope": hashlib.sha256(str(self.data_root).encode()).hexdigest(), "checks": report.checks, "errors": report.errors}
            finally: store.close()

    def doctor(self, job_file: Path | None = None) -> dict[str, Any]:
        store = PlatformStore(self.data_root, self.migrations_root)
        try:
            report = store.doctor()
            scopes = []
            for variable in ("KIMI_API_KEY",):
                value = self.credential_adapter.get(variable)
                scopes.append({"credential_scope": hashlib.sha256(variable.encode()).hexdigest(), "status": "configured" if value else "missing"})
            identity_files = [Path(__file__).resolve().parents[2] / "pyproject.toml", Path(__file__).resolve().parents[2] / "web/package-lock.json", *sorted(self.migrations_root.glob("*.sql"))]
            build_identity = hashlib.sha256("".join(_sha256(path) for path in identity_files if path.is_file()).encode()).hexdigest()
            warnings = ["SENSITIVE_BACKUP_ENCRYPTION_NOT_VERIFIED"] if os.name == "nt" else []
            lock_state = {name: (self.data_root / name).exists() for name in (".writer.lock", ".server.presence", ".workflow.presence")}
            provider_readiness: Any = {"status": "not_configured"}
            if job_file is not None:
                from trading_platform.provider_config import decode_sync_job

                decoded = decode_sync_job(job_file)
                credential_configured = bool(
                    self.credential_adapter.get(decoded.credential_variable)
                )
                provider_readiness = {
                    "status": "configured" if credential_configured else "missing_credential",
                    "job_schema_version": decoded.job.schema_version,
                    "adapter_version": decoded.source_policy.adapter_version,
                    "source_policy_identity": decoded.source_policy.identity,
                    "provider_scope": hashlib.sha256(decoded.provider_id.encode()).hexdigest(),
                    "credential_scope": hashlib.sha256(decoded.credential_variable.encode()).hexdigest(),
                }
            privacy_errors = self._privacy_source_errors(self.repo_root)
            errors = tuple(report.errors) + privacy_errors
            return {"status": "failed" if errors else report.status, "checks": report.checks + ("personal_source_privacy",), "errors": errors, "warnings": warnings, "lock_state": lock_state, "provider_readiness": provider_readiness, "python_version": sys.version.split()[0], "sqlite_version": sqlite3.sqlite_version, "build_identity": build_identity, "credentials": scopes}
        finally:
            store.close()

    @staticmethod
    def _privacy_source_errors(repo_root: Path) -> tuple[str, ...]:
        return personal_source_privacy_errors(repo_root, (path for path in repo_root.rglob("*.xls") if ".git" not in path.parts))

    def migrate(self) -> dict[str, Any]:
        database = self.data_root / "platform.sqlite3"
        if database.is_file():
            self._assert_no_live_workflow(migration=True)
            connection = sqlite3.connect(database)
            try:
                has_ledger = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'").fetchone()
                version = connection.execute("SELECT coalesce(max(version),0) FROM schema_migration").fetchone()[0] if has_ledger else 0
            finally: connection.close()
            backup = self.data_root.parent / f"{self.data_root.name}-pre-migrate-v{version:04d}.zip"
            if backup.exists(): backup = backup.with_name(f"{backup.stem}-{uuid.uuid4().hex[:8]}.zip")
            if has_ledger: self.backup(backup)
            else: self._backup_uninitialized_database(database, backup)
        with DataRootWriterLock(self.data_root).acquire("maintenance:migrate"):
            assert_maintenance_available(self.data_root); self._assert_no_live_workflow(migration=True)
            store = PlatformStore(self.data_root, self.migrations_root)
            try:
                store.migrations.migrate(acquire_lock=False)
                report = store.doctor()
                return {"status": report.status, "errors": report.errors, "backup_ref": backup.name if database.is_file() else None}
            finally: store.close()

    def _backup_uninitialized_database(self, database: Path, archive: Path) -> None:
        payload = database.read_bytes()
        manifest = {"schema_version": self.SCHEMA, "app_version": "platform-skeleton@1", "database_schema_version": 0, "journal_mode": "uninitialized", "configuration_schema_version": "local-env-scopes@1", "created_at": datetime.now(timezone.utc).isoformat(), "source_scope": hashlib.sha256(str(self.data_root).encode()).hexdigest(), "files": [{"path": "platform.sqlite3", "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}]}
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("backup-manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":"))); bundle.writestr("platform.sqlite3", payload)
        archive.chmod(stat.S_IREAD)

    def _assert_no_live_workflow(self, *, migration: bool = False) -> None:
        database = self.data_root / "platform.sqlite3"
        if not database.is_file(): return
        connection = sqlite3.connect(database)
        try:
            connection.row_factory = sqlite3.Row
            ledger = WorkflowLedger(
                connection, self.data_root, DataRootWriterLock(self.data_root)
            )
            if ledger.load(NonterminalWorkflowQuery()):
                code = (
                    "MIGRATION_WORKFLOW_NOT_TERMINAL"
                    if migration
                    else "MAINTENANCE_WORKFLOW_ACTIVE"
                )
                raise OperationError(code, "A nonterminal workflow blocks maintenance.")
        finally: connection.close()

    @classmethod
    def _validate_backup_archive(cls, archive: Path) -> None:
        try:
            with zipfile.ZipFile(archive) as bundle:
                if bundle.testzip() is not None: raise OperationError("MIGRATION_BACKUP_INVALID", "Existing full backup failed CRC validation.")
                manifest = json.loads(bundle.read("backup-manifest.json"))
                if manifest.get("schema_version") != cls.SCHEMA: raise OperationError("MIGRATION_BACKUP_INVALID", "Existing full backup has an unsupported schema.")
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error: raise OperationError("MIGRATION_BACKUP_INVALID", "Existing full backup is invalid.") from error

    @staticmethod
    def dependency_inventory(repo_root: Path) -> dict[str, Any]:
        repo_root = repo_root.resolve()
        required = (
            repo_root / "pyproject.toml",
            repo_root / "requirements.lock",
            repo_root / "requirements-build.lock",
            repo_root / "THIRD_PARTY_NOTICES.md",
            repo_root / "web/package-lock.json",
            repo_root / "web/THIRD_PARTY_NOTICES.md",
            repo_root / "web/dist/THIRD_PARTY_NOTICES.md",
            repo_root / "web/index.html",
        )
        missing = [path.relative_to(repo_root).as_posix() for path in required if not path.is_file()]
        if missing: raise OperationError("DEPENDENCY_INVENTORY_INCOMPLETE", ",".join(missing))
        package_lock = json.loads((repo_root / "web/package-lock.json").read_text(encoding="utf-8"))
        packages = []
        for name, metadata in sorted(package_lock.get("packages", {}).items()):
            if not name: continue
            packages.append({"path": name, "version": metadata.get("version"), "integrity": metadata.get("integrity"), "license": metadata.get("license")})
        if any(not item["integrity"] or not item["license"] for item in packages): raise OperationError("DEPENDENCY_METADATA_INCOMPLETE", "Every npm package requires integrity and license metadata.")
        if "THIRD_PARTY_NOTICES.md" not in (repo_root / "web/index.html").read_text(encoding="utf-8"): raise OperationError("PAGE_ATTRIBUTION_MISSING", "Workspace must link the dependency notice.")
        files = {path.relative_to(repo_root).as_posix(): _sha256(path) for path in required}
        return {"status": "passed", "python_lock_basis": "requirements.lock+requirements-build.lock", "npm_lock_version": package_lock.get("lockfileVersion"), "packages": packages, "files": files, "offline_install": "automatic_install_disabled"}

    @classmethod
    def switch_restored_root(cls, restored_root: Path, pointer_file: Path, migrations_root: Path | None = None) -> dict[str, Any]:
        restored_root = restored_root.resolve(); pointer_file = pointer_file.resolve()
        if pointer_file == restored_root or restored_root in pointer_file.parents: raise OperationError("ACTIVE_POINTER_INSIDE_DATA_ROOT", "Active-root pointer must remain outside the restored root.")
        with DataRootWriterLock(restored_root).acquire("maintenance:restore-switch-root"):
            assert_maintenance_available(restored_root); cls(restored_root, migrations_root)._assert_no_live_workflow()
            report_path = restored_root / "restore-report.json"
            if not report_path.is_file(): raise OperationError("RESTORE_REPORT_MISSING", "Only a validated restored root may be switched active.")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("status") != "succeeded": raise OperationError("RESTORE_REPORT_INVALID", "Restore report is not successful.")
            doctor = cls(restored_root, migrations_root).doctor()
            if doctor["status"] != "passed": raise OperationError("RESTORE_DOCTOR_FAILED", ",".join(doctor["errors"]))
            pointer_file.parent.mkdir(parents=True, exist_ok=True)
            with DataRootWriterLock(pointer_file.parent).acquire("maintenance:restore-switch"):
                temporary = pointer_file.with_name(f".{pointer_file.name}.{os.getpid()}.tmp")
                try:
                    temporary.write_text(json.dumps({"schema_version": "ActiveDataRoot@1", "data_root": str(restored_root)}, sort_keys=True), encoding="utf-8")
                    os.replace(temporary, pointer_file)
                finally: temporary.unlink(missing_ok=True)
        return {"status": "succeeded", "active_root_scope": hashlib.sha256(str(restored_root).encode()).hexdigest(), "pointer_ref": pointer_file.name}

    def backup(self, archive: Path) -> dict[str, Any]:
        _assert_no_reparse_components(Path(archive).parent)
        archive = archive.resolve()
        if archive == self.data_root or self.data_root in archive.parents:
            raise OperationError("BACKUP_TARGET_INSIDE_LIVE_ROOT", "Backup target must be outside the live data root.")
        if archive.exists():
            raise OperationError("BACKUP_TARGET_EXISTS", "Backup archives are immutable and cannot be overwritten.")
        database = self.data_root / "platform.sqlite3"
        if not database.is_file():
            raise OperationError("DATA_ROOT_NOT_INITIALIZED", "platform.sqlite3 is missing.")
        assert_maintenance_available(self.data_root)
        archive.parent.mkdir(parents=True, exist_ok=True)
        lock = DataRootWriterLock(self.data_root)
        with lock.acquire("maintenance:backup"):
            with tempfile.TemporaryDirectory(prefix="platform-backup-", dir=archive.parent) as temporary:
                staging = Path(temporary)
                frozen = staging / "platform.sqlite3"
                source = sqlite3.connect(database); target = sqlite3.connect(frozen)
                try:
                    source.backup(target)
                finally:
                    target.close(); source.close()
                connection = sqlite3.connect(frozen); connection.row_factory = sqlite3.Row
                try:
                    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or tuple(connection.execute("PRAGMA foreign_key_check")):
                        raise OperationError("BACKUP_DATABASE_INVALID", "Frozen SQLite validation failed.")
                    objects = WorkflowLedger(connection, self.data_root, lock).load(ObjectInventoryQuery())
                    schema_version = connection.execute("SELECT coalesce(max(version),0) FROM schema_migration").fetchone()[0]
                finally:
                    connection.close()
                files = [frozen]
                relative_paths = ["platform.sqlite3"]
                for row in objects:
                    relative = PurePosixPath(row.relative_path)
                    if relative.is_absolute() or any(part in {"", ".", ".."} or ":" in part for part in relative.parts): raise OperationError("BACKUP_OBJECT_PATH_INVALID", str(row.sha256))
                    path = self.data_root.joinpath(*relative.parts).resolve()
                    if self.data_root not in path.parents: raise OperationError("BACKUP_OBJECT_PATH_INVALID", str(row.sha256))
                    expected_relative = f"objects/sha256/{row.sha256[:2]}/{row.sha256}"
                    if relative.as_posix() != expected_relative: raise OperationError("BACKUP_OBJECT_PATH_HASH_MISMATCH", str(row.sha256))
                    if not path.is_file() or path.stat().st_size != row.size_bytes or _sha256(path) != row.sha256:
                        raise OperationError("BACKUP_OBJECT_INVALID", str(row.sha256))
                    files.append(path); relative_paths.append(relative.as_posix())
                entries = [{"path": relative, "sha256": _sha256(path), "size": path.stat().st_size} for path, relative in zip(files, relative_paths)]
                manifest = {"schema_version": self.SCHEMA, "app_version": "platform-skeleton@1", "database_schema_version": schema_version, "journal_mode": "delete", "configuration_schema_version": "local-env-scopes@1", "created_at": datetime.now(timezone.utc).isoformat(), "source_scope": hashlib.sha256(str(self.data_root).encode()).hexdigest(), "files": entries}
                temporary_archive = archive.with_name(f".{archive.name}.{os.getpid()}.tmp")
                try:
                    with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
                        bundle.writestr("backup-manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")))
                        for path, relative in zip(files, relative_paths): bundle.write(path, relative)
                    os.replace(temporary_archive, archive)
                    archive.chmod(stat.S_IREAD)
                finally:
                    temporary_archive.unlink(missing_ok=True)
        return {"status": "succeeded", "archive_ref": archive.name, "archive_sha256": _sha256(archive), "file_count": len(entries)}

    @classmethod
    def restore(cls, archive: Path, target_root: Path, migrations_root: Path | None = None) -> dict[str, Any]:
        _assert_no_reparse_components(Path(archive)); _assert_no_reparse_components(Path(target_root).parent)
        archive = archive.resolve(); target_root = target_root.resolve()
        if not archive.is_file(): raise OperationError("BACKUP_NOT_FOUND", "Backup archive does not exist.")
        if target_root.exists(): raise OperationError("RESTORE_TARGET_EXISTS", "Restore target must be a new root.")
        parent = target_root.parent; parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f".{target_root.name}.restore-{os.getpid()}"
        if temporary.exists(): raise OperationError("RESTORE_STAGING_EXISTS", "Restore staging path already exists.")
        with DataRootWriterLock(parent).acquire(f"maintenance:restore:{target_root.name}"):
            return cls._restore_locked(archive, target_root, temporary, migrations_root)

    @classmethod
    def _restore_locked(cls, archive: Path, target_root: Path, temporary: Path, migrations_root: Path | None) -> dict[str, Any]:
        temporary.mkdir()
        try:
            with zipfile.ZipFile(archive) as bundle:
                infos = bundle.infolist()
                if len(infos) > cls.MAX_FILES: raise OperationError("RESTORE_FILE_COUNT_LIMIT", "Bundle contains too many files.")
                names = [info.filename for info in infos]
                if len(names) != len(set(names)): raise OperationError("RESTORE_DUPLICATE_PATH", "Bundle has duplicate paths.")
                for info in infos: cls._validate_member(info)
                try: manifest = json.loads(bundle.read("backup-manifest.json"))
                except (KeyError, json.JSONDecodeError) as error: raise OperationError("RESTORE_MANIFEST_INVALID", "Manifest missing or invalid.") from error
                if manifest.get("schema_version") != cls.SCHEMA: raise OperationError("RESTORE_SCHEMA_UNSUPPORTED", "Backup schema is unsupported.")
                for field in ("app_version", "database_schema_version", "journal_mode", "configuration_schema_version"):
                    if field not in manifest: raise OperationError("RESTORE_MANIFEST_INVALID", f"Manifest field missing: {field}")
                file_entries = manifest.get("files", [])
                if not isinstance(file_entries, list) or any(not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"} for entry in file_entries): raise OperationError("RESTORE_MANIFEST_INVALID", "Manifest file entries are invalid.")
                manifest_paths = [entry["path"] for entry in file_entries]
                if len(manifest_paths) != len(set(manifest_paths)): raise OperationError("RESTORE_DUPLICATE_PATH", "Manifest has duplicate paths.")
                expected = {entry["path"]: entry for entry in file_entries}
                actual = set(names) - {"backup-manifest.json"}
                if set(expected) != actual or "platform.sqlite3" not in expected: raise OperationError("RESTORE_MANIFEST_MISMATCH", "Manifest and bundle paths differ.")
                for name in actual - {"platform.sqlite3"}:
                    parts = PurePosixPath(name).parts
                    if len(parts) != 4 or parts[:2] != ("objects", "sha256") or len(parts[2]) != 2 or len(parts[3]) != 64 or parts[2] != parts[3][:2] or any(character not in "0123456789abcdef" for character in parts[3]): raise OperationError("RESTORE_OBJECT_PATH_INVALID", name)
                total = 0
                for name, entry in expected.items():
                    info = bundle.getinfo(name); total += info.file_size
                    if total > cls.MAX_TOTAL_SIZE: raise OperationError("RESTORE_TOTAL_SIZE_LIMIT", "Bundle is too large.")
                    destination = temporary.joinpath(*PurePosixPath(name).parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256(); written = 0
                    with bundle.open(info) as source, destination.open("xb") as output:
                        while block := source.read(1024 * 1024):
                            written += len(block)
                            if written > cls.MAX_FILE_SIZE: raise OperationError("RESTORE_FILE_SIZE_LIMIT", name)
                            digest.update(block); output.write(block)
                    if written != entry.get("size") or digest.hexdigest() != entry.get("sha256"): raise OperationError("RESTORE_HASH_MISMATCH", name)
            operations = cls(temporary, migrations_root)
            restored_database = sqlite3.connect(temporary / "platform.sqlite3"); restored_database.row_factory = sqlite3.Row
            try:
                schema_version = restored_database.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
                journal_mode = restored_database.execute("PRAGMA journal_mode").fetchone()[0]
                restored_ledger = WorkflowLedger(restored_database, temporary, DataRootWriterLock(temporary))
                object_rows = restored_ledger.load(ObjectInventoryQuery())
            finally: restored_database.close()
            if manifest["app_version"] != "platform-skeleton@1" or manifest["configuration_schema_version"] != "local-env-scopes@1" or manifest["database_schema_version"] != schema_version or manifest["journal_mode"] != journal_mode:
                raise OperationError("RESTORE_METADATA_MISMATCH", "Manifest metadata differs from the restored runtime/database.")
            database_objects = {row.relative_path: {"sha256": row.sha256, "size": row.size_bytes} for row in object_rows}
            manifest_objects = {name: {"sha256": entry["sha256"], "size": entry["size"]} for name, entry in expected.items() if name != "platform.sqlite3"}
            if database_objects != manifest_objects: raise OperationError("RESTORE_OBJECT_GRAPH_MISMATCH", "Bundle objects do not exactly match object_blob references.")
            report = operations.doctor()
            if report["status"] != "passed": raise OperationError("RESTORE_DOCTOR_FAILED", ",".join(report["errors"]))
            database = sqlite3.connect(temporary / "platform.sqlite3")
            try:
                counts = WorkflowLedger(database, temporary, DataRootWriterLock(temporary)).load(PersistenceCountsQuery())
                minimum_query = {"schema_version": database.execute("SELECT max(version) FROM schema_migration").fetchone()[0], "security_count": database.execute("SELECT count(*) FROM security").fetchone()[0], **counts}
            finally: database.close()
            restored_files = [{"path": name, "sha256": entry["sha256"], "size": entry["size"], "status": "verified"} for name, entry in sorted(expected.items())]
            validations = [{"check": "archive_paths_and_types", "status": "passed"}, {"check": "item_hashes_and_sizes", "status": "passed", "items": restored_files}, {"check": "sqlite_integrity_fk_journal_schema", "status": "passed"}, {"check": "domain_objects_manifests_workflow_refs", "status": "passed"}, {"check": "minimum_public_query", "status": "passed", "result": minimum_query}]
            restore_report = {"schema_version": "RestoreReport@1", "status": "succeeded", "archive_sha256": _sha256(archive), "doctor_status": report["status"], "backup_schema_version": manifest["schema_version"], "database_schema_version": manifest["database_schema_version"], "validations": validations, "restored_at": datetime.now(timezone.utc).isoformat()}
            report_path = temporary / "restore-report.json"; report_path.write_text(json.dumps(restore_report, sort_keys=True), encoding="utf-8"); report_path.chmod(stat.S_IREAD)
            os.replace(temporary, target_root)
            return restore_report
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @classmethod
    def _validate_member(cls, info: zipfile.ZipInfo) -> None:
        name = info.filename
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if not name or "\\" in name or path.is_absolute() or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
            raise OperationError("RESTORE_PATH_INVALID", name)
        if stat.S_ISLNK(mode) or (file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))): raise OperationError("RESTORE_LINK_FORBIDDEN", name)
        if info.file_size > cls.MAX_FILE_SIZE: raise OperationError("RESTORE_FILE_SIZE_LIMIT", name)
        if info.compress_size and info.file_size / info.compress_size > 200: raise OperationError("RESTORE_COMPRESSION_BOMB", name)
