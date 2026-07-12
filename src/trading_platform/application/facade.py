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
)


class ApplicationFacade:
    """The sole command/query boundary used by local adapters."""

    VERSION = "platform-skeleton@1"

    def query_health(self, query: HealthQuery) -> HealthResult:
        del query
        return HealthResult(
            status=ApplicationStatus.AVAILABLE_WITH_LIMITS,
            application_version=self.VERSION,
            capabilities={
                Capability.HEALTH: CapabilityStatus.AVAILABLE,
                Capability.PERSISTENCE: CapabilityStatus.UNAVAILABLE,
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
