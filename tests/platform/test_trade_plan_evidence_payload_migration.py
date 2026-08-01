from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.platform.canonical_plan_journey_fixture import (
    arrange_canonical_plan_journey,
)
from trading_platform.application import GetTradePlanGraph
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.plans import SQLiteTradePlanRepository


ROOT = Path(__file__).resolve().parents[2]


def _downgrade_evidence_table_to_v23(data_root: Path) -> None:
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.executescript(
        """
        DROP TRIGGER trade_plan_evidence_no_late_insert;
        DROP TRIGGER trade_plan_evidence_no_update;
        DROP TRIGGER trade_plan_evidence_no_delete;
        ALTER TABLE trade_plan_evidence_reference
        RENAME TO trade_plan_evidence_reference_v24_fixture;
        CREATE TABLE trade_plan_evidence_reference (
          plan_version_id TEXT NOT NULL
            REFERENCES trade_plan_version(plan_version_id),
          ref_order INTEGER NOT NULL CHECK(ref_order >= 0),
          ref_type TEXT NOT NULL,
          ref_id TEXT NOT NULL,
          resolution_status TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          PRIMARY KEY(plan_version_id,ref_order)
        );
        INSERT INTO trade_plan_evidence_reference
        SELECT plan_version_id,ref_order,ref_type,ref_id,
               resolution_status,content_hash
        FROM trade_plan_evidence_reference_v24_fixture;
        DROP TABLE trade_plan_evidence_reference_v24_fixture;
        CREATE TRIGGER trade_plan_evidence_no_late_insert
        BEFORE INSERT ON trade_plan_evidence_reference
        WHEN (
          SELECT graph_sealed FROM trade_plan_version
          WHERE plan_version_id=NEW.plan_version_id
        )=1
        BEGIN
          SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE');
        END;
        CREATE TRIGGER trade_plan_evidence_no_update
        BEFORE UPDATE ON trade_plan_evidence_reference
        BEGIN
          SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE');
        END;
        CREATE TRIGGER trade_plan_evidence_no_delete
        BEFORE DELETE ON trade_plan_evidence_reference
        BEGIN
          SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE');
        END;
        DELETE FROM schema_migration WHERE version=24;
        """
    )
    connection.commit()
    connection.close()


def test_0024_recovers_approved_enriched_evidence_as_single_payload(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "evidence-payload-migration"
    with arrange_canonical_plan_journey(
        data_root, activate=True
    ) as journey:
        version_id = journey.plan_version_id
        graph = journey.platform.plans.get(
            GetTradePlanGraph(version_id)
        )
        expected = tuple(
            dict(reference)
            for reference in graph.evidence_references
        )
        assert any(
            len(reference) > 4 for reference in expected
        )

    _downgrade_evidence_table_to_v23(data_root)

    upgraded = PlatformStore(data_root, ROOT / "migrations")
    upgraded.migrate()
    migrated = SQLiteTradePlanRepository(
        upgraded.connection, upgraded.writer_lock
    ).get_graph(version_id)
    assert migrated.evidence_references == expected
    rows = tuple(
        upgraded.connection.execute(
            "SELECT reference_json FROM "
            "trade_plan_evidence_reference "
            "WHERE plan_version_id=? ORDER BY ref_order",
            (version_id,),
        )
    )
    assert tuple(json.loads(row["reference_json"]) for row in rows) == (
        expected
    )
    assert upgraded.connection.execute(
        "SELECT max(version) FROM schema_migration"
    ).fetchone()[0] == 24
    with pytest.raises(
        sqlite3.IntegrityError,
        match="TRADE_PLAN_GRAPH_IMMUTABLE",
    ):
        upgraded.connection.execute(
            "UPDATE trade_plan_evidence_reference "
            "SET resolution_status='tampered' "
            "WHERE plan_version_id=?",
            (version_id,),
        )
    upgraded.close()

    restarted = PlatformStore(data_root, ROOT / "migrations")
    replay = SQLiteTradePlanRepository(
        restarted.connection, restarted.writer_lock
    ).get_graph(version_id)
    assert replay.evidence_references == expected
    restarted.close()
