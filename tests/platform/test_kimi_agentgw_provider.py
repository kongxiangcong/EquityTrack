from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_platform.application.contracts import SecurityIdentity
from trading_platform.application.provider_job import ProviderJob
from trading_platform.data.kimi_agentgw import (
    KimiAgentGatewayProvider,
    KimiAgentGwDetection,
    KimiAgentGwEnvironment,
)
from trading_platform.data.normalizer import normalize
from trading_platform.domain.data import (
    DailyOhlcvQuery,
    FetchStatus,
    FinancialStatementQuery,
    ForecastActualQuery,
    OfficialFilingQuery,
    QueryPolicy,
    SecurityMasterQuery,
    SnapshotPurpose,
    SyncRequest,
    TradingCalendarQuery,
)
from trading_platform.operations import OperationError
from trading_platform.provider_config import (
    DecodedProviderJob,
    PreconfiguredKimiAgentGwRuntime,
    canonical_kimi_agentgw_source_policy,
    canonical_official_source_policy,
)


# ── fake agent-gw client ─────────────────────────────────────────────────


class _Resp:
    def __init__(self, raw: dict) -> None:
        self.raw = raw


class _FakeTools:
    def __init__(self, handler) -> None:
        self._handler = handler

    def call_data_source_tool(self, payload):
        return self._handler(payload)


class _FakeClient:
    def __init__(self, handler) -> None:
        self.tools = _FakeTools(handler)


def _csv(headers: list[str], rows: list[list[object]]) -> str:
    lines = [",".join(headers)]
    lines.extend(",".join(str(value) for value in row) for row in rows)
    return "\n".join(lines) + "\n"


def _ok(content: str) -> _Resp:
    return _Resp(
        {
            "is_success": True,
            "files": [{"name": "virtual.csv", "content": content}],
            "result": {"assistant": []},
        }
    )


def _entitled_error() -> _Resp:
    return _Resp({"is_success": False, "error": {"assistant": ["权限不足"]}})


class _RateLimitError(Exception):
    pass


# name matches the SDK class so the provider maps it deterministically
_RateLimitError.__name__ = "RateLimitError"


WIND_PRICE_CSV = _csv(
    ["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"],
    [
        ["2026-07-20", "002407.SZ", "31.66", "32.0", "28.12", "28.12", "135749800", "3857498000"],
        ["2026-07-21", "002407.SZ", "28.2", "30.18", "25.49", "30.13", "163432900", "4628052702"],
    ],
)

WIND_INDEX_CSV = _csv(
    ["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"],
    [
        ["2026-07-20", "000001.SH", "3808.90", "3858.31", "3793.45", "3858.25", "50487945400", "1031312143000"],
        ["2026-07-21", "000001.SH", "3823.13", "3844.01", "3797.37", "3813.31", "49482912600", "949683080100"],
    ],
)

WIND_STOCK_INFO_CSV = _csv(
    ["wind_code", "证券简称", "首发上市日期"],
    [["002407.SZ", "多氟多", "2010-05-18"]],
)

WIND_FIRST_SESSION_CSV = _csv(
    ["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"],
    [["2010-05-18", "002407.SZ", "35.0", "36.0", "34.0", "35.5", "1000", "35000"]],
)

_API_DATASOURCE = {
    "wind_get_price": "wind",
    "wind_get_index_price": "wind",
    "wind_get_stock_info": "wind",
    "ifind_get_financial_statements": "ifind",
    "ifind_get_forecast": "ifind",
}

INCOME_CSV = _csv(
    [
        "ths_operating_total_revenue_stock",
        "ths_np_atoopc_stock",
        "ths_op_stock",
        "ths_income_tax_cost_stock",
        "ths_dlt_earnings_per_share_stock",
    ],
    [["9434247610.47", "212784849.4", "215850396.69", "30100000.5", "0.18"]],
)

BALANCE_CSV = _csv(
    [
        "ths_currency_fund_stock",
        "ths_st_borrow_stock",
        "ths_noncurrent_liab_due_in1y_stock",
        "ths_lease_libilities_stock",
        "ths_minority_equity_stock",
        "ths_actual_received_capital_stock",
        "ths_total_current_assets_stock",
        "ths_total_current_liab_stock",
    ],
    [[
        "5030602303.23",
        "1200370025.21",
        "1483194839.33",
        "625433554.46",
        "2594330853.91",
        "1190432569.0",
        "10704565673.13",
        "8224646462.73",
    ]],
)

