const csrfToken =
  document.querySelector('meta[name="csrf-token"]')?.content ?? "";

const routes = {
  portfolio: "/api/read-models/portfolio@1",
  holding: "/api/read-models/holding@1",
  review: "/api/read-models/review@1",
  research: "/api/read-models/research-index@1",
  editor: "/api/read-models/account-snapshot-editor@1",
  chart: "/api/read-models/chart-workspace@1",
};

let models;

function text(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function stateValue(state, value, currency = "") {
  if (state === "known") return `${text(value)} ${currency}`.trim();
  if (state === "not_applicable") return "不适用";
  return "未知（未按零处理）";
}

const taskKindLabels = {
  manual_review: "人工复核",
  grid_trigger: "网格条件复核",
};
const priorityLabels = {
  critical: "紧急",
  high: "高",
  normal: "普通",
  low: "低",
};
const taskStatusLabels = {
  open: "待处理",
  deferred: "已延后",
  resolved: "已处理",
  superseded: "已失效",
};
const errorMessages = {
  MANUAL_REVIEW_COMMAND_INVALID: "复核请求与当前产品契约不一致。",
  MANUAL_REVIEW_RUN_INVALID: "当前复核窗口无法成立。",
  READ_MODEL_HTTP_404: "未找到所需记录。",
  PLAN_CONFIRMATION_CHALLENGE_REQUIRED: "需要先生成并核对精确变更差异。",
};

function taskLabel(item) {
  return `${taskKindLabels[item.task_kind] ?? "计划复核"}；优先级 ${priorityLabels[item.priority] ?? "普通"}；${taskStatusLabels[item.status] ?? "状态待确认"}`;
}

function userError(error) {
  return errorMessages[error?.message] ?? "操作未完成；请稍后重试或展开诊断详情。";
}

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = text(content);
  if (className) node.className = className;
  return node;
}

function svgElement(tag, attributes = {}) {
  const svgNamespace = ["http:", "", "www.w3.org", "2000", "svg"].join("/");
  const node = document.createElementNS(svgNamespace, tag);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, String(value));
  }
  return node;
}
function emptyList(label) {
  return [element("li", label, "empty")];
}

function renderList(target, values, render = text, empty = "当前无此项。") {
  target.replaceChildren(
    ...(values?.length
      ? values.map((value) => element("li", render(value)))
      : emptyList(empty)),
  );
}

async function fetchModel(url) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`READ_MODEL_HTTP_${response.status}`);
  return response.json();
}

function renderOverview(view) {
  const account = view.account_state_summary;
  const estimated = account.estimated_state;
  document.querySelector("#account-caption").textContent =
    `账户 ${account.account_id} · confirmed ${account.confirmed_snapshot.as_of}`;
  const summary = document.querySelector("#account-summary");
  summary.replaceChildren(
    element("p", `Confirmed：${account.confirmed_snapshot.as_of}`),
    element(
      "p",
      `Estimated cash：${stateValue(
        estimated.cash_state,
        estimated.cash_value,
        estimated.currency,
      )}`,
    ),
    element(
      "p",
      `Estimated NAV：${stateValue(
        estimated.nav_state,
        estimated.nav_value,
        estimated.currency,
      )}`,
    ),
    element("p", `估算状态：${estimated.status}`, "muted"),
  );
  const taskSummary = document.querySelector("#task-summary");
  taskSummary.replaceChildren(
    ...(view.unresolved_decision_tasks.length
      ? view.unresolved_decision_tasks.map((item) => {
          const row = element("li");
          row.append(element("span", taskLabel(item)));
          const defer = element("button", "延后到下次复核", "link-button");
          defer.type = "button";
          defer.addEventListener("click", () => disposeTask(item, "defer"));
          const resolve = element("button", "标记不适用", "link-button");
          resolve.type = "button";
          resolve.addEventListener("click", () => disposeTask(item, "not_applicable"));
          row.append(defer, resolve);
          return row;
        })
      : emptyList("无未决任务。")),
  );
  renderList(
    document.querySelector("#change-summary"),
    view.material_changes_since_last_review,
    text,
    "没有已证明的重要变化。",
  );
  const plans = document.querySelector("#plan-summary");
  plans.replaceChildren(
    ...(view.holding_active_plan_summaries.length
      ? view.holding_active_plan_summaries.map((plan) => {
          const card = element("article", undefined, "compact-card");
          card.append(
            element("h4", "持仓纪律计划"),
            element("p", plan.lifecycle_status === "active" ? `已启用版本 v${plan.version_no}` : "当前没有已启用版本"),
          );
          const button = element("button", "查看只读计划", "link-button");
          button.type = "button";
          button.addEventListener("click", () => openPlan(plan.plan_id));
          card.append(button);
          return card;
        })
      : [element("p", "当前没有 active master plan。", "empty")]),
  );
  renderList(
    document.querySelector("#exception-summary"),
    view.discipline_exception_summary,
    text,
    "当前没有已确认的纪律例外。",
  );
}

