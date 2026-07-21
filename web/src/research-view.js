export function selectResearchView(views, viewId) {
  return views.find(view => view.view_id === viewId) ?? null
}

export function researchViewLabel(view, index) {
  const snapshot = String(view.model_data_snapshot_identity ?? view.data_snapshot_id ?? "unknown")
  const shortSnapshot = snapshot.length > 12 ? snapshot.slice(0, 12) : snapshot
  return `${index + 1}. ${view.as_of ?? "—"} · ${view.model_identity ?? "—"} · ${view.policy_identity ?? "—"} · 数据 ${shortSnapshot}`
}

export function formatQuantity(quantity) {
  if (!quantity) return "—"
  const numericValue = Number(quantity.value)
  const value = Number.isFinite(numericValue)
    ? new Intl.NumberFormat("zh-CN", {
        maximumFractionDigits: quantity.unit === "decimal" ? 4 : 2,
        minimumFractionDigits: 0,
      }).format(numericValue)
    : quantity.value ?? "—"
  const suffix = quantity.unit === "decimal" ? "" : ` ${quantity.unit ?? ""}`
  return `${value}${suffix}`.trim()
}

export function formatPercent(quantity) {
  if (!quantity) return "—"
  const numericValue = Number(quantity.value)
  if (!Number.isFinite(numericValue)) return String(quantity.value ?? "—")
  return new Intl.NumberFormat("zh-CN", {
    style: "percent",
    maximumFractionDigits: 1,
    minimumFractionDigits: 0,
  }).format(numericValue)
}

function horizonLabel(value) {
  const horizon = String(value ?? "未声明期限")
  return horizon.split(";").map(part => {
    if (part.startsWith("valuation_as_of=")) return `估值时点 ${part.slice("valuation_as_of=".length)}`
    if (part.startsWith("terminal_period=")) return `终值期 ${part.slice("terminal_period=".length)}`
    if (part.startsWith("cash_flows=")) return `现金流期间 ${part.slice("cash_flows=".length)}`
    if (part.startsWith("market_as_of=")) return `市场截至 ${part.slice("market_as_of=".length)}`
    return part
  }).join("；")
}

function basisLabel(value) {
  if (value === "enterprise_value") return "企业价值口径；股权桥完整时才继续转换"
  if (value === "equity_value") return "股权价值口径"
  return String(value ?? "未声明价值口径")
}

export function methodSummary(method) {
  const range = method.conditional_value_range
  const level = {
    basis_value: "企业价值",
    equity_value: "股权价值",
    per_share_value: "每股价值",
  }[method.display_value_level] ?? "条件价值"
  const value = range
    ? `${formatQuantity(range.low)} / ${formatQuantity(range.base)} / ${formatQuantity(range.high)}`
    : `受限：${method.display_applicability ?? method.applicability ?? "输入不足"}`
  const diagnostics = method.display_diagnostics ?? method.diagnostics ?? []
  const warning = diagnostics.length ? ` · 注意：${diagnostics.join("；")}` : ""
  return `${method.method_id} · ${level} ${value} · ${basisLabel(method.value_basis)} · ${horizonLabel(method.horizon)}${warning}`
}

export function persistedResearchHtml(view) {
  return view.html_projection ?? "<p>持久化研究 HTML 缺失。</p>"
}
