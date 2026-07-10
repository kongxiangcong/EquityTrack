from __future__ import annotations

import html
import json
from typing import Any, Iterable, Mapping

from .evidence import numeric_value, period_rank
from .models import EvidenceItem, ResearchRun


STATUS_LABELS = {
    "ready": "可用",
    "limited": "有限可用",
    "ready_with_estimates": "估算情景可用",
    "caution": "谨慎交叉检查",
    "blocked": "输入不足",
    "disabled": "方法不适用",
    "completed": "研究完成",
    "completed_with_limits": "研究完成 · 能力受限",
}


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _json_for_html(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).replace("</", "<\\/")


def _best_item(run: ResearchRun, field_name: str, *, full_year: bool = False) -> EvidenceItem | None:
    subject_id = str(run.company.get("ticker", ""))
    items = [
        item
        for item in run.evidence
        if item.field_name == field_name
        and not item.estimated
        and (not subject_id or item.subject_id == subject_id)
    ]
    if field_name not in {"current_price", "market_cap", "fx_rate"}:
        items = [item for item in items if item.official]
    if full_year:
        items = [
            item
            for item in items
            if "FY" in item.period.upper() or "ANNUAL" in item.period.upper()
        ]
    if not items:
        return None
    return max(items, key=lambda item: (period_rank(item.period), item.official, item.confidence == "high"))


def _format_value(item: EvidenceItem | None) -> str:
    if item is None:
        return "—"
    value = item.value
    if isinstance(value, Mapping):
        for key in (
            f"total_{item.field_name}",
            "total_depreciation_and_amortization",
            "total_lease_liability",
            "total",
        ):
            if key in value:
                value = value[key]
                break
    number = numeric_value(value)
    if number is None:
        return esc(value)
    unit = item.unit.lower()
    if "share" in unit and abs(number) >= 1_000_000:
        return f"{number / 100_000_000:.2f} 亿股"
    if "/share" in unit:
        return f"{number:,.2f} {esc(item.currency)}/股"
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:,.2f} 亿元"
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:,.1f} 百万元"
    if abs(number) >= 1_000:
        return f"{number:,.0f}"
    return f"{number:,.2f}"


def _status_badge(status: str) -> str:
    label = STATUS_LABELS.get(status, status)
    return f'<span class="status status-{esc(status)}">{esc(label)}</span>'


def _evidence_refs(run: ResearchRun, fields: Iterable[str]) -> str:
    refs: list[str] = []
    for field_name in fields:
        item = _best_item(run, field_name)
        if item and item.evidence_id not in refs:
            refs.append(item.evidence_id)
    if not refs:
        return ""
    return f'<span class="evidence-ref">证据 {esc(", ".join(refs))}</span>'


def _capability_svg(run: ResearchRun) -> str:
    rows = list(run.capabilities.values())
    width = 980
    row_h = 38
    height = 36 + row_h * len(rows)
    scores = {
        "ready": 1.0,
        "limited": 0.72,
        "ready_with_estimates": 0.58,
        "blocked": 0.16,
    }
    colors = {
        "ready": "#26a269",
        "limited": "#d69e2e",
        "ready_with_estimates": "#7c6ee6",
        "blocked": "#d95763",
    }
    parts = [
        f'<svg class="viz" viewBox="0 0 {width} {height}" role="img" aria-label="能力可用性概览">',
        '<text x="0" y="18" class="svg-title">能力可用性不是总开关</text>',
    ]
    for index, result in enumerate(rows):
        y = 38 + index * row_h
        bar_x = 230
        bar_w = 650
        fill_w = max(12, int(bar_w * scores.get(result.status, 0.1)))
        color = colors.get(result.status, "#8995a3")
        parts.extend(
            [
                f'<text x="0" y="{y + 18}" class="svg-label">{esc(result.label)}</text>',
                f'<rect x="{bar_x}" y="{y + 4}" width="{bar_w}" height="18" rx="9" fill="var(--chart-track)"/>',
                f'<rect x="{bar_x}" y="{y + 4}" width="{fill_w}" height="18" rx="9" fill="{color}"/>',
                f'<text x="{bar_x + bar_w + 12}" y="{y + 18}" class="svg-value">{esc(STATUS_LABELS.get(result.status, result.status))}</text>',
            ]
        )
    parts.append("</svg>")
    return "".join(parts)