function renderPortfolio(view) {
  const root = document.querySelector("#holding-content");
  const account = view.account_state_summary;
  const entries = new Map();
  for (const position of account.positions ?? []) {
    entries.set(position.security_id, { position });
  }
  for (const watched of account.watchlist ?? []) {
    const current = entries.get(watched.security_id) ?? {};
    entries.set(watched.security_id, { ...current, watched });
  }
  for (const plan of view.holding_active_plan_summaries ?? []) {
    const current = entries.get(plan.security_id) ?? {};
    entries.set(plan.security_id, { ...current, plan });
  }
  const cards = [...entries.entries()].map(([securityId, entry]) => {
      const card = element("article", undefined, "detail-card");
      card.append(element("h3", securityId));
      if (entry.position) {
        card.append(
          element("p", `总数量 ${text(entry.position.total_quantity)}；可用 ${stateValue(
            entry.position.available_quantity_state,
            entry.position.available_quantity_value,
          )}`),
          element("p", `成本 ${stateValue(entry.position.cost_state, entry.position.cost_value)}；市值 ${stateValue(
            entry.position.market_value_state,
            entry.position.market_value_value,
          )}`, "muted"),
        );
      } else {
        card.append(element("p", "观察股；当前没有已证明持仓。", "muted"));
      }
      if (entry.plan) {
        const planState = entry.plan.plan_version_id
          ? `已启用版本 v${entry.plan.version_no}`
          : "尚未激活";
        const draftState = entry.plan.open_draft_id
          ? `；有未确认草稿 r${entry.plan.draft_revision}`
          : "";
        card.append(element("p", `纪律计划 · ${planState}${draftState}`));
        const button = element("button", "查看计划版本与证据", "link-button");
        button.type = "button";
        button.addEventListener("click", () => openPlan(entry.plan.plan_id));
        card.append(button);
      } else {
        card.append(element("p", "当前没有计划草稿或 active plan。", "empty"));
      }
      return card;
    });
  root.replaceChildren(
    ...(cards.length
      ? cards
      : [element("p", "当前没有持仓或观察股。", "empty")]),
  );
}
function renderReview(view) {
  const root = document.querySelector("#review-content");
  const periodic = view.periodic_discipline_review;
  const cycle = element("article", undefined, "detail-card");
  cycle.append(element("h3", "周期纪律记录"));
  if (periodic) {
    cycle.append(
      element("p", `${periodic.period_start_session} → ${periodic.period_end_session} · v${periodic.version_no} · ${periodic.status}`),
      element("p", `例外 ${periodic.exceptions.length}；覆盖 ${periodic.overridden_items.length}；未记录 ${periodic.unrecorded_items.length}；未核实 ${periodic.unverified_items.length}`, "muted"),
    );
    if (periodic.status === "draft") {
      const confirm = element("button", "用户明确确认本周期复盘", "primary");
      confirm.type = "button";
      confirm.addEventListener("click", async () => {
        if (!window.confirm("确认将当前周期复盘草稿冻结为不可变版本？")) return;
        const status = document.querySelector("#cycle-action-status");
        status.textContent = "正在确认周期复盘…";
        try {
          await dispatch(envelope(
            "discipline_review.confirm@1",
            "ConfirmDisciplineReview@1",
            { discipline_review_id: periodic.discipline_review_id, confirmed_at: new Date().toISOString() },
            periodic.version_no,
          ));
          models.review = await fetchModel(routes.review);
          renderReview(models.review);
          status.textContent = "周期复盘已由用户明确确认。";
        } catch (error) {
          status.textContent = `周期复盘确认失败：${userError(error)}`;
        }
      });
      cycle.append(confirm);
    }
  } else {
    cycle.append(element("p", "尚无周期纪律复盘。", "empty"));
  }
  const run = view.review_run;
  const today = element("article", undefined, "detail-card");
  today.append(
    element("h3", "最近一次今日复核"),
    element("p", run ? `${run.selected_session} · ${run.status}` : "尚未完成今日复核。"),
  );
  const results = element("ul");
  renderList(results, view.holding_outcomes, (item) => `${item.security_id} · ${item.outcome}`);
  today.append(results);
  const tasks = element("article", undefined, "detail-card");
  tasks.append(element("h3", "未决 / 延后任务"));
  const taskList = element("ul");
  renderList(taskList, view.unresolved_or_deferred_tasks, taskLabel);
  tasks.append(taskList);
  const changes = element("article", undefined, "detail-card");
  changes.append(element("h3", "计划影响与变更提案"));
  const changeList = element("ul");
  renderList(
    changeList,
    [
      ...view.plan_impact_summaries.map((item) => `${item.assessment_id} · ${item.impact_kind} · ${item.materiality}`),
      ...view.proposal_summaries.map((item) => `${item.proposal_id} · r${item.revision} · ${item.status}`),
    ],
  );
  changes.append(changeList);
  root.replaceChildren(cycle, today, tasks, changes);
}
function renderChart(view) {
  const card = element("article", undefined, "detail-card chart-card");
  card.id = "chart-workspace";
  const frame = view.frame;
  card.append(
    element("h3", "日 K 线与持久标注"),
    element(
      "p",
      `截至 ${frame.effective_session_date}；${frame.interval}；${frame.adjustment_mode === "none" ? "未复权" : frame.adjustment_mode}；证据 ${frame.freshness}`,
      "muted",
    ),
  );
  if (!view.bars.length) {
    card.append(element("p", "当前冻结快照没有可显示的 K 线。", "empty"));
    return card;
  }
  const width = 760;
  const height = 300;
  const pad = 36;
  const prices = view.bars.flatMap((bar) => [Number(bar.high_decimal), Number(bar.low_decimal)]);
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const span = Math.max(high - low, Math.abs(high) * 0.01, 1);
  const y = (price) => pad + ((high - Number(price)) / span) * (height - pad * 2);
  const x = (index) => pad + ((index + 0.5) / view.bars.length) * (width - pad * 2);
  const candleWidth = Math.max(3, Math.min(16, (width - pad * 2) / view.bars.length * 0.55));
  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `截至 ${frame.effective_session_date} 的日 K 线与用户标注`,
  });
  svg.classList.add("candlestick-chart");
  const timestampIndex = new Map();
  view.bars.forEach((bar, index) => {
    timestampIndex.set(bar.market_timestamp, index);
    const center = x(index);
    const rising = Number(bar.close_decimal) >= Number(bar.open_decimal);
    const color = rising ? "#a33b32" : "#247052";
    svg.append(svgElement("line", {
      x1: center,
      x2: center,
      y1: y(bar.high_decimal),
      y2: y(bar.low_decimal),
      stroke: color,
      "stroke-width": 1.5,
    }));
    const openY = y(bar.open_decimal);
    const closeY = y(bar.close_decimal);
    svg.append(svgElement("rect", {
      x: center - candleWidth / 2,
      y: Math.min(openY, closeY),
      width: candleWidth,
      height: Math.max(2, Math.abs(openY - closeY)),
      fill: rising ? "#fff" : color,
      stroke: color,
      "stroke-width": 1.5,
    }));
  });
  for (const annotation of view.annotations) {
    for (const anchor of annotation.anchors) {
      const anchorIndex = timestampIndex.get(anchor.market_timestamp);
      if (anchorIndex === undefined) continue;
      const anchorY = y(anchor.exact_price_decimal);
      const line = svgElement("line", {
        x1: pad,
        x2: width - pad,
        y1: anchorY,
        y2: anchorY,
        stroke: "#174f86",
        "stroke-width": 2,
        "stroke-dasharray": "7 5",
      });
      line.dataset.annotationId = annotation.annotation_id;
      line.dataset.marketTimestamp = anchor.market_timestamp;
      line.dataset.exactPriceDecimal = anchor.exact_price_decimal;
      svg.append(line, svgElement("circle", {
        cx: x(anchorIndex),
        cy: anchorY,
        r: 5,
        fill: "#174f86",
      }));
    }
  }
  card.append(svg);
  const latest = view.bars.at(-1);
  const status = element("p", "", "muted");
  status.id = "chart-action-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const add = element("button", "在最新收盘位置添加水平标注", "link-button");
  add.id = "add-chart-annotation";
  add.type = "button";
  add.addEventListener("click", async () => {
    add.disabled = true;
    status.textContent = "正在保存不可变标注版本…";
    try {
      await dispatch(envelope(
        "chart_annotation.apply@1",
        "ApplyChartAnnotation@1",
        {
          operation: "create",
          security_id: frame.security_id,
          data_snapshot_id: frame.data_snapshot_id,
          annotation_id: null,
          kind: "horizontal_line",
          style: "accent",
          anchors: [{
            market_timestamp: latest.market_timestamp,
            exact_price_decimal: latest.close_decimal,
          }],
        },
        null,
      ));
      models.chart = await fetchModel(routes.chart);
      renderResearch(models.research);
      document.querySelector("#chart-action-status").textContent = "标注已保存；刷新或重启后仍会按同一市场坐标恢复。";
    } catch (error) {
      add.disabled = false;
      status.textContent = `标注未保存：${userError(error)}`;
    }
  });
  card.append(add, status);
  const annotations = element("ul");
  renderList(
    annotations,
    view.annotations,
    (item) => `${item.kind === "horizontal_line" ? "水平标注" : "图表标注"} · v${item.version_no} · ${item.anchors[0]?.market_timestamp ?? "坐标未知"} · ${item.anchors[0]?.exact_price_decimal ?? "价格未知"}`,
    "当前没有用户标注。",
  );
  card.append(annotations);
  const details = element("details");
  details.append(
    element("summary", "展开图表快照 ID 与完整标注历史"),
    element("pre", JSON.stringify({ frame, annotation_history: view.annotation_history }, null, 2)),
  );
  card.append(details);
  return card;
}

