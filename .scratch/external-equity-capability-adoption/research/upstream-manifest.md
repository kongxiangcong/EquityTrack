# External equity capability upstream manifest

Captured: `2026-07-24`

This manifest is the canonical ticket-01 index. Detailed evidence and
reproduction commands live in the linked audits; this file does not copy entire
upstream READMEs or source trees.

## Reproducible identity

| Candidate | Canonical identity | Pinned revision | Release/tag | Licence and notices | Current availability |
|---|---|---|---|---|---|
| Public Equity Investing | OpenAI hosted catalog: <https://openai.com/business/plugins/public-equity-investing/> | No source commit or artifact hash disclosed | Hosted rollout; no reproducible release exposed to this thread | No source licence/NOTICE disclosed | `external_blocked`: Plugin Management returned `plugin_not_found` |
| `a-stock-data` | <https://github.com/simonlin1212/a-stock-data> | `06791b5a3159401524c10bd0e28aaebe415ce604` | lightweight tag and latest release `v3.5.0` | Apache-2.0; no NOTICE file | Clean external clone at `E:\workspace\tradingSystem-upstreams\a-stock-data` |
| `global-stock-data` | <https://github.com/simonlin1212/global-stock-data> | `d52a8a0013363577bceb28ca876c88fe6c1a5aeb` | lightweight tag/release `v1.0.1` | Apache-2.0; no NOTICE file | Clean external clone at `E:\workspace\tradingSystem-upstreams\global-stock-data` |
| `Vibe-Trading` | <https://github.com/HKUDS/Vibe-Trading> | `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` | `v0.1.12-78-g0aa45a9` | MIT; NOTICE plus bundled factor attribution | Clean external clone at `E:\workspace\tradingSystem-upstreams\Vibe-Trading` |

## Pinned file hashes

| Candidate | File | SHA-256 |
|---|---|---|
| `a-stock-data` | `LICENSE` | `3771d5ef0b45983555794596241f598ebd90069b1cf8004b06fcf0e75129aa0a` |
| `a-stock-data` | `SKILL.md` | `a7369eb8ec07aa5ed5620ddd6f6f4929dab6994713439e871ddeeb4bba170551` |
| `a-stock-data` | `README.md` | `6491b951d1db6d666c3e97cb8c0da7798a7f05295873c578bfd9f8b0e883af60` |
| `a-stock-data` | `CHANGELOG.md` | `3ecf033998738af1c5a306a91824d742119ca73f03fa0d1e964a85047631a53b` |
| `global-stock-data` | `LICENSE` | `3771d5ef0b45983555794596241f598ebd90069b1cf8004b06fcf0e75129aa0a` |
| `global-stock-data` | `SKILL.md` | `0de2209ab626244b945bc86588d33e46e7b9fd215617a3e5510b818b9d9ff696` |
| `global-stock-data` | `README.md` | `4af2e6389a9045ee5ca91f0b3e06cc155fcbc01a0d0bc1f154a495effe399068` |
| `global-stock-data` | `CHANGELOG.md` | `189014e6e5044b2fec755a9443578c0941c9a57d41ce6ddf96aa76b772bec844` |
| `Vibe-Trading` | `LICENSE` | `399b7c624a8feb0388293c17782e04a87da7741c5362cfa36f80452b58385802` |
| `Vibe-Trading` | `NOTICE` | `ff585653f9f7b3b3792175e837ca8897ef3f9a0bed3d94ce8f09366aebac56ae` |
| `Vibe-Trading` | `pyproject.toml` | `af07cebb666de3bf53f604741047f261693c303fc531333ebfff7f2b2c2631a0` |
| `Vibe-Trading` | `README.md` | `27e77f16299956263421f757d7aec9b9308d8974c83864af9ac571e7c7176711` |
| `Vibe-Trading` | `requirements-lock.txt` | `b5a1bb3e28bc78d519537a72b00014f5aaca9df55986a6de541e639e6b45d841` |

## Runtime, dependency and maintenance summary

