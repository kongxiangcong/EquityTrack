# `a-stock-data` endpoint terms, protocols, and failure-semantics qualification

Status: `static-qualified / runtime-unqualified`

Research date: `2026-07-24`

Pinned upstream:

- repository: <https://github.com/simonlin1212/a-stock-data>
- commit: `06791b5a3159401524c10bd0e28aaebe415ce604`
- tag: `v3.5.0`
- pinned `SKILL.md` SHA-256:
  `a7369eb8ec07aa5ed5620ddd6f6f4929dab6994713439e871ddeeb4bba170551`

This asset covers the endpoint-terms and protocol part of Wayfinder ticket 04.
It does not execute the upstream Skill, install its dependencies, write outside
the repository, resolve the ticket, or claim that any endpoint passed a live
connectivity or deterministic-fixture qualification. Those runtime results must
be combined with this asset before ticket 04 can be resolved.

## Executive decision

The pinned repository is useful as an **endpoint failure-history and field-mapping
notebook**, but its advertised “44 endpoints” do not form a production-ready
provider:

1. Apache-2.0 covers the repository's authored code and documentation; it does
   not grant rights to TongdaXin, Tencent, Baidu, Eastmoney, Tonghuashun,
   iwencai, Sina, CNINFO, CLS, SSE, or SZSE data.
2. No executable path preserves tradingSystem's required
   `requested_date`, `effective_session_date`, `as_of_at`, `published_at`,
   `available_at`, `retrieved_at`, freshness, quality, authority, immutable
   snapshot identity, and typed external failure semantics.
3. Most empty, partial, rate-limited, unauthorized, timed-out, and schema-drift
   outcomes collapse to `[]`, `{}`, zeros, a warning printed to stdout, or an
   arbitrary HTML table. Unknown is repeatedly converted to zero.
4. The source contains unacceptable transport and filesystem behavior:
   certificate verification is disabled for two SZSE calls, one CNINFO security
   map uses cleartext HTTP, a northbound helper writes under the user home, report
   downloads accept a caller-directed path, and an environment-controlled
   iwencai host receives a bearer credential.
5. Product-specific primary terms do not authorize the undocumented aggregator
   interfaces for a canonical persisted data path. Some first-party terms
   expressly restrict unauthorized third-party extraction, robot access,
   copying, redistribution, or commercial use.
6. CNINFO, SSE, and SZSE provide the only positive terms evidence in this audit:
   their official content may be browsed/downloaded for non-commercial purposes.
   That supports narrowly adapting **official disclosure/regulatory-record
   protocols** for a local, non-commercial research system, subject to HTTPS,
   exact provenance, typed failures, endpoint-specific runtime qualification,
   and no redistribution. It does not qualify their undocumented real-time
   market-data endpoints or grant commercial redistribution rights.

Preliminary disposition:

- `adapt-code`: narrowly scoped CNINFO announcement retrieval and official
  SSE/SZSE announcement/public-trading-record protocols, only after the runtime
  suite proves the exact HTTPS endpoints and the implementation drops all
  insecure transport, guessed identity, fallback, and empty-on-error behavior.
- `auxiliary`: CNINFO Interactive Q&A, because it is company interaction content
  rather than statutory disclosure; it must never upgrade a missing official
  filing. It still requires the same non-commercial/no-redistribution boundary.
- `reject`: all executable TongdaXin/mootdx, Tencent, Baidu, Eastmoney,
  Tonghuashun/Hexin, iwencai, Sina, and CLS data paths at the current evidence
  level, plus the insecure implementations of the official-source fallbacks.
- `reject`: the Skill's source routing, fallbacks, valuation formulas, local
  caches, PDF downloader, free-Python execution model, and direct persistence
  behavior.

Tushare-compatible structured A-share market data and existing official
disclosure policy therefore remain canonical. Nothing in this audit supports a
parallel Skill runtime or a provider-order fallback.

## 1. Primary evidence and rights boundary

### 1.1 Code identity and license

The isolated checkout is clean at the pinned SHA. Its top-level tree contains
only documentation, images, and an Apache-2.0 `LICENSE`; it is not a packaged
Python library and has no machine-readable dependency lock, tests, fixtures, or
CI workflow. The upstream license is:

- <https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/LICENSE>

The dependency and direct-HTTP/TCP design is stated in pinned
[`SKILL.md` lines 243-269](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L243-L269).
The Apache grant does not purport to license any returned third-party data.

### 1.2 First-party terms captured

