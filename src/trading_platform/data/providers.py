from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
import socket
import ssl
from datetime import datetime, timezone
from typing import Callable, Mapping
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from pathlib import Path
from urllib.error import HTTPError, URLError

from trading_platform.domain.data import (
    DailyOhlcvQuery,
    MarketDataCapability,
    ProviderCapability,
    ProviderCapabilityStatus,
    FetchBatch,
    ForecastActualQuery,
    FetchStatus,
    OfficialFilingQuery,
    RawEnvelope,
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
def tushare_compatible_code_identity() -> str:
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TRUSTED_GATEWAY_ENDPOINT = "http://8.136.22.187:8010/"
_RETAINED_HEADERS = {"content-type", "date", "retry-after"}


class _ProviderTransportFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise _ProviderTransportFailure("PROVIDER_REDIRECT_BLOCKED")


def _retained_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {

        key: value
        for key, value in headers.items()
        if key.lower() in _RETAINED_HEADERS
    }


def _transport_error_code(error: BaseException) -> str:
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        return "PROVIDER_DNS_FAILED"
    if isinstance(reason, ssl.SSLError):
        return "PROVIDER_TLS_FAILED"
    if isinstance(reason, ConnectionRefusedError):
        return "PROVIDER_CONNECTION_REFUSED"
    if isinstance(reason, TimeoutError):
        return "PROVIDER_TIMEOUT"
    return "PROVIDER_TRANSPORT_FAILED"


def _validated_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("PROVIDER_DESTINATION_INVALID")
    production = endpoint == _TRUSTED_GATEWAY_ENDPOINT
    loopback = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port is not None
    if not production and not loopback:
        raise ValueError("PROVIDER_DESTINATION_INVALID")
    return endpoint




def _wire_date(value: str) -> str:
    return value.replace("-", "")


def _tushare_code(code: str, venue: str) -> str:
    suffix = {"SZSE": "SZ", "SSE": "SH", "BSE": "BJ"}.get(venue)
    if suffix is None or not code.isdigit():
        raise ValueError("PROVIDER_SECURITY_IDENTITY_UNSUPPORTED")
    return f"{code}.{suffix}"


def _query_identity(query: TypedDatasetQuery) -> dict[str, str]:
    if isinstance(query, TradingCalendarQuery):
        return {"exchange": query.market, "start_date": _wire_date(query.start_date), "end_date": _wire_date(query.end_date)}
    if isinstance(query, DailyOhlcvQuery):
        return {"ts_code": _tushare_code(query.security_code, query.venue), "start_date": _wire_date(query.start_date), "end_date": _wire_date(query.end_date), "adjustment_mode": query.adjustment_mode}
    if isinstance(query, SecurityMasterQuery):
        return {"ts_code": _tushare_code(query.security_code, query.venue), "list_status": query.list_status}
    if isinstance(query, OfficialFilingQuery):
        return {
            "security_id": query.security_id,
            "security_code": query.security_code,
            "venue": query.venue,
            "start_date": _wire_date(query.start_date),
            "end_date": _wire_date(query.end_date),
        }
    if isinstance(query, ForecastActualQuery):
        return {"security_id": query.security_id, "as_of_date": query.as_of_date}
    raise TypeError("TYPED_DATASET_QUERY_INVALID")


def _cursor_value(query: TypedDatasetQuery) -> str | None:
    return (
        query.as_of_date
        if isinstance(query, (SecurityMasterQuery, ForecastActualQuery))
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


class TushareCompatibleProvider:
    """Own the complete Tushare-compatible transport and typed-query translation."""
    capabilities = (
        ProviderCapability(MarketDataCapability.TRADING_CALENDAR, ProviderCapabilityStatus.SUPPORTED, "TUSHARE_TRADE_CAL"),
        ProviderCapability(MarketDataCapability.DAILY_UNADJUSTED, ProviderCapabilityStatus.SUPPORTED, "TUSHARE_DAILY"),
        ProviderCapability(MarketDataCapability.ADJUSTMENT_FACTORS, ProviderCapabilityStatus.UNAVAILABLE, "TYPED_QUERY_NOT_IMPLEMENTED"),
        ProviderCapability(MarketDataCapability.CORPORATE_ACTIONS, ProviderCapabilityStatus.UNAVAILABLE, "TYPED_QUERY_NOT_IMPLEMENTED"),
        ProviderCapability(MarketDataCapability.SUSPENSION_STATUS, ProviderCapabilityStatus.UNAVAILABLE, "TYPED_QUERY_NOT_IMPLEMENTED"),
        ProviderCapability(MarketDataCapability.PRICE_LIMIT_STATUS, ProviderCapabilityStatus.UNAVAILABLE, "TYPED_QUERY_NOT_IMPLEMENTED"),
    )


    fixture = False

    def __init__(self, provider_id: str, adapter_version: str, endpoint: str, credential: str, source_identity: str, terms_profile: str, transport: Callable[[Request], TransportResponse] | None = None, source_authority: SourceAuthority = SourceAuthority.STRUCTURED_AGGREGATOR) -> None:
        self.code_identity = tushare_compatible_code_identity()
        self.provider_id = provider_id
        self.adapter_version = adapter_version
        self._endpoint = _validated_endpoint(endpoint)
        self.transport_identity = canonical_hash({"provider_id": provider_id, "adapter_version": adapter_version, "destination": self._endpoint})
        self._credential = credential
        self._source_identity = source_identity
        self._terms_profile = terms_profile
        self._source_authority = source_authority
        self._transport = transport or self._default_transport

    @staticmethod
    def _default_transport(request: Request) -> TransportResponse:
        with build_opener(_RejectRedirects()).open(request, timeout=30) as response:
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise _ProviderTransportFailure("PROVIDER_RESPONSE_OVERSIZE")
            return TransportResponse(payload, _retained_headers(dict(response.headers.items())))

    def fetch(self, query: TypedDatasetQuery) -> FetchBatch:
        now = datetime.now(timezone.utc)
        params = _query_identity(query)
        if isinstance(query, ForecastActualQuery):
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self._endpoint, params, {}, "not_applicable", self._terms_profile, now, FetchStatus.FAILED, None, None, error_code="TUSHARE_QUERY_UNSUPPORTED"),))
        if not query.network_authorized:
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self._endpoint, params, {}, "unknown", self._terms_profile, now, FetchStatus.FAILED, None, None, error_code="NETWORK_NOT_AUTHORIZED"),))
        api_name = "stock_basic" if isinstance(query, SecurityMasterQuery) else query.dataset
        wire_params = dict(params)
        wire_params.pop("adjustment_mode", None)
        body = json.dumps({"api_name": api_name, "token": self._credential, "params": wire_params}, sort_keys=True).encode("utf-8")
        try:
            response = self._transport(Request(self._endpoint, data=body, headers={"Content-Type": "application/json"}))
            if len(response.body) > _MAX_RESPONSE_BYTES:
                raise _ProviderTransportFailure("PROVIDER_RESPONSE_OVERSIZE")
            response = TransportResponse(response.body, _retained_headers(response.headers))
            payload = response.body
        except HTTPError as error:
            status = (
                FetchStatus.RATE_LIMITED
                if error.code == 429
                else FetchStatus.FAILED
            )
            headers = _retained_headers(dict(error.headers.items())) if error.headers else {}
            code = {
                401: "AUTHENTICATION_FAILED",
                403: "ACCESS_FORBIDDEN",
                429: "RATE_LIMITED",
            }.get(error.code, "PROVIDER_HTTP_FAILED")
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self._endpoint, params, headers, "http-date", self._terms_profile, now, status, None, None, error_code=code),))
        except _ProviderTransportFailure as error:
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self._endpoint, params, {}, "unknown", self._terms_profile, now, FetchStatus.FAILED, None, None, error_code=error.code),))
        except TimeoutError:
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self._endpoint, params, {}, "unknown", self._terms_profile, now, FetchStatus.FAILED, None, None, error_code="PROVIDER_TIMEOUT"),))
        except (URLError, OSError) as error:
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self._endpoint, params, {}, "unknown", self._terms_profile, now, FetchStatus.FAILED, None, None, error_code=_transport_error_code(error)),))
        try:
            provider_response = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            provider_response = None
        if isinstance(provider_response, dict) and provider_response.get("code") not in {None, 0}:
            provider_code = provider_response.get("code")
            error_code = (
                "CREDENTIAL_EXPIRED"
                if provider_code == 2002
                else f"PROVIDER_API_ERROR_{provider_code}"
                if isinstance(provider_code, int)
                else "PROVIDER_API_REJECTED"
            )
            return FetchBatch((RawEnvelope(
                self._source_identity, self._source_authority, self._endpoint, params,
                response.headers, "provider_defined", self._terms_profile, now,
                FetchStatus.FAILED, payload, hashlib.sha256(payload).hexdigest(),
                cursor_value=None, error_code=error_code,
            ),))
        return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self._endpoint, params, response.headers, "provider_defined", self._terms_profile, now, FetchStatus.COMPLETE, payload, hashlib.sha256(payload).hexdigest(), cursor_value=_cursor_value(query)),))
