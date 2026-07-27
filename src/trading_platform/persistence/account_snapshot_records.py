from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from trading_platform.domain.account_snapshots import (
    AccountSnapshotDraft,
    AccountSnapshotError,
    AccountSnapshotPosition,
    AccountSnapshotVersion,
)


def encode_draft_record(draft: AccountSnapshotDraft) -> tuple[object, ...]:
    """Translate one validated draft aggregate to the fixed SQLite record."""
    return (
        draft.draft_id,
        draft.account_id,
        draft.revision,
        draft.status,
        draft.source_kind,
        draft.redacted_source_ref,
        draft.as_of_at,
        draft.as_of_precision,
        draft.timezone,
        draft.session_semantics,
        draft.currency,
        draft.cash_state,
        draft.cash_value,
        draft.nav_state,
        draft.nav_value,
        draft.fees_state,
        draft.fees_value,
        draft.previous_snapshot_version_id,
        draft.revises_snapshot_version_id,
        draft.corrects_snapshot_version_id,
        draft.correction_reason,
        draft.validation_state,
        json.dumps(draft.validation_errors),
        json.dumps(draft.capability_impacts),
        draft.canonical_diff,
        draft.canonical_diff_hash,
        json.dumps(asdict(draft), sort_keys=True, separators=(",", ":")),
        draft.content_hash,
        draft.created_by,
        draft.created_at,
        draft.updated_at,
    )


def load_draft_record(
    connection: sqlite3.Connection, draft_id: str
) -> AccountSnapshotDraft:
    """Rehydrate an exact draft revision from its canonical persisted record."""
    row = connection.execute(
        "SELECT content_json,status,revision,updated_at "
        "FROM account_snapshot_draft WHERE draft_id=?",
        (draft_id,),
    ).fetchone()
    if row is None:
        raise AccountSnapshotError("SNAPSHOT_NOT_FOUND")
    decoded = json.loads(row["content_json"])
    decoded["positions"] = tuple(
        AccountSnapshotPosition(**position) for position in decoded["positions"]
    )
    for field in ("validation_errors", "capability_impacts"):
        decoded[field] = tuple(decoded[field])
    decoded["status"] = row["status"]
    decoded["revision"] = row["revision"]
    decoded["updated_at"] = row["updated_at"]
    return AccountSnapshotDraft(**decoded)


def load_version_record(
    connection: sqlite3.Connection, version_id: str
) -> AccountSnapshotVersion:
    """Verify and rehydrate one immutable snapshot graph."""
    row = connection.execute(
        "SELECT * FROM account_snapshot_version "
        "WHERE account_snapshot_version_id=?",
        (version_id,),
    ).fetchone()
    if row is None:
        raise AccountSnapshotError("SNAPSHOT_NOT_FOUND")
    positions = tuple(
        AccountSnapshotPosition(
            security_id=position["security_id"],
            total_quantity=position["total_quantity"],
            available_quantity_state=position["available_quantity_state"],
            available_quantity_value=position["available_quantity_value"],
            cost_state=position["cost_state"],
            cost_value=position["cost_value"],
            market_value_state=position["market_value_state"],
            market_value_value=position["market_value_value"],
            content_hash=position["content_hash"],
        )
        for position in connection.execute(
            "SELECT * FROM account_snapshot_position "
            "WHERE account_snapshot_version_id=? ORDER BY security_id",
            (version_id,),
        )
    )
    capabilities = tuple(
        (
            capability["capability_key"],
            capability["state"],
            capability["reason_code"],
            tuple(json.loads(capability["required_field_refs_json"])),
        )
        for capability in connection.execute(
            "SELECT * FROM account_snapshot_capability "
            "WHERE account_snapshot_version_id=? ORDER BY capability_key",
            (version_id,),
        )
    )
    cash = connection.execute(
        "SELECT * FROM account_snapshot_cash "
        "WHERE account_snapshot_version_id=?",
        (version_id,),
    ).fetchone()
    if cash is None:
        raise AccountSnapshotError("SNAPSHOT_GRAPH_INCOMPLETE")
    return AccountSnapshotVersion(
        account_snapshot_version_id=row["account_snapshot_version_id"],
        account_id=row["account_id"],
        version_no=row["version_no"],
        source_draft_id=row["source_draft_id"],
        as_of_at=row["as_of_at"],
        as_of_precision=row["as_of_precision"],
        timezone=row["timezone"],
        session_semantics=row["session_semantics"],
        currency=row["currency"],
        source_kind=row["source_kind"],
        redacted_source_ref=row["redacted_source_ref"],
        previous_snapshot_version_id=row["previous_snapshot_version_id"],
        revises_snapshot_version_id=row["revises_snapshot_version_id"],
        corrects_snapshot_version_id=row["corrects_snapshot_version_id"],
        correction_reason=row["correction_reason"],
        confirmed_by=row["confirmed_by"],
        confirmed_at=row["confirmed_at"],
        content_hash=row["content_hash"],
        graph_seal_hash=row["graph_seal_hash"],
        cash_state=cash["cash_state"],
        cash_value=cash["cash_value"],
        nav_state=cash["nav_state"],
        nav_value=cash["nav_value"],
        fees_state=cash["fees_state"],
        fees_value=cash["fees_value"],
        positions=positions,
        capabilities=capabilities,
    )


__all__ = ["encode_draft_record", "load_draft_record", "load_version_record"]
