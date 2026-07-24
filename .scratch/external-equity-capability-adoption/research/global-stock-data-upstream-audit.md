# `global-stock-data` upstream identity, licence, rights, and attack-surface audit

## Scope and status

- Candidate: [`simonlin1212/global-stock-data`](https://github.com/simonlin1212/global-stock-data).
- Audit scope: Wayfinder ticket 01 evidence only—repository identity, licence/NOTICE,
  dependency/runtime shape, declared external sources, credentials, local and network
  capabilities, and public maintenance evidence.
- This is **not** the endpoint qualification required by ticket 05. No data endpoint was
  called, no dependency was installed, and no production adoption decision is made here.
- Isolated checkout: `E:\workspace\tradingSystem-upstreams\global-stock-data`.
  The absolute target was resolved before cloning, did not exist, and was confirmed not to
  be inside `E:\workspace\tradingSystem`.
- Clone began at `2026-07-24T09:55:38.7023361Z` (UTC, `.git/HEAD` creation time).
  GitHub API maintenance evidence was fetched at `2026-07-24T09:57:00.189Z`.
- The isolated checkout was clean after inspection. It was not fetched into the product
  repository, `.scratch`, `src`, `vendor`, or a submodule.

## Pinned identity

| Field | Evidence |
|---|---|
| Canonical repository | `https://github.com/simonlin1212/global-stock-data` |
| Configured clone remote | `https://github.com/simonlin1212/global-stock-data.git` |
| Default/current branch | `main` |
| Pinned `HEAD` | `d52a8a0013363577bceb28ca876c88fe6c1a5aeb` |
| Commit time | `2026-06-20T15:23:58+08:00` |
| Commit tree | `5f5d1389277acc78f06cd6051a27cb8fdcd41e7a` |
| Release/tag at `HEAD` | `v1.0.1`; GitHub release published `2026-06-20T07:24:14Z` |
| Prior tag | `v1.0` -> `00292c9f27266efda22de80dda17b158be280a6b` |
| Tag integrity | Both tags are lightweight commit refs, not signed annotated tags; `git verify-tag v1.0.1` reports `cannot verify a non-tag object of type commit` |
| GitHub state at fetch | Not archived/disabled; created `2026-05-20T10:12:30Z`; last push `2026-06-20T07:24:13Z`; 4 commits; 2 releases |

Pinned source links in this note use the immutable commit:

- [`SKILL.md`](https://github.com/simonlin1212/global-stock-data/blob/d52a8a0013363577bceb28ca876c88fe6c1a5aeb/SKILL.md)
- [`LICENSE`](https://github.com/simonlin1212/global-stock-data/blob/d52a8a0013363577bceb28ca876c88fe6c1a5aeb/LICENSE)
- [`CHANGELOG.md`](https://github.com/simonlin1212/global-stock-data/blob/d52a8a0013363577bceb28ca876c88fe6c1a5aeb/CHANGELOG.md)
- [`v1.0.1` release](https://github.com/simonlin1212/global-stock-data/releases/tag/v1.0.1)

### Artifact hashes at the pinned commit

| File | SHA-256 |
|---|---|
| `SKILL.md` | `0DE2209AB626244B945BC86588D33E46E7B9FD215617A3E5510B818B9D9FF696` |
| `LICENSE` | `3771D5EF0B45983555794596241F598EBD90069B1CF8004B06FCF0E75129AA0A` |
| `README.md` | `4AF2E6389A9045EE5CA91F0B3E06CC155FCBC01A0D0BC1F154A495EFFE399068` |
| `CHANGELOG.md` | `189014E6E5044B2FEC755A9443578C0941C9A57D41CE6DDF96AA76B772BEC844` |

## Repository and runtime form

This is a small Skill/endpoint knowledge base, not a released Python package:

- The complete tracked tree has only `.github/FUNDING.yml`, `CHANGELOG.md`,
  `LICENSE`, `README.md`, `SKILL.md`, and two sponsor images.
- There is no `pyproject.toml`, `setup.py`, package module, CLI entrypoint,
  dependency manifest/lock, test tree, fixture tree, or runnable verification script.
- `SKILL.md` is 1,437 lines of Markdown with independent embedded Python snippets.
  Its own installation instruction is only `pip install requests`; the dependency is
  declared as version `any` (`SKILL.md:76-86`). No package hash or version bound exists.
- No Python version is declared. The snippets use built-in generic annotations such as
  `list[str]` (`SKILL.md:151`), so parsing them as written requires Python 3.9 or later.
  This is an inference from syntax, not an upstream runtime guarantee.
- External runtime dependency: `requests`, unconstrained. Standard-library use visible in
  snippets includes `re`, `json`, and `datetime`.
- No dependency was installed for this audit.

The format matters for adoption: the upstream explicitly encourages copying the Markdown
into an agent context and directly executing/copying its code (`README.md:44-50`,
`README.md:220`). That execution model cannot cross tradingSystem's production seam:
it has no typed provider contract, versioned source policy, snapshot identity, or
controlled transport boundary.

## Code licence and data-rights boundary

- The repository contains the Apache License 2.0 text and an appended
  `Copyright 2026 Simon Lin` notice (`LICENSE:1-190`). GitHub reports SPDX
  `Apache-2.0`.
- No `NOTICE` file exists in the pinned tree. There is also no third-party notice,
  provider terms inventory, or data-rights grant.
- Apache-2.0 grants rights in the **repository code/contributions** subject to its
  conditions. It does not grant rights in responses obtained from Eastmoney, Yahoo
  Finance, Sina, Tencent, or SEC endpoints, and it does not establish permission to
  cache, store, redistribute, display, or commercially use those third-party data.
- The README's shorthand “free to use, attribution required” (`README.md:252-254`) is not
  a substitute for the full licence conditions and says nothing about provider data.
- Therefore all non-SEC data rights are **unproven in this upstream**. Even for SEC data,
  public/official source status does not by itself settle access policy, bulk-use,
  retention, or downstream redistribution. Ticket 05 must record each endpoint's
  authority, terms profile, cache/redistribution constraints, rate limits, provenance,
  and time semantics before any production use.
- The Skill contains no HKEXnews or issuer-IR endpoint. Its Hong Kong financial and market
  paths are aggregators (Eastmoney/Yahoo/Sina/Tencent), so nothing in this repository
  satisfies tradingSystem's official-source gate for critical HK disclosures.

## External domains and endpoints declared by source

This inventory is static source inspection, not a connectivity or correctness result.

| Host / authority | Exact path(s) used or emitted | Purpose and code location | Credential/network behaviour |
|---|---|---|---|
| `fc.yahoo.com` | `/` | Bootstrap Yahoo cookie (`SKILL.md:137-146`, `1280-1286`) | HTTPS GET; cookie held in a process-memory `requests.Session`; 10 s timeout |
| `query2.finance.yahoo.com` | `/v1/test/getcrumb`; `/v10/finance/quoteSummary/{symbol}`; `/v8/finance/chart/{symbol}`; `/v7/finance/options/{symbol}`; `/v1/finance/search` | Crumb, quote/financial/analyst/holder modules, OHLCV, options, news (`SKILL.md:144-160`, `443-475`, `1040-1087`, `1273-1299`) | HTTPS GET; browser-like UA; quoteSummary/options use cookie+crumb; no user API key |
| `datacenter-web.eastmoney.com` | `/api/data/v1/get` | US/HK statements and indicators (`SKILL.md:163-183`, `711-777`) | HTTPS GET; browser-like UA; no credential declared; 15 s timeout |
| `push2.eastmoney.com` | `/api/qt/stock/get`; `/api/qt/clist/get` | Quote and market list (`SKILL.md:355-392`, `1337-1395`) | HTTPS GET; no credential declared; 10/15 s timeout |
| `push2his.eastmoney.com` | `/api/qt/stock/fflow/daykline/get` | Daily fund flow (`SKILL.md:994-1027`) | HTTPS GET; no credential declared; 15 s timeout |
| `searchapi.eastmoney.com` | `/api/suggest/get` | Symbol/security search (`SKILL.md:1232-1267`) | HTTPS GET with a hard-coded shared `token=D43...E8`; not a user secret, but its ownership/terms/rotation are undocumented; 10 s timeout |
| `hq.sinajs.cn` | `/list=gb_{ticker}`; `/list=rt_hk{code}` | US/HK quotes (`SKILL.md:197-233`, `314-347`) | HTTPS GET with GBK parsing and Finance-Sina Referer; 10 s timeout |
| `stock.finance.sina.com.cn` | `/usstock/api/jsonp.php/var/US_MinKService.getDailyK` | US daily K-line JSONP (`SKILL.md:412-440`) | HTTPS GET with Referer; 15 s timeout |
| `finance.sina.com.cn` | `/` | Referer only | No response is consumed |
| `qt.gtimg.cn` | `/q=us{ticker}`; `/q=r_hk{code}` | US/HK quotes (`SKILL.md:236-270`, `276-311`) | HTTPS GET with GBK parsing; 10 s timeout |
| `data.sec.gov` (official SEC) | `/submissions/CIK{cik}.json`; `/api/xbrl/companyfacts/CIK{cik}.json` | Filing list and XBRL company facts (`SKILL.md:1097-1206`) | HTTPS GET; 15 s timeout; hard-coded UA uses placeholder `contact@example.com` |
| `www.sec.gov` (official SEC) | `/files/company_tickers.json`; emitted `/Archives/edgar/data/...` document URL | Ticker/CIK map and filing document locator (`SKILL.md:1130`, `1305-1331`) | Mapping is fetched by HTTPS GET; 15 s timeout; same placeholder UA |

The summary table says Sina uses HTTP (`SKILL.md:1426-1435`), while every Sina URL in
the executable snippets is HTTPS. This internal documentation inconsistency is another
reason to qualify code, not prose.

No arbitrary host is accepted as an input. User-controlled ticker/code/CIK values are
inserted into paths or query parameters on the fixed hosts above. The news API returns
provider-supplied links and thumbnail URLs (`SKILL.md:1289-1298`), but this code does not
follow them.

## Local capability and attack-surface inventory

Static inspection of every tracked text file and every code block found:

| Capability | Evidence / result |
|---|---|
| Outbound network | Broad direct GET access to the fixed external domains above; 10–15 s per-request timeouts; no retry, rate limiter, circuit breaker, transport allowlist, redaction layer, or tradingSystem provenance wrapper |
| Credentials/secrets | No environment-secret reader or user token input. Yahoo cookies/crumb are acquired automatically. Eastmoney search embeds a shared token. SEC UA embeds a placeholder email. Request inputs reveal searched securities/keywords to third parties. |
| File reads | None in the embedded Python |
| File writes / writable directories | None in the embedded Python; no artifact or cache directory is defined |
| Persistent cache/database | None |
| In-memory mutable state | Global `_yahoo_session` retains cookies/crumb (`SKILL.md:129-149`); global `_cik_cache` retains the SEC ticker table (`SKILL.md:1305-1320`) |
| Subprocess/shell | None |
| Dynamic execution/import/plugin loading | No `eval`, `exec`, dynamic import, plugin registry, or arbitrary module loading |
| Local listener/server | None |
| User-agent impersonation | Yahoo/Eastmoney/Sina paths use a Safari-like browser UA (`SKILL.md:138`, `166`, `455`, `1281`) |
| Returned active content | No HTML/PDF renderer. News links and SEC filing URLs are returned as strings; upstream does not download or sanitize the linked content. |

This narrower local attack surface does not make direct Skill execution safe for
production. Its network calls bypass tradingSystem's canonical `DataProvider` seam,
source policy, typed failures, PIT timestamps, immutable snapshot identity, and data
rights enforcement.

## Failure, time, identity, and financial-output risks visible before endpoint qualification

These are source-level facts that ticket 05 must test, not endpoint verdicts:

1. **Failure is frequently collapsed into empty data.** Sina parsers return `{}`/`[]` for
   regex/shape failures (`SKILL.md:210-216`, `425-427`); Eastmoney helper and quote/flow
   paths return empty collections for missing response data (`SKILL.md:179-183`,
   `371-374`, `1011-1015`). Those paths do not call `raise_for_status()`. Empty response
   is therefore not distinguishable from no security/no rows/provider failure.
2. **Unknown is often rewritten to zero.** Quote parsers and Yahoo K-line conversion use
   `0` when fields are empty (`SKILL.md:227-232`, `257-268`, `297-309`, `469-473`).
   This violates tradingSystem's unknown-is-not-zero invariant.
3. **No typed time/provenance contract exists.** Returned rows omit `requested_date`,
   `effective_session_date`, `as_of_at`, `published_at`, `available_at`, `retrieved_at`,
   source-manifest identity, freshness, quality, or immutable snapshot identity.
   Yahoo timestamps are converted through local `datetime.fromtimestamp` without an
   explicit timezone (`SKILL.md:464-473`).
4. **No security-identity validation exists.** Callers pass free strings and Eastmoney
   numeric market prefixes; mismatches can return empty or the wrong market.
5. **Critical official-source coverage is incomplete.** SEC EDGAR/XBRL is present for US
   filings/facts, but Eastmoney/Yahoo statement paths are not official disclosures, and
   no HKEX/issuer-IR path exists.
6. **Financial-output boundary is directly exposed.** `key_statistics()` returns analyst
   `target_high`, `target_low`, `target_mean`, and a `recommendation` documented as
   buy/hold/sell (`SKILL.md:801-807`). `analyst_estimates()` returns strong-buy/buy/hold/
   sell/strong-sell counts and upgrade/downgrade history (`SKILL.md:845-901`). These fields
   cannot enter a formal artifact without tradingSystem's financial-output gate.
7. **Current public correctness challenge.** Open issue
   [#2](https://github.com/simonlin1212/global-stock-data/issues/2), created
   `2026-07-24T06:56:18Z`, reports that the pinned Tencent US/HK field indices and market
   capitalization units are wrong. For example, pinned code reads US English name at
   index 27, 52-week high/low at 35/36, market cap at 44, PE at 53, and PB at 56
   (`SKILL.md:254-269`); the issue reports different indices and distinguishes float
   market cap from total market cap. It was open with zero comments at API fetch time.
8. **A recent release fixed silently-empty paths.** `v1.0.1` and its changelog state that
   five functions in `v1.0` built `params` but failed to send them, so the endpoints
   returned empty/wrong data; a second response-shape bug expected a list where Eastmoney
   sometimes returned a dictionary (`CHANGELOG.md:3-15`). This is concrete evidence that
   empty/shape semantics need adversarial fixtures and cannot be trusted from README
   claims.

## Test, CI, release, issue, and maintenance evidence

| Signal | Primary evidence | Audit interpretation |
|---|---|---|
| Tests in pinned tree | `git ls-tree -r --name-only HEAD` contains no test or fixture files | No reproducible upstream test suite is shipped |
| CI | GitHub `actions/workflows` reports `total_count: 0`; `.github` contains only `FUNDING.yml` | No upstream CI evidence |
| Test claim | Commit `9b95390...` says “1404 automated test assertions passed”; no tests or run artifact are in the release tree | Claim is not independently reproducible from the repository |
| Releases | GitHub releases `v1.0` (2026-05-20) and `v1.0.1` (2026-06-20) | Release practice exists, but history is only one month/two releases |
| Commits | Four commits total at fetch; last push 2026-06-20 | Too little history to infer stable maintenance |
| Contributions | One merged external PR, [#1](https://github.com/simonlin1212/global-stock-data/pull/1), fixed five missing-parameter calls | External correction was accepted, but it exposed broad untested breakage |
| Current issues | One open issue, #2, about quote field correctness; `open_issues_count=1` | Pinned release has a live correctness concern |
| Repository state | GitHub reports not archived/disabled | Available, not proof of production maturity |

Stars/forks were visible in GitHub metadata but are deliberately not used as quality or
correctness evidence.

## Ticket-01 conclusion

- **Identity pinned:** yes, to `d52a8a...` / lightweight tag `v1.0.1`, with file hashes.
- **Code licence identified:** Apache-2.0; no NOTICE or third-party notice.
- **Data rights established:** no. The upstream provides no endpoint-specific terms,
  caching, retention, redistribution, or commercial-use grants.
- **Runtime maturity:** Skill/knowledge-base only, not a stable package. Dependency and
  runtime are unpinned; no shipped tests or CI.
- **Attack surface:** fixed-host outbound HTTP(S), in-memory Yahoo cookie/crumb and CIK
  caches, no filesystem/subprocess/dynamic execution. Direct Skill execution would still
  be an impermissible bypass.
- **Qualification posture for ticket 05:** only extract/adapt separately qualified
  protocol/parsing knowledge behind the canonical `DataProvider` seam; do not execute
  `SKILL.md` from CLI/Web/research, do not treat aggregator data as official, and do not
  admit any endpoint until rights, PIT/time semantics, identity, failure/empty/unknown
  behaviour, field stability, and current issue #2 are resolved by evidence.

## Reproduction commands

All commands are read-only except the initial clone into the prevalidated external
directory. They were run from `E:\workspace\tradingSystem`.

```powershell
$parent = Resolve-Path -LiteralPath 'E:\workspace\tradingSystem-upstreams'
$target = [System.IO.Path]::GetFullPath(
  'E:\workspace\tradingSystem-upstreams\global-stock-data'
)
$target.StartsWith(
  [System.IO.Path]::GetFullPath('E:\workspace\tradingSystem') +
    [System.IO.Path]::DirectorySeparatorChar,
  [System.StringComparison]::OrdinalIgnoreCase
)
Test-Path -LiteralPath $target

git clone --origin origin -- `
  https://github.com/simonlin1212/global-stock-data.git `
  'E:\workspace\tradingSystem-upstreams\global-stock-data'

git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' remote get-url origin
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' rev-parse HEAD
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' status --short
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' tag --points-at HEAD
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' log -1 `
  --format='commit=%H%ncommit_time=%cI%nsubject=%s'
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' ls-tree -r `
  --name-only HEAD
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' rev-list --count HEAD
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' cat-file -t `
  refs/tags/v1.0.1
git -C 'E:\workspace\tradingSystem-upstreams\global-stock-data' verify-tag v1.0.1

Get-FileHash -Algorithm SHA256 `
  'E:\workspace\tradingSystem-upstreams\global-stock-data\SKILL.md', `
  'E:\workspace\tradingSystem-upstreams\global-stock-data\LICENSE', `
  'E:\workspace\tradingSystem-upstreams\global-stock-data\README.md', `
  'E:\workspace\tradingSystem-upstreams\global-stock-data\CHANGELOG.md'

rg -n 'https?://|requests\.|Session\(' `
  'E:\workspace\tradingSystem-upstreams\global-stock-data\SKILL.md'
rg -n -i 'subprocess|os\.|open\(|Path\(|write|sqlite|pickle|eval\(|exec\(' `
  'E:\workspace\tradingSystem-upstreams\global-stock-data\SKILL.md'

gh api repos/simonlin1212/global-stock-data
gh api repos/simonlin1212/global-stock-data/releases
gh api repos/simonlin1212/global-stock-data/tags
gh api 'repos/simonlin1212/global-stock-data/issues?state=all&per_page=100'
gh api repos/simonlin1212/global-stock-data/issues/2
gh api repos/simonlin1212/global-stock-data/actions/workflows
gh api 'repos/simonlin1212/global-stock-data/commits?per_page=100'
```

The GitHub API fields used above are reproducible primary evidence, but counts and issue
state are time-varying; the fetch timestamps at the top of this note bind this snapshot.
