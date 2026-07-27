from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from trading_platform.domain.strategies import (
    StrategyCatalog,
    StrategyVersion,
)


@dataclass(frozen=True)
class GetStrategyCatalog:
    pass


@dataclass(frozen=True)
class GetStrategyVersion:
    strategy_version_id: str


StrategyQuery: TypeAlias = GetStrategyCatalog | GetStrategyVersion


class StrategyVersionReader(Protocol):
    def all_versions(self) -> tuple[StrategyVersion, ...]: ...


class StrategyQueries:
    """Exposes the complete closed-catalog read task through one interface."""

    def __init__(self, reader: StrategyVersionReader) -> None:
        self._reader = reader

    def get(
        self, query: StrategyQuery
    ) -> tuple[StrategyVersion, ...] | StrategyVersion:
        catalog = StrategyCatalog(self._reader.all_versions())
        if isinstance(query, GetStrategyCatalog):
            return catalog.list_public()
        return catalog.get(query.strategy_version_id)


__all__ = [
    "GetStrategyCatalog",
    "GetStrategyVersion",
    "StrategyQueries",
]
