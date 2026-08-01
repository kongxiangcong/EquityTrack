from __future__ import annotations

import html
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from trading_platform.research_view import ResearchDecisionView


VALUE_LEVEL_LABELS = {
    "basis_value": "企业价值",
    "equity_value": "股权价值",
    "per_share_value": "每股价值",
}
STORY_LABELS = {
    "what_happens": "未来会发生什么",
    "why_it_matters": "为什么重要",
    "transmission": "如何传导到经营与价值",
    "counterevidence": "反证与不确定性",
    "what_would_change_the_view": "什么会改变当前判断",
    "core_thesis": "核心故事",
    "variant_view": "市场可能忽略什么",
    "business_quality": "业务质量",
    "earnings_outlook": "盈利推演",
    "valuation_view": "估值视角",
    "valuation_guardrails": "估值边界与选择权",
    "risk_reward_summary": "潜在改善与主要约束",
    "key_uncertainties": "关键不确定性",
}
PRIMARY_STORY_KEYS = (
    "what_happens",
    "why_it_matters",
    "transmission",
    "counterevidence",
    "what_would_change_the_view",
)
SECONDARY_STORY_KEYS = tuple(
    key for key in STORY_LABELS if key not in PRIMARY_STORY_KEYS
)
VALUATION_STATUS_LABELS = {
    "ready": "可用",
    "limited": "有限",
    "unavailable": "不可用",
    "blocked": "已阻断",
}
VALUE_ORIGIN_LABELS = {
    "observed_official": "官方观测值",
    "observed_structured": "结构化观测值",
    "derived": "推导值",
    "estimated": "估算值",
    "assumption": "假设",
}




def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _quantity(value: Any) -> str:
    if isinstance(value, Mapping):
        raw = value.get("value")
        unit = value.get("unit") or ""
    else:
        raw = value
        unit = ""
    if raw is None:
        return "—"
    try:
        number = Decimal(str(raw))
        decimals = 4 if unit == "decimal" else 2
        rendered = format(number, f",.{decimals}f").rstrip("0").rstrip(".")
    except (InvalidOperation, ValueError):
        rendered = str(raw)
    suffix = "" if not unit or unit == "decimal" else f" {unit}"
    return _esc(f"{rendered}{suffix}")


def _percent(value: Any) -> str:
    raw = value.get("value") if isinstance(value, Mapping) else value
    if raw is None:
        return "—"
    try:
        rendered = format(Decimal(str(raw)) * 100, ",.1f")
    except (InvalidOperation, ValueError):
        return _esc(raw)
    return _esc(f"{rendered}%")


def _value_level_label(value: object, *, conditional: bool = False) -> str:
    label = VALUE_LEVEL_LABELS.get(str(value))
    if label is None:
        return "条件价值基准值" if conditional else "条件价值"
    return f"条件{label}基准值" if conditional else label


def _render_implied_expectations(items: object) -> str:
    if not isinstance(items, (list, tuple)):
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{_esc(item.get('scenario_label'))}</td>"
        f"<td>{_esc(item.get('metric_id'))}</td>"
        f"<td>{_percent(item.get('low'))}</td>"
        f"<td>{_percent(item.get('base'))}</td>"
        f"<td>{_percent(item.get('high'))}</td>"
        f"<td>{_esc(item.get('explanation'))}</td>"
        "</tr>"
        for item in items
        if isinstance(item, Mapping)
    )
    if not rows:
        return ""
    return (
        "<section><h2>当前价格隐含预期</h2>"
        "<p class='section-note'>Reverse DCF 只反推当前观察价值需要哪些经营与终值假设共同成立。</p>"
        "<div class='table-wrap'><table><thead><tr><th>情景</th><th>指标</th><th>低</th><th>基准</th><th>高</th><th>解释</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
    )


