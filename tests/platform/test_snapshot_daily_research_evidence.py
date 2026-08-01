from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.data.providers import (
    TransportResponse,
    TushareCompatibleProvider,
)
from trading_platform.domain.data import (
    CompletenessRequirement,
    FallbackMode,
    QueryPolicy,
    SnapshotPurpose,
    SourceAuthority,
    SourceFailureDisposition,
    SourcePolicy,
    SourceRights,
    SourceRoute,
    SyncRequest,
    SyncStatus,
)


def test_snapshot_evidence_exposes_every_frozen_daily_close(tmp_path) -> None:
    responses = {
        "trade_cal": {
            "code": 0,
            "data": {
                "fields": ["exchange", "cal_date", "is_open"],
                "items": [["SZSE", "20260710", 1]],
            },
        },
        "stock_basic": {
            "code": 0,
            "data": {
                "fields": ["ts_code", "name", "list_date"],
                "items": [["002897.SZ", "意华股份", "20170907"]],
            },
        },
        "daily": {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ],
                "items": [
                    [
                        "002897.SZ",
                        "20260710",
                        "10.8",
                        "11.2",
                        "10.7",
                        "11",
                        "1000",
                        "11000",
                    ],
                    [
                        "002897.SZ",
                        "20260709",
                        "9.8",
                        "10.2",
                        "9.7",
                        "10",
                        "1000",
                        "10000",
                    ],
                    [
                        "002897.SZ",
                        "20260708",
                        "8.8",
                        "9.2",
                        "8.7",
                        "9",
                        "1000",
                        "9000",
                    ],
                ],
            },
        },
    }

    def transport(request):
        body = json.loads(request.data.decode("utf-8"))
        return TransportResponse(
            json.dumps(responses[body["api_name"]]).encode(),
            {},
        )

    provider = TushareCompatibleProvider(
        "gateway",
        "tushare-http@2",
        "http://127.0.0.1:9/",
        "redacted-test-secret",
        "preconfigured_tushare_compatible_non_official",
        "gateway-terms-pending@1",
        transport,
        SourceAuthority.STRUCTURED_AGGREGATOR,
    )
    datasets = ("trade_cal", "market_universe", "daily")
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        "preconfigured_tushare_compatible_non_official",
        SourceAuthority.STRUCTURED_AGGREGATOR,
        "gateway-terms-pending@1",
        SourceRights(True, True, True, True, False, "2026-07-24"),
        tuple(
            SourceRoute(
                dataset,
                1,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            )
            for dataset in datasets
        ),
    )
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=QueryPolicy("QueryPolicy@1", 550, "L", "none"),
        source_policy=source_policy,
    )
    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua",
            "SZSE",
            "002897",
            "CNY",
            "2017-09-07",
        ),
    )
    snapshot = root.data.sync(
        SyncRequest(
            "daily-evidence-history",
            "security_yihua",
            "002897",
            "2026-07-10",
            datetime.now(timezone.utc) + timedelta(minutes=1),
            "Asia/Shanghai",
            "SZSE",
            SnapshotPurpose.RESEARCH,
            datasets,
            True,
            False,
        )
    )
    assert snapshot.status is SyncStatus.COMPLETE
    assert snapshot.snapshot_id is not None

    evidence = root.inspection.snapshot(snapshot.snapshot_id)
    observed = tuple(
        (
            member.normalized_version_id,
            str(field["period"]),
            str(field["value"]),
        )
        for member in evidence.member_evidence
        if member.dataset == "daily"
        for field in member.extracted_fields
        if field["field_name"] == "current_price"
    )

    assert len(observed) == 3
    assert {item[1:] for item in observed} == {
        ("2026-07-08", "9"),
        ("2026-07-09", "10"),
        ("2026-07-10", "11"),
    }
    assert len({item[0] for item in observed}) == 3
    root.close()
