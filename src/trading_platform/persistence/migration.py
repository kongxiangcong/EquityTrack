from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
                path.name
                in {
                    "0013_source_policy_official_evidence.sql",
                    "0014_research_evaluation.sql",
                    "0015_account_snapshot_version.sql",
                }
            )
            try:
                if rebuilds_parent_tables:
                    self.connection.execute("PRAGMA foreign_keys=OFF")
                    self.connection.execute("PRAGMA legacy_alter_table=ON")
                self.connection.execute("BEGIN IMMEDIATE")
                if rebuilds_parent_tables:
                    if path.name == "0013_source_policy_official_evidence.sql":
                        self._preflight_source_policy_0013()
                    elif path.name == "0014_research_evaluation.sql":
                        self._preflight_research_evaluation_0014()
                    else:
                        self._preflight_account_snapshot_0015()
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
                            (
                                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE"
                                if path.name
                                == "0013_source_policy_official_evidence.sql"
                                else (
                                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE"
                                    if path.name == "0014_research_evaluation.sql"
                                    else "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE"
                                )
                            ),
                            f"Migration {index:04d} produced invalid foreign-key lineage.",
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

    def _preflight_account_snapshot_0015(self) -> None:
        def block(message: str) -> None:
            raise PersistenceError(
                "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE", message
            )

        invalid_account = self.connection.execute(
            "SELECT p.portfolio_snapshot_id FROM portfolio_snapshot p "
            "LEFT JOIN account a USING(account_id) "
            "WHERE a.account_id IS NULL OR length(trim(a.account_id))=0 "
            "OR length(trim(a.base_currency))<>3 LIMIT 1"
        ).fetchone()
        if invalid_account is not None:
            block("A legacy opening graph lacks stable account identity or currency.")

        missing_graph = self.connection.execute(
            "SELECT p.portfolio_snapshot_id FROM portfolio_snapshot p "
            "LEFT JOIN account_import_batch b "
            "ON b.account_id=p.account_id "
            "AND b.source_snapshot_hash=p.source_snapshot_hash "
            "LEFT JOIN account_cash_opening c USING(account_id) "
            "WHERE b.import_batch_id IS NULL OR c.account_id IS NULL LIMIT 1"
        ).fetchone()
        if missing_graph is not None:
            block("A legacy opening graph is incomplete.")

        legacy_graphs = tuple(
            self.connection.execute(
                "SELECT p.portfolio_snapshot_id,p.account_id,p.as_of_date,"
                "p.source_snapshot_hash,b.confirmed_as_of,b.evidence_json "
                "FROM portfolio_snapshot p "
                "JOIN account_import_batch b "
                "ON b.account_id=p.account_id "
                "AND b.source_snapshot_hash=p.source_snapshot_hash"
            )
        )
        for row in legacy_graphs:
            try:
                evidence = json.loads(row["evidence_json"])
                confirmation = evidence["confirmation"]
                invocation_id = confirmation["invocation_id"]
                confirmed_at = confirmation["confirmed_at"]
                confirmed_as_of = confirmation["confirmed_as_of"]
                confirmed_instant = datetime.fromisoformat(confirmed_at)
                datetime.fromisoformat(f"{row['as_of_date']}T00:00:00")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise PersistenceError(
                    "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE",
                    "A legacy opening graph lacks explicit confirmation provenance.",
                ) from error
            if (
                not invocation_id
                or confirmed_instant.tzinfo is None
                or confirmed_as_of != row["as_of_date"]
                or row["confirmed_as_of"] != row["as_of_date"]
            ):
                block(
                    "A legacy opening graph has inconsistent confirmation provenance."
                )

        positions = tuple(
            self.connection.execute(
                "SELECT p.position_id,p.account_id,p.security_id,"
                "p.quantity_decimal,p.available_decimal,p.frozen_decimal "
                "FROM account_position p "
                "LEFT JOIN security s USING(security_id)"
                " WHERE s.security_id IS NULL OR length(trim(p.security_id))=0 "
                "OR NOT EXISTS(SELECT 1 FROM portfolio_snapshot ps "
                "WHERE ps.account_id=p.account_id)"
            )
        )
        if positions:
            block("A legacy position lacks stable snapshot or security identity.")
        quantities = tuple(
            self.connection.execute(
                "SELECT position_id,quantity_decimal,available_decimal,"
                "frozen_decimal FROM account_position"
            )
        )
        for row in quantities:
            try:
                total = Decimal(row["quantity_decimal"])
                available = Decimal(row["available_decimal"])
                frozen = Decimal(row["frozen_decimal"])
            except (InvalidOperation, TypeError) as error:
                raise PersistenceError(
                    "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE",
                    "A legacy position quantity is not an exact decimal.",
                ) from error
            if (
                not all(value.is_finite() and value >= 0 for value in (total, available, frozen))
                or available + frozen != total
            ):
                block("A legacy position has an invalid quantity relation.")

        history_reference = self.connection.execute(
            "SELECT plan_version_id FROM plan_account_snapshot_reference "
            "WHERE snapshot_type<>'PortfolioSnapshot' LIMIT 1"
        ).fetchone()
        if history_reference is not None:
            block(
                "A legacy plan references broker history as current account truth."
            )

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

    def _preflight_research_evaluation_0014(self) -> None:
        from .migrations.research_evaluation_0014 import (
            decode_request_v1_for_audit,
        )

        nonterminal = self.connection.execute(
            "SELECT workflow_run_id FROM workflow_run "
            "WHERE workflow_id='research-workflow' "
            "AND status IN ('queued','running') LIMIT 1"
        ).fetchone()
        if nonterminal is not None:
            raise PersistenceError(
                "MIGRATION_WORKFLOW_NOT_TERMINAL",
                "A nonterminal legacy research workflow blocks migration 0014.",
            )
        legacy_requests = tuple(
            self.connection.execute(
                "SELECT w.workflow_run_id,r.request_hash,a.object_sha256,"
                "o.size_bytes,o.relative_path "
                "FROM workflow_run w "
                "JOIN workflow_run_request r USING(workflow_run_id) "
                "JOIN artifact a ON a.artifact_id=r.request_artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256 "
                "WHERE w.workflow_id='research-workflow' "
                "AND r.request_schema_version='ResearchWorkflowRequest@1'"
            )
        )
        for row in legacy_requests:
            path = (self.data_root / row["relative_path"]).resolve()
            try:
                path.relative_to(self.data_root.resolve())
                payload = path.read_bytes()
                audit = decode_request_v1_for_audit(payload)
            except (OSError, ValueError) as error:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy Request@1 audit identity is unavailable.",
                ) from error
            digest = hashlib.sha256(payload).hexdigest()
            if (
                len(payload) != row["size_bytes"]
                or digest != row["object_sha256"]
                or digest != row["request_hash"]
            ):
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy Request@1 failed identity verification.",
                )
            projection = self.connection.execute(
                "SELECT security_id FROM research_input_projection "
                "WHERE research_projection_id=?",
                (audit.research_projection_id,),
            ).fetchone()
            if projection is None or projection["security_id"] != audit.security_id:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy Request@1 projection identity does not match history.",
                )
        ambiguous = self.connection.execute(
            "SELECT research_projection_id FROM research_input_projection "
            "GROUP BY projection_hash HAVING count(*)<>1 LIMIT 1"
        ).fetchone()
        if ambiguous is not None:
            raise PersistenceError(
                "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                "Legacy projection identity is not unique.",
            )
        missing_artifact = self.connection.execute(
            "SELECT p.research_projection_id FROM research_input_projection p "
            "LEFT JOIN artifact a ON a.artifact_id=p.projection_artifact_id "
            "LEFT JOIN object_blob o ON o.sha256=a.object_sha256 "
            "WHERE a.artifact_id IS NULL OR o.sha256 IS NULL LIMIT 1"
        ).fetchone()
        if missing_artifact is not None:
            raise PersistenceError(
                "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                "Legacy projection audit artifact is missing.",
            )
        projection_artifacts = tuple(
            self.connection.execute(
                "SELECT p.research_projection_id,p.projection_hash,"
                "a.object_sha256,o.size_bytes,o.relative_path "
                "FROM research_input_projection p "
                "JOIN artifact a ON a.artifact_id=p.projection_artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256"
            )
        )
        for row in projection_artifacts:
            path = (self.data_root / row["relative_path"]).resolve()
            try:
                path.relative_to(self.data_root.resolve())
                payload = path.read_bytes()
            except (OSError, ValueError) as error:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy projection audit object is unavailable.",
                ) from error
            digest = hashlib.sha256(payload).hexdigest()
            if (
                len(payload) != row["size_bytes"]
                or digest != row["object_sha256"]
                or digest != row["projection_hash"]
            ):
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy projection audit object failed identity verification.",
                )
        research_artifacts = tuple(
            self.connection.execute(
                "SELECT r.research_run_id,r.engine_schema_version,"
                "a.object_sha256,o.size_bytes,o.relative_path "
                "FROM research_run_record r "
                "JOIN artifact a "
                "ON a.artifact_id=r.canonical_json_artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256"
            )
        )
        for row in research_artifacts:
            path = (self.data_root / row["relative_path"]).resolve()
            try:
                path.relative_to(self.data_root.resolve())
                payload = path.read_bytes()
                decoded = json.loads(payload)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy research artifact is missing or corrupt.",
                ) from error
            if (
                len(payload) != row["size_bytes"]
                or hashlib.sha256(payload).hexdigest()
                != row["object_sha256"]
                or not isinstance(decoded, dict)
                or decoded.get("run_id") != row["research_run_id"]
                or decoded.get("schema_version")
                != row["engine_schema_version"]
            ):
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy research artifact failed identity verification.",
                )
        incomplete_view = self.connection.execute(
            "SELECT w.workflow_run_id FROM workflow_run w "
            "LEFT JOIN workflow_run_ref r "
            "ON r.workflow_run_id=w.workflow_run_id "
            "AND r.ref_role='decision_view_manifest' "
            "LEFT JOIN artifact_manifest f "
            "ON f.artifact_manifest_id=r.ref_id "
            "WHERE w.workflow_id='research-workflow' "
            "AND w.status IN ('succeeded','succeeded_with_limits') "
            "GROUP BY w.workflow_run_id "
            "HAVING count(f.artifact_manifest_id)<>1 "
            "OR min(f.manifest_role)<>'workflow_decision_view@1' "
            "OR min(f.member_count)<>2 LIMIT 1"
        ).fetchone()
        if incomplete_view is not None:
            raise PersistenceError(
                "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                "Legacy successful workflow lacks one complete decision view.",
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