CASHFLOW_CSV = _csv(
    [
        "ths_ncf_from_oa_stock",
        "ths_cash_paid_for_assets_stock",
        "ths_depreciation_etc_stock",
        "ths_intangible_assets_amortized_stock",
        "ths_rou_depreciation_stock",
    ],
    [["199089470.35", "1056712029.23", "916528668.83", "29061542.97", "39365570.32"]],
)

FORECAST_CSV = _csv(
    [
        "ths_fore_np_fy1_stock",
        "ths_fore_np_fy2_stock",
        "ths_fore_np_fy3_stock",
        "ths_fore_mbi_fy1_stock",
        "ths_fore_mbi_fy2_stock",
        "ths_fore_mbi_fy3_stock",
    ],
    [["2427375000.0", "2792500000.0", "3299125000.0", "66832411250.0", "70629426250.0", "77386408750.0"]],
)

_STATEMENT_CSVS = {
    "income": INCOME_CSV,
    "balancesheet": BALANCE_CSV,
    "cashflow": CASHFLOW_CSV,
}


def _handler(api_content: dict[str, str]):
    def handle(payload: dict) -> _Resp:
        api_name = payload["api_name"]
        assert payload["data_source_name"] == _API_DATASOURCE[api_name]
        if api_name not in api_content:
            raise AssertionError(f"unexpected api call: {api_name}")
        return _ok(api_content[api_name])

    return handle


def _provider(handler, resolver=None) -> KimiAgentGatewayProvider:
    policy = canonical_kimi_agentgw_source_policy()
    return KimiAgentGatewayProvider(
        policy.provider_id,
        policy.adapter_version,
        policy.source_identity,
        policy.terms_profile,
        client_factory=lambda: _FakeClient(handler),
        source_authority=policy.source_authority,
        forecast_security_resolver=resolver,
    )


def _daily_query(network_authorized: bool = True) -> DailyOhlcvQuery:
    return DailyOhlcvQuery(
        "inv-1", "security_duofuduo", "002407", "SZSE",
        "2026-07-20", "2026-08-01", "none", None,
        "security_duofuduo", network_authorized,
    )


def _statement_query(dataset: str) -> FinancialStatementQuery:
    return FinancialStatementQuery(
        "inv-1", "security_duofuduo", "002407", "SZSE", dataset,
        "2025-10-01", "2026-08-01", None, "security_duofuduo", True,
    )


def _forecast_query() -> ForecastActualQuery:
    return ForecastActualQuery(
        "inv-1", "security_duofuduo", "2026-08-01", None, "security_duofuduo", True
    )


# ── daily ────────────────────────────────────────────────────────────────


