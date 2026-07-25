from __future__ import annotations

import base64
import hashlib
import json
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from trading_platform.domain.data import (
    FetchBatch,
    FetchStatus,
    OfficialFilingQuery,
    MarketDataCapability,
    ProviderCapability,
    ProviderCapabilityStatus,
    RawEnvelope,
    SourceAuthority,
    TypedDatasetQuery,
)

from .providers import TransportResponse


_SZSE_INDEX_ENDPOINT = (
    "https://www.szse.cn/api/disc/announcement/annList"
)
_SZSE_DOCUMENT_ORIGIN = "https://disc.static.szse.cn/download"
_CNINFO_SECURITY_ENDPOINT = (
    "https://www.cninfo.com.cn/new/data/szse_stock.json"
)
_CNINFO_INDEX_ENDPOINT = (
    "https://www.cninfo.com.cn/new/hisAnnouncement/query"
)
_CNINFO_DOCUMENT_ORIGIN = "https://static.cninfo.com.cn/"
_MAX_INDEX_BYTES = 2 * 1024 * 1024
_MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
_MAX_BATCH_DOCUMENTS = 100
_MAX_BATCH_DOCUMENT_BYTES = 128 * 1024 * 1024
_RETAINED_HEADERS = {"content-type", "date", "retry-after"}
_INDEX_ENDPOINTS = {
    _SZSE_INDEX_ENDPOINT,
    _CNINFO_SECURITY_ENDPOINT,
    _CNINFO_INDEX_ENDPOINT,
}


class _OfficialTransportFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise _OfficialTransportFailure("OFFICIAL_REDIRECT_BLOCKED")


def _retained_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in _RETAINED_HEADERS
    }


def _transport_error_code(error: BaseException) -> str:
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        return "OFFICIAL_DNS_FAILED"
    if isinstance(reason, ssl.SSLError):
        return "OFFICIAL_TLS_FAILED"
    if isinstance(reason, ConnectionRefusedError):
        return "OFFICIAL_CONNECTION_REFUSED"
    if isinstance(reason, TimeoutError):
        return "OFFICIAL_TIMEOUT"
    return "OFFICIAL_TRANSPORT_FAILED"


def _published_at(value: object) -> str:
    text = str(value)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        raise _OfficialTransportFailure(
            "OFFICIAL_FILING_PUBLISHED_AT_INVALID"
        ) from None
    return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()


def _correction_status(value: object) -> str:
    if not isinstance(value, str):
        raise _OfficialTransportFailure(
            "OFFICIAL_FILING_TITLE_INVALID"
        )
    if "更正" in value or "纠正" in value:
        return "corrected"
    if "修订" in value or "修正" in value:
        return "amended"
    return "original"


def _filing_capabilities() -> tuple[ProviderCapability, ...]:
    return tuple(
        ProviderCapability(
            capability,
            ProviderCapabilityStatus.UNAVAILABLE,
            "not_applicable:filing_dataset",
        )
        for capability in (
            MarketDataCapability.TRADING_CALENDAR,
            MarketDataCapability.ADJUSTMENT_FACTORS,
            MarketDataCapability.CORPORATE_ACTIONS,
            MarketDataCapability.SUSPENSION_STATUS,
            MarketDataCapability.PRICE_LIMIT_STATUS,
            MarketDataCapability.T_PLUS_ONE,
        )
    )


def _security_code(value: object) -> str:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, str) or not value.isdigit():
        raise _OfficialTransportFailure(
            "OFFICIAL_FILING_SECURITY_IDENTITY_INVALID"
        )
    return value


def _document_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or ".." in value
        or "?" in value
        or "#" in value
    ):
        raise _OfficialTransportFailure(
            "OFFICIAL_FILING_DOCUMENT_PATH_INVALID"
        )
    return value


