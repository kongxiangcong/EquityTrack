# Provisional endpoint terms and authority profile

Status: `static-unqualified`

This is the ticket-01 source inventory. It is deliberately fail-closed:
repository code, “free”, “no key”, successful access and an official hostname do
not prove caching, persistence, redistribution or commercial-use rights.
Tickets 04–06 must replace `unknown` with primary terms and runtime evidence
before any source enters production.

Legend:

- `official-candidate`: official domain is visible, but endpoint purpose and
  access/data terms still require qualification.
- `aggregator/secondary`: cannot be the sole authority for critical financial
  facts.
- `commercial-entitlement`: access and downstream rights require a licensed
  account/workspace.
- `engine-input-only`: source must not become a DataProvider through this
  candidate; future evaluation should receive a frozen repository-owned input.

## `a-stock-data`

| Endpoint family / host | Authority | Terms/cache/redistribution | Rate/credential evidence | Provisional result |
|---|---|---|---|---|
| hard-coded TongdaXin TCP hosts:7709 / mootdx | aggregator/secondary | unknown | no key; server probing; undocumented | blocked |
| `qt.gtimg.cn`, `ifzq.gtimg.cn` | aggregator/secondary | unknown | crafted referers; undocumented | blocked |
| `finance.pae.baidu.com`, `gushitong.baidu.com` | aggregator/secondary | unknown | undocumented | blocked |
| `datacenter-web.eastmoney.com` | aggregator/secondary | unknown | public request constants; undocumented | blocked |
| `push2.eastmoney.com`, `push2his.eastmoney.com`, `push2ex.eastmoney.com`, `emappdata.eastmoney.com` | aggregator/secondary | unknown | some observed retry; no primary rate terms | blocked |
| `reportapi.eastmoney.com`, `pdf.dfcfw.com`, Eastmoney search/news/announcement hosts | aggregator/secondary | unknown, including report/PDF storage | downloads binary reports; no primary terms | blocked |
| `basic.10jqka.com.cn`, `data.10jqka.com.cn`, `d.10jqka.com.cn`, `dq.10jqka.com.cn`, `zx.10jqka.com.cn`, `data.hexin.cn` | aggregator/secondary | unknown | no primary terms | blocked |
| `openapi.iwencai.com` or caller-set `IWENCAI_BASE_URL` | commercial/aggregator | unknown | bearer `IWENCAI_API_KEY`; redirectable destination is unsafe | blocked |
| Sina quote/stock/news hosts | aggregator/secondary | unknown | crafted headers; no primary terms | blocked |
| `www.cninfo.com.cn`, `irm.cninfo.com.cn` | official-candidate for A-share disclosures/IR | unknown | one path uses cleartext HTTP; no primary access terms | blocked; insecure path rejected |
| `www.cls.cn` | news/secondary | unknown | locally signed request; no primary terms | blocked |
| `query.sse.com.cn`, `yunhq.sse.com.cn`, `www.sse.com.cn` | official-candidate | unknown | no primary terms captured | blocked |
| `www.szse.cn`, `szse.cn`, `disc.static.szse.cn` | official-candidate | unknown | pinned code disables certificate verification in fallback | blocked; insecure path rejected |
| `hkex.com.hk` | official-candidate for HK market information | unknown | only documentary fallback in this Skill | blocked |
| `jin10.com` | news/secondary | unknown | only documentary fallback | blocked |

## `global-stock-data`

