from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from trading_platform.domain.data import QualityStatus


ALLOWED_AVAILABILITY_BASES = {"publisher_timestamp", "conservative_next_session", "market_close_plus_provider_delay", "documented_provider_schedule", "retrieved_only"}


@dataclass(frozen=True)
class NormalizedItem:
    dataset: str
    natural_key: str
    payload: Mapping[str, Any]
    event_at: str | None
    published_at: str | None
    published_precision: str | None
    available_at: str
    availability_basis: str
    retrieved_at: str
    quality: QualityStatus
    issues: tuple[tuple[str, str], ...]


def _decimal(row: Mapping[str, Any], key: str) -> Decimal:
    value = Decimal(str(row[key]))
    if not value.is_finite():
        raise InvalidOperation(key)
    return value


def _iso_date(value: object) -> str:
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def normalize(dataset: str, payload: bytes, security_id: str | None = None, market: str | None = None, source_ref: str = "provider", retrieved_at: datetime | None = None) -> tuple[NormalizedItem, ...]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("SCHEMA_DRIFT") from error
    rows = document.get("rows") if isinstance(document, dict) else None
    if rows is None and isinstance(document, dict) and isinstance(document.get("data"), dict):
        fields = document["data"].get("fields")
        values = document["data"].get("items")
        if isinstance(fields, list) and isinstance(values, list):
            source_rows = [dict(zip(fields, item)) for item in values]
            rows = []
            for source in source_rows:
                conservative_available_at = (retrieved_at or datetime.now().astimezone()).isoformat()
                if dataset == "daily":
                    session_date = _iso_date(source.get("trade_date"))
                    rows.append({"security_id": security_id, "session_date": session_date, "market_timezone": "Asia/Shanghai", "adjustment_mode": "none", "open": source.get("open"), "high": source.get("high"), "low": source.get("low"), "close": source.get("close"), "volume": source.get("vol"), "volume_unit": "hand", "amount": source.get("amount"), "amount_unit": "thousand_cny", "currency": "CNY", "published_at": session_date, "published_precision": "date", "available_at": conservative_available_at, "availability_basis": "retrieved_only"})
                elif dataset == "trade_cal":
                    session_date = _iso_date(source.get("cal_date"))
                    rows.append({"market": source.get("exchange") or market, "session_date": session_date, "is_open": bool(source.get("is_open")), "calendar_version": "provider-calendar@1", "published_at": session_date, "published_precision": "date", "available_at": conservative_available_at, "availability_basis": "retrieved_only"})
                elif dataset == "market_universe":
                    listed_from = _iso_date(source.get("list_date"))
                    rows.append({"market_scope_id": market, "security_id": security_id, "listed_from": listed_from, "source_ref": f"{source_ref}:stock_basic:{source.get('ts_code')}", "published_at": listed_from, "published_precision": "date", "available_at": conservative_available_at, "availability_basis": "retrieved_only"})
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_PAYLOAD")
    items: list[NormalizedItem] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("SCHEMA_DRIFT")
        available_at = str(row.get("available_at", ""))
        basis = str(row.get("availability_basis", ""))
        issues: list[tuple[str, str]] = []
        quality = QualityStatus.PASS
        if not available_at or basis not in ALLOWED_AVAILABILITY_BASES:
            quality = QualityStatus.BLOCKING
            issues.append(("blocking", "AVAILABILITY_BASIS_MISSING"))
        else:
            try:
                parse_instant(available_at)
            except ValueError:
                quality = QualityStatus.BLOCKING
                issues.append(("blocking", "AVAILABLE_AT_INVALID"))
        if dataset == "daily":
            required = {"security_id", "session_date", "open", "high", "low", "close", "volume", "volume_unit", "currency", "adjustment_mode"}
            if not required.issubset(row):
                raise ValueError("SCHEMA_DRIFT")
            try:
                open_, high, low, close, volume = (_decimal(row, key) for key in ("open", "high", "low", "close", "volume"))
            except (InvalidOperation, KeyError) as error:
                raise ValueError("SCHEMA_DRIFT") from error
            if row["adjustment_mode"] != "none" or high < max(open_, close) or low > min(open_, close) or volume < 0:
                quality = QualityStatus.QUARANTINE
                issues.append(("quarantine", "OHLCV_INVALID"))
            natural_key = f"{row['security_id']}:{row['session_date']}:none"
            event_at = str(row["session_date"])
        elif dataset == "trade_cal":
            required = {"market", "session_date", "is_open", "calendar_version"}
            if not required.issubset(row): raise ValueError("SCHEMA_DRIFT")
            natural_key = f"{row['market']}:{row['session_date']}:{row['calendar_version']}"
            event_at = str(row["session_date"])
        elif dataset == "market_universe":
            required = {"market_scope_id", "security_id", "listed_from", "source_ref"}
            if not required.issubset(row): raise ValueError("SCHEMA_DRIFT")
            natural_key = f"{row['market_scope_id']}:{row['security_id']}:{row['listed_from']}"
            event_at = str(row["listed_from"])
        elif dataset == "forecast_actual":
            required = {
                "security_id",
                "metric_id",
                "value",
                "unit",
                "scale",
                "currency",
                "period",
                "published_at",
                "available_at",
                "source_id",
                "official",
                "comparability_status",
            }
            if not required.issubset(row):
                raise ValueError("SCHEMA_DRIFT")
            natural_key = f"{row['security_id']}:{row['metric_id']}:{row['period']}"
            event_at = str(row["period"])
            row = {
                key: row[key]
                for key in (
                    "metric_id",
                    "value",
                    "unit",
                    "scale",
                    "currency",
                    "period",
                    "published_at",
                    "available_at",
                    "source_id",
                    "official",
                    "comparability_status",
                )
            }
        else:
            raise ValueError("DATASET_UNSUPPORTED")
        retrieved = (retrieved_at or datetime.now().astimezone()).isoformat()
        items.append(NormalizedItem(dataset, natural_key, row, event_at, row.get("published_at"), row.get("published_precision"), available_at, basis, retrieved, quality, tuple(issues)))
    return tuple(items)


def parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_MISSING")
    return parsed
