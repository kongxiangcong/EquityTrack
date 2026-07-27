/*
 * PROTOTYPE ONLY — throwaway UI for one Wayfinder decision.
 * Three radically different variants share one fixture and one serialized state.
 */

(() => {
  "use strict";

  const STORAGE_KEY = "PROTOTYPE_WIPE_ME_chart_annotation_v1";
  const VARIANTS = ["A", "B", "C"];
  const VARIANT_NAMES = {
    A: "证据优先控制台",
    B: "画布优先驾驶舱",
    C: "版本账本工作台",
  };

  const app = document.querySelector("#app");
  let fixture = null;
  let state = null;
  let chart = null;
  let restoringOverlay = false;

  const escapeHtml = (value) =>
    String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  function initialState() {
    return {
      schema: "chart-prototype-state@1",
      source_snapshot_id: fixture.snapshot.data_snapshot_id,
      active_view: {
        interval: fixture.snapshot.interval,
        adjustment_mode: fixture.snapshot.adjustment_mode,
        data_snapshot_id: fixture.snapshot.data_snapshot_id,
        factor_snapshot_id: fixture.snapshot.factor_snapshot_id,
      },
      proposed_view: null,
      mapping_resolution: "exact",
      availability: "available",
      annotation_versions: [],
      last_event: {
        type: "prototype_initialized",
        at: new Date().toISOString(),
        detail: "No domain mutation yet.",
      },
    };
  }

  function loadState() {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialState();
    try {
      const parsed = JSON.parse(raw);
      if (parsed.schema !== "chart-prototype-state@1") return initialState();
      if (parsed.source_snapshot_id !== fixture.snapshot.data_snapshot_id) return initialState();
      return parsed;
    } catch {
      return initialState();
    }
  }

  function persistState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function currentVariant() {
    const value = new URLSearchParams(location.search).get("variant")?.toUpperCase();
    return VARIANTS.includes(value) ? value : "A";
  }

  function latestVersion() {
    return state.annotation_versions.at(-1) ?? null;
  }

  function activeVersion() {
    const latest = latestVersion();
    return latest?.status === "active" ? latest : null;
  }

  function latestNonDeletedVersion() {
    return [...state.annotation_versions].reverse().find((item) => item.status === "active") ?? null;
  }

  function marketBars() {
    return fixture.bars.map((bar) => ({
      timestamp: Date.parse(bar.timestamp),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: bar.volume,
      turnover: bar.turnover,
    }));
  }

  function normalizeOverlayPoints(points) {
    if (!Array.isArray(points) || points.length < 2) return null;
    const barTimestamps = new Set(fixture.bars.map((bar) => Date.parse(bar.timestamp)));
    const normalized = points.slice(0, 2).map((point) => ({
      timestampMs: Number(point.timestamp),
      price: Number(point.value),
    }));

    if (
      normalized.some(
        (point) =>
          !Number.isFinite(point.timestampMs) ||
          !Number.isFinite(point.price) ||
          !barTimestamps.has(point.timestampMs),
      )
    ) {
      return null;
    }

    return normalized.map((point) => ({
      timestamp: new Date(point.timestampMs).toISOString(),
      price: point.price.toFixed(2),
    }));
  }

  function appendActiveVersion(anchors, reason) {
    const previous = latestVersion();
    const version = (previous?.version ?? 0) + 1;
    const annotationId = previous?.annotation_id ?? "ca_proto_002897_001";
    const item = {
      annotation_id: annotationId,
      annotation_version_id: `cav_proto_002897_${String(version).padStart(3, "0")}`,
      version,
      supersedes_version_id: previous?.annotation_version_id ?? null,
      status: "active",
      security_id: fixture.security.security_id,
      type: "trend_line",
      interval: state.active_view.interval,
      adjustment_mode: state.active_view.adjustment_mode,
      data_snapshot_id: state.active_view.data_snapshot_id,
      factor_snapshot_id: state.active_view.factor_snapshot_id,
      price_basis: "display_view",
      anchors,
      text: "用户标注：观察区间",
      style: { color: "#8ef0bf", line_width: 2 },
      links: fixture.domain_links,
      author: "local-user",
      created_at: new Date().toISOString(),
      change_reason: reason,
    };
    state.annotation_versions.push(item);
    state.last_event = {
      type: version === 1 ? "annotation_created" : "annotation_version_appended",
      at: item.created_at,
      detail: `${item.annotation_version_id} via ${reason}`,
    };
    persistState();
    render();
  }

  function appendTombstone() {
    const current = activeVersion();
    if (!current) return;
    const version = current.version + 1;
    const tombstone = {
      ...current,
      annotation_version_id: `cav_proto_002897_${String(version).padStart(3, "0")}`,
      version,
      supersedes_version_id: current.annotation_version_id,
      status: "deleted",
      created_at: new Date().toISOString(),
      change_reason: "user_deleted_tombstone",
    };
    state.annotation_versions.push(tombstone);
    state.last_event = {
      type: "annotation_tombstoned",
      at: tombstone.created_at,
      detail: `${tombstone.annotation_version_id}; prior versions retained`,
    };
    persistState();
    render();
  }

  function restoreDeleted() {
    const previous = latestNonDeletedVersion();
    if (!previous || latestVersion()?.status !== "deleted") return;
    appendActiveVersion(previous.anchors, "restore_after_tombstone");
  }

  function nudgeVersion() {
    const current = activeVersion();
    if (!current) return;
    const anchors = current.anchors.map((anchor, index) => ({
      ...anchor,
      price: index === 1 ? (Number(anchor.price) + 0.5).toFixed(2) : anchor.price,
    }));
    appendActiveVersion(anchors, "prototype_nudge_second_anchor_plus_0_50");
  }

  function markMappingUnresolved(interval, adjustmentMode) {
    if (interval === state.active_view.interval && adjustmentMode === state.active_view.adjustment_mode) {
      state.proposed_view = null;
      state.mapping_resolution = "exact";
    } else {
      state.proposed_view = {
        interval,
        adjustment_mode: adjustmentMode,
        requested_factor_snapshot_id:
          adjustmentMode === "none" ? null : fixture.available_factor_snapshot.factor_snapshot_id,
      };
      state.mapping_resolution = "unresolved_requires_confirmation";
    }
    state.last_event = {
      type: "view_mapping_evaluated",
      at: new Date().toISOString(),
      detail:
        state.mapping_resolution === "exact"
          ? "Existing immutable view retained."
          : "No derived snapshot/bucket mapping is available; coordinates were not moved.",
    };
    persistState();
    render();
  }

  function cycleAvailability() {
    const order = ["available", "stale", "missing"];
    state.availability = order[(order.indexOf(state.availability) + 1) % order.length];
    state.last_event = {
      type: "prototype_availability_changed",
      at: new Date().toISOString(),
      detail: `Simulated state: ${state.availability}`,
    };
    persistState();
    render();
  }

  function serializedState() {
    return {
      prototype_only: true,
      security: fixture.security,
      snapshot: fixture.snapshot,
      state,
      persistence: {
        adapter: "browser_localStorage",
        scratch_key: STORAGE_KEY,
        note: "PROTOTYPE — wipe me; not the platform database",
      },
    };
  }

  function availabilityChip() {
    const details = {
      available: ["good", "数据可用 · 当日能力开放"],
      stale: ["warn", "数据陈旧 · 当日评估阻断"],
      missing: ["block", "数据缺失 · 图表阻断"],
    };
    const [kind, label] = details[state.availability];
    return `<span class="chip ${kind}">${label}</span>`;
  }

  function identityChips() {
    return `
      <div class="chip-row">
        <span class="chip"><strong>${escapeHtml(fixture.security.ticker)}</strong> · ${escapeHtml(fixture.security.exchange)}</span>
        <span class="chip"><strong>未复权</strong> · 1 日</span>
        <span class="chip"><strong>截至</strong> 2026-07-10 15:00 CST</span>
        <span class="chip"><strong>DataSnapshot</strong> <span class="mono">${escapeHtml(fixture.snapshot.data_snapshot_id)}</span></span>
        ${availabilityChip()}
      </div>`;
  }

  function mappingCallout() {
    if (state.mapping_resolution === "exact") {
      return `<div class="callout good">当前坐标精确引用冻结的未复权日线视图。刷新、变体切换和服务重启不会重算锚点。</div>`;
    }
    return `
      <div class="callout block">
        <strong>unresolved / requires_confirmation</strong><br />
        请求 ${escapeHtml(state.proposed_view.interval)} · ${escapeHtml(state.proposed_view.adjustment_mode)}，但原型没有对应的派生 DataSnapshot、周/月 bucket 或已验证坐标变换。原标注仍停留在 ${escapeHtml(state.active_view.interval)} · ${escapeHtml(state.active_view.adjustment_mode)}，没有按最近 bar、数组索引或像素静默吸附。
        <div class="btn-row" style="margin-top:9px"><button class="btn ghost" data-action="keep-original-view">保持原视图</button></div>
      </div>`;
  }

  function controlsHtml(compact = false) {
    const selectedInterval = state.proposed_view?.interval ?? state.active_view.interval;
    const selectedAdjustment =
      state.proposed_view?.adjustment_mode ?? state.active_view.adjustment_mode;
    const active = activeVersion();
    const deleted = latestVersion()?.status === "deleted";
    return `
      <div class="${compact ? "" : "field-row"}">
        <div class="field">
          <label>展示周期（只提出映射请求）</label>
          <select data-action="view-interval">
            <option value="1d" ${selectedInterval === "1d" ? "selected" : ""}>日线 1d</option>
            <option value="1w" ${selectedInterval === "1w" ? "selected" : ""}>周线 1w</option>
            <option value="1m" ${selectedInterval === "1m" ? "selected" : ""}>月线 1m</option>
          </select>
        </div>
        <div class="field" ${compact ? 'style="margin-top:8px"' : ""}>
          <label>复权语义（只提出映射请求）</label>
          <select data-action="view-adjustment">
            <option value="none" ${selectedAdjustment === "none" ? "selected" : ""}>不复权 none</option>
            <option value="forward" ${selectedAdjustment === "forward" ? "selected" : ""}>前复权 forward</option>
            <option value="backward" ${selectedAdjustment === "backward" ? "selected" : ""}>后复权 backward</option>
          </select>
        </div>
      </div>
      <div class="btn-row" style="margin-top:11px">
        <button class="btn primary" data-action="draw" ${active || state.availability === "missing" ? "disabled" : ""}>${deleted ? "已删除，可恢复" : "画一条趋势线"}</button>
        <button class="btn" data-action="nudge" ${active ? "" : "disabled"}>第二锚点 +0.50 并保存新版本</button>
        <button class="btn danger" data-action="delete" ${active ? "" : "disabled"}>删除为 tombstone</button>
        <button class="btn warn" data-action="restore" ${deleted ? "" : "disabled"}>从 tombstone 恢复</button>
        <button class="btn ghost" data-action="availability">模拟数据状态：${escapeHtml(state.availability)}</button>
      </div>`;
  }

  function annotationSummary() {
    const current = latestVersion();
    if (!current) {
      return `<div class="callout">尚无 ChartAnnotation。点击“画一条趋势线”，再依次点击起点、终点和最终确认；只有两个锚点会进入领域 DTO。</div>`;
    }
    return `
      <dl class="meta-list">
        <div class="meta-row"><dt>逻辑身份</dt><dd class="mono">${escapeHtml(current.annotation_id)}</dd></div>
        <div class="meta-row"><dt>当前版本</dt><dd><span class="mono">${escapeHtml(current.annotation_version_id)}</span> · ${escapeHtml(current.status)}</dd></div>
        <div class="meta-row"><dt>坐标</dt><dd class="mono">${current.anchors.map((a) => `${escapeHtml(a.timestamp)} @ ${escapeHtml(a.price)}`).join("<br />")}</dd></div>
        <div class="meta-row"><dt>快照引用</dt><dd class="mono">${escapeHtml(current.data_snapshot_id)} / factor=${escapeHtml(current.factor_snapshot_id)}</dd></div>
        <div class="meta-row"><dt>作者 / 创建</dt><dd>${escapeHtml(current.author)} / ${escapeHtml(current.created_at)}</dd></div>
      </dl>`;
  }

  function linksHtml() {
    return `<div class="link-list">${fixture.domain_links
      .map(
        (link) =>
          `<div class="link-item"><span class="chip">${escapeHtml(link.type)}</span><div>${escapeHtml(link.label)}<br /><code>${escapeHtml(link.id)}</code></div></div>`,
      )
      .join("")}</div>`;
  }

  function versionsHtml() {
    if (!state.annotation_versions.length) {
      return `<p class="prototype-subtitle">版本账本为空。图库运行时对象不会写入这里。</p>`;
    }
    return `<div class="version-list">${[...state.annotation_versions]
      .reverse()
      .map(
        (item, index) => `
          <article class="version-item ${index === 0 ? "active" : ""} ${item.status === "deleted" ? "deleted" : ""}">
            <header><strong>v${item.version} · ${escapeHtml(item.status)}</strong><span class="mono">${escapeHtml(item.annotation_version_id)}</span></header>
            <p>${escapeHtml(item.change_reason)}<br />supersedes: ${escapeHtml(item.supersedes_version_id)}</p>
          </article>`,
      )
      .join("")}</div>`;
  }

  function stateHtml() {
    return `<pre class="state-pre">${escapeHtml(JSON.stringify(serializedState(), null, 2))}</pre>`;
  }

  function chartHtml() {
    if (state.availability === "missing") {
      return `
        <div class="chart-wrap">
          <div class="chart-empty"><div><strong>DATA_SNAPSHOT_MISSING</strong><span>没有合法缓存时不渲染假 K 线，也不允许创建标注。已有版本账本仍可审计。</span></div></div>
        </div>`;
    }
    return `<div class="chart-wrap"><div id="chart" class="chart-host" aria-label="意华股份未复权日 K 线与成交量"></div></div>`;
  }

  function switcherHtml(variant) {
    return `
      <nav class="prototype-switcher" aria-label="原型变体切换">
        <button data-action="previous-variant" aria-label="上一个变体">←</button>
        <span>${variant} — ${VARIANT_NAMES[variant]}</span>
        <button data-action="next-variant" aria-label="下一个变体">→</button>
      </nav>`;
  }

  function variantA() {
    return `
      <main class="prototype-shell variant-a">
        <header class="a-header">
          <div>
            <div class="prototype-kicker">Prototype only · Variant A</div>
            <h1 class="prototype-title">证据优先控制台</h1>
            <p class="prototype-subtitle">先固定“这张图是什么数据”，再允许标注。适合审计密度高、需要随时解释坐标来源的工作台。</p>
          </div>
          ${identityChips()}
        </header>
        <section class="a-grid">
          <article class="panel chart-panel">
            <div class="panel-head"><div><h2>意华股份 · 未复权日线</h2><p>真实离线 fixture · 29 bars · KLineChart 10.0.0</p></div><span class="chip">VOL</span></div>
            ${chartHtml()}
          </article>
          <aside class="a-side">
            <section class="panel"><div class="panel-head"><div><h3>标注命令</h3><p>图库事件 → 领域版本</p></div></div><div class="panel-body">${controlsHtml()}<div style="margin-top:12px">${mappingCallout()}</div></div></section>
            <section class="panel"><div class="panel-head"><div><h3>当前 ChartAnnotation</h3><p>稳定身份，不保存 pixel/dataIndex</p></div></div><div class="panel-body">${annotationSummary()}</div></section>
            <section class="panel"><div class="panel-head"><div><h3>完整相关状态</h3><p>每次操作后立即刷新</p></div><button class="btn danger" data-action="clear">清空原型状态</button></div><div class="panel-body">${stateHtml()}</div></section>
          </aside>
        </section>
        ${switcherHtml("A")}
      </main>`;
  }

  function variantB() {
    return `
      <main class="prototype-shell variant-b">
        <section class="b-stage">
          <div class="b-chart">${chartHtml()}</div>
          <header class="b-topbar">
            <div class="b-identity">
              <div class="prototype-kicker">Prototype only · Variant B</div>
              <h1>${escapeHtml(fixture.security.name)} <span class="mono">${escapeHtml(fixture.security.ticker)}</span></h1>
              <div class="chip-row" style="margin-top:8px">${availabilityChip()}<span class="chip">未复权 · 日线</span><span class="chip">截至 07-10</span></div>
            </div>
            <div class="b-tools">${controlsHtml(true)}</div>
          </header>
          <footer class="b-bottom">
            <section class="b-strip">
              <div class="prototype-kicker">Canvas-first context rail</div>
              <div style="margin-top:9px">${mappingCallout()}</div>
              <div class="chip-row" style="margin-top:9px"><span class="chip"><strong>snapshot</strong> ${escapeHtml(fixture.snapshot.data_snapshot_id)}</span><span class="chip"><strong>annotation</strong> ${escapeHtml(latestVersion()?.annotation_version_id ?? "none")}</span></div>
            </section>
            <section class="b-state">
              <details open><summary>完整相关状态 · ${state.annotation_versions.length} 个版本</summary>${stateHtml()}</details>
            </section>
          </footer>
        </section>
        ${switcherHtml("B")}
      </main>`;
  }

  function variantC() {
    return `
      <main class="prototype-shell variant-c">
        <header class="c-header">
          <div>
            <div class="prototype-kicker">Prototype only · Variant C</div>
            <h1 class="prototype-title">版本账本工作台</h1>
            <p class="prototype-subtitle">把不可变历史放在第一视觉层级；图表是版本账本的投影，而不是状态权威。</p>
          </div>
          ${identityChips()}
        </header>
        <section class="c-grid">
          <aside class="c-ledger">
            <section class="panel"><div class="panel-head"><div><h2>标注版本账本</h2><p>append-only · tombstone delete</p></div></div><div class="panel-body">${versionsHtml()}</div></section>
            <section class="panel"><div class="panel-head"><div><h3>领域命令</h3><p>操作先解释，再落版本</p></div></div><div class="panel-body">${controlsHtml()}<div style="margin-top:12px">${mappingCallout()}</div></div></section>
          </aside>
          <article class="panel c-chart-panel">
            <div class="panel-head"><div><h2>所选版本的图表投影</h2><p>${escapeHtml(latestVersion()?.annotation_version_id ?? "尚无标注版本")}</p></div><span class="chip">renderer ≠ authority</span></div>
            ${chartHtml()}
          </article>
        </section>
        <section class="c-bottom">
          <article class="panel"><div class="panel-head"><div><h3>领域关联</h3><p>ResearchRun / Evidence / TradePlanVersion</p></div></div><div class="panel-body">${linksHtml()}</div></article>
          <article class="panel"><div class="panel-head"><div><h3>完整相关状态</h3><p>可直接检查序列化边界</p></div><button class="btn danger" data-action="clear">清空原型状态</button></div><div class="panel-body">${stateHtml()}</div></article>
        </section>
        ${switcherHtml("C")}
      </main>`;
  }

  function renderVariant(variant) {
    if (variant === "B") return variantB();
    if (variant === "C") return variantC();
    return variantA();
  }

  function mountChart() {
    const host = document.querySelector("#chart");
    if (!host || state.availability === "missing") return;
    if (!window.klinecharts) throw new Error("Local klinecharts bundle did not load");

    chart = window.klinecharts.init(host);
    if (!chart) throw new Error("KLineChart init returned null");
    chart.setLocale("zh-CN");
    chart.setTimezone(fixture.security.market_timezone);
    chart.setDataLoader({
      getBars: ({ callback }) => callback(marketBars(), false),
    });
    chart.setSymbol({
      ticker: fixture.security.ticker,
      pricePrecision: 2,
      volumePrecision: 0,
    });
    chart.setPeriod({ type: "day", span: 1 });
    chart.createIndicator("VOL", false);

    const current = activeVersion();
    if (current) {
      restoringOverlay = true;
      chart.createOverlay(overlayDefinition(current));
      restoringOverlay = false;
    }
  }

  function overlayDefinition(version = null) {
    const definition = {
      name: "segment",
      groupId: "prototype-domain-annotation",
      extendData: version
        ? { annotation_id: version.annotation_id, annotation_version_id: version.annotation_version_id }
        : { annotation_id: "draft" },
      onDrawEnd: ({ overlay }) => commitOverlay(overlay, "klinecharts_onDrawEnd"),
      onPressedMoveEnd: ({ overlay }) => commitOverlay(overlay, "klinecharts_onPressedMoveEnd"),
    };
    if (version) {
      definition.points = version.anchors.map((anchor) => ({
        timestamp: Date.parse(anchor.timestamp),
        value: Number(anchor.price),
      }));
    }
    return definition;
  }

  function commitOverlay(overlay, reason) {
    if (restoringOverlay) return;
    const anchors = normalizeOverlayPoints(overlay.points);
    if (!anchors) {
      state.proposed_view = {
        interval: state.active_view.interval,
        adjustment_mode: state.active_view.adjustment_mode,
        reason: "overlay_anchor_not_on_exact_market_bar",
      };
      state.mapping_resolution = "unresolved_requires_confirmation";
      state.last_event = {
        type: "annotation_save_blocked",
        at: new Date().toISOString(),
        detail: "KLineChart returned a non-exact timestamp/value anchor; no domain version was written.",
      };
      persistState();
      render();
      return;
    }
    appendActiveVersion(anchors, reason);
  }

  function startDrawing() {
    if (!chart || activeVersion() || state.availability === "missing") return;
    chart.createOverlay(overlayDefinition());
    state.last_event = {
      type: "overlay_drawing_started",
      at: new Date().toISOString(),
      detail: "KLineChart segment requires start, end, and final-confirm clicks; only two exact market-bar/display-price anchors may be persisted.",
    };
    persistState();
  }

  function disposeChart() {
    if (chart && window.klinecharts) {
      window.klinecharts.dispose(chart);
      chart = null;
    }
  }

  function render() {
    disposeChart();
    const variant = currentVariant();
    app.innerHTML = renderVariant(variant);
    requestAnimationFrame(() => {
      try {
        mountChart();
      } catch (error) {
        const target = document.querySelector(".chart-wrap");
        if (target) {
          target.innerHTML = `<div class="chart-empty"><div><strong>CHART_RUNTIME_FAILED</strong><span>${escapeHtml(error.message)}</span></div></div>`;
        }
      }
    });
  }

  function setVariant(offset) {
    const current = VARIANTS.indexOf(currentVariant());
    const next = VARIANTS[(current + offset + VARIANTS.length) % VARIANTS.length];
    const params = new URLSearchParams(location.search);
    params.set("variant", next);
    history.replaceState(null, "", `${location.pathname}?${params.toString()}`);
    render();
  }

  app.addEventListener("click", (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) return;
    const action = control.dataset.action;
    if (action === "previous-variant") setVariant(-1);
    if (action === "next-variant") setVariant(1);
    if (action === "draw") startDrawing();
    if (action === "nudge") nudgeVersion();
    if (action === "delete") appendTombstone();
    if (action === "restore") restoreDeleted();
    if (action === "availability") cycleAvailability();
    if (action === "keep-original-view") {
      state.proposed_view = null;
      state.mapping_resolution = "exact";
      state.last_event = {
        type: "proposed_view_cancelled",
        at: new Date().toISOString(),
        detail: "Original immutable chart/annotation view retained.",
      };
      persistState();
      render();
    }
    if (action === "clear") {
      localStorage.removeItem(STORAGE_KEY);
      state = initialState();
      render();
    }
  });

  app.addEventListener("change", (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) return;
    const interval =
      control.dataset.action === "view-interval"
        ? control.value
        : state.proposed_view?.interval ?? state.active_view.interval;
    const adjustment =
      control.dataset.action === "view-adjustment"
        ? control.value
        : state.proposed_view?.adjustment_mode ?? state.active_view.adjustment_mode;
    markMappingUnresolved(interval, adjustment);
  });

  document.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || document.activeElement?.isContentEditable) return;
    if (event.key === "ArrowLeft") setVariant(-1);
    if (event.key === "ArrowRight") setVariant(1);
  });

  window.addEventListener("popstate", render);

  fetch("./fixture.json")
    .then((response) => {
      if (!response.ok) throw new Error(`Fixture load failed: HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      fixture = data;
      state = loadState();
      render();
    })
    .catch((error) => {
      app.innerHTML = `<main class="prototype-shell"><div class="chart-empty"><div><strong>PROTOTYPE_BOOT_FAILED</strong><span>${escapeHtml(error.message)}</span></div></div></main>`;
    });
})();