def _render_valuation_summary(view: ResearchDecisionView) -> str:
    valuation = view.valuation_view
    status = str(valuation.get("status", "blocked"))
    status_label = VALUATION_STATUS_LABELS.get(status, status)
    methods = valuation.get("methods")
    method_rows = "".join(
        "<tr>"
        f"<td>{_esc(item.get('label') or item.get('method_id'))}</td>"
        f"<td>{_esc(item.get('status'))}</td>"
        f"<td>{_esc(item.get('explanation'))}</td>"
        f"<td>{_esc('、'.join(str(value) for value in item.get('missing_fields', ())))}</td>"
        "</tr>"
        for item in (methods if isinstance(methods, (list, tuple)) else ())
        if isinstance(item, Mapping)
    )
    uncertainty_items = "".join(
        f"<li>{_esc(item)}</li>" for item in view.key_uncertainties
    )
    change_items = "".join(
        f"<li>{_esc(item)}</li>" for item in view.what_would_change_the_view
    )
    return (
        "<section><div class='section-head'><h2>研究摘要与估值边界</h2>"
        f"<span class='valuation-state state-{_esc(status)}'>估值状态：{_esc(status_label)}</span></div>"
        "<div class='decision-grid'>"
        "<article><h3>数据质量</h3>"
        f"<strong class='grade'>数据质量 {_esc(view.data_quality_grade)}</strong>"
        f"<p>{_esc(view.risk_reward_summary)}</p></article>"
        "<article><h3>估值视角</h3>"
        f"<p>{_esc(valuation.get('summary'))}</p>"
        f"<code>{_esc(valuation.get('reason_code'))}</code></article>"
        "<article><h3>关键不确定性</h3>"
        f"<ul>{uncertainty_items}</ul></article>"
        "<article><h3>什么会改变当前判断</h3>"
        f"<ul>{change_items}</ul></article></div>"
        "<h3>方法状态</h3><div class='table-wrap'><table><thead><tr>"
        "<th>方法</th><th>状态</th><th>解释</th><th>缺失输入</th>"
        f"</tr></thead><tbody>{method_rows or '<tr><td colspan=\"4\">当前没有可发布的估值方法。</td></tr>'}</tbody></table></div></section>"
    )


def _render_pipeline_status(audit: object) -> str:
    audit_value = audit if isinstance(audit, Mapping) else {}
    bundle = audit_value.get("evaluation_bundle")
    components = (
        bundle.get("components")
        if isinstance(bundle, Mapping)
        else None
    )
    if not isinstance(components, Mapping):
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{_esc(name)}</td>"
        f"<td>{_esc(item.get('status'))}</td>"
        f"<td>{_esc('；'.join(str(code) for code in item.get('reason_codes', ())))}</td>"
        f"<td>{_esc(len(item.get('source_member_ids', ())))}</td>"
        f"<td><code>{_esc(item.get('artifact_id'))}</code></td>"
        "</tr>"
        for name, item in components.items()
        if isinstance(item, Mapping)
    )
    return (
        "<section><h2>研究管线状态</h2>"
        "<p class='section-note'>各状态直接来自同一 ResearchEvaluationBundle，不在呈现层重算。</p>"
        "<div class='table-wrap'><table><thead><tr>"
        "<th>组件</th><th>状态</th><th>原因</th><th>来源成员数</th><th>Artifact</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div></section>"
    )