function renderResearch(view) {
  const root = document.querySelector("#research-content");
  const researchCards = view.research_items.length
    ? view.research_items.map((item) => {
        const card = element("article", undefined, "detail-card");
        card.append(
          element("h3", `${item.security_id} · ${item.status}`),
          element("p", `重要变化：${text(item.material_change)}`),
          element("p", `关键不确定性：${text(item.key_uncertainties)}`),
          element("p", `什么会改变当前看法：${text(item.what_would_change_the_view)}`),
          element("p", `计划能力影响：${text(item.ability_impact)}`, "muted"),
        );
        return card;
      })
    : [element("p", "当前没有已持久化的研究视图。", "empty")];
  if (models.chart) researchCards.push(renderChart(models.chart));
  root.replaceChildren(...researchCards);
}
async function openPlan(planId) {
  const dialog = document.querySelector("#plan-dialog");
  const target = document.querySelector("#plan-detail-content");
  target.replaceChildren(element("p", "正在载入计划版本与证据…"));
  if (!dialog.open) dialog.showModal();
  try {
    const view = await fetchModel(
      `/api/read-models/trade-plan-detail@1?plan_id=${encodeURIComponent(planId)}`,
    );
    const identity = view.plan_identity;
    const summary = view.decision_summary;
    const version = element("article", undefined, "detail-card");
    version.append(
      element("h3", "计划概要"),
      element("p", summary.lifecycle_label),
      element(
        "p",
        `期限 ${text(summary.horizon.start)} → ${text(summary.horizon.end)}；复核日 ${text(summary.horizon.review_by)}`,
      ),
      element(
        "p",
        `核心数量下限 ${stateValue(summary.quantities.core_floor.state, summary.quantities.core_floor.value, summary.quantities.core_floor.unit)}；候选数量调整 ${stateValue(summary.quantities.candidate_adjustment.state, summary.quantities.candidate_adjustment.value, summary.quantities.candidate_adjustment.unit)}`,
      ),
      element("p", summary.user_control_boundary, "muted"),
    );
    const triggers = element("article", undefined, "detail-card");
    triggers.append(element("h3", "触发条件与触发后行为"));
    const triggerList = element("ul");
    renderList(
      triggerList,
      summary.trigger_conditions,
      (item) => `${item.name}：${item.condition}。当前：${item.current_state}；触发后：${item.on_trigger}`,
    );
    triggers.append(triggerList);
    const risk = element("article", undefined, "detail-card");
    risk.append(element("h3", "风险约束"));
    const riskList = element("ul");
    renderList(
      riskList,
      summary.risk_constraints,
      (item) => `${item.label}：${item.value}`,
      "当前没有可确认的风险约束。",
    );
    risk.append(riskList);
    const evidence = element("article", undefined, "detail-card");
    evidence.append(
      element("h3", "证据新鲜度"),
      element("p", summary.evidence_status.summary),
    );
    const evidenceList = element("ul");
    renderList(
      evidenceList,
      summary.evidence_status.items,
      (item) => `${item.label}：${item.state}；截至 ${text(item.as_of)}`,
    );
    evidence.append(evidenceList);
    const evaluation = element("article", undefined, "detail-card");
    evaluation.append(
      element("h3", "当前评估"),
      element("p", summary.evaluation.state),
      element("p", summary.evaluation.reason),
      element("p", `下一步：${summary.evaluation.next_step}`, "muted"),
    );
    const work = element("article", undefined, "detail-card");
    work.append(element("h3", "任务与复核"));
    const workList = element("ul");
    renderList(
      workList,
      [
        ...view.related_tasks.map((item) => `待办：${taskLabel(item)}`),
        ...view.review_history.map((item) => `复核 ${item.selected_complete_session}：${item.outcome}`),
      ],
    );
    work.append(workList);
    const changes = element("details");
    changes.append(element("summary", "展开确认与变更提案差异"));
    const changeList = element("pre", view.change_diffs.length ? JSON.stringify(view.change_diffs, null, 2) : "当前无变更差异。");
    changes.append(changeList);
    const confirmation = view.confirmation_state;
    const openDraft = confirmation?.open_draft;
    if (openDraft) {
      if (!confirmation.challenge_id || confirmation.status !== "issued") {
        const issue = element("button", "生成精确确认差异", "primary");
        issue.type = "button";
        issue.addEventListener("click", async () => {
          const issuedAt = new Date();
          const expiresAt = new Date(issuedAt.getTime() + 60 * 60 * 1000);
          try {
            await dispatch(envelope(
              "trade_plan.issue_confirmation_challenge@1",
              "IssuePlanConfirmationChallenge@1",
              {
                draft_id: openDraft.draft_id,
                activation_intent: "confirm_and_activate",
                issued_at: issuedAt.toISOString(),
                expires_at: expiresAt.toISOString(),
              },
              openDraft.revision,
            ));
            await openPlan(planId);
          } catch (error) {
            issue.replaceWith(element("p", `确认差异生成失败：${userError(error)}`, "error"));
          }
        });
        version.append(issue);
      } else {
        const confirm = element("button", "用户确认并激活此计划版本", "primary");
        confirm.type = "button";
        confirm.addEventListener("click", async () => {
          if (!window.confirm("确认当前 canonical diff，并激活其精确计划版本？")) return;
          try {
            await dispatch(envelope(
              "trade_plan.confirm@1",
              "ConfirmTradePlanDraft@1",
              {
                expected_draft_hash: confirmation.expected_content_hash,
                expected_diff_hash: confirmation.canonical_diff_hash,
                activation_intent: confirmation.activation_intent,
                approved_at: new Date().toISOString(),
              },
              confirmation.expected_revision,
              confirmation.challenge_id,
            ));
            models.portfolio = await fetchModel(routes.portfolio);
            renderOverview(models.portfolio);
            renderPortfolio(models.portfolio);
            await openPlan(planId);
          } catch (error) {
            confirm.replaceWith(element("p", `计划确认失败：${userError(error)}`, "error"));
          }
        });
        version.append(confirm);
      }
    }
    const diagnostics = element("details");
    diagnostics.append(
      element("summary", "展开内部 ID、完整证据与版本历史"),
      element(
        "pre",
        JSON.stringify(
          {
            plan_identity: identity,
            rules: view.rules,
            evidence: view.evidence_freshness,
            version_history: view.version_history,
            diagnostics: view.diagnostics,
          },
          null,
          2,
        ),
      ),
    );
    target.replaceChildren(
      version,
      triggers,
      risk,
      evidence,
      evaluation,
      work,
      changes,
      diagnostics,
    );
  } catch (error) {
    target.replaceChildren(element("p", `计划详情不可用：${userError(error)}`, "error"));
  }
}
function applyStateField(form, prefix, state, value) {
  form.elements[`${prefix}_state`].value = state ?? "unknown";
  form.elements[`${prefix}_value`].value = value ?? "";
}

