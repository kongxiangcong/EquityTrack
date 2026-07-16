function escapeHtml(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;")
}

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
  if (value === "enterprise_value") return "企业价值口径，经股权桥转换为每股值"
  if (value === "equity_value") return "股权价值口径"
  return String(value ?? "未声明价值口径")
}

export function methodSummary(method) {
  const range = method.conditional_per_share_range
  const value = range
    ? `${formatQuantity(range.low)} / ${formatQuantity(range.base)} / ${formatQuantity(range.high)}`
    : `受限：${method.display_applicability ?? method.applicability ?? "输入不足"}`
  const diagnostics = method.display_diagnostics ?? method.diagnostics ?? []
  const warning = diagnostics.length ? ` · 注意：${diagnostics.join("；")}` : ""
  return `${method.method_id} · ${value} · ${basisLabel(method.value_basis)} · ${horizonLabel(method.horizon)}${warning}`
}

function list(items) {
  return `<ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
}

export function renderSandboxReport(view) {
  const story = view.story ?? {}
  const scenarioHtml = (view.scenarios ?? []).map(scenario => {
    const financials = (scenario.financials ?? [])
      .map(item => `<li><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(formatQuantity(item))}</span></li>`)
      .join("")
    const methods = (scenario.methods ?? [])
      .map(method => `<li>${escapeHtml(methodSummary(method))}</li>`)
      .join("")
    return `<article><p class="eyebrow">${escapeHtml(scenario.role)}</p><h3>${escapeHtml(scenario.label)}情景</h3><p>${escapeHtml(scenario.terminal_period)}</p><h4>关键财务</h4><ul class="metrics">${financials}</ul><h4>方法级条件每股价值区间</h4><ul class="metrics">${methods}</ul></article>`
  }).join("")
  const drivers = (view.key_drivers ?? []).map(item => `<li><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(formatQuantity(item))} · ${escapeHtml(item.period)}</span></li>`).join("")
  const implied = (view.market_implied_expectations ?? []).map(item => `<li><strong>${escapeHtml(item.scenario_label)}情景</strong><span>${escapeHtml(formatPercent(item.base))} · ${escapeHtml(item.explanation)}</span></li>`).join("")
  const simulation = view.valuation_simulation
  const simulationAssumptions = (simulation?.assumptions ?? []).map(item => {
    const calibration = item.calibration ?? {}
    return `${item.assumption_id} · ${item.family} · reference ${item.reference_value} ${item.unit} · sample ${calibration.sample_id} · ${calibration.window_start}–${calibration.window_end} · available ${calibration.available_at} · override ${item.user_override_identity ?? "无"}`
  })
  const fallback = simulation?.deterministic_fallback ?? {}
  const simulationHtml = simulation
    ? `<section><p class="eyebrow">Valuation Simulation · 条件分布</p><h2>校准后的每股价值分布</h2><p>${escapeHtml(simulation.converged ? "已通过收敛门禁" : "模拟受限，保留确定性情景")}</p><ul class="metrics">${Object.entries(simulation.quantiles ?? {}).map(([key, quantity]) => `<li><strong>${escapeHtml(key.toUpperCase())}</strong><span>${escapeHtml(formatQuantity(quantity))}</span></li>`).join("")}</ul><h3>关键变量贡献</h3>${list((simulation.contributions ?? []).map(item => `${item.assumption_id} · ${formatPercent({value:item.share,unit:"decimal"})}`))}<p>RNG ${escapeHtml(simulation.rng_algorithm)} · seed ${escapeHtml(simulation.seed)} · 样本预算 ${escapeHtml(simulation.sample_budget)} · 无效路径率 ${escapeHtml(simulation.invalid_path_rate)}</p><details><summary>展开分布校准、依赖结构与降级依据</summary><h3>随机变量与点时校准</h3>${list(simulationAssumptions)}<h3>依赖结构</h3><pre>${escapeHtml(JSON.stringify(simulation.dependency_model ?? {}, null, 2))}</pre><h3>确定性估值锚</h3><p>${escapeHtml(`${fallback.scenario_id} / ${fallback.method_id} / ${fallback.formula_version} · ${fallback.low} / ${fallback.base} / ${fallback.high} ${fallback.unit}`)}</p><h3>诊断</h3>${list(simulation.diagnostics ?? [])}</details></section>`
    : ""
  const marketPath = view.market_price_paths
  const divergence = view.value_market_divergence
  const marketPathHtml = marketPath
    ? `<section><p class="eyebrow">Market Path · 市场交易价格路径</p><h2>状态条件下的价格与回撤分布</h2><p>${escapeHtml(marketPath.interpretation)}</p><p>${escapeHtml(divergence?.explanation)}</p><ul class="metrics">${Object.entries(marketPath.terminal_price_quantiles ?? {}).map(([key, quantity]) => `<li><strong>${escapeHtml(`终点 ${key.toUpperCase()}`)}</strong><span>${escapeHtml(formatQuantity(quantity))}</span></li>`).join("")}</ul><h3>期限收益与最大回撤</h3><p>P50 收益 ${escapeHtml(formatPercent(marketPath.horizon_return_quantiles?.p50))} · P50 最大回撤 ${escapeHtml(formatPercent(marketPath.maximum_drawdown_quantiles?.p50))}</p><h3>阈值触发与尾部</h3>${list([...(marketPath.threshold_trigger_probabilities ?? []).map(item => `${item.threshold} ${marketPath.price_unit} · ${formatPercent({value:item.probability,unit:"decimal"})}`), marketPath.tail_results ? `收益低于 ${formatPercent({value:marketPath.tail_results.return_threshold,unit:"decimal"})} · ${formatPercent({value:marketPath.tail_results.probability_below_threshold,unit:"decimal"})}` : "尾部结果受限"])}<details><summary>展开区块样本、市场状态、成本与交易限制</summary><pre>${escapeHtml(JSON.stringify({horizon_return_basis:marketPath.horizon_return_basis,execution_period:marketPath.execution_period,terminal_period:marketPath.terminal_period,risk_horizon_period:marketPath.risk_horizon_period,starting_price:marketPath.starting_price,starting_price_available_at:marketPath.starting_price_available_at,starting_price_evidence_refs:marketPath.starting_price_evidence_refs,current_market_state:marketPath.current_market_state,current_state_available_at:marketPath.current_state_available_at,current_state_evidence_refs:marketPath.current_state_evidence_refs,calibration:marketPath.calibration,constraints:marketPath.constraints,budget:marketPath.budget}, null, 2))}</pre></details></section>`
    : ""
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>研究推演视图</title><style>:root{font:16px/1.6 system-ui;color:#182230;background:#f5f6f8}*{box-sizing:border-box}body{margin:0;padding:clamp(16px,4vw,48px)}main{max-width:1100px;margin:auto}header,article,section{min-width:0;background:#fff;border:1px solid #d8dde5;border-radius:18px;padding:clamp(16px,3vw,30px);margin:14px 0}.eyebrow{font-size:.75rem;letter-spacing:.14em;text-transform:uppercase;color:#4d6178}.scenarios{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.metrics{padding:0;list-style:none}.metrics li{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #edf0f3;overflow-wrap:anywhere}.boundary{border-left:4px solid #365f86}@media(max-width:760px){.scenarios{grid-template-columns:minmax(0,1fr)}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}</style></head><body><main><header><p class="eyebrow">${escapeHtml(view.schema_version ?? "ResearchDecisionView@2")}</p><h1>${escapeHtml(view.subject_id)} · 公司未来推演</h1><p>截至 ${escapeHtml(view.as_of)} · ${escapeHtml(view.model_identity)} · ${escapeHtml(view.policy_identity)}</p></header><section><p class="eyebrow">Forecast / Judgment / Risk · 推演、判断与反证</p><h2>核心故事</h2><h3>Forecast · 发生什么</h3><p>${escapeHtml(story.what_happens)}</p><h3>Judgment · 为什么重要</h3><p>${escapeHtml(story.why_it_matters)}</p><h3>Model logic · 如何传导</h3>${list(story.transmission ?? [])}<h3>Risk · 反例</h3>${list(story.counterevidence ?? [])}<h3>Review condition · 什么会改变判断</h3>${list(story.what_would_change_the_view ?? [])}</section><section><p class="eyebrow">Forecast · 推演值，不是已观察事实</p><h2>关键业务 Driver</h2><ul class="metrics">${drivers}</ul></section><section><p class="eyebrow">Forecast → Valuation · 条件结果</p><h2>三种条件情景</h2><div class="scenarios">${scenarioHtml}</div></section>${simulationHtml}${marketPathHtml}<section><p class="eyebrow">Valuation · 市场反推</p><h2>当前价格隐含预期</h2><ul class="metrics">${implied}</ul></section><p class="boundary">${escapeHtml(view.boundary)}</p></main></body></html>`
}
