from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone

from trading_platform.application.account_snapshots import (
    ConfirmAccountSnapshot,
    CreateAccountSnapshotDraft,
    GetAccountSnapshot,
    RegisterAccountForSnapshots,
    UpdateAccountSnapshotDraft,
)
from trading_platform.domain.account_snapshots import (
    AccountRegistration,
    AccountSecurityIdentity,
    AccountSnapshotDraft,
    AccountSnapshotError,
    AccountSnapshotPosition,
    AccountSnapshotService,
    AccountSnapshotVersion,
)
from trading_platform.identity import canonical_hash

from .locking import DataRootWriterLock
from .account_snapshot_records import (
    encode_draft_record,
    load_draft_record,
    load_version_record,
)


class SQLiteAccountSnapshotRepository:
    """Owns durable snapshot protocol translation and atomic confirmation."""

    def __init__(
        self, connection: sqlite3.Connection, writer_lock: DataRootWriterLock
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock
        self._service = AccountSnapshotService()

    def register_account(
        self,
        command: RegisterAccountForSnapshots,
        registration: AccountRegistration,
    ) -> AccountRegistration:
        request_hash = canonical_hash(command)
        replay = self._receipt(command.invocation_id, request_hash)
        if replay is not None:
            return registration
        with self._writer_lock.acquire(
            f"account-registration:{registration.account_id}"
        ):
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                replay = self._receipt(command.invocation_id, request_hash)
                if replay is not None:
                    self._connection.rollback()
                    return registration
                self._insert_or_verify_account(registration)
                self._insert_or_verify_securities(registration.securities)
                now = datetime.now(timezone.utc).isoformat()
                self._insert_receipt(
                    command.invocation_id,
                    "account_snapshot.register_account@2",
                    request_hash,
                    "AccountRegistration",
                    registration.account_id,
                    registration.registration_id,
                    self._actor(
                        command.decision_actor_type,
                        command.decision_actor_id,
                    ),
                    command.interaction_channel,
                    self._actor(
                        command.transport_actor_type,
                        command.transport_actor_id,
                    ),
                    now,
                )
                self._connection.commit()
                return registration
            except Exception:
                self._connection.rollback()
                raise

    def create_draft(
        self, command: CreateAccountSnapshotDraft, draft: AccountSnapshotDraft
    ) -> AccountSnapshotDraft:
        request_hash = canonical_hash(command)
        replay = self._receipt(command.invocation_id, request_hash)
        if replay is not None:
            return load_draft_record(self._connection, replay["revision_or_version_id"])
        now = datetime.now(timezone.utc).isoformat()
        prepared = replace(draft, created_at=now, updated_at=now)
        prepared = self._service.prepare(
            prepared, self._latest_version(prepared.account_id)
        )
        owns_transaction = not self._connection.in_transaction
        lock = (
            self._writer_lock.acquire(f"account-snapshot-draft:{prepared.account_id}")
            if owns_transaction
            else nullcontext()
        )
        with lock:
            replay = self._receipt(command.invocation_id, request_hash)
            if replay is not None:
                return load_draft_record(
                    self._connection, replay["revision_or_version_id"]
                )
            try:
                if owns_transaction:
                    self._connection.execute("BEGIN IMMEDIATE")
                self._assert_account_and_positions(prepared)
                self._insert_draft(prepared)
                self._insert_receipt(
                    command.invocation_id,
                    "account_snapshot.create_draft@1",
                    request_hash,
                    "AccountSnapshotDraft",
                    prepared.account_id,
                    prepared.draft_id,
                    self._actor(
                        command.decision_actor_type,
                        command.decision_actor_id,
                    ),
                    command.interaction_channel,
                    self._actor(
                        command.transport_actor_type,
                        command.transport_actor_id,
                    ),
                    now,
                )
                if owns_transaction:
                    self._connection.commit()
            except Exception:
                if owns_transaction:
                    self._connection.rollback()
                raise
        return prepared

    def update_draft(
        self, command: UpdateAccountSnapshotDraft, draft: AccountSnapshotDraft
    ) -> AccountSnapshotDraft:
        request_hash = canonical_hash(command)
        replay = self._receipt(command.invocation_id, request_hash)
        if replay is not None:
            return load_draft_record(self._connection, replay["revision_or_version_id"])
        current = load_draft_record(self._connection, draft.draft_id)
        if current.status != "open":
            raise AccountSnapshotError("SNAPSHOT_DRAFT_NOT_OPEN")
        if current.revision != command.expected_revision:
            raise AccountSnapshotError("SNAPSHOT_DRAFT_REVISION_STALE")
        if draft.account_id != current.account_id:
            raise AccountSnapshotError("SNAPSHOT_DRAFT_ACCOUNT_IMMUTABLE")
        now = datetime.now(timezone.utc).isoformat()
        prepared = self._service.prepare(
            replace(
                draft,
                revision=current.revision + 1,
                created_at=current.created_at,
                updated_at=now,
            ),
            self._latest_version(draft.account_id),
        )
        with self._writer_lock.acquire(f"account-snapshot-draft:{prepared.account_id}"):
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT revision,status FROM account_snapshot_draft "
                    "WHERE draft_id=?",
                    (prepared.draft_id,),
                ).fetchone()
                if (
                    row is None
                    or row["status"] != "open"
                    or row["revision"] != command.expected_revision
                ):
                    raise AccountSnapshotError("SNAPSHOT_DRAFT_REVISION_STALE")
                self._assert_account_and_positions(prepared)
                self._connection.execute(
                    "DELETE FROM account_snapshot_draft_position WHERE draft_id=?",
                    (prepared.draft_id,),
                )
                self._update_draft_row(prepared)
                self._insert_draft_positions(prepared)
                self._insert_receipt(
                    command.invocation_id,
                    "account_snapshot.update_draft@1",
                    request_hash,
                    "AccountSnapshotDraft",
                    prepared.account_id,
                    prepared.draft_id,
                    self._actor(
                        command.decision_actor_type,
                        command.decision_actor_id,
                    ),
                    command.interaction_channel,
                    self._actor(
                        command.transport_actor_type,
                        command.transport_actor_id,
                    ),
                    now,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return prepared

    def confirm(self, command: ConfirmAccountSnapshot) -> AccountSnapshotVersion:
        request_hash = canonical_hash(command)
        replay = self._receipt(command.invocation_id, request_hash)
        if replay is not None:
            if replay["result_type"] != "AccountSnapshotVersion":
                raise AccountSnapshotError("COMMAND_INVOCATION_CONFLICT")
            return load_version_record(
                self._connection, replay["revision_or_version_id"]
            )
        draft = load_draft_record(self._connection, command.draft_id)
        if draft.status != "open":
            raise AccountSnapshotError("SNAPSHOT_DRAFT_NOT_OPEN")
        if draft.revision != command.expected_revision:
            raise AccountSnapshotError("SNAPSHOT_DRAFT_REVISION_STALE")
        if draft.validation_state != "valid":
            raise AccountSnapshotError("SNAPSHOT_DRAFT_INVALID")
        now = datetime.now(timezone.utc).isoformat()
        with self._writer_lock.acquire(f"account-snapshot-confirm:{draft.account_id}"):
            replay = self._receipt(command.invocation_id, request_hash)
            if replay is not None:
                return load_version_record(
                    self._connection, replay["revision_or_version_id"]
                )
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                locked = self._connection.execute(
                    "SELECT status,revision FROM account_snapshot_draft "
                    "WHERE draft_id=?",
                    (draft.draft_id,),
                ).fetchone()
                if (
                    locked is None
                    or locked["status"] != "open"
                    or locked["revision"] != command.expected_revision
                ):
                    raise AccountSnapshotError("SNAPSHOT_DRAFT_REVISION_STALE")
                prior = self._latest_version(draft.account_id)
                reason = self._service.transition_reason(draft, prior)
                version_no = 1 if prior is None else prior.version_no + 1
                version_id = (
                    "account_snapshot_version_"
                    + canonical_hash(
                        {
                            "account_id": draft.account_id,
                            "version_no": version_no,
                            "draft_hash": draft.content_hash,
                        }
                    )[:24]
                )
                actor = self._actor(
                    command.decision_actor_type, command.decision_actor_id
                )
                graph_seal_hash = canonical_hash(
                    {
                        "version_id": version_id,
                        "draft_hash": draft.content_hash,
                        "positions": tuple(
                            position.content_hash for position in draft.positions
                        ),
                        "prior": prior.graph_seal_hash if prior else None,
                        "actor": actor,
                    }
                )
                self._connection.execute(
                    "INSERT INTO account_snapshot_version VALUES("
                    "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        version_id,
                        draft.account_id,
                        version_no,
                        draft.draft_id,
                        draft.as_of_at,
                        draft.as_of_precision,
                        draft.timezone,
                        draft.session_semantics,
                        draft.currency,
                        draft.source_kind,
                        draft.redacted_source_ref,
                        prior.account_snapshot_version_id if prior else None,
                        draft.revises_snapshot_version_id,
                        draft.corrects_snapshot_version_id,
                        draft.correction_reason,
                        actor,
                        now,
                        draft.content_hash,
                        graph_seal_hash,
                    ),
                )
                self._connection.execute(
                    "INSERT INTO account_snapshot_cash VALUES(?,?,?,?,?,?,?,?)",
                    (
                        version_id,
                        draft.cash_state,
                        draft.cash_value,
                        draft.currency,
                        draft.nav_state,
                        draft.nav_value,
                        draft.fees_state,
                        draft.fees_value,
                    ),
                )
                for position in draft.positions:
                    self._connection.execute(
                        "INSERT INTO account_snapshot_position VALUES("
                        "?,?,?,?,?,?,?,?,?,?)",
                        (
                            version_id,
                            position.security_id,
                            position.total_quantity,
                            position.available_quantity_state,
                            position.available_quantity_value,
                            position.cost_state,
                            position.cost_value,
                            position.market_value_state,
                            position.market_value_value,
                            position.content_hash,
                        ),
                    )
                self._insert_capabilities(version_id, draft)
                transition_id = (
                    "account_snapshot_transition_"
                    + canonical_hash(
                        {
                            "invocation_id": command.invocation_id,
                            "to": version_id,
                            "reason": reason,
                        }
                    )[:24]
                )
                transport_actor = self._actor(
                    command.transport_actor_type,
                    command.transport_actor_id,
                )
                transition_hash = canonical_hash(
                    {
                        "transition_id": transition_id,
                        "from": prior.account_snapshot_version_id if prior else None,
                        "to": version_id,
                        "reason": reason,
                        "actor": actor,
                    }
                )
                self._connection.execute(
                    "INSERT INTO account_snapshot_transition VALUES("
                    "?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        transition_id,
                        draft.account_id,
                        prior.account_snapshot_version_id if prior else None,
                        version_id,
                        reason,
                        actor,
                        command.interaction_channel,
                        transport_actor,
                        command.invocation_id,
                        now,
                        transition_hash,
                    ),
                )
                event_payload = {
                    "account_id": draft.account_id,
                    "account_snapshot_version_id": version_id,
                    "transition_id": transition_id,
                }
                event_hash = canonical_hash(event_payload)
                self._connection.execute(
                    "INSERT INTO application_event VALUES(?,?,?,?,?,?,?)",
                    (
                        "application_event_" + event_hash[:24],
                        "AccountSnapshotConfirmed",
                        "AccountSnapshotVersion",
                        version_id,
                        json.dumps(
                            event_payload, sort_keys=True, separators=(",", ":")
                        ),
                        now,
                        event_hash,
                    ),
                )
                projection_hash = canonical_hash(
                    {
                        "account_id": draft.account_id,
                        "version_id": version_id,
                        "revision": version_no,
                    }
                )
                self._connection.execute(
                    "INSERT INTO account_snapshot_projection_checkpoint "
                    "VALUES(?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                    "account_snapshot_version_id=excluded.account_snapshot_version_id,"
                    "projection_revision=excluded.projection_revision,"
                    "projection_hash=excluded.projection_hash,"
                    "advanced_at=excluded.advanced_at",
                    (
                        draft.account_id,
                        version_id,
                        version_no,
                        projection_hash,
                        now,
                    ),
                )
                self._connection.execute(
                    "UPDATE account_snapshot_draft SET status='confirmed',"
                    "updated_at=? WHERE draft_id=?",
                    (now, draft.draft_id),
                )
                self._insert_receipt(
                    command.invocation_id,
                    "account_snapshot.confirm@1",
                    request_hash,
                    "AccountSnapshotVersion",
                    draft.account_id,
                    version_id,
                    actor,
                    command.interaction_channel,
                    transport_actor,
                    now,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return load_version_record(self._connection, version_id)

    def get(
        self, query: GetAccountSnapshot
    ) -> AccountSnapshotDraft | AccountSnapshotVersion:
        if query.draft_id is not None:
            return load_draft_record(self._connection, query.draft_id)
        if query.account_snapshot_version_id is not None:
            return load_version_record(
                self._connection, query.account_snapshot_version_id
            )
        row = self._connection.execute(
            "SELECT account_snapshot_version_id "
            "FROM account_snapshot_projection_checkpoint WHERE account_id=?",
            (query.account_id,),
        ).fetchone()
        if row is None:
            raise AccountSnapshotError("SNAPSHOT_NOT_FOUND")
        return load_version_record(self._connection, row["account_snapshot_version_id"])

    def latest(self, account_id: str) -> AccountSnapshotVersion | None:
        return self._latest_version(account_id)

    def _assert_account_and_positions(self, draft: AccountSnapshotDraft) -> None:
        account = self._connection.execute(
            "SELECT base_currency FROM account WHERE account_id=?",
            (draft.account_id,),
        ).fetchone()
        if account is None:
            raise AccountSnapshotError("ACCOUNT_NOT_FOUND")
        if account["base_currency"] != draft.currency:
            raise AccountSnapshotError("ACCOUNT_CURRENCY_MISMATCH")
        known = (
            {
                row["security_id"]
                for row in self._connection.execute(
                    "SELECT security_id FROM security WHERE security_id IN "
                    f"({','.join('?' for _ in draft.positions)})",
                    tuple(position.security_id for position in draft.positions),
                )
            }
            if draft.positions
            else set()
        )
        if known != {position.security_id for position in draft.positions}:
            raise AccountSnapshotError("POSITION_SECURITY_NOT_FOUND")

    def _insert_or_verify_account(self, registration: AccountRegistration) -> None:
        alias = self._connection.execute(
            "SELECT account_id FROM account WHERE alias=?",
            (registration.alias,),
        ).fetchone()
        if alias is not None and alias["account_id"] != registration.account_id:
            raise AccountSnapshotError("ACCOUNT_ALIAS_CONFLICT")
        row = self._connection.execute(
            "SELECT alias,base_currency,source_snapshot_hash "
            "FROM account WHERE account_id=?",
            (registration.account_id,),
        ).fetchone()
        if row is None:
            self._connection.execute(
                "INSERT INTO account VALUES(?,?,?,?,?)",
                (
                    registration.account_id,
                    registration.alias,
                    registration.base_currency,
                    registration.registered_at,
                    registration.content_hash,
                ),
            )
            return
        if (
            row["alias"] != registration.alias
            or row["base_currency"] != registration.base_currency
            or row["source_snapshot_hash"] != registration.content_hash
        ):
            raise AccountSnapshotError("ACCOUNT_IDENTITY_CONFLICT")

    def _insert_or_verify_securities(
        self, identities: tuple[AccountSecurityIdentity, ...]
    ) -> None:
        for identity in identities:
            security = self._connection.execute(
                "SELECT currency FROM security WHERE security_id=?",
                (identity.security_id,),
            ).fetchone()
            if security is None:
                self._connection.execute(
                    "INSERT INTO security VALUES(?,?)",
                    (identity.security_id, identity.currency),
                )
            elif security["currency"] != identity.currency:
                raise AccountSnapshotError("SECURITY_CURRENCY_CONFLICT")
            identifiers = self._connection.execute(
                "SELECT i.security_id,s.currency "
                "FROM security_identifier i JOIN security s USING(security_id) "
                "WHERE i.market=? AND i.code=? AND i.valid_from<=? "
                "AND (i.valid_to IS NULL OR i.valid_to>?)",
                (
                    identity.market,
                    identity.code,
                    identity.observed_on,
                    identity.observed_on,
                ),
            ).fetchall()
            if len(identifiers) > 1:
                raise AccountSnapshotError("SECURITY_IDENTIFIER_AMBIGUOUS")
            if not identifiers:
                any_identifier = self._connection.execute(
                    "SELECT security_id FROM security_identifier "
                    "WHERE market=? AND code=? LIMIT 1",
                    (identity.market, identity.code),
                ).fetchone()
                if any_identifier is not None:
                    raise AccountSnapshotError("SECURITY_IDENTIFIER_TEMPORAL_CONFLICT")
                identifier_id = (
                    "security_identifier_"
                    + canonical_hash(
                        {
                            "security_id": identity.security_id,
                            "market": identity.market,
                            "code": identity.code,
                            "observed_on": identity.observed_on,
                        }
                    )[:24]
                )
                self._connection.execute(
                    "INSERT INTO security_identifier VALUES(?,?,?,?,?,?,?,?)",
                    (
                        identifier_id,
                        identity.security_id,
                        identity.market,
                        identity.code,
                        identity.observed_on,
                        "date",
                        None,
                        None,
                    ),
                )
            elif (
                identifiers[0]["security_id"] != identity.security_id
                or identifiers[0]["currency"] != identity.currency
            ):
                raise AccountSnapshotError("SECURITY_IDENTIFIER_CONFLICT")

    def _insert_draft(self, draft: AccountSnapshotDraft) -> None:
        self._connection.execute(
            "INSERT INTO account_snapshot_draft VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            encode_draft_record(draft),
        )
        self._insert_draft_positions(draft)

    def _update_draft_row(self, draft: AccountSnapshotDraft) -> None:
        values = encode_draft_record(draft)
        self._connection.execute(
            "UPDATE account_snapshot_draft SET "
            "account_id=?,revision=?,status=?,source_kind=?,redacted_source_ref=?,"
            "as_of_at=?,as_of_precision=?,timezone=?,session_semantics=?,currency=?,"
            "cash_state=?,cash_value=?,nav_state=?,nav_value=?,fees_state=?,fees_value=?,"
            "previous_snapshot_version_id=?,revises_snapshot_version_id=?,"
            "corrects_snapshot_version_id=?,correction_reason=?,validation_state=?,"
            "validation_errors_json=?,capability_impacts_json=?,canonical_diff=?,"
            "canonical_diff_hash=?,content_json=?,content_hash=?,created_by=?,"
            "created_at=?,updated_at=? WHERE draft_id=?",
            values[1:] + (draft.draft_id,),
        )

    def _insert_draft_positions(self, draft: AccountSnapshotDraft) -> None:
        for position in draft.positions:
            self._connection.execute(
                "INSERT INTO account_snapshot_draft_position VALUES("
                "?,?,?,?,?,?,?,?,?,?)",
                (
                    draft.draft_id,
                    position.security_id,
                    position.total_quantity,
                    position.available_quantity_state,
                    position.available_quantity_value,
                    position.cost_state,
                    position.cost_value,
                    position.market_value_state,
                    position.market_value_value,
                    position.content_hash,
                ),
            )

    def _insert_capabilities(
        self, version_id: str, draft: AccountSnapshotDraft
    ) -> None:
        fields = (
            ("cash_rules", draft.cash_state, ("cash",)),
            ("nav_rules", draft.nav_state, ("nav",)),
            ("fees_rules", draft.fees_state, ("fees",)),
        )
        for key, state, refs in fields:
            self._capability(version_id, key, state == "known", refs)
        for position in draft.positions:
            prefix = f"positions.{position.security_id}"
            self._capability(
                version_id,
                f"total_quantity:{position.security_id}",
                True,
                (f"{prefix}.total_quantity",),
            )
            self._capability(
                version_id,
                f"available_quantity:{position.security_id}",
                position.available_quantity_state == "known",
                (f"{prefix}.available_quantity",),
            )
            self._capability(
                version_id,
                f"cost:{position.security_id}",
                position.cost_state == "known",
                (f"{prefix}.cost",),
            )
            self._capability(
                version_id,
                f"market_value:{position.security_id}",
                position.market_value_state == "known",
                (f"{prefix}.market_value",),
            )

    def _capability(
        self, version_id: str, key: str, available: bool, refs: tuple[str, ...]
    ) -> None:
        self._connection.execute(
            "INSERT INTO account_snapshot_capability VALUES(?,?,?,?,?)",
            (
                version_id,
                key,
                "available" if available else "unable",
                None if available else "OPTIONAL_OPERAND_UNKNOWN",
                json.dumps(refs),
            ),
        )

    def _latest_version(self, account_id: str) -> AccountSnapshotVersion | None:
        row = self._connection.execute(
            "SELECT account_snapshot_version_id "
            "FROM account_snapshot_projection_checkpoint WHERE account_id=?",
            (account_id,),
        ).fetchone()
        return (
            load_version_record(self._connection, row["account_snapshot_version_id"])
            if row is not None
            else None
        )

    def _receipt(self, invocation_id: str, request_hash: str) -> sqlite3.Row | None:
        row = self._connection.execute(
            "SELECT * FROM application_command_receipt WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is not None and row["request_hash"] != request_hash:
            raise AccountSnapshotError("COMMAND_INVOCATION_CONFLICT")
        return row

    def _insert_receipt(
        self,
        invocation_id: str,
        command_name: str,
        request_hash: str,
        result_type: str,
        aggregate_id: str,
        revision_or_version_id: str,
        decision_actor: str,
        interaction_channel: str,
        transport_actor: str,
        created_at: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO application_command_receipt VALUES(" "?,?,?,?,?,?,?,?,?,?,?)",
            (
                invocation_id,
                command_name,
                request_hash,
                result_type,
                aggregate_id,
                revision_or_version_id,
                "succeeded",
                decision_actor,
                interaction_channel,
                transport_actor,
                created_at,
            ),
        )

    @staticmethod
    def _actor(actor_type: str, actor_id: str) -> str:
        return f"{actor_type}:{actor_id}"


class SQLiteAccountSnapshotProjection:
    """Owns reads of draft history and the latest-confirmed projection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, query: GetAccountSnapshot
    ) -> AccountSnapshotDraft | AccountSnapshotVersion:
        if query.draft_id is not None:
            return load_draft_record(self._connection, query.draft_id)
        if query.account_snapshot_version_id is not None:
            return load_version_record(
                self._connection, query.account_snapshot_version_id
            )
        row = self._connection.execute(
            "SELECT account_snapshot_version_id "
            "FROM account_snapshot_projection_checkpoint WHERE account_id=?",
            (query.account_id,),
        ).fetchone()
        if row is None:
            raise AccountSnapshotError("SNAPSHOT_NOT_FOUND")
        return load_version_record(self._connection, row["account_snapshot_version_id"])

    def latest(self, account_id: str) -> AccountSnapshotVersion | None:
        row = self._connection.execute(
            "SELECT account_snapshot_version_id "
            "FROM account_snapshot_projection_checkpoint WHERE account_id=?",
            (account_id,),
        ).fetchone()
        return (
            load_version_record(self._connection, row["account_snapshot_version_id"])
            if row is not None
            else None
        )

    def version(self, account_snapshot_version_id: str) -> AccountSnapshotVersion:
        return load_version_record(self._connection, account_snapshot_version_id)

    def account_ids(self) -> tuple[str, ...]:
        return tuple(
            row["account_id"]
            for row in self._connection.execute(
                "SELECT account_id FROM account_snapshot_projection_checkpoint "
                "ORDER BY account_id"
            )
        )


__all__ = [
    "SQLiteAccountSnapshotProjection",
    "SQLiteAccountSnapshotRepository",
]
