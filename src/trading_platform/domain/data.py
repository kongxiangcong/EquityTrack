from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Mapping, Protocol

from trading_platform.identity import canonical_hash


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
class ProviderCapabilityStatus(str, Enum):
    SUPPORTED = "supported"
    UNAVAILABLE = "unavailable"


class MarketDataCapability(str, Enum):
    TRADING_CALENDAR = "trading_calendar"
    DAILY_UNADJUSTED = "daily_unadjusted"
    ADJUSTMENT_FACTORS = "adjustment_factors"
    CORPORATE_ACTIONS = "corporate_actions"
    SUSPENSION_STATUS = "suspension_status"
    PRICE_LIMIT_STATUS = "price_limit_status"
    T_PLUS_ONE = "t_plus_one"


@dataclass(frozen=True)
class ProviderCapability:
    capability: MarketDataCapability
    status: ProviderCapabilityStatus
    reason_code: str




class SnapshotPurpose(str, Enum):
    RESEARCH = "research"
    WORKFLOW = "workflow"
    MARKET = "market"
    CHART = "chart"


class SyncStatus(str, Enum):
    COMPLETE = "complete"
    BLOCKED = "blocked"
    COMPLETE_WITH_SUBSTITUTION = "complete_with_substitution"
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
class SourceRights:
    automation_allowed: bool
    local_storage_allowed: bool
    deterministic_replay_allowed: bool
    derived_use_allowed: bool
    redistribution_allowed: bool
    reviewed_on: str
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.reviewed_on:
            raise ValueError("SOURCE_RIGHTS_REVIEW_REQUIRED")
        if self.evidence_sha256 is not None and len(self.evidence_sha256) != 64:
            raise ValueError("SOURCE_RIGHTS_EVIDENCE_INVALID")


class FallbackMode(str, Enum):
    NO_FALLBACK = "no_fallback"
    QUALIFIED_EQUIVALENT = "qualified_equivalent"


class CompletenessRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class SourceFailureDisposition(str, Enum):
    BLOCK = "block"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class SourceRoute:
    dataset: str
    freshness_max_stale_days: int
    completeness: CompletenessRequirement
    retry_max_attempts: int
    fallback: FallbackMode
    failure_disposition: SourceFailureDisposition
    qualified_equivalent_receipt_ids: tuple[str, ...] = ()

    fallback_on_error_codes: tuple[str, ...] = ()
    def __post_init__(self) -> None:
        if (
            not self.dataset
            or not 0 <= self.freshness_max_stale_days <= 30
            or not 1 <= self.retry_max_attempts <= 5
        ):
            raise ValueError("SOURCE_ROUTE_INVALID")
        allowed_fallback_codes = {
            "RATE_LIMITED",
            "PROVIDER_TIMEOUT",
            "PROVIDER_DNS_FAILED",
            "PROVIDER_CONNECTION_REFUSED",
            "PROVIDER_HTTP_FAILED",
            "PROVIDER_API_RATE_LIMITED",
            "PROVIDER_API_ENTITLEMENT_UNAVAILABLE",
            "TUSHARE_QUERY_UNSUPPORTED",
            "FIXTURE_DATASET_MISSING",
        }
        if self.fallback is FallbackMode.NO_FALLBACK and (
            self.qualified_equivalent_receipt_ids or self.fallback_on_error_codes
        ):
            raise ValueError("SOURCE_ROUTE_FALLBACK_INVALID")
        if self.fallback is FallbackMode.QUALIFIED_EQUIVALENT and (
            not self.qualified_equivalent_receipt_ids
            or not self.fallback_on_error_codes
            or not set(self.fallback_on_error_codes) <= allowed_fallback_codes
        ):
            raise ValueError("SOURCE_ROUTE_QUALIFICATION_REQUIRED")


