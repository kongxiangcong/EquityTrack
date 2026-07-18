from __future__ import annotations

import html
import json
from typing import Any, Mapping

from trading_platform.research_view import ResearchDecisionView


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _quantity(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "—"
    raw = value.get("value")
    unit = value.get("unit") or ""
    return f"{raw} {unit}".strip() if raw is not None else "—"


def render_research_decision_html(
    view: ResearchDecisionView | Mapping[str, Any],
) -> str:
    """Render the canonical decision-first view without recalculating it."""

    payload = view.to_dict() if isinstance(view, ResearchDecisionView) else dict(view)
    story = payload.get("story") if isinstance(payload.get("story"), Mapping) else {}
    scenarios = payload.get("scenarios") if isinstance(payload.get("scenarios"), (list, tuple)) else ()
    drivers = payload.get("key_drivers") if isinstance(payload.get("key_drivers"), (list, tuple)) else ()
    audit = payload.get("audit") if isinstance(payload.get("audit"), Mapping) else {}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    story_blocks = "".join(
        f"<article><h3>{_esc(label)}</h3><ul>"
        + "".join(
            f"<li>{_esc(item)}</li>"
            for item in (
                value
                if isinstance(value, (list, tuple))
                else (value,)
            )
        )
        + "</ul></article>"
        for key, label in (
            ("core_thesis", "核心故事"),
            ("variant_view", "市场可能忽略什么"),
            ("business_quality", "业务质量"),
            ("earnings_outlook", "盈利推演"),
            ("what_happens", "未来会发生什么"),
            ("why_it_matters", "为什么重要"),
            ("transmission", "如何传导到经营与价值"),
            ("valuation_view", "估值视角"),
            ("valuation_guardrails", "估值边界与选择权"),
            ("risk_reward_summary", "潜在改善与主要约束"),
            ("key_uncertainties", "关键不确定性"),
            ("counterevidence", "反证与不确定性"),
            ("what_would_change_the_view", "什么会改变当前判断"),
        )
        for value in (story.get(key, ()),)
        if (
            isinstance(value, (str, list, tuple))
            and value
        )
    )
    driver_rows = "".join(
        "<tr>"
        f"<td>{_esc(item.get('metric_id'))}</td>"
        f"<td>{_quantity(item)}</td>"
        f"<td>{_esc(item.get('period'))}</td>"
        "</tr>"
        for item in drivers
        if isinstance(item, Mapping)
    )
    scenario_sections = ""
    value_level_labels = {
        "basis_value": "条件企业价值基准值",
        "equity_value": "条件股权价值基准值",
        "per_share_value": "条件每股基准值",
    }
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            continue
        method_rows = "".join(
            "<tr>"
            f"<td>{_esc(method.get('method_id'))}</td>"
            f"<td>{_esc(method.get('status'))}</td>"
            f"<td>{_esc(method.get('display_applicability'))}</td>"
            f"<td>{_esc(value_level_labels.get(method.get('display_value_level'), '条件价值基准值'))}</td>"
            f"<td>{_quantity((method.get('conditional_value_range') or {}).get('base'))}</td>"
            f"<td>{_esc(method.get('horizon'))}</td>"
            "</tr>"
            for method in scenario.get("methods", ())
            if isinstance(method, Mapping)
        )
        scenario_sections += (
            f"<section><div class='section-head'><h2>{_esc(scenario.get('label'))}情景</h2>"
            f"<span>{_esc(scenario.get('terminal_period'))}</span></div>"
            "<div class='table-wrap'><table><thead><tr>"
            "<th>方法</th><th>状态</th><th>适用性</th><th>价值层级</th><th>条件基准值</th><th>期限</th>"
            f"</tr></thead><tbody>{method_rows}</tbody></table></div></section>"
        )
    artifacts = audit.get("artifact_records", ())
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
@media(max-width:640px){{header,section,footer{{padding-left:20px;padding-right:20px}}}}
</style></head><body><main>
<header><small>{_esc(payload.get('schema_version'))} · {_esc(payload.get('as_of'))}</small>
<h1>{_esc(payload.get('subject_id'))} 公司未来推演</h1>
<p>故事、Driver、情景和估值来自同一组不可变 Forecast / Valuation artifacts。</p></header>
<section><h2>未来故事</h2><div class="story">{story_blocks or '<p>当前 typed artifacts 未形成可展示故事。</p>'}</div></section>
<section><h2>关键 Driver</h2><div class="table-wrap"><table><thead><tr><th>指标</th><th>数值</th><th>期间</th></tr></thead><tbody>{driver_rows}</tbody></table></div></section>
{scenario_sections}
<section><h2>审计附录</h2><div class="table-wrap"><table><thead><tr><th>Artifact</th><th>Schema</th><th>Hash</th><th>状态</th></tr></thead><tbody>{artifact_rows}</tbody></table></div></section>
<footer>{_esc(payload.get('boundary'))}</footer>
</main><script type="application/json" id="research-decision-view">{canonical}</script></body></html>"""