def test_daily_fetch_emits_canonical_unadjusted_rows() -> None:
    captured: list[dict] = []

    def handle(payload: dict) -> _Resp:
        captured.append(payload)
        return _ok(WIND_PRICE_CSV)

    batch = _provider(handle).fetch(_daily_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.COMPLETE
    assert envelope.error_code is None
    call = captured[0]
    assert call["data_source_name"] == "wind"
    assert call["api_name"] == "wind_get_price"
    params = call["params"]
    assert params["ticker"] == "002407.SZ"
    assert params["price_adj"] == "N"
    assert params["frequency"] == "D"
    assert "\\" not in params["file_path"]

    items = normalize(
        "daily", envelope.payload, "security_duofuduo", "SZSE",
        envelope.source_identity, envelope.retrieved_at,
    )
    assert len(items) == 2
    first = items[0]
    assert first.quality.value == "pass"
    assert first.payload["adjustment_mode"] == "none"
    assert first.payload["volume_unit"] == "share"
    assert first.payload["close"] == "28.12"
    assert first.payload["amount"] == "3857498000"
    assert first.payload["amount_unit"] == "yuan"
    assert first.payload["availability_basis"] == "conservative_end_of_session_date"


def test_daily_fetch_requires_network_authorization() -> None:
    batch = _provider(_handler({})).fetch(_daily_query(network_authorized=False))
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.FAILED
    assert envelope.error_code == "NETWORK_NOT_AUTHORIZED"


def test_empty_provider_rows_are_missing_not_complete() -> None:
    empty = _csv(["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"], [])
    batch = _provider(_handler({"wind_get_price": empty})).fetch(_daily_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.MISSING
    assert envelope.error_code == "AGENTGW_DATASET_EMPTY"


def test_entitlement_rejection_maps_to_typed_code() -> None:
    def handle(payload: dict) -> _Resp:
        return _entitled_error()

    batch = _provider(handle).fetch(_daily_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.FAILED
    assert envelope.error_code == "PROVIDER_API_ENTITLEMENT_UNAVAILABLE"


def test_rate_limit_maps_to_rate_limited_status() -> None:
    def handle(payload: dict) -> _Resp:
        raise _RateLimitError("slow down")

    batch = _provider(handle).fetch(_daily_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.RATE_LIMITED
    assert envelope.error_code == "PROVIDER_API_RATE_LIMITED"


def test_unsupported_query_type_fails_closed() -> None:
    query = OfficialFilingQuery(
        "inv-1", "security_duofuduo", "002407", "SZSE",
        "2026-07-01", "2026-08-01", None, "security_duofuduo", True,
    )
    batch = _provider(_handler({})).fetch(query)
    assert batch.envelopes[0].error_code == "AGENTGW_QUERY_UNSUPPORTED"


# ── trade_cal ────────────────────────────────────────────────────────────


def _trade_cal_query() -> TradingCalendarQuery:
    return TradingCalendarQuery(
        "inv-1", "SZSE", "2026-07-20", "2026-07-21", None, "security_duofuduo", True
    )


def test_trade_cal_fetch_emits_wind_index_session_rows() -> None:
    captured: list[dict] = []

    def handle(payload: dict) -> _Resp:
        captured.append(payload)
        return _ok(WIND_INDEX_CSV)

    batch = _provider(handle).fetch(_trade_cal_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.COMPLETE, envelope.error_code
    call = captured[0]
    assert call["data_source_name"] == "wind"
    assert call["api_name"] == "wind_get_index_price"
    assert call["params"]["ticker"] == "000001.SH"

    items = normalize(
        "trade_cal", envelope.payload, None, "SZSE",
        envelope.source_identity, envelope.retrieved_at,
    )
    assert len(items) == 2
    for item in items:
        assert item.quality.value == "pass"
        assert item.payload["market"] == "SZSE"
        assert item.payload["is_open"] is True
        assert item.payload["calendar_version"] == "wind-index-sessions@1"
        assert item.payload["availability_basis"] == "publisher_timestamp"


def test_trade_cal_empty_sessions_are_missing() -> None:
    empty = _csv(["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"], [])
    batch = _provider(_handler({"wind_get_index_price": empty})).fetch(_trade_cal_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.MISSING
    assert envelope.error_code == "AGENTGW_DATASET_EMPTY"


# ── market_universe ───────────────────────────────────────────────────────


def _universe_query() -> SecurityMasterQuery:
    return SecurityMasterQuery(
        "inv-1", "security_duofuduo", "002407", "SZSE", "L",
        "2026-08-01", None, "security_duofuduo", True,
    )


def test_market_universe_prefers_stock_info_listing_date() -> None:
    captured: list[dict] = []

    def handle(payload: dict) -> _Resp:
        captured.append(payload)
        assert payload["api_name"] == "wind_get_stock_info"
        return _ok(WIND_STOCK_INFO_CSV)

    batch = _provider(handle).fetch(_universe_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.COMPLETE, envelope.error_code
    assert captured[0]["data_source_name"] == "wind"
    assert captured[0]["params"]["fields"] == "ipo_date"

    items = normalize(
        "market_universe", envelope.payload, "security_duofuduo", "SZSE",
        envelope.source_identity, envelope.retrieved_at,
    )
    assert len(items) == 1
    row = items[0].payload
    assert items[0].quality.value == "pass"
    assert row["market_scope_id"] == "CN_A_SHARE"
    assert row["listed_from"] == "2010-05-18"
    assert row["source_ref"] == "wind:wind_get_stock_info:ipo_date:002407.SZ"


def test_market_universe_falls_back_to_first_daily_session() -> None:
    def handle(payload: dict) -> _Resp:
        if payload["api_name"] == "wind_get_stock_info":
            return _ok(_csv(["wind_code", "证券简称"], [["002407.SZ", "多氟多"]]))
        if payload["api_name"] == "wind_get_price":
            return _ok(WIND_FIRST_SESSION_CSV)
        raise AssertionError(f"unexpected api call: {payload['api_name']}")

    batch = _provider(handle).fetch(_universe_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.COMPLETE, envelope.error_code
    items = normalize(
        "market_universe", envelope.payload, "security_duofuduo", "SZSE",
        envelope.source_identity, envelope.retrieved_at,
    )
    assert len(items) == 1
    row = items[0].payload
    assert row["listed_from"] == "2010-05-18"
    assert row["source_ref"] == "wind:wind_get_price:first_session:002407.SZ"


def test_market_universe_without_listing_evidence_is_missing() -> None:
    empty = _csv(["trade_date", "wind_code"], [])

    def handle(payload: dict) -> _Resp:
        return _ok(empty)

    batch = _provider(handle).fetch(_universe_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.MISSING
    assert envelope.error_code == "AGENTGW_DATASET_EMPTY"


# ── financial statements ─────────────────────────────────────────────────


@pytest.mark.parametrize("dataset", ["income", "balancesheet", "cashflow"])
def test_statement_fetch_maps_verified_fields(dataset: str) -> None:
    batch = _provider(
        _handler({"ifind_get_financial_statements": _STATEMENT_CSVS[dataset]})
    ).fetch(
        _statement_query(dataset)
    )
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.COMPLETE, envelope.error_code
    items = normalize(
        dataset, envelope.payload, "security_duofuduo", "SZSE",
        envelope.source_identity, envelope.retrieved_at,
    )
    # 2025-10-01..2026-08-01 spans 2025Q4, 2026Q1 and 2026H1 quarter ends.
    assert len(items) == 3
    for item in items:
        assert item.quality.value == "pass"
        assert item.payload["availability_basis"] == "retrieved_only"
        assert item.payload["extracted_fields"]
        assert item.payload["accounting_standard"] == "PRC-GAAP"


def test_income_statement_extracted_field_values() -> None:
    batch = _provider(_handler({"ifind_get_financial_statements": INCOME_CSV})).fetch(
        _statement_query("income")
    )
    document = json.loads(batch.envelopes[0].payload.decode("utf-8"))
    fields = {
        field["field_name"]: field
        for field in document["rows"][0]["extracted_fields"]
    }
    assert fields["revenue"]["value"] == "9434247610.47"
    assert fields["net_income"]["value"] == "212784849.4"
    assert fields["eps"]["value"] == "0.18"
    assert fields["eps"]["unit"] == "CNY/share"
    assert "agentgw:ifind" in fields["revenue"]["extraction_method"]
    assert "not official filing evidence" in fields["revenue"]["notes"]


def test_balancesheet_derives_debt_and_working_capital() -> None:
    batch = _provider(_handler({"ifind_get_financial_statements": BALANCE_CSV})).fetch(
        _statement_query("balancesheet")
    )
    document = json.loads(batch.envelopes[0].payload.decode("utf-8"))
    fields = {
        field["field_name"]: field
        for field in document["rows"][0]["extracted_fields"]
    }
    expected_debt = (
        Decimal("1200370025.21") + Decimal("1483194839.33") + Decimal("625433554.46")
    )
    assert Decimal(fields["debt"]["value"]) == expected_debt
    assert Decimal(fields["working_capital"]["value"]) == (
        Decimal("10704565673.13") - Decimal("8224646462.73")
    )
    assert fields["lease_debt"]["value"] == "625433554.46"
    assert fields["diluted_shares"]["unit"] == "shares"


def test_cashflow_derives_fcf_and_d_and_a() -> None:
    batch = _provider(_handler({"ifind_get_financial_statements": CASHFLOW_CSV})).fetch(
        _statement_query("cashflow")
    )
    document = json.loads(batch.envelopes[0].payload.decode("utf-8"))
    fields = {
        field["field_name"]: field
        for field in document["rows"][0]["extracted_fields"]
    }
    assert Decimal(fields["fcf"]["value"]) == (
        Decimal("199089470.35") - Decimal("1056712029.23")
    )
    assert Decimal(fields["d_and_a"]["value"]) == (
        Decimal("916528668.83") + Decimal("29061542.97") + Decimal("39365570.32")
    )


# ── forecast ─────────────────────────────────────────────────────────────


def test_forecast_fetch_emits_consensus_rows() -> None:
    resolver = lambda security_id: ("002407", "SZSE")
    batch = _provider(
        _handler({"ifind_get_forecast": FORECAST_CSV}), resolver=resolver
    ).fetch(_forecast_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.COMPLETE
    items = normalize(
        "forecast_actual", envelope.payload, "security_duofuduo", "SZSE",
        envelope.source_identity, envelope.retrieved_at,
    )
    assert len(items) == 6
    by_metric = {item.payload["metric_id"]: item.payload for item in items}
    assert by_metric["analyst_consensus_net_profit_fy1"]["value"] == "2427375000.0"
    assert by_metric["analyst_consensus_net_profit_fy1"]["period"] == "2026F"
    assert by_metric["analyst_consensus_revenue_fy3"]["period"] == "2028F"
    assert all(item["official"] is False for item in by_metric.values())
    assert all(item["scale"] == "1" for item in by_metric.values())


def test_forecast_without_security_resolution_fails_closed() -> None:
    batch = _provider(_handler({})).fetch(_forecast_query())
    envelope = batch.envelopes[0]
    assert envelope.status is FetchStatus.FAILED
    assert envelope.error_code == "AGENTGW_SECURITY_IDENTITY_UNSUPPORTED"


# ── environment detection ────────────────────────────────────────────────


def test_environment_detection_requires_credential(tmp_path) -> None:
    environment = KimiAgentGwEnvironment(
        config_path=tmp_path / "missing.json", environ={}
    )
    detection = environment.detect()
    if detection.reason_code != "AGENTGW_SDK_MISSING":
        assert not detection.available
        assert detection.reason_code == "AGENTGW_CREDENTIAL_MISSING"


def test_environment_detection_accepts_process_credential(tmp_path) -> None:
    environment = KimiAgentGwEnvironment(
        config_path=tmp_path / "missing.json",
        environ={"KIMI_API_KEY": "present"},
    )
    detection = environment.detect()
    if detection.reason_code != "AGENTGW_SDK_MISSING":
        assert detection.available


# ── runtime binding ──────────────────────────────────────────────────────


class _FakeEnvironment:
    def __init__(self, available: bool) -> None:
        self._detection = KimiAgentGwDetection(
            available,
            "AGENTGW_AVAILABLE" if available else "AGENTGW_CREDENTIAL_MISSING",
            "test-double",
        )

    def detect(self) -> KimiAgentGwDetection:
        return self._detection

    def build_client(self):  # pragma: no cover - bind never calls the network
        raise AssertionError("build_client must not run during bind")


def _decoded(datasets: tuple[str, ...]) -> DecodedProviderJob:
    policy = canonical_kimi_agentgw_source_policy()
    provider_id, adapter_version, credential = (
        policy.provider_id,
        policy.adapter_version,
        "KIMI_API_KEY",
    )
    job = ProviderJob(
        "ProviderJob@2",
        SecurityIdentity(
            "security_duofuduo", "SZSE", "002407", "CNY", "2010-05-18"
        ),
        None,
        None,
        None,
    )
    request = SyncRequest(
        "inv-1",
        "security_duofuduo",
        "002407",
        "2026-08-01",
        datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc),
        "Asia/Shanghai",
        "SZSE",
        SnapshotPurpose.RESEARCH,
        datasets,
        True,
        False,
    )
    return DecodedProviderJob(
        job,
        request,
        QueryPolicy("QueryPolicy@1", 550, "L", "none"),
        policy,
        provider_id,
        adapter_version,
        credential,
    )


def test_kimi_runtime_fails_closed_outside_kimi_environment() -> None:
    runtime = PreconfiguredKimiAgentGwRuntime(_FakeEnvironment(False))
    with pytest.raises(OperationError) as raised:
        runtime.bind(_decoded(("daily",)))
    assert raised.value.code == "KIMI_AGENTGW_UNAVAILABLE"


def test_kimi_runtime_rejects_tampered_policy() -> None:
    runtime = PreconfiguredKimiAgentGwRuntime(_FakeEnvironment(True))
    decoded = _decoded(("daily",))
    tampered = DecodedProviderJob(
        decoded.job,
        decoded.request,
        decoded.query_policy,
        canonical_official_source_policy("szse-official-disclosure"),
        decoded.provider_id,
        decoded.adapter_version,
        decoded.credential_variable,
    )
    with pytest.raises(OperationError) as raised:
        runtime.bind(tampered)
    assert raised.value.code == "PROVIDER_SOURCE_POLICY_UNTRUSTED"


# ── repository-level acceptance ──────────────────────────────────────────


def test_wind_routed_datasets_pass_repository_coverage_and_snapshot_gates(
    tmp_path,
) -> None:
    """Wind daily/trade_cal/market_universe rows produce a valid PIT snapshot.

    Proves: daily rows carrying ``amount`` pass the repository coverage gate,
    and open-day-only calendar rows plus CN_A_SHARE universe rows yield
    eligible snapshot members.
    """
    from tests.platform.application_task_fixture import PlatformTaskFixture
    from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
    from trading_platform.domain.data import (
        FreshnessStatus,
        QualityStatus,
        SyncStatus,
    )

    index_csv = _csv(
        ["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"],
        [
            ["2026-07-17", "000001.SH", "3800", "3810", "3790", "3805", "1", "1"],
            ["2026-07-20", "000001.SH", "3808", "3858", "3793", "3858", "1", "1"],
        ],
    )
    daily_csv = _csv(
        ["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"],
        [
            ["2026-07-17", "002407.SZ", "31.0", "31.5", "30.5", "31.2", "100000", "3120000"],
            ["2026-07-20", "002407.SZ", "31.66", "32.0", "28.12", "28.12", "135749800", "3857498000"],
        ],
    )

    def handle(payload: dict) -> _Resp:
        assert payload["data_source_name"] == "wind"
        return _ok(
            {
                "wind_get_index_price": index_csv,
                "wind_get_stock_info": WIND_STOCK_INFO_CSV,
                "wind_get_price": daily_csv,
            }[payload["api_name"]]
        )

    provider = _provider(handle)
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=QueryPolicy("QueryPolicy@1", 7, "L", "none"),
        source_policy=canonical_kimi_agentgw_source_policy(),
    )
    root.watchlist.add(
        "watch:security_duofuduo",
        SecurityIdentity("security_duofuduo", "SZSE", "002407", "CNY", "2010-05-18"),
    )
    request = SyncRequest(
        "sync-1",
        "security_duofuduo",
        "002407",
        "2026-07-20",
        datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc),
        "Asia/Shanghai",
        "SZSE",
        SnapshotPurpose.WORKFLOW,
        ("trade_cal", "market_universe", "daily"),
        True,
        False,
    )
    result = root.data.sync(request)
    assert result.status is SyncStatus.COMPLETE, result
    assert result.effective_session_date == "2026-07-20"
    assert result.freshness is FreshnessStatus.VALID
    assert result.quality is QualityStatus.PASS
    assert result.coverage.missing == 0
    assert result.disposition.snapshot_created

    connection = SQLiteOwningAdapterFixture(root.data_root)
    row = connection.execute(
        "SELECT amount_decimal,calendar_version FROM ohlcv_version o "
        "JOIN data_snapshot_member m ON m.normalized_version_id=o.normalized_version_id "
        "JOIN data_snapshot s ON s.data_snapshot_id=m.data_snapshot_id "
        "WHERE s.data_snapshot_id=?",
        (result.snapshot_id,),
    ).fetchone()
    assert row is not None and row["amount_decimal"] is not None
    calendars = connection.execute(
        "SELECT DISTINCT calendar_version FROM market_session_version WHERE market='SZSE'"
    ).fetchall()
    assert [tuple(r) for r in calendars] == [("wind-index-sessions@1",)]
    universe = connection.execute(
        "SELECT market_scope_id FROM market_universe_version"
    ).fetchall()
    assert universe and all(r["market_scope_id"] == "CN_A_SHARE" for r in universe)
    members = connection.execute(
        "SELECT security_id,listed_from,source_ref FROM market_universe_member"
    ).fetchall()
    assert [tuple(r) for r in members] == [
        ("security_duofuduo", "2010-05-18", "wind:wind_get_stock_info:ipo_date:002407.SZ")
    ]
    root.close()
