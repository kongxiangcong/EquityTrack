import assert from "node:assert/strict";

const checks = [];

function check(name, fn) {
  fn();
  checks.push(name);
}

function parseYahooChartCurrent(chart, interval = "1d") {
  const timestamps = chart.timestamp ?? [];
  const quote = chart.indicators?.quote?.[0] ?? {};
  return timestamps.map((timestamp, index) => ({
    timestamp,
    open: quote.open[index] ? Number(quote.open[index].toFixed(2)) : 0,
    high: quote.high[index] ? Number(quote.high[index].toFixed(2)) : 0,
    low: quote.low[index] ? Number(quote.low[index].toFixed(2)) : 0,
    close: quote.close[index] ? Number(quote.close[index].toFixed(2)) : 0,
    volume: quote.volume[index] ? Number(quote.volume[index]) : 0,
    interval,
  }));
}

function parseMagicQuoteCurrent(text, separator, minimumFields, fieldIndexes) {
  const match = text.match(/"(.+)"/);
  if (!match) return {};
  const fields = match[1].split(separator);
  if (fields.length < minimumFields) return {};
  return Object.fromEntries(
    Object.entries(fieldIndexes).map(([name, index]) => [
      name,
      fields[index] ? Number(fields[index]) : 0,
    ]),
  );
}

function parseEastmoneyCurrent(payload) {
  const data = payload.data;
  if (!data) return {};
  const decimals = data.f59 ?? 3;
  const divisor = 10 ** decimals;
  const price = data.f43 === undefined || data.f43 === "-" ? null : data.f43 / divisor;
  return { code: data.f57, price };
}

function parseSecFilingsCurrent(payload, formType = null) {
  const recent = payload.filings?.recent ?? {};
  const forms = recent.form ?? [];
  const dates = recent.filingDate ?? [];
  const accessions = recent.accessionNumber ?? [];
  const primaryDocuments = recent.primaryDocument ?? [];
  const descriptions = recent.primaryDocDescription ?? [];
  const filings = [];
  for (let index = 0; index < forms.length; index += 1) {
    if (formType && forms[index] !== formType) continue;
    filings.push({
      form: forms[index],
      date: dates[index],
      accession_number: accessions[index],
      primary_document: primaryDocuments[index] ?? "",
      description: descriptions[index] ?? "",
    });
  }
  return {
    company_name: payload.name,
    ticker: payload.tickers?.[0] ?? "",
    filings: filings.slice(0, 50),
  };
}

function parseSecFactsCurrent(payload, metricName) {
  const metric = payload.facts?.["us-gaap"]?.[metricName] ?? {};
  if (Object.keys(metric).length === 0) return [];
  const units = metric.units ?? {};
  const unit = "USD" in units ? "USD" : Object.keys(units)[0];
  if (!unit) return [];
  return units[unit]
    .filter((entry) => ["10-K", "10-Q"].includes(entry.form))
    .slice(-20)
    .map((entry) => ({
      end: entry.end,
      val: entry.val,
      form: entry.form,
      filed: entry.filed,
      fy: entry.fy,
      fp: entry.fp,
    }));
}

check("Yahoo converts an unknown price to zero", () => {
  const rows = parseYahooChartCurrent({
    timestamp: [1],
    indicators: { quote: [{ open: [null], high: [2], low: [1], close: [0], volume: [null] }] },
  });
  assert.equal(rows[0].open, 0);
  assert.equal(rows[0].close, 0);
  assert.equal(rows[0].volume, 0);
});

check("Yahoo discards adjustment and corporate-action evidence", () => {
  const fixture = {
    timestamp: [1],
    indicators: {
      quote: [{ open: [1], high: [1], low: [1], close: [1], volume: [1] }],
      adjclose: [{ adjclose: [0.5] }],
    },
    events: { splits: { one: { numerator: 2, denominator: 1 } } },
  };
  const [row] = parseYahooChartCurrent(fixture);
  assert.equal("adjclose" in row, false);
  assert.equal("events" in row, false);
});

check("Yahoo parser silently pads a partial quote array with zero", () => {
  const [row] = parseYahooChartCurrent({
    timestamp: [1],
    indicators: { quote: [{ open: [], high: [1], low: [1], close: [1], volume: [1] }] },
  });
  assert.equal(row.open, 0);
});

