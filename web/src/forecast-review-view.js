export function registrySummary(item) {
  const status = {
    reviewed: "已复核",
    due: "到期待复核",
    registered: "已登记",
  }[item.review_status] ?? item.review_status ?? "未知"
  return `${item.label ?? item.target_id} · ${item.horizon ?? "—"} · ${item.review_date ?? "—"} · ${status}`
}

export function forecastReviewSummary(review) {
  const numeric = review.numeric_results ?? []
  const comparable = numeric.filter(item => item.absolute_error != null).length
  const coverage = review.numeric_interval_coverage == null
    ? "区间覆盖率受限"
    : `区间覆盖率 ${(Number(review.numeric_interval_coverage) * 100).toFixed(1)}%`
  const calibration = review.calibration_version?.new_model_identity
    ? `新校准版本 ${review.calibration_version.new_model_identity}`
    : "未创建校准版本"
  return `${review.reviewed_at ?? "—"} · ${review.status ?? "—"} · 可比数值项 ${comparable} · ${coverage} · ${calibration}`
}

function text(value) {
  return value == null || value === "" ? "—" : String(value)
}

export function renderForecastReviewWorkspace(model) {
  const registryTarget = document.querySelector("#forecast-registry")
  const reviewsTarget = document.querySelector("#forecast-review-history")
  if (!registryTarget || !reviewsTarget) return
  const registry = model.forecast_registry ?? []
  registryTarget.replaceChildren(...(registry.length
    ? registry.map(item => {
        const li = document.createElement("li")
        li.textContent = registrySummary(item)
        li.dataset.status = text(item.review_status)
        return li
      })
    : [Object.assign(document.createElement("li"), {textContent: "当前没有已登记的 Forecast 复核项。"})]))
  const reviews = model.forecast_reviews ?? []
  reviewsTarget.replaceChildren(...(reviews.length
    ? reviews.map(review => {
        const article = document.createElement("article")
        const heading = document.createElement("h3")
        heading.textContent = `ForecastReview · ${text(review.model_identity)}`
        const summary = document.createElement("p")
        summary.textContent = forecastReviewSummary(review)
        const interpretation = document.createElement("p")
        interpretation.textContent = text(review.interpretation)
        const details = document.createElement("details")
        const label = document.createElement("summary")
        label.textContent = "展开误差、Driver 分解与校准 lineage"
        const payload = document.createElement("pre")
        payload.textContent = JSON.stringify({
          probability_results: review.probability_results,
          numeric_results: review.numeric_results,
          driver_error_decomposition: review.driver_error_decomposition,
          calibration_version: review.calibration_version,
          diagnostics: review.diagnostics,
        }, null, 2)
        details.append(label, payload)
        article.append(heading, summary, interpretation, details)
        return article
      })
    : [Object.assign(document.createElement("p"), {textContent: "尚无到期后的 ForecastReview；登记项仍保留。"})]))
}
