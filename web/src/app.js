const csrfToken =
  document.querySelector('meta[name="csrf-token"]')?.content ?? "";

const routes = {
  portfolio: "/api/read-models/portfolio@1",
  holding: "/api/read-models/holding@1",
  review: "/api/read-models/review@1",
  research: "/api/read-models/research-index@1",
  editor: "/api/read-models/account-snapshot-editor@1",
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

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = text(content);
  if (className) node.className = className;
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
  renderList(
    document.querySelector("#task-summary"),
    view.unresolved_decision_tasks,
    (item) => `${item.task_type} · ${item.status}`,
    "无未决任务。",
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
            element("h4", `${plan.security_id} · ${plan.strategy_version_id}`),
            element("p", `状态：${plan.lifecycle_status}`),
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

function renderHolding(view) {
  const root = document.querySelector("#holding-content");
  const position = view.position_summary;
  const plan = view.active_plan_summary;
  const positionCard = element("article", undefined, "detail-card");
  positionCard.append(
    element("h3", `${view.security_identity.security_id} · A 股`),
    element(
      "p",
      position.position_state === "unknown"
        ? "仓位未知（未按零仓位处理）"
        : `总数量 ${text(position.total_quantity)}；可用数量 ${stateValue(
            position.available_quantity_state,
            position.available_quantity_value,
          )}`,
    ),
    element(
      "p",
      position.position_state === "unknown"
        ? position.reason_code
        : `成本 ${stateValue(position.cost_state, position.cost_value)}；市值 ${stateValue(
            position.market_value_state,
            position.market_value_value,
          )}`,
      "muted",
    ),
  );
  const planCard = element("article", undefined, "detail-card");
  planCard.append(
    element("h3", "Active master / core / grid"),
    element(
      "p",
      plan
        ? `${plan.strategy_version_id} · ${plan.lifecycle_status}`
        : "当前没有 active plan。",
    ),
  );
  if (plan) {
    const button = element("button", "查看计划详情", "link-button");
    button.type = "button";
    button.addEventListener("click", () => openPlan(plan.plan_id));
    planCard.append(button);
  }
  const warningCard = element("article", undefined, "detail-card");
  warningCard.append(element("h3", "能力变化与不确定性"));
  const warnings = element("ul");
  renderList(
    warnings,
    [
      ...view.ability_changing_warnings,
      ...view.key_uncertainties,
      ...view.material_evidence_changes,
    ],
  );
  warningCard.append(warnings);
  root.replaceChildren(positionCard, planCard, warningCard);
}

function renderReview(view) {
  const root = document.querySelector("#review-content");
  const run = view.review_run;
  const summary = element("article", undefined, "detail-card");
  summary.append(
    element("h3", "所选完整交易日与运行状态"),
    element(
      "p",
      run
        ? `${run.selected_session} · ${run.status}`
        : "尚未选择并完成一次手动复核。",
    ),
  );
  const results = element("article", undefined, "detail-card");
  results.append(element("h3", "逐持仓结果"));
  const resultList = element("ul");
  renderList(
    resultList,
    view.holding_outcomes,
    (item) => `${item.security_id} · ${item.outcome}`,
  );
  results.append(resultList);
  const tasks = element("article", undefined, "detail-card");
  tasks.append(element("h3", "未决 / 延后任务"));
  const taskList = element("ul");
  renderList(
    taskList,
    view.unresolved_or_deferred_tasks,
    (item) => `${item.task_type} · ${item.status}`,
  );
  tasks.append(taskList);
  const impacts = element("article", undefined, "detail-card");
  impacts.append(element("h3", "PlanImpact / Proposal"));
  const impactList = element("ul");
  renderList(
    impactList,
    [
      ...view.plan_impact_summaries.map(
        (item) =>
          `${item.assessment_id} · ${item.impact_kind} · ${item.materiality}`,
      ),
      ...view.proposal_summaries.map(
        (item) => `${item.proposal_id} · ${item.status}`,
      ),
    ],
    text,
  );
  impacts.append(impactList);
  root.replaceChildren(summary, results, tasks, impacts);
}

function renderResearch(view) {
  const root = document.querySelector("#research-content");
  root.replaceChildren(
    ...(view.research_items.length
      ? view.research_items.map((item) => {
          const card = element("article", undefined, "detail-card");
          card.append(
            element("h3", `${item.security_id} · ${item.status}`),
            element("p", `重要变化：${text(item.material_change)}`),
            element("p", `关键不确定性：${text(item.key_uncertainties)}`),
            element(
              "p",
              `什么会改变当前看法：${text(item.what_would_change_the_view)}`,
            ),
            element("p", `计划能力影响：${text(item.plan_capability_impact)}`, "muted"),
          );
          return card;
        })
      : [element("p", "当前没有已持久化的研究视图。", "empty")]),
  );
}

async function openPlan(planId) {
  const dialog = document.querySelector("#plan-dialog");
  const target = document.querySelector("#plan-detail-content");
  target.replaceChildren(element("p", "正在载入只读计划…"));
  dialog.showModal();
  try {
    const view = await fetchModel(
      `/api/read-models/trade-plan-detail@1?plan_id=${encodeURIComponent(planId)}`,
    );
    const identity = view.plan_identity;
    const rules = element("ul");
    renderList(
      rules,
      view.rules,
      (rule) => `${rule.rule_class} · ${rule.rule_kind} · ${rule.priority}`,
    );
    const history = element("ul");
    renderList(
      history,
      view.version_history,
      (version) => `v${version.version_no} · ${version.confirmed_at}`,
    );
    const diagnostics = element("details");
    diagnostics.append(
      element("summary", "展开诊断与版本数量"),
      element("p", `版本数量：${view.diagnostics.version_count}`),
    );
    target.replaceChildren(
      element(
        "p",
        `${identity.security_id} · ${identity.strategy_version_id} · ${identity.lifecycle_status}`,
      ),
      element("h3", "HardRule / ReviewRule"),
      rules,
      element("h3", "版本历史"),
      history,
      diagnostics,
    );
  } catch (error) {
    target.replaceChildren(element("p", `计划详情不可用：${error.message}`, "error"));
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

function envelope(commandName, payloadSchemaVersion, payload, expectedRevision) {
  return {
    schema_version: "ApplicationCommandEnvelope@1",
    command_name: commandName,
    invocation_id: `web:${commandName}:${crypto.randomUUID()}`,
    payload_schema_version: payloadSchemaVersion,
    expected_revision: expectedRevision ?? null,
    decision_actor: { actor_type: "user", actor_id: "local-user" },
    interaction_channel: "web",
    transport_actor: { actor_type: "adapter", actor_id: "web-local" },
    approval: null,
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
    status.textContent = `草稿未保存：${error.message}`;
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
    status.textContent = `确认未完成：${error.message}`;
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
  try {
    const [portfolio, holding, review, research, editor] = await Promise.all(
      Object.values(routes).map(fetchModel),
    );
    models = { portfolio, holding, review, research, editor };
    renderOverview(portfolio);
    renderHolding(holding);
    renderReview(review);
    renderResearch(research);
    renderEditor(editor);
    status.textContent = "已载入同一 application read-model authority。";
    status.dataset.state = "ready";
  } catch (error) {
    status.textContent = `工作台不可用：${error.message}`;
    status.dataset.state = "error";
  }
}

initialize();
