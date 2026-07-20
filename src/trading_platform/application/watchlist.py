from __future__ import annotations

from typing import Protocol

from .contracts import SecurityIdentity, WatchlistView


class Watchlist(Protocol):
    def add(
        self, invocation_id: str, security: SecurityIdentity
    ) -> WatchlistView: ...

    def list(self) -> tuple[WatchlistView, ...]: ...


__all__ = ["Watchlist"]
