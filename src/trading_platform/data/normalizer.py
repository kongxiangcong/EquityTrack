from __future__ import annotations

import json
import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from trading_platform.domain.data import QualityStatus


ALLOWED_AVAILABILITY_BASES = {
    "publisher_timestamp",
    "conservative_next_calendar_day",
    "conservative_end_of_session_date",
    "documented_provider_schedule",
    "retrieved_only",
}


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


def _shanghai_start(value: object, *, next_day: bool = False) -> str:
    parsed = datetime.fromisoformat(_iso_date(value))
    if next_day:
        parsed += timedelta(days=1)
    return parsed.replace(tzinfo=timezone(timedelta(hours=8))).isoformat()


def _shanghai_end_of_day(value: object) -> str:
    parsed = datetime.fromisoformat(_iso_date(value)).replace(
        hour=23,
        minute=59,
        second=59,
        tzinfo=timezone(timedelta(hours=8)),
    )
    return parsed.isoformat()


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


def _financial_field(
    *,
    field_name: str,
    value: object,
    period: str,
    security_id: str,
    dataset: str,
    provider_fields: tuple[str, ...],
    unit: str = "CNY",
    confidence: str = "medium",
) -> dict[str, object] | None:
    numeric = _numeric_text(value)
    if numeric is None:
        return None
    return {
        "field_name": field_name,
        "subject_id": security_id,
        "semantic_role": field_name,
        "period": period,
        "value": numeric,
        "unit": unit,
        "currency": "CNY",
        "extraction_method": (
            f"tushare_compatible:{dataset}:{'+'.join(provider_fields)}"
        ),
        "confidence": confidence,
        "notes": (
            "Structured aggregator candidate; not official filing evidence."
        ),
    }


def _sum_fields(
    source: Mapping[str, Any], names: tuple[str, ...]
) -> str | None:
    values = [
        parsed
        for name in names
        if (parsed := _numeric_text(source.get(name))) is not None
    ]
    if not values:
        return None
    return format(sum((Decimal(value) for value in values), Decimal("0")), "f")


