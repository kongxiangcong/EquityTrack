from __future__ import annotations

import re
from typing import Any, Mapping

from .evidence import EvidenceBook, canonical_field_name, numeric_value
from .models import (
    AnalysisBundle,
    AnalysisResult,
    DebateCase,
    DebateResult,
    EvidenceClaim,
    ResearchSynthesis,
)


DIMENSION_SPECS = (
    ("business", "公司与商业模式"),
    ("industry", "行业与竞争格局"),
    ("fundamentals", "基本面与盈利质量"),
    ("technical", "技术趋势与资金行为"),
    ("sentiment_events", "市场情绪与事件"),
    ("valuation", "估值视角"),
    ("governance_risk", "治理与风险"),
)


def _has_unbound_number(text: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", text))


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := str(item).strip()))


def _metric_item(book: EvidenceBook, reference: Any) -> Any:
    if not isinstance(reference, Mapping):
        return None
    field = canonical_field_name(reference.get("field_name"))
    source_id = str(reference.get("source_id", "")).strip()
    period = str(reference.get("period", "")).strip()
    if not source_id or not field or not period:
        return None
    return book.resolve_reference(
        reference,
        allowed_tiers={"official", "terminal", "secondary", "news"},
        expected_subject_id=book.subject_id,
        expected_semantic_role=str(reference.get("semantic_role", field)).strip(),
        expected_field_names={field},
    )


def _metric_units_valid(resolved: tuple[Any, ...], calculation: str, display: str) -> bool:
    units = tuple(item.unit.lower() for item in resolved)
    currencies = tuple(item.currency.upper() for item in resolved)
    if calculation == "direct":
        allowed = {
            "cny_100m": len(resolved) == 1 and currencies[0] == "CNY" and units[0] in {"cny", "yuan", "rmb"},
            "cny_per_share": len(resolved) == 1 and currencies[0] == "CNY" and units[0] in {"cny/share", "cny_per_share"},
            "percent_upper_bound": len(resolved) == 1 and units[0] in {"ratio_upper_bound", "decimal"},
            "tpy_10k": len(resolved) == 1 and units[0] in {"tons/year", "tpy"},
            "number": len(resolved) == 1,
        }
        return allowed.get(display, False)
    if calculation == "ratio":
        return (
            len(resolved) == 2
            and display in {"percent", "multiple"}
            and units[0] == units[1]
            and currencies[0] == currencies[1]
        )
    if calculation == "difference":
        return (
            len(resolved) == 2
            and display == "cny_100m"
            and units[0] == units[1]
            and currencies[0] == currencies[1] == "CNY"
        )
    return False


def _format_metric(value: float, display: str) -> str:
    if display == "cny_100m":
        return f"{value / 100_000_000:,.2f} 亿元"
    if display == "cny_per_share":
        return f"{value:,.2f} 元"
    if display == "percent":
        return f"{value * 100:,.1f}%"
    if display == "percent_upper_bound":
        return f"低于 {value * 100:g}%"
    if display == "multiple":
        return f"{value:,.1f}×"
    if display == "tpy_10k":
        return f"{value / 10_000:,.1f} 万吨/年"
    return f"{value:,.2f}"


def _metrics(value: Any, book: EvidenceBook) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    metrics: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label", "")).strip()
        references = item.get("evidence_refs", [])
        references = references if isinstance(references, list) else []
        resolved = tuple(_metric_item(book, reference) for reference in references)
        if not label or not resolved or any(evidence is None for evidence in resolved):
            continue
        numbers = tuple(numeric_value(evidence.value) for evidence in resolved)
        calculation = str(item.get("calculation", "direct")).strip().lower()
        display = str(item.get("display", "number")).strip().lower()
        if not _metric_units_valid(resolved, calculation, display):
            continue
        if calculation == "direct" and len(numbers) == 1:
            metric_value = numbers[0]
        elif calculation == "ratio" and len(numbers) == 2 and numbers[1] not in (None, 0):
            metric_value = numbers[0] / numbers[1]
        elif calculation == "difference" and len(numbers) == 2:
            metric_value = numbers[0] - numbers[1]
        else:
            continue
        evidence_ids = tuple(dict.fromkeys(evidence.evidence_id for evidence in resolved))
        fields = tuple(dict.fromkeys(evidence.field_name for evidence in resolved))
        metrics.append(
            {
                "label": label,
                "value": _format_metric(float(metric_value), display),
                "note": " · ".join(dict.fromkeys(evidence.period for evidence in resolved)),
                "tone": str(item.get("tone", "neutral")).strip() or "neutral",
                "evidence_fields": list(fields),
                "evidence_ids": list(evidence_ids),
            }
        )
    return tuple(metrics)