function renderEditor(view) {
  const form = document.querySelector("#account-form");
  const current = view.current_draft;
  const confirmed = view.confirmed_snapshot_summary;
  document.querySelector("#account-editor-summary").replaceChildren(
    element(
      "p",
      confirmed
        ? `已确认 v${confirmed.version_no} · ${confirmed.as_of_at}`
        : "尚无已确认账户快照。",
    ),
    element(
      "p",
      current
        ? `当前草稿 r${current.revision} · ${view.validation.state}`
        : "当前没有 open 草稿。",
      "muted",
    ),
  );
  const accountId = models.portfolio.account_state_summary.account_id;
  form.dataset.accountId = accountId;
  if (current) {
    form.dataset.draftId = current.draft_id;
    form.dataset.revision = String(current.revision);
    form.elements.as_of_at.value = current.as_of_at;
    form.elements.session_semantics.value = current.session_semantics;
    form.elements.currency.value = current.currency;
    form.elements.redacted_source_ref.value = current.redacted_source_ref;
    applyStateField(form, "cash", current.cash_state, current.cash_value);
    applyStateField(form, "nav", current.nav_state, current.nav_value);
    applyStateField(form, "fees", current.fees_state, current.fees_value);
  } else {
    delete form.dataset.draftId;
    delete form.dataset.revision;
    form.elements.as_of_at.value = new Date().toISOString().slice(0, 10);
    form.elements.currency.value =
      confirmed?.currency ?? models.portfolio.account_state_summary.estimated_state.currency;
  }
  document.querySelector("#confirm-draft").disabled =
    !current || view.validation.state !== "valid";
  const details = document.querySelector("#account-editor-details");
  details.replaceChildren(
    element("h3", "字段 lineage"),
    element(
      "p",
      view.field_lineage.length
        ? view.field_lineage
            .map((item) => `${item.field} · ${item.source_kind} · ${item.redacted_source_ref}`)
            .join("；")
        : "无已确认 lineage。",
    ),
    element("h3", "校验"),
    element(
      "p",
      view.validation.errors.length
        ? view.validation.errors.join("；")
        : view.validation.state,
    ),
    element("h3", "Canonical diff"),
    element(
      "pre",
      view.canonical_diff
        ? JSON.stringify(view.canonical_diff.canonical_diff, null, 2)
        : "无 open 草稿。",
    ),
    element("h3", "能力影响"),
    element(
      "p",
      view.capability_impacts.length
        ? view.capability_impacts
            .map((item) => `${item.capability_key} · ${item.state}`)
            .join("；")
        : "尚无已确认能力状态。",
    ),
  );
}