class SzseOfficialDisclosureProvider:
    """Own SZSE announcement discovery, identity validation, and PDF acquisition."""

    provider_id = "szse-official-disclosure"
    adapter_version = "szse-announcement@1"
    fixture = False
    capabilities = _filing_capabilities()
    source_identity = "szse-statutory-disclosure"
    terms_profile = "szse-local-noncommercial@2026-07-24"

    def __init__(
        self,
        transport: Callable[[Request], TransportResponse] | None = None,
    ) -> None:
        self._transport = transport or self._default_transport
        self.code_identity = "sha256:" + hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        self.transport_identity = hashlib.sha256(
            (
                self.provider_id
                + self.adapter_version
                + _SZSE_INDEX_ENDPOINT
                + _SZSE_DOCUMENT_ORIGIN
            ).encode()
        ).hexdigest()

    @staticmethod
    def _default_transport(request: Request) -> TransportResponse:
        with build_opener(_RejectRedirects()).open(
            request, timeout=30
        ) as response:
            maximum = (
                _MAX_INDEX_BYTES
                if request.full_url in _INDEX_ENDPOINTS
                else _MAX_DOCUMENT_BYTES
            )
            body = response.read(maximum + 1)
            if len(body) > maximum:
                raise _OfficialTransportFailure(
                    "OFFICIAL_RESPONSE_OVERSIZE"
                )
            return TransportResponse(
                body, _retained_headers(dict(response.headers.items()))
            )

    def fetch(self, query: TypedDatasetQuery) -> FetchBatch:
        now = datetime.now(timezone.utc)
        params = {
            "security_id": getattr(query, "security_id", ""),
            "venue": getattr(query, "venue", ""),
            "start_date": getattr(query, "start_date", ""),
            "end_date": getattr(query, "end_date", ""),
        }
        if not isinstance(query, OfficialFilingQuery):
            return self._failure(
                now, params, "OFFICIAL_QUERY_UNSUPPORTED"
            )
        if query.venue != "SZSE" or not query.security_code.isdigit():
            return self._failure(
                now, params, "OFFICIAL_FILING_SECURITY_IDENTITY_INVALID"
            )
        if not query.network_authorized:
            return self._failure(now, params, "NETWORK_NOT_AUTHORIZED")
        try:
            rows: list[object] = []
            retained_headers: dict[str, str] = {}
            page_number = 1
            while True:
                body = json.dumps(
                    {
                        "channelCode": ["listedNotice_disc"],
                        "pageSize": 30,
                        "pageNum": page_number,
                        "stock": [query.security_code],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                response = self._transport(
                    Request(
                        _SZSE_INDEX_ENDPOINT,
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": (
                                "tradingSystem/1.0 local-research"
                            ),
                            "Referer": (
                                "https://www.szse.cn/disclosure/listed/"
                                "notice/index.html"
                            ),
                        },
                    )
                )
                retained_headers = _retained_headers(response.headers)
                if len(response.body) > _MAX_INDEX_BYTES:
                    raise _OfficialTransportFailure(
                        "OFFICIAL_RESPONSE_OVERSIZE"
                    )
                decoded = json.loads(response.body)
                page_rows = (
                    decoded.get("data")
                    if isinstance(decoded, dict)
                    else None
                )
                if not isinstance(page_rows, list):
                    raise _OfficialTransportFailure(
                        "OFFICIAL_FILING_SCHEMA_DRIFT"
                    )
                dated_rows: list[object] = []
                page_dates = []
                for item in page_rows:
                    if not isinstance(item, dict):
                        dated_rows.append(item)
                        continue
                    published_date = _published_at(
                        item.get("publishTime")
                    )[:10]
                    page_dates.append(published_date)
                    if query.start_date <= published_date <= query.end_date:
                        dated_rows.append(item)
                rows.extend(dated_rows)
                explicit_more = (
                    decoded.get("hasNextPage")
                    if isinstance(decoded, dict)
                    else None
                )
                total = (
                    (
                        decoded.get("totalSize")
                        if "totalSize" in decoded
                        else decoded.get("announceCount")
                    )
                    if isinstance(decoded, dict)
                    else None
                )
                has_more = (
                    explicit_more
                    if isinstance(explicit_more, bool)
                    else isinstance(total, int) and len(rows) < total
                )
                passed_start_boundary = (
                    bool(page_dates)
                    and min(page_dates) < query.start_date
                )
                if not has_more or passed_start_boundary:
                    break
                if not page_rows or page_number >= 50:
                    raise _OfficialTransportFailure(
                        "OFFICIAL_FILING_PARTIAL"
                    )
                page_number += 1
            if not rows:
                return self._failure(
                    now, params, "OFFICIAL_FILING_EMPTY_CONFIRMED",
                    FetchStatus.MISSING,
                )
            if len(rows) > _MAX_BATCH_DOCUMENTS:
                raise _OfficialTransportFailure(
                    "OFFICIAL_FILING_PARTIAL"
                )
            filings = []
            total_document_bytes = 0
            for item in rows:
                if not isinstance(item, dict):
                    continue
                filing = self._filing(query, item, now)
                total_document_bytes += int(filing["byte_size"])
                if total_document_bytes > _MAX_BATCH_DOCUMENT_BYTES:
                    raise _OfficialTransportFailure(
                        "OFFICIAL_FILING_PARTIAL"
                    )
                filings.append(filing)
            if len(filings) != len(rows):
                raise _OfficialTransportFailure(
                    "OFFICIAL_FILING_SCHEMA_DRIFT"
                )
            payload = json.dumps(
                {"rows": filings},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            return FetchBatch(
                (
                    RawEnvelope(
                        self.source_identity,
                        SourceAuthority.OFFICIAL,
                        _SZSE_INDEX_ENDPOINT,
                        params,
                        retained_headers,
                        "second",
                        self.terms_profile,
                        now,
                        FetchStatus.COMPLETE,
                        payload,
                        hashlib.sha256(payload).hexdigest(),
                        cursor_value=query.end_date,
                    ),
                )
            )
        except HTTPError as error:
            status = (
                FetchStatus.RATE_LIMITED
                if error.code == 429
                else FetchStatus.FAILED
            )
            code = {
                401: "AUTHENTICATION_FAILED",
                403: "ACCESS_FORBIDDEN",
                429: "RATE_LIMITED",
            }.get(error.code, "OFFICIAL_HTTP_FAILED")
            return self._failure(now, params, code, status)
        except _OfficialTransportFailure as error:
            return self._failure(
                now,
                params,
                error.code,
                (
                    FetchStatus.PARTIAL
                    if error.code == "OFFICIAL_FILING_PARTIAL"
                    else FetchStatus.FAILED
                ),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._failure(
                now, params, "OFFICIAL_FILING_SCHEMA_DRIFT"
            )
        except (URLError, OSError) as error:
            return self._failure(
                now, params, _transport_error_code(error)
            )

    def _filing(
        self,
        query: OfficialFilingQuery,
        item: Mapping[str, object],
        retrieved_at: datetime,
    ) -> dict[str, object]:
        if _security_code(item.get("secCode")) != query.security_code:
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_SECURITY_IDENTITY_MISMATCH"
            )
        announcement_id = item.get("annId")
        if (
            not isinstance(announcement_id, (str, int))
            or isinstance(announcement_id, bool)
            or str(announcement_id).strip() == ""
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_DOCUMENT_IDENTITY_INVALID"
            )
        announcement_id = str(announcement_id)
        path = _document_path(item.get("attachPath"))
        response = self._transport(
            Request(
                _SZSE_DOCUMENT_ORIGIN + path,
                headers={
                    "User-Agent": "tradingSystem/1.0 local-research"
                },
            )
        )
        content_type = next(
            (
                value
                for key, value in response.headers.items()
                if key.lower() == "content-type"
            ),
            "",
        ).split(";")[0].strip().lower()
        if (
            content_type != "application/pdf"
            or not response.body.startswith(b"%PDF-")
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_DOCUMENT_MIME_INVALID"
            )
        if (
            len(response.body) > _MAX_DOCUMENT_BYTES
            or b"/JavaScript" in response.body
            or b"/Launch" in response.body
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_DOCUMENT_QUARANTINED"
            )
        published = _published_at(item.get("publishTime"))
        return {
            "security_id": query.security_id,
            "issuer_identity": (
                f"cn-a-share:{query.venue}:{query.security_code}"
            ),
            "authority": "SZSE",
            "document_identity": f"szse:{announcement_id}",
            "accession_or_document_id": announcement_id,
            "filing_type": "statutory_announcement",
            "report_period_end": None,
            "document_sha256": hashlib.sha256(
                response.body
            ).hexdigest(),
            "document_base64": base64.b64encode(
                response.body
            ).decode("ascii"),
            "content_type": "application/pdf",
            "byte_size": len(response.body),
            "correction_status": _correction_status(item.get("title")),
            "published_at": published,
            "published_precision": "second",
            "available_at": retrieved_at.isoformat(),
            "availability_basis": "retrieved_only",
        }

    def _failure(
        self,
        retrieved_at: datetime,
        params: Mapping[str, str],
        code: str,
        status: FetchStatus = FetchStatus.FAILED,
    ) -> FetchBatch:
        return FetchBatch(
            (
                RawEnvelope(
                    self.source_identity,
                    SourceAuthority.OFFICIAL,
                    _SZSE_INDEX_ENDPOINT,
                    params,
                    {},
                    "unknown",
                    self.terms_profile,
                    retrieved_at,
                    status,
                    None,
                    None,
                    error_code=code,
                ),
            )
        )


class CninfoOfficialDisclosureProvider:
    """Own CNINFO exact issuer resolution, announcement discovery, and PDFs."""

    provider_id = "cninfo-official-disclosure"
    adapter_version = "cninfo-announcement@1"
    fixture = False
    capabilities = _filing_capabilities()
    source_identity = "cninfo-statutory-disclosure"
    terms_profile = "cninfo-local-noncommercial@2026-07-24"

    def __init__(
        self,
        transport: Callable[[Request], TransportResponse] | None = None,
    ) -> None:
        self._transport = (
            transport or SzseOfficialDisclosureProvider._default_transport
        )
        self.code_identity = "sha256:" + hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        self.transport_identity = hashlib.sha256(
            (
                self.provider_id
                + self.adapter_version
                + _CNINFO_SECURITY_ENDPOINT
                + _CNINFO_INDEX_ENDPOINT
                + _CNINFO_DOCUMENT_ORIGIN
            ).encode()
        ).hexdigest()

    def fetch(self, query: TypedDatasetQuery) -> FetchBatch:
        now = datetime.now(timezone.utc)
        params = {
            "security_id": getattr(query, "security_id", ""),
            "venue": getattr(query, "venue", ""),
            "start_date": getattr(query, "start_date", ""),
            "end_date": getattr(query, "end_date", ""),
        }
        if not isinstance(query, OfficialFilingQuery):
            return self._failure(
                now, params, "OFFICIAL_QUERY_UNSUPPORTED"
            )
        if (
            query.venue not in {"SSE", "SZSE", "BSE"}
            or not query.security_code.isdigit()
        ):
            return self._failure(
                now, params, "OFFICIAL_FILING_SECURITY_IDENTITY_INVALID"
            )
        if not query.network_authorized:
            return self._failure(now, params, "NETWORK_NOT_AUTHORIZED")
        try:
            mapping_response = self._transport(
                Request(
                    _CNINFO_SECURITY_ENDPOINT,
                    headers={
                        "User-Agent": (
                            "tradingSystem/1.0 local-research"
                        )
                    },
                )
            )
            if len(mapping_response.body) > _MAX_INDEX_BYTES:
                raise _OfficialTransportFailure(
                    "OFFICIAL_RESPONSE_OVERSIZE"
                )
            mapping = json.loads(mapping_response.body)
            stocks = (
                mapping.get("stockList")
                if isinstance(mapping, dict)
                else None
            )
            if not isinstance(stocks, list):
                raise _OfficialTransportFailure(
                    "OFFICIAL_SECURITY_MAP_SCHEMA_DRIFT"
                )
            matches = [
                item
                for item in stocks
                if isinstance(item, dict)
                and item.get("code") == query.security_code
                and isinstance(item.get("orgId"), str)
                and item["orgId"]
            ]
            if len(matches) != 1:
                raise _OfficialTransportFailure(
                    "OFFICIAL_SECURITY_IDENTITY_UNRESOLVED"
                )
            org_id = matches[0]["orgId"]
            rows: list[object] = []
            retained_headers: dict[str, str] = {}
            page_number = 1
            while True:
                form = urlencode(
                    {
                        "stock": f"{query.security_code},{org_id}",
                        "tabName": "fulltext",
                        "pageSize": "30",
                        "pageNum": str(page_number),
                        "column": "",
                        "category": "",
                        "plate": "",
                        "seDate": (
                            f"{query.start_date}~{query.end_date}"
                        ),
                        "searchkey": "",
                        "secid": "",
                        "sortName": "",
                        "sortType": "",
                        "isHLtitle": "true",
                    }
                ).encode()
                response = self._transport(
                    Request(
                        _CNINFO_INDEX_ENDPOINT,
                        data=form,
                        headers={
                            "User-Agent": (
                                "tradingSystem/1.0 local-research"
                            ),
                            "Content-Type": (
                                "application/x-www-form-urlencoded"
                            ),
                            "Referer": (
                                "https://www.cninfo.com.cn/new/disclosure"
                            ),
                            "Origin": "https://www.cninfo.com.cn",
                        },
                    )
                )
                retained_headers = _retained_headers(response.headers)
                if len(response.body) > _MAX_INDEX_BYTES:
                    raise _OfficialTransportFailure(
                        "OFFICIAL_RESPONSE_OVERSIZE"
                    )
                decoded = json.loads(response.body)
                page_rows = (
                    decoded.get("announcements")
                    if isinstance(decoded, dict)
                    else None
                )
                if (
                    page_rows is None
                    and isinstance(decoded, dict)
                    and decoded.get("totalAnnouncement") == 0
                    and page_number == 1
                ):
                    page_rows = []
                if not isinstance(page_rows, list):
                    raise _OfficialTransportFailure(
                        "OFFICIAL_FILING_SCHEMA_DRIFT"
                    )
                rows.extend(page_rows)
                explicit_more = (
                    decoded.get("hasMore")
                    if isinstance(decoded, dict)
                    else None
                )
                total = (
                    decoded.get("totalAnnouncement")
                    if isinstance(decoded, dict)
                    else None
                )
                has_more = (
                    explicit_more
                    if isinstance(explicit_more, bool)
                    else isinstance(total, int) and len(rows) < total
                )
                if not has_more:
                    break
                if not page_rows or page_number >= 50:
                    raise _OfficialTransportFailure(
                        "OFFICIAL_FILING_PARTIAL"
                    )
                page_number += 1
            if not rows:
                return self._failure(
                    now,
                    params,
                    "OFFICIAL_FILING_EMPTY_CONFIRMED",
                    FetchStatus.MISSING,
                )
            if len(rows) > _MAX_BATCH_DOCUMENTS:
                raise _OfficialTransportFailure(
                    "OFFICIAL_FILING_PARTIAL"
                )
            filings = []
            total_document_bytes = 0
            for item in rows:
                if not isinstance(item, dict):
                    continue
                filing = self._filing(query, org_id, item, now)
                published_date = str(filing["published_at"])[:10]
                if not (
                    query.start_date <= published_date <= query.end_date
                ):
                    raise _OfficialTransportFailure(
                        "OFFICIAL_FILING_DATE_WINDOW_MISMATCH"
                    )
                total_document_bytes += int(filing["byte_size"])
                if total_document_bytes > _MAX_BATCH_DOCUMENT_BYTES:
                    raise _OfficialTransportFailure(
                        "OFFICIAL_FILING_PARTIAL"
                    )
                filings.append(filing)
            if len(filings) != len(rows):
                raise _OfficialTransportFailure(
                    "OFFICIAL_FILING_SCHEMA_DRIFT"
                )
            payload = json.dumps(
                {"rows": filings},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            return FetchBatch(
                (
                    RawEnvelope(
                        self.source_identity,
                        SourceAuthority.OFFICIAL,
                        _CNINFO_INDEX_ENDPOINT,
                        params,
                        retained_headers,
                        "millisecond",
                        self.terms_profile,
                        now,
                        FetchStatus.COMPLETE,
                        payload,
                        hashlib.sha256(payload).hexdigest(),
                        cursor_value=query.end_date,
                    ),
                )
            )
        except HTTPError as error:
            status = (
                FetchStatus.RATE_LIMITED
                if error.code == 429
                else FetchStatus.FAILED
            )
            code = {
                401: "AUTHENTICATION_FAILED",
                403: "ACCESS_FORBIDDEN",
                429: "RATE_LIMITED",
            }.get(error.code, "OFFICIAL_HTTP_FAILED")
            return self._failure(now, params, code, status)
        except _OfficialTransportFailure as error:
            return self._failure(
                now,
                params,
                error.code,
                (
                    FetchStatus.PARTIAL
                    if error.code == "OFFICIAL_FILING_PARTIAL"
                    else FetchStatus.FAILED
                ),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._failure(
                now, params, "OFFICIAL_FILING_SCHEMA_DRIFT"
            )
        except (URLError, OSError) as error:
            return self._failure(
                now, params, _transport_error_code(error)
            )

    def _filing(
        self,
        query: OfficialFilingQuery,
        org_id: str,
        item: Mapping[str, object],
        retrieved_at: datetime,
    ) -> dict[str, object]:
        if (
            item.get("secCode") != query.security_code
            or item.get("orgId") != org_id
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_SECURITY_IDENTITY_MISMATCH"
            )
        announcement_id = item.get("announcementId")
        if (
            not isinstance(announcement_id, (str, int))
            or isinstance(announcement_id, bool)
            or str(announcement_id).strip() == ""
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_DOCUMENT_IDENTITY_INVALID"
            )
        announcement_id = str(announcement_id)
        path = item.get("adjunctUrl")
        if (
            not isinstance(path, str)
            or path.startswith("/")
            or ".." in path
            or "?" in path
            or "#" in path
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_DOCUMENT_PATH_INVALID"
            )
        response = self._transport(
            Request(
                _CNINFO_DOCUMENT_ORIGIN + path,
                headers={
                    "User-Agent": "tradingSystem/1.0 local-research"
                },
            )
        )
        content_type = next(
            (
                value
                for key, value in response.headers.items()
                if key.lower() == "content-type"
            ),
            "",
        ).split(";")[0].strip().lower()
        if (
            content_type != "application/pdf"
            or not response.body.startswith(b"%PDF-")
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_DOCUMENT_MIME_INVALID"
            )
        if (
            len(response.body) > _MAX_DOCUMENT_BYTES
            or b"/JavaScript" in response.body
            or b"/Launch" in response.body
        ):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_DOCUMENT_QUARANTINED"
            )
        timestamp = item.get("announcementTime")
        if not isinstance(timestamp, (int, float)):
            raise _OfficialTransportFailure(
                "OFFICIAL_FILING_PUBLISHED_AT_INVALID"
            )
        published = datetime.fromtimestamp(
            timestamp / 1000, timezone.utc
        ).isoformat()
        return {
            "security_id": query.security_id,
            "issuer_identity": f"cninfo:{org_id}",
            "authority": "CNINFO",
            "document_identity": f"cninfo:{announcement_id}",
            "accession_or_document_id": announcement_id,
            "filing_type": "statutory_announcement",
            "report_period_end": None,
            "document_sha256": hashlib.sha256(
                response.body
            ).hexdigest(),
            "document_base64": base64.b64encode(
                response.body
            ).decode("ascii"),
            "content_type": "application/pdf",
            "byte_size": len(response.body),
            "correction_status": _correction_status(
                item.get("announcementTitle")
                or item.get("announcementTypeName")
            ),
            "published_at": published,
            "published_precision": "millisecond",
            "available_at": retrieved_at.isoformat(),
            "availability_basis": "retrieved_only",
        }

    def _failure(
        self,
        retrieved_at: datetime,
        params: Mapping[str, str],
        code: str,
        status: FetchStatus = FetchStatus.FAILED,
    ) -> FetchBatch:
        return FetchBatch(
            (
                RawEnvelope(
                    self.source_identity,
                    SourceAuthority.OFFICIAL,
                    _CNINFO_INDEX_ENDPOINT,
                    params,
                    {},
                    "unknown",
                    self.terms_profile,
                    retrieved_at,
                    status,
                    None,
                    None,
                    error_code=code,
                ),
            )
        )


__all__ = [
    "CninfoOfficialDisclosureProvider",
    "SzseOfficialDisclosureProvider",
]
