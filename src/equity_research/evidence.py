from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any, Iterable, Mapping

from .models import EvidenceItem, IntegrityIssue, SourceRecord
from .output_policy import normalize_action_language


VALID_SOURCE_TIERS = {
    "official",
    "terminal",
    "secondary",
    "news",
    "estimate",
    "missing",
}

ESTIMATE_METADATA_KEYS = (
    "basis_sources",
    "policy",
    "range_policy",
    "basis_period",
    "lower_bound",
    "upper_bound",
    "calibration_window",
    "rationale",
    "invalidation_condition",
    "formal_gate_coverage",
)


def _estimate_metadata(
    value: Mapping[str, Any],
    *,
    policy: str = "",
) -> Mapping[str, Any]:
    metadata = {
        key: value[key]
        for key in ESTIMATE_METADATA_KEYS
        if key in value
    }
    if policy and "policy" not in metadata:
        metadata["policy"] = policy
    basis_sources = metadata.get("basis_sources")
    if isinstance(basis_sources, (list, tuple)):
        metadata["basis_sources"] = [
            str(source_id) for source_id in basis_sources if source_id
        ]
    calibration_window = metadata.get("calibration_window")
    if isinstance(calibration_window, Mapping):
        metadata["calibration_window"] = dict(calibration_window)
    return metadata


REPORTING_CURRENCY_FIELDS = {
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
}
MARKET_CURRENCY_FIELDS = {"current_price", "market_cap"}

FIELD_ALIASES = {
    "sales": "revenue",
    "operatingrevenue": "revenue",
    "totalrevenue": "revenue",
    "operatingincome": "ebit",
    "operatingprofit": "ebit",
    "netincome": "net_income",
    "netprofit": "net_income",
    "dilutedeps": "eps",
    "taxexpense": "tax",
    "da": "d_and_a",
    "depreciationamortization": "d_and_a",
    "depreciationandamortization": "d_and_a",
    "depreciationamortisation": "d_and_a",
    "capitalexpenditure": "capex",
    "capitalexpenditures": "capex",
    "operatingcashflow": "cfo",
    "cashflowfromoperations": "cfo",
    "freecashflow": "fcf",
    "networkingcapital": "working_capital",
    "cashandcashequivalents": "cash",
    "totaldebt": "debt",
    "leasedebt": "lease_debt",
    "leaseliabilities": "lease_debt",
    "preferredstock": "preferred_stock",
    "minorityinterest": "minority_interest",
    "noncontrollinginterest": "minority_interest",
    "pensiondeficit": "pension_deficit",
    "associatesjvvalue": "associates_jv_value",
    "nonoperatingassets": "non_operating_assets",
    "dilutedshares": "diluted_shares",
    "fullydilutedshares": "diluted_shares",
    "sbcoptionsdilution": "sbc_options_dilution",
    "marketcap": "market_cap",
    "marketcapitalization": "market_cap",
    "currentprice": "current_price",
    "shareprice": "current_price",
    "fxrate": "fx_rate",
}


def canonical_field_name(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "", raw).lower()
    if not normalized:
        return ""
    return FIELD_ALIASES.get(normalized, re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower())


def period_rank(period: str) -> float:
    text = str(period or "").upper().replace(" ", "")
    date_match = re.match(r"(20\d{2}|19\d{2})-(\d{2})-(\d{2})", text)
    if date_match:
        year, month, day = (int(part) for part in date_match.groups())
        return year + ((month - 1) * 31 + day) / 372
    year_match = re.search(r"(20\d{2}|19\d{2})", text)
    if not year_match:
        return -1.0
    year = int(year_match.group(1))
    if "Q1" in text or "0331" in text:
        return year + 0.25
    if "H1" in text or "1H" in text or "0630" in text:
        return year + 0.50
    if "Q3" in text or "0930" in text:
        return year + 0.75
    if "FY" in text or "ANNUAL" in text or "1231" in text:
        return year + 0.99
    return float(year)


def is_full_year(period: str) -> bool:
    text = str(period or "").upper()
    return "FY" in text or "ANNUAL" in text or "1231" in text


def numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value.replace(",", "").replace("%", "").strip())
            return number if isfinite(number) else None
        except ValueError:
            return None
    return None


def has_numeric_payload(value: Any) -> bool:
    if numeric_value(value) is not None:
        return True
    return isinstance(value, Mapping) and any(
        numeric_value(component) is not None for component in value.values()
    )


def _parse_iso_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None