def _render_recent_trend(audit: object) -> str:
    audit_value = audit if isinstance(audit, Mapping) else {}
    component = audit_value.get("recent_trend_assessment")
    if not isinstance(component, Mapping):
        return ""
    assessment = component.get("assessment")
    if not isinstance(assessment, Mapping):
        return ""
    reason_codes = component.get("reason_codes", ())
    metrics = (
        ("收盘价", assessment.get("close")),
        ("SMA20", assessment.get("sma20")),
        ("SMA60", assessment.get("sma60")),
        ("五个交易日前 SMA20", assessment.get("sma20_five_sessions_prior")),
        ("近 20 个交易日低点", assessment.get("window_low_20")),
    )
    rows = "".join(
        f"<tr><td>{_esc(label)}</td><td>{_quantity(value)}</td></tr>"
        for label, value in metrics
    )
    return (
        "<section><div class='section-head'><h2>近期走势</h2>"
        f"<span class='valuation-state state-{_esc(component.get('status'))}'>"
        f"{_esc(component.get('status'))}</span></div>"
        "<p class='section-note'>仅描述冻结日线的观察结果，不构成预测或交易指令。</p>"
        "<div class='decision-grid'><article><h3>分类</h3>"
        f"<strong>{_esc(assessment.get('classification') or '不可用')}</strong>"
        f"<p>样本数：{_esc(assessment.get('observation_count'))}</p></article>"
        "<article><h3>原因</h3>"
        f"<code>{_esc('；'.join(str(code) for code in reason_codes))}</code>"
        "</article></div><div class='table-wrap'><table><thead><tr>"
        f"<th>指标</th><th>观测值</th></tr></thead><tbody>{rows}</tbody>"
        "</table></div></section>"
    )


