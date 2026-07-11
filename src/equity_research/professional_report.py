from __future__ import annotations

import html
import json
from typing import Any, Iterable, Mapping

from .evidence import numeric_value, period_rank
from .models import AnalysisResult, EvidenceClaim, EvidenceItem, ResearchRun


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _status_label(status: str) -> str:
    return {
        "ready": "证据充分",
        "limited": "有限判断",
        "blocked": "暂不判断",
    }.get(status, status)


def _completeness_label(value: str) -> str:
    return {
        "complete": "多维研究完整",
        "complete_with_limits": "多维研究完成 · 部分维度有限",
        "partial": "多维研究部分完成",
        "blocked": "研究完整性受阻",
    }.get(value, value)


def _best(run: ResearchRun, field_name: str) -> EvidenceItem | None:
    items = [
        item
        for item in run.evidence
        if item.field_name == field_name
        and item.subject_id == str(run.company.get("ticker", ""))
        and not item.estimated
    ]
    return max(items, key=lambda item: period_rank(item.period), default=None)


def _format_number(item: EvidenceItem | None) -> str:
    if not item:
        return "—"
    value = numeric_value(item.value)
    if value is None:
        return _esc(item.value)
    unit = item.unit.lower()
    if unit in {"cny/share", "cny_per_share"}:
        return f"{value:,.2f} 元/股"
    if item.currency == "CNY" and unit in {"cny", "yuan", "rmb"}:
        absolute = abs(value)
        if absolute >= 100_000_000:
            return f"{value / 100_000_000:,.2f} 亿元"
        if absolute >= 1_000_000:
            return f"{value / 1_000_000:,.1f} 百万元"
    if unit in {"shares", "share"}:
        return f"{value / 100_000_000:,.2f} 亿股"
    return f"{value:,.2f} {_esc(item.unit)}".strip()


def _evidence_chips(run: ResearchRun, evidence_ids: Iterable[str]) -> str:
    by_id = {item.evidence_id: item for item in run.evidence}
    chips: list[str] = []
    for evidence_id in evidence_ids:
        item = by_id.get(evidence_id)
        if not item:
            continue
        label = f"{item.evidence_id} · {item.period}"
        title = f"{item.publisher} · {item.field_name}"
        if item.url_or_api.startswith(("https://", "http://")):
            chips.append(
                f'<a class="evidence-chip" href="{_esc(item.url_or_api)}" '
                f'title="{_esc(title)}" rel="noopener noreferrer">{_esc(label)}</a>'
            )
        else:
            chips.append(f'<span class="evidence-chip" title="{_esc(title)}">{_esc(label)}</span>')
    return '<div class="evidence-row">' + "".join(chips) + "</div>"


def _evidence_ref(evidence_ids: Iterable[str]) -> str:
    count = len(tuple(dict.fromkeys(evidence_ids)))
    if not count:
        return ""
    return f'<a class="evidence-ref" href="#audit-appendix">证据注 · {count} 项</a>'


def _metrics(run: ResearchRun, result: AnalysisResult) -> str:
    cards = []
    for item in result.key_metrics:
        tone = str(item.get("tone", "neutral"))
        cards.append(
            f'<article class="metric tone-{_esc(tone)}"><span>{_esc(item.get("label"))}</span>'
            f'<strong>{_esc(item.get("value"))}</strong><small>{_esc(item.get("note"))}</small>'
            f'{_evidence_ref(item.get("evidence_ids", []))}</article>'
        )
    return '<div class="metric-grid">' + "".join(cards) + "</div>" if cards else ""


def _bullet_group(title: str, items: Iterable[str], css_class: str = "") -> str:
    values = [item for item in items if item]
    if not values:
        return ""
    return (
        f'<div class="bullet-group {_esc(css_class)}"><h3>{_esc(title)}</h3><ul>'
        + "".join(f"<li>{_esc(item)}</li>" for item in values)
        + "</ul></div>"
    )


