from __future__ import annotations

import hashlib
import base64
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs

import pytest

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_data_sync_pit import (
    FIXTURE_SOURCE,
    _composition,
    _payloads,
    _request,
    _rights,
)
from trading_platform.application import (
    open_platform_operations,
    open_provider_qualification,
)
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.data.official_disclosures import (
    CninfoOfficialDisclosureProvider,
    SzseOfficialDisclosureProvider,
)
from trading_platform.data import official_disclosures as official_module
from trading_platform.data.providers import FixtureProvider, TransportResponse
from trading_platform.data.normalizer import normalize
from trading_platform.domain.data import (
    CompletenessRequirement,
    FetchBatch,
    FetchStatus,
    FallbackMode,
    OfficialFilingQuery,
    SourceFailureDisposition,
    SourcePolicy,
    SourceRoute,
    SyncStatus,
    SnapshotPurpose,
    QueryPolicy,
    RawEnvelope,
    SourceAuthority,
    SourceRights,
    SyncRequest,
)
from trading_platform.provider_config import (
    DecodedProviderJob,
    ProviderRuntimeBinding,
    canonical_official_source_policy,
    load_sync_job,
)
from trading_platform.persistence.locking import PersistenceError


def _filing_payload() -> bytes:
    document = b"%PDF-1.7\nA-share statutory disclosure fixture\n%%EOF\n"
    return json.dumps(
        {
            "rows": [
                {
                    "security_id": "security_yihua",
                    "issuer_identity": "issuer_002897_szse",
                    "authority": "SZSE",
                    "document_identity": "szse:notice:2026-001",
                    "accession_or_document_id": "2026-001",
                    "filing_type": "annual_report",
                    "report_period_end": "2025-12-31",
                    "document_sha256": hashlib.sha256(document).hexdigest(),
                    "document_base64": base64.b64encode(document).decode("ascii"),
                    "content_type": "application/pdf",
                    "byte_size": len(document),
                    "correction_status": "original",
                    "published_at": "2026-04-18T09:00:00+08:00",
                    "published_precision": "second",
                    "available_at": "2026-04-18T09:00:00+08:00",
                    "availability_basis": "publisher_timestamp",
                }
            ]
        },
        sort_keys=True,
    ).encode("utf-8")


