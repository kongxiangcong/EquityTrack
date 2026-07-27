from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Mapping

from trading_platform.application.web_tasks import (
    WorkspaceUpdateCommand,
)

from .locking import DataRootWriterLock


class WorkspaceUpdateAuthorizationService:
    """Owns replay-safe authorization for refreshing frozen inputs."""

    def __init__(
        self, connection, writer_lock: DataRootWriterLock
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock

    def authorize(
        self, command: WorkspaceUpdateCommand
    ) -> Mapping[str, object]:
        if (
            not command.invocation_id
            or not command.security_id
            or not command.requested_date
            or not command.effective_session_date
        ):
            raise ValueError("WORKSPACE_UPDATE_AUTHORIZATION_INVALID")
        with self._writer_lock.acquire(
            f"update-authorization:{command.invocation_id}"
        ):
            existing = self._row(command.invocation_id)
            if existing is not None:
                if (
                    existing["security_id"] != command.security_id
                    or existing["requested_date"]
                    != command.requested_date
                    or existing["effective_session_date"]
                    != command.effective_session_date
                ):
                    raise ValueError("INVOCATION_CONFLICT")
                return existing
            authorization_id = f"update_auth_{uuid.uuid4().hex}"
            created_at = datetime.now(timezone.utc).isoformat()
            with self._connection:
                self._connection.execute(
                    "INSERT INTO update_authorization VALUES("
                    "?,?,?,?,?,?,?)",
                    (
                        authorization_id,
                        command.invocation_id,
                        command.security_id,
                        command.requested_date,
                        command.effective_session_date,
                        "refresh_frozen_inputs",
                        created_at,
                    ),
                )
        row = self._connection.execute(
            "SELECT * FROM update_authorization "
            "WHERE update_authorization_id=?",
            (authorization_id,),
        ).fetchone()
        assert row is not None
        return dict(row)

    def _row(
        self, invocation_id: str
    ) -> Mapping[str, object] | None:
        row = self._connection.execute(
            "SELECT * FROM update_authorization WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        return dict(row) if row is not None else None


__all__ = ["WorkspaceUpdateAuthorizationService"]
