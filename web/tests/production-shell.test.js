import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../src/app.js", import.meta.url), "utf8");

test("production shell has exactly the four primary navigation items", () => {
  const labels = [...html.matchAll(/data-page="[^"]+"[^>]*>([^<]+)</g)].map(
    (match) => match[1],
  );
  assert.deepEqual(labels, ["今日", "组合", "研究与计划", "周期复盘"]);
});

test("production source consumes only versioned read routes and shared commands", () => {
  assert.equal(app.includes("/api/workspace"), false);
  assert.equal(app.includes("/api/annotations"), false);
  assert.equal(app.includes("/api/update-authorizations"), false);
  assert.match(app, /\/api\/read-models\/portfolio@1/);
  assert.match(app, /\/api\/read-models\/chart-workspace@1/);
  assert.match(app, /\/api\/application-commands/);
  assert.match(app, /account_snapshot\.confirm@1/);
  assert.match(app, /manual_portfolio_review\.run@2/);
  assert.match(app, /chart_annotation\.apply@1/);
  assert.match(app, /discipline_review\.create_draft@2/);
  assert.equal(
    app.includes(["discipline_review", "create_draft@1"].join(".")),
    false,
  );
  assert.match(app, /trade_plan\.issue_confirmation_challenge@1/);
  assert.match(app, /trade_plan\.confirm@1/);
});

test("research product renders K-line coordinates and persistent annotations", () => {
  assert.match(app, /function renderChart/);
  assert.match(app, /candlestick-chart/);
  assert.match(app, /market_timestamp/);
  assert.match(app, /exact_price_decimal/);
  assert.match(app, /在最新收盘位置添加水平标注/);
  assert.match(app, /展开图表快照 ID 与完整标注历史/);
});
test("plan detail is decision-first and keeps internals behind disclosure", () => {
  assert.match(app, /view\.decision_summary/);
  assert.match(app, /触发条件与触发后行为/);
  assert.match(app, /证据新鲜度/);
  assert.match(app, /下一步/);
  assert.match(app, /展开内部 ID、完整证据与版本历史/);
  assert.match(app, /user_control_boundary/);
  assert.equal(app.includes("Open discipline draft; not confirmed, active"), false);
  assert.equal(app.includes("OPEN draft"), false);
});
test("home shell exposes only five decision summary regions", () => {
  const ids = [
    "account-summary",
    "task-summary",
    "change-summary",
    "plan-summary",
    "exception-summary",
  ];
  for (const id of ids) assert.match(html, new RegExp(`id="${id}"`));
  for (const forbidden of [
    "policy_identity",
    "model_identity",
    "manifest_id",
    "workflow_log",
    "readiness",
  ]) {
    assert.equal(html.includes(forbidden), false);
  }
});
