# `a-stock-data` upstream identity, license, rights, and attack-surface audit

Audit scope: `https://github.com/simonlin1212/a-stock-data` only.

Audit time: `2026-07-24T09:55:27.8071281Z` (initial clone completed and metadata captured);
remote identity rechecked at `2026-07-24T09:57:40.4797847Z`.

This is a ticket-01 research asset. It does **not** claim or resolve the Wayfinder
ticket, qualify any data endpoint, install dependencies, execute any embedded
Python, or probe any upstream data service.

## Executive finding

`a-stock-data` is an actively edited, Apache-2.0-licensed **single Markdown Skill
containing copy-and-run Python fragments**, not a versioned Python package or a
stable runtime library. At the pinned revision it has no package manifest, lock
file, automated test suite, or CI workflow. Its useful candidate material is
endpoint knowledge, field interpretation, and selected protocol/parsing logic,
which would have to be separately qualified and adapted into tradingSystem's
canonical `DataProvider` path. The upstream Skill must not be executed directly
from CLI, Web, research workflows, or the Codex control plane.

The Apache-2.0 grant applies to the repository's authored code and documentation.
The repository contains no evidence that the third-party data providers grant
storage, caching, redistribution, or commercial-use rights. "Free" and "no key"
claims are authentication/cost claims, not data-rights evidence. Endpoint-level
rights therefore remain unqualified for ticket 04.

Direct execution also exposes capabilities that are outside tradingSystem's
allowed provider boundary: wide HTTP/TCP egress, environment-variable credential
access, caller-directed file writes, user-home caching, a cleartext HTTP request,
disabled TLS certificate verification for selected official-source calls, and
fallbacks that collapse transport/parsing failures into empty/zero-shaped results.

## 1. Isolation and pinned upstream identity

| Field | Evidence |
|---|---|
| Requested isolated path | `E:\workspace\tradingSystem-upstreams\a-stock-data` |
| Absolute-path check before clone | Target resolved to the exact path above; target and parent did not exist |
| Clone location | Outside `E:\workspace\tradingSystem`; not under `.scratch`, `src`, `vendor`, or a submodule |
| Canonical remote observed | `https://github.com/simonlin1212/a-stock-data.git` |
| Default branch | `main` |
| Pinned HEAD | `06791b5a3159401524c10bd0e28aaebe415ce604` |
| Remote recheck | remote `HEAD`, `refs/heads/main`, and `refs/tags/v3.5.0` all resolved to the pinned SHA |
| Tag/release | lightweight tag `v3.5.0`; GitHub marks release `v3.5.0` as Latest |
| Commit timestamp | `2026-07-23T16:17:26+12:00` |
| Commit subject | `feat: 板块资金流向 board_fund_flow (v3.5.0, #37)` |
| Clone state after inspection | clean (`git status --porcelain=v1` emitted no paths) |

Primary identity sources:

- local Git metadata in the isolated clone;
- canonical repository: <https://github.com/simonlin1212/a-stock-data>;
- pinned commit: <https://github.com/simonlin1212/a-stock-data/commit/06791b5a3159401524c10bd0e28aaebe415ce604>;
- pinned release: <https://github.com/simonlin1212/a-stock-data/releases/tag/v3.5.0>.

Pinned file hashes:

| File | Bytes | SHA-256 |
|---|---:|---|
| `LICENSE` | 10,950 | `3771d5ef0b45983555794596241f598ebd90069b1cf8004b06fcf0e75129aa0a` |
| `SKILL.md` | 139,751 | `a7369eb8ec07aa5ed5620ddd6f6f4929dab6994713439e871ddeeb4bba170551` |
| `README.md` | 50,179 | `6491b951d1db6d666c3e97cb8c0da7798a7f05295873c578bfd9f8b0e883af60` |
| `CHANGELOG.md` | 28,388 | `3ecf033998738af1c5a306a91824d742119ca73f03fa0d1e964a85047631a53b` |

The release is source-centric: the repository tree contains `SKILL.md`,
documentation, license, funding metadata, and image assets. It does not contain a
published-package manifest or a stable executable/library entrypoint.

## 2. License and NOTICE

The pinned `LICENSE` is the Apache License 2.0 with `Copyright 2026 Simon Lin`.
Its redistribution conditions include providing the license, marking modified
files, and retaining applicable notices. Source:

- local `E:\workspace\tradingSystem-upstreams\a-stock-data\LICENSE`;
- pinned source:
  <https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/LICENSE>.

No `NOTICE`, `NOTICE.txt`, or equivalent file exists in the pinned tree. Apache
2.0 section 4(d) therefore has no upstream NOTICE payload to propagate from this
revision, but tradingSystem would still need to record origin, pinned commit,
copied files/sections, modifications, and the Apache-2.0 license if code is
adapted.

This is a source audit, not legal advice. It establishes that the repository
declares Apache-2.0; it does not establish the rights of any downstream data
provider.

## 3. Runtime and dependency evidence

### Declared shape

`SKILL.md` declares these installation requirements:

| Dependency | Upstream constraint | Observed purpose |
|---|---|---|
| `mootdx` | `>=0.10` | TongdaXin TCP market data, financial snapshot, and F10 |
| `requests` | `any` | direct HTTP requests |
| `pandas` | `any` | tabular processing and HTML parsing |
| `stockstats` | `any` | technical indicators |

Source: pinned
[`SKILL.md` lines 243-256](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L243-L256).

The repository has none of: `pyproject.toml`, `setup.py`, `setup.cfg`,
`requirements.txt`, `Pipfile`, `poetry.lock`, `uv.lock`, `tox.ini`, or
`noxfile.py`. Consequently:

- there is no machine-verifiable dependency graph or hash lock;
- `requests`, `pandas`, and `stockstats` are unbounded;
- `mootdx` is only lower-bounded;
- transitive dependencies and platform wheels are left to the install-time
  environment;
- `pd.read_html(...)` is used, but an HTML parser backend is not declared or
  pinned in this repository.

### Python version ambiguity

No Python runtime version is declared. Current embedded code uses PEP 604 type
unions such as `dict | None` and `str | None`, which require Python 3.10 or newer
to parse. Yet upstream discusses a Python 3.9 dependency failure as an example,
without reconciling that runtime with the current source syntax. Relevant
sources:

- [`SKILL.md` lines 271-275](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L271-L275);
- [`SKILL.md` lines 410-411](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L410-L411);
- [`SKILL.md` lines 664-665](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L664-L665).

### Known dependency conflict

The upstream README states that `mootdx` pins `httpx<0.26`, conflicting with
MCP environments requiring `httpx>=0.27.1`. It recommends either overriding the
dependency with `--no-deps` or using an isolated venv. The Goal explicitly
forbids hiding dependency conflicts with `--no-deps`, so only isolation or
rejection would be admissible during later qualification. Source:

