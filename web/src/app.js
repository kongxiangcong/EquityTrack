import {init, dispose} from "klinecharts"
import {toKLineData, toOverlay} from "./chart-adapter.js"
import {createMutationRunner} from "./mutation-runner.js"
import "./motion.css"
const csrfToken=document.querySelector('meta[name="csrf-token"]')?.content ?? ""

const gateway = globalThis.chartGateway ?? {
  async series() { return (await fetch("/api/chart-series", {headers:{Accept:"application/json"}})).json() },
  async history() { return (await fetch("/api/annotations", {headers:{Accept:"application/json"}})).json() },
  async workspace() { const response=await fetch("/api/workspace", {headers:{Accept:"application/json"}});if(!response.ok)throw new Error(`HTTP_${response.status}`);return response.json() },
  async authorize(payload,invocationId) { const response=await fetch("/api/update-authorizations",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrfToken,"X-Invocation-Id":invocationId},body:JSON.stringify(payload)});if(!response.ok)throw new Error((await response.json().catch(()=>({}))).error_code??`HTTP_${response.status}`);return response.json() },
  async confirmPlan(payload,invocationId) { const response=await fetch("/api/plan-confirmations",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrfToken,"X-Invocation-Id":invocationId},body:JSON.stringify(payload)});if(!response.ok)throw new Error((await response.json().catch(()=>({}))).error_code??`HTTP_${response.status}`);return response.json() },
  async command(payload,invocationId) { let response;try{response=await fetch("/api/annotations", {method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrfToken,"X-Invocation-Id":invocationId},body:JSON.stringify(payload)})}catch(cause){const error=new Error("COMMAND_RESULT_UNKNOWN");error.resultUnknown=true;error.cause=cause;throw error}if(!response.ok) throw new Error((await response.json().catch(()=>({}))).error_code??`HTTP_${response.status}`);try{return await response.json()}catch(cause){const error=new Error("COMMAND_RESULT_UNKNOWN");error.resultUnknown=true;error.cause=cause;throw error} }
}
const mutations=createMutationRunner((payload,invocationId)=>gateway.command(payload,invocationId))
let chart
let series
let history = []
let drawing = []
let workspaceModel