def _claim_group(
    title: str,
    claims: Iterable[EvidenceClaim],
    css_class: str = "",
) -> str:
    values = tuple(claims)
    if not values:
        return ""
    return (
        f'<div class="bullet-group {_esc(css_class)}"><h3>{_esc(title)}</h3><ul>'
        + "".join(
            f'<li>{_esc(claim.text)}{_evidence_ref(claim.evidence_ids)}</li>'
            for claim in values
        )
        + "</ul></div>"
    )


def _analysis_section(
    run: ResearchRun,
    result: AnalysisResult,
    *,
    section_id: str,
    number: str,
    kicker: str,
    intro: str,
    extra: str = "",
) -> str:
    return f"""
    <section id="{_esc(section_id)}">
      <div class="section-heading"><div><span class="kicker">{_esc(number)} · {_esc(kicker)}</span><h2>{_esc(result.title)}</h2></div><span class="lens-status lens-{_esc(result.status)}">{_esc(_status_label(result.status))}</span></div>
      <p class="section-intro">{_esc(intro)}</p>
      <div class="conclusion-card"><span>本维度结论</span><p>{_esc(result.conclusion)}</p>{_evidence_ref(result.evidence_ids)}</div>
      {_metrics(run, result)}
      {extra}
      <div class="analysis-grid">
        {_claim_group("关键发现", result.key_findings)}
        {_claim_group("反证与约束", result.counterpoints, "counter")}
        {_claim_group("仍待验证", result.uncertainties, "uncertain")}
      </div>
    </section>
    """


def _fundamental_svg(run: ResearchRun) -> str:
    items = [
        ("收入", _best(run, "revenue")),
        ("归母利润", _best(run, "net_income")),
        ("经营现金流", _best(run, "cfo")),
        ("现金", _best(run, "cash")),
        ("债务", _best(run, "debt")),
    ]
    values = [abs(numeric_value(item.value) or 0.0) for _, item in items if item]
    maximum = max(values, default=1.0)
    rows = []
    for index, (label, item) in enumerate(items):
        value = abs(numeric_value(item.value) or 0.0) if item else 0.0
        width = 510 * value / maximum if maximum else 0
        y = 52 + index * 44
        rows.append(
            f'<text x="0" y="{y + 13}" class="svg-label">{_esc(label)}</text>'
            f'<rect x="110" y="{y}" width="510" height="18" rx="9" class="svg-track"/>'
            f'<rect x="110" y="{y}" width="{width:.1f}" height="18" rx="9" class="svg-bar"/>'
            f'<text x="638" y="{y + 13}" class="svg-value">{_esc(_format_number(item))}</text>'
        )
    return (
        '<div class="visual-card"><svg class="viz" viewBox="0 0 820 280" role="img" aria-label="最新财务规模对比">'
        '<text x="0" y="20" class="svg-title">最新财务规模 · 同币种绝对值</text>'
        + "".join(rows)
        + '</svg></div>'
    )


def _technical_svg(result: AnalysisResult) -> str:
    blocks = []
    for index, item in enumerate(result.key_metrics[:4]):
        x = 20 + index * 190
        blocks.append(
            f'<rect x="{x}" y="46" width="170" height="92" rx="14" class="svg-panel"/>'
            f'<text x="{x + 14}" y="72" class="svg-label">{_esc(item.get("label"))}</text>'
            f'<text x="{x + 14}" y="103" class="svg-metric">{_esc(item.get("value"))}</text>'
            f'<text x="{x + 14}" y="124" class="svg-note">{_esc(item.get("note"))}</text>'
        )
    title = "市场价格快照" if result.status != "ready" else "价格趋势与动量快照"
    return (
        f'<div class="visual-card"><svg class="viz" viewBox="0 0 800 165" role="img" aria-label="{_esc(title)}">'
        f'<text x="20" y="24" class="svg-title">{_esc(title)}</text>'
        + "".join(blocks)
        + '</svg></div>'
    )


