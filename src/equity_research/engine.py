from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Mapping

from .evidence import EvidenceBook, build_evidence
from .models import IntegrityIssue, MethodResult, ResearchRequest, ResearchRun
from .output_policy import normalize_action_language
from .policies import evaluate_capabilities
from .valuation import route_methods


SCHEMA_VERSION = 2

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


class ResearchEngine:
    """Deep deterministic module behind the research workflow seam."""

    def run(self, request: ResearchRequest) -> ResearchRun:
        normalized_context, policy_issues = _normalize_context_language(
            request.context or {}
        )
        context: Mapping[str, Any] = normalized_context
        build = build_evidence(
            request.manifest,
            request.estimates,
            as_of_date=request.as_of_date,
        )
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
        capabilities = evaluate_capabilities(book, context)
        integrity_errors = tuple(
            issue for issue in issues if issue.severity == "error"
        )
        if integrity_errors:
            capabilities = {
                name: replace(
                    result,
                    status="blocked",
                    explanation="Manifest identity, provenance, or time integrity failed; capability is fail-closed.",
                )
                for name, result in capabilities.items()
            }
            methods = self._blocked_methods(context)
        else:
            methods = route_methods(
                book,
                capabilities,
                build.company,
                context,
                as_of_date=request.as_of_date,
            )

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
            context=context,
            capabilities=capabilities,
            methods=methods,
            issue_count=len(issues),
        )
        plan = self._conditional_plan(context, capabilities, methods)
        diagnostics = self._diagnostics(issues, capabilities, methods)

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
            conditional_plan=plan,
            diagnostics=diagnostics,
        )

        if request.render_html:
            from .report import render_html_report

            run = replace(run, html=render_html_report(run))
        return run

    @staticmethod
    def _blocked_methods(context: Mapping[str, Any]) -> dict[str, MethodResult]:
        specs = [
            ("observed_multiples", "市场观察倍数", "context"),
            ("peer_comps", "可比公司法", "relative_valuation"),
            ("historical_band", "历史估值带", "relative_to_self"),
            ("dcf", "DCF", "intrinsic_valuation"),
        ]
        if str(context.get("company_type", "")).strip().lower() in {
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
            not integrity_errors
            and capabilities["research_report"].status != "blocked"
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
        limited_statuses = {"blocked", "limited", "ready_with_estimates", "caution", "disabled"}
        capability_limited = any(
            value.status in limited_statuses for value in capabilities.values()
        )
        method_limited = any(value.status in limited_statuses for value in methods.values())
        return "completed_with_limits" if capability_limited or method_limited else "completed"

    @staticmethod
    def _summary(
        *,
        book: EvidenceBook,
        context: Mapping[str, Any],
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

        executive = str(context.get("executive_summary", "")).strip()
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
                status: len([value for value in capabilities.values() if value.status == status])
                for status in ("ready", "limited", "ready_with_estimates", "blocked")
            },
            "method_counts": {
                status: len([value for value in methods.values() if value.status == status])
                for status in ("ready", "limited", "caution", "blocked", "disabled")
            },
            "theses": list(context.get("theses", [])) if isinstance(context.get("theses", []), list) else [],
            "risks": list(context.get("risks", [])) if isinstance(context.get("risks", []), list) else [],
            "catalysts": list(context.get("catalysts", [])) if isinstance(context.get("catalysts", []), list) else [],
            "scenarios": (
                list(context.get("scenarios", []))
                if capabilities["financial_model"].status
                in {"ready", "limited", "ready_with_estimates"}
                and isinstance(context.get("scenarios", []), list)
                else []
            ),
        }

    @staticmethod
    def _conditional_plan(
        context: Mapping[str, Any],
        capabilities: Mapping[str, Any],
        methods: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        raw = context.get("conditional_plan", [])
        plan: list[Mapping[str, Any]] = [
            dict(item) for item in raw if isinstance(item, Mapping)
        ] if isinstance(raw, list) else []

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