function draftFromForm(form) {
  const current = models.editor.current_draft;
  const value = (name) => form.elements[name].value.trim();
  const optionalValue = (prefix) =>
    value(`${prefix}_state`) === "known" ? value(`${prefix}_value`) : null;
  return {
    draft_id: form.dataset.draftId ?? `draft_web_${crypto.randomUUID().replaceAll("-", "")}`,
    account_id: form.dataset.accountId,
    revision: Number(form.dataset.revision ?? "1"),
    status: "open",
    source_kind: "manual_web_entry",
    redacted_source_ref: value("redacted_source_ref"),
    as_of_at: value("as_of_at"),
    as_of_precision: "date",
    timezone: "Asia/Shanghai",
    session_semantics: value("session_semantics"),
    currency: value("currency"),
    cash_state: value("cash_state"),
    cash_value: optionalValue("cash"),
    nav_state: value("nav_state"),
    nav_value: optionalValue("nav"),
    fees_state: value("fees_state"),
    fees_value: optionalValue("fees"),
    positions:
      current?.positions ??
      models.editor.confirmed_snapshot_summary?.positions ??
      [],
    previous_snapshot_version_id:
      current?.previous_snapshot_version_id ??
      models.editor.confirmed_snapshot_summary?.account_snapshot_version_id ??
      null,
    revises_snapshot_version_id: current?.revises_snapshot_version_id ?? null,
    corrects_snapshot_version_id: current?.corrects_snapshot_version_id ?? null,
    correction_reason: current?.correction_reason ?? null,
  };
}

