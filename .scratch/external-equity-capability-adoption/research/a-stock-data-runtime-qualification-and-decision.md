# `a-stock-data` runtime qualification and ticket-04 decision

Status: `qualified`

Research date: `2026-07-24`

Pinned upstream:

- repository: <https://github.com/simonlin1212/a-stock-data>
- commit/tag: `06791b5a3159401524c10bd0e28aaebe415ce604` / `v3.5.0`
- pinned `SKILL.md` SHA-256:
  `a7369eb8ec07aa5ed5620ddd6f6f4929dab6994713439e871ddeeb4bba170551`

This asset combines:

- the pinned upstream/source audit;
- primary provider terms and protocol review;
- a Python 3.11 isolated dependency installation;
- controlled live connectivity probes that retained only metadata/schema/hashes;
- deterministic replay of synthetic, non-provider payloads.

It is the answer to Wayfinder ticket 04. It does not modify production code or
authorize direct execution of the upstream Skill.

## Decision

The upstream Skill and every one of its current executable implementations are
`reject` for production. It is not a package, has no dependency lock, tests,
fixtures, CI, stable schema, typed failure contract, point-in-time contract, or
data-rights grant. No `a-stock-data` runtime, dependency, fallback table, cache,
file writer, valuation workflow, CLI, or free-form Python enters tradingSystem.

Three official-source request protocols remain eligible for a later owned
`adapt-code` implementation:

1. CNINFO statutory-announcement security mapping and announcement query, using
   HTTPS only;
2. SZSE statutory-announcement query;
3. SSE/SZSE public trading/supervision record query.

This does **not** qualify any current upstream parser. The pinned implementations
use cleartext identity resolution or disabled TLS, guess identity, discard
document/security/time/unit fields, keep SSE records as untyped text, and do not
distinguish empty from failure. A later implementation may adapt only the
verified request protocol and field hypotheses into the canonical
`DataProvider`/official-disclosure path, with a new local parser, typed failures,
immutable raw hashes, source-policy identity, and the full public-interface
suite.

CNINFO Interactive Q&A is at most a non-authoritative, local non-commercial
auxiliary candidate. It cannot upgrade a missing statutory filing, critical
fact, or readiness gate. No current product task needs it, so no adapter or
placeholder is created.

The existing Tushare-compatible provider remains the canonical structured
A-share market-data source. Official disclosures remain the authority for
critical financial facts. There is no temporary dual path, hidden fallback, or
second persistence route.

## 1. Isolated runtime evidence

An upstream-local environment was created at:

`E:\workspace\tradingSystem-upstreams\a-stock-data\.venv-qualification`

The environment is outside tradingSystem and is not a project dependency or
committable artifact.

Exact command:

```powershell
uv venv --python 3.11 .venv-qualification
uv pip install --python .venv-qualification\Scripts\python.exe `
  mootdx requests pandas stockstats
