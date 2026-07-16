from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Mapping

from .evidence import EvidenceBook, EvidenceBuild, build_evidence
from .financial import FinancialInvariantError, exact_decimal_from_legacy
from .forecast import ForecastEngine, ForecastInvariantError
from .models import (
    AnalysisBundle,
    IntegrityIssue,
    MethodResult,
    ResearchRequest,
    ResearchRun,
)
from .narrative import NarrativeInputs, build_professional_narrative
from .output_policy import normalize_action_language
from .policies import evaluate_capabilities
from .research_inputs import LegacyResearchContextAdapter, ResearchInputs
from .valuation import route_methods


SCHEMA_VERSION = 3

NARRATIVE_KEYS = {
    "executive_summary",
    "title",
    "detail",
    "event",
    "why_it_matters",
    "name",
    "conditions",
    "view_change",
    "watch",
    "validation_trigger",
    "invalidation",
    "review_window",
    "monitor",
    "monitor_variable",
    "window",
    "conclusion",
    "key_findings",
    "counterpoints",
    "uncertainties",
    "claim",
    "thesis",
    "manager_summary",
    "key_disagreements",
    "unresolved_questions",
    "core_thesis",
    "variant_view",
    "business_quality",
    "earnings_outlook",
    "market_view",
    "valuation_view",
    "risk_reward_summary",
    "key_uncertainties",
    "what_would_change_the_view",
    "value",
    "label",
    "note",
    "response_to",
    "text",
}


def _normalize_context_language(
    value: Any,
    *,
    path: str = "$.context",
    normalize_strings: bool = False,
) -> tuple[Any, tuple[IntegrityIssue, ...]]:
    issues: list[IntegrityIssue] = []
    if isinstance(value, str) and normalize_strings:
        normalized, changed = normalize_action_language(value)
        if changed:
            issues.append(
                IntegrityIssue(
                    "warning",
                    "OUTPUT_LANGUAGE_NORMALIZED",
                    "Action or rating language was converted to neutral research language.",
                    path,
                )
            )
        return normalized, tuple(issues)
    if isinstance(value, list):
        normalized_items: list[Any] = []
        for index, item in enumerate(value):
            normalized, child_issues = _normalize_context_language(
                item,
                path=f"{path}[{index}]",
                normalize_strings=normalize_strings,
            )
            normalized_items.append(normalized)
            issues.extend(child_issues)
        return normalized_items, tuple(issues)
    if isinstance(value, Mapping):
        normalized_mapping: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized, child_issues = _normalize_context_language(
                item,
                path=f"{path}.{key_text}",
                normalize_strings=key_text in NARRATIVE_KEYS,
            )
            normalized_mapping[key_text] = normalized
            issues.extend(child_issues)
        return normalized_mapping, tuple(issues)
    return value, ()


def _normalize_research_inputs(
    inputs: ResearchInputs,
) -> tuple[ResearchInputs, tuple[IntegrityIssue, ...]]:
    narrative = {
        "executive_summary": inputs.executive_summary,
        "theses": list(inputs.theses),
        "risks": list(inputs.risks),
        "catalysts": list(inputs.catalysts),
        "scenarios": list(inputs.scenarios),
        "conditional_plan": list(inputs.conditional_plan),
        "analyses": inputs.analyses,
        "debate": inputs.debate,
        "synthesis": inputs.synthesis,
    }
    normalized, issues = _normalize_context_language(
        narrative,
        path="$.research_inputs",
    )
    return (
        replace(
            inputs,
            executive_summary=str(
                normalized["executive_summary"]
            ).strip(),
            theses=tuple(normalized["theses"]),
            risks=tuple(normalized["risks"]),
            catalysts=tuple(normalized["catalysts"]),
            scenarios=tuple(normalized["scenarios"]),
            conditional_plan=tuple(normalized["conditional_plan"]),
            analyses=normalized["analyses"],
            debate=normalized["debate"],
            synthesis=normalized["synthesis"],
        ),
        issues,
    )