function envelope(commandName, payloadSchemaVersion, payload, expectedRevision, approvalChallengeId = null) {
  return {
    schema_version: "ApplicationCommandEnvelope@1",
    command_name: commandName,
    invocation_id: `web:${commandName}:${crypto.randomUUID()}`,
    payload_schema_version: payloadSchemaVersion,
    expected_revision: expectedRevision ?? null,
    decision_actor: { actor_type: "user", actor_id: "local-user" },
    interaction_channel: "web",
    transport_actor: { actor_type: "adapter", actor_id: "web-local" },
    approval: approvalChallengeId ? { challenge_id: approvalChallengeId } : null,
    payload,
  };
}

async function dispatch(command) {
  const response = await fetch("/api/application-commands", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(command),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.code ?? `COMMAND_HTTP_${response.status}`);
  return result;
}

async function refreshEditor() {
  models.editor = await fetchModel(routes.editor);
  renderEditor(models.editor);
}

async function refreshDecisionViews() {
  const results = await Promise.allSettled([
    fetchModel(routes.portfolio),
    fetchModel(routes.review),
    fetchModel(routes.research),
  ]);
  if (results[0].status === "fulfilled") {
    models.portfolio = results[0].value;
    renderOverview(models.portfolio);
    renderPortfolio(models.portfolio);
  }
  if (results[1].status === "fulfilled") {
    models.review = results[1].value;
    renderReview(models.review);
  }
  if (results[2].status === "fulfilled") {
    models.research = results[2].value;
    renderResearch(models.research);
  }
}

