import assert from "node:assert/strict";
import crypto from "node:crypto";

function hash(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function szseAnnouncementBackup(payload) {
  return (payload.data ?? []).map((item) => ({
    title: item.title,
    time: (item.publishTime ?? "").slice(0, 10),
    pdf: `https://disc.static.szse.cn/download${item.attachPath ?? ""}`,
  }));
}

function szseDragonTigerBackup(payload) {
  return (payload?.[0]?.data ?? []).map((row) => ({
    code: row.zqdm,
    name: row.zqjc,
    amount: row.cjje,
    reason: row.plyy,
  }));
}

const observations = [];
function observe(id, actual, consequence) {
  observations.push({ id, actual, consequence, output_sha256: hash(actual) });
}

const announcement = szseAnnouncementBackup({
  data: [
    {
      annId: "synthetic-announcement",
      secCode: ["002897"],
      secName: ["合成证券"],
      title: "合成公告",
      publishTime: "2026-07-01 08:00:00",
      attachPath: "/synthetic.pdf",
      attachSize: 1234,
    },
  ],
});
assert.equal(announcement[0].title, "合成公告");
assert.equal("annId" in announcement[0], false);
assert.equal("secCode" in announcement[0], false);
observe(
  "szse_announcement_parser_drops_document_and_security_identity",
  announcement,
  "title/date/link survive, but announcement id, security identity, size, availability, retrieval, and hash are dropped",
);

const announcementEmpty = szseAnnouncementBackup({ data: [] });
const announcementDrift = szseAnnouncementBackup({ announcements: [{ title: "合成公告" }] });
assert.deepEqual(announcementEmpty, []);
assert.deepEqual(announcementDrift, []);
observe(
  "szse_announcement_empty_and_schema_drift_collide",
  { empty: announcementEmpty, schema_drift: announcementDrift },
  "a valid empty result and a renamed container produce the same output",
);

const tradingRecord = szseDragonTigerBackup([
  {
    data: [
      {
        zqdm: "002897",
        zqjc: "合成证券",
        cjje: "1000",
        cjsl: "10",
        dqrq: "2026-07-01",
        plyy: "合成原因",
      },
    ],
  },
]);
assert.equal(tradingRecord[0].code, "002897");
assert.equal("date" in tradingRecord[0], false);
assert.equal("volume" in tradingRecord[0], false);
observe(
  "szse_trading_record_parser_drops_date_volume_and_units",
  tradingRecord,
  "code/name/amount/reason survive, but returned date, volume, units, publication, availability, retrieval, and completeness are dropped",
);

const tradingEmpty = szseDragonTigerBackup([{ data: [] }]);
const tradingPartial = szseDragonTigerBackup([{ data: [{ zqdm: "002897" }] }]);
assert.deepEqual(tradingEmpty, []);
assert.equal(tradingPartial[0].amount, undefined);
observe(
  "szse_trading_empty_and_partial_are_untyped",
  { empty: tradingEmpty, partial: tradingPartial },
  "empty and missing required fields carry no distinct typed status",
);

const sseRaw = {
  date: "2026-07-01",
  sse_raw: ["synthetic heading", "synthetic record"].join("\n"),
  szse: [],
};
assert.equal(typeof sseRaw.sse_raw, "string");
observe(
  "sse_trading_record_is_untyped_text",
  sseRaw,
  "joined official record lines have no typed identity, amount, unit, row count, or schema",
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
