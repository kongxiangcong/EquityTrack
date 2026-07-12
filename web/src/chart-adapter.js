export const ALLOWED_KINDS = new Set(["trend_line", "horizontal_line", "note"])

export function toKLineData(series) {
  if (series.interval !== "1d" || series.adjustment_mode !== "none") throw new Error("CHART_MAPPING_UNAVAILABLE")
  return series.bars.map(bar => ({
    timestamp: Date.parse(bar.market_timestamp), open: Number(bar.open_decimal), high: Number(bar.high_decimal),
    low: Number(bar.low_decimal), close: Number(bar.close_decimal), volume: Number(bar.volume_decimal)
  }))
}

export function toOverlay(version) {
  if (!ALLOWED_KINDS.has(version.draft.kind)) throw new Error("ANNOTATION_KIND_INVALID")
  return {
    name: version.draft.kind === "horizontal_line" ? "horizontalStraightLine" : "segment",
    id: version.annotation_id,
    points: version.draft.anchors.map(anchor => ({timestamp: Date.parse(anchor.market_timestamp), value: Number(anchor.exact_price_decimal)})),
    styles: {line: {color: version.draft.style === "warning" ? "#c76532" : "#1677ff"}}
  }
}

export function fromConfirmedPoints(points, context) {
  if (!Array.isArray(points) || points.length < 1 || points.some(point => !Number.isFinite(point.timestamp) || !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(point.exactPriceDecimal))) throw new Error("ANNOTATION_POINTS_INVALID")
  return {
    ...context,
    anchors: points.map(point => ({market_timestamp: new Date(point.timestamp).toISOString(), exact_price_decimal: point.exactPriceDecimal}))
  }
}