function text(value){return value == null || value === "" ? "—" : String(value)}
function identity(kind,item){const keys={WorkflowRun:"workflow_run_id",DataSnapshot:"data_snapshot_id",ResearchRun:"research_run_id",ChartAnnotationVersion:"annotation_version_id",TradePlanVersion:"plan_version_id",MarketSnapshot:"market_snapshot_id",PlanEvaluation:"plan_evaluation_id",ArtifactManifest:"artifact_manifest_id",FrozenRef:"ref_id"};return text(item[keys[kind]])}
function historyExplanation(kind,item){
  if(kind==="WorkflowRun")return `研究结果 ${text(item.research_disposition)}；原因 ${text(item.research_reuse_reason)}；复用政策 ${text(item.research_reuse_policy)}`
  if(kind==="DataSnapshot")return `${text(item.snapshot_purpose)} 快照；requested ${text(item.requested_date)}；effective ${text(item.effective_session_date)}；cutoff ${text(item.as_of_at)}；质量 ${text(item.freshness_status)}/${text(item.quality_status)}`
  if(kind==="ResearchRun")return `研究 cutoff ${text(item.original_cutoff_date)}；输入快照 ${text(item.research_snapshot_id)}；JSON ${text(item.canonical_json_artifact_id)}；HTML ${text(item.html_artifact_id)}`
  if(kind==="PlanEvaluation")return `评估器 ${text(item.evaluator_version)}；政策 ${text(item.evaluation_policy_version)}；结果 ${text(item.outcome)}；冻结规则 ${JSON.stringify(item.rules??[])}`
  if(kind==="ArtifactManifest")return `manifest ${text(item.manifest_role)}；成员 ${JSON.stringify(item.members??[])}`
  if(kind==="FrozenRef")return `${text(item.ref_type)} ${text(item.ref_id)} · ${text(item.disposition)}`
  return JSON.stringify(item)
}
function renderWorkspace(model){
  workspaceModel=model
  const task=model.task??{}
  document.querySelector("#task-summary").textContent=task.freshness_status==="valid"?"冻结数据可用于继续检查规则；请确认变化与不确定性。":"本次数据受限；仍可查看已冻结历史，但新的规则结论已阻断。"
  const facts=[["请求日期",task.requested_date],["有效交易日",task.effective_session_date],["数据质量",task.quality_status],["冻结快照",task.snapshot_id]]
  document.querySelector("#task-facts").replaceChildren(...facts.flatMap(([label,value])=>{const dt=document.createElement("dt");dt.textContent=label;const dd=document.createElement("dd");dd.textContent=text(value);return[dt,dd]}))
  const plans=model.history?.plans??[]
  const planCards=plans.map(plan=>{const article=document.createElement("article");const heading=document.createElement("h3");heading.textContent=`计划 v${plan.version_no} · 已确认`;const copy=document.createElement("p");copy.textContent=`输入来源 ${text(plan.user_input_source)} · 冻结于 ${text(plan.created_at)}`;article.append(heading,copy);return article})
  for(const draft of model.plan_drafts??[]){if(draft.status!=="open")continue;const article=document.createElement("article");const heading=document.createElement("h3");heading.textContent=`待确认草稿 r${draft.revision}`;const diff=document.createElement("p");diff.textContent=draft.based_on_version_id?`相对 ${draft.based_on_version_id} 的新版本；确认后并列保留旧版本。`:"初始计划草稿；阈值与金额来自用户输入。";const confirm=document.createElement("button");confirm.type="button";confirm.textContent="确认此计划版本";confirm.addEventListener("click",async()=>{confirm.disabled=true;try{await gateway.confirmPlan({draft_id:draft.draft_id,expected_revision:draft.revision,activation_intent:"activate"},`workspace:plan:${crypto.randomUUID()}`);renderWorkspace(await gateway.workspace())}catch{confirm.disabled=false;diff.textContent="确认未完成；草稿仍保留，可检查后重试。"}});article.append(heading,diff,confirm);planCards.unshift(article)}
  document.querySelector("#plan-list").replaceChildren(...(planCards.length?planCards:[Object.assign(document.createElement("p"),{textContent:"尚无计划草稿或已确认版本；可继续查看研究与标注历史。"})]))
  const workflowRefs=(model.history?.workflows??[]).flatMap(run=>(run.refs??[]).map(ref=>({...ref,created_at:run.created_at,status:ref.disposition})))
  const groups=[["WorkflowRun",model.history?.workflows??[]],["DataSnapshot",model.history?.data_snapshots??[]],["ResearchRun",model.history?.research_runs??[]],["ChartAnnotationVersion",model.history?.annotations??[]],["TradePlanVersion",plans],["MarketSnapshot",model.history?.market_snapshots??[]],["PlanEvaluation",model.history?.evaluations??[]],["ArtifactManifest",model.history?.artifact_manifests??[]],["FrozenRef",workflowRefs]]
  const timeline=groups.flatMap(([kind,items])=>items.map(item=>({kind,item})))
  document.querySelector("#timeline").replaceChildren(...(timeline.length?timeline.map(({kind,item})=>{const li=document.createElement("li");const details=document.createElement("details");const summary=document.createElement("summary");summary.textContent=`${kind} · ${identity(kind,item)} · ${text(item.status??item.lifecycle_status??item.disposition??"frozen")}`;const explanation=document.createElement("p");explanation.textContent=historyExplanation(kind,item);details.append(summary,explanation);li.append(details);return li}):[Object.assign(document.createElement("li"),{textContent:"当前尚无版本历史。"})]))
  document.querySelector("#boundary").textContent=text(model.boundary)
  const latest=model.update_authorizations?.[0]
  document.querySelector("#authorization-status").textContent=latest?`已授权 · ${text(latest.requested_date)} → ${text(latest.effective_session_date)}`:"尚未授权新的更新"
}