async function disposeTask(task, action) {
  const occurredAt = new Date().toISOString();
  try {
    if (action === "defer") {
      await dispatch(envelope(
        "decision_task.defer@1",
        "DeferDecisionTask@1",
        {
          decision_task_id: task.decision_task_id,
          defer_target_type: "next_manual_review",
          defer_target_value: null,
          occurred_at: occurredAt,
        },
      ));
    } else {
      const reason = window.prompt("请记录为什么该任务不适用：");
      if (!reason?.trim()) return;
      await dispatch(envelope(
        "decision_task.resolve@1",
        "ResolveDecisionTask@1",
        {
          decision_task_id: task.decision_task_id,
          disposition: "not_applicable",
          reason: reason.trim(),
          occurred_at: occurredAt,
        },
      ));
    }
    await refreshDecisionViews();
  } catch (error) {
    document.querySelector("#today-action-status").textContent = `任务更新失败：${userError(error)}`;
  }
}

document.querySelector("#run-today-review").addEventListener("click", async () => {
  const status = document.querySelector("#today-action-status");
  status.textContent = "正在冻结最新完整交易日并复核全部持仓与观察股…";
  try {
    await dispatch(envelope(
      "manual_portfolio_review.run@2",
      "RunManualPortfolioReview@2",
      {
        account_id: models.portfolio.account_state_summary.account_id,
        requested_at: new Date().toISOString(),
        session_selection: "latest_proven_complete_session",
      },
    ));
    await refreshDecisionViews();
    status.textContent = "今日复核已完成；待办与变更已刷新。";
  } catch (error) {
    status.textContent = `今日复核未完成：${userError(error)}`;
  }
});

document.querySelector("#create-cycle-review").addEventListener("click", async () => {
  const status = document.querySelector("#cycle-action-status");
  const run = models.review?.review_run;
  if (!run) {
    status.textContent = "需要先完成一次今日复核，才能确定有证据的周期边界。";
    return;
  }
  status.textContent = "正在从正式复核、任务和执行记录编译周期草稿…";
  try {
    await dispatch(envelope(
      "discipline_review.create_draft@2",
      "CreateDisciplineReviewDraft@2",
      {
        account_id: models.portfolio.account_state_summary.account_id,
        period_request: {
          period_kind: "weekly",
          requested_at: new Date().toISOString(),
          requested_start_date: null,
          requested_end_date: null,
        },
      },
    ));
    models.review = await fetchModel(routes.review);
    renderReview(models.review);
    status.textContent = "周期复盘草稿已生成；请检查后明确确认。";
  } catch (error) {
    status.textContent = `周期复盘草稿未生成：${userError(error)}`;
  }
});
document.querySelector("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.querySelector("#account-form-status");
  status.textContent = "正在确定性校验并保存草稿…";
  const form = event.currentTarget;
  const isUpdate = Boolean(form.dataset.draftId);
  const command = envelope(
    isUpdate ? "account_snapshot.update_draft@1" : "account_snapshot.create_draft@1",
    isUpdate ? "UpdateAccountSnapshotDraft@1" : "CreateAccountSnapshotDraft@1",
    { draft: draftFromForm(form) },
    isUpdate ? Number(form.dataset.revision) : null,
  );
  try {
    await dispatch(command);
    await refreshEditor();
    status.textContent =
      models.editor.validation.state === "valid"
        ? "草稿已保存并通过校验；仍需用户明确确认。"
        : `草稿已保存但未通过校验：${models.editor.validation.errors.join("；")}`;
  } catch (error) {
    status.textContent = `草稿未保存：${userError(error)}`;
  }
});

