from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .locking import DataRootWriterLock, PersistenceError


class MigrationRunner:
    def __init__(self, connection: sqlite3.Connection, data_root: Path, migrations_root: Path, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.data_root = data_root
        self.migrations_root = migrations_root
        self.writer_lock = writer_lock
        self.connection.execute("CREATE TABLE IF NOT EXISTS schema_migration(version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL, app_version TEXT NOT NULL)")
        self.connection.commit()

    def validate(self) -> tuple[list[Path], dict[int, sqlite3.Row]]:
        files = sorted(self.migrations_root.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        applied = {row["version"]: row for row in self.connection.execute("SELECT * FROM schema_migration ORDER BY version")}
        if applied and max(applied) > len(files):
            raise PersistenceError("MIGRATION_FUTURE_VERSION", "Database has an unknown future migration.")
        if sorted(applied) != list(range(1, len(applied) + 1)):
            raise PersistenceError("MIGRATION_HALF_UPGRADED", "Migration ledger is not contiguous.")
        for index, path in enumerate(files, start=1):
            if not path.name.startswith(f"{index:04d}_"):
                raise PersistenceError("MIGRATION_SEQUENCE_INVALID", "Migration sequence is not contiguous.")
            row = applied.get(index)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if row and (row["name"] != path.name or row["sha256"] != digest):
                raise PersistenceError("MIGRATION_HASH_DRIFT", f"Migration {index} differs from its ledger entry.")
        return files, applied

    def migrate(self, fail_after_statement: int | None = None) -> None:
        with self.writer_lock.acquire("maintenance:migrate"):
            files, applied = self.validate()
            pending = [(index, path) for index, path in enumerate(files, start=1) if index not in applied]
            if applied and pending:
                self._backup_and_verify(max(applied))
            for index, path in pending:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                try:
                    self.connection.execute("BEGIN IMMEDIATE")
                    statements = (item.strip() for item in path.read_text(encoding="utf-8").split(";") if item.strip())
                    for statement_number, statement in enumerate(statements, start=1):
                        self.connection.execute(statement)
                        if fail_after_statement == statement_number:
                            raise PersistenceError("MIGRATION_INJECTED_FAILURE", "Injected inside migration transaction.")
                    self.connection.execute(
                        "INSERT INTO schema_migration VALUES(?,?,?,?,?)",
                        (index, path.name, digest, datetime.now(timezone.utc).isoformat(), "platform-skeleton@1"),
                    )
                    self.connection.commit()
                except Exception:
                    self.connection.rollback()
                    raise

    def _backup_and_verify(self, version: int) -> Path:
        final = self.data_root / f"migration-backup-v{version:04d}.sqlite3"
        if final.exists():
            existing = sqlite3.connect(final)
            try:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise PersistenceError("MIGRATION_BACKUP_INVALID", "Existing migration backup failed integrity verification.")
                backed_up_version = existing.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
                if backed_up_version != version:
                    raise PersistenceError("MIGRATION_BACKUP_INVALID", "Existing migration backup has the wrong schema version.")
            except sqlite3.DatabaseError as error:
                raise PersistenceError("MIGRATION_BACKUP_INVALID", "Existing migration backup is unreadable.") from error
            finally:
                existing.close()
            return final
        descriptor, temp_name = tempfile.mkstemp(prefix=".migration-backup-", suffix=".sqlite3", dir=self.data_root)
        os.close(descriptor)
        temp = Path(temp_name)
        target = sqlite3.connect(temp)
        try:
            self.connection.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PersistenceError("MIGRATION_BACKUP_INVALID", "Migration backup failed integrity verification.")
        finally:
            target.close()
        os.replace(temp, final)
        return final