@dataclass(frozen=True)
class SourcePolicy:
    schema_version: str
    provider_id: str
    adapter_version: str
    source_identity: str
    source_authority: SourceAuthority
    terms_profile: str
    rights: SourceRights
    routes: tuple[SourceRoute, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "SourcePolicy@1":
            raise ValueError("SOURCE_POLICY_SCHEMA_INVALID")
        identity_fields = (self.provider_id, self.adapter_version, self.source_identity, self.terms_profile)
        if not all(identity_fields) or not self.routes:
            raise ValueError("SOURCE_POLICY_INVALID")
        datasets = tuple(route.dataset for route in self.routes)
        if len(set(datasets)) != len(datasets):
            raise ValueError("SOURCE_POLICY_ROUTE_DUPLICATE")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "adapter_version": self.adapter_version,
            "source_identity": self.source_identity,
            "source_authority": self.source_authority.value,
            "terms_profile": self.terms_profile,
            "rights": {
                "automation_allowed": self.rights.automation_allowed,
                "local_storage_allowed": self.rights.local_storage_allowed,
                "deterministic_replay_allowed": self.rights.deterministic_replay_allowed,
                "derived_use_allowed": self.rights.derived_use_allowed,
                "redistribution_allowed": self.rights.redistribution_allowed,
                "reviewed_on": self.rights.reviewed_on,
                "evidence_sha256": self.rights.evidence_sha256,
            },
            "routes": [{
                "dataset": route.dataset,
                "freshness_max_stale_days": route.freshness_max_stale_days,
                "completeness": route.completeness.value,
                "retry_max_attempts": route.retry_max_attempts,
                "fallback": route.fallback.value,
                "failure_disposition": route.failure_disposition.value,
                "qualified_equivalent_receipt_ids": list(route.qualified_equivalent_receipt_ids),
                "fallback_on_error_codes": list(route.fallback_on_error_codes),
            } for route in self.routes],
        }

    @property
    def identity(self) -> str:
        return "source_policy_" + canonical_hash(self.canonical_content)[:24]

    def route_for(self, dataset: str) -> SourceRoute:
        try:
            return next(route for route in self.routes if route.dataset == dataset)
        except StopIteration:
            raise ValueError("SOURCE_POLICY_ROUTE_UNDECLARED") from None


@dataclass(frozen=True)
class TradingCalendarQuery:
    invocation_id: str
    market: str
    start_date: str
    end_date: str
    dataset_cursor: str | None
    scope_id: str
    network_authorized: bool

    @property
    def dataset(self) -> str:
        return "trade_cal"


@dataclass(frozen=True)
class DailyOhlcvQuery:
    invocation_id: str
    security_id: str
    security_code: str
    venue: str
    start_date: str
    end_date: str
    adjustment_mode: str
    dataset_cursor: str | None
    scope_id: str
    network_authorized: bool

    @property
    def dataset(self) -> str:
        return "daily"


@dataclass(frozen=True)
class SecurityMasterQuery:
    invocation_id: str
    security_id: str
    security_code: str
    venue: str
    list_status: str
    as_of_date: str
    dataset_cursor: str | None
    scope_id: str
    network_authorized: bool

    @property
    def dataset(self) -> str:
        return "market_universe"


@dataclass(frozen=True)
class OfficialFilingQuery:
    invocation_id: str
    security_id: str
    security_code: str
    venue: str
    start_date: str
    end_date: str
    dataset_cursor: str | None
    scope_id: str
    network_authorized: bool

    @property
    def dataset(self) -> str:
        return "official_filing"


@dataclass(frozen=True)
class FinancialStatementQuery:
    invocation_id: str
    security_id: str
    security_code: str
    venue: str
    dataset: str
    start_date: str
    end_date: str
    dataset_cursor: str | None
    scope_id: str
    network_authorized: bool

    def __post_init__(self) -> None:
        if self.dataset not in {"income", "balancesheet", "cashflow"}:
            raise ValueError("FINANCIAL_STATEMENT_DATASET_INVALID")


@dataclass(frozen=True)
class ForecastActualQuery:
    invocation_id: str
    security_id: str
    as_of_date: str
    dataset_cursor: str | None
    scope_id: str
    network_authorized: bool

    @property
    def dataset(self) -> str:
        return "forecast_actual"


@dataclass(frozen=True)
class ResearchComponentInputQuery:
    invocation_id: str
    security_id: str
    as_of_date: str
    component_dataset: str
    dataset_cursor: str | None
    scope_id: str
    network_authorized: bool

    def __post_init__(self) -> None:
        if self.component_dataset not in {
            "research_model_input",
            "market_path_policy",
        }:
            raise ValueError("RESEARCH_COMPONENT_DATASET_INVALID")

    @property
    def dataset(self) -> str:
        return self.component_dataset