def _debate(run: ResearchRun) -> str:
    debate = run.debate
    if not debate:
        return ""

    def case_html(case: Any, label: str, css: str) -> str:
        arguments = "".join(
            f'<li><span class="argument-id">{_esc(item.get("argument_id"))}'
            + (f' · 回应 {_esc(item.get("response_to"))}' if item.get("response_to") else "")
            + f'</span><p>{_esc(item.get("claim"))}</p>'
            + _evidence_ref(item.get("evidence_ids", []))
            + "</li>"
            for item in case.arguments
        )
        return f'<article class="debate-card {css}"><span>{label}</span><h3>{_esc(case.thesis)}</h3><ol>{arguments}</ol></article>'

    return f"""
    <section id="debate">
      <div class="section-heading"><div><span class="kicker">07 · CHALLENGE</span><h2>多空质询与核心分歧</h2></div></div>
      <p class="section-intro">正反观点必须引用可追溯证据；角色分工用于挑战假设，不替代事实校验。</p>
      <div class="debate-grid">{case_html(debate.bull, "正方论点", "bull")}{case_html(debate.bear, "反方论点", "bear")}</div>
      <div class="manager-card"><span>Research Manager</span><p>{_esc(debate.manager_summary)}</p></div>
      <div class="analysis-grid">
        {_bullet_group("关键分歧", debate.key_disagreements)}
        {_bullet_group("已形成共识", debate.resolved_disagreements)}
        {_bullet_group("未解决问题", debate.unresolved_questions, "uncertain")}
      </div>
    </section>
    """


def _synthesis(run: ResearchRun) -> str:
    synthesis = run.synthesis
    if not synthesis:
        return ""
    cards = (
        ("商业质量", synthesis.business_quality),
        ("盈利展望", synthesis.earnings_outlook),
        ("市场结构", synthesis.market_view),
        ("估值视角", synthesis.valuation_view),
    )
    return f"""
    <section id="synthesis" class="synthesis-section">
      <div class="section-heading"><div><span class="kicker">08 · SYNTHESIS</span><h2>综合研究观点</h2></div></div>
      <div class="thesis-hero"><span>核心论点</span><p>{_esc(synthesis.core_thesis)}</p><small>差异化视角：{_esc(synthesis.variant_view)}</small></div>
      <div class="synthesis-grid">{''.join(f'<article><span>{_esc(label)}</span><p>{_esc(value)}</p></article>' for label, value in cards)}</div>
      <div class="risk-reward"><span>风险收益特征</span><p>{_esc(synthesis.risk_reward_summary)}</p></div>
      <div class="analysis-grid">
        {_bullet_group("关键不确定性", synthesis.key_uncertainties, "uncertain")}
        {_bullet_group("什么会改变观点", synthesis.what_would_change_the_view)}
      </div>
      {_evidence_ref(synthesis.evidence_ids)}
    </section>
    """


def _monitoring(run: ResearchRun) -> str:
    rows = "".join(
        f'<tr><td>{_esc(item.get("watch"))}</td><td>{_esc(item.get("validation_trigger"))}</td>'
        f'<td>{_esc(item.get("invalidation"))}</td><td>{_esc(item.get("review_window"))}</td></tr>'
        for item in run.conditional_plan
    )
    return f"""
    <section id="monitoring">
      <div class="section-heading"><div><span class="kicker">09 · MONITORING</span><h2>条件验证与复核计划</h2></div></div>
      <p class="section-intro">将观点拆成可观察变量、验证信号和失效条件；不把研究结论转换成个性化交易指令。</p>
      <div class="table-wrap"><table><thead><tr><th>观察变量</th><th>验证信号</th><th>失效条件</th><th>复核窗口</th></tr></thead><tbody>{rows}</tbody></table></div>
    </section>
    """