def test_szse_adapter_owns_verified_protocol_identity_and_document_bytes() -> None:
    document = b"%PDF-1.7\nsynthetic SZSE filing\n%%EOF\n"
    calls = []

    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return TransportResponse(
                json.dumps(
                    {
                        "data": [
                            {
                                "annId": "synthetic-announcement",
                                "secCode": ["002897"],
                                "publishTime": "2026-04-18 09:00:00",
                                "attachPath": "/synthetic.pdf",
                                "attachSize": len(document),
                                "attachFormat": "PDF",
                                "title": "Synthetic annual report",
                            }
                        ]
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        return TransportResponse(
            document, {"Content-Type": "application/pdf"}
        )

    provider = SzseOfficialDisclosureProvider(transport=transport)
    query = OfficialFilingQuery(
        "szse-adapter",
        "security_yihua",
        "002897",
        "SZSE",
        "2026-04-01",
        "2026-04-30",
        None,
        "security_yihua",
        True,
    )

    envelope = provider.fetch(query).envelopes[0]
    decoded = json.loads(envelope.payload)
    filing = decoded["rows"][0]

    assert envelope.status.value == "complete"
    assert envelope.source_authority.value == "official"
    assert filing["security_id"] == "security_yihua"
    assert filing["authority"] == "SZSE"
    assert filing["document_identity"] == "szse:synthetic-announcement"
    assert filing["correction_status"] == "original"
    assert filing["document_sha256"] == hashlib.sha256(document).hexdigest()
    assert base64.b64decode(filing["document_base64"]) == document
    assert calls[0].full_url == (
        "https://www.szse.cn/api/disc/announcement/annList"
    )
    assert calls[1].full_url == (
        "https://disc.static.szse.cn/download/synthetic.pdf"
    )
    assert calls[0].data is not None
    assert b"002897" in calls[0].data


@pytest.mark.parametrize(
    ("index_payload", "document", "document_content_type", "expected_code"),
    (
        (
            {"data": []},
            None,
            None,
            "OFFICIAL_FILING_EMPTY_CONFIRMED",
        ),
        (
            {"unexpected": []},
            None,
            None,
            "OFFICIAL_FILING_SCHEMA_DRIFT",
        ),
        (
            {
                "data": [
                    {
                        "annId": "wrong-issuer",
                        "secCode": ["000001"],
                        "publishTime": "2026-04-18 09:00:00",
                        "attachPath": "/wrong.pdf",
                    }
                ]
            },
            None,
            None,
            "OFFICIAL_FILING_SECURITY_IDENTITY_MISMATCH",
        ),
        (
            {
                "data": [
                    {
                        "annId": "wrong-mime",
                        "secCode": ["002897"],
                        "publishTime": "2026-04-18 09:00:00",
                        "attachPath": "/wrong.pdf",
                    }
                ]
            },
            b"<html>not a PDF</html>",
            "text/html",
            "OFFICIAL_FILING_DOCUMENT_MIME_INVALID",
        ),
        (
            {
                "data": [
                    {
                        "annId": "active-content",
                        "secCode": ["002897"],
                        "publishTime": "2026-04-18 09:00:00",
                        "attachPath": "/active.pdf",
                    }
                ]
            },
            b"%PDF-1.7\n/JavaScript\n%%EOF\n",
            "application/pdf",
            "OFFICIAL_FILING_DOCUMENT_QUARANTINED",
        ),
        (
            {
                "data": [
                    {
                        "annId": "invalid-time",
                        "secCode": ["002897"],
                        "publishTime": "not-a-time",
                        "attachPath": "/invalid-time.pdf",
                    }
                ]
            },
            b"%PDF-1.7\ninvalid timestamp\n%%EOF\n",
            "application/pdf",
            "OFFICIAL_FILING_PUBLISHED_AT_INVALID",
        ),
    ),
)
def test_szse_adapter_fails_closed_with_distinct_evidence_codes(
    index_payload: dict[str, object],
    document: bytes | None,
    document_content_type: str | None,
    expected_code: str,
) -> None:
    calls = 0

    def transport(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TransportResponse(
                json.dumps(index_payload).encode(),
                {"Content-Type": "application/json"},
            )
        assert document is not None and document_content_type is not None
        return TransportResponse(
            document, {"Content-Type": document_content_type}
        )

    envelope = SzseOfficialDisclosureProvider(
        transport=transport
    ).fetch(
        OfficialFilingQuery(
            "szse-failure",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.error_code == expected_code
    assert envelope.payload is None
    assert envelope.status.value == (
        "missing"
        if expected_code == "OFFICIAL_FILING_EMPTY_CONFIRMED"
        else "failed"
    )


def test_szse_adapter_owns_pagination_before_declaring_complete() -> None:
    document = b"%PDF-1.7\npaged filing\n%%EOF\n"
    pages: list[int] = []

    def transport(request):
        if request.full_url.endswith("/annList"):
            page = json.loads(request.data)["pageNum"]
            pages.append(page)
            return TransportResponse(
                json.dumps(
                    {
                        "data": [
                            {
                                "annId": f"page-{page}",
                                "secCode": ["002897"],
                                "publishTime": "2026-04-18 09:00:00",
                                "attachPath": f"/page-{page}.pdf",
                                "title": "Synthetic filing",
                            }
                        ],
                        "hasNextPage": page == 1,
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        return TransportResponse(
            document, {"Content-Type": "application/pdf"}
        )

    envelope = SzseOfficialDisclosureProvider(
        transport=transport
    ).fetch(
        OfficialFilingQuery(
            "szse-pagination",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.status.value == "complete"
    assert pages == [1, 2]
    assert len(json.loads(envelope.payload)["rows"]) == 2


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_status"),
    (
        (
            HTTPError("https://official.invalid", 401, "unauthorized", {}, None),
            "AUTHENTICATION_FAILED",
            "failed",
        ),
        (
            HTTPError("https://official.invalid", 403, "forbidden", {}, None),
            "ACCESS_FORBIDDEN",
            "failed",
        ),
        (
            HTTPError("https://official.invalid", 429, "limited", {}, None),
            "RATE_LIMITED",
            "rate_limited",
        ),
        (TimeoutError(), "OFFICIAL_TIMEOUT", "failed"),
    ),
)
@pytest.mark.parametrize(
    "provider_type",
    (SzseOfficialDisclosureProvider, CninfoOfficialDisclosureProvider),
)
def test_official_adapters_preserve_transport_failure_semantics(
    provider_type,
    failure: BaseException,
    expected_code: str,
    expected_status: str,
) -> None:
    def transport(_request):
        raise failure

    envelope = provider_type(
        transport=transport
    ).fetch(
        OfficialFilingQuery(
            "szse-transport",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.error_code == expected_code
    assert envelope.status.value == expected_status
    assert envelope.payload is None


def test_szse_date_window_and_batch_budget_fail_closed_before_documents() -> None:
    document_calls = 0

    def outside_window(request):
        nonlocal document_calls
        if request.full_url.endswith("/annList"):
            return TransportResponse(
                json.dumps(
                    {
                        "data": [
                            {
                                "annId": "outside-window",
                                "secCode": ["002897"],
                                "publishTime": "2026-03-01 09:00:00",
                                "attachPath": "/outside.pdf",
                                "title": "Outside window",
                            }
                        ],
                        "announceCount": 1,
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        document_calls += 1
        return TransportResponse(
            b"%PDF-1.7\noutside\n%%EOF\n",
            {"Content-Type": "application/pdf"},
        )

    query = OfficialFilingQuery(
        "szse-bounds",
        "security_yihua",
        "002897",
        "SZSE",
        "2026-04-01",
        "2026-04-30",
        None,
        "security_yihua",
        True,
    )
    outside = SzseOfficialDisclosureProvider(
        transport=outside_window
    ).fetch(query).envelopes[0]
    assert outside.status.value == "missing"
    assert outside.error_code == "OFFICIAL_FILING_EMPTY_CONFIRMED"
    assert document_calls == 0

    rows = [
        {
            "annId": f"bounded-{index}",
            "secCode": ["002897"],
            "publishTime": "2026-04-18 09:00:00",
            "attachPath": f"/bounded-{index}.pdf",
            "title": "Bounded filing",
        }
        for index in range(101)
    ]
    partial = SzseOfficialDisclosureProvider(
        transport=lambda _request: TransportResponse(
            json.dumps({"data": rows, "announceCount": len(rows)}).encode(),
            {"Content-Type": "application/json"},
        )
    ).fetch(query).envelopes[0]
    assert partial.status.value == "partial"
    assert partial.error_code == "OFFICIAL_FILING_PARTIAL"
    assert partial.payload is None


def test_szse_document_size_limit_is_enforced_per_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(official_module, "_MAX_DOCUMENT_BYTES", 8)
    calls = 0

    def transport(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TransportResponse(
                json.dumps(
                    {
                        "data": [
                            {
                                "annId": "oversize",
                                "secCode": ["002897"],
                                "publishTime": "2026-04-18 09:00:00",
                                "attachPath": "/oversize.pdf",
                                "title": "Oversize filing",
                            }
                        ],
                        "announceCount": 1,
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        return TransportResponse(
            b"%PDF-1.7\noversize\n%%EOF\n",
            {"Content-Type": "application/pdf"},
        )

    envelope = SzseOfficialDisclosureProvider(
        transport=transport
    ).fetch(
        OfficialFilingQuery(
            "szse-document-bound",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.status.value == "failed"
    assert (
        envelope.error_code
        == "OFFICIAL_FILING_DOCUMENT_QUARANTINED"
    )
    assert envelope.payload is None


def test_cninfo_adapter_requires_https_exact_identity_before_document() -> None:
    document = b"%PDF-1.7\nsynthetic CNINFO filing\n%%EOF\n"
    calls = []

    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return TransportResponse(
                json.dumps(
                    {
                        "stockList": [
                            {
                                "code": "002897",
                                "orgId": "synthetic-org",
                            }
                        ]
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        if len(calls) == 2:
            return TransportResponse(
                json.dumps(
                    {
                        "announcements": [
                            {
                                "announcementId": "synthetic-cninfo",
                                "secCode": "002897",
                                "orgId": "synthetic-org",
                                "announcementTime": 1776474000000,
                                "storageTime": 1776474000000,
                                "adjunctUrl": (
                                    "finalpage/2026-04-18/"
                                    "synthetic-cninfo.PDF"
                                ),
                                "adjunctSize": len(document),
                                "announcementTypeName": "Annual report",
                            }
                        ],
                        "totalAnnouncement": 1,
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        return TransportResponse(
            document, {"Content-Type": "application/pdf"}
        )

    provider = CninfoOfficialDisclosureProvider(transport=transport)
    envelope = provider.fetch(
        OfficialFilingQuery(
            "cninfo-adapter",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]
    filing = json.loads(envelope.payload)["rows"][0]

    assert envelope.status.value == "complete"
    assert filing["authority"] == "CNINFO"
    assert filing["issuer_identity"] == "cninfo:synthetic-org"
    assert filing["document_identity"] == "cninfo:synthetic-cninfo"
    assert filing["correction_status"] == "original"
    assert base64.b64decode(filing["document_base64"]) == document
    assert calls[0].full_url.startswith("https://www.cninfo.com.cn/")
    assert calls[1].full_url == (
        "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    )
    assert b"synthetic-org" in calls[1].data
    assert calls[2].full_url == (
        "https://static.cninfo.com.cn/finalpage/2026-04-18/"
        "synthetic-cninfo.PDF"
    )


@pytest.mark.parametrize(
    ("provider_name", "expected_status"),
    (("szse", "corrected"), ("cninfo", "amended")),
)
def test_official_adapters_preserve_correction_evidence(
    provider_name: str,
    expected_status: str,
) -> None:
    document = b"%PDF-1.7\ncorrected filing\n%%EOF\n"
    calls = 0

    def transport(_request):
        nonlocal calls
        calls += 1
        if provider_name == "szse":
            if calls == 1:
                return TransportResponse(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "annId": "corrected",
                                    "secCode": ["002897"],
                                    "publishTime": "2026-04-18 09:00:00",
                                    "attachPath": "/corrected.pdf",
                                    "title": "年度报告更正公告",
                                }
                            ],
                            "announceCount": 1,
                        }
                    ).encode(),
                    {"Content-Type": "application/json"},
                )
        else:
            if calls == 1:
                return TransportResponse(
                    json.dumps(
                        {
                            "stockList": [
                                {"code": "002897", "orgId": "corrected-org"}
                            ]
                        }
                    ).encode(),
                    {"Content-Type": "application/json"},
                )
            if calls == 2:
                return TransportResponse(
                    json.dumps(
                        {
                            "announcements": [
                                {
                                    "announcementId": "amended",
                                    "secCode": "002897",
                                    "orgId": "corrected-org",
                                    "announcementTime": 1776474000000,
                                    "adjunctUrl": "amended.PDF",
                                    "announcementTitle": "年度报告修订稿",
                                }
                            ],
                            "totalAnnouncement": 1,
                        }
                    ).encode(),
                    {"Content-Type": "application/json"},
                )
        return TransportResponse(
            document, {"Content-Type": "application/pdf"}
        )

    provider = (
        SzseOfficialDisclosureProvider(transport=transport)
        if provider_name == "szse"
        else CninfoOfficialDisclosureProvider(transport=transport)
    )
    filing = json.loads(
        provider.fetch(
            OfficialFilingQuery(
                "correction",
                "security_yihua",
                "002897",
                "SZSE",
                "2026-04-01",
                "2026-04-30",
                None,
                "security_yihua",
                True,
            )
        ).envelopes[0].payload
    )["rows"][0]
    assert filing["correction_status"] == expected_status


def test_cninfo_adapter_owns_pagination_before_declaring_complete() -> None:
    document = b"%PDF-1.7\npaged CNINFO filing\n%%EOF\n"
    pages: list[int] = []

    def transport(request):
        if request.full_url.endswith("szse_stock.json"):
            return TransportResponse(
                json.dumps(
                    {
                        "stockList": [
                            {"code": "002897", "orgId": "paged-org"}
                        ]
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        if request.full_url.endswith("/query"):
            page = int(parse_qs(request.data.decode())["pageNum"][0])
            pages.append(page)
            return TransportResponse(
                json.dumps(
                    {
                        "announcements": [
                            {
                                "announcementId": f"page-{page}",
                                "secCode": "002897",
                                "orgId": "paged-org",
                                "announcementTime": 1776474000000,
                                "storageTime": 1776474000000,
                                "adjunctUrl": f"page-{page}.PDF",
                                "announcementTitle": "Synthetic filing",
                            }
                        ],
                        "hasMore": page == 1,
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        return TransportResponse(
            document, {"Content-Type": "application/pdf"}
        )

    envelope = CninfoOfficialDisclosureProvider(
        transport=transport
    ).fetch(
        OfficialFilingQuery(
            "cninfo-pagination",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.status.value == "complete"
    assert pages == [1, 2]
    assert len(json.loads(envelope.payload)["rows"]) == 2


def test_cninfo_null_announcements_with_zero_total_is_legal_empty() -> None:
    calls = 0

    def transport(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TransportResponse(
                json.dumps(
                    {
                        "stockList": [
                            {"code": "002897", "orgId": "empty-org"}
                        ]
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        return TransportResponse(
            json.dumps(
                {
                    "announcements": None,
                    "totalAnnouncement": 0,
                    "hasMore": False,
                }
            ).encode(),
            {"Content-Type": "application/json"},
        )

    envelope = CninfoOfficialDisclosureProvider(
        transport=transport
    ).fetch(
        OfficialFilingQuery(
            "cninfo-empty",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.status.value == "missing"
    assert envelope.error_code == "OFFICIAL_FILING_EMPTY_CONFIRMED"
    assert envelope.payload is None


def test_cninfo_security_map_is_size_bounded_before_parsing() -> None:
    envelope = CninfoOfficialDisclosureProvider(
        transport=lambda _request: TransportResponse(
            b" " * (2 * 1024 * 1024 + 1),
            {"Content-Type": "application/json"},
        )
    ).fetch(
        OfficialFilingQuery(
            "cninfo-oversize",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.status.value == "failed"
    assert envelope.error_code == "OFFICIAL_RESPONSE_OVERSIZE"
    assert envelope.payload is None


@pytest.mark.parametrize(
    ("scenario", "expected_code", "expected_status"),
    (
        (
            "identity",
            "OFFICIAL_FILING_SECURITY_IDENTITY_MISMATCH",
            "failed",
        ),
        ("mime", "OFFICIAL_FILING_DOCUMENT_MIME_INVALID", "failed"),
        (
            "malicious",
            "OFFICIAL_FILING_DOCUMENT_QUARANTINED",
            "failed",
        ),
        (
            "oversize",
            "OFFICIAL_FILING_DOCUMENT_QUARANTINED",
            "failed",
        ),
        ("partial", "OFFICIAL_FILING_PARTIAL", "partial"),
    ),
)
def test_cninfo_adapter_fails_closed_across_document_and_partial_matrix(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_code: str,
    expected_status: str,
) -> None:
    if scenario == "oversize":
        monkeypatch.setattr(official_module, "_MAX_DOCUMENT_BYTES", 8)
    calls = 0

    def transport(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TransportResponse(
                json.dumps(
                    {
                        "stockList": [
                            {"code": "002897", "orgId": "matrix-org"}
                        ]
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        if calls == 2:
            if scenario == "partial":
                payload = {"announcements": [], "hasMore": True}
            else:
                payload = {
                    "announcements": [
                        {
                            "announcementId": f"matrix-{scenario}",
                            "secCode": (
                                "000001"
                                if scenario == "identity"
                                else "002897"
                            ),
                            "orgId": "matrix-org",
                            "announcementTime": 1776474000000,
                            "adjunctUrl": f"matrix-{scenario}.PDF",
                            "announcementTitle": "Synthetic filing",
                        }
                    ],
                    "totalAnnouncement": 1,
                }
            return TransportResponse(
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
            )
        if scenario == "mime":
            return TransportResponse(
                b"<html>not a PDF</html>",
                {"Content-Type": "text/html"},
            )
        document = (
            b"%PDF-1.7\n/JavaScript\n%%EOF\n"
            if scenario == "malicious"
            else b"%PDF-1.7\noversize\n%%EOF\n"
        )
        return TransportResponse(
            document, {"Content-Type": "application/pdf"}
        )

    envelope = CninfoOfficialDisclosureProvider(
        transport=transport
    ).fetch(
        OfficialFilingQuery(
            "cninfo-matrix",
            "security_yihua",
            "002897",
            "SZSE",
            "2026-04-01",
            "2026-04-30",
            None,
            "security_yihua",
            True,
        )
    ).envelopes[0]

    assert envelope.status.value == expected_status
    assert envelope.error_code == expected_code
    assert envelope.payload is None


def test_production_job_statically_composes_szse_without_credential(
    tmp_path: Path,
) -> None:
    job = {
        "schema_version": "ProviderJob@2",
        "provider": {
            "provider_id": "szse-official-disclosure",
            "adapter_version": "szse-announcement@1",
            "credential_env": "not_applicable",
        },
        "query_policy": {
            "schema_version": "QueryPolicy@1",
            "lookback_days": 30,
            "market_universe_list_status": "L",
            "adjustment_mode": "none",
        },
        "source_policy": {
            "schema_version": "SourcePolicy@1",
            "provider_id": "szse-official-disclosure",
            "adapter_version": "szse-announcement@1",
            "source_identity": "szse-statutory-disclosure",
            "source_authority": "official",
            "terms_profile": "szse-local-noncommercial@2026-07-24",
            "rights": {
                "automation_allowed": True,
                "local_storage_allowed": True,
                "deterministic_replay_allowed": True,
                "derived_use_allowed": True,
                "redistribution_allowed": False,
                "reviewed_on": "2026-07-24",
                "evidence_sha256": None,
            },
            "routes": [
                {
                    "dataset": "official_filing",
                    "freshness_max_stale_days": 30,
                    "completeness": "required",
                    "retry_max_attempts": 1,
                    "fallback": "no_fallback",
                    "failure_disposition": "block",
                }
            ],
        },
        "request": {
            "invocation_id": "szse-production-composition",
            "security_id": "security_yihua",
            "security_code": "002897",
            "requested_date": "2026-04-30",
            "as_of_at": "2026-04-30T12:00:00+00:00",
            "market_timezone": "Asia/Shanghai",
            "market": "SZSE",
            "snapshot_purpose": "research",
            "datasets": ["official_filing"],
            "network_authorized": True,
            "offline": False,
        },
    }
    job_path = tmp_path / "szse-job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")

    class NoCredential:
        def get(self, _name: str) -> str:
            raise AssertionError("official provider must not read a credential")

    loaded = load_sync_job(job_path, credential_adapter=NoCredential())

    assert isinstance(loaded.provider, SzseOfficialDisclosureProvider)
    assert loaded.credential_variable == "not_applicable"
    assert loaded.source_policy.source_authority.value == "official"
    assert {
        item.reason_code for item in loaded.provider.capabilities
    } == {"not_applicable:filing_dataset"}
    assert {
        item.capability.value for item in loaded.provider.capabilities
    } == {
        "trading_calendar",
        "adjustment_factors",
        "corporate_actions",
        "suspension_status",
        "price_limit_status",
        "t_plus_one",
    }


@pytest.mark.parametrize(
    ("example_name", "provider_type"),
    (
        ("szse-official-yihua-job.json", SzseOfficialDisclosureProvider),
        ("cninfo-official-yihua-job.json", CninfoOfficialDisclosureProvider),
    ),
)
def test_versioned_official_examples_use_static_no_credential_composition(
    example_name: str,
    provider_type: type,
) -> None:
    class NoCredential:
        def get(self, _name: str) -> str:
            raise AssertionError("official provider must not read a credential")

    loaded = load_sync_job(
        Path("examples/platform") / example_name,
        credential_adapter=NoCredential(),
    )

    assert isinstance(loaded.provider, provider_type)
    assert loaded.credential_variable == "not_applicable"
    assert loaded.source_policy.source_authority is SourceAuthority.OFFICIAL


def test_official_provider_qualification_commits_identity_bound_pdf_receipt(
    tmp_path: Path,
) -> None:
    document = b"%PDF-1.7\nqualification filing\n%%EOF\n"

    def transport(request):
        if request.full_url.endswith("/api/disc/announcement/annList"):
            return TransportResponse(
                json.dumps(
                    {
                        "data": [
                            {
                                "annId": "qualification-announcement",
                                "secCode": ["002897"],
                                "publishTime": "2026-07-20 09:00:00",
                                "attachPath": "/qualification.pdf",
                                "title": "Synthetic filing",
                            }
                        ]
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
        return TransportResponse(
            document, {"Content-Type": "application/pdf"}
        )

    class LoopbackOfficialRuntime:
        def bind(
            self, decoded: DecodedProviderJob
        ) -> ProviderRuntimeBinding:
            assert (
                decoded.source_policy
                == canonical_official_source_policy(decoded.provider_id)
            )
            assert decoded.credential_variable == "not_applicable"
            provider = SzseOfficialDisclosureProvider(transport=transport)
            return ProviderRuntimeBinding(
                provider,
                hashlib.sha256(b"not_applicable").hexdigest(),
                "not_applicable",
                provider.transport_identity,
                "test_loopback",
            )

    policy = canonical_official_source_policy(
        "szse-official-disclosure"
    )
    job = {
        "schema_version": "ProviderJob@2",
        "provider": {
            "provider_id": policy.provider_id,
            "adapter_version": policy.adapter_version,
            "credential_env": "not_applicable",
        },
        "query_policy": {
            "schema_version": "QueryPolicy@1",
            "lookback_days": 30,
            "market_universe_list_status": "L",
            "adjustment_mode": "none",
        },
        "source_policy": policy.canonical_content,
        "request": {
            "invocation_id": "qualify-official-loopback",
            "security_id": "security_yihua",
            "security_code": "002897",
            "requested_date": "2026-07-25",
            "as_of_at": "2026-07-25T23:59:59+00:00",
            "market_timezone": "Asia/Shanghai",
            "market": "SZSE",
            "snapshot_purpose": "research",
            "datasets": ["official_filing"],
            "network_authorized": True,
            "offline": False,
        },
        "security_identity": {
            "security_id": "security_yihua",
            "venue": "SZSE",
            "code": "002897",
            "currency": "CNY",
            "listed_from": "2017-09-07",
        },
    }
    job_path = tmp_path / "official-job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    data_root = tmp_path / "data"
    assert open_platform_operations(data_root).bootstrap()["status"] == "passed"

    with open_provider_qualification(
        data_root,
        job_path,
        provider_runtime=LoopbackOfficialRuntime(),
    ) as qualification:
        result = qualification.run()

    assert result.status == "qualified"
    assert result.source_authority == "official"
    assert result.provider_identity == "szse-statutory-disclosure"
    assert result.credential_scope_id == hashlib.sha256(
        b"not_applicable"
    ).hexdigest()
    assert len(result.attempts) == 1
    assert result.attempts[0].dataset == "official_filing"
    assert result.attempts[0].raw_sha256 is not None
    database = SQLiteOwningAdapterFixture(data_root)
    filing = database.execute(
        "SELECT document_object_sha256 FROM official_filing_version"
    ).fetchone()
    document_object = database.execute(
        "SELECT relative_path FROM object_blob WHERE sha256=?",
        (filing[0],),
    ).fetchone()
    assert (
        data_root / Path(*document_object[0].split("/"))
    ).read_bytes() == document


def test_official_filing_only_sync_builds_research_snapshot_without_market_data(
    tmp_path: Path,
) -> None:
    provider = FixtureProvider(
        "official-fixture",
        "official-fixture@1",
        {"official_filing": _filing_payload()},
        FIXTURE_SOURCE,
        "derived-fact-fixture-terms@1",
        SourceAuthority.FIXTURE,
    )
    query_policy = QueryPolicy("QueryPolicy@1", 30, "L", "none")
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        FIXTURE_SOURCE,
        SourceAuthority.FIXTURE,
        "derived-fact-fixture-terms@1",
        SourceRights(True, True, True, True, False, "2026-07-10"),
        (
            SourceRoute(
                "official_filing",
                30,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            ),
        ),
    )
    rights = replace(
        _rights("fixture")[("fixture", "daily")],
        member_id="official-fixture:official_filing",
    )
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
        fixture_rights={
            ("official-fixture", "official_filing"): rights
        },
    )
    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua", "SZSE", "002897", "CNY", "2017-09-07"
        ),
    )
    result = root.data.sync(
        SyncRequest(
            "official-only",
            "security_yihua",
            "002897",
            "2026-04-30",
            datetime(2026, 4, 30, 12, tzinfo=timezone.utc),
            "Asia/Shanghai",
            "SZSE",
            SnapshotPurpose.RESEARCH,
            ("official_filing",),
            False,
            False,
        )
    )

    assert result.status is SyncStatus.COMPLETE
    assert result.effective_session_date == "2026-04-30"
    snapshot = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT calendar_version,coverage_expected,coverage_eligible,"
        "coverage_missing FROM data_snapshot WHERE data_snapshot_id=?",
        (result.snapshot_id,),
    ).fetchone()
    assert tuple(snapshot) == (
        "not_applicable:filing_dataset",
        1,
        1,
        0,
    )
    root.close()


def test_official_filing_snapshot_uses_retrieval_freshness_not_calendar_rules(
    tmp_path: Path,
) -> None:
    payload = _filing_payload()

    class StaleOfficialFixture:
        provider_id = "stale-official-fixture"
        adapter_version = "stale-official-fixture@1"
        fixture = True
        capabilities = ()
        code_identity = "fixture:stale-official"
        transport_identity = "fixture:stale-official-transport"

        def fetch(self, _query) -> FetchBatch:
            retrieved_at = datetime(
                2026, 4, 18, 12, tzinfo=timezone.utc
            )
            return FetchBatch(
                (
                    RawEnvelope(
                        FIXTURE_SOURCE,
                        SourceAuthority.FIXTURE,
                        "urn:test:stale-official",
                        {},
                        {},
                        "second",
                        "derived-fact-fixture-terms@1",
                        retrieved_at,
                        FetchStatus.COMPLETE,
                        payload,
                        hashlib.sha256(payload).hexdigest(),
                        cursor_value="2026-04-30",
                    ),
                )
            )

    provider = StaleOfficialFixture()
    query_policy = QueryPolicy("QueryPolicy@1", 30, "L", "none")
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        FIXTURE_SOURCE,
        SourceAuthority.FIXTURE,
        "derived-fact-fixture-terms@1",
        SourceRights(True, True, True, True, False, "2026-07-10"),
        (
            SourceRoute(
                "official_filing",
                30,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            ),
        ),
    )
    rights = replace(
        _rights("fixture")[("fixture", "daily")],
        member_id="stale-official-fixture:official_filing",
    )
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
        fixture_rights={
            ("stale-official-fixture", "official_filing"): rights
        },
    )
    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua", "SZSE", "002897", "CNY", "2017-09-07"
        ),
    )

    result = root.data.sync(
        SyncRequest(
            "stale-official",
            "security_yihua",
            "002897",
            "2026-04-30",
            datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
            "Asia/Shanghai",
            "SZSE",
            SnapshotPurpose.RESEARCH,
            ("official_filing",),
            False,
            False,
        )
    )

    assert result.status is SyncStatus.BLOCKED
    assert result.freshness.value == "stale"
    assert result.stale_by_days == 98
    assert result.freshness_basis == "official_filing_retrieved_at"
    assert result.snapshot_id is None
    root.close()


def test_official_filing_unit_of_work_rolls_back_then_replays_once(
    tmp_path: Path,
) -> None:
    provider = FixtureProvider(
        "atomic-official-fixture",
        "atomic-official-fixture@1",
        {"official_filing": _filing_payload()},
        FIXTURE_SOURCE,
        "derived-fact-fixture-terms@1",
        SourceAuthority.FIXTURE,
    )
    query_policy = QueryPolicy("QueryPolicy@1", 30, "L", "none")
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        FIXTURE_SOURCE,
        SourceAuthority.FIXTURE,
        "derived-fact-fixture-terms@1",
        SourceRights(True, True, True, True, False, "2026-07-10"),
        (
            SourceRoute(
                "official_filing",
                30,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            ),
        ),
    )
    rights = replace(
        _rights("fixture")[("fixture", "daily")],
        member_id="atomic-official-fixture:official_filing",
    )
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
        fixture_rights={
            ("atomic-official-fixture", "official_filing"): rights
        },
    )
    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua", "SZSE", "002897", "CNY", "2017-09-07"
        ),
    )
    request = SyncRequest(
        "atomic-official",
        "security_yihua",
        "002897",
        "2026-04-30",
        datetime(2026, 4, 30, 12, tzinfo=timezone.utc),
        "Asia/Shanghai",
        "SZSE",
        SnapshotPurpose.RESEARCH,
        ("official_filing",),
        False,
        False,
    )

    def fail_before_commit(boundary: str) -> None:
        if boundary == "data.before_atomic_commit":
            raise RuntimeError("synthetic atomic failure")

    root.faults.set_data_fault_injector(fail_before_commit)
    with pytest.raises(RuntimeError, match="synthetic atomic failure"):
        root.data.sync(request)
    database = SQLiteOwningAdapterFixture(root.data_root)
    assert database.execute(
        "SELECT count(*) FROM provider_attempt "
        "WHERE invocation_id='atomic-official'"
    ).fetchone()[0] == 0
    assert database.execute(
        "SELECT count(*) FROM official_filing_version"
    ).fetchone()[0] == 0
    assert database.execute(
        "SELECT count(*) FROM data_snapshot "
        "WHERE scope_id='security_yihua'"
    ).fetchone()[0] == 0

    root.faults.set_data_fault_injector(None)
    replay = root.data.sync(request)
    assert replay.status is SyncStatus.COMPLETE
    assert database.execute(
        "SELECT count(*) FROM provider_attempt "
        "WHERE invocation_id='atomic-official'"
    ).fetchone()[0] == 1
    assert database.execute(
        "SELECT count(*) FROM official_filing_version"
    ).fetchone()[0] == 1
    assert database.execute(
        "SELECT count(*) FROM data_snapshot "
        "WHERE scope_id='security_yihua'"
    ).fetchone()[0] == 1
    root.close()


def test_public_sync_freezes_typed_a_share_filing_without_inventing_facts(
    tmp_path: Path,
) -> None:
    payloads = {**_payloads(), "official_filing": _filing_payload()}
    provider = FixtureProvider(
        "fixture",
        "fixture@1",
        payloads,
        FIXTURE_SOURCE,
        "derived-fact-fixture-terms@1",
    )
    composition = _composition(provider)
    base_policy = composition["source_policy"]
    assert isinstance(base_policy, SourcePolicy)
    composition["source_policy"] = replace(
        base_policy,
        routes=(
            *base_policy.routes,
            SourceRoute(
                "official_filing",
                30,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            ),
        ),
    )
    rights = {
        **_rights("fixture"),
        ("fixture", "official_filing"): replace(
            _rights("fixture")[("fixture", "daily")],
            member_id="fixture:official_filing",
        ),
    }
    root = PlatformTaskFixture(
        tmp_path,
        **composition,
        fixture_rights=rights,
    )
    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua", "SZSE", "002897", "CNY", "2017-09-07"
        ),
    )
    root.watchlist.add(
        "watch:security_old",
        SecurityIdentity(
            "security_old", "SZSE", "000001", "CNY", "2010-01-01"
        ),
    )
    mixed_request = replace(
        _request("a-share-official-filing"),
        datasets=(
            "trade_cal",
            "market_universe",
            "daily",
            "official_filing",
        ),
        as_of_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
    )
    with pytest.raises(
        PersistenceError, match="dedicated atomic sync task"
    ) as mixed_error:
        root.data.sync(mixed_request)
    assert (
        getattr(mixed_error.value, "code", None)
        == "OFFICIAL_FILING_MIXED_DATASET_FORBIDDEN"
    )
    request = replace(
        mixed_request,
        invocation_id="a-share-official-filing-only",
        datasets=("official_filing",),
    )

    query = composition["query_policy"].build(
        "official_filing", request, None
    )
    assert isinstance(query, OfficialFilingQuery)
    assert query.security_id == "security_yihua"
    assert not hasattr(query, "endpoint")
    assert not hasattr(query, "wire_params")

    result = root.data.sync(request)
    assert result.status is SyncStatus.COMPLETE
    assert {
        member.dataset for member in root.data.snapshot_members(result.snapshot_id)
    } >= {"official_filing"}

    database = SQLiteOwningAdapterFixture(root.data_root)
    filing = database.execute(
        "SELECT security_id,authority,document_identity,content_type,"
        "correction_status,document_object_sha256 FROM official_filing_version"
    ).fetchone()
    assert tuple(filing[:5]) == (
        "security_yihua",
        "SZSE",
        "szse:notice:2026-001",
        "application/pdf",
        "original",
    )
    document_path = database.execute(
        "SELECT relative_path FROM object_blob WHERE sha256=?",
        (filing[5],),
    ).fetchone()[0]
    assert (root.data_root / Path(*document_path.split("/"))).read_bytes().startswith(
        b"%PDF-"
    )
    assert database.execute(
        "SELECT count(*) FROM financial_fact_version"
    ).fetchone()[0] == 0
    root.close()


def test_official_filing_normalization_quarantines_impossible_pit_order() -> None:
    payload = json.loads(_filing_payload())
    payload["rows"][0]["published_at"] = "2026-04-19T09:00:00+08:00"
    payload["rows"][0]["available_at"] = "2026-04-18T09:00:00+08:00"

    items = normalize(
        "official_filing",
        json.dumps(payload).encode(),
        "security_yihua",
        "SZSE",
        FIXTURE_SOURCE,
        datetime(2026, 4, 20, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].quality.value == "quarantine"
    assert (
        "quarantine",
        "OFFICIAL_FILING_PIT_ORDER_INVALID",
    ) in items[0].issues
