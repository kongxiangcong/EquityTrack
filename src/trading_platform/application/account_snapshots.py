from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from trading_platform.domain.account_snapshots import (
    AccountRegistration,
    AccountSnapshotDraft,
    AccountSnapshotError,
    AccountSnapshotService,
    AccountSnapshotVersion,
)


@dataclass(frozen=True)
class RegisterAccountForSnapshots:
    invocation_id: str
    registration: AccountRegistration
    decision_actor_type: str
    decision_actor_id: str
    interaction_channel: str
    transport_actor_type: str
    transport_actor_id: str


@dataclass(frozen=True)
class CreateAccountSnapshotDraft:
    invocation_id: str
    draft: AccountSnapshotDraft
    decision_actor_type: str
    decision_actor_id: str
    interaction_channel: str
    transport_actor_type: str
    transport_actor_id: str


@dataclass(frozen=True)
class UpdateAccountSnapshotDraft:
    invocation_id: str
    draft: AccountSnapshotDraft
    expected_revision: int
    decision_actor_type: str
    decision_actor_id: str
    interaction_channel: str
    transport_actor_type: str
    transport_actor_id: str


@dataclass(frozen=True)
class ConfirmAccountSnapshot:
    invocation_id: str
    draft_id: str
    expected_revision: int
    decision_actor_type: str
    decision_actor_id: str
    interaction_channel: str
    transport_actor_type: str
    transport_actor_id: str


@dataclass(frozen=True)
class GetAccountSnapshot:
    account_id: str | None = None
    account_snapshot_version_id: str | None = None
    draft_id: str | None = None


AccountSnapshotCommand: TypeAlias = (
    RegisterAccountForSnapshots
    | CreateAccountSnapshotDraft
    | UpdateAccountSnapshotDraft
    | ConfirmAccountSnapshot
)


class AccountSnapshotRepository(Protocol):
    def register_account(
        self,
        command: RegisterAccountForSnapshots,
        registration: AccountRegistration,
    ) -> AccountRegistration: ...

    def create_draft(
        self, command: CreateAccountSnapshotDraft, draft: AccountSnapshotDraft
    ) -> AccountSnapshotDraft: ...

    def update_draft(
        self, command: UpdateAccountSnapshotDraft, draft: AccountSnapshotDraft
    ) -> AccountSnapshotDraft: ...

    def confirm(self, command: ConfirmAccountSnapshot) -> AccountSnapshotVersion: ...

    def get(
        self, query: GetAccountSnapshot
    ) -> AccountSnapshotDraft | AccountSnapshotVersion: ...

    def latest(self, account_id: str) -> AccountSnapshotVersion | None: ...

    def resolve_account(self, reference: str) -> str: ...


class AccountSnapshotCommands:
    """Complete account snapshot mutation tasks behind one application seam."""

    def __init__(
        self,
        repository: AccountSnapshotRepository,
        service: AccountSnapshotService,
    ) -> None:
        self._repository = repository
        self._service = service

    def execute(
        self, command: AccountSnapshotCommand
    ) -> AccountRegistration | AccountSnapshotDraft | AccountSnapshotVersion:
        if not command.invocation_id:
            raise AccountSnapshotError("COMMAND_INVOCATION_ID_REQUIRED")
        if (
            command.decision_actor_type not in {"user", "agent"}
            or not command.decision_actor_id
            or command.interaction_channel not in {"skill", "cli", "web"}
            or command.transport_actor_type not in {"user", "agent", "adapter"}
            or not command.transport_actor_id
        ):
            raise AccountSnapshotError("COMMAND_ACTOR_METADATA_INVALID")
        if isinstance(command, RegisterAccountForSnapshots):
            if command.decision_actor_type != "user":
                raise AccountSnapshotError("USER_CONFIRMATION_CAPABILITY_REQUIRED")
            registration = self._service.prepare_registration(command.registration)
            return self._repository.register_account(command, registration)
        if isinstance(command, CreateAccountSnapshotDraft):
            if command.draft.status != "open":
                raise AccountSnapshotError("SNAPSHOT_DRAFT_STATUS_INVALID")
            prepared = self._service.prepare(
                command.draft,
                self._repository.latest(command.draft.account_id),
            )
            return self._repository.create_draft(command, prepared)
        if isinstance(command, UpdateAccountSnapshotDraft):
            if command.draft.status != "open":
                raise AccountSnapshotError("SNAPSHOT_DRAFT_STATUS_INVALID")
            prepared = self._service.prepare(
                command.draft,
                self._repository.latest(command.draft.account_id),
            )
            return self._repository.update_draft(command, prepared)
        if command.decision_actor_type != "user":
            raise AccountSnapshotError("USER_CONFIRMATION_CAPABILITY_REQUIRED")
        return self._repository.confirm(command)


class AccountSnapshotQueries:
    def __init__(self, repository: AccountSnapshotRepository) -> None:
        self._repository = repository

    def get(
        self, query: GetAccountSnapshot
    ) -> AccountSnapshotDraft | AccountSnapshotVersion:
        requested = sum(
            value is not None
            for value in (
                query.account_id,
                query.account_snapshot_version_id,
                query.draft_id,
            )
        )
        if requested != 1:
            raise AccountSnapshotError("SNAPSHOT_QUERY_IDENTITY_REQUIRED")
        return self._repository.get(query)


    def resolve(self, reference: str) -> str:
        if not reference or not reference.strip():
            raise AccountSnapshotError("ACCOUNT_REFERENCE_REQUIRED")
        return self._repository.resolve_account(reference.strip())

__all__ = [
    "RegisterAccountForSnapshots",
    "AccountSnapshotCommands",
    "AccountSnapshotQueries",
    "ConfirmAccountSnapshot",
    "CreateAccountSnapshotDraft",
    "GetAccountSnapshot",
    "UpdateAccountSnapshotDraft",
]
