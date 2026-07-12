from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from trading_platform.domain.data import FetchBatch, FetchRequest, FetchStatus, RawEnvelope, SourceAuthority


@dataclass(frozen=True)
class TransportResponse:
    body: bytes
    headers: Mapping[str, str]


class FixtureProvider:
    fixture = True

    def __init__(self, provider_id: str, adapter_version: str, payloads: Mapping[str, bytes], source_identity: str, terms_profile: str, source_authority: SourceAuthority = SourceAuthority.FIXTURE) -> None:
        self.provider_id = provider_id
        self.adapter_version = adapter_version
        self._payloads = dict(payloads)
        self._source_identity = source_identity
        self._terms_profile = terms_profile
        self._source_authority = source_authority
        self.endpoint = "fixture://local-replay"

    def fetch(self, request: FetchRequest) -> FetchBatch:
        payload = self._payloads.get(request.dataset)
        return FetchBatch((RawEnvelope(
            source_identity=self._source_identity,
            source_authority=self._source_authority,
            real_source_url=self.endpoint,
            redacted_params=request.canonical_params,
            response_headers={},
            source_time_precision="microsecond",
            terms_profile=self._terms_profile,
            retrieved_at=datetime.now(timezone.utc),
            status=FetchStatus.COMPLETE if payload is not None else FetchStatus.MISSING,
            payload=payload,
            raw_sha256=hashlib.sha256(payload).hexdigest() if payload is not None else None,
            cursor_value=request.range_end if payload is not None else None,
            error_code=None if payload is not None else "FIXTURE_DATASET_MISSING",
        ),))


class HttpJsonProvider:
    fixture = False

    def __init__(self, provider_id: str, adapter_version: str, endpoint: str, credential: str, source_identity: str, terms_profile: str, transport: Callable[[Request], TransportResponse | bytes] | None = None, source_authority: SourceAuthority = SourceAuthority.STRUCTURED_AGGREGATOR, api_name_map: Mapping[str, str] | None = None) -> None:
        self.provider_id = provider_id
        self.adapter_version = adapter_version
        self._endpoint = endpoint
        self.endpoint = endpoint
        self._credential = credential
        self._source_identity = source_identity
        self._terms_profile = terms_profile
        self._source_authority = source_authority
        self._transport = transport or self._default_transport
        self._api_name_map = dict(api_name_map or {})

    @staticmethod
    def _default_transport(request: Request) -> TransportResponse:
        with urlopen(request, timeout=30) as response:
            return TransportResponse(response.read(), dict(response.headers.items()))

    def fetch(self, request: FetchRequest) -> FetchBatch:
        now = datetime.now(timezone.utc)
        if not request.network_authorized:
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self.endpoint, request.canonical_params, {}, "unknown", self._terms_profile, now, FetchStatus.FAILED, None, None, error_code="NETWORK_NOT_AUTHORIZED"),))
        body = json.dumps({"api_name": self._api_name_map.get(request.dataset, request.dataset), "token": self._credential, "params": dict(request.canonical_params)}, sort_keys=True).encode("utf-8")
        try:
            response = self._transport(Request(self._endpoint, data=body, headers={"Content-Type": "application/json"}))
            if isinstance(response, bytes):
                response = TransportResponse(response, {})
            payload = response.body
        except HTTPError as error:
            status = FetchStatus.RATE_LIMITED if error.code == 429 else FetchStatus.FAILED
            headers = {key: value for key, value in error.headers.items()} if error.headers else {}
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self.endpoint, request.canonical_params, headers, "http-date", self._terms_profile, now, status, None, None, error_code="RATE_LIMITED" if error.code == 429 else "PROVIDER_HTTP_FAILED"),))
        except Exception:
            return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self.endpoint, request.canonical_params, {}, "unknown", self._terms_profile, now, FetchStatus.FAILED, None, None, error_code="PROVIDER_TRANSPORT_FAILED"),))
        return FetchBatch((RawEnvelope(self._source_identity, self._source_authority, self.endpoint, request.canonical_params, response.headers, "provider_defined", self._terms_profile, now, FetchStatus.COMPLETE, payload, hashlib.sha256(payload).hexdigest(), cursor_value=request.range_end),))


class TushareCompatibleProvider(HttpJsonProvider):
    """Deterministic adapter for a Tushare-Pro-compatible HTTP surface."""

    def __init__(self, provider_id: str, adapter_version: str, endpoint: str, credential: str, source_identity: str, terms_profile: str, transport: Callable[[Request], TransportResponse | bytes] | None = None) -> None:
        super().__init__(provider_id, adapter_version, endpoint, credential, source_identity, terms_profile, transport, SourceAuthority.STRUCTURED_AGGREGATOR, {"market_universe": "stock_basic"})