function renderLedger() {
  document.querySelector("#ledger").replaceChildren(...history.map(version => {
    const item = document.createElement("li")
    item.textContent = `v${version.version_no} · ${version.status === "deleted" ? "已删除" : "生效"} · ${version.draft.anchors.map(anchor => anchor.exact_price_decimal).join(" → ")}`
    return item
  }))
  const current=history.at(-1)
  document.querySelector("#revise").disabled=!current||current.status!=="active"
  document.querySelector("#delete").disabled=!current||current.status!=="active"
  document.querySelector("#restore").disabled=!current||current.status!=="deleted"
}

const errorMessages={ANNOTATION_PRICE_INVALID:"价格格式无效，请输入普通十进制价格后重试。",ANNOTATION_VERSION_CONFLICT:"标注已被更新，请刷新历史后重试。",INVOCATION_CONFLICT:"请求标识冲突，请重新执行操作。"}
function showFailure(error){const message=error.resultUnknown?"提交结果未知；请保持输入不变并重试同一操作，系统会复用原请求标识。":errorMessages[error.message]??"操作未完成，请检查输入并重试。";document.querySelector("#save-status").textContent=`保存失败：${message}`}
function acceptSaved(saved){history.push(saved);renderLedger()}
function showProjectionFailure(){document.querySelector("#save-status").textContent="已保存，但图表刷新失败；请重新载入页面恢复权威状态。";for(const id of ["start","finish","confirm","revise","delete","restore"]){document.querySelector(`#${id}`).disabled=true}}

async function boot() {
  ;[series,history]=await Promise.all([gateway.series(),gateway.history()])
  renderWorkspace(await gateway.workspace())
  document.querySelector("#session").textContent = `有效交易日 ${series.effective_session_date}`
  document.querySelector("#freshness").textContent = series.freshness === "valid" ? "数据有效" : `数据受限：${series.freshness}`
  document.querySelector("#banner").textContent = series.freshness === "valid" ? "冻结快照已载入；标注锚定市场时间与精确价格。" : "数据不可用或陈旧，绘制已阻断。"
  document.querySelector("#details").textContent = JSON.stringify({data_snapshot_id:series.data_snapshot_id,factor_snapshot_id:series.factor_snapshot_id,adjustment_mode:series.adjustment_mode}, null, 2)
  document.querySelector("#start-price").value=series.bars[0]?.close_decimal ?? ""
  document.querySelector("#end-price").value=series.bars.at(-1)?.close_decimal ?? ""
  if(series.freshness !== "valid") document.querySelector("#start").disabled=true
  chart = init("chart")
  if(!chart) throw new Error("KLINECHART_INIT_FAILED")
  const chartData=toKLineData(series)
  chart.setLocale("zh-CN"); chart.setTimezone("Asia/Shanghai")
  chart.setDataLoader({getBars:({callback})=>callback(chartData,false)})
  chart.setSymbol({ticker:series.security_id,pricePrecision:4,volumePrecision:2})
  chart.setPeriod({type:"day",span:1}); chart.createIndicator("VOL",false)
  history.filter(version => version.status === "active").slice(-1).forEach(version => chart.createOverlay(toOverlay(version)))
  renderLedger()
}