def _audit_appendix(run: ResearchRun) -> str:
    capability_rows = "".join(
        f'<tr><td>{_esc(item.label)}</td><td>{_esc(item.status)}</td><td>{_esc(", ".join(item.missing_fields + item.context_gaps) or "—")}</td></tr>'
        for item in run.capabilities.values()
    )
    method_rows = "".join(
        f'<tr><td>{_esc(item.label)}</td><td>{_esc(item.status)}</td><td>{_esc(", ".join(item.missing_fields) or "—")}</td></tr>'
        for item in run.methods.values()
    )
    source_rows = "".join(
        f'<tr><td>{_esc(source.source_id)}</td><td>{_esc(source.tier)}</td><td>{_esc(source.publisher)}</td><td>{_esc(source.available_at)}</td></tr>'
        for source in run.sources
    )
    claim_rows: list[str] = []

    def add_claim(scope: str, claim: str, evidence_ids: Iterable[str]) -> None:
        ids = tuple(dict.fromkeys(evidence_ids))
        if not claim or not ids:
            return
        claim_rows.append(
            f'<tr><td>{_esc(scope)}</td><td>{_esc(claim)}</td><td>{_evidence_chips(run, ids)}</td></tr>'
        )

    for result in run.analysis.dimensions.values():
        add_claim(result.title, result.conclusion, result.evidence_ids)
        for claim_type, claims in (
            ("关键发现", result.key_findings),
            ("反证与约束", result.counterpoints),
            ("仍待验证", result.uncertainties),
        ):
            for claim in claims:
                add_claim(f"{result.title} · {claim_type}", claim.text, claim.evidence_ids)
        for metric in result.key_metrics:
            add_claim(
                f'{result.title} · 指标',
                f'{metric.get("label")}: {metric.get("value")}',
                metric.get("evidence_ids", []),
            )
    if run.debate:
        for case in (run.debate.bull, run.debate.bear):
            for argument in case.arguments:
                add_claim(
                    f'质询 · {argument.get("argument_id")}',
                    str(argument.get("claim", "")),
                    argument.get("evidence_ids", []),
                )
    if run.synthesis:
        add_claim("综合观点", run.synthesis.core_thesis, run.synthesis.evidence_ids)
    return f"""
    <section id="audit-appendix" class="appendix-section">
      <details>
        <summary>研究审计附录 · 数据质量、方法状态与来源索引</summary>
        <div class="appendix-body">
          <p>该附录用于复现与质量控制，不构成公司研究正文。</p>
          <h3>论点—证据映射</h3><div class="table-wrap"><table><thead><tr><th>研究位置</th><th>论点或指标</th><th>Evidence ID</th></tr></thead><tbody>{''.join(claim_rows)}</tbody></table></div>
          <h3>能力状态</h3><div class="table-wrap"><table><thead><tr><th>能力</th><th>状态</th><th>直接限制</th></tr></thead><tbody>{capability_rows}</tbody></table></div>
          <h3>估值方法</h3><div class="table-wrap"><table><thead><tr><th>方法</th><th>状态</th><th>直接限制</th></tr></thead><tbody>{method_rows}</tbody></table></div>
          <h3>来源索引</h3><div class="table-wrap"><table><thead><tr><th>Source ID</th><th>层级</th><th>发布者</th><th>公开时间</th></tr></thead><tbody>{source_rows}</tbody></table></div>
          <p class="audit-note">数据质量 {_esc(run.summary.get("data_quality_grade", "—"))} · {_esc(run.summary.get("data_quality_score", "—"))}/100 · Run {_esc(run.run_id)}</p>
        </div>
      </details>
    </section>
    """