| Candidate | Runtime/dependency shape | Tests/CI/release evidence | Qualification consequence |
|---|---|---|---|
| Public Equity Investing | Hosted role plugin bundling skills/workflows and underlying apps; exact manifest unavailable | OpenAI product page and rollout announcement only; no locally reproducible artifact | It cannot be copied, pinned as runtime code, or treated as a data source. Later black-box comparison requires actual workspace availability. |
| `a-stock-data` | One 139 KB `SKILL.md` containing copy-and-run snippets; Python version undeclared/current syntax needs >=3.10; `mootdx>=0.10`, unbounded requests/pandas/stockstats; known `httpx` conflict | 32 commits and active releases/issues; no package manifest, lock, shipped tests or CI | Only separately qualified protocol/parser behavior can be adapted. Do not execute the Skill or use `--no-deps`. |
| `global-stock-data` | One 1,437-line `SKILL.md`; unconstrained requests; Python not declared/current syntax implies >=3.9 | Four commits, two releases, no shipped tests/CI; current issue #2 challenges quote indices/units; v1.0.1 fixed silent empty results | Treat as endpoint knowledge, not a library. Every parser needs independent fixtures and current field evidence. |
| `Vibe-Trading` | Full Python >=3.11 app with CLI, FastAPI, MCP, Web, LLM, data, backtest, broker, document and rendering stacks; lock file exists | 1,013 commits, 331 test files, three workflows and releases; active correctness/security repair history | Only a pinned isolated process and minimal strategy-validation tool allowlist can be considered. No in-process/full-app adoption. |

## Attack-surface summary

| Candidate | Network/credentials | Files/process/persistence | Forbidden or constrained surface |
|---|---|---|---|
| Public Equity Investing | Underlying apps may search/read/sync/write; named commercial providers require independent entitlements | Hosted processing/retention and exact app manifest are unknown | No personal data/secrets, sync, writes, runtime dependency, data-authority role or unfiltered investment language |
| `a-stock-data` | Broad fixed HTTP/TCP sources; iwencai bearer key and configurable base URL; opaque shared constants; cleartext CNINFO and disabled TLS verification in SZSE fallback | Caller-directed PDF writes, user-home CSV/config/cache; no subprocess in pinned snippets | Direct Skill execution, insecure transport, arbitrary/user-home writes, empty-on-error and legacy fallback are rejected |
| `global-stock-data` | Fixed Yahoo/Eastmoney/Sina/Tencent/SEC GETs; in-memory Yahoo cookie/crumb; shared Eastmoney token; placeholder SEC UA | No file/subprocess/dynamic-exec path in snippets; process-memory caches only | Direct Skill execution, unknown-to-zero, empty-on-error, unqualified analyst ratings/targets and aggregator authority are rejected |
| `Vibe-Trading` | Data/search/LLM/messaging/broker/external-MCP egress; broker and provider credentials | Web/API/MCP servers, generated-code subprocess, read/write tools, user-home state, memory, scheduler, swarm, artifacts and optional shell | Deny live/order/broker, arbitrary file/web/search, memory, scheduler, swarm, shell, external MCP and full Web. Allow only a future explicit strategy-validation subset in an isolated process. |

## Data-rights result

The three code licences govern repository code, not third-party responses. None
of the candidates establishes all required endpoint rights for cache,
persistence, derivation, redistribution or commercial use:

- `a-stock-data` and `global-stock-data` provide no endpoint terms inventory.
- Vibe-Trading's NOTICE covers bundled code/formulas, not its data loaders.
- Public Equity Investing names commercial providers but exposes neither this
  user's entitlements nor those providers' downstream rights.
- Official-source status can establish authority for a fact; it does not grant
  unlimited automated access, caching or redistribution.

The provisional per-source record is
[endpoint-terms-profile.md](endpoint-terms-profile.md). Every row remains
production-blocked until its later qualification ticket supplies primary terms
and runtime evidence.

## Unknowns classified by effect

### Blocks production adoption of the affected capability

- missing endpoint-specific terms, cache/redistribution/commercial-use rights;
- unknown PIT/publication/availability/retrieval semantics and source identity;
- Public Equity Investing's unavailable manifest, workspace eligibility and
  underlying app/provider entitlements;
- insecure transport, empty-on-error, unknown-as-zero or untyped fallback;
- Vibe-Trading's unrestricted MCP/full-app surface and any result lacking typed
  identity, lineage and tamper checks.

### Limits the candidate without blocking the whole Goal

- Public Equity Investing may remain `external_blocked`; its role is optional
  control-plane comparison, never production runtime.
- Unknown data-loader rights do not prevent offline Vibe algorithm evaluation
  against a repository-owned frozen fixture with egress denied.
- Unsigned/lightweight tags do not prevent reproducibility when the full commit
  and file hashes are pinned.
- Missing upstream NOTICE in the Apache repositories does not remove Apache
  obligations; it simply means there is no upstream NOTICE payload at these
  commits.
- Rejected endpoint behavior does not prevent adapting a different, separately
  qualified protocol/parser from the same repository.

## Detailed evidence

- [Public Equity Investing audit](public-equity-investing-upstream-audit.md)
- [`a-stock-data` audit](a-stock-data-upstream-audit.md)
- [`global-stock-data` audit](global-stock-data-upstream-audit.md)
- [Vibe-Trading audit](vibe-trading-upstream-audit.md)