document.querySelector("#start").addEventListener("click", event => { const exact=document.querySelector("#start-price").value; if(!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(exact)) return document.querySelector("#save-status").textContent="起点价格格式无效"; drawing=[{...series.bars[0],close_decimal:exact}]; event.currentTarget.disabled=true; document.querySelector("#finish").disabled=false; document.querySelector("#end-price").focus(); document.querySelector("#save-status").textContent="起点已选择；请选择终点" })
document.querySelector("#finish").addEventListener("click", event => { const exact=document.querySelector("#end-price").value; if(!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(exact)) return document.querySelector("#save-status").textContent="终点价格格式无效"; drawing.push({...series.bars.at(-1),close_decimal:exact}); event.currentTarget.disabled=true; document.querySelector("#confirm").disabled=false; document.querySelector("#confirm").focus(); document.querySelector("#save-status").textContent="终点已选择；请确认持久化" })
document.querySelector("#confirm").addEventListener("click",async event=>{const button=event.currentTarget;button.disabled=true;const payload={operation:"create",kind:"trend_line",style:"accent",anchors:drawing.map(bar=>({market_timestamp:bar.market_timestamp,exact_price_decimal:bar.close_decimal}))};let saved;try{saved=await mutations.run(payload)}catch(error){showFailure(error);button.disabled=false;return}acceptSaved(saved);try{chart.createOverlay(toOverlay(saved))}catch{showProjectionFailure();return}document.querySelector("#save-status").textContent=`已持久化 v${saved.version_no}`;document.querySelector("#start").disabled=false})
document.querySelector("#revise").addEventListener("click",async event=>{event.currentTarget.disabled=true;const current=history.at(-1);const anchors=current.draft.anchors.map((anchor,index)=>({...anchor,exact_price_decimal:index===0?document.querySelector('#start-price').value:document.querySelector('#end-price').value}));let saved;try{saved=await mutations.run({operation:"revise",annotation_id:current.annotation_id,expected_version_no:current.version_no,kind:current.draft.kind,style:"warning",anchors})}catch(error){showFailure(error);renderLedger();return}acceptSaved(saved);try{chart.removeOverlay({id:current.annotation_id});chart.createOverlay(toOverlay(saved))}catch{showProjectionFailure();return}document.querySelector('#save-status').textContent=`已持久化 v${saved.version_no} 修订`})
document.querySelector("#delete").addEventListener("click",async event=>{event.currentTarget.disabled=true;const current=history.at(-1);let saved;try{saved=await mutations.run({operation:"delete",annotation_id:current.annotation_id,expected_version_no:current.version_no})}catch(error){showFailure(error);renderLedger();return}acceptSaved(saved);try{chart.removeOverlay({id:current.annotation_id})}catch{showProjectionFailure();return}document.querySelector('#save-status').textContent=`已持久化 v${saved.version_no} 删除版本`})
document.querySelector("#restore").addEventListener("click",async event=>{event.currentTarget.disabled=true;const current=history.at(-1);let saved;try{saved=await mutations.run({operation:"restore",annotation_id:current.annotation_id,expected_version_no:current.version_no})}catch(error){showFailure(error);renderLedger();return}acceptSaved(saved);try{chart.createOverlay(toOverlay(saved))}catch{showProjectionFailure();return}document.querySelector('#save-status').textContent=`已持久化 v${saved.version_no} 恢复版本`})
document.querySelector("#fullscreen").addEventListener("click", () => document.querySelector(".workspace").classList.toggle("fullscreen"))
document.querySelector("#motion-toggle").addEventListener("click",event=>{const reduced=document.documentElement.classList.toggle("reduce-motion");event.currentTarget.setAttribute("aria-pressed",String(reduced));event.currentTarget.textContent=reduced?"已减少动态效果":"减少动态效果"})
document.querySelector("#authorize-update").addEventListener("click",async event=>{const button=event.currentTarget;button.disabled=true;const payload={requested_date:workspaceModel.task.requested_date,effective_session_date:workspaceModel.task.effective_session_date};try{const saved=await gateway.authorize(payload,`workspace:update:${crypto.randomUUID()}`);document.querySelector("#authorization-status").textContent=`已授权 · ${saved.requested_date} → ${saved.effective_session_date}`}catch{document.querySelector("#authorization-status").textContent="授权未完成；仍可查看现有冻结历史。";button.disabled=false}})
document.querySelectorAll("[data-target]").forEach(button=>button.addEventListener("click",()=>{const target=document.querySelector(`#${button.dataset.target}`);target.scrollIntoView({block:"start"});target.focus?.()}))
window.addEventListener("beforeunload", () => chart && dispose("chart"))
boot().catch(error => { document.querySelector("#banner").textContent=`图表不可用：${error.message}` })
