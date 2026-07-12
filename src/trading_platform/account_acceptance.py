from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from trading_platform.persistence import PlatformStore


class AccountAcceptanceService:
    """Writes a local, aggregate-only replay receipt for an initialized account."""

    def __init__(self, data_root: Path, migrations_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.migrations_root = migrations_root.resolve()

    def write_manifest(
        self, account_id: str, suite_artifacts: tuple[Path, ...]
    ) -> Path:
        store = PlatformStore(self.data_root, self.migrations_root)
        try:
            store.migrate()
            opening = store.connection.execute(
                "SELECT b.import_batch_id,b.confirmed_as_of,p.portfolio_snapshot_id,p.reconciliation_status FROM account_import_batch b JOIN portfolio_snapshot p USING(account_id) WHERE b.account_id=?",
                (account_id,),
            ).fetchone()
            history = store.connection.execute(
                "SELECT b.history_import_batch_id,b.window_start,b.window_end,b.result_counts_json,b.quality_issues_json,s.account_history_snapshot_id,s.reconciliation_status,s.limitations_json FROM history_import_batch b LEFT JOIN account_history_snapshot s USING(history_import_batch_id) WHERE b.account_id=? ORDER BY b.created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            if (
                opening is None
                or history is None
                or history["account_history_snapshot_id"] is None
                or history["reconciliation_status"] == "blocked"
            ):
                raise RuntimeError("ACCOUNT_ACCEPTANCE_INCOMPLETE")
            counts = json.loads(history["result_counts_json"])
            source_refs = [
                {"role": row[0], "schema": row[1], "safe_sha256": row[2]}
                for row in store.connection.execute(
                    "SELECT source_role,source_schema_version,object_sha256 FROM history_import_source WHERE history_import_batch_id=? ORDER BY source_role",
                    (history["history_import_batch_id"],),
                )
            ]
            source_refs.extend(
                {"role": row[0], "schema": row[1], "safe_sha256": row[2]}
                for row in store.connection.execute(
                    "SELECT source_role,source_schema_version,object_sha256 FROM account_import_source WHERE import_batch_id=? ORDER BY source_role",
                    (opening["import_batch_id"],),
                )
            )
            latest_cash = store.connection.execute(
                "SELECT running_balance_decimal FROM account_event WHERE account_id=? AND cash_effect=1 ORDER BY event_date DESC,source_order DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            opening_cash = store.connection.execute(
                "SELECT amount_decimal FROM account_cash_opening WHERE account_id=?",
                (account_id,),
            ).fetchone()
            position_check = store.connection.execute(
                "SELECT count(*),sum(CASE WHEN CAST(quantity_decimal AS NUMERIC)=CAST(available_decimal AS NUMERIC)+CAST(frozen_decimal AS NUMERIC) THEN 0 ELSE 1 END) FROM account_position WHERE account_id=?",
                (account_id,),
            ).fetchone()
            artifact_refs = []
            required_artifacts = {
                "account-import",
                "workspace-browser",
                "backup-restore",
                "full-regression",
            }
            for artifact in suite_artifacts:
                resolved = artifact.resolve()
                if not resolved.is_file():
                    raise RuntimeError("ACCOUNT_ACCEPTANCE_ARTIFACT_MISSING")
                evidence = json.loads(resolved.read_text(encoding="utf-8"))
                if evidence.get("status") != "passed":
                    raise RuntimeError("ACCOUNT_ACCEPTANCE_ARTIFACT_FAILED")
                artifact_refs.append(
                    {
                        "name": resolved.stem,
                        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
                    }
                )
            if {item["name"] for item in artifact_refs} != required_artifacts:
                raise RuntimeError("ACCOUNT_ACCEPTANCE_ARTIFACT_SET_INVALID")
            checks = {
                "current_state_initialized": True,
                "cash_reconciled": latest_cash is not None
                and opening_cash is not None
                and latest_cash[0] == opening_cash[0],
                "positions_reconciled": history["reconciliation_status"] != "blocked"
                and position_check[0] > 0
                and position_check[1] == 0,
                "history_complete": counts.get("opening_gaps", 0) == 0,
            }
            current_slice_complete = (
                checks["current_state_initialized"]
                and checks["cash_reconciled"]
                and checks["positions_reconciled"]
                and not checks["history_complete"]
                and bool(artifact_refs)
            )
            manifest = {
                "schema_version": "AccountAcceptanceManifest@1",
                "canonical_row_identity_version": "content+occurrence+previous-cash-balance@1",
                "account_ref": hashlib.sha256(account_id.encode()).hexdigest()[:16],
                "opening": dict(opening),
                "history": {
                    **dict(history),
                    "result_counts_json": counts,
                    "quality_issues_json": json.loads(history["quality_issues_json"]),
                    "limitations_json": json.loads(history["limitations_json"]),
                },
                "source_refs": source_refs,
                "checks": checks,
                "suite_artifact_refs": artifact_refs,
                "current_slice_complete": current_slice_complete,
                "long_term_platform_complete": False,
            }
            target = self.data_root / "acceptance/account-initialization.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                dir=target.parent, prefix=".account-acceptance-"
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(manifest, stream, ensure_ascii=False, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return target
        finally:
            store.close()


__all__ = ["AccountAcceptanceService"]