| Provider | First-party evidence | Cache / redistribution / commercial conclusion |
|---|---|---|
| TongdaXin | [TongdaXin user agreement](https://www.tdx.com.cn/about/yhxy/index.html?tabindex=1) prohibits unauthorized third-party tools from accessing software/server interaction data; its [community rules](https://www.tdx.com.cn/about/sqgz/index.html) expressly prohibit robot scraping and direct users with data needs to business cooperation. | The hard-coded TCP protocol is not authorized for this production use. `mootdx`'s own open-source license cannot cure the data-rights gap. Reject. |
| Tencent | [Tencent Service Agreement](https://edu.tencent.com/agreement.html) limits service use to personal non-commercial use unless otherwise agreed and prohibits unauthorized third-party software from viewing/obtaining service data; Tencent also requires adherence to its robots rules. | No product-specific permission was found for `qt.gtimg.cn` or `ifzq.gtimg.cn`, persistence, redistribution, or commercial use. Reject. |
| Baidu | [Baidu User Agreement](https://passport.baidu.com/static/passpc-account/html/protocal.html) limits authorized copying to information purposes/non-commercial use and reserves site data/content rights; no first-party API contract was found for the PAE path. | An undocumented browser endpoint plus general browse terms does not authorize canonical API ingestion or persistence. Reject. |
| Eastmoney | [Eastmoney User Service Agreement](https://about.eastmoney.com/home/protocol) says its information/data are not guaranteed for truth, completeness, accuracy, timeliness, or continuity and names use through non-authorized means as a risk. No endpoint terms were found for the internal `push2`, `datacenter`, `reportapi`, `search`, `emappdata`, or PDF paths. | “Free” and “no key” are not grants. Cache, retention, redistribution, and commercial rights remain absent. Reject all production endpoint families. |
| Tonghuashun / Hexin | [Tonghuashun Financial Information Service License](https://news.10jqka.com.cn/clientinfo/protocol.html) says free products are for self-use and non-commercial use and may not be copied or distributed; it claims rights in relevant data. No public API contract was found for the scraped HTML/internal JSON paths. | Self-use of a product is not permission to build a persisted provider from internal endpoints. Reject. |
| iwencai | The pinned Skill points to the first-party SkillHub and requires a bearer key, but no accessible first-party endpoint terms establishing cache, retention, redistribution, or commercial rights were found. | Fail closed. Do not request a key to preserve a nonessential candidate. Reject current integration. |
| Sina Finance | [Sina Finance User Agreement](https://finance.sina.com.cn/roll/2021-05-12/doc-ikmxzfmm2033220.shtml) section 6 requires written permission for copying/reading/adopting service content for commercial use or displaying organized content elsewhere; section 10 expressly covers robot/spider monitoring, copying, dissemination, display, mirroring, upload, and download. | The Skill's quote, statement, option, fund-flow, and news endpoints are not licensed for this canonical ingestion path. Reject. |
| CLS | [CLS copyright statement](https://www.cls.cn/our?nav=contact) prohibits use, copying, reproduction, modification, display, or mirroring without written authorization. | Local request signing is not authorization. Reject. |
| CNINFO | [CNINFO legal statement](https://www.cninfo.com.cn/new/snapshot/companyDetailCn?code=000768) identifies CNINFO as the SZSE statutory disclosure platform and permits non-commercial browsing/downloading, while prohibiting direct or indirect for-profit use without written permission. It also says site content is company-supplied and not guaranteed complete/accurate. | Candidate for local non-commercial official-disclosure retrieval only. No redistribution or commercial use; preserve issuer/document provenance. Interactive Q&A remains auxiliary, not statutory disclosure. |
| SZSE | [SZSE legal statement](https://www.szse.cn/application/laws/) permits non-commercial browsing/downloading and prohibits for-profit copying, storage, electronic extraction, transmission, conversion, redistribution, and related use without written permission. | Candidate for narrow local non-commercial official records/disclosures. It does not prove automated real-time quote redistribution rights. |
| SSE | [SSE legal statement](https://www.sse.com.cn/home/legal/) permits non-commercial browsing/downloading and requires written permission for for-profit copying, storage, electronic extraction, transmission, conversion, redistribution, and related use. | Candidate for narrow local non-commercial official records/disclosures. It does not prove automated real-time quote redistribution rights. |

`robots.txt` is not a data license. The Tonghuashun root robots file observed
during this audit only disallowed selected site directories; it neither grants
API access nor overrides the product license. Where no endpoint-specific
first-party terms were found, this audit records rights as absent rather than
inferring permission from accessibility.

This is technical qualification, not legal advice. Any future commercial,
multi-user, or redistributed deployment must re-qualify the relevant rights.

## 2. Executable endpoint and protocol inventory

The upstream's “44 endpoints” is a marketing count rather than a stable exported
API: one table row sometimes contains multiple functions, `mootdx` object
methods, a derived calculation, or documentary-only fallbacks. The inventory
below enumerates every executable external capability in the pinned Skill by
protocol family, without pretending that its count is a contract.

| Family / functions | Transport and request shape | Response / field facts from pinned source | Static failure behavior | Preliminary decision |
|---|---|---|---|---|
| TongdaXin `tdx_client()` then `bars`, `quotes`, `transaction`, `finance`, `F10` | Raw TCP to ten hard-coded IPv4 addresses on port 7709 through `mootdx`; each candidate is handshake-probed and then asked for one daily bar. | Bars claim `open/close/high/low/vol/amount/datetime`; bars are unadjusted. Quote response claims depth, volume, amount, and server time. Transaction claims time, price, volume, count, side. Financial/F10 shapes are library-specific. | Server failures are swallowed while routing to another server; all candidates failing becomes one `RuntimeError`. Transaction empty outside trading hours is not distinguished from wrong identity or outage. Units and schema are not validated. | `reject` endpoint and routing; field/frequency bug history may inform tests only. |
| Tencent `tencent_quote`; documentary minute-K fallback | HTTPS GET to `qt.gtimg.cn`, GBK, semicolon lines and `~`-delimited positional fields; minute K uses `ifzq.gtimg.cn`. | Quote parser claims price CNY, amount in ten-thousand CNY, percentages, market cap in hundred-million CNY, PE/PB, and limits. Minute-K note says volume is lots and the last field is turnover basis points, not amount. | Lines with missing separators or fewer than 53 fields are silently dropped; every empty numeric field becomes `0`; no symbol echo/name validation, `raise_for_status`, freshness, or response timestamp is retained. | `reject`. |
| Baidu `baidu_kline_with_ma` | HTTPS GET to an undocumented PAE browser endpoint with browser `Origin`, `Referer`, and vendor media type. | Dynamic `keys` plus semicolon-delimited rows; claims OHLC, volume, amount, and MA5/10/20. Units and adjustment policy are not established. | HTTP/status/provider result code is ignored. Missing or changed `Result.newMarketData` becomes empty keys/rows. Empty, unauthorized, stale, and schema drift are indistinguishable. | `reject`. |
| Eastmoney `eastmoney_datacenter`; `dragon_tiger_board`; `daily_dragon_tiger`; `lockup_expiry`; `margin_trading`; `block_trade`; `holder_num_change`; `dividend_history` | HTTPS GET to one undocumented data-center endpoint with caller-built report names, filter expressions, paging, and sort fields. | Wrapper returns arbitrary row dicts. Downstream functions claim trade dates, security code/name, net/buy/sell amounts, turnover; lockup shares in ten-thousand shares and ratio as a decimal; several money fields are converted to ten-thousand CNY. | Any missing `result.data` becomes `[]`. No HTTP/status/schema/completeness typing. User-controlled code/date enters a filter expression without lexical validation. Missing numeric fields commonly become `0`. `daily_dragon_tiger` labels any empty as “non-trading day or not updated,” although outage/403/drift are equally possible. | `reject`. |
| Eastmoney `eastmoney_concept_blocks`; `eastmoney_fund_flow_minute`; `industry_comparison`; `board_fund_flow`; `stock_fund_flow_120d`; `eastmoney_stock_info` | HTTPS GET across undocumented `push2` and `push2his` paths with opaque field IDs and a heuristic `secid`. | Claims board names/codes/change/leader; minute and daily fund-flow buckets in CNY; board flows in CNY and percent; stock info/quote fields by opaque IDs. | Several paths catch any exception and return empty lists/zero totals. Others index JSON without typed transport errors. A `6... else 0` market heuristic misrepresents Shanghai ETFs, BSE, and ambiguous instruments. Missing fields default to zero. | `reject`. |
| Eastmoney `em_zt_pool`; `em_zb_pool`; `em_dt_pool`; `em_yzt_pool`; derived `limit_up_sentiment` | HTTPS GET to four undocumented `push2ex` paths, selected by a caller-supplied endpoint string inside the shared helper. | Claims limit/failed-limit/down-limit/prior-limit pools, price scaled from an opaque integer, sealing amounts, board count, open count, and industry. Sentiment is calculated from the four responses. | Any exception becomes `[]`; a real empty pool, rate limiting, 403, timeout, and schema drift are identical. The derived result can therefore assert zero counts/zero break rate from failed inputs. | `reject`. |
| Eastmoney `eastmoney_reports`; `eastmoney_industry_reports`; `download_pdf` | HTTPS paged report list plus a synthesized PDF URL; browser referer; file write to caller-selected directory. | List claims publish date, organization, title, report/industry codes, EPS forecasts, ratings, pages, and size. | Empty data ends pagination, so partial pages and transport/provider failure can look complete. PDF success is only HTTP 200 and at least 1 KiB; no MIME, PDF structure, content hash, size cap, or report identity verification. Existing filename is trusted. Writes are outside a controlled artifact port. | `reject`. |
| Eastmoney `eastmoney_stock_news`; `eastmoney_global_news`; `em_hot_rank`; `em_hot_concept`; announcement fallback | Undocumented search JSONP, fast-news JSON, app-ranking POSTs, push2 name enrichment, and announcement/PDF paths. | Claims article date/title/content/media/URL, news time/content, rank changes, concepts, prices, announcement dates and PDF links. | JSONP/container shapes are brittle; most exceptions become `[]`. Ranking requires a second non-atomically consistent request. No publication-vs-availability semantics, completeness, or article/document authority is preserved. | `reject`. |
| Tonghuashun `ths_eps_forecast` | HTTPS GET of an HTML page, forced GBK, then `pandas.read_html`. | Claims year, institution count, min/mean/max EPS; the mean is treated as consensus. Currency, fiscal basis, accounting basis, coverage, and update time are not captured. | No status check. A table with a matching heading is accepted; otherwise the first table is returned. HTML/layout drift can silently produce a semantically unrelated DataFrame. | `reject`. |
| Tonghuashun `ths_hot_reason` | **Cleartext HTTP** GET to a private event path with a date in the URL. | Claims six-digit code, name, reason tags, close/change in CNY, percent/turnover, amount CNY, volume shares, order-flow indicator, and market. | Provider `errocode` is raised, but HTTP/status/schema/identity are not validated; empty data is accepted. Cleartext transport is inadmissible. Editorial tags are not official facts. | `reject`. |
| Hexin `hsgt_realtime`; local save/load helpers | HTTPS GET of a private JSON path, then optional CSV write under `Path.home()/.tradingagents/cache`. | Claims minute times and cumulative Shanghai-/Shenzhen-connect values in hundred-million CNY. Upstream itself says Shenzhen values are unreliable and historical disclosure changed after 2024-08. | Unequal arrays are padded with `None`, but no session date, availability, finality, correction, freshness, or source revision is recorded. Home writes bypass application persistence and provenance. | `reject`. |
| Tonghuashun `ths_limit_up_pool`; `ths_hot_list`; documentary K-line and financial-statement fallbacks | HTTPS internal JSON/JSONP paths; one HTML/JSON family uses only browser headers. | Claims limit-up themes/types, popularity and concept tags, OHLC/K-lines, and financial statement facts. | Exceptions become `[]`; no schema, identity, calendar, adjustment, publication, availability, or authoritative-source gate. The documentary fallback snippets are not complete tested functions. | `reject`. |
| iwencai `iwencai_search`; `iwencai_query`; `dedup_articles` | HTTPS POST to environment-configurable `IWENCAI_BASE_URL` with bearer token and generated X-Claw headers. | Search/query returns arbitrary dicts; query enables a hidden cache flag. Dedup keeps one row per uid/title-date using an untyped score. | Non-200 and provider status raise `RuntimeError`, but no stable schema, rights, timestamps, or typed error codes exist. Host override can exfiltrate the bearer token. Missing key is still sent. | `reject`. |
| Sina `sina_financial_report`; `sina_option_codes`; `sina_option_tquote`; `sina_option_greeks`; fund-flow/news fallbacks | HTTPS GET, JSON/JSONP/GBK positional parsing and browser referer. | Financial report claims period/items/YoY. Option response claims price/depth/interest/limits and Greeks; IV is a decimal. Fund-flow fallback claims daily net amount and turnover. | Many failures return `[]`/`{}`. Positional option fields have documented past offset hazards. No exchange identity, contract multiplier, quote time, expiry verification, statement publication/availability, or provenance. Primary terms expressly block this use. | `reject`. |
| CLS `cls_telegraph` | HTTPS GET with a reverse-engineered local signature `md5(sha1(sorted query))`. | Claims timestamp/title/content/related stocks from an undocumented response. | No authorization is conveyed by deriving a signature; HTTP/schema/partial/rate semantics are untyped. Copyright terms prohibit use without written authorization. | `reject`. |
| CNINFO `_cninfo_orgid`; `cninfo_announcements` | Security map fetched over **cleartext HTTP**; announcement query uses HTTPS POST with browser headers and a derived `orgId`. | Claims announcement id/title/type/date and a detail URL. CNINFO is the official statutory disclosure platform, but the response lacks a preserved document hash and availability timestamp. | Map failure falls back to a guessed legacy org id; wrong identity may return empty and appear valid. No status/schema/completeness typing. Cleartext identity resolution is unacceptable. | Protocol `adapt-code` candidate only after HTTPS exact-identity resolution, typed failures, document download/hash, and rights/runtime gates; current implementation `reject`. |
| CNINFO `cninfo_irm` | Two HTTPS POSTs: keyword-to-org lookup, then Q&A query whose parameters are placed in the query string. | Claims code/company/question/answer/answerer and converts a millisecond timestamp to local naive minutes. Unanswered questions legitimately have `None`. | First match is trusted without exact identity validation; all exceptions and empty lookup collapse to `[]`; timezone, publication/availability, edits, and answer authority are absent. | `auxiliary` candidate only; current code `reject`. |
| SSE/SZSE `dragon_tiger_backup` | Official HTTPS JSON/JSONP endpoints. The SZSE request uses an SSL context with hostname checking disabled and `CERT_NONE`; SSE returns semi-structured file text. | SZSE claims code/name/amount/reason. SSE preserves only joined text, losing typed seat identity/amounts. | TLS bypass enables interception. No status/schema/completeness/timestamp typing. SSE's free text is not a typed equivalent of the SZSE result. | Official protocol `adapt-code` candidate; current implementation `reject`. |
| SZSE/CNINFO/Eastmoney `announcements_backup` | Deep-SZSE HTTPS POST with TLS verification disabled; Shanghai branch silently switches to Eastmoney, creating an undeclared authority/failure fallback. | Deep-SZSE returns title, publish date, and official PDF link. Shanghai branch returns aggregator title/date/PDF. | TLS bypass; no document hash/identity/completeness. Market-prefix routing silently changes authority. Empty/failure untyped. | Deep-SZSE official protocol `adapt-code` candidate after secure rewrite; entire fallback implementation `reject`. |
| Documentary-only SSE/SZSE quote, HKEX daily statistics, Jin10, Tencent minute K, Tonghuashun K-line/F10 | URLs appear only in the fallback table or partial snippets; there is no complete production contract or fixture. | Claims include exchange quote depth, HKEX northbound daily statistics, news, K-line, and statements. | Not executable/qualified as a coherent adapter. Endpoint-specific terms, schema, units, identity, timestamps, and failures are missing. | `reject` for this candidate; official sources may be separately researched through their own ticket/policy. |

Primary pinned-source references:

- routing, identity heuristics, and Eastmoney transport:
  [`SKILL.md` lines 271-436](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L271-L436)
- quote/K-line protocols:
  [`SKILL.md` lines 441-620](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L441-L620)
- report, consensus, and iwencai paths:
  [`SKILL.md` lines 625-896](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L625-L896)
- signals and home cache:
  [`SKILL.md` lines 900-1178](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L900-L1178)
- data-center and board families:
  [`SKILL.md` lines 1180-1768](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L1180-L1768)
- news, statements, and CNINFO announcements:
  [`SKILL.md` lines 1770-2146](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L1770-L2146)
- pools, options, Q&A, and rankings:
  [`SKILL.md` lines 2149-2512](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2149-L2512)
- fallback table and insecure official-source functions:
  [`SKILL.md` lines 2775-2859](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2775-L2859)

## 3. Identity, unit, calendar, adjustment, and time audit

### 3.1 Security identity

The Skill accepts mostly unvalidated strings and uses multiple incompatible
identity heuristics:

- global prefix routing recognizes selected Shanghai indices, `5/6/9` as
  Shanghai, `4/8` as BSE, and defaults everything else to Shenzhen;
- several Eastmoney functions instead use only `code.startswith("6")`, mapping
  every other instrument to market `0`;
- several Sina/Eastmoney helpers handle only Shanghai-vs-Shenzhen and omit BSE;
- CNINFO picks the first keyword result and can guess a legacy `orgId`;
- the Tencent parser derives identity from the response variable name but does
  not verify returned name/type/exchange against the requested instrument.

Consequences include a known historical wrong-security bug (`000016` routed as
the wrong market), ambiguity between `sh000001` and `sz000001`, and current risk
for ETFs, indices, BSE securities, options, and invalid codes. No function
returns a typed security master identity or rejects mismatched echoed identity.

Required admission rule: an adapted adapter must accept tradingSystem's typed
security identity, construct the provider identity internally, verify all echoed
identity fields, and return `SECURITY_IDENTITY_MISMATCH` rather than empty data.

### 3.2 Units and unknown values

The Skill documents some useful mapping facts, but does not validate them:

| Family | Upstream unit claim | Qualification |
|---|---|---|
| Tencent quote | price CNY; amount ten-thousand CNY; market cap hundred-million CNY; percentages as percentage points | Useful fixture hypothesis, not a contract. Empty numerics becoming `0` is rejected. |
| Tencent minute K | volume lots; last field turnover basis points, not amount | Useful regression fixture for a prior silent thousand-fold error. |
| Tonghuashun hot reasons | amount CNY; volume shares; prices CNY; rates percent | Secondary/editorial only; no provider schema contract. |
| Hexin northbound | hundred-million CNY | Shenzhen series is explicitly unreliable; no session/finality. |
| Eastmoney minute/daily/board fund flow | CNY | Opaque field IDs and missing-to-zero behavior require fixtures; endpoint rights fail. |
| Eastmoney dragon-tiger | output converted to ten-thousand CNY | Conversion is deterministic but source completeness/rights fail. |
| Eastmoney lockup | shares in ten-thousand shares; ratio decimal | Must not default missing shares/ratio to zero. |
| Sina option | IV decimal (for example `0.1735` = `17.35%`) | Positional parser and rights fail; exchange contract semantics absent. |
| CNINFO Q&A | provider timestamp interpreted as Unix milliseconds | Conversion uses local naive time and loses timezone/availability semantics. |

Unknown values are widely converted with `or 0`, empty strings become floats of
zero, and malformed rows are skipped. None of those conversions are admissible.

### 3.3 Trading calendar, adjustment, corporate actions, and market rules

- There is no trading-calendar endpoint or canonical session resolver.
- `mootdx.bars` is explicitly unadjusted. No adjustment factors or corporate
  action lineage are returned.
- The Skill suggests switching sources for adjusted history, which would be a
  forbidden provider fallback and does not define the adjustment algorithm.
- `dividend_history` and `lockup_expiry` expose isolated aggregator events but do
  not provide an authoritative corporate-action ledger or adjustment factors.
- Suspension, stale last quote, no-trade sessions, listing/delisting, ST status,
  BSE rules, and 5%/10%/20% price limits are not represented as typed state.
- Limit-pool data is not a substitute for exchange rules or a complete daily
  limit-state series.

No market-history endpoint in this candidate can support PIT backtesting,
corporate-action adjustment, or trading-rule simulation without a different
canonical source.

### 3.4 Publication, availability, retrieval, and freshness

Some payloads contain a provider date/time (`publishDate`, `TRADE_DATE`,
announcement timestamp, minute clock, news timestamp, quote server time), but:

- the Skill does not distinguish issuer publication time from aggregator
  ingestion time or first availability;
- quote server time is not retained by `tencent_quote`;
- several date strings have no timezone;
- no HTTP `Date`, response metadata, revision, correction, or source snapshot is
  preserved;
- no function records `retrieved_at`;
- no result binds requested date, effective trading session, or actual returned
  date;
- no freshness threshold exists;
- no page/cursor total is bound into completeness evidence;
- no immutable raw payload hash is returned.

Therefore no endpoint currently proves PIT availability. A valid adapted
official-disclosure adapter must preserve the document's issuer/provider
publication time, separately record first-known availability when observable,
always record repository-controlled retrieval time, and bind raw bytes plus
document hash to the immutable snapshot.

## 4. Required failure semantics versus pinned behavior

| Scenario | Pinned behavior | Required canonical behavior |
|---|---|---|
| Normal | Untyped dict/list/DataFrame; usually no source identity, schema version, raw hash, retrieval time, or completeness. | Typed provider result with source-policy version, endpoint/schema identity, requested/effective dates, provenance, quality, and immutable raw evidence. |
| Genuine empty | Usually `[]`, `{}`, empty DataFrame, or zero totals. | `EMPTY_CONFIRMED` only when the endpoint succeeded, identity/session matched, the response is complete, and the domain semantics permit a true empty. |
| Partial/pagination gap | Empty page stops Eastmoney report pagination; page totals/cursors are not retained; multi-request rankings are not atomic. | `PARTIAL_RESPONSE` with expected/received counts, cursor/page evidence, and no promotion to a ready snapshot. |
| Stale | No requested-vs-actual session comparison or freshness rule; provider may return a prior session. | `STALE_RESPONSE` carrying actual session/source time and a policy-calculated age. |
| `429` / rate limit | Eastmoney retries selected GETs three times, then returns a response that downstream may parse; most other paths do nothing. | `RATE_LIMITED` with redacted status, retry-after/backoff evidence, attempt count, and no alternate-source fallback. |
| `401` / `403` | Usually JSON/HTML parse error, swallowed exception, or empty; iwencai raises a free-text `RuntimeError`. | `AUTHENTICATION_FAILED` or `ACCESS_FORBIDDEN`; never empty, never retry a known forbidden response, never switch authority. |
| Timeout / DNS / reset | Sometimes propagates library exception; often caught and converted to empty/warning. | Typed `TIMEOUT`, `DNS_FAILURE`, or `CONNECTION_FAILURE` with attempt evidence. |
| Malformed JSON/JSONP/HTML | Commonly exception-to-empty; HTML consensus may return first unrelated table. | `MALFORMED_RESPONSE` or `SCHEMA_MISMATCH`; retain bounded/redacted payload hash and reject the snapshot. |
| Schema drift / missing field | Opaque field lookups default to empty/zero; short rows are skipped. | Versioned schema validation with required/optional fields, unit checks, and fail-closed diagnostics. |
| Wrong security | Prefix heuristics can query wrong market; no echo validation. | `SECURITY_IDENTITY_MISMATCH`; no result persistence. |
| Non-trading day / suspension / no trades | Often indistinguishable from empty/outage. | Resolve official calendar/session first; return typed `NON_TRADING_SESSION`, `SUSPENDED`, or valid zero-trade state only with authoritative evidence. |
| Upstream correction | No correction/revision model. | Preserve new immutable snapshot/version and lineage; never rewrite prior evidence silently. |

The Eastmoney `Retry` object also retries `429` inside the HTTP adapter before the
application can observe a typed attempt. Random jitter makes exact fixture replay
non-deterministic. Neither behavior should be copied into domain code; retry
policy belongs to the provider adapter and must emit typed attempt evidence.

## 5. Security and operational findings

| Finding | Evidence | Disposition |
|---|---|---|
| TLS verification disabled | `_ctx.check_hostname = False` and `CERT_NONE` are used for SZSE official calls. | Delete from any adapted code; never qualify this implementation. |
| Cleartext official identity lookup | CNINFO organization map uses `http://`. | HTTPS-only replacement with certificate verification and exact identity checks. |
| User-home persistence | Northbound helper creates/overwrites a CSV below `Path.home()`. | Reject; all persistence must cross the canonical repository/application port. |
| Caller-directed file write | Report downloader creates directories and writes PDFs to arbitrary `target_dir`. | Reject; document acquisition must use a controlled artifact root, size cap, atomic write, hash, and repository transaction. |
| Credential destination injection | `IWENCAI_BASE_URL` controls where the bearer key is sent. | Reject; if ever reconsidered, pin scheme/host and isolate credentials. |
| Wide unrestricted egress | Arbitrary direct requests across many hosts and raw TCP IPs; no host allowlist. | Reject direct Skill execution; adapters get one explicit host family and source policy. |
| Filter/query injection | Caller-provided codes/dates are interpolated into Eastmoney filter strings without strict parsing. | Reject; typed identity/date construction only. |
| Unbounded/brittle responses | Most responses have no byte/row/page cap; PDF validates only minimum size; HTML/JSONP parsers are positional. | Bounded transport and schema validation required. |
| Broad exception swallowing | Many `except Exception` blocks print a warning and return empty. | Forbidden; preserve typed redacted failure evidence. |
| Silent authority switching | Fallback instructions switch providers and one announcement helper changes source by market. | Forbidden; source selection is versioned policy and a failure never selects an undeclared source. |
| External financial output | Skill includes forward-PE/PEG/full-valuation workflows and rating/target-price fields. | Reject entirely; formal valuation remains behind tradingSystem's router, source gate, equity bridge, and financial-output boundary. |

## 6. Preliminary adoption matrix

`auxiliary` below means a possible non-authoritative source role, not a fifth
production adoption decision. The final replacement matrix must encode the
production decision using the Goal's four allowed values.

| Capability | Candidate behavior | Preliminary result | Conditions / deletion boundary |
|---|---|---|---|
| A-share structured OHLCV, calendar, adjustment, corporate actions | TongdaXin/Tencent/Baidu/Tonghuashun internal paths | `reject` | Keep Tushare-compatible canonical path. Do not add a provider fallback, direct Skill call, or copied browser protocol. |
| Quotes, valuation ratios, limits, depth | TongdaXin/Tencent/Sina/official documentary quote paths | `reject` | No endpoint has both rights and typed identity/time/unit qualification. |
| Aggregator market signals, fund flow, pools, popularity, northbound | Eastmoney/Tonghuashun/Hexin/Sina | `reject` | Rights fail; failure semantics and PIT fail. Unknown/empty cannot become zero. |
| Consensus and research reports | Eastmoney/Tonghuashun/iwencai | `reject` | No persistence/redistribution grant; ratings/targets cannot bypass financial-output policy. |
| Financial statements/F10 | TongdaXin/Sina/Tonghuashun | `reject` | Critical financial facts continue to require official disclosures. |
| News/telegraph | Eastmoney/CLS/Sina/Jin10 | `reject` | Rights and publication/availability lineage fail. |
| CNINFO statutory announcements | HTTPS official disclosure protocol | `adapt-code` candidate | Local non-commercial only; HTTPS exact org/security identity; document bytes/hash; publication/availability/retrieval; typed empty/partial/error; no guessed fallback. Reuse existing official-disclosure seam rather than create a second path. |
| SZSE official announcements | HTTPS official disclosure protocol | `adapt-code` candidate | Same as CNINFO; certificate verification mandatory. No Eastmoney Shanghai fallback. |
| SSE/SZSE public trading records | Official disclosure/supervision protocol | `adapt-code` candidate | Non-commercial only; exact schema and date completeness; retain official source identity. SSE text requires a real typed parser, not raw text forwarding. |
| CNINFO Interactive Q&A | Company Q&A protocol | `auxiliary` candidate | Never statutory/critical authority; exact company identity; unanswered vs failed distinction; edit/publication lineage; non-commercial/no redistribution. |
| ETF options | Sina positional protocol | `reject` | Rights, contract identity, exchange calendar, multiplier, timestamps, and schema fail. |
| Source routing and fallback | Skill priority/fallback table | `reject` | Provider choice remains versioned source policy; no provider-order loop or prefer-new-else-old. |
| PDF/file/cache behavior | Direct writes and home CSV | `reject` | Use canonical artifact and persistence transactions only. |
| Local valuation formulas/workflows | Forward PE, PEG, full valuation | `reject` | Keep local Forecast/ScenarioValuation/method router and output gates. |

These `adapt-code` rows are not yet “adopted” or production-qualified.
They are eligible to proceed to deterministic fixtures and one controlled live
probe. If the runtime suite cannot establish exact endpoint identity, complete
failure semantics, and the non-commercial deployment boundary, they must be
reclassified to `reject`; no alternate aggregator fallback is permitted.

## 7. Runtime qualification handoff

The endpoint runtime asset should test only the candidates that remain legally
eligible:

1. CNINFO announcement lookup/download over HTTPS;
2. SZSE official announcement lookup/download over HTTPS;
3. SSE/SZSE official public-trading records;
4. optionally CNINFO Q&A as an explicitly auxiliary source.

For every candidate, deterministic fixtures and a controlled live probe must
cover:

- normal response with exact security/exchange/document identity;
- genuine empty on a known valid security/session;
- truncated page and missing next page;
- stale/previous-session response;
- `429`, `401`, `403`, timeout, DNS/reset, invalid JSON/JSONP/HTML, and required
  field removal/type change;
- wrong-security response and ambiguous code;
- publication, availability, retrieval, timezone, revision, and freshness;
- exact units and missing-vs-zero behavior;
- response byte/row/page limits and PDF type/hash/tamper checks;
- TLS certificate and hostname verification;
- source-policy identity and proof that no failed source silently invokes
  another provider.

Market history cannot pass without an authoritative calendar, adjustment
factors, corporate actions, suspension/limit state, and requested-vs-effective
session binding. Because every market-history candidate in this Skill is
rejected on rights or protocol evidence, ticket 04 should not spend runtime
budget probing them merely to prove they are reachable.

## 8. Reproducible static checks

Run from the isolated upstream checkout; these checks do not execute endpoint
code:

```powershell
git remote -v
git status --short
git rev-parse HEAD
git describe --tags --always --dirty
Get-FileHash -Algorithm SHA256 `
  -LiteralPath SKILL.md, README.md, LICENSE, CHANGELOG.md

rg -n "^(def |class )|https?://|requests\.(get|post)|urlopen|url\s*=" SKILL.md
rg -n "CERT_NONE|check_hostname|Path\.home|target_dir|write_bytes|IWENCAI_BASE_URL" SKILL.md
rg -n "except Exception|return \[\]|return \{\}|or 0|pd\.read_html" SKILL.md
rg -n "published|publishDate|available|retrieved|servertime|TRADE_DATE|pubDate" SKILL.md
```

Observed identity:

```text
origin  https://github.com/simonlin1212/a-stock-data.git
HEAD    06791b5a3159401524c10bd0e28aaebe415ce604
tag     v3.5.0
state   clean
```

## 9. Non-negotiable boundary

No code from this Skill may be executed directly by CLI, Web, research, or the
Codex control plane. Any later adaptation must implement one canonical
`DataProvider`/official-disclosure application path, own meaningful protocol
translation and failure policy, preserve immutable evidence, and atomically
replace any superseded behavior. It must not copy the Skill as a module, add a
generic endpoint manager, preserve its fallback table, or create compatibility,
dual-read, shadow-write, direct-file, or parallel-persistence paths.