def _render_simulation(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    status = str(value.get("status", "not_run"))
    result = value.get("result")
    result = result if isinstance(result, Mapping) else {}
    if status not in {"ready", "partial"}:
        label = "仿真已阻断" if status == "blocked" else "仿真未运行"
        return (
            "<section><div class='section-head'><h2>估值仿真</h2>"
            f"<span class='valuation-state state-{_esc(status)}'>{label}</span></div>"
            f"<p>{_esc(value.get('interpretation'))}</p>"
            f"<code>{_esc(value.get('reason_code'))}</code></section>"
        )
    quantiles = result.get("quantiles")
    quantile_rows = "".join(
        f"<tr><td>{_esc(key.upper())}</td><td>{_quantity(quantity)}</td></tr>"
        for key, quantity in (
            quantiles.items() if isinstance(quantiles, Mapping) else ()
        )
    )
    contribution_rows = "".join(
        f"<li><span>{_esc(item.get('assumption_id'))}</span><strong>{_percent(item.get('share'))}</strong></li>"
        for item in result.get("contributions", ())
        if isinstance(item, Mapping)
    )
    diagnostics = "".join(
        f"<li>{_esc(item)}</li>" for item in result.get("diagnostics", ())
    )
    level = _value_level_label(result.get("output_level"))
    convergence = (
        "已通过收敛门禁。"
        if result.get("converged")
        else "模拟受限，保留确定性情景。"
    )
    return (
        f"<section><h2>校准后的{_esc(level)}分布</h2>"
        f"<p class='section-note'>{convergence} {_esc(value.get('interpretation'))}</p>"
        "<div class='distribution-grid'><div class='table-wrap'><table><thead><tr><th>分位数</th><th>条件值</th></tr></thead>"
        f"<tbody>{quantile_rows}</tbody></table></div>"
        f"<div><h3>关键变量贡献</h3><ul class='metric-list'>{contribution_rows or '<li>当前未发布贡献度。</li>'}</ul></div></div>"
        f"<details class='model-details'><summary>展开模拟诊断</summary><ul>{diagnostics or '<li>无额外诊断。</li>'}</ul></details></section>"
    )


def _render_market_paths(value: object, divergence: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    status = str(value.get("status", "not_run"))
    result = value.get("result")
    result = result if isinstance(result, Mapping) else {}
    if status not in {"ready", "partial"}:
        label = "路径已阻断" if status == "blocked" else "路径未运行"
        return (
            "<section><div class='section-head'><h2>市场价格路径</h2>"
            f"<span class='valuation-state state-{_esc(status)}'>{label}</span></div>"
            f"<p>{_esc(value.get('interpretation'))}</p>"
            f"<code>{_esc(value.get('reason_code'))}</code></section>"
        )
    terminal = result.get("terminal_price_quantiles")
    terminal_rows = "".join(
        f"<tr><td>终点 {_esc(key.upper())}</td><td>{_quantity(quantity)}</td></tr>"
        for key, quantity in (
            terminal.items() if isinstance(terminal, Mapping) else ()
        )
    )
    returns = result.get("horizon_return_quantiles")
    drawdowns = result.get("maximum_drawdown_quantiles")
    return_p50 = returns.get("p50") if isinstance(returns, Mapping) else None
    drawdown_p50 = (
        drawdowns.get("p50") if isinstance(drawdowns, Mapping) else None
    )
    divergence_text = (
        divergence.get("explanation")
        if isinstance(divergence, Mapping)
        else ""
    )
    return (
        "<section><h2>状态条件下的市场价格与回撤分布</h2>"
        f"<p>{_esc(value.get('interpretation'))}</p>"
        f"<p class='section-note'>{_esc(divergence_text)}</p>"
        "<div class='distribution-grid'><div class='table-wrap'><table><thead><tr><th>分位数</th><th>市场价格</th></tr></thead>"
        f"<tbody>{terminal_rows}</tbody></table></div><div><h3>期限风险</h3>"
        f"<ul class='metric-list'><li><span>P50 期限收益</span><strong>{_percent(return_p50)}</strong></li>"
        f"<li><span>P50 最大回撤</span><strong>{_percent(drawdown_p50)}</strong></li></ul></div></div></section>"
    )


def _render_metric_rows(items: object) -> str:
    if not isinstance(items, (list, tuple)):
        return ""
    return "".join(
        "<tr>"
        f"<td>{_esc(item.get('label') or item.get('metric_id'))}</td>"
        f"<td>{_esc(item.get('metric_id'))}</td>"
        f"<td>{_quantity(item)}</td>"
        f"<td>{_esc(item.get('period'))}</td>"
        "</tr>"
        for item in items
        if isinstance(item, Mapping)
    )


def _scenario_display_quantity(point: object) -> object:
    if not isinstance(point, Mapping):
        return point
    for key in ("per_share_value", "equity_value", "basis_value"):
        candidate = point.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return point


def _render_scenarios(value: object) -> str:
    if not isinstance(value, (list, tuple)):
        return ""
    sections: list[str] = []
    for scenario in value:
        if not isinstance(scenario, Mapping):
            continue
        method_rows = ""
        for method in scenario.get("methods", ()):
            if not isinstance(method, Mapping):
                continue
            value_range = method.get("conditional_value_range")
            points = value_range if isinstance(value_range, Mapping) else {}
            diagnostics = (
                method.get("display_diagnostics")
                or method.get("diagnostics")
            )
            diagnostic_text = (
                "；".join(str(item) for item in diagnostics)
                if isinstance(diagnostics, (list, tuple))
                else ""
            )
            method_rows += (
                "<tr>"
                f"<td>{_esc(method.get('method_id'))}</td>"
                f"<td>{_esc(method.get('status'))}</td>"
                f"<td>{_esc(method.get('display_applicability') or method.get('applicability'))}</td>"
                f"<td>{_esc(_value_level_label(method.get('display_value_level') or method.get('value_basis'), conditional=True))}</td>"
                f"<td>{_quantity(_scenario_display_quantity(points.get('low')))}</td>"
                f"<td>{_quantity(_scenario_display_quantity(points.get('base')))}</td>"
                f"<td>{_quantity(_scenario_display_quantity(points.get('high')))}</td>"
                f"<td>{_esc(method.get('horizon'))}</td>"
                f"<td>{_esc(diagnostic_text)}</td>"
                "</tr>"
            )
        driver_rows = _render_metric_rows(scenario.get("drivers"))
        financial_rows = _render_metric_rows(scenario.get("financials"))
        sections.append(
            f"<section><div class='section-head'><h2>{_esc(scenario.get('label'))}情景</h2>"
            f"<span>{_esc(scenario.get('terminal_period'))}</span></div>"
            "<div class='scenario-evidence'><div><h3>情景 Driver</h3>"
            "<div class='table-wrap'><table><thead><tr><th>指标</th><th>ID</th><th>数值</th><th>期间</th></tr></thead>"
            f"<tbody>{driver_rows}</tbody></table></div></div>"
            "<div><h3>关键财务结果</h3><div class='table-wrap'><table><thead><tr><th>指标</th><th>ID</th><th>数值</th><th>期间</th></tr></thead>"
            f"<tbody>{financial_rows}</tbody></table></div></div></div>"
            "<h3>方法级条件价值区间</h3><div class='table-wrap'><table><thead><tr>"
            "<th>方法</th><th>状态</th><th>适用性</th><th>价值层级</th><th>条件低值</th><th>条件基准值</th><th>条件高值</th><th>期限</th><th>诊断</th>"
            f"</tr></thead><tbody>{method_rows}</tbody></table></div></section>"
        )
    return "".join(sections)


def _audit_json(value: object) -> str:
    return _esc(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )


def _render_audit(audit: object) -> str:
    value = audit if isinstance(audit, Mapping) else {}
    artifacts = value.get("artifact_records", ())
    artifact_rows = "".join(
        "<tr>"
        f"<td>{_esc(item.get('artifact_kind'))}</td>"
        f"<td>{_esc(item.get('schema_version'))}</td>"
        f"<td><code>{_esc(item.get('content_hash'))}</code></td>"
        f"<td>{_esc(item.get('status'))}</td>"
        "</tr>"
        for item in artifacts
        if isinstance(item, Mapping)
    )
    groups = (
        ("评估 Bundle", value.get("evaluation_bundle", {})),
        ("Forecast", value.get("forecast", {})),
        ("估值方法路由", value.get("valuation_method_route", {})),
        ("近期走势", value.get("recent_trend_assessment", {})),
        ("事实与证据", value.get("fact_evidence", ())),
        ("公式身份", value.get("formula_identities", ())),
        ("研究摘要", value.get("research_summary", {})),
        (
            "分析与综合",
            {"analysis": value.get("analysis", {}), "synthesis": value.get("synthesis", {})},
        ),
        ("估值方法", value.get("methods", {})),
        ("模型参数", value.get("parameters", {})),
        ("来源注册", value.get("sources", ())),
        (
            "版本与权限",
            {
                "versions": value.get("versions", {}),
                "permissions": value.get("permissions", {}),
            },
        ),
        (
            "诊断与缺口",
            {
                "diagnostics": value.get("diagnostics", ()),
                "declared_missing": value.get("declared_missing", ()),
                "integrity_issues": value.get("integrity_issues", ()),
                "simulation_decision": value.get("simulation_decision", {}),
                "market_path_decision": value.get("market_path_decision", {}),
            },
        ),
    )
    group_html = "".join(
        f"<details class='audit-group'><summary>{_esc(label)}</summary><pre>{_audit_json(content)}</pre></details>"
        for label, content in groups
    )
    return (
        '<section class="audit-shell"><details class="audit-appendix">'
        "<summary><span>审计附录</span><small>来源、公式、参数、版本与诊断</small></summary>"
        "<div class='table-wrap'><table><thead><tr><th>Artifact</th><th>Schema</th><th>Hash</th><th>状态</th></tr></thead>"
        f"<tbody>{artifact_rows}</tbody></table></div><div class='audit-groups'>{group_html}</div>"
        "</details></section>"
    )


def _render_story_cards(story: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    cards: list[str] = []
    for key in keys:
        value = story.get(key, ())
        if not isinstance(value, (str, list, tuple)) or not value:
            continue
        items = value if isinstance(value, (list, tuple)) else (value,)
        class_name = " class='story-lead'" if key == "what_happens" else ""
        cards.append(
            f"<article{class_name}><h3>{_esc(STORY_LABELS[key])}</h3><ul>"
            + "".join(f"<li>{_esc(item)}</li>" for item in items)
            + "</ul></article>"
        )
    return "".join(cards)


def _render_estimate_boundary(item: Mapping[str, Any]) -> str:
    metadata = item.get("estimate_metadata")
    if not isinstance(metadata, Mapping) or not metadata:
        return "—"
    lower = metadata.get("lower_bound")
    upper = metadata.get("upper_bound")
    summary = (
        f"{lower} – {upper}"
        if lower is not None and upper is not None
        else "查看估算边界"
    )
    policy = metadata.get("range_policy") or metadata.get("policy")
    basis_sources = metadata.get("basis_sources")
    basis = (
        "、".join(str(value) for value in basis_sources)
        if isinstance(basis_sources, (list, tuple))
        else ""
    )
    details = "<br>".join(
        value
        for value in (
            f"<code>{_esc(policy)}</code>" if policy else "",
            f"<small>依据：{_esc(basis)}</small>" if basis else "",
            (
                f"<small>{_esc(metadata.get('rationale'))}</small>"
                if metadata.get("rationale")
                else ""
            ),
            (
                "<small>失效条件："
                f"{_esc(metadata.get('invalidation_condition'))}</small>"
                if metadata.get("invalidation_condition")
                else ""
            ),
        )
        if value
    )
    return f"<details><summary>{_esc(summary)}</summary>{details}</details>"


def render_research_decision_html(
    view: ResearchDecisionView,
) -> str:
    """Render the canonical decision-first view without recalculating it."""

    payload = view.to_dict()
    story = view.story
    scenarios = view.scenarios
    drivers = view.key_drivers
    audit = view.audit
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    primary_story_blocks = _render_story_cards(story, PRIMARY_STORY_KEYS)
    secondary_story_blocks = _render_story_cards(story, SECONDARY_STORY_KEYS)
    valuation_summary_section = _render_valuation_summary(view)
    pipeline_status_section = _render_pipeline_status(audit)
    recent_trend_section = _render_recent_trend(audit)
    driver_rows = "".join(
        "<tr>"
        f"<td><strong>{_esc(item.get('label') or item.get('metric_id'))}</strong><br><code>{_esc(item.get('metric_id'))}</code></td>"
        f"<td>{_quantity(item)}</td>"
        f"<td>{_esc(VALUE_ORIGIN_LABELS.get(str(item.get('value_origin')), item.get('value_origin') or '未标注'))}</td>"
        f"<td>{_esc(item.get('period'))}</td>"
        f"<td>{_render_estimate_boundary(item)}</td>"
        f"<td><code>{_esc(item.get('evidence_id'))}</code></td>"
        "</tr>"
        for item in drivers
        if isinstance(item, Mapping)
    )
    scenario_sections = _render_scenarios(scenarios)
    implied_section = _render_implied_expectations(
        payload.get("market_implied_expectations")
    )
    simulation_section = _render_simulation(payload.get("valuation_simulation"))
    market_path_section = _render_market_paths(
        payload.get("market_price_paths"),
        payload.get("value_market_divergence"),
    )
    audit_section = _render_audit(audit)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(payload.get('subject_id'))} · 公司未来推演</title>
<style>
:root{{--ink:#16242d;--muted:#667984;--line:#dce4e8;--paper:#fff;--bg:#eef3f5;--accent:#176b87;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,"Microsoft YaHei",sans-serif}}
main{{width:min(1180px,calc(100% - 28px));margin:26px auto;background:var(--paper);border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 18px 50px rgba(20,45,58,.1)}}
header{{padding:42px;background:linear-gradient(135deg,#123b4e,#1d7187);color:#fff}}header h1{{margin:6px 0;font-size:clamp(28px,5vw,48px)}}header p{{margin:0;color:#dcecf1}}
section{{padding:30px 40px;border-bottom:1px solid var(--line)}}.story{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}article{{padding:18px;border:1px solid var(--line);border-radius:14px;background:#fbfdfe}}article h3{{margin-top:0}}ul{{padding-left:18px}}
.section-head{{display:flex;justify-content:space-between;gap:16px;align-items:baseline}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:12px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{background:#f3f7f8;color:var(--muted)}}code{{font-size:11px;word-break:break-all}}footer{{padding:22px 40px;color:var(--muted)}}
.decision-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin-bottom:22px}}.grade{{font-size:1.6rem;color:var(--accent)}}.valuation-state{{display:inline-block;padding:5px 10px;border-radius:999px;background:#e7f1f4;color:#174e60;font-weight:700}}.state-blocked{{background:#f9e4e4;color:#8a2929}}.state-unavailable{{background:#f4eee2;color:#725313}}
.story .story-lead{{grid-column:1/-1;background:#123b4e;color:#fff;border-color:#123b4e}}.story-details{{margin-top:18px}}.story-details>summary{{cursor:pointer;font-weight:600}}.story-details[open]>summary{{margin-bottom:14px}}.section-note{{color:var(--muted)}}.distribution-grid,.scenario-evidence{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;align-items:start}}.metric-list{{list-style:none;padding:0}}.metric-list li{{display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-bottom:1px solid var(--line)}}.model-details{{margin-top:18px}}.model-details summary{{cursor:pointer;font-weight:600}}.audit-shell{{padding-top:20px;padding-bottom:20px}}.audit-appendix>summary{{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;cursor:pointer;font-size:1.25rem;font-weight:700;list-style-position:inside}}.audit-appendix summary small{{color:var(--muted);font-size:.78rem;font-weight:400}}.audit-appendix summary:focus-visible,.model-details summary:focus-visible,.audit-group summary:focus-visible,.story-details summary:focus-visible{{outline:3px solid var(--accent);outline-offset:5px;border-radius:4px}}.audit-appendix[open]>summary{{margin-bottom:16px}}.audit-groups{{display:grid;gap:8px;margin-top:16px}}.audit-group{{border:1px solid var(--line);border-radius:10px;padding:10px 12px}}.audit-group summary{{cursor:pointer;font-weight:600}}pre{{max-height:420px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f7f8;border-radius:8px;padding:12px}}
@media(max-width:640px){{header,section,footer{{padding-left:20px;padding-right:20px}}}}
@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important;animation:none!important;transition:none!important}}}}
</style></head><body><main>
<header><small>{_esc(payload.get('schema_version'))} · {_esc(payload.get('as_of'))}</small>
<h1>{_esc(payload.get('subject_id'))} 公司未来推演</h1>
<p>故事、证据指标、方法状态和估值边界来自同一冻结数据快照与不可变研究运行。</p></header>
<section><h2>未来故事</h2><div class="story">{primary_story_blocks or '<p>当前研究运行未形成可展示故事。</p>'}</div><details class="story-details"><summary>补充公司叙事与估值上下文</summary><div class="story">{secondary_story_blocks or '<p>当前没有额外补充叙事。</p>'}</div></details></section>
{valuation_summary_section}
{pipeline_status_section}
{recent_trend_section}
<section><h2>关键证据指标</h2><div class="table-wrap"><table><thead><tr><th>指标</th><th>数值</th><th>来源类型</th><th>期间</th><th>估算边界</th><th>证据</th></tr></thead><tbody>{driver_rows or '<tr><td colspan="6">当前没有可展示的证据指标。</td></tr>'}</tbody></table></div></section>
{scenario_sections}
{implied_section}
{simulation_section}
{market_path_section}
{audit_section}
<footer>{_esc(payload.get('boundary'))}</footer>
</main><script type="application/json" id="research-decision-view">{canonical}</script></body></html>"""