def _financial_svg(run: ResearchRun) -> str:
    series_specs = (
        ("revenue", "营业收入", "#3b82f6"),
        ("net_income", "归母净利润", "#26a269"),
        ("cfo", "经营现金流", "#d69e2e"),
    )
    subject_id = str(run.company.get("ticker", ""))
    period_set = {
        item.period
        for item in run.evidence
        if item.official
        and not item.estimated
        and (not subject_id or item.subject_id == subject_id)
        and item.field_name in {spec[0] for spec in series_specs}
    }
    periods = sorted(period_set, key=period_rank)
    if not periods:
        return '<svg class="viz" viewBox="0 0 980 180"><text x="30" y="90" class="svg-label">暂无可绘制财务序列</text></svg>'
    width, height = 980, 390
    left, right = 140, 40
    chart_w = width - left - right
    panel_h = 94
    parts = [
        f'<svg class="viz" viewBox="0 0 {width} {height}" role="img" aria-label="多期财务指标小图">',
        '<text x="0" y="20" class="svg-title">财务事实序列 · 各指标独立刻度</text>',
    ]
    for panel_index, (field_name, label, color) in enumerate(series_specs):
        panel_top = 46 + panel_index * 108
        values: list[float | None] = []
        item_ids: list[str] = []
        for period in periods:
            candidates = [
                item
                for item in run.evidence
                if item.field_name == field_name
                and item.period == period
                and item.official
                and not item.estimated
                and (not subject_id or item.subject_id == subject_id)
            ]
            if candidates:
                item = max(candidates, key=lambda candidate: (candidate.official, candidate.confidence == "high"))
                values.append(numeric_value(item.value))
                item_ids.append(item.evidence_id)
            else:
                values.append(None)
        numeric = [value for value in values if value is not None]
        min_value = min([0.0] + numeric)
        max_value = max([0.0] + numeric)
        span = max_value - min_value or 1.0
        plot_top = panel_top + 12
        plot_h = 62
        zero_y = plot_top + (max_value / span) * plot_h
        parts.append(f'<text x="0" y="{panel_top + 44}" class="svg-label strong">{esc(label)}</text>')
        parts.append(f'<line x1="{left}" y1="{zero_y:.1f}" x2="{left + chart_w}" y2="{zero_y:.1f}" stroke="var(--chart-grid)"/>')
        points: list[str] = []
        for index, (period, value) in enumerate(zip(periods, values)):
            x = left + (chart_w * index / max(len(periods) - 1, 1))
            if value is not None:
                y = plot_top + ((max_value - value) / span) * plot_h
                points.append(f"{x:.1f},{y:.1f}")
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>')
                display = f"{value / 100_000_000:.2f}亿" if abs(value) >= 100_000_000 else f"{value / 1_000_000:.1f}百万"
                label_y = y - 10 if value >= 0 else y + 17
                parts.append(f'<text x="{x:.1f}" y="{label_y:.1f}" text-anchor="middle" class="svg-value">{esc(display)}</text>')
            if panel_index == 2:
                parts.append(f'<text x="{x:.1f}" y="{panel_top + panel_h + 22}" text-anchor="middle" class="svg-axis">{esc(period)}</text>')
        frequencies = {
            "annual" if "FY" in period.upper() or "ANNUAL" in period.upper() else "interim"
            for period, value in zip(periods, values)
            if value is not None
        }
        if len(points) >= 2 and len(frequencies) == 1:
            parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    parts.append("</svg>")
    return "".join(parts)