document.querySelector("#confirm-draft").addEventListener("click", async () => {
  const current = models.editor.current_draft;
  if (!current) return;
  const status = document.querySelector("#account-form-status");
  status.textContent = "正在记录用户明确确认…";
  try {
    await dispatch(
      envelope(
        "account_snapshot.confirm@1",
        "ConfirmAccountSnapshot@1",
        { draft_id: current.draft_id },
        current.revision,
      ),
    );
    models.portfolio = await fetchModel(routes.portfolio);
    await refreshEditor();
    renderOverview(models.portfolio);
    status.textContent = "账户快照已由用户明确确认并生成不可变版本。";
  } catch (error) {
    status.textContent = `确认未完成：${userError(error)}`;
  }
});

document.querySelectorAll("[data-value-field]").forEach((group) => {
  const prefix = group.dataset.valueField;
  const select = group.querySelector("select");
  const input = group.querySelector("input");
  const synchronize = () => {
    input.disabled = select.value !== "known";
    if (input.disabled) input.value = "";
    input.required = select.value === "known";
  };
  select.addEventListener("change", synchronize);
  synchronize();
});

document.querySelectorAll(".primary-nav [data-page]").forEach((button) => {
  button.addEventListener("click", () => {
    const page = button.dataset.page;
    document.querySelectorAll(".primary-nav button").forEach((item) => {
      item.removeAttribute("aria-current");
    });
    button.setAttribute("aria-current", "page");
    document.querySelectorAll(".page").forEach((section) => {
      section.hidden = section.id !== `page-${page}`;
    });
    document.querySelector(`#page-${page}`).focus({ preventScroll: true });
  });
});

document.querySelector("#open-account-editor").addEventListener("click", () => {
  document.querySelector("#account-dialog").showModal();
});

document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector(`#${button.dataset.closeDialog}`).close();
  });
});

async function initialize() {
  const status = document.querySelector("#load-status");
  models = {};
  try {
    models.portfolio = await fetchModel(routes.portfolio);
    renderOverview(models.portfolio);
    renderPortfolio(models.portfolio);
  } catch (error) {
    status.textContent = `账户与今日待办不可用：${userError(error)}`;
    status.dataset.state = "error";
    return;
  }
  const sections = await Promise.allSettled([
    fetchModel(routes.review),
    fetchModel(routes.research),
    fetchModel(routes.editor),
    fetchModel(routes.chart),
  ]);
  const failures = [];
  if (sections[0].status === "fulfilled") {
    models.review = sections[0].value;
    renderReview(models.review);
  } else {
    failures.push("周期复盘");
  }
  if (sections[1].status === "fulfilled") {
    models.research = sections[1].value;
    renderResearch(models.research);
  } else {
    failures.push("研究与计划");
  }
  if (sections[2].status === "fulfilled") {
    models.editor = sections[2].value;
    renderEditor(models.editor);
  } else {
    failures.push("账户编辑器");
    document.querySelector("#open-account-editor").disabled = true;
  }
  if (sections[3].status === "fulfilled") {
    models.chart = sections[3].value;
    if (models.research) renderResearch(models.research);
  } else {
    failures.push("K 线与标注");
  }
  status.textContent = failures.length
    ? `核心今日与组合已载入；局部不可用：${failures.join("、")}。`
    : "已载入同一 application read-model authority。";
  status.dataset.state = failures.length ? "limited" : "ready";
}

initialize();