TypedDatasetQuery = (
    TradingCalendarQuery
    | DailyOhlcvQuery
    | SecurityMasterQuery
    | OfficialFilingQuery
    | FinancialStatementQuery
    | ForecastActualQuery
    | ResearchComponentInputQuery
)


@dataclass(frozen=True)
class QueryPolicy:
    schema_version: str
    lookback_days: int
    market_universe_list_status: str
    adjustment_mode: str

    def __post_init__(self) -> None:
        if self.schema_version != "QueryPolicy@1" or self.lookback_days < 1:
            raise ValueError("QUERY_POLICY_INVALID")
        if not self.market_universe_list_status or self.adjustment_mode != "none":
            raise ValueError("QUERY_POLICY_INVALID")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "lookback_days": self.lookback_days,
            "market_universe_list_status": self.market_universe_list_status,
            "adjustment_mode": self.adjustment_mode,
        }

    @property
    def identity(self) -> str:
        return "query_policy_" + canonical_hash(self.canonical_content)[:24]

    def build(self, dataset: str, request: "SyncRequest", cursor: str | None) -> TypedDatasetQuery:
        start_date = (date.fromisoformat(request.requested_date) - timedelta(days=self.lookback_days)).isoformat()
        end_date = request.requested_date
        if dataset == "trade_cal":
            return TradingCalendarQuery(request.invocation_id, request.market, start_date, end_date, cursor, request.security_id, request.network_authorized)
        if dataset == "daily":
            return DailyOhlcvQuery(request.invocation_id, request.security_id, request.security_code, request.market, start_date, end_date, self.adjustment_mode, cursor, request.security_id, request.network_authorized)
        if dataset == "market_universe":
            return SecurityMasterQuery(request.invocation_id, request.security_id, request.security_code, request.market, self.market_universe_list_status, request.requested_date, cursor, request.security_id, request.network_authorized)
        if dataset == "official_filing":
            return OfficialFilingQuery(
                request.invocation_id,
                request.security_id,
                request.security_code,
                request.market,
                start_date,
                end_date,
                cursor,
                request.security_id,
                request.network_authorized,
            )
        if dataset in {"income", "balancesheet", "cashflow"}:
            return FinancialStatementQuery(
                request.invocation_id,
                request.security_id,
                request.security_code,
                request.market,
                dataset,
                start_date,
                end_date,
                cursor,
                request.security_id,
                request.network_authorized,
            )
        if dataset == "forecast_actual":
            return ForecastActualQuery(request.invocation_id, request.security_id, request.requested_date, cursor, request.security_id, request.network_authorized)
        if dataset in {"research_model_input", "market_path_policy"}:
            return ResearchComponentInputQuery(
                request.invocation_id,
                request.security_id,
                request.requested_date,
                dataset,
                cursor,
                request.security_id,
                request.network_authorized,
            )
        raise ValueError("QUERY_DATASET_UNDECLARED")


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
    code_identity: str
    transport_identity: str
    provider_id: str
    adapter_version: str
    fixture: bool
    capabilities: tuple[ProviderCapability, ...]

    def fetch(self, request: TypedDatasetQuery) -> FetchBatch: ...


@dataclass(frozen=True)
class QualifiedEquivalentBinding:
    qualification_receipt_id: str
    provider: DataProvider
    source_policy: SourcePolicy

    def __post_init__(self) -> None:
        if not self.qualification_receipt_id.startswith("artifact_"):
            raise ValueError("QUALIFIED_EQUIVALENT_RECEIPT_INVALID")
        if (self.provider.provider_id, self.provider.adapter_version) != (
            self.source_policy.provider_id,
            self.source_policy.adapter_version,
        ):
            raise ValueError("QUALIFIED_EQUIVALENT_PROVIDER_MISMATCH")



class QualifiedEquivalentAuthority(Protocol):
    def authorize(
        self,
        receipt_artifact_id: str,
        provider_id: str,
        adapter_version: str,
        source_policy_identity: str,
        dataset: str,
        adapter_code_identity: str,
        transport_identity: str,
    ) -> None: ...


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
    security_code: str
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
    substitution_receipt_ids: tuple[str, ...] = ()


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
