from __future__ import annotations

from pathlib import Path
import json
import os

import pytest

from trading_platform import ProductionCompositionRoot
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.application.contracts import Capability, CapabilityStatus, HealthQuery
from trading_platform.persistence.runtime import PersistenceError, PlatformStore
from trading_platform.application.workflow_ledger import GenericObjectCommit


ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_watchlist_replay_restart_and_doctor(tmp_path: Path) -> None:
    app = ProductionCompositionRoot(tmp_path)
    assert app.facade.query_health(HealthQuery()).capabilities[Capability.PERSISTENCE] is CapabilityStatus.AVAILABLE
    security = SecurityIdentity("security_yihua_a", "SZSE", "002897", "CNY", "2026-07-10")
    first = app.facade.add_watchlist_item("inv-1", security)
    assert app.facade.add_watchlist_item("inv-1", security) == first
    assert app.facade.add_watchlist_item("inv-2", security) == first
    assert app.facade.doctor().status == "passed"
    app.close()
    reopened = ProductionCompositionRoot(tmp_path)
    assert reopened.facade.list_watchlist_items() == (first,)
    reopened.close()


def test_migrations_are_idempotent_atomic_and_reject_drift_and_future(tmp_path: Path) -> None:
    migration_root = tmp_path / "migrations"; migration_root.mkdir()
    source = ROOT / "migrations/0001_core_identity_objects.sql"
    target = migration_root / source.name; target.write_bytes(source.read_bytes())
    store = PlatformStore(tmp_path / "data", migration_root)
    store.migrate(); store.migrate()
    target.write_text(target.read_text(encoding="utf-8") + "\n-- drift", encoding="utf-8")
    with pytest.raises(PersistenceError, match="differs") as drift: store.migrate()
    assert drift.value.code == "MIGRATION_HASH_DRIFT"
    store.close()

    failed = PlatformStore(tmp_path / "failed", migration_root)
    with pytest.raises(PersistenceError): failed.migrate(fail_after=1)
    assert failed.connection.execute("SELECT count(*) FROM schema_migration").fetchone()[0] == 0
    failed.close()


def test_object_publish_is_content_addressed_and_doctor_detects_damage(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path, ROOT / "migrations"); store.migrate()
    first = store.workflow_ledger.commit_artifacts(GenericObjectCommit(b"immutable"))
    replay = store.workflow_ledger.commit_artifacts(GenericObjectCommit(b"immutable"))
    digest = first.sha256
    assert replay.sha256 == digest
    assert replay.disposition.value == "reused"
    path = tmp_path / "objects/sha256" / digest[:2] / digest
    path.write_bytes(b"damaged")
    assert "OBJECT_INTEGRITY_FAILED" in store.doctor().errors
    with pytest.raises(PersistenceError) as damaged:
        store.workflow_ledger.commit_artifacts(GenericObjectCommit(b"immutable"))
    assert damaged.value.code == "OBJECT_HASH_MISMATCH"
    store.close()


def test_active_data_root_rejects_known_synchronized_location(tmp_path: Path) -> None:
    with pytest.raises(PersistenceError) as error:
        PlatformStore(tmp_path / "OneDrive" / "data", ROOT / "migrations")
    assert error.value.code == "DATA_ROOT_NOT_LOCAL"


def test_second_writer_future_ledger_and_identity_conflict_fail_closed(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path, ROOT / "migrations"); store.migrate()
    (tmp_path / ".writer.lock").write_text(json.dumps({"owner_ref": "run-active", "pid": os.getpid()}), encoding="utf-8")
    with pytest.raises(PersistenceError) as busy:
        store.add_watchlist_item("inv", SecurityIdentity("stable", "SZSE", "002897", "CNY", "2026-07-10"))
    assert busy.value.code == "RUNTIME_BUSY"
    assert busy.value.owner_ref == "run-active"
    (tmp_path / ".writer.lock").unlink()
    store.add_watchlist_item("inv", SecurityIdentity("stable", "SZSE", "002897", "CNY", "2026-07-10"))
    with pytest.raises(PersistenceError) as conflict:
        store.add_watchlist_item("inv-2", SecurityIdentity("stable", "SZSE", "002897", "USD", "2026-07-10"))
    assert conflict.value.code == "SECURITY_IDENTITY_CONFLICT"
    store.connection.execute("INSERT INTO schema_migration VALUES(99,'future.sql','x','2026-07-10','future')")
    store.connection.commit()
    with pytest.raises(PersistenceError) as future: store.migrate()
    assert future.value.code == "MIGRATION_FUTURE_VERSION"
    store.close()