| Endpoint family / host | Authority | Terms/cache/redistribution | Rate/credential evidence | Provisional result |
|---|---|---|---|---|
| `fc.yahoo.com` | aggregator/secondary | unknown | acquires session cookie | blocked |
| `query2.finance.yahoo.com` quoteSummary/chart/options/search | aggregator/secondary | unknown | cookie/crumb, browser UA, 10–15 s timeouts | blocked |
| `datacenter-web.eastmoney.com` | aggregator/secondary | unknown | browser UA; no credential | blocked |
| `push2.eastmoney.com` | aggregator/secondary | unknown | no primary rate terms | blocked |
| `push2his.eastmoney.com` | aggregator/secondary | unknown | no primary rate terms | blocked |
| `searchapi.eastmoney.com` | aggregator/secondary | unknown | hard-coded shared token with undocumented ownership/rotation | blocked |
| `hq.sinajs.cn` | aggregator/secondary | unknown | GBK parsing and referer | blocked |
| `stock.finance.sina.com.cn` | aggregator/secondary | unknown | JSONP/referer | blocked |
| `qt.gtimg.cn` | aggregator/secondary | unknown | no primary terms; current upstream issue challenges field indices/units | blocked |
| `data.sec.gov` submissions/XBRL | official-candidate for US filings/facts | primary SEC policy not yet captured | placeholder UA is noncompliant evidence; no ticket runtime probe | blocked pending SEC terms/UA/rate qualification |
| `www.sec.gov` ticker map/Archives locator | official-candidate | primary SEC policy not yet captured | placeholder UA; no ticket runtime probe | blocked pending SEC terms/UA/rate qualification |

## Vibe-Trading loaders and tools

All rows are `engine-input-only` for this Goal. Vibe-Trading must not become a
second DataProvider router; ticket 06 should prefer a frozen, local,
rights-qualified fixture and deny network egress.

| Loader/source family | Authority/entitlement | Terms/cache/redistribution | Result |
|---|---|---|---|
| Tushare | configured structured-provider candidate, governed by tradingSystem policy | not inherited from Vibe | no direct Vibe fetch |
| yfinance/Yahoo | aggregator/secondary | unknown | no direct Vibe fetch |
| AkShare | library aggregating many sources | endpoint-specific and unknown | no direct Vibe fetch |
| BaoStock | secondary candidate | unknown | no direct Vibe fetch |
| Tencent, Eastmoney, Sina, mootdx | aggregator/secondary | unknown | no direct Vibe fetch |
| CCXT, Binance, OKX and other exchanges | exchange/aggregator varies | per-exchange terms unknown | no direct Vibe fetch |
| Futu, Longbridge, MetaTrader 5, India broker | broker/commercial entitlement | account and data terms unknown | broker/live surface denied |
| Stooq | secondary | unknown | no direct Vibe fetch |
| Finnhub, Alpha Vantage, Tiingo, FMP, QVeris | commercial/freemium entitlement | plan-specific and unknown | no direct Vibe fetch |
| local files | caller-owned only if provenance/rights are proved | controlled artifact root only | candidate frozen input |
| SEC filings tool | official-candidate | SEC policy still required | do not use as Vibe data router |
| research reports/news/options/macro/web search | mixed commercial/secondary | unknown | denied for production adapter |

## Public Equity Investing sources

| Source | Authority/entitlement | Terms/cache/redistribution | Provisional result |
|---|---|---|---|
| Moody's | commercial entitlement | not disclosed in plugin catalog | blocked |
| Daloopa | commercial entitlement | not disclosed | blocked |
| Datasite | commercial/private workspace data | not disclosed | blocked; no private diligence data |
| FactSet | commercial entitlement | not disclosed | blocked |
| LSEG | commercial entitlement | not disclosed | blocked |
| S&P | commercial entitlement | not disclosed | blocked |
| PitchBook | commercial entitlement | not disclosed | blocked |
| Hebbia | hosted research/workspace tool | not disclosed | blocked |
| user-supplied frozen public manifest | original sources govern | repository-approved non-personal inputs only | possible later black-box comparison |

## Qualification handoff

- Ticket 04 must split every executable A-share host/path into a versioned source
  policy row and capture primary terms, timestamps, schema/failure fixtures and a
  real probe.
- Ticket 05 must do the same for US/HK endpoints and use SEC/HKEX/IR official
  sources for critical facts.
- Ticket 06 must not infer data rights from Vibe. It should validate the engine
  with a frozen, rights-qualified input and a deny-by-default tool/network policy.
- No row in this file is production-ready.
