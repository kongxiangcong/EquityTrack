from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.domain.account_state import (
    AccountStateDrift,
    AccountStateError,
    EstimatedAccountState,
    ExecutionRecordReader,
    derive_estimated_account_state,
    reconcile_account_state,
)


@dataclass(frozen=True)
class GetEstimatedAccountState:
    account_id: str


@dataclass(frozen=True)
class CompareConfirmedAccountState:
    expected_from_snapshot_version_id: str
    confirmed_snapshot_version_id: str


class AccountSnapshotAuthorityReader(Protocol):
    def latest(self, account_id: str) -> AccountSnapshotVersion | None: ...

    def version(self, account_snapshot_version_id: str) -> AccountSnapshotVersion: ...

    def account_ids(self) -> tuple[str, ...]: ...


class AccountStateQueries:
    """Derives working state and drift from immutable authority records."""

    def __init__(
        self,
        snapshots: AccountSnapshotAuthorityReader,
        executions: ExecutionRecordReader | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._executions = executions

    def get(self, query: GetEstimatedAccountState) -> EstimatedAccountState:
        if not query.account_id:
            raise AccountStateError("ACCOUNT_ID_REQUIRED")
        snapshot = self._snapshots.latest(query.account_id)
        if snapshot is None:
            raise AccountStateError("ACCOUNT_SNAPSHOT_NOT_CONFIRMED")
        records = (
            ()
            if self._executions is None
            else self._executions.read_confirmed(
                query.account_id, after_snapshot=snapshot
            )
        )
        return derive_estimated_account_state(
            snapshot,
            records,
            execution_reader_available=self._executions is not None,
        )

    def compare(
        self, query: CompareConfirmedAccountState
    ) -> AccountStateDrift:
        baseline = self._snapshots.version(
            query.expected_from_snapshot_version_id
        )
        confirmed = self._snapshots.version(query.confirmed_snapshot_version_id)
        if baseline.account_id != confirmed.account_id:
            raise AccountStateError("ACCOUNT_SNAPSHOT_ACCOUNT_MISMATCH")
        records = (
            ()
            if self._executions is None
            else self._executions.read_confirmed(
                baseline.account_id,
                after_snapshot=baseline,
                through_snapshot=confirmed,
            )
        )
        expected = derive_estimated_account_state(
            baseline,
            records,
            execution_reader_available=self._executions is not None,
            through_snapshot=confirmed,
        )
        return reconcile_account_state(expected, confirmed)

    def list_current(self) -> tuple[EstimatedAccountState, ...]:
        return tuple(
            self.get(GetEstimatedAccountState(account_id))
            for account_id in self._snapshots.account_ids()
        )


__all__ = [
    "AccountStateQueries",
    "CompareConfirmedAccountState",
    "GetEstimatedAccountState",
]
