from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from trading_platform.domain.data import (
    DailyOhlcvQuery,
    FinancialStatementQuery,
    MarketDataCapability,
    ProviderCapability,
    ProviderCapabilityStatus,
    FetchBatch,
    ForecastActualQuery,
    FetchStatus,
    OfficialFilingQuery,
    RawEnvelope,
    ResearchComponentInputQuery,
    SecurityMasterQuery,
    SourceAuthority,
    TradingCalendarQuery,
    TypedDatasetQuery,
)
from trading_platform.identity import canonical_hash


@dataclass(frozen=True)
class TransportResponse:
    body: bytes
    headers: Mapping[str, str]


def _wire_date(value: str) -> str:
    return value.replace("-", "")


def _exchange_code(code: str, venue: str) -> str:
    suffix = {"SZSE": "SZ", "SSE": "SH", "BSE": "BJ"}.get(venue)
    if suffix is None or not code.isdigit():
        raise ValueError("PROVIDER_SECURITY_IDENTITY_UNSUPPORTED")
    return f"{code}.{suffix}"


def _query_identity(query: TypedDatasetQuery) -> dict[str, str]:
    if isinstance(query, TradingCalendarQuery):
        return {"exchange": query.market, "start_date": _wire_date(query.start_date), "end_date": _wire_date(query.end_date)}
    if isinstance(query, DailyOhlcvQuery):
        return {"ts_code": _exchange_code(query.security_code, query.venue), "start_date": _wire_date(query.start_date), "end_date": _wire_date(query.end_date), "adjustment_mode": query.adjustment_mode}
    if isinstance(query, SecurityMasterQuery):
        return {"ts_code": _exchange_code(query.security_code, query.venue), "list_status": query.list_status}
    if isinstance(query, OfficialFilingQuery):
        return {
            "security_id": query.security_id,
            "security_code": query.security_code,
            "venue": query.venue,
            "start_date": _wire_date(query.start_date),
            "end_date": _wire_date(query.end_date),
        }
    if isinstance(query, FinancialStatementQuery):
        return {
            "ts_code": _exchange_code(query.security_code, query.venue),
            "start_date": _wire_date(query.start_date),
            "end_date": _wire_date(query.end_date),
        }
    if isinstance(query, ForecastActualQuery):
        return {"security_id": query.security_id, "as_of_date": query.as_of_date}
    if isinstance(query, ResearchComponentInputQuery):
        return {
            "security_id": query.security_id,
            "as_of_date": query.as_of_date,
            "component_dataset": query.component_dataset,
        }
    raise TypeError("TYPED_DATASET_QUERY_INVALID")


def _cursor_value(query: TypedDatasetQuery) -> str | None:
    return (
        query.as_of_date
        if isinstance(
            query,
            (
                SecurityMasterQuery,
                ForecastActualQuery,
                ResearchComponentInputQuery,
            ),
        )
        else query.end_date
    )


class FixtureProvider:
    fixture = True
    capabilities = (
        ProviderCapability(MarketDataCapability.TRADING_CALENDAR, ProviderCapabilityStatus.SUPPORTED, "FIXTURE_TYPED_QUERY"),
        ProviderCapability(MarketDataCapability.DAILY_UNADJUSTED, ProviderCapabilityStatus.SUPPORTED, "FIXTURE_TYPED_QUERY"),
        ProviderCapability(MarketDataCapability.ADJUSTMENT_FACTORS, ProviderCapabilityStatus.UNAVAILABLE, "FIXTURE_CONTRACT_NOT_IMPLEMENTED"),
        ProviderCapability(MarketDataCapability.CORPORATE_ACTIONS, ProviderCapabilityStatus.UNAVAILABLE, "FIXTURE_CONTRACT_NOT_IMPLEMENTED"),
        ProviderCapability(MarketDataCapability.SUSPENSION_STATUS, ProviderCapabilityStatus.UNAVAILABLE, "FIXTURE_CONTRACT_NOT_IMPLEMENTED"),
        ProviderCapability(MarketDataCapability.PRICE_LIMIT_STATUS, ProviderCapabilityStatus.UNAVAILABLE, "FIXTURE_CONTRACT_NOT_IMPLEMENTED"),
    )


    def __init__(self, provider_id: str, adapter_version: str, payloads: Mapping[str, bytes], source_identity: str, terms_profile: str, source_authority: SourceAuthority = SourceAuthority.FIXTURE) -> None:
        self.provider_id = provider_id
        self.adapter_version = adapter_version
        self._payloads = dict(payloads)
        self._source_identity = source_identity
        self._terms_profile = terms_profile
        self._source_authority = source_authority
        self.endpoint = "fixture://local-replay"
        self.code_identity = "sha256:" + hashlib.sha256(b"FixtureProvider@1").hexdigest()
        self.transport_identity = canonical_hash({"provider_id": provider_id, "adapter_version": adapter_version, "destination": self.endpoint})

    def fetch(self, request: TypedDatasetQuery) -> FetchBatch:
        payload = self._payloads.get(request.dataset)
        return FetchBatch((RawEnvelope(
            source_identity=self._source_identity,
            source_authority=self._source_authority,
            real_source_url=self.endpoint,
            redacted_params=_query_identity(request),
            response_headers={},
            source_time_precision="microsecond",
            terms_profile=self._terms_profile,
            retrieved_at=datetime.now(timezone.utc),
            status=FetchStatus.COMPLETE if payload is not None else FetchStatus.MISSING,
            payload=payload,
            raw_sha256=hashlib.sha256(payload).hexdigest() if payload is not None else None,
            cursor_value=_cursor_value(request) if payload is not None else None,
            error_code=None if payload is not None else "FIXTURE_DATASET_MISSING",
        ),))