uv pip check --python .venv-qualification\Scripts\python.exe
```

Result:

- duration: `46.6 s`;
- Python: `3.11.15`;
- installed: `mootdx 0.11.7`, `requests 2.34.2`, `pandas 3.0.5`,
  `stockstats 0.6.8`, `httpx 0.25.2`;
- `uv pip check`: all 26 installed packages compatible inside this environment.

The resolution proves the upstream's unbounded requirements currently select
moving versions and force `httpx 0.25.2`. It does not make them suitable for the
project runtime. Isolation avoids contaminating the project environment but
does not cure data rights, home-directory behavior, or protocol semantics.

No `mootdx` market-data method was invoked. Importing/constructing it creates or
reads `Path.home()/.mootdx/config.json`; doing so would touch a user-home path.
The data terms also reject unauthorized third-party server access. A raw,
write-free TCP handshake probe reached all 10 pinned port-7709 addresses in
`12–39 ms`, but the result is deliberately classified as connectivity-only:
upstream itself states that a handshake may still return an empty two-byte
market response. It is not data qualification.

## 2. Live connectivity evidence

Probe payload bodies and financial values were not persisted. Evidence files
retain only status, duration, byte size, schema keys/counts, and SHA-256:

- `a-stock-data-live-probe-evidence.json`;
- `a-stock-data-official-live-probe-evidence.json`.

### Representative aggregator probes

| Protocol family | Live observation | Qualification |
|---|---|---|
| Tencent GBK quote | HTTP `200`, `494` bytes, `202 ms`; positional non-JSON body | Reachable only. Rights fail; missing values become zero; schema/identity/time fail. `reject`. |
| Baidu K-line exact request | HTTP `200`, business code `0`, 18 keys, 2001 rows, `438 ms` | No embedded security identity or publication/availability/retrieval timestamps; rights and adjustment semantics fail. `reject`. |
| Eastmoney quote | First request HTTP `200`; repeat request failed at transport in `91 ms` while peer hosts remained reachable | Demonstrates unstable/blocked transport and absence of typed attempts. Rights fail. `reject`. |
| Eastmoney report list | HTTP `200`, JSON-shaped text, `142 ms` | Reachability does not grant report/PDF storage or redistribution rights; rating/target content is outside the formal path. `reject`. |
| Tonghuashun limit pool | HTTP `200`, business code `0`, three rows, `159 ms` | No publication/availability/retrieval time; internal endpoint rights and PIT fail. `reject`. |
| Sina financial statement | HTTP `200`, top-level `result`, `342 ms` | Critical facts lack official authority, units/restatement/availability and rights. `reject`. |

These calls were intentionally minimal. Once primary terms rejected the
automated/persisted production role, additional calls could not improve the
legal or architectural decision.

### Official-source probes

All official probes used Node's default certificate and hostname verification;
no custom TLS agent or insecure SSL context was used.

| Protocol | Live observation | Result |
|---|---|---|
| CNINFO HTTPS security map | HTTP `200`, 6,221 securities; requested identity found with an organization ID; `262 ms` | HTTPS identity protocol reachable. |
| CNINFO exact announcement query | HTTP `200`, three returned rows, all three matched the requested security; schema included announcement/document/issuer/time fields; `105 ms` | Official protocol remains `adapt-code` candidate. Current parser is rejected because it drops most lineage and uses cleartext mapping plus guessed fallback. |
| SZSE announcement query | HTTP `200`, three rows, all matched requested identity; schema includes `annId`, `secCode`, `publishTime`, attachment path/size; `1080 ms` | Official protocol remains `adapt-code` candidate. Current parser and `CERT_NONE` transport are rejected. |
| SZSE public trading record | HTTP `200`, ten rows; returned code/name/amount/volume/date/reason fields; `265 ms` | Official protocol remains `adapt-code` candidate. Current parser drops date, volume, units and provenance. |
| SSE public trading record | HTTP `200`, 510 record strings; `1048 ms` | Request protocol remains a candidate, but upstream parser is rejected: it joins untyped text and proves no row identity/unit/schema. |

CNINFO's live response contains `announcementTime` and `storageTime`, but the
meaning of `storageTime` as first public availability is not established.
Neither it nor the exchange responses supplies repository `retrieved_at`; the
adapter must record that at acquisition. Live reachability therefore does not
yet prove the complete PIT contract.

## 3. Deterministic replay

Commands:

```powershell
node .scratch/external-equity-capability-adoption/research/a-stock-data-fixture-replay.mjs
node .scratch/external-equity-capability-adoption/research/a-stock-data-official-fixture-replay.mjs
```

Results:

- general replay: `12/12` assertions passed in `0.8 s`;
- official replay: `5/5` assertions passed in `0.8 s`;
- fixtures are fully synthetic and contain no provider data.

Observed deterministic failures in the pinned behavior:

| Case | Pinned output | Required result |
|---|---|---|
| missing Tencent numeric | numeric zero | typed unknown/missing, never zero |
| truncated Tencent positional row | security silently absent | `SCHEMA_MISMATCH` |
| changed Tencent response identity | result keyed to changed security | `SECURITY_IDENTITY_MISMATCH` |
| empty Baidu market data | one blank row | `EMPTY_CONFIRMED` only after identity/completeness proof |
| renamed Baidu field | same empty-looking output | `SCHEMA_MISMATCH` |
| Eastmoney empty vs renamed container | both `[]` | typed empty vs schema mismatch |
| CNINFO empty vs renamed container | both `[]` | typed empty vs schema mismatch |
| rate limit / 401 / timeout / invalid JSON in broad-catch paths | all `[]` | distinct typed external failures |
| CNINFO announcement time | date only; no availability/retrieval | full publication/availability/retrieval lineage |
| SZSE announcement | title/date/link only | retain announcement ID, security identity, attachment metadata/hash and time lineage |
| SZSE trading record | code/name/amount/reason only | retain returned date, volume, units, completeness and time lineage |
| SSE trading record | one joined text blob | typed rows or fail `SCHEMA_MISMATCH`; raw text is not a result |

Stale/session behavior cannot be proven from the Skill because it has no
official trading calendar, requested/effective-session comparison, freshness
policy, or actual-session binding. Suspension and no-trade are likewise
indistinguishable from empty. The correct qualification is failure, not a
synthetic claim that these conditions passed.

## 4. Endpoint-by-endpoint disposition

The pinned routing table's 44 advertised endpoints are grouped below only where
they share the same protocol, terms, parser and failure decision. Every
executable function is included.

| Functions / endpoint family | Production decision | Role and reason |
|---|---|---|
| `tdx_client`; `bars`; `quotes`; `transaction`; `finance`; `F10` | `reject` | TongdaXin terms, hard-coded TCP, user-home configuration, no units/PIT/calendar/adjustment/action lineage, failure routing. |
| `tencent_quote`; Tencent minute-K documentary fallback | `reject` | Unauthorized undocumented browser protocol, positional schema, unknown-to-zero, wrong-identity history. |
| `baidu_kline_with_ma` | `reject` | Undocumented browser API, no identity/adjustment/time contract, empty/drift collision. |
| `eastmoney_datacenter`; `dragon_tiger_board`; `daily_dragon_tiger`; `lockup_expiry`; `margin_trading`; `block_trade`; `holder_num_change`; `dividend_history` | `reject` | Rights absent; arbitrary row dictionaries, filter interpolation, missing-to-zero, empty/failure collision. |
| `eastmoney_concept_blocks`; `eastmoney_fund_flow_minute`; `industry_comparison`; `board_fund_flow`; `stock_fund_flow_120d`; `eastmoney_stock_info` | `reject` | Opaque fields and units, incomplete market identity, broad catch, no PIT. |
| `em_zt_pool`; `em_zb_pool`; `em_dt_pool`; `em_yzt_pool`; `limit_up_sentiment` | `reject` | Empty/error collapse can manufacture zero counts and rates; not authoritative market-rule state. |
| `eastmoney_reports`; `eastmoney_industry_reports`; `download_pdf` | `reject` | Report/PDF rights absent, pagination partials, uncontrolled files, forbidden ratings/targets. |
| `eastmoney_stock_news`; `eastmoney_global_news`; `em_hot_rank`; `em_hot_concept`; Eastmoney announcement fallback | `reject` | Rights, authority, publication/availability and multi-request consistency fail. |
| `ths_eps_forecast`; `ths_hot_reason`; `hsgt_realtime`; cache helpers; `ths_limit_up_pool`; `ths_hot_list`; documentary K-line/F10 fallbacks | `reject` | Internal/cleartext/scraped paths, no storage grant, unreliable series, user-home cache and empty-on-error. |
| `iwencai_search`; `iwencai_query`; `dedup_articles` | `reject` | Nonessential credential, redirectable bearer destination, arbitrary schema, rights absent. |
| `sina_financial_report`; `sina_option_codes`; `sina_option_tquote`; `sina_option_greeks`; fund-flow/news fallbacks | `reject` | Terms restrict this use; critical authority, contract identity, units, time and positional schema fail. |
| `cls_telegraph` | `reject` | Reverse-engineered signing is not authorization; copyright terms and failure typing fail. |
| `_cninfo_orgid`; `cninfo_announcements` current implementation | `reject` | Cleartext mapping, guessed identity, discarded document fields and untyped failures. |
| CNINFO HTTPS statutory-announcement request protocol | `adapt-code` | Local non-commercial/no-redistribution only; exact identity, typed lineage/failures and immutable document hash required in canonical official-disclosure path. |
| `cninfo_irm` current implementation | `reject` | First-match identity and exception-to-empty fail. Its content is auxiliary, not statutory. |
| CNINFO Q&A protocol | `keep-local` | No current production need. It may be a future control-plane/auxiliary source only after a separate typed task and rights gate; no placeholder now. |
| `dragon_tiger_backup` current implementation | `reject` | Disabled SZSE TLS and untyped SSE text are inadmissible. |
| SSE/SZSE public trading-record request protocols | `adapt-code` | Non-commercial official record protocol only; new typed parsers, exact date/completeness/unit/time and secure TLS required. |
| `announcements_backup` current implementation | `reject` | Disabled TLS and silent official-to-Eastmoney authority switching. |
| SZSE statutory-announcement request protocol | `adapt-code` | Non-commercial/no-redistribution official path only; new parser and artifact lineage required. |
| documentary-only SSE/SZSE quote, HKEX/Jin10, Tencent/Tonghuashun fallbacks | `reject` | Not complete executable protocols; endpoint terms/schema/units/time absent. |
| `forward_pe`; `pe_digestion`; `calc_peg`; `full_valuation` | `keep-local` | Existing local Forecast, ScenarioValuation, method router, equity bridge and output boundary remain authoritative; external workflow rejected. |
| upstream priority/fallback table, `em_get` routing, direct PDF/cache behavior | `reject` | Provider choice remains versioned local source policy; no prefer-new-else-old, user-home writes or arbitrary artifact paths. |

No row is `adopt-external`.

## 5. Canonical admission and deletion boundary

The retained official protocol candidates may proceed only through the existing
or explicitly deepened canonical path:

```text
CLI / Web / Codex task
  -> trading_platform.application named task
  -> EvidenceSnapshot / DataSynchronization
  -> one OfficialDisclosure/DataProvider adapter
  -> immutable raw artifact + normalized typed record + source manifest
