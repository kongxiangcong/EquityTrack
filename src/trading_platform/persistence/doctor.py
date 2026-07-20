from __future__ import annotations

import sqlite3
import sys

from trading_platform.application.contracts import DoctorReport

from .migration import MigrationRunner
from .locking import PersistenceError
from .workflow_ledger import IntegrityScope, WorkflowLedger


class DoctorService:
    REQUIRED_TABLES = {"security", "security_identifier", "watchlist", "watchlist_item", "object_blob", "artifact", "artifact_relation", "command_receipt"}

    def __init__(self, connection: sqlite3.Connection, migrations: MigrationRunner, workflow_ledger: WorkflowLedger) -> None:
        self.connection = connection
        self.migrations = migrations
        self.workflow_ledger = workflow_ledger

    def run(self) -> DoctorReport:
        errors: list[str] = []
        checks = ("runtime_identity", "sqlite_journal", "migration_ledger", "sqlite_integrity", "foreign_keys", "domain_invariants", "object_integrity", "artifact_manifests", "workflow_history", "references")
        if sys.version_info < (3, 10) or sqlite3.sqlite_version_info < (3, 35):
            errors.append("RUNTIME_UNSUPPORTED")
        if self.connection.execute("PRAGMA journal_mode").fetchone()[0].casefold() != "delete": errors.append("SQLITE_JOURNAL_INVALID")
        if self.connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1: errors.append("FOREIGN_KEYS_DISABLED")
        if self.connection.execute("PRAGMA synchronous").fetchone()[0] != 2: errors.append("SQLITE_SYNCHRONOUS_INVALID")
        try:
            files, applied = self.migrations.validate()
            if len(files) != len(applied): errors.append("MIGRATION_PENDING")
        except PersistenceError as error:
            errors.append(error.code)
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok": errors.append("SQLITE_INTEGRITY_FAILED")
        if tuple(self.connection.execute("PRAGMA foreign_key_check")): errors.append("FOREIGN_KEY_FAILED")
        tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not self.REQUIRED_TABLES.issubset(tables): errors.append("SCHEMA_REQUIRED_TABLE_MISSING")
        duplicate_active = self.connection.execute("SELECT security_id FROM security_identifier WHERE valid_to IS NULL GROUP BY market,code HAVING count(*) > 1").fetchone()
        if duplicate_active: errors.append("DOMAIN_IDENTIFIER_CONFLICT")
        bad_artifact = self.connection.execute("SELECT a.artifact_id FROM artifact a LEFT JOIN object_blob o ON o.sha256=a.object_sha256 WHERE o.sha256 IS NULL LIMIT 1").fetchone()
        bad_relation = self.connection.execute("SELECT r.artifact_id FROM artifact_relation r LEFT JOIN artifact a USING(artifact_id) WHERE a.artifact_id IS NULL LIMIT 1").fetchone()
        if bad_artifact or bad_relation: errors.append("REFERENCE_MISSING")
        target_tables = {"Security": ("security", "security_id"), "WatchlistItem": ("watchlist_item", "watchlist_item_id"), "ObjectBlob": ("object_blob", "sha256")}
        for relation in self.connection.execute("SELECT target_type,target_id FROM artifact_relation"):
            target = target_tables.get(relation["target_type"])
            if target is None:
                errors.append("REFERENCE_TARGET_TYPE_INVALID")
                continue
            table, column = target
            if self.connection.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (relation["target_id"],)).fetchone() is None:
                errors.append("REFERENCE_MISSING")
        errors.extend(self.workflow_ledger.audit_integrity(IntegrityScope()).errors)
        if "plan_evaluation" in tables:
            if self.connection.execute("SELECT e.plan_evaluation_id FROM plan_evaluation e LEFT JOIN plan_rule_evaluation r USING(plan_evaluation_id) GROUP BY e.plan_evaluation_id HAVING count(r.rule_order)!=e.rule_count LIMIT 1").fetchone(): errors.append("PLAN_EVALUATION_INCOMPLETE")
        if "trade_plan_version" in tables and self.connection.execute("SELECT 1 FROM trade_plan_version WHERE user_input_source!='user_fixture_input' LIMIT 1").fetchone(): errors.append("PLAN_INPUT_SOURCE_INVALID")
        if "chart_annotation_version" in tables and self.connection.execute("SELECT v.annotation_version_id FROM chart_annotation_version v LEFT JOIN chart_annotation_anchor a USING(annotation_version_id) WHERE v.status='active' GROUP BY v.annotation_version_id HAVING count(a.anchor_no)=0 LIMIT 1").fetchone(): errors.append("ANNOTATION_ANCHOR_MISSING")
        return DoctorReport("passed" if not errors else "failed", checks, tuple(sorted(set(errors))))