- local `README.md` lines 282-285;
- pinned
  [`README.md` lines 282-285](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/README.md#L282-L285).

No dependency was installed for this audit.

## 4. Data-source domains and endpoint families

This inventory records attack surface and provenance candidates only. It does not
qualify accuracy, terms, point-in-time semantics, authority, stability, or
production fitness.

| Family | Domains/endpoints observed in pinned source | Claimed capability |
|---|---|---|
| TongdaXin/mootdx | 10 hard-coded IPv4 hosts on TCP `7709` | K-line, quote depth, trades, financial snapshot, F10 |
| Tencent | `qt.gtimg.cn`, `ifzq.gtimg.cn`, referers `gu.qq.com` | quote/valuation fields, full/minute K-line |
| Baidu | `finance.pae.baidu.com`, `gushitong.baidu.com` | K-line and historical/deprecated PAE knowledge |
| Eastmoney data center | `datacenter-web.eastmoney.com/api/data/v1/get` | dragon-tiger, lockups, margin, block trades, holders, dividends |
| Eastmoney market APIs | `push2.eastmoney.com`, `push2his.eastmoney.com`, `push2ex.eastmoney.com`, `emappdata.eastmoney.com` | concepts, fund flows, board/limit pools, popularity |
| Eastmoney research/news | `reportapi.eastmoney.com`, `pdf.dfcfw.com`, `search-api-web.eastmoney.com`, `np-weblist.eastmoney.com`, `np-anotice-stock.eastmoney.com` | report lists/PDFs, news, announcements |
| Tonghuashun/Hexin | `basic.10jqka.com.cn`, `data.10jqka.com.cn`, `d.10jqka.com.cn`, `dq.10jqka.com.cn`, `zx.10jqka.com.cn`, `data.hexin.cn` | consensus, limit pools, K-line fallback, popularity, northbound |
| iwencai | default `openapi.iwencai.com`, configurable through `IWENCAI_BASE_URL` | authenticated semantic search and query-to-data |
| Sina | `quotes.sina.cn`, `hq.sinajs.cn`, `stock.finance.sina.com.cn`, `vip.stock.finance.sina.com.cn`, `zhibo.sina.com.cn` | statements, options, fund flow, news |
| CNINFO | `www.cninfo.com.cn`, `irm.cninfo.com.cn` | security-org mapping, announcements, IR Q&A |
| CLS | `www.cls.cn/v1/roll/get_roll_list` | signed news flash |
| SSE/SZSE official candidates | `query.sse.com.cn`, `yunhq.sse.com.cn`, `www.sse.com.cn`, `www.szse.cn`, `szse.cn`, `disc.static.szse.cn` | dragon-tiger, quote, announcements and PDFs |
| Documentary fallback candidates | `hkex.com.hk`, `jin10.com` | northbound official statistics and news fallback |

The hard-coded TCP servers are listed in pinned
[`SKILL.md` lines 283-289](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L283-L289).
The upstream's own source-priority and fallback tables are in:

- [`SKILL.md` lines 2750-2769](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2750-L2769);
- [`SKILL.md` lines 2775-2793](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2775-L2793).

Not every hostname in those tables is a currently executable primary path.
The source itself labels several historical sources dead or deprecated. Ticket 04
must derive a smaller endpoint-by-endpoint inventory from executable code, then
probe and qualify it without treating this table as proof.

## 5. Network, credentials, writes, subprocesses, and outbound capability

### Outbound network

The embedded code can:

- open raw TCP connections to hard-coded IPs on port `7709`, then issue a real
  K-line request to validate a server
  ([`SKILL.md` lines 279-335](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L279-L335));
- send HTTP `GET` and `POST` requests across all domain families above;
- download binary PDF content;
- send locally signed requests to CLS;
- retry selected Eastmoney GET requests after `429`/5xx responses;
- use a caller/environment-controlled base URL for iwencai requests.

There is no host allowlist, DNS/IP pinning policy, egress proxy boundary, response
size cap for most calls, or canonical typed transport abstraction.

### Credentials and environment

Only iwencai is described as requiring a key. The code reads:

- `IWENCAI_API_KEY`;
- `IWENCAI_BASE_URL` (default `https://openapi.iwencai.com`).

It sends the key as `Authorization: Bearer ...` to the configured base URL
([`SKILL.md` lines 795-874](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L795-L874)).
Because the destination is environment-configurable, an untrusted value could
redirect the bearer credential. No validation constrains the scheme or host.

Other endpoints are claimed to need no key, but the source uses multiple opaque
public request constants (`ut`, application IDs, and `globalId`) and crafted
referer/origin headers. "No key" does not establish authorization or data-use
rights.

### Filesystem reads and writes

Executable snippets can:

- write downloaded research-report PDFs under a caller-provided `target_dir`
  (default `./reports`) and create parent directories
  ([`SKILL.md` lines 627-682](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L627-L682));
- create, read, and overwrite
  `Path.home()/.tradingagents/cache/northbound_daily.csv`
  ([`SKILL.md` lines 975-1046](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L975-L1046));
- indirectly interact with mootdx's user-home configuration; the upstream names
  `~/.mootdx/config.json` as a runtime input
  ([`SKILL.md` lines 271-275](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L271-L275));
- during manual installation, create/copy into
  `~/.claude/skills/a-stock-data`
  ([`SKILL.md` lines 2922-2935](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2922-L2935)).

There is no repository-aware path boundary, artifact root enforcement, quota, or
atomic-write/locking policy. This is incompatible with direct execution against
tradingSystem or personal data roots.

### TLS and cleartext transport

Two concrete transport hazards are present:

1. `_cninfo_orgid` fetches the security mapping over cleartext
   `http://www.cninfo.com.cn/new/data/szse_stock.json`
   ([`SKILL.md` lines 2064-2084](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2064-L2084)).
2. The official-source fallback creates an SSL context with hostname checking
   disabled and `CERT_NONE`, then uses it for SZSE calls
   ([`SKILL.md` lines 2797-2809](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2797-L2809) and
   [`SKILL.md` lines 2834-2846](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2834-L2846)).

Neither behavior is acceptable for a production provider adapter.

### Subprocess and inbound capabilities

No embedded `subprocess`, shell execution, dynamic import, `exec`, `eval`, server,
listener, or inbound network capability was found. The only shell commands are
manual installation instructions. This absence is based on the pinned source
search, not a sandbox guarantee: an AI agent is still instructed to copy and run
free Python fragments.

## 6. Failure-semantics and financial-boundary risks

The source contains many broad `except Exception` handlers that print warnings and
return `[]`, `{... total: 0 ...}`, or `{}`. This makes upstream outage, rate
limiting, authentication failure, schema drift, parsing failure, non-trading-day
absence, and genuine empty results indistinguishable in several paths.

Concrete examples:

- concept-block transport/parsing failure becomes `total=0` and empty lists
  ([`SKILL.md` lines 1071-1107](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L1071-L1107));
- fund-flow request failure becomes an empty list
  ([`SKILL.md` lines 1127-1151](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L1127-L1151));
- an empty dragon-tiger result is labeled "non-trading day or not updated",
  even though the shared fetch path does not type those causes
  ([`SKILL.md` lines 1497-1508](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L1497-L1508));
- CNINFO mapping failure silently falls back to a hard-coded legacy org-id rule
  ([`SKILL.md` lines 2064-2085](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2064-L2085));
- multiple limit-pool and sentiment endpoints return empty lists after arbitrary
  exceptions
  ([`SKILL.md` lines 2156-2178](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2156-L2178)).

The Skill also includes a free-standing `full_valuation` calculation and examples
that consume secondary-source quote/consensus fields without tradingSystem's
method router, official-source gate, source manifest, equity bridge, or typed
degradation behavior
([`SKILL.md` lines 2587-2662](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/SKILL.md#L2587-L2662)).
That workflow cannot cross tradingSystem's financial output boundary.

These are reasons to adapt only narrowly qualified protocol/parsing behavior,
never to adopt the Skill's orchestration or fallback policy wholesale.

## 7. Data rights are not supplied by the code license

The pinned repository:

- provides an Apache-2.0 license for its own work;
- calls many third-party web/API endpoints;
- claims most are "free" and "no key";
- downloads reports and announcements;
- persists a locally accumulated northbound CSV;
- does not include endpoint terms-of-service links, data licenses, redistribution
  grants, caching policies, commercial-use grants, or provider rate-limit terms.

Therefore all of the following remain `unknown` until endpoint-level
qualification:

| Required profile | Current evidence |
|---|---|
| authority | branding/source-domain claims only; official status must be checked per endpoint |
| terms profile | missing |
| storage/cache permission | missing |
| redistribution permission | missing |
| commercial-use permission | missing |
| retention limit | missing |
| documented rate limit | mostly missing; upstream observations are not provider terms |
| provenance contract | no stable response/schema contract |
| PIT/publication/availability semantics | not established |

Even the official exchange/CNINFO candidates require their own terms and endpoint
qualification. An official domain can establish source authority for particular
facts; it does not automatically establish unlimited API, caching, or
redistribution rights.

Ticket 04 should treat each executable endpoint as a distinct candidate. No
endpoint should enter production because it is public, works without a key, or is
mentioned by an Apache-licensed repository.

## 8. Tests, CI, releases, issues, and maintenance evidence

### Tests and CI

The pinned tree has:

- no `tests/` directory or test module;
- no pytest/unittest/tox/nox configuration;
- no deterministic fixtures;
- no schema contract tests;
- no GitHub Actions workflow; `.github` contains only `FUNDING.yml`.

The GitHub Actions page shows the generic "get started" content rather than
repository workflow runs:
<https://github.com/simonlin1212/a-stock-data/actions>.

`CHANGELOG.md` reports manual live-data smoke tests and `py_compile` of 48 Python
code blocks for recent releases. For v3.5.0 it records live board-flow checks,
parameter rejection, and zero syntax errors
([`CHANGELOG.md` lines 3-17](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/CHANGELOG.md#L3-L17)).
For v3.4.1 it records live route/server checks
([`CHANGELOG.md` lines 19-37](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/CHANGELOG.md#L19-L37)).
Those are maintainer-authored release notes, not reproducible test artifacts:
the commands, environment, raw results, and harness are absent from the tree.

### Release and maintenance cadence

Positive maintenance evidence:

- 32 commits from the initial public commit on `2026-05-11` through pinned HEAD
  on `2026-07-23`;
- tags/releases from `v2.1.0` through `v3.5.0`;
- recent issue-driven fixes and two releases on `2026-07-23`;
- release page:
  <https://github.com/simonlin1212/a-stock-data/releases>.

Concentration and maturity risks:

- all 32 commits in the pinned history are authored by `Simon Lin`;
- the repository intentionally retains a single-file form
  ([`CHANGELOG.md` lines 66-75](https://github.com/simonlin1212/a-stock-data/blob/06791b5a3159401524c10bd0e28aaebe415ce604/CHANGELOG.md#L66-L75));
- frequent historical endpoint breakages and silent wrong-data bugs are recorded
  in the changelog;
- the GitHub page showed 2 open issues and 1 open pull request at audit time;
- issue `#42`, "深股通北向资金当日数据异常", was still open and directly
  concerns source reliability:
  <https://github.com/simonlin1212/a-stock-data/issues/42>;
- issue creation is restricted on the repository's Issues page:
  <https://github.com/simonlin1212/a-stock-data/issues>.

The release cadence is evidence of active maintenance, but not of a stable
library contract. Tags pin a changing knowledge document rather than a tested
package API.

## 9. Reproducible audit commands

Run from PowerShell. These commands do not install dependencies or call data
endpoints.

```powershell
# Resolve and verify the exact isolated target before clone.
$target = [System.IO.Path]::GetFullPath(
  'E:\workspace\tradingSystem-upstreams\a-stock-data'
)
$target
Test-Path -LiteralPath $target

# Initial non-destructive clone (only when the target does not exist).
New-Item -ItemType Directory -Path `
  'E:\workspace\tradingSystem-upstreams' -Force
git clone --origin origin -- `
  https://github.com/simonlin1212/a-stock-data.git `
  'E:\workspace\tradingSystem-upstreams\a-stock-data'

# Identity and cleanliness.
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' remote -v
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' rev-parse HEAD
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' branch --show-current
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' status --porcelain=v1
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' `
  log -1 --format='commit=%H%ncommit_time=%cI%nauthor=%an <%ae>%nsubject=%s'
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' `
  tag --points-at HEAD
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' `
  ls-remote origin HEAD refs/heads/main refs/tags/v3.5.0

# Tree, package/CI absence, and source hashes.
git -C 'E:\workspace\tradingSystem-upstreams\a-stock-data' `
  ls-tree -r --name-only HEAD
Get-ChildItem -LiteralPath `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\.github' -Recurse -Force
Get-FileHash -Algorithm SHA256 `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\LICENSE', `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\SKILL.md', `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\README.md', `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\CHANGELOG.md'

# Attack-surface searches.
rg -n 'requests\.(get|post|request)|urlopen|socket\.create_connection|https?://' `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\SKILL.md'
rg -n 'Path\.home|target_dir|write_bytes|write\(|mkdir|read_text|read_csv' `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\SKILL.md'
rg -n 'subprocess|Popen|os\.system|shell=True|exec\(|eval\(|importlib' `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\SKILL.md'
rg -n 'CERT_NONE|check_hostname|http://' `
  'E:\workspace\tradingSystem-upstreams\a-stock-data\SKILL.md'
```

## 10. Boundary for the next ticket

This audit supports only the following preliminary posture:

- do not adopt the Skill/runtime wholesale;
- do not execute its free Python through CLI, Web, research, or Codex;
- do not install its dependencies into tradingSystem;
- consider `adapt-code` only for small, complete endpoint protocol/parsing
  behaviors that pass ticket-04 endpoint qualification;
- preserve Tushare-compatible structured A-share market data and official
  disclosure authority unless stronger evidence supports an explicit
  replacement;
- require typed source policy, provenance, timestamps, freshness/quality,
  immutable snapshot identity, and typed external failures;
- reject all empty-on-error, hard-coded fallback, insecure TLS, cleartext, and
  direct user-home write behavior;
- require endpoint-specific terms, caching, redistribution, and commercial-use
  evidence before production use.

No adopt/adapt/reject decision for an individual endpoint is made here; that
would improperly pre-empt ticket 04.