def _financial_extracted_fields(
    dataset: str, source: Mapping[str, Any], security_id: str, period: str
) -> list[dict[str, object]]:
    specs: list[tuple[str, object, tuple[str, ...], str, str]] = []
    if dataset == "income":
        revenue_field = (
            "revenue"
            if source.get("revenue") not in {None, ""}
            else "total_revenue"
        )
        eps_field = (
            "diluted_eps"
            if source.get("diluted_eps") not in {None, ""}
            else "basic_eps"
        )
        specs = [
            ("revenue", source.get(revenue_field), (revenue_field,), "CNY", "medium"),
            ("net_income", source.get("n_income_attr_p"), ("n_income_attr_p",), "CNY", "medium"),
            ("ebit", source.get("operate_profit"), ("operate_profit",), "CNY", "low"),
            ("tax", source.get("income_tax"), ("income_tax",), "CNY", "medium"),
            ("eps", source.get(eps_field), (eps_field,), "CNY/share", "medium"),
        ]
    elif dataset == "balancesheet":
        debt_fields = (
            "st_borr",
            "lt_borr",
            "bond_payable",
            "non_cur_liab_due_1y",
            "lease_liab",
        )
        working_capital = None
        current_assets = _numeric_text(source.get("total_cur_assets"))
        current_liabilities = _numeric_text(source.get("total_cur_liab"))
        if current_assets is not None and current_liabilities is not None:
            working_capital = format(
                Decimal(current_assets) - Decimal(current_liabilities), "f"
            )
        specs = [
            ("cash", source.get("money_cap"), ("money_cap",), "CNY", "medium"),
            ("debt", _sum_fields(source, debt_fields), debt_fields, "CNY", "low"),
            ("lease_debt", source.get("lease_liab"), ("lease_liab",), "CNY", "medium"),
            ("minority_interest", source.get("minority_int"), ("minority_int",), "CNY", "medium"),
            ("diluted_shares", source.get("total_share"), ("total_share",), "shares", "low"),
            ("working_capital", working_capital, ("total_cur_assets", "total_cur_liab"), "CNY", "medium"),
        ]
    elif dataset == "cashflow":
        depreciation_fields = (
            "depr_fa_coga_dpba",
            "amort_intang_assets",
            "lt_amort_deferred_exp",
        )
        cfo = _numeric_text(source.get("n_cashflow_act"))
        capex = _numeric_text(source.get("c_pay_acq_const_fiolta"))
        fcf = (
            None
            if cfo is None or capex is None
            else format(Decimal(cfo) - Decimal(capex), "f")
        )
        specs = [
            ("cfo", cfo, ("n_cashflow_act",), "CNY", "medium"),
            ("capex", capex, ("c_pay_acq_const_fiolta",), "CNY", "medium"),
            ("fcf", fcf, ("n_cashflow_act", "c_pay_acq_const_fiolta"), "CNY", "low"),
            ("d_and_a", _sum_fields(source, depreciation_fields), depreciation_fields, "CNY", "low"),
        ]
    return [
        field
        for field_name, value, provider_fields, unit, confidence in specs
        if (
            field := _financial_field(
                field_name=field_name,
                value=value,
                period=period,
                security_id=security_id,
                dataset=dataset,
                provider_fields=provider_fields,
                unit=unit,
                confidence=confidence,
            )
        )
        is not None
    ]


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
            if dataset in {"income", "balancesheet", "cashflow"}:
                selected: dict[tuple[str, str], Mapping[str, Any]] = {}
                for source in source_rows:
                    key = (
                        str(source.get("end_date", "")),
                        str(source.get("report_type", "")),
                    )
                    rank = (
                        str(source.get("update_flag", "")) == "1",
                        str(source.get("f_ann_date") or ""),
                        str(source.get("ann_date") or ""),
                    )
                    current = selected.get(key)
                    if current is None:
                        selected[key] = source
                        continue
                    current_rank = (
                        str(current.get("update_flag", "")) == "1",
                        str(current.get("f_ann_date") or ""),
                        str(current.get("ann_date") or ""),
                    )
                    if rank > current_rank:
                        selected[key] = source
                source_rows = [
                    selected[key] for key in sorted(selected)
                ]
            rows = []
            for source in source_rows:
                conservative_available_at = (retrieved_at or datetime.now().astimezone()).isoformat()
                if dataset == "daily":
                    session_date = _iso_date(source.get("trade_date"))
                    rows.append({"security_id": security_id, "session_date": session_date, "market_timezone": "Asia/Shanghai", "adjustment_mode": "none", "open": source.get("open"), "high": source.get("high"), "low": source.get("low"), "close": source.get("close"), "volume": source.get("vol"), "volume_unit": "hand", "amount": source.get("amount"), "amount_unit": "thousand_cny", "currency": "CNY", "published_at": session_date, "published_precision": "date", "available_at": _shanghai_end_of_day(session_date), "availability_basis": "conservative_end_of_session_date"})
                elif dataset == "trade_cal":
                    session_date = _iso_date(source.get("cal_date"))
                    rows.append({"market": source.get("exchange") or market, "session_date": session_date, "is_open": bool(source.get("is_open")), "calendar_version": "provider-calendar@1", "published_at": session_date, "published_precision": "date", "available_at": _shanghai_start(session_date), "availability_basis": "publisher_timestamp"})
                elif dataset == "market_universe":
                    listed_from = _iso_date(source.get("list_date"))
                    rows.append({"market_scope_id": "CN_A_SHARE" if market in {"SSE", "SZSE", "BSE"} else market, "security_id": security_id, "listed_from": listed_from, "source_ref": f"{source_ref}:stock_basic:{source.get('ts_code')}", "published_at": listed_from, "published_precision": "date", "available_at": _shanghai_start(listed_from), "availability_basis": "publisher_timestamp"})
                elif dataset in {"income", "balancesheet", "cashflow"}:
                    if security_id is None:
                        raise ValueError("FINANCIAL_STATEMENT_SECURITY_REQUIRED")
                    period = _iso_date(source.get("end_date"))
                    announced = source.get("f_ann_date") or source.get("ann_date")
                    if (
                        not period
                        or period == "None"
                        or announced in {None, ""}
                    ):
                        raise ValueError("FINANCIAL_STATEMENT_TIME_MISSING")
                    rows.append(
                        {
                            "security_id": security_id,
                            "statement_kind": dataset,
                            "period_end": period,
                            "report_type": str(source.get("report_type", "")),
                            "update_flag": str(source.get("update_flag", "")),
                            "published_at": _shanghai_start(announced),
                            "published_precision": "date",
                            "available_at": _shanghai_start(
                                announced, next_day=True
                            ),
                            "availability_basis": "conservative_next_calendar_day",
                            "currency": "CNY",
                            "accounting_standard": "PRC-GAAP",
                            "extracted_fields": _financial_extracted_fields(
                                dataset, source, security_id, period
                            ),
                        }
                    )
    if not isinstance(rows, list):
        raise ValueError("SCHEMA_DRIFT")
    if not rows:
        raise ValueError("EMPTY_CONFIRMED")
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
            market_path_keys = {
                "adjustment_factor",
                "suspended",
                "limit_state",
            }
            present_market_path_keys = market_path_keys.intersection(row)
            if present_market_path_keys and present_market_path_keys != market_path_keys:
                raise ValueError("MARKET_PATH_DAILY_EVIDENCE_INCOMPLETE")
            if present_market_path_keys:
                try:
                    factor = _decimal(row, "adjustment_factor")
                except (InvalidOperation, KeyError) as error:
                    raise ValueError("MARKET_PATH_ADJUSTMENT_FACTOR_INVALID") from error
                if (
                    factor <= 0
                    or type(row["suspended"]) is not bool
                    or row["limit_state"] not in {"none", "up", "down"}
                    or (
                        row.get("corporate_action_identity") is not None
                        and not str(row["corporate_action_identity"])
                    )
                ):
                    raise ValueError("MARKET_PATH_DAILY_EVIDENCE_INVALID")
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
        elif dataset in {"research_model_input", "market_path_policy"}:
            required = {
                "component_input_id",
                "security_id",
                "published_at",
                "available_at",
                "extracted_fields",
            }
            if not required.issubset(row) or row["security_id"] != security_id:
                raise ValueError("RESEARCH_COMPONENT_INPUT_IDENTITY_INVALID")
            component_input_id = str(row["component_input_id"])
            fields = row["extracted_fields"]
            if not component_input_id or not isinstance(fields, list) or not fields:
                raise ValueError("RESEARCH_COMPONENT_INPUT_FIELDS_MISSING")
            field_required = {
                "field_name",
                "subject_id",
                "semantic_role",
                "period",
                "value",
                "unit",
                "currency",
                "extraction_method",
                "confidence",
            }
            for field in fields:
                if (
                    not isinstance(field, dict)
                    or not field_required.issubset(field)
                    or any(
                        field[key] in {None, ""}
                        for key in field_required - {"value"}
                    )
                    or field["value"] is None
                    or field["confidence"] not in {"low", "medium", "high"}
                ):
                    raise ValueError("RESEARCH_COMPONENT_INPUT_FIELD_INVALID")
            try:
                if parse_instant(str(row["published_at"])) > parse_instant(
                    available_at
                ):
                    raise ValueError
            except ValueError as error:
                raise ValueError("RESEARCH_COMPONENT_INPUT_TIME_INVALID") from error
            natural_key = (
                f"{row['security_id']}:{dataset}:{component_input_id}"
            )
            event_at = str(row["published_at"])
        elif dataset in {"income", "balancesheet", "cashflow"}:
            required = {
                "security_id",
                "statement_kind",
                "period_end",
                "report_type",
                "published_at",
                "available_at",
                "currency",
                "accounting_standard",
                "extracted_fields",
            }
            if not required.issubset(row) or row["security_id"] != security_id:
                raise ValueError("FINANCIAL_STATEMENT_IDENTITY_INVALID")
            if (
                row["statement_kind"] != dataset
                or not isinstance(row["extracted_fields"], list)
                or not row["extracted_fields"]
            ):
                raise ValueError("FINANCIAL_STATEMENT_FACTS_MISSING")
            natural_key = (
                f"{row['security_id']}:{dataset}:{row['period_end']}:"
                f"{row['report_type']}"
            )
            event_at = str(row["period_end"])
        elif dataset == "official_filing":
            required = {
                "security_id",
                "issuer_identity",
                "authority",
                "document_identity",
                "accession_or_document_id",
                "filing_type",
                "document_sha256",
                "document_base64",
                "content_type",
                "byte_size",
                "correction_status",
                "published_at",
                "available_at",
            }
            if not required.issubset(row):
                raise ValueError("SCHEMA_DRIFT")
            if row["security_id"] != security_id:
                raise ValueError("OFFICIAL_FILING_SECURITY_IDENTITY_MISMATCH")
            if row["content_type"] != "application/pdf":
                quality = QualityStatus.QUARANTINE
                issues.append(("quarantine", "OFFICIAL_FILING_MIME_INVALID"))
            if (
                not isinstance(row["byte_size"], int)
                or row["byte_size"] < 0
                or len(str(row["document_sha256"])) != 64
            ):
                quality = QualityStatus.QUARANTINE
                issues.append(("quarantine", "OFFICIAL_FILING_DOCUMENT_INVALID"))
            try:
                document = base64.b64decode(
                    str(row["document_base64"]), validate=True
                )
            except ValueError as error:
                raise ValueError("OFFICIAL_FILING_DOCUMENT_INVALID") from error
            if (
                len(document) != row["byte_size"]
                or hashlib.sha256(document).hexdigest()
                != row["document_sha256"]
                or not document.startswith(b"%PDF-")
            ):
                quality = QualityStatus.QUARANTINE
                issues.append(
                    ("quarantine", "OFFICIAL_FILING_DOCUMENT_INVALID")
                )
            if row["correction_status"] not in {
                "original",
                "amended",
                "corrected",
                "superseded",
            }:
                raise ValueError("OFFICIAL_FILING_CORRECTION_INVALID")
            try:
                published_instant = parse_instant(str(row["published_at"]))
                available_instant = parse_instant(str(row["available_at"]))
            except ValueError as error:
                raise ValueError("OFFICIAL_FILING_PIT_TIME_INVALID") from error
            if not (
                published_instant
                <= available_instant
                <= retrieved_at
            ):
                quality = QualityStatus.QUARANTINE
                issues.append(
                    ("quarantine", "OFFICIAL_FILING_PIT_ORDER_INVALID")
                )
            natural_key = (
                f"{row['authority']}:{row['issuer_identity']}:"
                f"{row['document_identity']}"
            )
            event_at = str(row["published_at"])
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