def render_professional_report(run: ResearchRun) -> str:
    company_name = str(run.company.get("name", "公司"))
    ticker = str(run.company.get("ticker", ""))
    synthesis = run.synthesis
    dimensions: Mapping[str, AnalysisResult] = run.analysis.dimensions
    payload = json.dumps(run.to_dict(), ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    sections = [
        _analysis_section(run, dimensions["business"], section_id="company", number="01", kicker="COMPANY", intro="从收入来源、客户价值和资本占用解释公司如何创造利润。"),
        _analysis_section(run, dimensions["industry"], section_id="industry", number="02", kicker="INDUSTRY", intro="分别评价行业周期、产业链位置、竞争要素和公司相对位置。"),
        _analysis_section(run, dimensions["fundamentals"], section_id="fundamentals", number="03", kicker="FUNDAMENTALS", intro="把增长、利润、现金流和资产负债表放在同一经营逻辑下。", extra=_fundamental_svg(run)),
        _analysis_section(run, dimensions["technical"], section_id="technical", number="04", kicker="TECHNICAL", intro="技术指标描述价格与资金行为，不替代公司价值判断。", extra=_technical_svg(dimensions["technical"])),
        _analysis_section(run, dimensions["sentiment_events"], section_id="sentiment-events", number="05", kicker="SENTIMENT & EVENTS", intro="区分可验证事件、市场叙事与未经校准的情绪噪声。"),
        _analysis_section(run, dimensions["valuation"], section_id="valuation", number="06", kicker="VALUATION", intro="根据公司类型和数据质量选择方法，不把不可审计输入包装成精确结论。"),
        _analysis_section(run, dimensions["governance_risk"], section_id="risk-governance", number="06B", kicker="GOVERNANCE & RISK", intro="关注资本配置、治理结构和可能破坏核心论点的风险。"),
        _debate(run),
        _synthesis(run),
        _monitoring(run),
        _audit_appendix(run),
    ]
    executive = synthesis.core_thesis if synthesis else str(run.summary.get("executive_summary", ""))
    variant = synthesis.variant_view if synthesis else ""
    return f"""<!doctype html>
<html lang="zh-CN" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark"><title>{_esc(company_name)} {_esc(ticker)} · V3 Professional Research Narrative</title>
<style>
:root{{--paper:#f2f0eb;--surface:#fff;--surface-2:#f7f6f2;--ink:#172026;--muted:#66727a;--line:#dedfd9;--navy:#14374a;--blue:#356e8d;--green:#1f7a55;--amber:#9a6815;--red:#a0444d;--shadow:0 22px 70px rgba(28,42,50,.10)}}html[data-theme="dark"]{{--paper:#10161a;--surface:#172027;--surface-2:#1d282f;--ink:#e8eef1;--muted:#aab5bb;--line:#34434b;--navy:#a7d6e9;--blue:#76b7d8;--shadow:0 22px 70px rgba(0,0,0,.35)}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.72 Inter,"Segoe UI","Microsoft YaHei",sans-serif}}a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}
.report{{width:min(1240px,calc(100% - 32px));margin:24px auto 64px;background:var(--surface);border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);overflow:hidden}}.hero{{padding:54px 58px 48px;color:#fff;background:radial-gradient(circle at 82% 0,rgba(136,185,203,.38),transparent 35%),linear-gradient(135deg,#102d3f 0%,#174c63 58%,#554a3a 100%)}}.hero-top{{display:flex;justify-content:space-between;gap:24px}}.hero h1{{margin:8px 0 12px;font-size:clamp(34px,5vw,58px);line-height:1.04;letter-spacing:-.035em}}.hero-meta{{color:rgba(255,255,255,.72)}}.theme-toggle{{border:1px solid rgba(255,255,255,.28);color:#fff;background:rgba(255,255,255,.08);border-radius:99px;padding:9px 13px;height:max-content;cursor:pointer}}
.hero-thesis{{display:grid;grid-template-columns:1.8fr 1fr;gap:18px;margin-top:34px}}.hero-thesis>div{{padding:22px 24px;border:1px solid rgba(255,255,255,.18);border-radius:17px;background:rgba(255,255,255,.08)}}.hero-thesis span,.kicker{{display:block;font-size:11px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;opacity:.72}}.hero-thesis p{{margin:8px 0 0;font-size:18px;line-height:1.55}}.hero-thesis small{{display:block;color:rgba(255,255,255,.74);font-size:13px;line-height:1.55}}
.nav{{position:sticky;top:0;z-index:10;display:flex;gap:3px;overflow:auto;padding:10px 20px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--surface) 94%,transparent);backdrop-filter:blur(12px)}}.nav a{{white-space:nowrap;padding:7px 10px;color:var(--muted);font-size:12px;font-weight:700;border-radius:8px}}.nav a:hover{{background:var(--surface-2);color:var(--ink);text-decoration:none}}main{{padding:0 58px 58px}}section{{padding:46px 0;border-bottom:1px solid var(--line);scroll-margin-top:64px}}.section-heading{{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:8px}}h2{{margin:4px 0 0;font-size:29px;letter-spacing:-.025em}}h3{{font-size:16px}}.section-intro{{max-width:760px;color:var(--muted);margin-bottom:24px}}
.lens-status{{padding:5px 10px;border-radius:99px;font-size:11px;font-weight:800}}.lens-ready{{color:#14603d;background:#dcf3e7}}.lens-limited{{color:#7b520b;background:#fff0c9}}.lens-blocked{{color:#8d3039;background:#ffe3e6}}.conclusion-card,.manager-card,.risk-reward{{padding:22px 24px;border-radius:16px;background:linear-gradient(135deg,color-mix(in srgb,var(--blue) 10%,var(--surface)),var(--surface-2));border:1px solid var(--line)}}.conclusion-card span,.manager-card span,.risk-reward span,.thesis-hero span,.metric span,.synthesis-grid span{{color:var(--muted);font-size:11px;font-weight:800;letter-spacing:.07em;text-transform:uppercase}}.conclusion-card p,.manager-card p,.risk-reward p{{margin:7px 0 0;font-size:17px;line-height:1.65}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}}.metric{{padding:16px;border:1px solid var(--line);border-radius:14px;background:var(--surface-2)}}.metric strong{{display:block;margin:7px 0 3px;font-size:21px}}.metric small{{color:var(--muted)}}.tone-positive{{border-top:3px solid var(--green)}}.tone-caution{{border-top:3px solid var(--amber)}}.analysis-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:18px}}.bullet-group{{padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--surface)}}.bullet-group h3{{margin:0 0 10px}}.bullet-group ul{{margin:0;padding-left:18px;color:var(--muted)}}.bullet-group li+li{{margin-top:8px}}.bullet-group.counter{{border-top:3px solid var(--red)}}.bullet-group.uncertain{{border-top:3px solid var(--amber)}}
.evidence-ref{{display:inline-flex;margin-top:8px;color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.04em}}.evidence-row{{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}}.evidence-chip{{padding:3px 8px;border-radius:7px;background:color-mix(in srgb,var(--blue) 10%,transparent);font-size:10px;font-weight:750}}.argument-id{{display:block;margin-bottom:4px;color:var(--muted);font:10px/1.4 ui-monospace,Consolas,monospace}}.visual-card{{margin:18px 0;padding:18px;border:1px solid var(--line);border-radius:16px;background:var(--surface-2);overflow:auto}}.viz{{display:block;width:100%;min-width:720px;height:auto}}.svg-title{{fill:var(--ink);font-weight:800;font-size:14px}}.svg-label,.svg-note{{fill:var(--muted);font-size:11px}}.svg-value{{fill:var(--ink);font-size:11px;font-weight:700}}.svg-track{{fill:var(--line)}}.svg-bar{{fill:var(--blue)}}.svg-panel{{fill:var(--surface);stroke:var(--line)}}.svg-metric{{fill:var(--ink);font-size:20px;font-weight:800}}
.debate-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.debate-card{{padding:22px;border:1px solid var(--line);border-radius:16px}}.debate-card.bull{{border-top:4px solid var(--green)}}.debate-card.bear{{border-top:4px solid var(--red)}}.debate-card>span{{font-size:11px;font-weight:800;letter-spacing:.08em}}.debate-card h3{{font-size:18px}}.debate-card ol{{padding-left:20px}}.debate-card li+li{{margin-top:14px}}.manager-card{{margin-top:16px}}.synthesis-section{{padding:46px 30px;margin:0 -30px;background:linear-gradient(145deg,var(--surface-2),var(--surface))}}.thesis-hero{{padding:25px;border-radius:17px;background:var(--navy);color:var(--surface)}}.thesis-hero p{{margin:8px 0;font-size:22px;line-height:1.5}}.thesis-hero small{{opacity:.75}}.synthesis-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}}.synthesis-grid article{{padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--surface)}}.synthesis-grid p{{margin:6px 0 0}}.risk-reward{{margin-top:16px}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:14px}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}}th{{background:var(--surface-2);color:var(--muted);font-size:11px}}tr:last-child td{{border-bottom:0}}.appendix-section{{border-bottom:0}}details{{border:1px solid var(--line);border-radius:15px;background:var(--surface-2)}}summary{{padding:17px 19px;cursor:pointer;font-weight:800}}.appendix-body{{padding:0 19px 20px}}.appendix-body h3{{margin-top:24px}}.audit-note{{color:var(--muted);font:11px/1.6 ui-monospace,Consolas,monospace}}footer{{display:flex;justify-content:space-between;gap:20px;padding:27px 58px;color:rgba(255,255,255,.72);background:#102d3f;font-size:12px}}
@media(max-width:900px){{.report{{width:100%;margin:0;border-radius:0}}.hero,main{{padding-left:22px;padding-right:22px}}.hero-thesis,.analysis-grid,.debate-grid,.synthesis-grid{{grid-template-columns:1fr}}.metric-grid{{grid-template-columns:repeat(2,1fr)}}.synthesis-section{{margin:0 -10px;padding-left:10px;padding-right:10px}}footer{{padding:24px 22px}}}}@media(max-width:560px){{.hero-top{{display:block}}.theme-toggle{{margin-top:14px}}.metric-grid{{grid-template-columns:1fr}}.section-heading{{display:block}}.lens-status{{display:inline-flex;margin-top:8px}}}}@media print{{.nav,.theme-toggle{{display:none}}.report{{width:100%;margin:0;border:0;box-shadow:none}}section{{break-inside:avoid}}}}
</style></head><body><div class="report"><header class="hero" id="overview"><div class="hero-top"><div><span class="kicker">V3 · Professional Research Narrative</span><h1>{_esc(company_name)}</h1><div class="hero-meta">{_esc(ticker)} · 截至 {_esc(run.as_of_date)} · {_esc(_completeness_label(run.analysis.completeness))}</div></div><button class="theme-toggle" type="button">切换主题</button></div><div class="hero-thesis"><div><span>核心研究论点</span><p>{_esc(executive)}</p></div><div><span>差异化视角</span><small>{_esc(variant)}</small></div></div></header>
<nav class="nav"><a href="#company">公司</a><a href="#industry">行业</a><a href="#fundamentals">基本面</a><a href="#technical">技术</a><a href="#sentiment-events">情绪与事件</a><a href="#valuation">估值</a><a href="#debate">质询</a><a href="#synthesis">综合观点</a><a href="#monitoring">复核计划</a><a href="#audit-appendix">审计附录</a></nav><main>{''.join(sections)}</main><footer><span>{_esc(company_name)} · {_esc(ticker)}</span><span>Run {_esc(run.run_id)} · Schema v{run.schema_version}</span></footer></div>
<script id="research-run-data" type="application/json">{payload}</script><script>(()=>{{const r=document.documentElement,b=document.querySelector('.theme-toggle');b?.addEventListener('click',()=>{{r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'}})}})();</script></body></html>"""