```

Admission requires:

- typed canonical security/exchange and provider identifiers;
- HTTPS with certificate/hostname verification and a fixed host allowlist;
- non-commercial local-use deployment policy and no redistribution;
- bounded request/response/PDF size, MIME and hash validation;
- `published_at`, justified `available_at`, repository `retrieved_at`, timezone,
  freshness, correction/supersession, page/completeness evidence;
- typed `EMPTY_CONFIRMED`, `PARTIAL_RESPONSE`, `STALE_RESPONSE`,
  `RATE_LIMITED`, `AUTHENTICATION_FAILED`, `ACCESS_FORBIDDEN`, `TIMEOUT`,
  `DNS_FAILURE`, `CONNECTION_FAILURE`, `MALFORMED_RESPONSE`,
  `SCHEMA_MISMATCH`, and `SECURITY_IDENTITY_MISMATCH`;
- deterministic fixture suite plus a controlled live probe;
- source policy chooses one declared adapter; failure never selects an
  undeclared aggregator.

If implemented later, the same atomic slice must delete:

- cleartext CNINFO mapping and guessed organization-ID fallback;
- every `CERT_NONE` / disabled-hostname path;
- raw SSE text forwarding;
- Eastmoney announcement fallback;
- direct file writes and user-home caches;
- broad exception-to-empty/zero behavior;
- caller-built provider identities/filters;
- any test SQL or caller-authored official-filing object replaced by the new
  public interface.

Nothing is deleted now because Wayfinder forbids production edits. No prototype
provider or compatibility path was created.

## 6. Verification ledger

| Check | Duration | Result |
|---|---:|---|
| Isolated Python 3.11 dependency resolution and `uv pip check` | `46.6 s` | pass inside isolated upstream environment; 26 packages compatible |
| Representative live HTTP probes | `1.2 s` first batch; `1.9 s` semantic batch | 8 families reached or produced precise transport evidence; reachability not treated as qualification |
| Official verified-TLS live probes | `3.2 s` | CNINFO/SZSE/SSE protocol evidence captured; no raw payload retained |
| Raw TCP handshake probe | `1.3 s` | 10/10 connected; explicitly not counted as market-data pass |
| General synthetic fixture replay | `0.8 s` | 12/12 assertions passed |
| Official synthetic fixture replay | `0.8 s` | 5/5 assertions passed |

Required production checks are intentionally not marked passed: there is no
production adapter in this ticket. The future implementation slice must run the
full public-interface provider suite and canonical phase gate. No timeout,
external block, or failed required research check remains for this ticket.

## 7. Evidence index

- `a-stock-data-upstream-audit.md`
- `a-stock-data-endpoint-terms-and-protocols.md`
- `a-stock-data-live-probe-evidence.json`
- `a-stock-data-official-live-probe-evidence.json`
- `a-stock-data-fixture-replay.mjs`
- `a-stock-data-official-fixture-replay.mjs`
- `replacement-matrix-application-data.md`

The isolated upstream checkout remained clean at the pinned commit after the
audit. The `.venv-qualification` directory is untracked in that external
checkout and is not part of tradingSystem.
