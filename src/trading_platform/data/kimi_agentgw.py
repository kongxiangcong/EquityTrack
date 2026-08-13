"""Kimi agent-gw structured data provider layer.

This module is the first-priority market/financial data provider when the
platform runs inside a Kimi agent environment, and it is unavailable anywhere
else. It calls the Kimi agent-gw data gateway (Wind / iFinD datasources)
through the deterministic ``agent_gw`` Python SDK.

Hard rules owned by this module:

- Only structured datasource APIs with fixed ``api_name`` plus typed params
  are used. Natural-language question tools and any LLM-mediated path are
  never part of this business-runtime provider, which keeps every call
  deterministic, cacheable, and replayable.
- Credentials are resolved by the SDK from ``KIMI_API_KEY`` or
  ``~/.kimi/agent-gw.json``. The platform never persists, prints, or forwards
  credential values; only their presence is inspected for availability.
- Provenance is honest: every envelope is a structured aggregator candidate
  (Wind/iFinD identity), never official disclosure authority. Announcement
  dates are not fabricated; financial statement availability uses the
  conservative ``retrieved_only`` basis when the upstream API does not
  publish announcement timestamps.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import socket
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from trading_platform.domain.data import (
    DailyOhlcvQuery,
    FetchBatch,
    FetchStatus,
    FinancialStatementQuery,
    ForecastActualQuery,
    MarketDataCapability,
    ProviderCapability,
    ProviderCapabilityStatus,
    RawEnvelope,
    SecurityMasterQuery,
    SourceAuthority,
    TradingCalendarQuery,
    TypedDatasetQuery,
)
from trading_platform.identity import canonical_hash
from trading_platform.operations import OperationError


_AGENTGW_DESTINATION = "agentgw://datasource"
_AGENTGW_CONFIG_PATH = Path.home() / ".kimi" / "agent-gw.json"
_AGENTGW_API_KEY_SCOPE = "KIMI_API_KEY"
_SHANGHAI = timezone(timedelta(hours=8))

IFIND_DATASOURCE = "ifind"
WIND_DATASOURCE = "wind"

# Datasets this layer can serve through structured agent-gw APIs.
KIMI_AGENTGW_DATASETS = frozenset(
    {
        "daily",
        "trade_cal",
        "market_universe",
        "income",
        "balancesheet",
        "cashflow",
        "forecast_actual",
    }
)

# Dataset → datasource routing table (canonical mapping lives in
# skills/references/data-source-map.md; this table is its runtime twin).
_DATASET_DATASOURCE = {
    "daily": WIND_DATASOURCE,
    "trade_cal": WIND_DATASOURCE,
    "market_universe": WIND_DATASOURCE,
    "income": IFIND_DATASOURCE,
    "balancesheet": IFIND_DATASOURCE,
    "cashflow": IFIND_DATASOURCE,
    "forecast_actual": IFIND_DATASOURCE,
}

_TRADE_CAL_VERSION = "wind-index-sessions@1"
_TRADE_CAL_INDEX_TICKER = "000001.SH"
_MARKET_SCOPE_CN_A_SHARE = "CN_A_SHARE"

_STATEMENT_API_NAMES = {
    "income": "income_statement",
    "balancesheet": "balance_sheet",
    "cashflow": "cash_flow",
}

# iFinD field mappings verified against live 2025 annual-report responses.
# Each canonical field maps to an ordered tuple of upstream candidates; the
# first present numeric value wins. Only verified field names appear here.
_INCOME_FIELD_MAP: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("revenue", ("ths_operating_total_revenue_stock", "ths_revenue_stock"), "CNY", "medium"),
    ("net_income", ("ths_np_atoopc_stock",), "CNY", "medium"),
    ("ebit", ("ths_op_stock",), "CNY", "low"),
    ("tax", ("ths_income_tax_cost_stock",), "CNY", "medium"),
    ("eps", ("ths_dlt_earnings_per_share_stock", "ths_basic_eps_stock"), "CNY/share", "medium"),
)

_BALANCESHEET_DEBT_FIELDS = (
    "ths_st_borrow_stock",
    "ths_lt_borrow_stock",
    "ths_bond_payable_stock",
    "ths_noncurrent_liab_due_in1y_stock",
    "ths_lease_libilities_stock",
)

_BALANCESHEET_FIELD_MAP: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("cash", ("ths_currency_fund_stock",), "CNY", "medium"),
    ("lease_debt", ("ths_lease_libilities_stock",), "CNY", "medium"),
    ("minority_interest", ("ths_minority_equity_stock",), "CNY", "medium"),
    ("diluted_shares", ("ths_actual_received_capital_stock",), "shares", "low"),
)

_CASHFLOW_DA_FIELDS = (
    "ths_depreciation_etc_stock",
    "ths_intangible_assets_amortized_stock",
    "ths_rou_depreciation_stock",
)

_FORECAST_METRIC_MAP: tuple[tuple[str, str, str], ...] = (
    ("ths_fore_np_fy1_stock", "analyst_consensus_net_profit_fy1", "0"),
    ("ths_fore_np_fy2_stock", "analyst_consensus_net_profit_fy2", "1"),
    ("ths_fore_np_fy3_stock", "analyst_consensus_net_profit_fy3", "2"),
    ("ths_fore_mbi_fy1_stock", "analyst_consensus_revenue_fy1", "0"),
    ("ths_fore_mbi_fy2_stock", "analyst_consensus_revenue_fy2", "1"),
    ("ths_fore_mbi_fy3_stock", "analyst_consensus_revenue_fy3", "2"),
)


@dataclass(frozen=True)
class KimiAgentGwDetection:
    available: bool
    reason_code: str
    detail: str


class KimiAgentGwEnvironment:
    """Detect whether this runtime is a Kimi agent environment.

    Availability requires both the ``agent_gw`` SDK and a resolvable
    credential (process ``KIMI_API_KEY`` or an ``api_key`` entry in the
    agent-gw config file). Only presence is inspected; values are never
    read into the platform.
    """

    def __init__(
        self,
        config_path: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._config_path = config_path or _AGENTGW_CONFIG_PATH
        self._environ = environ if environ is not None else os.environ

    def detect(self) -> KimiAgentGwDetection:
        try:
            import agent_gw  # noqa: F401
        except ModuleNotFoundError:
            return KimiAgentGwDetection(
                False,
                "AGENTGW_SDK_MISSING",
                "The agent_gw Python SDK is not installed in this runtime.",
            )
        if self._environ.get(_AGENTGW_API_KEY_SCOPE, "").strip():
            return KimiAgentGwDetection(
                True, "AGENTGW_AVAILABLE", "Credential resolved from process environment."
            )
        try:
            if self._config_path.is_file():
                config = json.loads(self._config_path.read_text(encoding="utf-8"))
                if isinstance(config, dict) and str(config.get("api_key", "")).strip():
                    return KimiAgentGwDetection(
                        True,
                        "AGENTGW_AVAILABLE",
                        "Credential present in the agent-gw config file.",
                    )
        except (OSError, json.JSONDecodeError):
            pass
        return KimiAgentGwDetection(
            False,
            "AGENTGW_CREDENTIAL_MISSING",
            "No KIMI_API_KEY and no api_key in the agent-gw config file.",
        )

    def build_client(self, timeout: float = 60.0) -> Any:
        detection = self.detect()
        if not detection.available:
            raise OperationError("KIMI_AGENTGW_UNAVAILABLE", detection.reason_code)
        from agent_gw import AgentGwClient

        return AgentGwClient(timeout=timeout)


def kimi_agentgw_code_identity() -> str:
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def kimi_agentgw_transport_identity(provider_id: str, adapter_version: str) -> str:
    return canonical_hash(
        {
            "provider_id": provider_id,
            "adapter_version": adapter_version,
            "destination": _AGENTGW_DESTINATION,
        }
    )


class _AgentGwCallFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _iso_date(value: object) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _wire_date(value: str) -> str:
    return value.replace("-", "")


def _shanghai_start(value: str) -> str:
    return (
        datetime.fromisoformat(value)
        .replace(tzinfo=_SHANGHAI)
        .isoformat()
    )


def _shanghai_end_of_day(value: str) -> str:
    return (
        datetime.fromisoformat(value)
        .replace(hour=23, minute=59, second=59, tzinfo=_SHANGHAI)
        .isoformat()
    )


def _aggregator_code(code: str, venue: str) -> str:
    """Exchange-suffixed ticker shared by the Wind and iFinD structured APIs."""
    suffix = {"SZSE": "SZ", "SSE": "SH", "BSE": "BJ"}.get(venue)
    if suffix is None or not code.isdigit():
        raise ValueError("PROVIDER_SECURITY_IDENTITY_UNSUPPORTED")
    return f"{code}.{suffix}"


def _agentgw_file_path(stem: str) -> str:
    # Wind upstream escapes backslash+t into a Tab, so the server-side
    # file_path must be a forward-slash absolute path. The platform only
    # consumes the response's files[].content, never the server file.
    return (Path(tempfile.gettempdir()) / stem).as_posix()


def _numeric_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("FINANCIAL_STATEMENT_VALUE_INVALID") from error
    if not parsed.is_finite():
        raise ValueError("FINANCIAL_STATEMENT_VALUE_INVALID")
    return format(parsed, "f")


def _first_numeric(record: Mapping[str, Any], candidates: tuple[str, ...]) -> tuple[str, str] | None:
    for name in candidates:
        if (parsed := _numeric_text(record.get(name))) is not None:
            return name, parsed
    return None


def _sum_numeric(record: Mapping[str, Any], names: tuple[str, ...]) -> tuple[tuple[str, ...], str] | None:
    present = tuple(
        (name, parsed)
        for name in names
        if (parsed := _numeric_text(record.get(name))) is not None
    )
    if not present:
        return None
    total = sum((Decimal(value) for _, value in present), Decimal("0"))
    return tuple(name for name, _ in present), format(total, "f")


def _quarter_ends(start_date: str, end_date: str) -> tuple[str, ...]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    periods: list[str] = []
    for year in range(start.year, end.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            candidate = date(year, month, day)
            if start <= candidate <= end:
                periods.append(f"{year}{month:02d}{day:02d}")
    return tuple(periods)


def _report_type(period_end: str) -> str:
    return {"0331": "Q1", "0630": "H1", "0930": "Q3", "1231": "A"}[period_end[4:]]


def _transport_failure_code(error: BaseException) -> str:
    cause: BaseException = error
    while cause.__cause__ is not None:
        cause = cause.__cause__
    if isinstance(cause, socket.gaierror):
        return "PROVIDER_DNS_FAILED"
    if isinstance(cause, ConnectionRefusedError):
        return "PROVIDER_CONNECTION_REFUSED"
    if isinstance(cause, TimeoutError):
        return "PROVIDER_TIMEOUT"
    return "PROVIDER_TRANSPORT_FAILED"


def _sdk_error_code(error: BaseException) -> str:
    name = type(error).__name__
    if name == "RateLimitError":
        return "PROVIDER_API_RATE_LIMITED"
    if name == "AuthenticationError":
        return "AUTHENTICATION_FAILED"
    if name == "PaymentRequiredError":
        return "PROVIDER_API_ENTITLEMENT_UNAVAILABLE"
    if name == "ServerError":
        return "PROVIDER_HTTP_FAILED"
    if name == "TransportError":
        return _transport_failure_code(error)
    return "PROVIDER_API_REJECTED"


class KimiAgentGatewayProvider:
    """Own the Kimi agent-gw transport and typed-query translation.

    Structured Wind/iFinD datasource APIs back every supported dataset,
    routed per dataset by ``_DATASET_DATASOURCE``; the
    payload emitted is the canonical ``{"rows": [...]}`` document consumed
    by the platform normalizer, so downstream evidence handling is identical
    to any other provider.
    """

    fixture = False
    capabilities = (
        ProviderCapability(MarketDataCapability.TRADING_CALENDAR, ProviderCapabilityStatus.SUPPORTED, "WIND_INDEX_SESSIONS"),
        ProviderCapability(MarketDataCapability.DAILY_UNADJUSTED, ProviderCapabilityStatus.SUPPORTED, "WIND_GET_PRICE_UNADJUSTED"),
        ProviderCapability(MarketDataCapability.ADJUSTMENT_FACTORS, ProviderCapabilityStatus.UNAVAILABLE, "AGENTGW_STRUCTURED_ADJ_FACTOR_UNAVAILABLE"),
        ProviderCapability(MarketDataCapability.CORPORATE_ACTIONS, ProviderCapabilityStatus.UNAVAILABLE, "AGENTGW_STRUCTURED_CORP_ACTION_UNAVAILABLE"),
        ProviderCapability(MarketDataCapability.SUSPENSION_STATUS, ProviderCapabilityStatus.UNAVAILABLE, "AGENTGW_STRUCTURED_SUSPENSION_UNAVAILABLE"),
        ProviderCapability(MarketDataCapability.PRICE_LIMIT_STATUS, ProviderCapabilityStatus.UNAVAILABLE, "AGENTGW_STRUCTURED_PRICE_LIMIT_UNAVAILABLE"),
    )

    def __init__(
        self,
        provider_id: str,
        adapter_version: str,
        source_identity: str,
        terms_profile: str,
        client_factory: Callable[[], Any],
        source_authority: SourceAuthority = SourceAuthority.STRUCTURED_AGGREGATOR,
        forecast_security_resolver: Callable[[str], tuple[str, str] | None] | None = None,
    ) -> None:
        self.code_identity = kimi_agentgw_code_identity()
        self.provider_id = provider_id
        self.adapter_version = adapter_version
        self.transport_identity = kimi_agentgw_transport_identity(provider_id, adapter_version)
        self._source_identity = source_identity
        self._terms_profile = terms_profile
        self._source_authority = source_authority
        self._client_factory = client_factory
        # ForecastActualQuery carries only security_id; the composition root
        # resolves it to (code, venue) from the job's security identity.
        self._forecast_security_resolver = forecast_security_resolver

    # ── envelope helpers ────────────────────────────────────────────────

    def _envelope(
        self,
        params: Mapping[str, str],
        now: datetime,
        status: FetchStatus,
        payload: bytes | None,
        error_code: str | None,
        cursor_value: str | None = None,
    ) -> RawEnvelope:
        return RawEnvelope(
            source_identity=self._source_identity,
            source_authority=self._source_authority,
            real_source_url=_AGENTGW_DESTINATION,
            redacted_params=params,
            response_headers={},
            source_time_precision="not_applicable",
            terms_profile=self._terms_profile,
            retrieved_at=now,
            status=status,
            payload=payload,
            raw_sha256=hashlib.sha256(payload).hexdigest() if payload is not None else None,
            cursor_value=cursor_value,
            error_code=error_code,
        )

    def _failure(self, params: Mapping[str, str], now: datetime, code: str, status: FetchStatus = FetchStatus.FAILED) -> FetchBatch:
        return FetchBatch((self._envelope(params, now, status, None, code),))

    # ── agent-gw call ───────────────────────────────────────────────────

    def _call_rows(self, dataset: str, api_name: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
        client = self._client_factory()
        try:
            response = client.tools.call_data_source_tool(
                {
                    "data_source_name": _DATASET_DATASOURCE[dataset],
                    "api_name": api_name,
                    "params": dict(params),
                }
            )
            raw = response.raw
        except TimeoutError as error:
            raise _AgentGwCallFailure("PROVIDER_TIMEOUT") from error
        except Exception as error:  # SDK error taxonomy mapped by class name
            raise _AgentGwCallFailure(_sdk_error_code(error)) from error
        if not isinstance(raw, Mapping) or not raw.get("is_success"):
            message = ""
            if isinstance(raw, Mapping):
                message = json.dumps(
                    raw.get("error") or raw.get("result") or {},
                    ensure_ascii=False,
                    default=str,
                )
            code = (
                "PROVIDER_API_ENTITLEMENT_UNAVAILABLE"
                if "权限不足" in message
                else "PROVIDER_API_REJECTED"
            )
            raise _AgentGwCallFailure(code)
        files = raw.get("files") or []
        content = None
        for file_info in files:
            if isinstance(file_info, Mapping) and file_info.get("content"):
                content = str(file_info["content"])
                break
        if content is None:
            raise _AgentGwCallFailure("AGENTGW_RESPONSE_INVALID")
        return list(csv.DictReader(io.StringIO(content)))

    # ── dataset handlers ────────────────────────────────────────────────

    def fetch(self, query: TypedDatasetQuery) -> FetchBatch:
        now = datetime.now(timezone.utc)
        if isinstance(query, DailyOhlcvQuery):
            params: Mapping[str, str] = {
                "ticker": _aggregator_code(query.security_code, query.venue),
                "start_date": query.start_date,
                "end_date": query.end_date,
                "price_adj": "N",
                "frequency": "D",
            }
            handler = lambda: self._daily_rows(query)
        elif isinstance(query, TradingCalendarQuery):
            params = {
                "ticker": _TRADE_CAL_INDEX_TICKER,
                "market": query.market,
                "start_date": query.start_date,
                "end_date": query.end_date,
            }
            handler = lambda: self._trade_cal_rows(query)
        elif isinstance(query, SecurityMasterQuery):
            params = {
                "ticker": _aggregator_code(query.security_code, query.venue),
                "market_scope_id": _MARKET_SCOPE_CN_A_SHARE,
                "as_of_date": query.as_of_date,
            }
            handler = lambda: self._market_universe_rows(query)
        elif isinstance(query, FinancialStatementQuery):
            params = {
                "ticker": _aggregator_code(query.security_code, query.venue),
                "statement": _STATEMENT_API_NAMES[query.dataset],
                "start_date": query.start_date,
                "end_date": query.end_date,
            }
            handler = lambda: self._statement_rows(query, now)
        elif isinstance(query, ForecastActualQuery):
            resolved = (
                self._forecast_security_resolver(query.security_id)
                if self._forecast_security_resolver is not None
                else None
            )
            if resolved is None:
                return self._failure(
                    {
                        "security_id": query.security_id,
                        "as_of_date": query.as_of_date,
                    },
                    now,
                    "AGENTGW_SECURITY_IDENTITY_UNSUPPORTED",
                )
            ticker = _aggregator_code(*resolved)
            params = {
                "ticker": ticker,
                "as_of_date": query.as_of_date,
            }
            handler = lambda: self._forecast_rows(query, now, ticker)
        else:
            return self._failure(
                {"dataset": query.dataset}, now, "AGENTGW_QUERY_UNSUPPORTED"
            )
        if not query.network_authorized:
            return self._failure(params, now, "NETWORK_NOT_AUTHORIZED")
        try:
            rows = handler()
        except _AgentGwCallFailure as error:
            status = (
                FetchStatus.RATE_LIMITED
                if error.code == "PROVIDER_API_RATE_LIMITED"
                else FetchStatus.FAILED
            )
            return self._failure(params, now, error.code, status)
        except ValueError as error:
            return self._failure(params, now, str(error))
        if not rows:
            return self._failure(params, now, "AGENTGW_DATASET_EMPTY", FetchStatus.MISSING)
        payload = json.dumps(
            {"rows": rows}, ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode("utf-8")
        cursor = (
            query.as_of_date
            if isinstance(query, (ForecastActualQuery, SecurityMasterQuery))
            else query.end_date
        )
        return FetchBatch(
            (self._envelope(params, now, FetchStatus.COMPLETE, payload, None, cursor),)
        )

    def _daily_rows(self, query: DailyOhlcvQuery) -> list[dict[str, Any]]:
        ticker = _aggregator_code(query.security_code, query.venue)
        records = self._call_rows(
            query.dataset,
            "wind_get_price",
            {
                "ticker": ticker,
                "start_date": query.start_date,
                "end_date": query.end_date,
                "price_adj": "N",
                "frequency": "D",
                "file_path": _agentgw_file_path(
                    f"agentgw-daily-{ticker}-{query.start_date}-{query.end_date}.csv"
                ),
            },
        )
        rows: list[dict[str, Any]] = []
        for record in records:
            session_date = _iso_date(record.get("trade_date", ""))
            try:
                date.fromisoformat(session_date)
            except ValueError:
                continue
            rows.append(
                {
                    "security_id": query.security_id,
                    "session_date": session_date,
                    "market_timezone": "Asia/Shanghai",
                    "adjustment_mode": "none",
                    "open": record.get("open"),
                    "high": record.get("high"),
                    "low": record.get("low"),
                    "close": record.get("close"),
                    "volume": record.get("volume"),
                    "volume_unit": "share",
                    "amount": record.get("amt"),
                    "amount_unit": "yuan",
                    "currency": record.get("currency") or "CNY",
                    "published_at": session_date,
                    "published_precision": "date",
                    "available_at": _shanghai_end_of_day(session_date),
                    "availability_basis": "conservative_end_of_session_date",
                }
            )
        return rows

    def _trade_cal_rows(self, query: TradingCalendarQuery) -> list[dict[str, Any]]:
        records = self._call_rows(
            query.dataset,
            "wind_get_index_price",
            {
                "ticker": _TRADE_CAL_INDEX_TICKER,
                "start_date": query.start_date,
                "end_date": query.end_date,
                "file_path": _agentgw_file_path(
                    f"agentgw-trade-cal-{query.start_date}-{query.end_date}.csv"
                ),
            },
        )
        rows: list[dict[str, Any]] = []
        for record in records:
            session_date = _iso_date(record.get("trade_date", ""))
            try:
                date.fromisoformat(session_date)
            except ValueError:
                continue
            rows.append(
                {
                    "market": query.market,
                    "session_date": session_date,
                    # Index sessions enumerate open days only.
                    "is_open": True,
                    "calendar_version": _TRADE_CAL_VERSION,
                    "published_at": session_date,
                    "published_precision": "date",
                    "available_at": _shanghai_start(session_date),
                    "availability_basis": "publisher_timestamp",
                }
            )
        return rows

    def _market_universe_rows(self, query: SecurityMasterQuery) -> list[dict[str, Any]]:
        ticker = _aggregator_code(query.security_code, query.venue)
        listed_from: str | None = None
        source_ref: str | None = None
        records = self._call_rows(
            query.dataset,
            "wind_get_stock_info",
            {
                "ticker": ticker,
                "fields": "ipo_date",
                "file_path": _agentgw_file_path(f"agentgw-stock-info-{ticker}.csv"),
            },
        )
        for record in records:
            candidate = _iso_date(
                record.get("ipo_date")
                or record.get("首发上市日期")
                or record.get("list_date")
                or ""
            )
            try:
                date.fromisoformat(candidate)
            except ValueError:
                continue
            listed_from = candidate
            source_ref = f"wind:wind_get_stock_info:ipo_date:{ticker}"
            break
        if listed_from is None:
            # Fallback: earliest daily session over a long window bounds the
            # listing date from below when the reference field is absent.
            records = self._call_rows(
                query.dataset,
                "wind_get_price",
                {
                    "ticker": ticker,
                    "start_date": "1990-12-19",
                    "end_date": query.as_of_date,
                    "price_adj": "N",
                    "frequency": "D",
                    "file_path": _agentgw_file_path(
                        f"agentgw-first-session-{ticker}-{query.as_of_date}.csv"
                    ),
                },
            )
            for record in records:
                candidate = _iso_date(record.get("trade_date", ""))
                try:
                    date.fromisoformat(candidate)
                except ValueError:
                    continue
                listed_from = candidate
                source_ref = f"wind:wind_get_price:first_session:{ticker}"
                break
        if listed_from is None or source_ref is None:
            return []
        return [
            {
                "market_scope_id": _MARKET_SCOPE_CN_A_SHARE,
                "security_id": query.security_id,
                "listed_from": listed_from,
                "source_ref": source_ref,
                "published_at": listed_from,
                "published_precision": "date",
                "available_at": _shanghai_start(listed_from),
                "availability_basis": "publisher_timestamp",
            }
        ]

    def _statement_rows(
        self, query: FinancialStatementQuery, now: datetime
    ) -> list[dict[str, Any]]:
        ticker = _aggregator_code(query.security_code, query.venue)
        retrieved = now.astimezone(_SHANGHAI).isoformat()
        rows: list[dict[str, Any]] = []
        for period in _quarter_ends(query.start_date, query.end_date):
            records = self._call_rows(
                query.dataset,
                "ifind_get_financial_statements",
                {
                    "ticker": ticker,
                    "statement": _STATEMENT_API_NAMES[query.dataset],
                    "financial_parameter": period,
                    "file_path": _agentgw_file_path(
                        f"agentgw-{query.dataset}-{ticker}-{period}.csv"
                    ),
                },
            )
            if not records:
                continue
            record = records[0]
            period_iso = _iso_date(period)
            fields = _statement_extracted_fields(
                query.dataset, record, query.security_id, period_iso
            )
            if not fields:
                continue
            rows.append(
                {
                    "security_id": query.security_id,
                    "statement_kind": query.dataset,
                    "period_end": period_iso,
                    "report_type": _report_type(period),
                    # The structured API exposes no announcement timestamp;
                    # availability is conservatively bounded by retrieval.
                    "published_at": retrieved,
                    "published_precision": "microsecond",
                    "available_at": retrieved,
                    "availability_basis": "retrieved_only",
                    "currency": "CNY",
                    "accounting_standard": "PRC-GAAP",
                    "extracted_fields": fields,
                }
            )
        return rows

    def _forecast_rows(self, query: ForecastActualQuery, now: datetime, ticker: str) -> list[dict[str, Any]]:
        records = self._call_rows(
            query.dataset,
            "ifind_get_forecast",
            {
                "ticker": ticker,
                "file_path": _agentgw_file_path(
                    f"agentgw-forecast-{ticker}-{query.as_of_date}.csv"
                ),
            },
        )
        if not records:
            return []
        record = records[0]
        retrieved = now.astimezone(_SHANGHAI).isoformat()
        base_year = date.fromisoformat(query.as_of_date).year
        rows: list[dict[str, Any]] = []
        for field, metric_id, year_offset in _FORECAST_METRIC_MAP:
            if (value := _numeric_text(record.get(field))) is None:
                continue
            rows.append(
                {
                    "security_id": query.security_id,
                    "metric_id": metric_id,
                    "value": value,
                    "unit": "CNY",
                    "scale": "1",
                    "currency": "CNY",
                    "period": f"{base_year + int(year_offset)}F",
                    "published_at": retrieved,
                    "published_precision": "microsecond",
                    "available_at": retrieved,
                    # The structured API publishes no consensus timestamp;
                    # availability is conservatively bounded by retrieval.
                    "availability_basis": "retrieved_only",
                    "source_id": "kimi_agentgw_ifind_analyst_consensus",
                    "official": False,
                    "comparability_status": "aggregator_consensus_unverified",
                }
            )
        return rows


def _extracted_field(
    field_name: str,
    value: str,
    *,
    period: str,
    security_id: str,
    dataset: str,
    provider_fields: tuple[str, ...],
    unit: str,
    confidence: str,
) -> dict[str, object]:
    return {
        "field_name": field_name,
        "subject_id": security_id,
        "semantic_role": field_name,
        "period": period,
        "value": value,
        "unit": unit,
        "currency": "CNY",
        "extraction_method": (
            f"agentgw:ifind:ifind_get_financial_statements:{dataset}:"
            f"{'+'.join(provider_fields)}"
        ),
        "confidence": confidence,
        "notes": "Structured aggregator candidate via Kimi agent-gw; not official filing evidence.",
    }


def _statement_extracted_fields(
    dataset: str, record: Mapping[str, Any], security_id: str, period: str
) -> list[dict[str, object]]:
    specs: list[tuple[str, str, tuple[str, ...], str, str]] = []
    if dataset == "income":
        for field_name, candidates, unit, confidence in _INCOME_FIELD_MAP:
            if (found := _first_numeric(record, candidates)) is not None:
                name, value = found
                specs.append((field_name, value, (name,), unit, confidence))
    elif dataset == "balancesheet":
        for field_name, candidates, unit, confidence in _BALANCESHEET_FIELD_MAP:
            if (found := _first_numeric(record, candidates)) is not None:
                name, value = found
                specs.append((field_name, value, (name,), unit, confidence))
        if (debt := _sum_numeric(record, _BALANCESHEET_DEBT_FIELDS)) is not None:
            names, value = debt
            specs.append(("debt", value, names, "CNY", "low"))
        current_assets = _numeric_text(record.get("ths_total_current_assets_stock"))
        current_liabilities = _numeric_text(record.get("ths_total_current_liab_stock"))
        if current_assets is not None and current_liabilities is not None:
            working_capital = format(
                Decimal(current_assets) - Decimal(current_liabilities), "f"
            )
            specs.append(
                (
                    "working_capital",
                    working_capital,
                    ("ths_total_current_assets_stock", "ths_total_current_liab_stock"),
                    "CNY",
                    "medium",
                )
            )
    elif dataset == "cashflow":
        if (found := _first_numeric(record, ("ths_ncf_from_oa_stock",))) is not None:
            name, value = found
            specs.append(("cfo", value, (name,), "CNY", "medium"))
        if (found := _first_numeric(record, ("ths_cash_paid_for_assets_stock",))) is not None:
            name, value = found
            specs.append(("capex", value, (name,), "CNY", "medium"))
        cfo = _numeric_text(record.get("ths_ncf_from_oa_stock"))
        capex = _numeric_text(record.get("ths_cash_paid_for_assets_stock"))
        if cfo is not None and capex is not None:
            specs.append(
                (
                    "fcf",
                    format(Decimal(cfo) - Decimal(capex), "f"),
                    ("ths_ncf_from_oa_stock", "ths_cash_paid_for_assets_stock"),
                    "CNY",
                    "low",
                )
            )
        if (da := _sum_numeric(record, _CASHFLOW_DA_FIELDS)) is not None:
            names, value = da
            specs.append(("d_and_a", value, names, "CNY", "low"))
    return [
        _extracted_field(
            field_name,
            value,
            period=period,
            security_id=security_id,
            dataset=dataset,
            provider_fields=provider_fields,
            unit=unit,
            confidence=confidence,
        )
        for field_name, value, provider_fields, unit, confidence in specs
    ]


__all__ = [
    "IFIND_DATASOURCE",
    "KIMI_AGENTGW_DATASETS",
    "KimiAgentGwDetection",
    "KimiAgentGwEnvironment",
    "KimiAgentGatewayProvider",
    "WIND_DATASOURCE",
    "kimi_agentgw_code_identity",
    "kimi_agentgw_transport_identity",
]
