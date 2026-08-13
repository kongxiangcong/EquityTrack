from __future__ import annotations

import json
import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from trading_platform.domain.data import QualityStatus
from trading_platform.domain.research_model_input import (
    exact_model_path,
    typed_model_field_failure,
)


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


def normalize(dataset: str, payload: bytes, security_id: str | None = None, market: str | None = None, source_ref: str = "provider", retrieved_at: datetime | None = None) -> tuple[NormalizedItem, ...]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("SCHEMA_DRIFT") from error
    rows = document.get("rows") if isinstance(document, dict) else None
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
            model_paths: set[str] = set()
            generic_non_empty = field_required - {"value"}
            if dataset == "research_model_input":
                generic_non_empty -= {
                    "field_name", "subject_id", "semantic_role",
                    "period", "unit", "currency",
                }
            for field in fields:
                if (
                    not isinstance(field, dict)
                    or not field_required.issubset(field)
                    or any(
                        field[key] in {None, ""}
                        for key in generic_non_empty
                    )
                    or (
                        dataset != "research_model_input" and field["value"] is None
                    )
                    or field["confidence"] not in {"low", "medium", "high"}
                ):
                    raise ValueError("RESEARCH_COMPONENT_INPUT_FIELD_INVALID")
                if dataset == "research_model_input":
                    model_path = exact_model_path(field)
                    failure_code = typed_model_field_failure(
                        field,
                        expected_subject_id=row["security_id"],
                    )
                    if failure_code is not None:
                        raise ValueError(failure_code)
                    if model_path in model_paths:
                        raise ValueError("RESEARCH_MODEL_INPUT_DUPLICATE")
                    model_paths.add(model_path)
                elif field["subject_id"] != row["security_id"]:
                    raise ValueError(
                        "RESEARCH_COMPONENT_INPUT_SUBJECT_INVALID"
                    )
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
