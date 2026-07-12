from __future__ import annotations

from .contracts import (
    ApplicationError,
    ApplicationStatus,
    Capability,
    CapabilityResult,
    CapabilityStatus,
    ErrorCode,
    HealthQuery,
    HealthResult,
    PlatformCommand,
    SecurityIdentity,
    DoctorReport,
    WatchlistView,
)
from .ports import PlatformPersistence


class ApplicationFacade:
    """The sole command/query boundary used by local adapters."""

    VERSION = "platform-skeleton@1"

    def __init__(self, store: PlatformPersistence | None = None) -> None:
        self._store = store

    def query_health(self, query: HealthQuery) -> HealthResult:
        del query
        return HealthResult(
            status=ApplicationStatus.AVAILABLE_WITH_LIMITS,
            application_version=self.VERSION,
            capabilities={
                Capability.HEALTH: CapabilityStatus.AVAILABLE,
                Capability.PERSISTENCE: CapabilityStatus.AVAILABLE if self._store is not None else CapabilityStatus.UNAVAILABLE,
                Capability.SYNC: CapabilityStatus.UNAVAILABLE,
                Capability.DAILY: CapabilityStatus.UNAVAILABLE,
                Capability.SERVE: CapabilityStatus.UNAVAILABLE,
            },
        )

    def execute(self, command: PlatformCommand) -> CapabilityResult:
        return CapabilityResult(
            status=CapabilityStatus.UNAVAILABLE,
            error=ApplicationError(
                code=ErrorCode.CAPABILITY_UNAVAILABLE,
                message=f"Capability '{command.capability.value}' is not implemented in this slice.",
            ),
        )

    def add_watchlist_item(self, invocation_id: str, security: SecurityIdentity) -> WatchlistView:
        if self._store is None:
            raise RuntimeError("persistence unavailable")
        return self._store.add_watchlist_item(invocation_id, security)

    def list_watchlist_items(self) -> tuple[WatchlistView, ...]:
        return () if self._store is None else self._store.list_watchlist_items()

    def doctor(self) -> DoctorReport:
        if self._store is None:
            return DoctorReport("failed", (), ("PERSISTENCE_UNAVAILABLE",))
        return self._store.doctor()
