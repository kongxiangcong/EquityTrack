import test from "node:test"
import assert from "node:assert/strict"
import {fromConfirmedPoints,toKLineData,toOverlay} from "../src/chart-adapter.js"

test("adapter converts only domain coordinates and never persists pixels or runtime ids", () => {
  const series={interval:"1d",adjustment_mode:"none",bars:[{market_timestamp:"2026-07-10T15:00:00+08:00",open_decimal:"1",high_decimal:"2",low_decimal:"0.5",close_decimal:"1.5",volume_decimal:"10"}]}
  assert.equal(toKLineData(series)[0].close,1.5)
  const draft=fromConfirmedPoints([{timestamp:Date.parse("2026-07-10T07:00:00Z"),value:82.33,exactPriceDecimal:"82.3300"}],{kind:"trend_line"})
  assert.equal(draft.anchors[0].exact_price_decimal,"82.3300")
  assert.deepEqual(Object.keys(draft.anchors[0]).sort(),["exact_price_decimal","market_timestamp"])
  const overlay=toOverlay({annotation_id:"stable",draft:{kind:"trend_line",style:"accent",anchors:draft.anchors}})
  assert.equal(overlay.id,"stable"); assert.equal("dataIndex" in overlay.points[0],false); assert.equal("pixel" in draft,false)
})

test("adapter fails closed on unsupported adjustment and annotation kind", () => {
  assert.throws(()=>toKLineData({interval:"1d",adjustment_mode:"forward",bars:[]}),/CHART_MAPPING_UNAVAILABLE/)
  assert.throws(()=>toOverlay({draft:{kind:"callback",anchors:[]}}),/ANNOTATION_KIND_INVALID/)
})
