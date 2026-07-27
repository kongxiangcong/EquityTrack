from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from trading_platform.domain.plans import (
    ActiveTradePlan,
    TradePlanGraph,
    TradePlanMaster,
)


@dataclass(frozen=True)
class CreateTradePlanMaster:
    master: TradePlanMaster


@dataclass(frozen=True)
class SealTradePlanGraph:
    graph: TradePlanGraph


@dataclass(frozen=True)
class ActivateTradePlanVersion:
    plan_id: str
    plan_version_id: str
    user_approval_receipt_id: str
    command_invocation_id: str


@dataclass(frozen=True)
class GetActiveTradePlan:
    account_id: str
    security_id: str


@dataclass(frozen=True)
class GetTradePlanGraph:
    plan_version_id: str


TradePlanCommand: TypeAlias = (
    CreateTradePlanMaster | SealTradePlanGraph | ActivateTradePlanVersion
)
TradePlanQuery: TypeAlias = GetActiveTradePlan | GetTradePlanGraph


class TradePlanStore(Protocol):
    def create_master(self, master: TradePlanMaster) -> TradePlanMaster: ...

    def seal_version(self, graph: TradePlanGraph) -> TradePlanGraph: ...

    def activate_version(
        self,
        *,
        plan_id: str,
        plan_version_id: str,
        user_approval_receipt_id: str,
        command_invocation_id: str,
    ) -> ActiveTradePlan: ...

    def get_active_master(
        self, account_id: str, security_id: str
    ) -> ActiveTradePlan: ...

    def get_graph(self, plan_version_id: str) -> TradePlanGraph: ...


class TradePlanTasks:
    """Owns complete Model B graph and activation tasks at one seam."""

    def __init__(self, store: TradePlanStore) -> None:
        self._store = store

    def execute(
        self, command: TradePlanCommand
    ) -> TradePlanMaster | TradePlanGraph | ActiveTradePlan:
        if isinstance(command, CreateTradePlanMaster):
            return self._store.create_master(command.master)
        if isinstance(command, SealTradePlanGraph):
            return self._store.seal_version(command.graph)
        return self._store.activate_version(
            plan_id=command.plan_id,
            plan_version_id=command.plan_version_id,
            user_approval_receipt_id=command.user_approval_receipt_id,
            command_invocation_id=command.command_invocation_id,
        )

    def get(
        self, query: TradePlanQuery
    ) -> ActiveTradePlan | TradePlanGraph:
        if isinstance(query, GetActiveTradePlan):
            return self._store.get_active_master(
                query.account_id, query.security_id
            )
        return self._store.get_graph(query.plan_version_id)


__all__ = [
    "ActivateTradePlanVersion",
    "CreateTradePlanMaster",
    "GetActiveTradePlan",
    "GetTradePlanGraph",
    "SealTradePlanGraph",
    "TradePlanTasks",
]
