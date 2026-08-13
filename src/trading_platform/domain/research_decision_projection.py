from __future__ import annotations

from typing import Any, Mapping


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_tuple(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text for item in value if (text := _text(item)))


def _unique_texts(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(text for group in groups for text in group))


def _canonical_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_canonical_safe(item) for item in value)
    if isinstance(value, float):
        return format(value, ".15g")
    return value


def _analysis_dimensions(
    analysis: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    dimensions = _mapping(analysis.get("dimensions"))
    return tuple(
        dict(value)
        for _, value in sorted(dimensions.items(), key=lambda item: str(item[0]))
        if isinstance(value, Mapping)
    )


def _claim_texts(
    dimensions: tuple[Mapping[str, Any], ...],
    key: str,
) -> tuple[str, ...]:
    values: list[str] = []
    for dimension in dimensions:
        claims = dimension.get(key)
        if not isinstance(claims, (list, tuple)):
            continue
        for claim in claims:
            text = (
                _text(claim.get("text")) if isinstance(claim, Mapping) else _text(claim)
            )
            if text:
                values.append(text)
    return tuple(dict.fromkeys(values))


def _method_views(value: object) -> tuple[Mapping[str, Any], ...]:
    methods = _mapping(value)
    projected: list[Mapping[str, Any]] = []
    for key, method_value in sorted(methods.items(), key=lambda item: str(item[0])):
        if not isinstance(method_value, Mapping):
            continue
        method = dict(method_value)
        method_id = _text(method.get("method_id")) or str(key)
        projected.append(
            {
                "method_id": method_id,
                "label": _text(method.get("label")) or method_id,
                "status": _text(method.get("status")) or "blocked",
                "role": _text(method.get("role")),
                "explanation": _text(method.get("explanation")),
                "missing_fields": _texts(method.get("missing_fields")),
                "evidence_ids": _texts(method.get("evidence_ids")),
                "assumptions": dict(_mapping(method.get("assumptions"))),
                "metrics": dict(_mapping(method.get("metrics"))),
                "diagnostics": _texts(method.get("diagnostics")),
            }
        )
    return tuple(projected)


def _valuation_projection(
    *,
    run_status: str,
    permissions: Mapping[str, Any],
    methods: tuple[Mapping[str, Any], ...],
    synthesis: Mapping[str, Any],
) -> Mapping[str, Any]:
    formal_allowed = permissions.get("formal_per_share_valuation") is True
    method_statuses = {_text(method.get("status")) for method in methods}
    usable_statuses = {
        "ready",
        "ready_with_estimates",
        "limited",
        "caution",
    }
    if run_status == "blocked":
        status = "blocked"
        reason_code = "RESEARCH_RUN_BLOCKED"
    elif formal_allowed and "ready" in method_statuses:
        status = "ready"
        reason_code = "VALUATION_METHODS_READY"
    elif method_statuses & usable_statuses:
        status = "limited"
        reason_code = "VALUATION_METHODS_LIMITED"
    else:
        status = "unavailable"
        reason_code = "VALUATION_METHODS_UNAVAILABLE"

    narrative = _text(synthesis.get("valuation_view"))
    if not narrative:
        labels = "、".join(
            _text(method.get("label"))
            for method in methods
            if _text(method.get("label"))
            and _text(method.get("status")) in usable_statuses
        )
        if status == "ready":
            narrative = f"{labels or '已选择方法'}已通过正式估值门禁。"
        elif status == "limited":
            narrative = (
                f"{labels or '现有方法'}仅支持带限制的条件估值框架；"
                "方法状态和假设保持显式。"
            )
        elif status == "unavailable":
            narrative = "现有证据可支持公司研究，但当前没有满足输入门禁的估值方法。"
        else:
            narrative = "研究运行未通过完整性门禁，估值输出被阻断。"

    missing_fields = _unique_texts(
        *(_texts(method.get("missing_fields")) for method in methods)
    )
    return {
        "status": status,
        "reason_code": reason_code,
        "summary": narrative,
        "formal_per_share_valuation": formal_allowed,
        "methods": methods,
        "missing_fields": missing_fields,
    }


def _evidence_origin(item: Mapping[str, Any]) -> str:
    derived_fields = {"debt", "working_capital", "fcf", "d_and_a"}
    if item.get("estimated") is True or item.get("source_tier") == "estimate":
        return "estimated"
    derived_from = item.get("derived_from")
    if isinstance(derived_from, (list, tuple)) and derived_from:
        return "derived"
    extraction_method = _text(item.get("extraction_method"))
    provider_expression = extraction_method.rsplit(":", 1)[-1]
    if "+" in provider_expression or (
        _text(item.get("field_name")) in derived_fields
        and extraction_method.startswith("agentgw:ifind:")
    ):
        return "derived"
    if item.get("official") is True or item.get("source_tier") == "official":
        return "observed_official"
    return "observed_structured"


def _key_drivers(
    *,
    dimensions: tuple[Mapping[str, Any], ...],
    evidence: tuple[Mapping[str, Any], ...],
    summary: Mapping[str, Any],
    as_of: str,
) -> tuple[Mapping[str, Any], ...]:
    by_id = {
        _text(item.get("evidence_id")): item
        for item in evidence
        if _text(item.get("evidence_id"))
    }
    by_field = {
        _text(item.get("field_name")): item
        for item in evidence
        if _text(item.get("field_name"))
    }
    by_field_period = {
        (_text(item.get("field_name")), _text(item.get("period"))): item
        for item in evidence
        if _text(item.get("field_name"))
    }
    projected: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for dimension in dimensions:
        metrics = dimension.get("key_metrics")
        if not isinstance(metrics, (list, tuple)):
            continue
        for metric_value in metrics:
            if not isinstance(metric_value, Mapping):
                continue
            metric = dict(metric_value)
            metric_id = _text(metric.get("metric_id"))
            if not metric_id:
                continue
            period = _text(metric.get("period"))
            evidence_item = (
                by_id.get(_text(metric.get("evidence_id")))
                or by_field_period.get((metric_id, period))
                or by_field.get(metric_id)
                or {}
            )
            identity = (metric_id, period)
            if identity in seen:
                continue
            seen.add(identity)
            metric.setdefault("label", metric_id)
            value_origin = _evidence_origin(evidence_item or metric)
            metric["value_origin"] = value_origin
            if evidence_item:
                metric.setdefault("evidence_id", evidence_item.get("evidence_id"))
                metric.setdefault("source_tier", evidence_item.get("source_tier"))
                estimate_metadata = _mapping(evidence_item.get("estimate_metadata"))
                if value_origin == "estimated" and estimate_metadata:
                    metric["estimate_metadata"] = dict(estimate_metadata)
            projected.append(metric)

    if not projected:
        for item in evidence:
            metric_id = _text(item.get("field_name"))
            if not metric_id or item.get("value") is None:
                continue
            metric = {
                "metric_id": metric_id,
                "label": metric_id,
                "value": item.get("value"),
                "unit": item.get("unit"),
                "currency": item.get("currency"),
                "period": item.get("period"),
                "value_origin": _evidence_origin(item),
                "evidence_id": item.get("evidence_id"),
                "source_tier": item.get("source_tier"),
            }
            estimate_metadata = _mapping(item.get("estimate_metadata"))
            if metric["value_origin"] == "estimated" and estimate_metadata:
                metric["estimate_metadata"] = dict(estimate_metadata)
            projected.append(metric)
            if len(projected) == 12:
                break

    if not projected:
        evidence_counts = _mapping(summary.get("evidence_counts"))
        if "total" in evidence_counts:
            projected.append(
                {
                    "metric_id": "evidence_count",
                    "label": "纳入研究的证据数量",
                    "value": evidence_counts["total"],
                    "unit": "count",
                    "period": as_of,
                    "value_origin": "derived",
                    "source_tier": "research_summary",
                }
            )
        elif "data_quality_score" in summary:
            projected.append(
                {
                    "metric_id": "data_quality_score",
                    "label": "数据质量分数",
                    "value": summary["data_quality_score"],
                    "unit": "score",
                    "period": as_of,
                    "value_origin": "derived",
                    "source_tier": "research_summary",
                }
            )
    return tuple(projected)


def _story_projection(
    *,
    run_status: str,
    summary: Mapping[str, Any],
    analysis: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    debate: Mapping[str, Any],
    methods: tuple[Mapping[str, Any], ...],
    declared_missing: tuple[Mapping[str, Any], ...],
    conditional_plan: tuple[Mapping[str, Any], ...],
    valuation_view: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str, tuple[str, ...], tuple[str, ...]]:
    dimensions = _analysis_dimensions(analysis)
    executive = _text(summary.get("executive_summary"))
    if not executive:
        executive = (
            "现有证据形成了带限制的结构化公司研究。"
            if run_status != "blocked"
            else "研究运行未通过完整性门禁。"
        )
    conclusions = tuple(
        f"{_text(item.get('title')) or _text(item.get('dimension_id'))}：{conclusion}"
        for item in dimensions
        if (conclusion := _text(item.get("conclusion")))
    )
    findings = _claim_texts(dimensions, "key_findings")
    counterpoints = _claim_texts(dimensions, "counterpoints")
    analysis_uncertainties = _claim_texts(dimensions, "uncertainties")
    method_limits = tuple(
        explanation
        for method in methods
        if _text(method.get("status"))
        in {"blocked", "disabled", "limited", "caution", "ready_with_estimates"}
        and (explanation := _text(method.get("explanation")))
    )
    declared_uncertainties = tuple(
        f"{field_name}：{reason}"
        for item in declared_missing
        if (field_name := _text(item.get("field_name")))
        and (reason := _text(item.get("missing_reason")))
    )
    key_uncertainties = _unique_texts(
        _texts(synthesis.get("key_uncertainties")),
        analysis_uncertainties,
        declared_uncertainties,
        method_limits,
    )
    if not key_uncertainties:
        key_uncertainties = ("当前结论受数据覆盖和方法适用性限制。",)

    plan_triggers = tuple(
        (f"{watch}：{trigger}" if (watch := _text(item.get("watch"))) else trigger)
        for item in conditional_plan
        if (trigger := _text(item.get("validation_trigger")))
    )
    next_data = tuple(
        text
        for item in declared_missing
        if (text := _text(item.get("next_data_required")))
    )
    what_changes = _unique_texts(
        _texts(synthesis.get("what_would_change_the_view")),
        plan_triggers,
        next_data,
    )
    if not what_changes:
        what_changes = ("更新冻结证据并重新评估受限方法。",)

    risk_reward = (
        _text(synthesis.get("risk_reward_summary"))
        or _text(debate.get("manager_summary"))
        or executive
    )
    transmission = _unique_texts(
        tuple(
            text
            for key in ("business_quality", "earnings_outlook", "market_view")
            if (text := _text(synthesis.get(key)))
        ),
        conclusions,
    )
    story = {
        "status": run_status,
        "what_happens": (executive,),
        "why_it_matters": findings or conclusions or (risk_reward,),
        "transmission": transmission or (valuation_view["summary"],),
        "counterevidence": _unique_texts(
            counterpoints,
            analysis_uncertainties,
            method_limits,
        )
        or key_uncertainties,
        "what_would_change_the_view": what_changes,
        "core_thesis": _text(synthesis.get("core_thesis")) or executive,
        "variant_view": _text(synthesis.get("variant_view")),
        "business_quality": _text(synthesis.get("business_quality")),
        "earnings_outlook": _text(synthesis.get("earnings_outlook")),
        "valuation_view": valuation_view["summary"],
        "valuation_guardrails": method_limits or key_uncertainties,
        "risk_reward_summary": risk_reward,
        "key_uncertainties": key_uncertainties,
    }
    return story, risk_reward, key_uncertainties, what_changes


def _simulation_decision(
    required_dimensions: tuple[str, ...],
    research_payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    existing = research_payload.get("valuation_simulation")
    if isinstance(existing, Mapping) and existing:
        return dict(existing)
    requested = "valuation_simulation" in required_dimensions
    if requested:
        return {
            "status": "not_run",
            "reason_code": "VALUATION_SIMULATION_INPUTS_UNAVAILABLE",
            "explanation": "本次评估请求了估值仿真，但没有产生可发布的仿真产物。",
        }
    return {
        "status": "not_run",
        "reason_code": "VALUATION_SIMULATION_NOT_REQUESTED",
        "explanation": "本次评估计划未请求估值仿真。",
    }


def _market_path_decision(
    required_dimensions: tuple[str, ...],
    research_payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    existing = research_payload.get("market_price_paths")
    if isinstance(existing, Mapping) and existing:
        return dict(existing)
    if "market_path" in required_dimensions:
        return {
            "status": "not_run",
            "reason_code": "MARKET_PATH_INPUTS_UNAVAILABLE",
            "explanation": "本次评估请求了市场价格路径，但没有产生可发布的路径产物。",
        }
    return {
        "status": "not_run",
        "reason_code": "MARKET_PATH_NOT_REQUESTED",
        "explanation": "本次评估计划未请求市场价格路径。",
    }


def project_research_decision(
    *,
    as_of: str,
    required_dimensions: tuple[str, ...],
    research_payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    run_status = _text(research_payload.get("status")) or "blocked"
    summary = dict(_mapping(research_payload.get("summary")))
    analysis = dict(_mapping(research_payload.get("analysis")))
    synthesis = dict(_mapping(research_payload.get("synthesis")))
    debate = dict(_mapping(research_payload.get("debate")))
    permissions = dict(_mapping(research_payload.get("permissions")))
    methods = _method_views(research_payload.get("methods"))
    evidence = _mapping_tuple(research_payload.get("evidence"))
    declared_missing = _mapping_tuple(research_payload.get("declared_missing"))
    conditional_plan = _mapping_tuple(research_payload.get("conditional_plan"))
    valuation_view = _valuation_projection(
        run_status=run_status,
        permissions=permissions,
        methods=methods,
        synthesis=synthesis,
    )
    story, risk_reward, uncertainties, what_changes = _story_projection(
        run_status=run_status,
        summary=summary,
        analysis=analysis,
        synthesis=synthesis,
        debate=debate,
        methods=methods,
        declared_missing=declared_missing,
        conditional_plan=conditional_plan,
        valuation_view=valuation_view,
    )
    simulation = _simulation_decision(required_dimensions, research_payload)
    market_paths = _market_path_decision(required_dimensions, research_payload)
    grade = _text(summary.get("data_quality_grade")).upper()
    if grade not in {"A", "B", "C", "D"}:
        grade = "D"
    dimensions = _analysis_dimensions(analysis)
    projection = {
        "valuation_view": valuation_view,
        "risk_reward_summary": risk_reward,
        "data_quality_grade": grade,
        "key_uncertainties": uncertainties,
        "what_would_change_the_view": what_changes,
        "story": story,
        "key_drivers": _key_drivers(
            dimensions=dimensions,
            evidence=evidence,
            summary=summary,
            as_of=as_of,
        ),
        "scenarios": _mapping_tuple(summary.get("scenarios")),
        "market_implied_expectations": _mapping_tuple(
            research_payload.get("market_implied_expectations")
        ),
        "valuation_simulation": simulation,
        "market_price_paths": market_paths,
        "value_market_divergence": (
            dict(research_payload["value_market_divergence"])
            if isinstance(research_payload.get("value_market_divergence"), Mapping)
            else {
                "status": "not_run",
                "reason_code": "MARKET_PATH_NOT_RUN",
                "explanation": "本次研究未产生市场价格路径，未计算价值与市场路径偏离。",
            }
        ),
    }
    audit = {
        "research_summary": summary,
        "analysis": analysis,
        "synthesis": synthesis,
        "methods": {item["method_id"]: item for item in methods},
        "fact_evidence": evidence,
        "sources": _mapping_tuple(research_payload.get("sources")),
        "declared_missing": declared_missing,
        "integrity_issues": _mapping_tuple(research_payload.get("integrity_issues")),
        "diagnostics": _texts(research_payload.get("diagnostics")),
        "simulation_decision": simulation,
        "market_path_decision": market_paths,
        "versions": {
            "research_run_schema": research_payload.get("schema_version"),
        },
    }
    return _canonical_safe(projection), _canonical_safe(audit)


__all__ = ["project_research_decision"]