def test_n_minus_one_upgrade_is_backup_first_preserves_date_precision_and_rolls_back_failure(tmp_path: Path) -> None:
    migration_root = tmp_path / "migrations"; migration_root.mkdir()
    first = ROOT / "migrations/0001_core_identity_objects.sql"
    (migration_root / first.name).write_bytes(first.read_bytes())
    data_root = tmp_path / "data"
    store = PlatformStore(data_root, migration_root); store.migrate()
    security = SecurityIdentity("stable", "SZSE", "002897", "CNY", "2026-07-10")
    store.add_watchlist_item("inv", security)
    store.close()

    (migration_root / "0002_date_probe.sql").write_text("CREATE TABLE date_probe(value TEXT NOT NULL); INSERT INTO date_probe VALUES('2026-07-10')", encoding="utf-8")
    upgraded = PlatformStore(data_root, migration_root); upgraded.migrate()
    assert (data_root / "migration-backup-v0001.sqlite3").is_file()
    assert upgraded.connection.execute("SELECT value FROM date_probe").fetchone()[0] == "2026-07-10"
    assert upgraded.connection.execute("SELECT valid_from_precision FROM security_identifier").fetchone()[0] == "date"
    assert upgraded.list_watchlist_items()[0].security_id == "stable"
    upgraded.close()

    (migration_root / "0003_failure.sql").write_text("CREATE TABLE must_rollback(value TEXT); INSERT INTO must_rollback VALUES('no')", encoding="utf-8")
    failed = PlatformStore(data_root, migration_root)
    with pytest.raises(PersistenceError) as injected: failed.migrate(fail_after=1)
    assert injected.value.code == "MIGRATION_INJECTED_FAILURE"
    assert failed.connection.execute("SELECT count(*) FROM schema_migration").fetchone()[0] == 2
    assert failed.connection.execute("SELECT count(*) FROM sqlite_master WHERE name='must_rollback'").fetchone()[0] == 0
    assert failed.list_watchlist_items()[0].security_id == "stable"
    failed.close()


def test_doctor_is_read_only_and_checks_required_references(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path, ROOT / "migrations"); store.migrate()
    before = store.connection.total_changes
    report = store.doctor()
    assert report.status == "passed"
    assert store.connection.total_changes == before
    assert {"runtime_identity", "domain_invariants", "references"}.issubset(report.checks)
    digest = store.workflow_ledger.commit_artifacts(GenericObjectCommit(b"artifact")).sha256
    store.connection.execute("INSERT INTO artifact VALUES('artifact-1',?,'application/json','test@1')", (digest,))
    store.connection.execute("INSERT INTO artifact_relation VALUES('artifact-1','supports','Security','missing-security')")
    store.connection.commit()
    assert "REFERENCE_MISSING" in store.doctor().errors
    store.close()


def test_corrupt_existing_migration_backup_blocks_upgrade(tmp_path: Path) -> None:
    migration_root = tmp_path / "migrations"; migration_root.mkdir()
    first = ROOT / "migrations/0001_core_identity_objects.sql"
    (migration_root / first.name).write_bytes(first.read_bytes())
    data_root = tmp_path / "data"
    store = PlatformStore(data_root, migration_root); store.migrate(); store.close()
    (migration_root / "0002_next.sql").write_text("CREATE TABLE next_version(value TEXT)", encoding="utf-8")
    (data_root / "migration-backup-v0001.sqlite3").write_bytes(b"corrupt")
    blocked = PlatformStore(data_root, migration_root)
    with pytest.raises(PersistenceError) as error: blocked.migrate()
    assert error.value.code == "MIGRATION_BACKUP_INVALID"
    assert blocked.connection.execute("SELECT count(*) FROM schema_migration").fetchone()[0] == 1
    blocked.close()