def _neutralize_narrative(
    value: Any,
    *,
    path: str,
    issues: list[IntegrityIssue],
) -> str:
    normalized, changed = normalize_action_language(str(value or ""))
    if changed:
        issues.append(
            IntegrityIssue(
                "warning",
                "OUTPUT_LANGUAGE_NORMALIZED",
                "Action or rating language was converted to neutral research language.",
                path,
            )
        )
    return normalized


@dataclass(frozen=True)
class EvidenceBuild:
    company: Mapping[str, Any]
    sources: tuple[SourceRecord, ...]
    items: tuple[EvidenceItem, ...]
    declared_missing: tuple[Mapping[str, Any], ...]
    issues: tuple[IntegrityIssue, ...]


class EvidenceBook:
    """Read-only projection over canonical evidence items."""

    def __init__(
        self,
        items: Iterable[EvidenceItem],
        sources: Iterable[SourceRecord] = (),
        subject_id: str = "",
    ) -> None:
        self.items = tuple(items)
        self.sources = tuple(sources)
        self.subject_id = subject_id
        self.source_ids = frozenset(source.source_id for source in self.sources)
        self._source_by_id = {source.source_id: source for source in self.sources}
        self._by_id = {item.evidence_id: item for item in self.items}
        by_field: dict[str, list[EvidenceItem]] = {}
        for item in self.items:
            by_field.setdefault(item.field_name, []).append(item)
        self._by_field = {key: tuple(value) for key, value in by_field.items()}

    @property
    def fields(self) -> set[str]:
        return set(self._by_field)

    @property
    def official_fields(self) -> set[str]:
        return {
            item.field_name
            for item in self.items
            if item.official
            and not item.estimated
            and has_numeric_payload(item.value)
            and (not self.subject_id or item.subject_id == self.subject_id)
        }

    @property
    def sourced_fields(self) -> set[str]:
        return {
            item.field_name
            for item in self.items
            if not item.estimated
            and has_numeric_payload(item.value)
            and (not self.subject_id or item.subject_id == self.subject_id)
        }

    @property
    def estimated_fields(self) -> set[str]:
        return {
            item.field_name
            for item in self.items
            if item.estimated
            and has_numeric_payload(item.value)
            and (not self.subject_id or item.subject_id == self.subject_id)
        }

    def for_field(self, field_name: str) -> tuple[EvidenceItem, ...]:
        return self._by_field.get(canonical_field_name(field_name), ())

    def source_is_usable(
        self,
        source_id: str,
        *,
        allowed_tiers: set[str],
    ) -> bool:
        source = self._source_by_id.get(source_id)
        return bool(
            source
            and source.tier in allowed_tiers
            and any(
                item.source_id == source_id
                and not item.estimated
                and has_numeric_payload(item.value)
                for item in self.items
            )
        )

    def resolve_reference(
        self,
        reference: Any,
        *,
        allowed_tiers: set[str],
        expected_subject_id: str = "",
        expected_semantic_role: str = "",
        expected_field_names: set[str] | None = None,
    ) -> EvidenceItem | None:
        if not isinstance(reference, Mapping):
            return None
        source_id = str(reference.get("source_id", "")).strip()
        field_name = canonical_field_name(reference.get("field_name"))
        period = str(reference.get("period", "")).strip()
        if not source_id or not field_name or not period:
            return None
        if not self.source_is_usable(source_id, allowed_tiers=allowed_tiers):
            return None
        candidates = [
            item
            for item in self.for_field(field_name)
            if item.source_id == source_id
            and item.period == period
            and not item.estimated
            and has_numeric_payload(item.value)
            and (not expected_subject_id or item.subject_id == expected_subject_id)
            and (
                not expected_semantic_role
                or item.semantic_role == expected_semantic_role
            )
            and (
                expected_field_names is None
                or item.field_name in expected_field_names
            )
        ]
        return candidates[0] if len(candidates) == 1 else None

    def best(
        self,
        field_name: str,
        *,
        allow_estimate: bool = False,
        full_year: bool = False,
        official_only: bool = False,
    ) -> EvidenceItem | None:
        candidates = list(self.for_field(field_name))
        if self.subject_id:
            candidates = [
                item for item in candidates if item.subject_id == self.subject_id
            ]
        if full_year:
            candidates = [item for item in candidates if is_full_year(item.period)]
        sourced = [
            item
            for item in candidates
            if not item.estimated and (item.official or not official_only)
        ]
        pool = sourced or ([item for item in candidates if item.estimated] if allow_estimate else [])
        if not pool:
            return None
        confidence_rank = {"high": 3, "medium": 2, "low": 1}
        return max(
            pool,
            key=lambda item: (
                period_rank(item.period),
                1 if item.official else 0,
                confidence_rank.get(item.confidence.lower(), 0),
            ),
        )

    def best_estimate(self, field_name: str) -> EvidenceItem | None:
        candidates = [
            item
            for item in self.for_field(field_name)
            if item.estimated
            and (not self.subject_id or item.subject_id == self.subject_id)
        ]
        if not candidates:
            return None
        confidence_rank = {"high": 3, "medium": 2, "low": 1}
        return max(
            candidates,
            key=lambda item: (
                period_rank(item.period),
                confidence_rank.get(item.confidence.lower(), 0),
            ),
        )

