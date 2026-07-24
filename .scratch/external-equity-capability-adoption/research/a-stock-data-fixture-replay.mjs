import assert from "node:assert/strict";
import crypto from "node:crypto";

// Qualification-only synthetic replay. This mirrors the parsing decisions in
// a-stock-data@06791b5a3159401524c10bd0e28aaebe415ce604 without importing or
// executing its free-form SKILL.md.

function tencentQuote(body) {
  const result = {};
  for (const line of body.trim().split(";")) {
    if (!line.trim() || !line.includes("=") || !line.includes('"')) continue;
    const key = line.split("=")[0].split("_").at(-1);
    const vals = line.split('"')[1].split("~");
    if (vals.length < 53) continue;
    const numberOrZero = (value) => (value ? Number(value) : 0);
    const code = key.slice(2);
    result[code] = {
      name: vals[1],
      price: numberOrZero(vals[3]),
      pe_ttm: numberOrZero(vals[39]),
      mcap_yi: numberOrZero(vals[44]),
      pb: numberOrZero(vals[46]),
      limit_up: numberOrZero(vals[47]),
      limit_down: numberOrZero(vals[48]),
    };
  }
  return result;
}

function baiduKline(payload) {
  const marketData = payload.Result?.newMarketData ?? {};
  return {
    keys: marketData.keys ?? [],
    rows: (marketData.marketData ?? "").split(";"),
  };
}

function eastmoneyDatacenter(payload) {
  if (payload.result && payload.result.data) return payload.result.data;
  return [];
}

function cninfoAnnouncements(payload) {
  return (payload.announcements ?? []).map((item) => ({
    title: item.announcementTitle ?? "",
    type: item.announcementTypeName ?? "",
    date:
      typeof item.announcementTime === "number"
        ? new Date(item.announcementTime).toISOString().slice(0, 10)
        : String(item.announcementTime ?? "").slice(0, 10),
    url: `https://www.cninfo.com.cn/new/disclosure/detail?annoId=${item.announcementId ?? ""}`,
  }));
}

function broadCatchAsEmpty(operation) {
  try {
    return operation();
  } catch {
    return [];
  }
}

const values = Array(53).fill("");
values[1] = "合成证券";
values[3] = "10.25";
values[39] = "";
values[44] = "100.5";
values[46] = "2.4";
values[47] = "11.28";
values[48] = "9.23";
const normalTencent = `v_sz002897="${values.join("~")}";`;

const observations = [];
function observe(id, actual, consequence) {
  observations.push({
    id,
    actual,
    consequence,
    output_sha256: crypto
      .createHash("sha256")
      .update(JSON.stringify(actual))
      .digest("hex"),
  });
}

const tq = tencentQuote(normalTencent);
assert.equal(tq["002897"].price, 10.25);
assert.equal(tq["002897"].pe_ttm, 0);
observe(
  "tencent_missing_numeric_becomes_zero",
  tq,
  "unknown is converted to zero; violates the local unknown-is-not-zero invariant",
);

const truncated = tencentQuote('v_sz002897="51~fields~only";');
assert.deepEqual(truncated, {});
observe(
  "tencent_truncated_schema_silently_skipped",
  truncated,
  "schema drift is indistinguishable from no security",
);

const wrongIdentity = tencentQuote(normalTencent.replace("v_sz002897", "v_sz000001"));
assert.ok(wrongIdentity["000001"]);
observe(
  "tencent_response_key_controls_identity",
  wrongIdentity,
  "requested security identity is not checked against a typed request",
);

const baiduEmpty = baiduKline({ ResultCode: 0, Result: {} });
assert.deepEqual(baiduEmpty, { keys: [], rows: [""] });
observe(
  "baidu_empty_payload_becomes_blank_row",
  baiduEmpty,
  "empty is represented as one blank record and has no typed empty reason",
);

const baiduDrift = baiduKline({
  ResultCode: 0,
  Result: { newMarketData: { keys: ["time", "close"], rows: "drifted" } },
});
assert.deepEqual(baiduDrift, { keys: ["time", "close"], rows: [""] });
observe(
  "baidu_renamed_marketData_silently_empty",
  baiduDrift,
  "field drift is silently converted to an empty-looking result",
);

const emEmpty = eastmoneyDatacenter({ result: { data: [] } });
const emDrift = eastmoneyDatacenter({ result: { rows: [{ SECURITY_CODE: "002897" }] } });
assert.deepEqual(emEmpty, []);
assert.deepEqual(emDrift, []);
observe(
  "eastmoney_empty_and_schema_drift_collide",
  { empty: emEmpty, schema_drift: emDrift },
  "valid empty and incompatible schema have identical outputs",
);

const cnEmpty = cninfoAnnouncements({ announcements: [] });
const cnDrift = cninfoAnnouncements({ announcementList: [{ announcementId: "synthetic" }] });
assert.deepEqual(cnEmpty, []);
assert.deepEqual(cnDrift, []);
observe(
  "cninfo_empty_and_schema_drift_collide",
  { empty: cnEmpty, schema_drift: cnDrift },
  "official result emptiness cannot be distinguished from parser drift",
);

for (const failure of ["rate_limit_429", "auth_401", "timeout", "invalid_json"]) {
  const collapsed = broadCatchAsEmpty(() => {
    throw new Error(failure);
  });
  assert.deepEqual(collapsed, []);
  observe(
    `broad_catch_${failure}_becomes_empty`,
    collapsed,
    "transport/protocol failure is indistinguishable from a valid empty dataset",
  );
}

const temporal = cninfoAnnouncements({
  announcements: [
    {
      announcementId: "synthetic",
      announcementTitle: "合成公告",
      announcementTime: Date.UTC(2026, 6, 1),
    },
  ],
});
assert.equal(temporal[0].date, "2026-07-01");
assert.equal("available_at" in temporal[0], false);
assert.equal("retrieved_at" in temporal[0], false);
observe(
  "cninfo_temporal_lineage_incomplete",
  temporal,
  "publication date is derived, but available_at and retrieved_at are absent",
);

console.log(
  JSON.stringify(
    {
      fixture_kind: "synthetic-no-provider-payload",
      upstream_commit: "06791b5a3159401524c10bd0e28aaebe415ce604",
      cases: observations.length,
      observations,
    },
    null,
    2,
  ),
);
