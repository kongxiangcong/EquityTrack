from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol


class FetchStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


class QualityStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    QUARANTINE = "quarantine"
    BLOCKING = "blocking"


class SourceAuthority(str, Enum):
    OFFICIAL = "official"
    STRUCTURED_AGGREGATOR = "structured_aggregator"
    SECONDARY = "secondary"
    FIXTURE = "fixture"


class FreshnessStatus(str, Enum):
    VALID = "valid"
    STALE = "stale"
    MISSING = "missing"


class SnapshotPurpose(str, Enum):
    RESEARCH = "research"
    WORKFLOW = "workflow"
    MARKET = "market"
    CHART = "chart"


class SyncStatus(str, Enum):
    COMPLETE = "complete"
    BLOCKED = "blocked"
    MISSING = "missing"
    CACHED = "cached"
    CACHED_WITH_LIMITS = "cached_with_limits"


class NextStep(str, Enum):
    SYNC_TRADE_CALENDAR = "sync_trade_calendar"
    RESOLVE_MISSING_CROSS_SECTION = "resolve_missing_cross_section"
    AUTHORIZE_SYNC = "authorize_sync"
    AUTHORIZE_REFRESH = "authorize_refresh"


class DistributionQualification(str, Enum):
    QUALIFIED = "qualified"
    EXTERNAL_BLOCKED = "external_blocked"


@dataclass(frozen=True)
class CursorCheckpoint:
    provider_id: str
    adapter_version: str
    dataset: str
    scope_id: str
    cursor_value: str


@dataclass(frozen=True)
class FetchRequest:
    invocation_id: str
    provider_id: str
    adapter_version: str
    dataset: str
    endpoint: str
    security_id: str | None
    market: str
    range_start: str | None
    range_end: str | None
    dataset_cursor: str | None
    scope_id: str
    canonical_params: Mapping[str, str]
    credential_scope_id: str
    network_authorized: bool


@dataclass(frozen=True)
class RawEnvelope:
    source_identity: str
    source_authority: SourceAuthority
    real_source_url: str
    redacted_params: Mapping[str, str]
    response_headers: Mapping[str, str]
    source_time_precision: str
    terms_profile: str
    retrieved_at: datetime
    status: FetchStatus
    payload: bytes | None
    raw_sha256: str | None
    cursor_value: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class FetchBatch:
    envelopes: tuple[RawEnvelope, ...]


class DataProvider(Protocol):
    provider_id: str
    adapter_version: str
    fixture: bool
    endpoint: str

    def fetch(self, request: FetchRequest) -> FetchBatch: ...


@dataclass(frozen=True)
class FixtureRights:
    member_id: str
    source_identity: str
    local_storage_allowed: bool
    deterministic_replay_allowed: bool
    repository_redistribution_allowed: bool
    packaged_distribution_allowed: bool
    terms_version: str
    reviewed_on: str
    raw_sha256: str | None = None


@dataclass(frozen=True)
class SyncRequest:
    invocation_id: str
    security_id: str
    provider_security_code: str
    requested_date: str
    as_of_at: datetime
    market_timezone: str
    market: str
    snapshot_purpose: SnapshotPurpose
    datasets: tuple[str, ...]
    network_authorized: bool
    offline: bool


@dataclass(frozen=True)
class Coverage:
    expected: int
    eligible: int
    excluded: int
    missing: int


@dataclass(frozen=True)
class SyncDisposition:
    raw_created: int
    raw_reused: int
    normalized_created: int
    normalized_reused: int
    snapshot_created: bool
    snapshot_reused: bool


@dataclass(frozen=True)
class SyncResult:
    status: SyncStatus
    snapshot_id: str | None
    requested_date: str
    effective_session_date: str | None
    freshness: FreshnessStatus
    quality: QualityStatus
    attempt_ids: tuple[str, ...]
    coverage: Coverage
    next_step: NextStep | None
    stale_by_days: int
    freshness_basis: str
    last_success_at: str | None
    distribution_qualification: DistributionQualification
    disposition: SyncDisposition


@dataclass(frozen=True)
class ProviderAttemptEvidence:
    attempt_id: str
    dataset: str
    status: str
    raw_sha256: str | None
    retrieved_at: str
    error_code: str | None
    blocking_codes: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotMemberView:
    normalized_version_id: str
    dataset: str