def build_evidence(
    manifest: Mapping[str, Any],
    estimates: Mapping[str, Any] | None = None,
    *,
    as_of_date: str,
) -> EvidenceBuild:
    issues: list[IntegrityIssue] = []
    items: list[EvidenceItem] = []
    source_records: list[SourceRecord] = []
    locked_date = _parse_iso_date(as_of_date)
    if locked_date is None:
        issues.append(
            IntegrityIssue(
                "error",
                "AS_OF_DATE_INVALID",
                "as_of_date must be a valid ISO date.",
                "$.as_of_date",
            )
        )

    if not isinstance(manifest, Mapping):
        return EvidenceBuild(
            company={},
            sources=(),
            items=(),
            declared_missing=(),
            issues=(IntegrityIssue("error", "MANIFEST_NOT_OBJECT", "Manifest root must be an object.", "$"),),
        )

    company = manifest.get("company")
    if not isinstance(company, Mapping):
        issues.append(IntegrityIssue("error", "COMPANY_MISSING", "Manifest company must be an object.", "$.company"))
        company = {}
    else:
        company = dict(company)
        if "name" in company:
            company["name"] = _neutralize_narrative(
                company["name"],
                path="$.company.name",
                issues=issues,
            )
    for field_name in (
        "name",
        "ticker",
        "market",
        "reporting_currency",
        "trading_currency",
        "accounting_standard",
        "latest_financial_period",
    ):
        if not str(company.get(field_name, "")).strip():
            issues.append(
                IntegrityIssue(
                    "error",
                    "COMPANY_FIELD_MISSING",
                    f"Company field is required: {field_name}.",
                    f"$.company.{field_name}",
                )
            )

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        issues.append(IntegrityIssue("error", "SOURCES_MISSING", "Manifest must contain at least one source.", "$.sources"))
        sources = []

    source_ids: set[str] = set()
    all_declared_source_ids = {
        str(source.get("source_id", "")).strip()
        for source in sources
        if isinstance(source, Mapping) and str(source.get("source_id", "")).strip()
    }
    next_id = 1
    for source_index, source in enumerate(sources):
        path = f"$.sources[{source_index}]"
        if not isinstance(source, Mapping):
            issues.append(IntegrityIssue("error", "SOURCE_NOT_OBJECT", "Source must be an object.", path))
            continue
        source_id = str(source.get("source_id", "")).strip()
        tier = str(source.get("tier", "")).strip().lower()
        if not source_id:
            issues.append(IntegrityIssue("error", "SOURCE_ID_MISSING", "source_id is required.", f"{path}.source_id"))
            continue
        if source_id in source_ids:
            issues.append(IntegrityIssue("error", "DUPLICATE_SOURCE_ID", f"Duplicate source_id: {source_id}.", f"{path}.source_id"))
        source_ids.add(source_id)
        if tier not in VALID_SOURCE_TIERS:
            issues.append(IntegrityIssue("error", "SOURCE_TIER_INVALID", f"Unsupported source tier: {tier}.", f"{path}.tier"))

        publisher = _neutralize_narrative(
            source.get("publisher", ""),
            path=f"{path}.publisher",
            issues=issues,
        ).strip()
        title = _neutralize_narrative(
            source.get("title", ""),
            path=f"{path}.title",
            issues=issues,
        ).strip()
        url_or_api = str(source.get("url_or_api", "")).strip()
        retrieved_at = str(source.get("retrieved_at", "")).strip()
        available_at = str(
            source.get("available_at")
            or source.get("published_at")
            or source.get("report_date")
            or ""
        ).strip()
        for field_name, value in (
            ("publisher", publisher),
            ("title", title),
            ("url_or_api", url_or_api),
            ("retrieved_at", retrieved_at),
        ):
            if not value:
                issues.append(
                    IntegrityIssue(
                        "error" if field_name == "retrieved_at" else "warning",
                        "SOURCE_RETRIEVED_AT_MISSING" if field_name == "retrieved_at" else "SOURCE_METADATA_MISSING",
                        f"Source metadata is missing: {field_name}.",
                        f"{path}.{field_name}",
                    )
                )

        declared_class = str(source.get("official_or_secondary", "")).strip().lower()
        if declared_class == "official" and tier != "official":
            issues.append(
                IntegrityIssue(
                    "error",
                    "SOURCE_CLASSIFICATION_CONFLICT",
                    f"Source {source_id} cannot claim official coverage with tier={tier}.",
                    f"{path}.official_or_secondary",
                )
            )
        official = tier == "official"
        retrieved_date = _parse_iso_date(retrieved_at)
        if retrieved_at and retrieved_date is None:
            issues.append(
                IntegrityIssue(
                    "error",
                    "SOURCE_RETRIEVED_AT_INVALID",
                    f"Source retrieved_at is not a valid ISO date: {source_id}.",
                    f"{path}.retrieved_at",
                )
            )
        available_date = _parse_iso_date(available_at)
        if not available_at:
            issues.append(
                IntegrityIssue(
                    "error",
                    "SOURCE_AVAILABLE_AT_MISSING",
                    f"Source {source_id} must declare available_at, published_at, or report_date.",
                    f"{path}.available_at",
                )
            )
        elif available_date is None:
            issues.append(
                IntegrityIssue(
                    "error",
                    "SOURCE_AVAILABLE_AT_INVALID",
                    f"Source availability date is invalid: {source_id}.",
                    f"{path}.available_at",
                )
            )
        elif locked_date is not None and available_date > locked_date:
            issues.append(
                IntegrityIssue(
                    "error",
                    "SOURCE_NOT_AVAILABLE_AS_OF",
                    f"Source {source_id} was not publicly available by the locked as-of date.",
                    f"{path}.available_at",
                )
            )
        if source_id and source_id not in {record.source_id for record in source_records}:
            source_records.append(
                SourceRecord(
                    source_id=source_id,
                    tier=tier,
                    publisher=publisher,
                    title=title,
                    url_or_api=url_or_api,
                    retrieved_at=retrieved_at,
                    available_at=available_at,
                    official=official and tier != "estimate",
                )
            )
        extracted = source.get("extracted_fields")
        if not isinstance(extracted, list):
            issues.append(IntegrityIssue("error", "EXTRACTED_FIELDS_INVALID", "extracted_fields must be a list.", f"{path}.extracted_fields"))
            continue
        if tier == "missing" and extracted:
            issues.append(
                IntegrityIssue(
                    "error",
                    "MISSING_SOURCE_HAS_FIELDS",
                    "A missing-source placeholder cannot provide extracted fields.",
                    f"{path}.extracted_fields",
                )
            )
            extracted = []
        for field_index, field in enumerate(extracted):
            field_path = f"{path}.extracted_fields[{field_index}]"
            if not isinstance(field, Mapping):
                issues.append(IntegrityIssue("error", "FIELD_NOT_OBJECT", "Extracted field must be an object.", field_path))
                continue
            canonical = canonical_field_name(field.get("field_name"))
            field_subject_id = str(
                field.get("subject_id") or company.get("ticker", "")
            ).strip()
            semantic_role = str(
                field.get("semantic_role") or canonical
            ).strip().lower()
            period = str(field.get("period", "")).strip()
            unit = str(field.get("unit", "")).strip()
            currency = str(field.get("currency", "")).strip()
            if not canonical:
                issues.append(IntegrityIssue("error", "FIELD_NAME_MISSING", "field_name is required.", f"{field_path}.field_name"))
                continue
            for required_name, value in (("period", period), ("unit", unit), ("currency", currency)):
                if not value:
                    issues.append(
                        IntegrityIssue(
                            "error",
                            "FIELD_METADATA_MISSING",
                            f"Extracted field metadata is required: {required_name}.",
                            f"{field_path}.{required_name}",
                        )
                    )
            if "value" not in field or field.get("value") is None:
                issues.append(IntegrityIssue("error", "FIELD_VALUE_MISSING", "Extracted field value is required; zero is valid.", f"{field_path}.value"))
                continue
            if not has_numeric_payload(field.get("value")):
                issues.append(
                    IntegrityIssue(
                        "error",
                        "FIELD_VALUE_NOT_NUMERIC",
                        f"Financial field must contain a finite numeric value: {canonical}.",
                        f"{field_path}.value",
                    )
                )
            expected_currency = ""
            if (
                field_subject_id == str(company.get("ticker", "")).strip()
                and canonical in REPORTING_CURRENCY_FIELDS
            ):
                expected_currency = str(company.get("reporting_currency", "")).strip()
            elif (
                field_subject_id == str(company.get("ticker", "")).strip()
                and canonical in MARKET_CURRENCY_FIELDS
            ):
                expected_currency = str(company.get("trading_currency", "")).strip()
            if expected_currency and currency and currency != expected_currency:
                issues.append(
                    IntegrityIssue(
                        "error",
                        "FIELD_CURRENCY_MISMATCH",
                        f"Field {canonical} uses {currency}; expected {expected_currency} for this run.",
                        f"{field_path}.currency",
                    )
                )
            is_estimate_source = tier == "estimate"
            field_basis_sources = tuple(
                str(value) for value in field.get("basis_sources", []) if value
            )
            if is_estimate_source and (
                not field_basis_sources
                or any(value not in all_declared_source_ids for value in field_basis_sources)
            ):
                issues.append(
                    IntegrityIssue(
                        "warning",
                        "ESTIMATE_SOURCE_BASIS_INVALID",
                        f"Estimate field {canonical} was ignored because its basis sources are missing or unknown.",
                        f"{field_path}.basis_sources",
                    )
                )
                continue
            items.append(
                EvidenceItem(
                    evidence_id=f"E{next_id:04d}",
                    subject_id=field_subject_id,
                    semantic_role=semantic_role,
                    field_name=canonical,
                    period=period,
                    value=field.get("value"),
                    unit=unit,
                    currency=currency,
                    source_id=source_id,
                    source_tier=tier,
                    publisher=publisher,
                    title=title,
                    url_or_api=url_or_api,
                    retrieved_at=retrieved_at,
                    extraction_method=_neutralize_narrative(
                        field.get("extraction_method", "unspecified"),
                        path=f"{field_path}.extraction_method",
                        issues=issues,
                    ),
                    confidence=str(field.get("confidence", "unknown")),
                    official=official and not is_estimate_source,
                    estimated=is_estimate_source,
                    derived_from=tuple(str(value) for value in field.get("derived_from", []) if value),
                    estimate_metadata=_estimate_metadata(
                        field,
                        policy=str(source.get("policy", "")).strip(),
                    ) if is_estimate_source else {},
                    basis_sources=field_basis_sources,
                )
            )
            next_id += 1

        cross_checks = source.get("cross_checks", [])
        if isinstance(cross_checks, list):
            for check_index, check in enumerate(cross_checks):
                if not isinstance(check, Mapping):
                    continue
                status = str(check.get("status", "")).lower()
                if status in {"mismatch", "conflict", "unresolved", "unresolved_conflict"}:
                    issues.append(
                        IntegrityIssue(
                            "error",
                            "UNRESOLVED_SOURCE_CONFLICT",
                            f"Source conflict remains unresolved for {source_id}.",
                            f"{path}.cross_checks[{check_index}]",
                        )
                    )

    if estimates and isinstance(estimates, Mapping):
        overlay_company = str(estimates.get("company", "")).strip()
        overlay_ticker = str(estimates.get("ticker", "")).strip()
        manifest_ticker = str(company.get("ticker", "")).strip()
        if (
            overlay_company
            and overlay_company != str(company.get("name", "")).strip()
            and (not overlay_ticker or overlay_ticker != manifest_ticker)
        ):
            issues.append(
                IntegrityIssue(
                    "error",
                    "ESTIMATE_COMPANY_MISMATCH",
                    "Estimate overlay company does not match the manifest company.",
                    "$.estimates.company",
                )
            )
        if overlay_ticker and overlay_ticker != manifest_ticker:
            issues.append(
                IntegrityIssue(
                    "error",
                    "ESTIMATE_TICKER_MISMATCH",
                    "Estimate overlay ticker does not match the manifest ticker.",
                    "$.estimates.ticker",
                )
            )
        overlay_as_of = str(estimates.get("as_of_date", "")).strip()
        overlay_date = _parse_iso_date(overlay_as_of)
        if overlay_as_of and overlay_date is None:
            issues.append(
                IntegrityIssue(
                    "error",
                    "ESTIMATE_AS_OF_INVALID",
                    "Estimate overlay as_of_date must be a valid ISO date.",
                    "$.estimates.as_of_date",
                )
            )
        elif locked_date is not None and overlay_date is not None and overlay_date > locked_date:
            issues.append(
                IntegrityIssue(
                    "error",
                    "ESTIMATE_AFTER_AS_OF",
                    "Estimate overlay was produced after the locked as-of date.",
                    "$.estimates.as_of_date",
                )
            )
        raw_estimates = estimates.get("estimates", [])
        if isinstance(raw_estimates, list):
            for estimate_index, estimate in enumerate(raw_estimates):
                if not isinstance(estimate, Mapping):
                    issues.append(
                        IntegrityIssue(
                            "warning",
                            "ESTIMATE_NOT_OBJECT",
                            "Estimate entry was ignored because it is not an object.",
                            f"$.estimates[{estimate_index}]",
                        )
                    )
                    continue
                canonical = canonical_field_name(estimate.get("field_name"))
                if not canonical:
                    continue
                estimate_value = estimate.get("estimate_value")
                period = str(estimate.get("period", "")).strip()
                unit = str(estimate.get("unit", "")).strip()
                currency = str(estimate.get("currency", "")).strip()
                basis_sources = tuple(
                    str(value) for value in estimate.get("basis_sources", []) if value
                )
                unknown_basis = [value for value in basis_sources if value not in source_ids]
                if (
                    estimate_value is None
                    or not has_numeric_payload(estimate_value)
                    or not period
                    or not unit
                    or not currency
                    or not basis_sources
                    or unknown_basis
                ):
                    issues.append(
                        IntegrityIssue(
                            "warning",
                            "ESTIMATE_INPUT_INVALID",
                            f"Estimate {canonical} was ignored because metadata, numeric payload, or basis sources are invalid.",
                            f"$.estimates.estimates[{estimate_index}]",
                        )
                    )
                    continue
                items.append(
                    EvidenceItem(
                        evidence_id=f"E{next_id:04d}",
                        subject_id=str(company.get("ticker", "")).strip(),
                        semantic_role=canonical,
                        field_name=canonical,
                        period=period,
                        value=estimate_value,
                        unit=unit,
                        currency=currency,
                        source_id=f"ESTIMATE_{canonical}_{estimate.get('period', '')}",
                        source_tier="estimate",
                        publisher="Estimate overlay",
                        title=_neutralize_narrative(
                            estimate.get("estimate_method", "Explicit estimate"),
                            path=f"$.estimates.estimates[{estimate_index}].estimate_method",
                            issues=issues,
                        ),
                        url_or_api="",
                        retrieved_at=str(estimates.get("as_of_date", "")),
                        extraction_method=_neutralize_narrative(
                            estimate.get("estimate_method", "explicit_estimate"),
                            path=f"$.estimates.estimates[{estimate_index}].estimate_method",
                            issues=issues,
                        ),
                        confidence=str(estimate.get("confidence", "low")),
                        official=False,
                        estimated=True,
                        estimate_metadata=_estimate_metadata(
                            estimate,
                            policy=str(estimates.get("policy", "")).strip(),
                        ),
                        basis_sources=basis_sources,
                    )
                )
                next_id += 1

    missing = manifest.get("missing_critical_data", [])
    declared_missing: list[Mapping[str, Any]] = []
    if isinstance(missing, list):
        for index, item in enumerate(missing):
            if not isinstance(item, Mapping):
                issues.append(IntegrityIssue("warning", "MISSING_ENTRY_INVALID", "Missing-data entry must be an object.", f"$.missing_critical_data[{index}]"))
                continue
            copied = dict(item)
            copied["field_name"] = canonical_field_name(item.get("field_name"))
            for narrative_key in (
                "missing_reason",
                "why_missing",
                "next_data_required",
                "next_required_evidence",
                "affected_outputs",
            ):
                if narrative_key in copied and isinstance(copied[narrative_key], str):
                    copied[narrative_key] = _neutralize_narrative(
                        copied[narrative_key],
                        path=f"$.missing_critical_data[{index}].{narrative_key}",
                        issues=issues,
                    )
            declared_missing.append(copied)

    return EvidenceBuild(
        company=dict(company),
        sources=tuple(source_records),
        items=tuple(items),
        declared_missing=tuple(declared_missing),
        issues=tuple(issues),
    )