class ResearchEngine:
    """Deep deterministic module behind the research workflow seam."""

    def run(self, request: ResearchRequest) -> ResearchRun:
        if request.research_inputs is not None:
            inputs, policy_issues = _normalize_research_inputs(
                request.research_inputs
            )
        else:
            normalized_context, policy_issues = _normalize_context_language(
                request.context or {}
            )
            migration = LegacyResearchContextAdapter.adapt(
                normalized_context
            )
            inputs = migration.inputs
        build = build_evidence(
            request.manifest,
            request.estimates,
            as_of_date=request.as_of_date,
        )
        forecast_graph = None
        if request.forecast_request is not None:
            if request.forecast_request.as_of != request.as_of_date:
                raise ForecastInvariantError(
                    "FORECAST_RESEARCH_AS_OF_MISMATCH",
                    "ResearchRequest and typed ForecastRequest must share one as-of date.",
                )
            manifest_security_id = str(build.company.get("ticker", "")).strip()
            if (
                not manifest_security_id
                or request.forecast_request.security.security_id != manifest_security_id
            ):
                raise ForecastInvariantError(
                    "FORECAST_RESEARCH_SECURITY_MISMATCH",
                    "Typed Forecast Security must match the canonical manifest Security.",
                )
            self._validate_forecast_fact_manifest(request, build)
            forecast_graph = ForecastEngine().build(request.forecast_request)
        extra_issues: list[IntegrityIssue] = list(policy_issues)
        if request.profile not in {"quick", "standard", "deep"}:
            extra_issues.append(
                IntegrityIssue(
                    "error",
                    "PROFILE_INVALID",
                    "profile must be quick, standard, or deep.",
                    "$.profile",
                )
            )
        issues = build.issues + tuple(extra_issues)
        book = EvidenceBook(
            build.items,
            build.sources,
            subject_id=str(build.company.get("ticker", "")),
        )
        capabilities = evaluate_capabilities(book, inputs)
        integrity_errors = tuple(issue for issue in issues if issue.severity == "error")
        if integrity_errors:
            capabilities = {
                name: replace(
                    result,
                    status="blocked",
                    explanation="Manifest identity, provenance, or time integrity failed; capability is fail-closed.",
                )
                for name, result in capabilities.items()
            }
            methods = self._blocked_methods(inputs)
        else:
            methods = route_methods(
                book,
                capabilities,
                build.company,
                inputs,
                as_of_date=request.as_of_date,
            )

        analysis, debate, synthesis, report_mode = build_professional_narrative(
            book,
            NarrativeInputs.from_research_inputs(inputs),
        )
        if integrity_errors:
            analysis = AnalysisBundle(
                dimensions={},
                completeness="blocked",
                missing_dimensions=tuple(analysis.dimensions),
            )
            debate = None
            synthesis = None
            report_mode = "audit_memo"
        elif inputs.report_version >= 3:
            report_capability = capabilities["research_report"]
            dimension_statuses = [item.status for item in analysis.dimensions.values()]
            if (
                synthesis is None
                or debate is None
                or not dimension_statuses
                or all(status == "blocked" for status in dimension_statuses)
            ):
                capabilities = {
                    **capabilities,
                    "research_report": replace(
                        report_capability,
                        status="blocked",
                        context_gaps=("professional_analysis_and_synthesis",),
                        explanation="V3 专业报告必须具备多维公司分析、证据约束质询和综合观点。",
                    ),
                }
            elif any(status != "ready" for status in dimension_statuses):
                capabilities = {
                    **capabilities,
                    "research_report": replace(
                        report_capability,
                        status="limited",
                        context_gaps=analysis.missing_dimensions,
                        explanation="V3 专业报告可生成，但部分分析维度只能形成有限判断。",
                    ),
                }

        permissions = self._permissions(
            integrity_errors=bool(integrity_errors),
            capabilities=capabilities,
            methods=methods,
        )
        status = self._status(
            integrity_errors=bool(integrity_errors),
            capabilities=capabilities,
            methods=methods,
        )
        run_id = self._run_id(request)
        summary = self._summary(
            book=book,
            inputs=inputs,
            capabilities=capabilities,
            methods=methods,
            issue_count=len(issues),
        )
        if forecast_graph is not None:
            summary = {
                **summary,
                "forecast_graph": {
                    "graph_id": forecast_graph.graph_id,
                    "template_id": forecast_graph.template_id,
                    "security_id": forecast_graph.security_id,
                    "data_snapshot_id": forecast_graph.data_snapshot_id,
                    "node_count": len(forecast_graph.nodes),
                    "edge_count": len(forecast_graph.edges),
                },
            }
        plan = self._conditional_plan(inputs, capabilities, methods)
        diagnostics = (
            *inputs.migration_diagnostics,
            *self._diagnostics(issues, capabilities, methods),
        )

        run = ResearchRun(
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            status=status,
            as_of_date=request.as_of_date,
            profile=request.profile,
            company=build.company,
            sources=build.sources,
            evidence=build.items,
            declared_missing=build.declared_missing,
            integrity_issues=issues,
            capabilities=capabilities,
            methods=methods,
            permissions=permissions,
            summary=summary,
            analysis=analysis,
            debate=debate,
            synthesis=synthesis,
            report_mode=report_mode,
            conditional_plan=plan,
            diagnostics=diagnostics,
        )

        if request.render_html:
            from .report import render_html_report

            run = replace(run, html=render_html_report(run))
        return run

    @staticmethod
    def _validate_forecast_fact_manifest(
        request: ResearchRequest,
        build: EvidenceBuild,
    ) -> None:
        if request.forecast_request is None:
            return
        source_by_id = {source.source_id: source for source in build.sources}
        for fact in request.forecast_request.data_snapshot.facts:
            source = source_by_id.get(fact.source_id)
            if (
                source is None
                or not source.official
                or source.available_at[:10] != fact.available_at
            ):
                raise ForecastInvariantError(
                    "FORECAST_FACT_MANIFEST_MISMATCH",
                    f"Forecast Fact {fact.fact_id} is not bound to its declared official manifest source.",
                )
            candidates = [
                item
                for item in build.items
                if item.source_id == fact.source_id
                and item.subject_id == fact.subject_id
                and item.field_name == fact.field_name
                and item.period == fact.period
                and item.unit == fact.unit
                and item.currency == fact.currency
                and item.official
                and not item.estimated
            ]
            matched = False
            for item in candidates:
                try:
                    value = exact_decimal_from_legacy(
                        item.value,
                        f"Forecast Fact {fact.fact_id}",
                    )
                except FinancialInvariantError:
                    continue
                if value == fact.value:
                    matched = True
                    break
            if not matched:
                raise ForecastInvariantError(
                    "FORECAST_FACT_MANIFEST_MISMATCH",
                    f"Forecast Fact {fact.fact_id} has no exact subject/PIT/dimension/value match in source_manifest.",
                )

    @staticmethod
    def _blocked_methods(inputs: ResearchInputs) -> dict[str, MethodResult]:
        specs = [
            ("observed_multiples", "市场观察倍数", "context"),
            ("peer_comps", "可比公司法", "relative_valuation"),
            ("historical_band", "历史估值带", "relative_to_self"),
            ("dcf", "DCF", "intrinsic_valuation"),
        ]
        if inputs.company_type.strip().lower() in {
            "cyclical",
            "cyclical_manufacturing",
            "resources",
            "commodity",
        }:
            specs.append(("mid_cycle", "中周期框架", "industry_specific"))
        return {
            method_id: MethodResult(
                method_id=method_id,
                label=label,
                status="blocked",
                role=role,
                explanation="Manifest identity, provenance, or time integrity failed; numeric method execution was skipped.",
            )
            for method_id, label, role in specs
        }

    @staticmethod
    def _run_id(request: ResearchRequest) -> str:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "as_of_date": request.as_of_date,
            "profile": request.profile,
            "manifest": request.manifest,
            "estimates": request.estimates,
            "context": request.context,
            "research_inputs": (
                request.research_inputs.identity_payload()
                if request.research_inputs is not None
                else None
            ),
            "forecast_request": (
                request.forecast_request.to_dict()
                if request.forecast_request is not None
                else None
            ),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"rr_{hashlib.sha256(encoded).hexdigest()[:16]}"

    @staticmethod
    def _permissions(
        *,
        integrity_errors: bool,
        capabilities: Mapping[str, Any],
        methods: Mapping[str, Any],
    ) -> dict[str, bool]:
        research_report = (
            not integrity_errors and capabilities["research_report"].status != "blocked"
        )
        conditional_plan = (
            not integrity_errors
            and capabilities["conditional_research_plan"].status != "blocked"
        )
        formal_methods = [
            methods[name]
            for name in ("dcf", "peer_comps", "historical_band")
            if name in methods and methods[name].status == "ready"
        ]
        formal_per_share = not integrity_errors and len(formal_methods) >= 2
        return {
            "research_report": research_report,
            "scenario_analysis": not integrity_errors
            and capabilities["financial_model"].status
            in {"ready", "limited", "ready_with_estimates"},
            "conditional_research_plan": conditional_plan,
            "formal_per_share_valuation": formal_per_share,
            "institution_style_rating": False,
            "personalized_investment_instruction": False,
        }

    @staticmethod
    def _status(
        *,
        integrity_errors: bool,
        capabilities: Mapping[str, Any],
        methods: Mapping[str, Any],
    ) -> str:
        if integrity_errors:
            return "blocked"
        limited_statuses = {
            "blocked",
            "limited",
            "ready_with_estimates",
            "caution",
            "disabled",
        }
        capability_limited = any(
            value.status in limited_statuses for value in capabilities.values()
        )
        method_limited = any(
            value.status in limited_statuses for value in methods.values()
        )
        return (
            "completed_with_limits"
            if capability_limited or method_limited
            else "completed"
        )

    @staticmethod
    def _summary(
        *,
        book: EvidenceBook,
        inputs: ResearchInputs,
        capabilities: Mapping[str, Any],
        methods: Mapping[str, Any],
        issue_count: int,
    ) -> dict[str, Any]:
        target_items = [
            item
            for item in book.items
            if not book.subject_id or item.subject_id == book.subject_id
        ]
        cross_subject_items = [
            item
            for item in book.items
            if book.subject_id and item.subject_id != book.subject_id
        ]
        sourced = [item for item in target_items if not item.estimated]
        official = [item for item in sourced if item.official]
        estimated = [item for item in target_items if item.estimated]
        core = capabilities["research_core"]
        score = 30.0 if issue_count == 0 else max(0.0, 30.0 - issue_count * 5)
        score += {
            "ready": 25.0,
            "limited": 20.0,
            "ready_with_estimates": 17.0,
            "blocked": 0.0,
        }.get(core.status, 0.0)
        if sourced:
            score += 25.0 * len(official) / len(sourced)
        available = sum(
            1
            for result in capabilities.values()
            if result.status in {"ready", "limited", "ready_with_estimates"}
        )
        score += 20.0 * available / max(len(capabilities), 1)
        score -= min(5.0, len(estimated) * 1.5)
        score = max(0.0, min(100.0, score))
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 65:
            grade = "C"
        else:
            grade = "D"

        executive = inputs.executive_summary
        if not executive:
            executive = (
                "现有证据可以形成结构化研究视图；每项估值方法和分析能力按自身输入独立评估。"
                if core.status != "blocked"
                else "基础研究字段尚不完整，当前输出聚焦证据缺口和下一步验证。"
            )

        return {
            "data_quality_score": round(score, 1),
            "data_quality_grade": grade,
            "executive_summary": executive,
            "evidence_counts": {
                "total": len(target_items),
                "sourced": len(sourced),
                "official": len(official),
                "secondary": len([item for item in sourced if not item.official]),
                "estimated": len(estimated),
                "cross_subject_method_evidence": len(cross_subject_items),
            },
            "capability_counts": {
                status: len(
                    [value for value in capabilities.values() if value.status == status]
                )
                for status in ("ready", "limited", "ready_with_estimates", "blocked")
            },
            "method_counts": {
                status: len(
                    [value for value in methods.values() if value.status == status]
                )
                for status in ("ready", "limited", "caution", "blocked", "disabled")
            },
            "theses": list(inputs.theses),
            "risks": list(inputs.risks),
            "catalysts": list(inputs.catalysts),
            "scenarios": (
                list(inputs.scenarios)
                if capabilities["financial_model"].status
                in {"ready", "limited", "ready_with_estimates"}
                else []
            ),
        }

    @staticmethod
    def _conditional_plan(
        inputs: ResearchInputs,
        capabilities: Mapping[str, Any],
        methods: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        plan: list[Mapping[str, Any]] = [
            dict(item) for item in inputs.conditional_plan
        ]

        existing_watch = {str(item.get("watch", "")) for item in plan}
        for method in methods.values():
            if method.status not in {"blocked", "disabled", "limited", "caution"}:
                continue
            missing = ", ".join(method.missing_fields) or "适用性或方法输入"
            watch = f"{method.label} 可用性"
            if watch in existing_watch:
                continue
            plan.append(
                {
                    "watch": watch,
                    "validation_trigger": f"补齐并验证：{missing}",
                    "invalidation": "输入仍不可审计、口径冲突或方法仍不适用",
                    "review_window": "相关官方披露或数据包更新后",
                }
            )
            existing_watch.add(watch)

        if not plan and capabilities["research_core"].status == "blocked":
            plan.append(
                {
                    "watch": "基础研究证据",
                    "validation_trigger": "补齐最新官方收入、利润、现金与债务字段",
                    "invalidation": "标的身份或官方披露仍无法确认",
                    "review_window": "证据补充后",
                }
            )
        elif not plan:
            plan.append(
                {
                    "watch": "核心经营与盈利质量复核",
                    "validation_trigger": "下一份官方定期报告延续收入、利润与现金流的一致性",
                    "invalidation": "核心经营指标显著偏离当前证据或出现未解决口径冲突",
                    "review_window": "下一份官方定期报告披露后",
                }
            )
        return tuple(plan)

    @staticmethod
    def _diagnostics(
        issues: tuple[Any, ...],
        capabilities: Mapping[str, Any],
        methods: Mapping[str, Any],
    ) -> tuple[str, ...]:
        diagnostics: list[str] = []
        diagnostics.extend(
            f"{issue.severity}:{issue.code}:{issue.path}" for issue in issues
        )
        diagnostics.extend(
            f"capability:{name}:{result.status}"
            for name, result in capabilities.items()
        )
        diagnostics.extend(
            f"method:{name}:{result.status}" for name, result in methods.items()
        )
        return tuple(diagnostics)
