import test from "node:test"
import assert from "node:assert/strict"
import {readFileSync} from "node:fs"

const html=readFileSync(new URL("../index.html",import.meta.url),"utf8")
const app=readFileSync(new URL("../src/app.js",import.meta.url),"utf8")
const css=readFileSync(new URL("../src/styles.css",import.meta.url),"utf8")
const motionCss=readFileSync(new URL("../src/motion.css",import.meta.url),"utf8")
const researchCss=readFileSync(new URL("../src/research-view.css",import.meta.url),"utf8")

test("workspace is task-first, progressively discloses provenance, and exposes frozen history",()=>{
  for(const marker of ["当前任务","计划确认","完整历史","数据详情与引用","计划版本绑定精确策略","不构成个性化投资建议"]) assert.ok(html.includes(marker))
  assert.ok(!html.includes("user_fixture_input"))
  assert.ok(!app.includes("plan-confirmations"))
  assert.ok(!app.includes("confirmPlan"))
  for(const kind of ["WorkflowRun","DataSnapshot","ResearchRun","ChartAnnotationVersion","TradePlanVersion","MarketSnapshot","PlanEvaluation","ArtifactManifest"]) assert.ok(app.includes(kind))
})

test("account context uses the canonical estimated state and keeps provenance progressive",()=>{
  for(const marker of ["当前仓位与现金","账户语境"]) assert.ok(html.includes(marker))
  for(const marker of ["current_positions","security_relationship","account_snapshot_id","derived_from_snapshot_as_of","total_quantity","available_quantity_state","cost_state","cash_state","state_status","blocking_reasons","unverified_evidence","仓位数据缺失","能力限制"]) assert.ok(app.includes(marker))
  for(const retiredField of ["position.snapshot_as_of","position.quantity_decimal","position.available_decimal","position.frozen_decimal","position.cost_price_decimal","position.base_currency","position.cash_decimal","position.reconciliation_status","position.limitations"]) assert.equal(app.includes(retiredField),false)
  for(const privateField of ["source_row_identity","source_object_sha256","private_root"]) assert.equal(app.includes(privateField),false)
})

test("workspace assets stay local and output uses text nodes",()=>{
  assert.equal(/(?:src|href)=["']https?:/i.test(html),false)
  assert.equal(/https?:\/\//i.test(app),false)
  assert.equal(app.includes("innerHTML"),false)
  assert.ok(app.includes("textContent")&&app.includes("replaceChildren"))
  assert.ok(/sandbox[^>]*srcdoc=/i.test(html)&&!html.includes('allow-scripts')&&!html.includes('allow-same-origin'))
})

test("accessibility policy includes keyboard focus, narrow layout, zoom-safe units, and reduced motion",()=>{
  assert.ok(html.includes('aria-label="工作区任务"')&&html.includes('role="status"'))
  assert.ok(css.includes(":focus-visible")&&css.includes("prefers-reduced-motion")&&css.includes("max-width:900px")&&css.includes("rem"))
  assert.ok(researchCss.includes(":focus-visible")&&researchCss.includes("prefers-reduced-motion")&&/max-width:\s*700px/.test(researchCss)&&researchCss.includes("rem"))
  assert.ok(motionCss.includes(".reduce-motion")&&/import\s*["']\.\/motion\.css["']/.test(app))
})

test("decision cards cannot force horizontal overflow on narrow screens",()=>{
  assert.match(researchCss,/\.story-grid article\s*\{[^}]*min-width:\s*0/s)
  assert.match(researchCss,/\.implied-grid article\s*\{[^}]*min-width:\s*0/s)
  assert.match(researchCss,/@media \(max-width: 700px\)[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
})

test("workspace copy contains no rating, target-price, or return-promise language",()=>{
  const copy=`${html}\n${app}`
  for(const prohibited of ["BUY","SELL","HOLD","买入","卖出","持有","目标价","收益承诺"]) assert.equal(copy.includes(prohibited),false)
})

test("decision-first copy distinguishes facts, forecasts, judgments, risks, and valuation",()=>{
  for(const marker of ["FORECAST · 推演判断","JUDGMENT · 研究判断","RISK · 反证","FORECAST DRIVERS · 推演变量","FORECAST → VALUATION · 条件结果","不是已观察事实"]) assert.ok(html.includes(marker))
  for(const marker of ["Forecast · 推演值","Forecast · 关键财务推演","Valuation · 方法级条件每股价值区间"]) assert.ok(app.includes(marker))
})
