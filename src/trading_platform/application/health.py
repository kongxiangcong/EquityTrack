from __future__ import annotations

from .contracts import (
    ApplicationStatus,
    Capability,
    CapabilityStatus,
    HealthQuery,
    HealthResult,
)


class Health:
    """Report the statically available platform capabilities."""

    VERSION = "platform-tasks@1"

    def __init__(self, *, persistence: bool = False, sync: bool = False) -> None:
        self._persistence = persistence
        self._sync = sync

    def inspect(self, query: HealthQuery) -> HealthResult:
        del query
        return HealthResult(
            status=ApplicationStatus.AVAILABLE_WITH_LIMITS,
            application_version=self.VERSION,
            capabilities={
                Capability.HEALTH: CapabilityStatus.AVAILABLE,
                Capability.PERSISTENCE: (
                    CapabilityStatus.AVAILABLE
                    if self._persistence
                    else CapabilityStatus.UNAVAILABLE
                ),
                Capability.SYNC: (
                    CapabilityStatus.AVAILABLE
                    if self._sync
                    else CapabilityStatus.UNAVAILABLE
                ),
                Capability.DAILY: CapabilityStatus.UNAVAILABLE,
                Capability.SERVE: CapabilityStatus.UNAVAILABLE,
            },
        )


__all__ = ["Health"]
