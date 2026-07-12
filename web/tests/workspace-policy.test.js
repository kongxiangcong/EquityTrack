import test from "node:test"
import assert from "node:assert/strict"
import {readFileSync} from "node:fs"

const html=readFileSync(new URL("../index.html",import.meta.url),"utf8")
const app=readFileSync(new URL("../src/app.js",import.meta.url),"utf8")
const css=readFileSync(new URL("../src/styles.css",import.meta.url),"utf8")
const motionCss=readFileSync(new URL("../src/motion.css",import.meta.url),"utf8")

test("workspace is task-first, progressively discloses provenance, and exposes frozen history",()=>{
  for(const marker of ["当前任务","计划确认","完整历史","数据详情与引用","user_fixture_input","不构成个性化投资建议"]) assert.ok(html.includes(marker))
  for(const kind of ["WorkflowRun","DataSnapshot","ResearchRun","ChartAnnotationVersion","TradePlanVersion","MarketSnapshot","PlanEvaluation","ArtifactManifest"]) assert.ok(app.includes(kind))
})

test("workspace assets stay local and output uses text nodes",()=>{
  assert.equal(/(?:src|href)=["']https?:/i.test(html),false)
  assert.equal(/https?:\/\//i.test(app),false)
  assert.equal(app.includes("innerHTML"),false)
  assert.ok(app.includes("textContent")&&app.includes("replaceChildren"))
  assert.ok(html.includes('sandbox srcdoc=')&&!html.includes('allow-scripts')&&!html.includes('allow-same-origin'))
})

test("accessibility policy includes keyboard focus, narrow layout, zoom-safe units, and reduced motion",()=>{
  assert.ok(html.includes('aria-label="工作区任务"')&&html.includes('role="status"'))
  assert.ok(css.includes(":focus-visible")&&css.includes("prefers-reduced-motion")&&css.includes("max-width:900px")&&css.includes("rem"))
  assert.ok(motionCss.includes(".reduce-motion")&&app.includes('import "./motion.css"'))
})

test("workspace copy contains no rating, target-price, or return-promise language",()=>{
  const copy=`${html}\n${app}`
  for(const prohibited of ["BUY","SELL","HOLD","买入","卖出","持有","目标价","收益承诺"]) assert.equal(copy.includes(prohibited),false)
})
