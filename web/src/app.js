import {init, dispose} from "klinecharts"
import {toKLineData, toOverlay} from "./chart-adapter.js"
import {createMutationRunner} from "./mutation-runner.js"
const csrfToken=document.querySelector('meta[name="csrf-token"]')?.content ?? ""

const gateway = globalThis.chartGateway ?? {
  async series() { return (await fetch("/api/chart-series", {headers:{Accept:"application/json"}})).json() },
  async history() { return (await fetch("/api/annotations", {headers:{Accept:"application/json"}})).json() },
  async command(payload,invocationId) { let response;try{response=await fetch("/api/annotations", {method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrfToken,"X-Invocation-Id":invocationId},body:JSON.stringify(payload)})}catch(cause){const error=new Error("COMMAND_RESULT_UNKNOWN");error.resultUnknown=true;error.cause=cause;throw error}if(!response.ok) throw new Error((await response.json().catch(()=>({}))).error_code??`HTTP_${response.status}`);try{return await response.json()}catch(cause){const error=new Error("COMMAND_RESULT_UNKNOWN");error.resultUnknown=true;error.cause=cause;throw error} }
}
const mutations=createMutationRunner((payload,invocationId)=>gateway.command(payload,invocationId))
let chart
let series
let history = []
let drawing = []

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
  series = await gateway.series()
  history = await gateway.history()
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
window.addEventListener("beforeunload", () => chart && dispose("chart"))
boot().catch(error => { document.querySelector("#banner").textContent=`图表不可用：${error.message}` })