def _risk_svg(risks: list[Any]) -> str:
    width, height = 760, 420
    left, bottom, top, right = 74, 58, 34, 52
    chart_w, chart_h = width - left - right, height - top - bottom
    parts = [
        f'<svg class="viz risk-viz" viewBox="0 0 {width} {height}" role="img" aria-label="风险矩阵">',
        '<text x="0" y="18" class="svg-title">风险矩阵 · 发生可能性 × 影响</text>',
    ]
    for index in range(5):
        x = left + chart_w * index / 4
        y = top + chart_h * index / 4
        parts.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top + chart_h}" stroke="var(--chart-grid)"/>')
        parts.append(f'<line x1="{left}" y1="{y}" x2="{left + chart_w}" y2="{y}" stroke="var(--chart-grid)"/>')
        parts.append(f'<text x="{x}" y="{top + chart_h + 24}" text-anchor="middle" class="svg-axis">{index + 1}</text>')
        parts.append(f'<text x="{left - 18}" y="{top + chart_h - chart_h * index / 4 + 4}" text-anchor="middle" class="svg-axis">{index + 1}</text>')
    parts.append(f'<text x="{left + chart_w / 2}" y="{height - 5}" text-anchor="middle" class="svg-label">发生可能性 →</text>')
    parts.append(f'<text x="16" y="{top + chart_h / 2}" text-anchor="middle" transform="rotate(-90 16 {top + chart_h / 2})" class="svg-label">影响 →</text>')
    palette = ("#3b82f6", "#d69e2e", "#d95763", "#7c6ee6", "#26a269")
    occupied: dict[tuple[float, float], int] = {}
    for index, risk in enumerate(risks):
        if not isinstance(risk, Mapping):
            continue
        likelihood = max(1.0, min(5.0, float(risk.get("likelihood", 3))))
        impact = max(1.0, min(5.0, float(risk.get("impact", 3))))
        x = left + chart_w * (likelihood - 1) / 4
        y = top + chart_h - chart_h * (impact - 1) / 4
        position_key = (likelihood, impact)
        overlap_index = occupied.get(position_key, 0)
        occupied[position_key] = overlap_index + 1
        if overlap_index:
            x += 14 * overlap_index
            y += 14 * overlap_index
        title = str(risk.get("title", f"风险 {index + 1}"))
        color = palette[index % len(palette)]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="12" fill="{color}" opacity=".88"><title>{esc(title)}</title></circle>')
        parts.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" class="risk-index">{index + 1}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _table(headers: Iterable[str], rows: Iterable[Iterable[Any]], *, classes: str = "") -> str:
    head = "".join(f"<th>{esc(value)}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{value if isinstance(value, _SafeHtml) else esc(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table class="{esc(classes)}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


class _SafeHtml(str):
    pass


def _method_metrics(method: Any, *, allow_per_share: bool) -> str:
    metrics = dict(method.metrics)
    if not metrics:
        return ""
    rows: list[tuple[str, str]] = []
    if "price_to_reported_fy_eps" in metrics:
        rows.append(("价格 / 已报告年度 EPS", f"{metrics['price_to_reported_fy_eps']:.1f}×"))
    if "market_cap_to_reported_fy_revenue" in metrics:
        rows.append(("市值 / 已报告年度收入", f"{metrics['market_cap_to_reported_fy_revenue']:.2f}×"))
    if "enterprise_value" in metrics:
        rows.extend(
            [
                ("企业价值", f"{metrics['enterprise_value']:,.2f}"),
                ("股权价值", f"{metrics['equity_value']:,.2f}"),
                ("终值现值占比", f"{metrics['terminal_value_share_of_enterprise_value']:.1%}"),
            ]
        )
        if allow_per_share:
            rows.append(("每股结果", f"{metrics['equity_value_per_share']:,.2f}"))
    if "peer_median_multiple" in metrics:
        rows.extend(
            [
                ("可用同业", str(metrics.get("peer_count", 0))),
                ("同业中位倍数", f"{metrics['peer_median_multiple']:.2f}×"),
            ]
        )
        if allow_per_share:
            rows.append(("中位每股映射", f"{metrics['implied_per_share_median']:,.2f}"))
    if "current_percentile" in metrics:
        rows.extend(
            [
                ("历史观察数", str(metrics.get("observations", 0))),
                ("历史中位数", f"{metrics['median']:.2f}×"),
                ("当前分位", f"{metrics['current_percentile']:.1%}"),
            ]
        )
    if not rows:
        return ""
    return '<dl class="mini-metrics">' + "".join(
        f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>" for label, value in rows
    ) + "</dl>"


def _method_assumptions(method: Any) -> str:
    assumptions = dict(method.assumptions)
    if not assumptions:
        return ""
    payload = json.dumps(assumptions, ensure_ascii=False, indent=2, default=str)
    return (
        '<details class="assumption-details"><summary>方法假设</summary>'
        f'<pre>{esc(payload)}</pre></details>'
    )


def _dcf_sensitivity(run: ResearchRun) -> str:
    if not run.permissions.get("formal_per_share_valuation", False):
        return ""
    dcf = run.methods.get("dcf")
    if not dcf or "sensitivity" not in dcf.metrics:
        return ""
    sensitivity = dcf.metrics["sensitivity"]
    if not isinstance(sensitivity, list) or not sensitivity:
        return ""
    waccs = sorted({float(item["wacc"]) for item in sensitivity})
    growths = sorted({float(item["terminal_growth"]) for item in sensitivity})
    lookup = {
        (float(item["wacc"]), float(item["terminal_growth"])): item.get("equity_value_per_share")
        for item in sensitivity
    }
    rows = []
    for wacc in waccs:
        cells: list[Any] = [f"{wacc:.1%}"]
        for growth in growths:
            value = lookup[(wacc, growth)]
            cells.append("—" if value is None else f"{float(value):,.2f}")
        rows.append(cells)
    return (
        '<div class="subsection"><h3>DCF 敏感性</h3>'
        + _table(["WACC / g"] + [f"{value:.1%}" for value in growths], rows, classes="sensitivity")
        + '<p class="caption">矩阵仅在显式 DCF case 通过金融 invariant 后出现。</p></div>'
    )


def _render_data_insufficient_memo(run: ResearchRun) -> str:
    company_name = run.company.get("name", "未确认公司")
    ticker = run.company.get("ticker", "—")
    issue_rows = [
        [issue.severity, issue.code, issue.path, issue.message]
        for issue in run.integrity_issues
    ]
    gap_rows = [
        [
            item.get("field_name", ""),
            item.get("affected_outputs", ""),
            item.get("why_missing", ""),
            item.get("next_required_evidence", ""),
        ]
        for item in run.declared_missing
    ]
    capability_rows = [
        [result.label, STATUS_LABELS.get(result.status, result.status), ", ".join(result.missing_fields + result.context_gaps) or "—"]
        for result in run.capabilities.values()
    ]
    has_integrity_error = any(
        issue.severity == "error" for issue in run.integrity_issues
    )
    memo_mode = "Fail-closed" if has_integrity_error else "Capability-limited"
    notice = (
        "来源身份、可得时间或完整性校验未通过。本次运行没有执行或展示数值估值方法；先修复下列问题，再重新生成完整研究报告。"
        if has_integrity_error
        else "完整研究报告的直接证据要求尚未满足。本备忘录保留能力缺口和下一步证据要求，不展示未获权限的估值结果。"
    )
    canonical_json = _json_for_html(run.to_dict())
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(company_name)} {esc(ticker)} · 数据不足备忘录</title>
<style>
:root {{ color-scheme:light dark; --ink:#17242d; --muted:#61717c; --line:#d8e0e5; --paper:#fff; --bg:#edf2f5; --accent:#b44b55; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.6 Inter,"Microsoft YaHei",sans-serif; }}
main {{ width:min(1060px,calc(100% - 28px)); margin:28px auto; background:var(--paper); border:1px solid var(--line); border-radius:18px; overflow:hidden; box-shadow:0 16px 45px rgba(25,45,58,.10); }}
header {{ padding:42px; color:#fff; background:linear-gradient(135deg,#183b4d,#7b4147); }} h1 {{ margin:8px 0 10px; font-size:clamp(30px,5vw,48px); }} header p {{ margin:0; max-width:760px; color:rgba(255,255,255,.82); }}
section {{ padding:30px 42px; border-bottom:1px solid var(--line); }} .eyebrow {{ letter-spacing:.1em; text-transform:uppercase; font-size:11px; opacity:.72; }}
.notice {{ padding:15px 17px; border-left:4px solid var(--accent); background:#fff1f2; color:#782d35; }} .table-wrap {{ overflow:auto; border:1px solid var(--line); border-radius:12px; }} table {{ width:100%; border-collapse:collapse; font-size:12px; }} th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; }} th {{ background:#f4f7f8; color:var(--muted); }}
footer {{ padding:20px 42px; color:var(--muted); }} @media(max-width:600px) {{ header,section,footer {{ padding-left:20px; padding-right:20px; }} }}
</style></head><body><main>
<header><span class="eyebrow">{esc(memo_mode)} · Run {esc(run.run_id)}</span><h1>数据不足备忘录</h1><p>{esc(company_name)} · {esc(ticker)} · 截至 {esc(run.as_of_date)}</p></header>
<section><p class="notice">{esc(notice)}</p></section>
<section><h2>完整性诊断</h2>{_table(["级别","代码","路径","说明"], issue_rows)}</section>
<section><h2>能力状态</h2>{_table(["能力","状态","直接缺口"], capability_rows)}</section>
<section><h2>已声明数据缺口</h2>{_table(["字段","影响","缺失原因","下一份证据"], gap_rows) if gap_rows else '<p>manifest 未声明额外数据缺口。</p>'}</section>
<footer>Schema v{run.schema_version} · 本备忘录不包含个性化投资指令或数值结论。</footer>
</main><script type="application/json" id="research-run-data">{canonical_json}</script></body></html>'''


def render_html_report(run: ResearchRun) -> str:
    if not run.permissions.get("research_report", False):
        return _render_data_insufficient_memo(run)
    company_name = run.company.get("name", "未确认公司")
    ticker = run.company.get("ticker", "—")
    grade = run.summary.get("data_quality_grade", "—")
    score = float(run.summary.get("data_quality_score", 0.0))
    evidence_counts = run.summary.get("evidence_counts", {})
    risks = run.summary.get("risks", [])
    theses = run.summary.get("theses", [])
    catalysts = run.summary.get("catalysts", [])
    scenarios = run.summary.get("scenarios", [])

    kpi_specs = (
        ("current_price", "市场快照"),
        ("market_cap", "总市值"),
        ("revenue", "最新收入"),
        ("net_income", "最新归母利润"),
        ("cfo", "最新经营现金流"),
        ("cash", "现金"),
    )
    kpi_html = "".join(
        f'''<article class="kpi-card">
          <span>{esc(label)}</span>
          <strong>{_format_value(_best_item(run, field_name))}</strong>
          <small>{esc((_best_item(run, field_name).period if _best_item(run, field_name) else "暂无"))}</small>
        </article>'''
        for field_name, label in kpi_specs
    )

    capability_cards = "".join(
        f'''<article class="cap-card status-border-{esc(result.status)}">
          <div class="card-head"><h3>{esc(result.label)}</h3>{_status_badge(result.status)}</div>
          <p>{esc(result.explanation)}</p>
          <dl class="cap-details">
            <div><dt>已覆盖</dt><dd>{esc(", ".join(result.sourced_fields) or "—")}</dd></div>
            <div><dt>估算</dt><dd>{esc(", ".join(result.estimated_fields) or "—")}</dd></div>
            <div><dt>缺口</dt><dd>{esc(", ".join(result.missing_fields + result.context_gaps) or "—")}</dd></div>
          </dl>
        </article>'''
        for result in run.capabilities.values()
    )

    method_cards = "".join(
        f'''<article class="method-card">
          <div class="card-head"><div><span class="eyebrow">{esc(method.role)}</span><h3>{esc(method.label)}</h3></div>{_status_badge(method.status)}</div>
          <p>{esc(method.explanation)}</p>
          {_method_metrics(method, allow_per_share=run.permissions.get("formal_per_share_valuation", False))}
          {_method_assumptions(method)}
          {f'<p class="gap-line">缺口：{esc(", ".join(method.missing_fields))}</p>' if method.missing_fields else ''}
          {''.join(f'<p class="diagnostic">{esc(item)}</p>' for item in method.diagnostics)}
        </article>'''
        for method in run.methods.values()
    )

    thesis_cards = "".join(
        f'''<article class="thesis-card">
          <span class="index">{index:02d}</span>
          <div><h3>{esc(item.get("title", "研究命题"))}</h3><p>{esc(item.get("detail", ""))}</p>{_evidence_refs(run, item.get("evidence_fields", []))}</div>
        </article>'''
        for index, item in enumerate(theses, start=1)
        if isinstance(item, Mapping)
    ) or '<p class="empty-state">尚未提供结构化研究命题；报告仍保留能力与证据层。</p>'

    scenario_cards = "".join(
        f'''<article class="scenario scenario-{esc(item.get("tone", "neutral"))}">
          <div class="card-head"><h3>{esc(item.get("name", "情景"))}</h3><span>{index:02d}</span></div>
          <ul>{''.join(f'<li>{esc(condition)}</li>' for condition in item.get("conditions", []))}</ul>
          <p class="view-change"><strong>视角变化：</strong>{esc(item.get("view_change", ""))}</p>
        </article>'''
        for index, item in enumerate(scenarios, start=1)
        if isinstance(item, Mapping)
    ) or '<p class="empty-state">暂无结构化情景。</p>'

    risk_rows = [
        [
            item.get("title", "风险"),
            item.get("likelihood", "—"),
            item.get("impact", "—"),
            item.get("monitor", ""),
            _SafeHtml(_evidence_refs(run, item.get("evidence_fields", []))),
        ]
        for item in risks
        if isinstance(item, Mapping)
    ]

    catalyst_html = "".join(
        f'''<article class="timeline-item">
          <span class="timeline-dot"></span>
          <div><span class="eyebrow">{esc(item.get("window", "待确认"))}</span><h3>{esc(item.get("event", "事件"))}</h3><p>{esc(item.get("why_it_matters", ""))}</p></div>
        </article>'''
        for item in catalysts
        if isinstance(item, Mapping)
    ) or '<p class="empty-state">暂无结构化事件窗口。</p>'

    plan_rows = [
        [
            item.get("watch", ""),
            item.get("validation_trigger", ""),
            item.get("invalidation", ""),
            item.get("review_window", ""),
        ]
        for item in run.conditional_plan
    ]

    evidence_rows = []
    for item in run.evidence:
        source_label = f"{item.publisher} · {item.source_id}"
        source_html = (
            f'<a href="{esc(item.url_or_api)}" rel="noopener noreferrer">{esc(source_label)}</a>'
            if item.url_or_api.startswith(("https://", "http://"))
            else esc(source_label)
        )
        quality = "估算" if item.estimated else ("官方" if item.official else item.source_tier)
        evidence_rows.append(
            [
                item.evidence_id,
                item.subject_id,
                item.semantic_role,
                item.field_name,
                item.period,
                _format_value(item),
                _SafeHtml(_status_badge("ready_with_estimates" if item.estimated else "ready") + f" <small>{esc(quality)}</small>"),
                _SafeHtml(source_html),
                item.extraction_method,
            ]
        )

    source_rows = []
    for source in run.sources:
        source_label = (
            f'<a href="{esc(source.url_or_api)}" rel="noopener noreferrer">{esc(source.title)}</a>'
            if source.url_or_api.startswith(("https://", "http://"))
            else esc(source.title)
        )
        source_rows.append(
            [
                source.source_id,
                source.tier,
                source.publisher,
                _SafeHtml(source_label),
                source.available_at,
                source.retrieved_at,
            ]
        )

    missing_rows = [
        [
            item.get("field_name", ""),
            ", ".join(item.get("required_for", [])) if isinstance(item.get("required_for"), list) else item.get("required_for", ""),
            item.get("missing_reason", ""),
            item.get("next_data_required", ""),
        ]
        for item in run.declared_missing
    ]

    canonical_json = _json_for_html(run.to_dict())
    style = """
    :root {
      --bg: #eef2f5; --surface: #ffffff; --surface-2: #f6f8fa; --ink: #15212b;
      --muted: #64717d; --line: #dce3e8; --navy: #163a52; --blue: #3b82f6;
      --green: #237f56; --amber: #a96f08; --red: #b63b49; --violet: #6758d8;
      --chart-track: #e6ebef; --chart-grid: #d7dfe5; --shadow: 0 18px 50px rgba(19,39,55,.09);
    }
    html[data-theme="dark"] {
      --bg: #10161b; --surface: #172027; --surface-2: #1d2830; --ink: #e6edf2;
      --muted: #a8b4bd; --line: #33414b; --navy: #9fd3ee; --chart-track: #2a3740;
      --chart-grid: #3a4953; --shadow: 0 20px 55px rgba(0,0,0,.3);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; color: var(--ink); background: var(--bg); font: 15px/1.65 Inter, "Segoe UI", "Microsoft YaHei", sans-serif; }
    a { color: var(--blue); text-decoration: none; } a:hover { text-decoration: underline; }
    .shell { width: min(1280px, calc(100% - 32px)); margin: 24px auto 60px; background: var(--surface); border: 1px solid var(--line); border-radius: 24px; box-shadow: var(--shadow); overflow: clip; }
    .hero { position: relative; padding: 54px 56px 44px; color: #fff; background: radial-gradient(circle at 85% 10%, rgba(91,154,190,.55), transparent 34%), linear-gradient(135deg,#102c3f 0%,#174c67 54%,#6a5942 100%); }
    .hero::after { content:""; position:absolute; inset:auto -8% -70% 44%; height:280px; border:1px solid rgba(255,255,255,.12); border-radius:50%; transform:rotate(-8deg); }
    .hero-top { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; position:relative; z-index:1; }
    .eyebrow { display:block; color:inherit; opacity:.72; letter-spacing:.11em; font-size:11px; font-weight:700; text-transform:uppercase; }
    h1,h2,h3,p { margin-top:0; } h1 { margin:8px 0 12px; font-size:clamp(32px,5vw,56px); line-height:1.05; letter-spacing:-.035em; } h2 { font-size:27px; letter-spacing:-.02em; margin-bottom:8px; } h3 { font-size:17px; margin-bottom:8px; }
    .hero-sub { max-width:830px; margin:0; color:rgba(255,255,255,.82); font-size:16px; }
    .theme-toggle { border:1px solid rgba(255,255,255,.3); color:#fff; background:rgba(255,255,255,.08); border-radius:999px; padding:9px 13px; cursor:pointer; }
    .hero-grid { display:grid; grid-template-columns:1.7fr .7fr; gap:28px; margin-top:36px; position:relative; z-index:1; }
    .hero-summary { padding:22px 24px; border:1px solid rgba(255,255,255,.2); border-radius:16px; background:rgba(255,255,255,.08); backdrop-filter:blur(8px); }
    .quality { display:grid; place-items:center; align-content:center; min-height:180px; border-radius:18px; background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.2); }
    .quality-ring { width:110px; aspect-ratio:1; display:grid; place-items:center; border-radius:50%; background:conic-gradient(#65d4a3 calc(var(--score)*1%), rgba(255,255,255,.15) 0); position:relative; }
    .quality-ring::after { content:""; position:absolute; width:82px; aspect-ratio:1; border-radius:50%; background:#17475e; }
    .quality-ring strong { position:relative; z-index:1; font-size:30px; } .quality small { margin-top:12px; color:rgba(255,255,255,.72); }
    .nav { position:sticky; top:0; z-index:20; display:flex; gap:4px; overflow:auto; scrollbar-width:none; padding:10px 18px; border-bottom:1px solid var(--line); background:color-mix(in srgb, var(--surface) 94%, transparent); backdrop-filter:blur(12px); }
    .nav::-webkit-scrollbar { display:none; }
    .nav a { white-space:nowrap; color:var(--muted); padding:7px 11px; border-radius:8px; font-size:12px; font-weight:650; } .nav a.active,.nav a:hover { color:var(--ink); background:var(--surface-2); text-decoration:none; }
    main { padding:0 56px 56px; }
    section { padding:44px 0; border-bottom:1px solid var(--line); scroll-margin-top:64px; } section:last-child { border-bottom:0; }
    .section-head { display:flex; justify-content:space-between; gap:24px; align-items:flex-end; margin-bottom:24px; } .section-head p { margin:0; max-width:680px; color:var(--muted); }
    .kpi-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
    .kpi-card { padding:18px; border:1px solid var(--line); border-radius:14px; background:linear-gradient(145deg,var(--surface),var(--surface-2)); }
    .kpi-card span,.kpi-card small { display:block; color:var(--muted); font-size:12px; } .kpi-card strong { display:block; font-size:22px; margin:8px 0 3px; font-variant-numeric:tabular-nums; }
    .viz-card { padding:20px; margin-bottom:18px; border:1px solid var(--line); border-radius:16px; background:var(--surface-2); overflow:auto; }
    .viz { display:block; width:100%; min-width:720px; height:auto; } .risk-viz { min-width:0; } .svg-title { fill:var(--ink); font-size:15px; font-weight:750; } .svg-label { fill:var(--muted); font-size:12px; } .svg-label.strong { fill:var(--ink); font-weight:700; } .svg-value { fill:var(--ink); font-size:10px; } .svg-axis { fill:var(--muted); font-size:10px; } .risk-index { fill:#fff; font-size:10px; font-weight:800; pointer-events:none; }
    .cap-grid,.method-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:14px; }
    .cap-card,.method-card,.thesis-card,.scenario { border:1px solid var(--line); border-radius:15px; background:var(--surface); padding:18px; }
    .status-border-ready { border-left:4px solid var(--green); } .status-border-limited { border-left:4px solid var(--amber); } .status-border-ready_with_estimates { border-left:4px solid var(--violet); } .status-border-blocked { border-left:4px solid var(--red); }
    .card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; } .card-head h3 { margin:0; }
    .status { display:inline-flex; white-space:nowrap; align-items:center; border-radius:999px; padding:4px 9px; font-size:11px; font-weight:750; }
    .status-ready { color:#176341; background:#ddf5e9; } .status-limited,.status-caution { color:#805506; background:#fff0ca; } .status-ready_with_estimates { color:#5141bb; background:#ece9ff; } .status-blocked,.status-disabled { color:#922b37; background:#ffe2e6; }
    .cap-card p,.method-card p { color:var(--muted); }
    .cap-details,.mini-metrics { margin:14px 0 0; display:grid; gap:8px; } .cap-details div,.mini-metrics div { display:grid; grid-template-columns:74px 1fr; gap:8px; } dt { color:var(--muted); font-size:12px; } dd { margin:0; font-size:12px; word-break:break-word; }
    .mini-metrics { grid-template-columns:repeat(2,1fr); } .mini-metrics div { display:block; padding:10px; border-radius:10px; background:var(--surface-2); } .mini-metrics dd { font-size:17px; font-weight:750; margin-top:4px; }
    .thesis-stack { display:grid; gap:10px; } .thesis-card { display:grid; grid-template-columns:44px 1fr; gap:14px; } .thesis-card .index { color:var(--blue); font-weight:800; font-size:18px; } .thesis-card p { margin-bottom:8px; color:var(--muted); }
    .evidence-ref { display:inline-flex; color:var(--blue); background:color-mix(in srgb,var(--blue) 10%,transparent); border-radius:6px; padding:2px 7px; font-size:10px; font-weight:700; }
    .scenario-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; } .scenario { border-top:4px solid var(--line); } .scenario-positive { border-top-color:var(--green); } .scenario-neutral { border-top-color:var(--amber); } .scenario-negative { border-top-color:var(--red); } .scenario ul { padding-left:18px; color:var(--muted); } .view-change { padding-top:12px; border-top:1px solid var(--line); font-size:13px; }
    .two-col { display:grid; grid-template-columns:1fr 1fr; gap:20px; align-items:start; }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:13px; } table { width:100%; border-collapse:collapse; font-size:12px; } th { position:sticky; top:0; background:var(--surface-2); color:var(--muted); text-align:left; font-size:11px; letter-spacing:.035em; } th,td { padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; } tbody tr:last-child td { border-bottom:0; } tbody tr:hover { background:color-mix(in srgb,var(--blue) 4%,transparent); }
    .timeline { position:relative; padding-left:26px; } .timeline::before { content:""; position:absolute; left:6px; top:8px; bottom:8px; width:2px; background:var(--line); } .timeline-item { position:relative; padding:0 0 24px 18px; } .timeline-dot { position:absolute; left:-25px; top:6px; width:12px; height:12px; border:3px solid var(--surface); border-radius:50%; background:var(--blue); box-shadow:0 0 0 1px var(--blue); }
    .caption,.diagnostic,.gap-line { color:var(--muted); font-size:11px; } .diagnostic { border-left:3px solid var(--amber); padding-left:8px; }
    .notice { padding:16px 18px; border-radius:13px; background:var(--surface-2); border:1px solid var(--line); color:var(--muted); }
    details { border:1px solid var(--line); border-radius:13px; background:var(--surface-2); } summary { padding:14px 16px; cursor:pointer; font-weight:700; } details .details-body { padding:0 16px 16px; }
    .assumption-details { margin-top:14px; } .assumption-details summary { padding:9px 11px; font-size:12px; } .assumption-details pre { margin:0; padding:0 11px 12px; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--muted); font:11px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .diagnostic-list { columns:2; color:var(--muted); font:11px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .report-footer { padding:28px 56px; color:rgba(255,255,255,.74); background:#102c3f; font-size:12px; display:flex; justify-content:space-between; gap:20px; }
    .empty-state { color:var(--muted); padding:24px; border:1px dashed var(--line); border-radius:13px; }
    @media (max-width:900px) { .shell { width:100%; margin:0; border-radius:0; border-left:0; border-right:0; } .hero,main { padding-left:22px; padding-right:22px; } .hero-grid,.two-col { grid-template-columns:1fr; } .kpi-grid,.cap-grid,.method-grid { grid-template-columns:repeat(2,1fr); } .scenario-grid { grid-template-columns:1fr; } .report-footer { padding:24px 22px; } }
    @media (max-width:580px) { .hero-top { display:block; } .theme-toggle { margin-top:14px; } .kpi-grid,.cap-grid,.method-grid { grid-template-columns:1fr; } .section-head { display:block; } .diagnostic-list { columns:1; } .risk-viz { min-width:500px; } }
    @media (prefers-reduced-motion:reduce) { html { scroll-behavior:auto; } }
    @media print { :root { --bg:#fff; --surface:#fff; --surface-2:#f7f7f7; --ink:#111; --muted:#555; --line:#ddd; } body { background:#fff; } .shell { width:100%; margin:0; border:0; box-shadow:none; } .nav,.theme-toggle { display:none; } section { break-inside:avoid; } .hero { print-color-adjust:exact; } a { color:inherit; } }
    """

    return f'''<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{esc(company_name)} {esc(ticker)} · 个人投研框架报告</title>
  <style>{style}</style>
</head>
<body>
<div class="shell">
  <header class="hero" id="overview">
    <div class="hero-top">
      <div><span class="eyebrow">Equity Research · Canonical Run {esc(run.run_id)}</span><h1>{esc(company_name)}</h1><p class="hero-sub">{esc(ticker)} · 截至 {esc(run.as_of_date)} · {esc(STATUS_LABELS.get(run.status, run.status))}</p></div>
      <button class="theme-toggle" type="button" aria-label="切换主题">切换主题</button>
    </div>
    <div class="hero-grid">
      <div class="hero-summary"><span class="eyebrow">研究摘要</span><p>{esc(run.summary.get("executive_summary", ""))}</p><p><strong>边界：</strong>本报告提供公开资料研究、方法可用性和条件验证框架，不构成个性化投资指令。</p></div>
      <div class="quality"><div class="quality-ring" style="--score:{score:.1f}"><strong>{esc(grade)}</strong></div><small>数据质量 {score:.1f} / 100</small></div>
    </div>
  </header>
  <nav class="nav" aria-label="报告导航">
    <a href="#overview">摘要</a><a href="#snapshot">快照</a><a href="#capabilities">能力</a><a href="#financials">财务</a><a href="#theses">命题</a><a href="#methodology">方法</a><a href="#scenarios">情景</a><a href="#risks">风险</a><a href="#plan">计划</a><a href="#evidence-ledger">证据</a>
  </nav>
  <main>
    <section id="snapshot">
      <div class="section-head"><div><span class="eyebrow">01 · Snapshot</span><h2>关键事实快照</h2></div><p>数字直接来自 canonical evidence ledger；报告层不重新抓取或重算金融事实。</p></div>
      <div class="kpi-grid">{kpi_html}</div>
      <p class="caption">目标主体证据 {esc(evidence_counts.get("total", 0))} 项，其中官方 {esc(evidence_counts.get("official", 0))}、二级来源 {esc(evidence_counts.get("secondary", 0))}、估算 {esc(evidence_counts.get("estimated", 0))}；跨主体方法证据 {esc(evidence_counts.get("cross_subject_method_evidence", 0))} 项，单独统计。</p>
    </section>
    <section id="capabilities">
      <div class="section-head"><div><span class="eyebrow">02 · Capability Matrix</span><h2>能力级门禁</h2></div><p>一个输入缺口只限制依赖它的能力，不再把整个研究链判为失败。</p></div>
      <div class="viz-card">{_capability_svg(run)}</div>
      <div class="cap-grid">{capability_cards}</div>
    </section>
    <section id="financials">
      <div class="section-head"><div><span class="eyebrow">03 · Financial Evidence</span><h2>财务事实与估算分层</h2></div><p>不同指标使用独立刻度，避免收入体量压扁利润与现金流；季度和年度不会被静默年化。</p></div>
      <div class="viz-card">{_financial_svg(run)}</div>
      {('<h3>明确缺口</h3>' + _table(["字段","影响能力","缺失原因","下一份证据"], missing_rows)) if missing_rows else '<p class="notice">当前 manifest 没有声明关键缺口。</p>'}
    </section>
    <section id="theses">
      <div class="section-head"><div><span class="eyebrow">04 · Research Questions</span><h2>核心研究命题</h2></div><p>命题描述需要被什么事实验证，而不是把观点写成不可证伪的口号。</p></div>
      <div class="thesis-stack">{thesis_cards}</div>
    </section>
    <section id="methodology">
      <div class="section-head"><div><span class="eyebrow">05 · Method Registry</span><h2>估值方法路由</h2></div><p>观察倍数、同业、历史带、DCF 和行业方法各自返回状态、缺口与诊断。</p></div>
      <div class="method-grid">{method_cards}</div>
      {_dcf_sensitivity(run)}
    </section>
    <section id="scenarios">
      <div class="section-head"><div><span class="eyebrow">06 · Scenarios</span><h2>条件情景</h2></div><p>默认不分配概率；每个情景是一组相互一致的验证条件。</p></div>
      <div class="scenario-grid">{scenario_cards}</div>
    </section>
    <section id="risks">
      <div class="section-head"><div><span class="eyebrow">07 · Risk & Catalysts</span><h2>风险矩阵与事件窗口</h2></div><p>风险分数用于排布复核顺序，不是总评分或自动决策信号。</p></div>
      <div class="two-col"><div class="viz-card">{_risk_svg(risks)}</div><div><h3>事件时间轴</h3><div class="timeline">{catalyst_html}</div></div></div>
      {_table(["风险","可能性","影响","监控变量","证据"], risk_rows) if risk_rows else ''}
    </section>
    <section id="plan">
      <div class="section-head"><div><span class="eyebrow">08 · Conditional Research Plan</span><h2>条件研究计划</h2></div><p>计划只定义观察、验证、失效和复核时间，不替用户作个性化决定。</p></div>
      {_table(["观察项","验证触发","失效条件","复核窗口"], plan_rows)}
    </section>
    <section id="evidence-ledger">
      <div class="section-head"><div><span class="eyebrow">09 · Provenance</span><h2>证据台账</h2></div><p>每个关键数字保留期间、单位、来源层级、提取方法和链接；估算永远单独标记。</p></div>
      {_table(["ID","主体","语义角色","字段","期间","值","质量","来源","方法"], evidence_rows)}
      <h3 style="margin-top:24px">来源注册表</h3>
      {_table(["Source ID","层级","发布者","标题","可得时间","获取时间"], source_rows)}
    </section>
    <section id="diagnostics">
      <div class="section-head"><div><span class="eyebrow">10 · Diagnostics</span><h2>运行诊断</h2></div><p>用于复现和排障；HTML 与下方嵌入的 JSON 来自同一 ResearchRun。</p></div>
      <details><summary>展开诊断与机器结果</summary><div class="details-body"><div class="diagnostic-list">{''.join(f'<div>{esc(item)}</div>' for item in run.diagnostics)}</div><p class="caption">机器可读结果嵌入在页面的 <code>#research-run-data</code> 节点中。</p></div></details>
    </section>
  </main>
  <footer class="report-footer"><span>{esc(company_name)} · {esc(ticker)}</span><span>Run {esc(run.run_id)} · Schema v{run.schema_version}</span></footer>
</div>
<script type="application/json" id="research-run-data">{canonical_json}</script>
<script>
(() => {{
  const root = document.documentElement;
  const button = document.querySelector('.theme-toggle');
  button?.addEventListener('click', () => {{
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  }});
  const links = [...document.querySelectorAll('.nav a')];
  const sections = links.map(a => document.querySelector(a.getAttribute('href'))).filter(Boolean);
  const observer = new IntersectionObserver(entries => {{
    const visible = entries.filter(entry => entry.isIntersecting).sort((a,b) => b.intersectionRatio-a.intersectionRatio)[0];
    if (!visible) return;
    links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + visible.target.id));
  }}, {{ rootMargin: '-20% 0px -65% 0px', threshold: [0,.2,.6] }});
  sections.forEach(section => observer.observe(section));
}})();
</script>
</body>
</html>'''