check("Magic-array parser maps an empty field to numeric zero", () => {
  const fields = Array(55).fill("1");
  fields[3] = "";
  const parsed = parseMagicQuoteCurrent(`v_quote="${fields.join("~")}"`, "~", 50, {
    price: 3,
    market_cap: 44,
  });
  assert.equal(parsed.price, 0);
});

check("Magic-array parser collapses schema drift and legitimate absence", () => {
  assert.deepEqual(parseMagicQuoteCurrent('v_quote="short"', "~", 50, { price: 3 }), {});
  assert.deepEqual(parseMagicQuoteCurrent("access denied", "~", 50, { price: 3 }), {});
});

check("Eastmoney collapses an error body and a valid empty result", () => {
  assert.deepEqual(parseEastmoneyCurrent({ rc: 1, message: "rate limited" }), {});
  assert.deepEqual(parseEastmoneyCurrent({ rc: 0, data: null }), {});
});

check("Eastmoney scale is response-controlled and unversioned", () => {
  assert.equal(parseEastmoneyCurrent({ data: { f43: 1234, f57: "AAPL", f59: 2 } }).price, 12.34);
  assert.equal(parseEastmoneyCurrent({ data: { f43: 1234, f57: "AAPL", f59: 3 } }).price, 1.234);
});

check("SEC filings silently truncate coverage to fifty", () => {
  const count = 60;
  const payload = {
    name: "Issuer",
    tickers: ["AAA", "AAA.B"],
    filings: {
      recent: {
        form: Array(count).fill("8-K"),
        filingDate: Array(count).fill("2026-01-01"),
        accessionNumber: Array.from({ length: count }, (_, index) => `accn-${index}`),
        primaryDocument: Array(count).fill("doc.htm"),
        primaryDocDescription: Array(count).fill("description"),
      },
      files: [{ name: "CIK-old-submissions-001.json" }],
    },
  };
  const result = parseSecFilingsCurrent(payload);
  assert.equal(result.filings.length, 50);
  assert.equal(result.ticker, "AAA");
  assert.equal("coverage" in result, false);
  assert.equal("historical_files" in result, false);
});

check("SEC filings discard acceptance and report times", () => {
  const result = parseSecFilingsCurrent({
    name: "Issuer",
    tickers: ["AAA"],
    filings: {
      recent: {
        form: ["10-K"],
        filingDate: ["2026-01-02"],
        reportDate: ["2025-12-31"],
        acceptanceDateTime: ["2026-01-02T12:34:56.000Z"],
        accessionNumber: ["0000000000-26-000001"],
        primaryDocument: ["doc.htm"],
        primaryDocDescription: ["Annual report"],
      },
    },
  });
  assert.equal("report_date" in result.filings[0], false);
  assert.equal("acceptance_datetime" in result.filings[0], false);
});

check("SEC facts choose USD and erase context and accession", () => {
  const result = parseSecFactsCurrent(
    {
      facts: {
        "us-gaap": {
          Revenue: {
            units: {
              EUR: [{ val: 90, form: "10-K", start: "2025-01-01", end: "2025-12-31", accn: "eur" }],
              USD: [
                {
                  val: 100,
                  form: "10-K",
                  start: "2025-01-01",
                  end: "2025-12-31",
                  accn: "usd",
                  frame: "CY2025",
                },
              ],
            },
          },
        },
      },
    },
    "Revenue",
  );
  assert.equal(result[0].val, 100);
  assert.equal("start" in result[0], false);
  assert.equal("accn" in result[0], false);
  assert.equal("frame" in result[0], false);
});

check("SEC facts collapse unknown taxonomy and true no-fact", () => {
  assert.deepEqual(parseSecFactsCurrent({ facts: { "ifrs-full": { Revenue: {} } } }, "Revenue"), []);
  assert.deepEqual(parseSecFactsCurrent({ facts: { "us-gaap": {} } }, "Revenue"), []);
});

check("Current result shapes carry no retrieval or artifact identity", () => {
  const filing = parseSecFilingsCurrent({
    name: "Issuer",
    tickers: [],
    filings: { recent: { form: [], filingDate: [], accessionNumber: [] } },
  });
  assert.equal("retrieved_at" in filing, false);
  assert.equal("raw_hash" in filing, false);
  assert.equal("adapter_identity" in filing, false);
});

console.log(
  JSON.stringify(
    {
      suite: "global-stock-data-current-parser-fixture-replay",
      passed: checks.length,
      failed: 0,
      checks,
    },
    null,
    2,
  ),
);
