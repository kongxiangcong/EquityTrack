import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../src/app.js", import.meta.url), "utf8");

test("production shell has exactly the four primary navigation items", () => {
  const labels = [...html.matchAll(/data-page="[^"]+"[^>]*>([^<]+)</g)].map(
    (match) => match[1],
  );
  assert.deepEqual(labels, ["总览", "组合", "复核", "研究"]);
});

test("production source consumes only versioned read routes and shared commands", () => {
  assert.equal(app.includes("/api/workspace"), false);
  assert.equal(app.includes("/api/annotations"), false);
  assert.equal(app.includes("/api/update-authorizations"), false);
  assert.match(app, /\/api\/read-models\/portfolio@1/);
  assert.match(app, /\/api\/application-commands/);
  assert.match(app, /account_snapshot\.confirm@1/);
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
