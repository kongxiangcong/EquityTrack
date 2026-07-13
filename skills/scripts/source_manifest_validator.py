#!/usr/bin/env python3
"""Validate equity research source manifests.

The validator turns ``references/source-manifest.md`` into an executable gate.
It accepts JSON manifests by default. YAML manifests are supported when PyYAML is
available; otherwise the validator returns a structured JSON failure instead of
crashing.

Usage:
    python source_manifest_validator.py --manifest path/to/source_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - depends on local environment
    yaml = None


VALID_TIERS = {"official", "terminal", "secondary", "news", "estimate", "missing"}
VALID_OFFICIAL_FLAGS = {"official", "secondary"}
VALID_CROSS_CHECK_STATUSES = {"match", "mismatch", "not_checked"}
CONFLICT_STATUSES = {"mismatch", "conflict", "unresolved", "unresolved_conflict"}

ROOT_REQUIRED_FIELDS = ("source_manifest_version", "company", "sources")
COMPANY_REQUIRED_FIELDS = (
    "name",
    "ticker",
    "market",
    "reporting_currency",
    "trading_currency",
    "accounting_standard",
    "latest_financial_period",
)
SOURCE_REQUIRED_FIELDS = (
    "source_id",
    "tier",
    "market",
    "publisher",
    "title",
    "official_or_secondary",
    "url_or_api",
    "retrieved_at",
    "query_params",
    "filing_period",
    "report_date",
    "currency",
    "unit",
    "raw_file_path",
    "raw_file_sha256",
    "page_or_table",
    "extracted_fields",
    "cross_checks",
)
SOURCE_REQUIRED_FIELDS_V2 = (
    "source_id",
    "tier",
    "publisher",
    "title",
    "url_or_api",
    "retrieved_at",
    "extracted_fields",
)
EXTRACTED_FIELD_REQUIRED_FIELDS = (
    "field_name",
    "period",
    "value",
    "unit",
    "currency",
    "extraction_method",
    "confidence",
)

BASE_CRITICAL_FIELDS = (
    "revenue",
    "ebit",
    "net_income",
    "eps",
    "tax",
    "d_and_a",
    "capex",
    "cfo",
    "fcf",
    "working_capital",
    "cash",
    "debt",
    "lease_debt",
    "preferred_stock",
    "minority_interest",
    "pension_deficit",
    "associates_jv_value",
    "non_operating_assets",
    "diluted_shares",
    "sbc_options_dilution",
    "market_cap",
    "current_price",
    "fx_rate",
)

MARKET_DATA_FIELDS = {"market_cap", "current_price", "fx_rate"}
OFFICIAL_FINANCIAL_FIELDS = tuple(
    field_name for field_name in BASE_CRITICAL_FIELDS if field_name not in MARKET_DATA_FIELDS
)

FIELD_ALIASES = {
    "revenue": "revenue",
    "sales": "revenue",
    "operatingrevenue": "revenue",
    "totalrevenue": "revenue",
    "ebit": "ebit",
    "operatingincome": "ebit",
    "operatingprofit": "ebit",
    "netincome": "net_income",
    "netprofit": "net_income",
    "profitattributabletoshareholders": "net_income",
    "eps": "eps",
    "dilutedeps": "eps",
    "tax": "tax",
    "incometax": "tax",
    "taxexpense": "tax",
    "da": "d_and_a",
    "depreciationamortization": "d_and_a",
    "depreciationandamortization": "d_and_a",
    "depreciationamortisation": "d_and_a",
    "capex": "capex",
    "capitalexpenditure": "capex",
    "capitalexpenditures": "capex",
    "cfo": "cfo",
    "operatingcashflow": "cfo",
    "cashflowfromoperations": "cfo",
    "netcashprovidedbyoperatingactivities": "cfo",
    "fcf": "fcf",
    "freecashflow": "fcf",
    "workingcapital": "working_capital",
    "networkingcapital": "working_capital",
    "nwc": "working_capital",
    "cash": "cash",
    "cashandcashequivalents": "cash",
    "debt": "debt",
    "totaldebt": "debt",
    "grossdebt": "debt",
    "leasedebt": "lease_debt",
    "leaseliabilities": "lease_debt",
    "leaseobligations": "lease_debt",
    "preferredstock": "preferred_stock",
    "preferenceshares": "preferred_stock",
    "minorityinterest": "minority_interest",
    "noncontrollinginterest": "minority_interest",
    "pensiondeficit": "pension_deficit",
    "associatesjvvalue": "associates_jv_value",
    "associatesandjvvalue": "associates_jv_value",
    "associatesjointventuresvalue": "associates_jv_value",
    "nonoperatingassets": "non_operating_assets",
    "dilutedshares": "diluted_shares",
    "fullydilutedshares": "diluted_shares",
    "weightedaveragedilutedshares": "diluted_shares",
    "sbcoptionsdilution": "sbc_options_dilution",
    "optionsdilution": "sbc_options_dilution",
    "stockbasedcompensationdilution": "sbc_options_dilution",
    "marketcap": "market_cap",
    "marketcapitalization": "market_cap",
    "currentprice": "current_price",
    "shareprice": "current_price",
    "stockprice": "current_price",
    "fxrate": "fx_rate",
    "exchangerate": "fx_rate",
}

OFFICIAL_PUBLISHER_HINTS = {
    "a-share": (
        "cninfo",
        "sse",
        "szse",
        "bse",
        "stock exchange",
        "investor relations",
        "company ir",
        "annual report",
        "interim report",
        "quarterly report",
    ),
    "hk": (
        "hkex",
        "hkexnews",
        "stock exchange",
        "investor relations",
        "company ir",
        "annual report",
        "interim report",
    ),
    "us": (
        "sec",
        "edgar",
        "xbrl",
        "companyfacts",
        "companyconcept",
        "investor relations",
        "company ir",
        "annual report",
        "10-k",
        "10-q",
    ),
}

DATA_SUFFICIENCY_CODES = {
    "CRITICAL_FIELD_MISSING",
    "CRITICAL_FIELD_NOT_DECLARED",
    "LATEST_PERIOD_COVERAGE_MISSING",
    "OFFICIAL_SOURCE_MISSING",
    "UNRESOLVED_SOURCE_CONFLICT",
}


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    path: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FieldRecord:
    canonical_name: str
    raw_name: str
    source_id: str
    source_index: int
    field_index: int
    path: str
    period: str
    currency: str
    unit: str
    official: bool


class SourceManifestValidator:
    def __init__(
        self,
        manifest: Mapping[str, Any],
        manifest_path: Path,
        required_fields: Optional[Iterable[str]] = None,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.base_dir = manifest_path.parent
        self.required_fields = {
            canonical_field_name(field_name) or field_name for field_name in (required_fields or BASE_CRITICAL_FIELDS)
        }
        self.issues: List[Issue] = []
        self.field_records: List[FieldRecord] = []
        self.source_ids: Set[str] = set()
        self.official_source_ids: Set[str] = set()
        self.hash_checks = 0
        raw_version = self.manifest.get("source_manifest_version")
        self.manifest_version = int(raw_version) if str(raw_version).isdigit() else None

    def validate(self) -> Dict[str, Any]:
        if not isinstance(self.manifest, Mapping):
            self.add_issue(
                "error",
                "MANIFEST_NOT_OBJECT",
                "Manifest root must be a JSON/YAML object.",
                "$",
            )
            return self.result()

        self.check_root_schema()
        self.check_company_schema()
        self.check_sources()
        self.check_cross_check_references()
        self.check_critical_field_coverage()
        self.check_official_financial_coverage()
        self.check_currency_unit_period_consistency()
        return self.result()

    def check_root_schema(self) -> None:
        for field_name in ROOT_REQUIRED_FIELDS:
            if is_blank(self.manifest.get(field_name)):
                self.add_issue(
                    "error",
                    "REQUIRED_FIELD_MISSING",
                    f"Missing required root field: {field_name}.",
                    f"$.{field_name}",
                )

        version = self.manifest.get("source_manifest_version")
        if version not in (1, "1", 2, "2"):
            self.add_issue(
                "error",
                "UNSUPPORTED_MANIFEST_VERSION",
                "source_manifest_version must be 1 or 2.",
                "$.source_manifest_version",
                {"actual": version},
            )

        if "missing_critical_data" in self.manifest and not isinstance(
            self.manifest.get("missing_critical_data"), list
        ):
            self.add_issue(
                "error",
                "INVALID_FIELD_TYPE",
                "missing_critical_data must be a list when provided.",
                "$.missing_critical_data",
            )

    def check_company_schema(self) -> None:
        company = self.manifest.get("company")
        if not isinstance(company, Mapping):
            self.add_issue("error", "INVALID_FIELD_TYPE", "company must be an object.", "$.company")
            return

        for field_name in COMPANY_REQUIRED_FIELDS:
            if is_blank(company.get(field_name)):
                self.add_issue(
                    "error",
                    "REQUIRED_FIELD_MISSING",
                    f"Missing required company field: {field_name}.",
                    f"$.company.{field_name}",
                )

    def check_sources(self) -> None:
        sources = self.manifest.get("sources")
        if not isinstance(sources, list):
            self.add_issue("error", "INVALID_FIELD_TYPE", "sources must be a list.", "$.sources")
            return

        seen: Dict[str, int] = {}
        for index, source in enumerate(sources):
            source_path = f"$.sources[{index}]"
            if not isinstance(source, Mapping):
                self.add_issue(
                    "error",
                    "INVALID_FIELD_TYPE",
                    "Each source must be an object.",
                    source_path,
                )
                continue

            source_id = str(source.get("source_id", "")).strip()
            if source_id:
                if source_id in seen:
                    self.add_issue(
                        "error",
                        "DUPLICATE_SOURCE_ID",
                        f"Duplicate source_id: {source_id}.",
                        f"{source_path}.source_id",
                        {"first_seen_at": f"$.sources[{seen[source_id]}].source_id"},
                    )
                else:
                    seen[source_id] = index
                    self.source_ids.add(source_id)

            required_source_fields = SOURCE_REQUIRED_FIELDS_V2 if self.manifest_version == 2 else SOURCE_REQUIRED_FIELDS
            for field_name in required_source_fields:
                allow_empty_collection = field_name in {"query_params", "cross_checks"}
                if required_value_missing(source, field_name, allow_empty_collection=allow_empty_collection):
                    self.add_issue(
                        "error",
                        "REQUIRED_FIELD_MISSING",
                        f"Missing required source field: {field_name}.",
                        f"{source_path}.{field_name}",
                    )

            if self.manifest_version == 2 and not any(
                not is_blank(source.get(field_name))
                for field_name in ("available_at", "published_at", "report_date")
            ):
                self.add_issue(
                    "error",
                    "SOURCE_AVAILABLE_AT_MISSING",
                    "Source must declare available_at, published_at, or report_date.",
                    f"{source_path}.available_at",
                )

            tier = normalized_text(source.get("tier"))
            if tier and tier not in VALID_TIERS:
                self.add_issue(
                    "error",
                    "INVALID_ENUM_VALUE",
                    f"Invalid source tier: {source.get('tier')}.",
                    f"{source_path}.tier",
                    {"allowed": sorted(VALID_TIERS)},
                )

            official_flag = normalized_text(source.get("official_or_secondary"))
            if official_flag and official_flag not in VALID_OFFICIAL_FLAGS:
                self.add_issue(
                    "error",
                    "INVALID_ENUM_VALUE",
                    f"Invalid official_or_secondary value: {source.get('official_or_secondary')}.",
                    f"{source_path}.official_or_secondary",
                    {"allowed": sorted(VALID_OFFICIAL_FLAGS)},
                )

            official = is_official_source(source, self.company_market())
            if official and source_id:
                self.official_source_ids.add(source_id)
                if not publisher_matches_market(source, self.company_market()):
                    self.add_issue(
                        "warning",
                        "OFFICIAL_PUBLISHER_UNRECOGNIZED",
                        "Source is marked official, but publisher/title/url do not match known official-source hints.",
                        source_path,
                        {"source_id": source_id, "publisher": source.get("publisher")},
                    )

            self.check_raw_file(source, source_path)
            self.collect_extracted_fields(source, index, source_id, official)
            self.check_cross_checks_shape(source, source_path)

    def check_raw_file(self, source: Mapping[str, Any], source_path: str) -> None:
        if normalized_text(source.get("tier")) == "missing":
            return

        raw_file_path = source.get("raw_file_path")
        raw_file_sha256 = source.get("raw_file_sha256")
        if is_blank(raw_file_path) or is_blank(raw_file_sha256):
            return

        resolved_path = resolve_raw_path(self.base_dir, str(raw_file_path))
        if not resolved_path.exists():
            self.add_issue(
                "error",
                "RAW_FILE_NOT_FOUND",
                f"raw_file_path does not exist: {raw_file_path}.",
                f"{source_path}.raw_file_path",
                {"resolved_path": str(resolved_path)},
            )
            return

        actual_hash = sha256_file(resolved_path)
        self.hash_checks += 1
        expected_hash = normalize_sha256(str(raw_file_sha256))
        if actual_hash != expected_hash:
            self.add_issue(
                "error",
                "RAW_FILE_SHA256_MISMATCH",
                f"raw_file_sha256 does not match file content for {raw_file_path}.",
                f"{source_path}.raw_file_sha256",
                {"expected": expected_hash, "actual": actual_hash, "resolved_path": str(resolved_path)},
            )

    def collect_extracted_fields(
        self,
        source: Mapping[str, Any],
        source_index: int,
        source_id: str,
        official: bool,
    ) -> None:
        fields = source.get("extracted_fields")
        source_path = f"$.sources[{source_index}]"
        if not isinstance(fields, list):
            self.add_issue(
                "error",
                "INVALID_FIELD_TYPE",
                "extracted_fields must be a list.",
                f"{source_path}.extracted_fields",
            )
            return

        for field_index, extracted in enumerate(fields):
            field_path = f"{source_path}.extracted_fields[{field_index}]"
            if not isinstance(extracted, Mapping):
                self.add_issue(
                    "error",
                    "INVALID_FIELD_TYPE",
                    "Each extracted_fields item must be an object.",
                    field_path,
                )
                continue

            for field_name in EXTRACTED_FIELD_REQUIRED_FIELDS:
                if field_name == "value":
                    if field_name not in extracted:
                        self.add_issue(
                            "error",
                            "REQUIRED_FIELD_MISSING",
                            "Missing required extracted field: value.",
                            f"{field_path}.value",
                        )
                    continue
                if is_blank(extracted.get(field_name)):
                    self.add_issue(
                        "error",
                        "REQUIRED_FIELD_MISSING",
                        f"Missing required extracted field: {field_name}.",
                        f"{field_path}.{field_name}",
                    )

            raw_name = str(extracted.get("field_name", "")).strip()
            canonical = canonical_field_name(raw_name)
            if not canonical:
                self.add_issue(
                    "warning",
                    "UNKNOWN_FIELD_NAME",
                    f"Unknown extracted field name: {raw_name}.",
                    f"{field_path}.field_name",
                )
                continue

            self.field_records.append(
                FieldRecord(
                    canonical_name=canonical,
                    raw_name=raw_name,
                    source_id=source_id,
                    source_index=source_index,
                    field_index=field_index,
                    path=field_path,
                    period=str(extracted.get("period", "")).strip(),
                    currency=str(extracted.get("currency", "")).strip(),
                    unit=str(extracted.get("unit", "")).strip(),
                    official=official,
                )
            )

    def check_cross_checks_shape(self, source: Mapping[str, Any], source_path: str) -> None:
        cross_checks = source.get("cross_checks")
        if not isinstance(cross_checks, list):
            self.add_issue(
                "error",
                "INVALID_FIELD_TYPE",
                "cross_checks must be a list.",
                f"{source_path}.cross_checks",
            )
            return

        for index, cross_check in enumerate(cross_checks):
            path = f"{source_path}.cross_checks[{index}]"
            if not isinstance(cross_check, Mapping):
                self.add_issue("error", "INVALID_FIELD_TYPE", "Each cross_check must be an object.", path)
                continue

            ref_source_id = str(cross_check.get("source_id", "")).strip()
            status = normalized_text(cross_check.get("status"))
            if is_blank(ref_source_id):
                self.add_issue(
                    "error",
                    "REQUIRED_FIELD_MISSING",
                    "Missing cross_check source_id.",
                    f"{path}.source_id",
                )
            if not status:
                self.add_issue(
                    "error",
                    "REQUIRED_FIELD_MISSING",
                    "Missing cross_check status.",
                    f"{path}.status",
                )
            elif status in CONFLICT_STATUSES:
                self.add_issue(
                    "error",
                    "UNRESOLVED_SOURCE_CONFLICT",
                    f"Unresolved source conflict against {ref_source_id}.",
                    f"{path}.status",
                    {"status": cross_check.get("status"), "notes": cross_check.get("notes")},
                )
            elif status not in VALID_CROSS_CHECK_STATUSES:
                self.add_issue(
                    "error",
                    "INVALID_ENUM_VALUE",
                    f"Invalid cross_check status: {cross_check.get('status')}.",
                    f"{path}.status",
                    {"allowed": sorted(VALID_CROSS_CHECK_STATUSES)},
                )
            elif status == "not_checked":
                self.add_issue(
                    "warning",
                    "CROSS_CHECK_NOT_PERFORMED",
                    f"Cross-check not performed for {ref_source_id}.",
                    f"{path}.status",
                )

    def check_cross_check_references(self) -> None:
        sources = self.manifest.get("sources")
        if not isinstance(sources, list):
            return

        for source_index, source in enumerate(sources):
            if not isinstance(source, Mapping):
                continue
            cross_checks = source.get("cross_checks")
            if not isinstance(cross_checks, list):
                continue
            for cross_index, cross_check in enumerate(cross_checks):
                if not isinstance(cross_check, Mapping):
                    continue
                ref_source_id = str(cross_check.get("source_id", "")).strip()
                if ref_source_id and ref_source_id not in self.source_ids:
                    self.add_issue(
                        "error",
                        "UNKNOWN_CROSS_CHECK_SOURCE_ID",
                        f"cross_check references unknown source_id: {ref_source_id}.",
                        f"$.sources[{source_index}].cross_checks[{cross_index}].source_id",
                    )

    def check_critical_field_coverage(self) -> None:
        covered_fields = {record.canonical_name for record in self.field_records if record.source_id}
        missing_fields = self.missing_critical_fields()

        for field_name in sorted(self.required_fields):
            if field_name in covered_fields:
                continue
            if field_name in missing_fields:
                self.add_issue(
                    "warning" if self.manifest_version == 2 else "error",
                    "CAPABILITY_INPUT_MISSING" if self.manifest_version == 2 else "CRITICAL_FIELD_MISSING",
                    f"Critical field is explicitly missing and limits dependent capabilities: {field_name}.",
                    "$.missing_critical_data",
                    {"field_name": field_name},
                )
                continue
            self.add_issue(
                "warning" if self.manifest_version == 2 else "error",
                "CAPABILITY_INPUT_UNDECLARED" if self.manifest_version == 2 else "CRITICAL_FIELD_NOT_DECLARED",
                f"Critical field lacks source coverage and limits dependent capabilities: {field_name}.",
                "$.sources[].extracted_fields",
                {"field_name": field_name},
            )

    def check_official_financial_coverage(self) -> None:
        official_covered = {record.canonical_name for record in self.field_records if record.official}
        missing_fields = self.missing_critical_fields()

        for field_name in OFFICIAL_FINANCIAL_FIELDS:
            if field_name not in self.required_fields or field_name in missing_fields:
                continue
            if field_name not in official_covered:
                self.add_issue(
                    "error",
                    "OFFICIAL_SOURCE_MISSING",
                    f"Critical financial field lacks official-source coverage: {field_name}.",
                    "$.sources",
                    {"field_name": field_name},
                )

    def check_currency_unit_period_consistency(self) -> None:
        company = self.manifest.get("company") if isinstance(self.manifest.get("company"), Mapping) else {}
        reporting_currency = str(company.get("reporting_currency", "")).strip()
        trading_currency = str(company.get("trading_currency", "")).strip()
        latest_period_key = period_key(str(company.get("latest_financial_period", "")).strip())

        by_field_period: Dict[str, List[FieldRecord]] = {}
        for record in self.field_records:
            key = f"{record.canonical_name}|{period_key(record.period)}"
            by_field_period.setdefault(key, []).append(record)

            if record.canonical_name in OFFICIAL_FINANCIAL_FIELDS:
                if reporting_currency and record.currency and not same_code(record.currency, reporting_currency):
                    self.add_issue(
                        "error",
                        "REPORTING_CURRENCY_CONFLICT",
                        f"{record.raw_name} currency does not match company reporting_currency.",
                        f"{record.path}.currency",
                        {
                            "field_currency": record.currency,
                            "reporting_currency": reporting_currency,
                            "source_id": record.source_id,
                        },
                    )
                if latest_period_key and record.canonical_name in self.required_fields:
                    source = self.source_at(record.source_index)
                    source_period_key = period_key(str(source.get("filing_period", ""))) if source else ""
                    record_period_key = period_key(record.period)
                    if source_period_key and record_period_key and source_period_key != record_period_key:
                        self.add_issue(
                            "error",
                            "SOURCE_FIELD_PERIOD_CONFLICT",
                            "Extracted field period does not match source filing_period.",
                            f"{record.path}.period",
                            {
                                "field_period": record.period,
                                "source_filing_period": source.get("filing_period") if source else None,
                                "source_id": record.source_id,
                            },
                        )

            if record.canonical_name in MARKET_DATA_FIELDS and trading_currency and record.currency:
                allowed = {trading_currency}
                if reporting_currency:
                    allowed.add(reporting_currency)
                if not any(same_code(record.currency, allowed_currency) for allowed_currency in allowed):
                    self.add_issue(
                        "error",
                        "TRADING_CURRENCY_CONFLICT",
                        f"{record.raw_name} currency does not match trading_currency/reporting_currency.",
                        f"{record.path}.currency",
                        {
                            "field_currency": record.currency,
                            "allowed_currencies": sorted(allowed),
                            "source_id": record.source_id,
                        },
                    )

        for key, records in by_field_period.items():
            currencies = {normalized_code(record.currency) for record in records if record.currency}
            units = {normalized_code(record.unit) for record in records if record.unit}
            if len(currencies) > 1:
                self.add_issue(
                    "error",
                    "CURRENCY_CONFLICT",
                    "Same field/period appears with conflicting currencies.",
                    records[0].path,
                    {
                        "field_period": key,
                        "currencies": sorted(currencies),
                        "source_ids": sorted({record.source_id for record in records}),
                    },
                )
            if len(units) > 1:
                self.add_issue(
                    "error",
                    "UNIT_CONFLICT",
                    "Same field/period appears with conflicting units.",
                    records[0].path,
                    {
                        "field_period": key,
                        "units": sorted(units),
                        "source_ids": sorted({record.source_id for record in records}),
                    },
                )

        if latest_period_key:
            latest_covered = {
                record.canonical_name
                for record in self.field_records
                if record.canonical_name in OFFICIAL_FINANCIAL_FIELDS and period_key(record.period) == latest_period_key
            }
            for field_name in OFFICIAL_FINANCIAL_FIELDS:
                if field_name in self.required_fields and field_name not in self.missing_critical_fields():
                    if field_name not in latest_covered:
                        self.add_issue(
                            "error",
                            "LATEST_PERIOD_COVERAGE_MISSING",
                            f"Latest financial period lacks field coverage: {field_name}.",
                            "$.sources[].extracted_fields",
                            {"field_name": field_name, "latest_financial_period": company.get("latest_financial_period")},
                        )

    def source_at(self, index: int) -> Optional[Mapping[str, Any]]:
        sources = self.manifest.get("sources")
        if isinstance(sources, list) and 0 <= index < len(sources) and isinstance(sources[index], Mapping):
            return sources[index]
        return None

    def missing_critical_fields(self) -> Set[str]:
        missing = self.manifest.get("missing_critical_data")
        if not isinstance(missing, list):
            return set()

        fields: Set[str] = set()
        for item in missing:
            if not isinstance(item, Mapping):
                continue
            canonical = canonical_field_name(str(item.get("field_name", "")))
            if canonical:
                fields.add(canonical)
        return fields

    def company_market(self) -> str:
        company = self.manifest.get("company")
        if not isinstance(company, Mapping):
            return ""
        return normalize_market(str(company.get("market", "")))

    def add_issue(
        self,
        severity: str,
        code: str,
        message: str,
        path: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.issues.append(Issue(severity, code, message, path, details or {}))

    def result(self) -> Dict[str, Any]:
        errors = [issue for issue in self.issues if issue.severity == "error"]
        warnings = [issue for issue in self.issues if issue.severity == "warning"]
        error_codes = {issue.code for issue in errors}
        covered_fields = {record.canonical_name for record in self.field_records if record.source_id}
        missing_fields = self.missing_critical_fields()
        official_covered = {record.canonical_name for record in self.field_records if record.official}
        uncovered_fields = self.required_fields - covered_fields

        if errors:
            if error_codes <= DATA_SUFFICIENCY_CODES:
                manifest_status = "insufficient"
            else:
                manifest_status = "invalid"
        elif self.manifest_version == 2 and uncovered_fields:
            manifest_status = "valid_with_limits"
        else:
            manifest_status = "sufficient"

        return {
            "validator": "source_manifest_validator",
            "validator_version": 2,
            "manifest_version": self.manifest_version,
            "input_path": str(self.manifest_path),
            "passed": not errors,
            "source_manifest_status": manifest_status,
            "data_insufficient_memo_required": bool(error_codes & DATA_SUFFICIENCY_CODES) if self.manifest_version != 2 else bool(errors),
            "limitations": {
                "missing_critical_fields": sorted(uncovered_fields),
                "declared_missing_fields": sorted(self.required_fields & missing_fields),
            },
            "summary": {
                "sources_total": len(self.manifest.get("sources", []))
                if isinstance(self.manifest.get("sources"), list)
                else 0,
                "official_sources_total": len(self.official_source_ids),
                "critical_fields_required": len(self.required_fields),
                "critical_fields_source_covered": len(self.required_fields & covered_fields),
                "critical_fields_explicitly_missing": len(self.required_fields & missing_fields),
                "official_financial_fields_covered": len(set(OFFICIAL_FINANCIAL_FIELDS) & official_covered),
                "hash_checks": self.hash_checks,
                "errors": len(errors),
                "warnings": len(warnings),
            },
            "required_fields": sorted(self.required_fields),
            "issues": [asdict(issue) for issue in self.issues],
        }


def load_manifest(path: Path) -> tuple[Optional[Mapping[str, Any]], List[Issue]]:
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, [Issue("error", "MANIFEST_READ_FAILED", str(exc), str(path))]

    if suffix == ".md":
        text, suffix = extract_fenced_manifest(text)

    try:
        if suffix == ".json":
            loaded = json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            if yaml is None:
                return None, [
                    Issue(
                        "error",
                        "YAML_SUPPORT_UNAVAILABLE",
                        "YAML manifest provided but PyYAML is not installed. Install PyYAML or use JSON.",
                        str(path),
                    )
                ]
            loaded = yaml.safe_load(text)
        else:
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                if yaml is None:
                    return None, [
                        Issue(
                            "error",
                            "UNSUPPORTED_MANIFEST_FORMAT",
                            "Manifest is not JSON, and YAML support is unavailable.",
                            str(path),
                        )
                    ]
                loaded = yaml.safe_load(text)
    except Exception as exc:  # JSONDecodeError/YAMLError both become structured output
        return None, [Issue("error", "MANIFEST_PARSE_FAILED", str(exc), str(path))]

    if not isinstance(loaded, Mapping):
        return None, [Issue("error", "MANIFEST_NOT_OBJECT", "Manifest root must be an object.", "$")]
    return loaded, []


def extract_fenced_manifest(markdown_text: str) -> tuple[str, str]:
    match = re.search(r"```(json|yaml|yml)\s*(.*?)```", markdown_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return markdown_text, ".json"
    language = match.group(1).lower()
    suffix = ".json" if language == "json" else ".yaml"
    return match.group(2).strip(), suffix


def canonical_field_name(field_name: str) -> Optional[str]:
    raw = str(field_name or "").strip()
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", raw).lower()
    if not cleaned:
        return None
    fallback = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    return FIELD_ALIASES.get(cleaned, fallback)


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def required_value_missing(
    container: Mapping[str, Any],
    field_name: str,
    allow_empty_collection: bool = False,
) -> bool:
    if field_name not in container or container[field_name] is None:
        return True
    value = container[field_name]
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return False if allow_empty_collection else len(value) == 0
    return False


def normalized_text(value: Any) -> str:
    return str(value or "").strip().lower()


def normalized_code(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "", value).upper()


def same_code(left: str, right: str) -> bool:
    return normalized_code(left) == normalized_code(right)


def normalize_sha256(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("sha256:"):
        value = value.split(":", 1)[1]
    return value


def resolve_raw_path(base_dir: Path, raw_file_path: str) -> Path:
    candidate = Path(raw_file_path)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_market(market: str) -> str:
    normalized = market.strip().lower()
    if normalized in {"a-share", "a shares", "ashare", "cn", "china", "sh", "sz", "bj"}:
        return "a-share"
    if normalized in {"hk", "hong kong", "hongkong", "h-share", "h shares"}:
        return "hk"
    if normalized in {"us", "usa", "u.s.", "nyse", "nasdaq", "amex"}:
        return "us"
    return normalized


def is_official_source(source: Mapping[str, Any], company_market: str) -> bool:
    tier = normalized_text(source.get("tier"))
    flag = normalized_text(source.get("official_or_secondary"))
    if tier != "official" and flag != "official":
        return False
    if not company_market:
        return True
    return True


def publisher_matches_market(source: Mapping[str, Any], company_market: str) -> bool:
    hints = OFFICIAL_PUBLISHER_HINTS.get(company_market, ())
    if not hints:
        return True
    haystack = " ".join(
        str(source.get(field_name, ""))
        for field_name in ("publisher", "title", "url_or_api")
    ).lower()
    return any(hint in haystack for hint in hints)


def period_key(value: str) -> str:
    text = value.upper().replace(" ", "")
    year_match = re.search(r"(20\d{2}|19\d{2})", text)
    if not year_match:
        return re.sub(r"[^A-Z0-9]+", "", text)
    year = year_match.group(1)
    if "Q1" in text or "0331" in text:
        return f"{year}Q1"
    if "H1" in text or "1H" in text or "HY" in text or "0630" in text:
        return f"{year}H1"
    if "Q3" in text or "0930" in text:
        return f"{year}Q3"
    if "Q4" in text or "FY" in text or "ANNUAL" in text or "YEAR" in text or "1231" in text:
        return f"{year}FY"
    return f"{year}FY"


def build_failure_result(path: Path, issues: Sequence[Issue]) -> Dict[str, Any]:
    return {
        "validator": "source_manifest_validator",
        "validator_version": 2,
        "manifest_version": None,
        "input_path": str(path),
        "passed": False,
        "source_manifest_status": "invalid",
        "data_insufficient_memo_required": False,
        "limitations": {"missing_critical_fields": [], "declared_missing_fields": []},
        "summary": {
            "sources_total": 0,
            "official_sources_total": 0,
            "critical_fields_required": len(BASE_CRITICAL_FIELDS),
            "critical_fields_source_covered": 0,
            "critical_fields_explicitly_missing": 0,
            "official_financial_fields_covered": 0,
            "hash_checks": 0,
            "errors": len([issue for issue in issues if issue.severity == "error"]),
            "warnings": len([issue for issue in issues if issue.severity == "warning"]),
        },
        "required_fields": sorted(BASE_CRITICAL_FIELDS),
        "issues": [asdict(issue) for issue in issues],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an equity research source manifest.")
    parser.add_argument("--manifest", required=True, help="Path to source manifest JSON/YAML/Markdown-fenced file.")
    parser.add_argument(
        "--required-field",
        action="append",
        default=[],
        help="Additional critical field to require. May be provided multiple times.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print validation result JSON.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    required_fields = list(BASE_CRITICAL_FIELDS) + list(args.required_field or [])

    manifest, load_issues = load_manifest(manifest_path)
    if load_issues:
        result = build_failure_result(manifest_path, load_issues)
    else:
        assert manifest is not None
        result = SourceManifestValidator(manifest, manifest_path, required_fields).validate()

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
