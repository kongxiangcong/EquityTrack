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
        self.connection.create_function(
            "canonical_sha256",
            1,
            lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest(),
            deterministic=True,
        )
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

    def migrate(self, fail_after_statement: int | None = None, acquire_lock: bool = True) -> None:
        if acquire_lock:
            with self.writer_lock.acquire("maintenance:migrate"):
                self._migrate_locked(fail_after_statement)
        else:
            self._migrate_locked(fail_after_statement)

    def _migrate_locked(self, fail_after_statement: int | None) -> None:
        files, applied = self.validate()
        pending = [(index, path) for index, path in enumerate(files, start=1) if index not in applied]
        if applied and pending:
            self._backup_and_verify(max(applied))
        for index, path in pending:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rebuilds_parent_tables = (
                path.name == "0013_source_policy_official_evidence.sql"
            )
            try:
                if rebuilds_parent_tables:
                    self.connection.execute("PRAGMA foreign_keys=OFF")
                    self.connection.execute("PRAGMA legacy_alter_table=ON")
                self.connection.execute("BEGIN IMMEDIATE")
                if rebuilds_parent_tables:
                    self._preflight_source_policy_0013()
                statements = self._statements(path.read_text(encoding="utf-8"))
                for statement_number, statement in enumerate(statements, start=1):
                    self.connection.execute(statement)
                    if fail_after_statement == statement_number:
                        raise PersistenceError("MIGRATION_INJECTED_FAILURE", "Injected inside migration transaction.")
                if rebuilds_parent_tables:
                    violations = self.connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if violations:
                        raise PersistenceError(
                            "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                            "Migration 0013 produced invalid foreign-key lineage.",
                        )
                self.connection.execute(
                    "INSERT INTO schema_migration VALUES(?,?,?,?,?)",
                    (index, path.name, digest, datetime.now(timezone.utc).isoformat(), "platform-skeleton@1"),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            finally:
                if rebuilds_parent_tables:
                    self.connection.execute("PRAGMA legacy_alter_table=OFF")
                    self.connection.execute("PRAGMA foreign_keys=ON")

    def _preflight_source_policy_0013(self) -> None:
        placeholder_policy = self.connection.execute(
            """
            SELECT data_snapshot_id
            FROM data_snapshot
            WHERE query_policy_version NOT LIKE 'query_policy_%'
               OR source_policy_version NOT LIKE 'source_policy_%'
            LIMIT 1
            """
        ).fetchone()
        if placeholder_policy is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy snapshot contains a placeholder policy identity.",
            )

        empty_snapshot = self.connection.execute(
            """
            SELECT s.data_snapshot_id
            FROM data_snapshot s
            LEFT JOIN data_snapshot_member m
              ON m.data_snapshot_id=s.data_snapshot_id
            GROUP BY s.data_snapshot_id
            HAVING count(m.normalized_version_id)=0
            LIMIT 1
            """
        ).fetchone()
        if empty_snapshot is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy data snapshot has no member attempts from which to prove policy identity.",
            )

        ambiguous = self.connection.execute(
            """
            SELECT v.source_attempt_id
            FROM normalized_version v
            JOIN data_snapshot_member m
              ON m.normalized_version_id=v.normalized_version_id
            JOIN data_snapshot s ON s.data_snapshot_id=m.data_snapshot_id
            GROUP BY v.source_attempt_id
            HAVING count(
              DISTINCT s.query_policy_version || char(0)
                || s.source_policy_version
            ) > 1
            LIMIT 1
            """
        ).fetchone()
        if ambiguous is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy provider attempt belongs to snapshots with conflicting policy identities.",
            )

        orphan_attempt = self.connection.execute(
            """
            SELECT p.attempt_id
            FROM provider_attempt p
            LEFT JOIN normalized_version v
              ON v.source_attempt_id=p.attempt_id
            LEFT JOIN data_snapshot_member m
              ON m.normalized_version_id=v.normalized_version_id
            WHERE m.data_snapshot_id IS NULL
            LIMIT 1
            """
        ).fetchone()
        if orphan_attempt is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy provider attempt has no snapshot policy identity.",
            )

        missing_rights = self.connection.execute(
            """
            SELECT p.attempt_id
            FROM provider_attempt p
            LEFT JOIN fixture_rights_profile f
              ON f.fixture_member_id=p.provider_id || ':' || p.dataset
             AND f.source_identity=p.source_identity
            WHERE p.source_authority='fixture'
              AND f.fixture_member_id IS NULL
            LIMIT 1
            """
        ).fetchone()
        if missing_rights is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy fixture provider attempt has no provable rights profile.",
            )

        unproved_source_rights = self.connection.execute(
            """
            SELECT attempt_id
            FROM provider_attempt
            WHERE source_authority<>'fixture'
            LIMIT 1
            """
        ).fetchone()
        if unproved_source_rights is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy non-fixture provider attempt has no persisted rights evidence.",
            )

    @staticmethod
    def _statements(script: str) -> tuple[str, ...]:
        statements: list[str] = []
        buffer = ""
        for character in script:
            buffer += character
            if character == ";" and sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                if statement:
                    statements.append(statement)
                buffer = ""
        if buffer.strip():
            if sqlite3.complete_statement(buffer + ";"):
                statements.append(buffer.strip())
            else:
                raise PersistenceError("MIGRATION_SQL_INCOMPLETE", "Migration contains an incomplete SQL statement.")
        return tuple(statements)

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
