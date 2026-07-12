from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ApplicationStatus(str, Enum):
    AVAILABLE_WITH_LIMITS = "available_with_limits"


class Capability(str, Enum):
    HEALTH = "health"
    PERSISTENCE = "persistence"
    SYNC = "sync"
    DAILY = "daily"
    SERVE = "serve"


class ErrorCode(str, Enum):
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"


CONTRACT_VERSION = "application-contract@1"


@dataclass(frozen=True)
class ApplicationError:
    code: ErrorCode
    message: str
    retryable: bool = False
    schema_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class HealthQuery:
    include_diagnostics: bool = False
    schema_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class HealthResult:
    status: ApplicationStatus
    application_version: str
    capabilities: Mapping[Capability, CapabilityStatus]
    schema_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class PlatformCommand:
    invocation_id: str
    capability: Capability
    schema_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class CapabilityResult:
    status: CapabilityStatus
    error: Optional[ApplicationError]
    schema_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class SecurityIdentity:
    security_id: str
    market: str
    code: str
    currency: str
    identifier_valid_from: str
    identifier_date_precision: str = "date"


@dataclass(frozen=True)
class WatchlistView:
    watchlist_item_id: str
    security_id: str
    market: str
    code: str
    currency: str


@dataclass(frozen=True)
class DoctorReport:
    status: str
    checks: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ResumeWorkflowCommand:
    workflow_run_id: str
    owner_token: str
    lease_seconds: int = 30


@dataclass(frozen=True)
class CancelWorkflowCommand:
    workflow_run_id: str
    reason: str
