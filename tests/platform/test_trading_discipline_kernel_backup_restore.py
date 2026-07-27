from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.trading_discipline_kernel_scenario import (
    build_kernel_scenario,
)
from trading_platform.application import (
    encode_read_model,
    open_read_models,
)
from trading_platform.operations import PlatformOperations


GENERATED_AT = "2026-08-03T20:00:00+08:00"


def _authority_manifest(data_root: Path) -> dict[str, object]:
    with open_read_models(data_root) as reads:
        portfolio = encode_read_model(
            reads.portfolio("account_local", GENERATED_AT)
        )
    adapter = SQLiteOwningAdapterFixture(data_root)
    manifest = {
        "portfolio_sha256": hashlib.sha256(portfolio).hexdigest(),
        "schema_versions": [
                tuple(row)
                for row in adapter.execute(
                    "SELECT version, name, sha256 "
                    "FROM schema_migration ORDER BY version"
                )
        ],
        "snapshot_hashes": [
            tuple(row)
            for row in adapter.execute(
                "SELECT account_snapshot_version_id, graph_seal_hash "
                "FROM account_snapshot_version ORDER BY version_no"
            )
        ],
        "plan_hashes": [
            tuple(row)
            for row in adapter.execute(
                "SELECT plan_version_id, graph_seal_hash "
                "FROM trade_plan_version ORDER BY plan_version_id"
            )
        ],
        "review_hashes": [
            tuple(row)
            for row in adapter.execute(
                "SELECT discipline_review_id, version_no, content_hash "
                "FROM discipline_review_version "
                "ORDER BY discipline_review_id, version_no"
            )
        ],
        "execution_ids": [
            row[0]
            for row in adapter.execute(
                "SELECT execution_record_id "
                "FROM execution_record ORDER BY 1"
            )
        ],
    }
    adapter.close()
    return manifest


def test_full_chain_rebuilds_after_restore(tmp_path: Path) -> None:
    live = tmp_path / "live"
    scenario = build_kernel_scenario(live)
    before = _authority_manifest(live)
    archive = tmp_path / "backup" / "tdk-kernel.zip"
    backup = PlatformOperations(live).backup(archive)
    restored = tmp_path / "restored"
    restore = PlatformOperations.restore(archive, restored)
    after = _authority_manifest(restored)

    assert scenario.data_root == live
    assert archive.is_file()
    assert restored != live
    assert backup["status"] == "succeeded"
    assert restore["status"] == "succeeded"
    assert restore["doctor_status"] == "passed"
    assert before == after

    evidence_root = os.environ.get("TDK_ACCEPTANCE_EVIDENCE_ROOT")
    if evidence_root:
        (Path(evidence_root) / "backup-restore.json").write_text(
            json.dumps(
                {
                    "schema_version": "KernelBackupRestoreEvidence@1",
                    "status": "passed",
                    "backup_name": archive.name,
                    "backup_sha256": hashlib.sha256(
                        archive.read_bytes()
                    ).hexdigest(),
                    "restored_root_distinct": restored != live,
                    "doctor_status": restore["doctor_status"],
                    "authority_manifest": after,
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
