from __future__ import annotations

import html
import json
from decimal import Decimal, InvalidOperation

from trading_platform.domain.chart import ChartSeries


class ResearchChartError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def render_price_chart_html(subject: str, series: ChartSeries) -> bytes:
    """Render a self-contained accessible chart from one frozen series."""
    if not subject or not series.bars:
        raise ResearchChartError("RESEARCH_CHART_INPUT_INVALID")
    try:
        lows = tuple(Decimal(bar.low_decimal) for bar in series.bars)
        highs = tuple(Decimal(bar.high_decimal) for bar in series.bars)
        closes = tuple(Decimal(bar.close_decimal) for bar in series.bars)
    except InvalidOperation as error:
        raise ResearchChartError("RESEARCH_CHART_PRICE_INVALID") from error
    low = min(lows)
    high = max(highs)
    if low <= 0 or high < low:
        raise ResearchChartError("RESEARCH_CHART_PRICE_INVALID")
    span = high - low or Decimal("1")
    width = Decimal("920")
    height = Decimal("320")
    x_step = width / Decimal(max(1, len(closes) - 1))

    def point(index: int, value: Decimal) -> str:
        x = Decimal(index) * x_step
        y = height - (value - low) / span * height
        return f"{x.quantize(Decimal('0.01'))},{y.quantize(Decimal('0.01'))}"

    line = " ".join(point(index, value) for index, value in enumerate(closes))
    latest_rows = "".join(
        "<tr>"
        f"<td>{html.escape(bar.market_timestamp[:10])}</td>"
        f"<td>{html.escape(bar.open_decimal)}</td>"
        f"<td>{html.escape(bar.high_decimal)}</td>"
        f"<td>{html.escape(bar.low_decimal)}</td>"
        f"<td>{html.escape(bar.close_decimal)}</td>"
        f"<td>{html.escape(bar.volume_decimal)}</td>"
        "</tr>"
        for bar in series.bars[-10:]
    )
    encoded = json.dumps(
        {
            "subject": subject,
            "effective_session_date": series.effective_session_date,
            "freshness": series.freshness,
            "bars": [bar.__dict__ for bar in series.bars],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(subject)} 价格图表</title>
<style>
:root{{--ink:#17242c;--muted:#657780;--line:#dce5e8;--paper:#fff;--bg:#edf3f5;--accent:#176b87}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,"Microsoft YaHei",sans-serif}}
main{{width:min(1060px,calc(100% - 28px));margin:28px auto;background:var(--paper);border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 18px 50px rgba(20,45,58,.1)}}
header,section{{padding:28px 36px;border-bottom:1px solid var(--line)}}h1{{margin:.25rem 0}}p{{color:var(--muted)}}svg{{display:block;width:100%;height:auto;background:linear-gradient(#f8fbfc,#fff);border:1px solid var(--line);border-radius:14px;padding:20px}}.axis{{display:flex;justify-content:space-between;color:var(--muted);margin-top:8px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{background:#f3f7f8}}
</style></head><body><main>
<header><small>截至 {html.escape(series.effective_session_date)} · {html.escape(series.freshness)}</small><h1>{html.escape(subject)} 收盘价</h1><p>来自同一冻结市场数据快照；仅用于研究与纪律复核，不构成行动建议。</p></header>
<section aria-label="价格走势图"><svg viewBox="0 0 920 320" role="img" aria-label="{html.escape(subject)} 收盘价折线图"><polyline fill="none" stroke="#176b87" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="{line}"/></svg><div class="axis"><span>{html.escape(series.bars[0].market_timestamp[:10])}</span><span>区间 {low} – {high}</span><span>{html.escape(series.bars[-1].market_timestamp[:10])}</span></div></section>
<section><h2>最近 10 个会话</h2><table><thead><tr><th>日期</th><th>开</th><th>高</th><th>低</th><th>收</th><th>成交量</th></tr></thead><tbody>{latest_rows}</tbody></table></section>
<script type="application/json" id="chart-data">{encoded}</script>
</main></body></html>"""
    return document.encode("utf-8")


__all__ = ["ResearchChartError", "render_price_chart_html"]