def _claims(
    value: Any,
    book: EvidenceBook,
    default_fields: tuple[str, ...],
) -> tuple[EvidenceClaim, ...]:
    if not isinstance(value, list):
        return ()
    claims: list[EvidenceClaim] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        raw = item
        text = str(raw.get("text", "")).strip()
        fields = tuple(
            canonical_field_name(field)
            for field in raw.get("evidence_fields", default_fields)
            if canonical_field_name(field)
        ) if isinstance(raw.get("evidence_fields", default_fields), (list, tuple)) else ()
        evidence_ids = _resolve_evidence(book, fields, allow_estimate=False)
        # Numeric facts belong in deterministic metrics, never in free-form claims.
        if (
            not text
            or _has_unbound_number(text)
            or not fields
            or len(evidence_ids) != len(set(fields))
        ):
            continue
        claims.append(EvidenceClaim(text, fields, evidence_ids))
    return tuple(claims)


def _resolve_evidence(
    book: EvidenceBook,
    fields: tuple[str, ...],
    *,
    allow_estimate: bool,
) -> tuple[str, ...]:
    ids: list[str] = []
    for field in fields:
        item = book.best(field, allow_estimate=allow_estimate)
        if item and item.evidence_id not in ids:
            ids.append(item.evidence_id)
    return tuple(ids)


def _analysis_bundle(book: EvidenceBook, context: Mapping[str, Any]) -> AnalysisBundle:
    raw_dimensions = context.get("analyses", {})
    raw_dimensions = raw_dimensions if isinstance(raw_dimensions, Mapping) else {}
    dimensions: dict[str, AnalysisResult] = {}
    missing: list[str] = []
    has_v3 = int(context.get("report_version", 0) or 0) >= 3

    for dimension_id, title in DIMENSION_SPECS:
        raw = raw_dimensions.get(dimension_id, {})
        if not isinstance(raw, Mapping):
            raw = {}
        conclusion = str(raw.get("conclusion", "")).strip()
        if _has_unbound_number(conclusion):
            conclusion = ""
        fields = tuple(
            canonical_field_name(item)
            for item in raw.get("evidence_fields", [])
            if canonical_field_name(item)
        ) if isinstance(raw.get("evidence_fields", []), list) else ()
        sourced_ids = _resolve_evidence(book, fields, allow_estimate=False)
        evidence_ids = _resolve_evidence(book, fields, allow_estimate=True)
        key_findings = _claims(raw.get("key_findings"), book, fields)
        counterpoints = _claims(raw.get("counterpoints"), book, fields)
        uncertainties = _claims(raw.get("uncertainties"), book, fields)
        requested_status = str(raw.get("status", "ready")).strip().lower()
        status = requested_status if requested_status in {"ready", "limited", "blocked"} else "limited"
        if not conclusion or not evidence_ids:
            status = "blocked"
        elif len(sourced_ids) != len(set(fields)):
            status = "limited"
        elif not key_findings or not counterpoints or not uncertainties:
            status = "limited"
        if status == "blocked":
            missing.append(dimension_id)
        dimensions[dimension_id] = AnalysisResult(
            dimension_id=dimension_id,
            title=str(raw.get("title", title)).strip() or title,
            status=status,
            conclusion=conclusion or "当前证据不足以形成这一维度的公司判断。",
            key_findings=key_findings,
            counterpoints=counterpoints,
            uncertainties=uncertainties,
            key_metrics=_metrics(raw.get("key_metrics"), book),
            evidence_fields=fields,
            evidence_ids=evidence_ids,
        )

    if not has_v3:
        return AnalysisBundle({}, "legacy", ())
    completeness = (
        "complete"
        if not missing and all(item.status == "ready" for item in dimensions.values())
        else "complete_with_limits"
        if not missing
        else "partial"
    )
    return AnalysisBundle(dimensions, completeness, tuple(missing))


def _debate_case(
    side: str,
    raw: Any,
    book: EvidenceBook,
) -> DebateCase:
    raw = raw if isinstance(raw, Mapping) else {}
    arguments: list[Mapping[str, Any]] = []
    ids: list[str] = []
    for item in raw.get("arguments", []) if isinstance(raw.get("arguments", []), list) else []:
        if not isinstance(item, Mapping):
            continue
        fields = tuple(
            canonical_field_name(field)
            for field in item.get("evidence_fields", [])
            if canonical_field_name(field)
        ) if isinstance(item.get("evidence_fields", []), list) else ()
        item_ids = _resolve_evidence(book, fields, allow_estimate=False)
        for evidence_id in item_ids:
            if evidence_id not in ids:
                ids.append(evidence_id)
        claim = str(item.get("claim", "")).strip()
        if claim and not _has_unbound_number(claim) and fields and len(item_ids) == len(set(fields)):
            arguments.append(
                {
                    "argument_id": str(item.get("argument_id", "")).strip(),
                    "claim": claim,
                    "response_to": str(item.get("response_to", "")).strip(),
                    "evidence_ids": list(item_ids),
                }
            )
    return DebateCase(
        side=side,
        thesis=str(raw.get("thesis", "")).strip(),
        arguments=tuple(arguments),
        evidence_ids=tuple(ids),
    )


def _debate(book: EvidenceBook, context: Mapping[str, Any]) -> DebateResult | None:
    raw = context.get("debate")
    if not isinstance(raw, Mapping):
        return None
    bull = _debate_case("bull", raw.get("bull"), book)
    bear = _debate_case("bear", raw.get("bear"), book)
    all_arguments = tuple(bull.arguments) + tuple(bear.arguments)
    argument_sides = {
        str(item.get("argument_id", "")): side
        for side, case in (("bull", bull), ("bear", bear))
        for item in case.arguments
        if item.get("argument_id")
    }
    if len(argument_sides) != len(all_arguments):
        return None
    for side, case in (("bull", bull), ("bear", bear)):
        for item in case.arguments:
            response_to = str(item.get("response_to", ""))
            if response_to and argument_sides.get(response_to) != ("bear" if side == "bull" else "bull"):
                return None
    if not any(item.get("response_to") for item in bull.arguments) or not any(
        item.get("response_to") for item in bear.arguments
    ):
        return None
    manager_summary = str(raw.get("manager_summary", "")).strip()
    debate_lists = (
        _strings(raw.get("key_disagreements")),
        _strings(raw.get("resolved_disagreements")),
        _strings(raw.get("unresolved_questions")),
    )
    if (
        not bull.thesis
        or not bear.thesis
        or not bull.evidence_ids
        or not bear.evidence_ids
        or not manager_summary
        or any(_has_unbound_number(text) for text in (bull.thesis, bear.thesis, manager_summary))
        or any(_has_unbound_number(text) for values in debate_lists for text in values)
    ):
        return None
    return DebateResult(
        bull=bull,
        bear=bear,
        manager_summary=manager_summary,
        key_disagreements=debate_lists[0],
        resolved_disagreements=debate_lists[1],
        unresolved_questions=debate_lists[2],
    )


def _synthesis(book: EvidenceBook, context: Mapping[str, Any]) -> ResearchSynthesis | None:
    raw = context.get("synthesis")
    if not isinstance(raw, Mapping):
        return None
    fields = tuple(
        canonical_field_name(item)
        for item in raw.get("evidence_fields", [])
        if canonical_field_name(item)
    ) if isinstance(raw.get("evidence_fields", []), list) else ()
    evidence_ids = _resolve_evidence(book, fields, allow_estimate=False)
    required = (
        "core_thesis",
        "variant_view",
        "business_quality",
        "earnings_outlook",
        "market_view",
        "valuation_view",
        "risk_reward_summary",
    )
    values = {key: str(raw.get(key, "")).strip() for key in required}
    uncertainty_values = _strings(raw.get("key_uncertainties"))
    view_change_values = _strings(raw.get("what_would_change_the_view"))
    if (
        any(not values[key] for key in required)
        or any(_has_unbound_number(values[key]) for key in required)
        or not fields
        or len(evidence_ids) != len(set(fields))
        or any(
            _has_unbound_number(text)
            for text in uncertainty_values + view_change_values
        )
    ):
        return None
    return ResearchSynthesis(
        **values,
        key_uncertainties=uncertainty_values,
        what_would_change_the_view=view_change_values,
        evidence_ids=evidence_ids,
    )


def build_professional_narrative(
    book: EvidenceBook,
    context: Mapping[str, Any],
) -> tuple[AnalysisBundle, DebateResult | None, ResearchSynthesis | None, str]:
    bundle = _analysis_bundle(book, context)
    if bundle.completeness == "legacy":
        return bundle, None, None, "audit_report"
    debate = _debate(book, context)
    synthesis = _synthesis(book, context)
    if bundle.completeness in {"complete", "complete_with_limits"} and debate and synthesis:
        return bundle, debate, synthesis, "professional"
    if bundle.dimensions:
        return bundle, debate, synthesis, "professional_limited"
    return bundle, debate, synthesis, "audit_memo"
