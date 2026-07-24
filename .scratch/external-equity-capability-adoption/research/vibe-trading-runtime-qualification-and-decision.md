# Vibe-Trading runtime qualification and adoption decision

## Decision

At pinned upstream commit `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6`
(`vibe-trading-ai` 0.1.12), the Vibe-Trading MCP server, its generic
`backtest(run_dir)` contract, its claimed Walk-Forward analysis, its Bootstrap,
and its strategy Monte Carlo are **rejected** for the production
`StrategyValidation` path.

The production MCP allowlist is therefore:

```json
[]
```

This is not a transient fallback decision. No `VibeTradingMcpAdapter`, broad MCP
proxy, compatibility wrapper, placeholder trading interface, or second report
path may be introduced from this candidate. The upstream checkout and its
virtual environment remain qualification-only, outside the repository.

The source contains a few `adapt-code` candidates:

- per-symbol one-bar signal lag and next-bar-open execution;
- point-in-time masking concepts for dated fundamentals and events;
- the A-share T+1, no-short and 100-share-lot skeleton, only after dated
  exchange-rule tables and typed suspension/limit/unfilled outcomes are added;
- deterministic artifact hash inventorying, only inside a target-owned evidence
  bundle with an independent verifier and complete engine, dependency, data,
  rule, seed and result identity.

Those algorithms are candidates for a future local implementation decision.
They are not evidence that the external MCP is adopted, and they do not
authorize adding `StrategyValidation` before ticket 07 proves a real variation
point and two real adapters as required by the Goal.

## Pinned and isolated runtime

| Item | Evidence |
|---|---|
| Repository | `https://github.com/HKUDS/Vibe-Trading.git` |
| Checkout | `E:\workspace\tradingSystem-upstreams\Vibe-Trading` |
| Commit | `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` |
| Describe | `v0.1.12-78-g0aa45a9` |
| Runtime | CPython 3.11.15 in the checkout-local `.venv`; `uv` 0.11.17 |
| MCP executable | Absolute `.venv\Scripts\vibe-trading-mcp.exe`, stdio |
| Controlled home/artifacts | `.venv\qualification-runtime`, outside `tradingSystem` |
| Docker | Daemon unavailable; correctly treated as non-blocking |
| Credentials | No LLM, OAuth, API key, broker, account, or user credential requested |
| Upstream state | Pinned checkout remained clean |

The upstream hash lock is internally unsatisfiable: `aiofile==3.11.1` requires
`caio>=0.9.0,<0.10.dev0`, while the lock pins `caio==0.10.2`. A qualification
environment could be installed only through an unlocked resolver selection
(`caio==0.9.25`); its 197-package freeze SHA-256 is
`4ba4b3aa671e2bf451f48f1609d5cc358a830a545068bbe818617a5301e9e1e1`.
Consequently the published lock cannot reproduce the qualified dependency
identity and cannot support production pinning.

## MCP black-box evidence

The bounded 120-second initialization retry passed in 13.6 seconds after a
45-second cold-start budget timed out. The server identified itself as
`Vibe-Trading` 0.1.12 using protocol `2025-11-25` and FastMCP 3.4.4.
`tools/list` returned 54 tools; the canonical schema-set SHA-256 is
`bfe800f472882c6ce255132efc2c26cc62f93d6f49acb2fd7ce382dabb1af1a2`.

The catalogue includes file, web, mutable research state, market discovery,
broker/account/order, swarm and Shadow Account capabilities. Generic MCP tools
for `walk_forward`, `bootstrap`, `monte_carlo`, `run_card`, and
`render_backtest_report` are absent. The opt-in shell tools were disabled and
were not in `tools/list`.

Only qualification-safe calls were made:

| Probe | Result |
|---|---|
| `analyze_options`, repeated | Same normalized response hash; pure-CPU smoke only, outside the Goal capability |
| `backtest` for a missing run | MCP `is_error=false` while application JSON says `status=error` |
| `backtest` with invalid arguments | MCP error with non-JSON text |
| nonexistent `walk_forward` | MCP error with non-JSON text |
| forced server crash | Classified `server_crash`, exit code 23 |
| forced client timeout | Classified `client_timeout` |
| malformed server result | Classified `malformed_json_rpc`, 18 bytes |

No forbidden tool or network-provider call was executed. These probes establish
that the upstream transport does not itself provide the stable typed failure
contract required at the application seam: a successful MCP envelope can carry
an application failure.

## Known-answer local backtest

A frozen local price fixture, executable strategy fixture and config were staged
only under the controlled qualification home. Two repeated calls first failed
because the generated subprocess changed `HOME` and rejected the controlled run
directory. After allowing exactly that run root, two further repeated calls
still failed: on the required isolated Windows path the child could not
re-expose the local data bridge, treated the local loader as unavailable, fell
through to Tushare, and demanded a token.

Both pairs were deterministically repeatable, but all four were application
failures transported in MCP success envelopes. The required no-credential,
local, known-answer backtest was therefore unavailable. No credential was
requested from the user and no provider call was made to disguise this failure.

During fixture setup, a PowerShell case-insensitive `$home` collision caused
three exact fixture files to be copied briefly under the real user
`C:\Users\72449\.vibe-trading` tree. The error was detected immediately; only
the three hash-matching files and then-empty directories were removed, and all
three paths were verified absent. No other user file was changed.

## Correctness and adversarial findings

The focused upstream unit suite passed `141` tests with `0` failures and `4`
warnings in `19.11s`. This confirms the implemented unit claims, but it does not
override the black-box failure or the semantic gaps below.

The repository-owned adversarial probe passed 12 assertions:

- identical seeds reproduce and different seeds vary for the implemented
  stochastic functions;
- the alleged Monte Carlo only permutes the order of realized trade P&L;
- Bootstrap independently resamples single-bar returns and does not preserve
  temporal dependence;
- neither output records seed, random algorithm, or convergence;
- “Walk-Forward” only splits one already-produced equity curve into post-hoc
  windows and has no train/test/refit/embargo or IS/OOS lineage;
- per-symbol one-bar signal lag, next-open sizing, T+1 and 100-share lot rules
  exist;
- ST 5% limit identity cannot be determined by the engine.

The run-card tamper probe passed five assertions. Recorded artifact hashes match
before tampering and an independent rehash detects mutation, but upstream
provides no verifier, the run card does not hash itself, and schema 0.1 omits
the identities needed for acceptance.

The generic backtest has no HTML/PDF report capability. The only such renderer
belongs to Shadow Account, writes through a separate persistence domain, and is
rejected.

## Required threat coverage

| Required concern | Finding | Decision |
|---|---|---|
| Same-close look-ahead | Per-symbol one-bar shift and next-open concept verified | `adapt-code` invariant only |
| Train/test leakage | No actual train/test/refit walk-forward contract | `reject` |
| Fold identity | Post-hoc windows lack frozen fold/parameter identity | `reject` |
| Universe PIT / survivorship | Caller-selected universe; no historical membership/delisting contract | `reject` |
| Adjustments / corporate actions | Loader-dependent mutable policies; no frozen policy identity | `reject` |
| A-share T+1 / lots | Skeleton verified | conditional `adapt-code` |
| Suspension / limits | Heuristic/missing-bar handling; ST and dated regimes incomplete | `reject` as supplied |
| Fees / slippage | Configurable skeleton exists without dated rule identity | conditional `adapt-code` |
| Unfilled / invalid events | No complete typed outcome taxonomy | `reject` as supplied |
| Seed replay / different seeds | Function-level behavior verified | insufficient without result identity |
| Monte Carlo convergence | No convergence evidence; wrong claimed method | `reject` |
| Bootstrap convergence | IID single-bar method; no dependence or convergence evidence | `reject` |
| Artifact tampering | Independently detectable but not upstream-verified or self-bound | hash idea `adapt-code` only |
| Timeout / crash / malformed | Client can classify in probes; upstream application contract is untyped/inconsistent | MCP contract `reject` |

## Deletion and adoption matrix

| Capability | Current canonical implementation | External candidate | Decision | Adoption condition | Delete or exclude | Rejection reason |
|---|---|---|---|---|---|---|
| Production strategy validation | No production module yet | Entire Vibe MCP | `reject` | None | No MCP adapter/proxy/config/registry | Broad attack surface and no credible typed core |
| Generic backtest | No canonical production seam | `backtest(run_dir)` | `reject` | None | Path/code-execution contract and loader fallback | No frozen snapshot, typed request/result, or no-credential known answer |
| Walk-Forward | No canonical production seam | Post-hoc window split | `reject` | None | Name and implementation | Not train/test/refit validation |
| Strategy Monte Carlo | No canonical production seam | Trade-P&L order permutation | `reject` | None | Monte Carlo label | Does not generate alternative strategy/market paths |
| Bootstrap | No canonical production seam | IID one-bar resampling | `reject` | None | Supplied algorithm | Ignores dependence and convergence |
| Signal timing | No strategy-validation implementation yet | Per-symbol lag / next open | `adapt-code` | Target-owned typed frozen-snapshot tests | Upstream runner/path contract | Useful invariant, not a drop-in module |
| PIT masking | Existing platform PIT/snapshot rules | Optional upstream masks | `adapt-code` | Preserve platform timestamps and immutable identity | Upstream provider loaders | Concept aligns; surrounding lineage does not |
| A-share execution rules | No full strategy-validation engine | ChinaAEngine skeleton | `adapt-code` | Dated rules plus typed fill/rejection evidence | Heuristic engine as supplied | ST/IPO/suspension/liquidity/history incomplete |
| Evidence bundle | Existing platform identity/ledger contracts | Run-card hash inventory | `adapt-code` | Independent production verifier and full identity binding | Upstream card as proof | Descriptive hashes are not acceptance evidence |
| Generic report | Canonical `ResearchDecisionView` presentation | Absent; Shadow report only | `reject` | None | Shadow Web/persistence/report path | Wrong domain and parallel presentation |
| Live/order/broker/file/web/search/memory/swarm | Explicitly out of scope | Broad MCP catalogue | `reject` | None | All interfaces, fixtures and placeholders | Permanent Goal exclusion |

## Verification ledger

All commands used the pinned checkout-local Python executable. No required
check was skipped or treated as a pass after timeout.

| Exact command | Duration | Result | Artifacts / classification |
|---|---:|---|---|
| `uv pip install --python .venv\Scripts\python.exe --require-hashes -r requirements-lock.txt` | resolver terminated before install | `failed` | Exact `aiofile` / `caio` conflict recorded; failure is part of the rejection evidence |
| `.venv\Scripts\python.exe .scratch\external-equity-capability-adoption\research\vibe-trading-mcp-probe.py` | cold budget `45s`; bounded retry `13.6s` within `120s` | retry `passed`, cold attempt `timeout` | Server/protocol/version, 54 schemas and schema-set hash |
| `.venv\Scripts\python.exe .scratch\external-equity-capability-adoption\research\vibe-trading-mcp-call-probe.py` | bounded per script | expected classifications passed | Repeated pure-CPU result, application-error-in-success-envelope, invalid args, absent tool |
| `.venv\Scripts\python.exe .scratch\external-equity-capability-adoption\research\vibe-trading-known-answer-probe.py` | four bounded calls | `0` successful backtests, `4` application failures | Two stable hashes for the two exact failure stages; no network/provider call |
| `.venv\Scripts\python.exe -m pytest agent/tests/test_validation.py agent/tests/test_china_a_engine.py agent/tests/test_run_card.py agent/tests/test_backtest_runner_security.py agent/tests/test_local_source_routing.py agent/tests/test_mcp_server_smoke.py -q --disable-warnings` | `19.11s` | `141 passed`, `0 failed`, `4 warnings` | Focused upstream claims only |
| `.venv\Scripts\python.exe .scratch\external-equity-capability-adoption\research\vibe-trading-algorithm-adversarial.py` | `<2.6s` in the local combined verification cell | `12 passed`, `0 failed` | Algorithm identity, seeds, lag, A-share skeleton and ST gap |
| `.venv\Scripts\python.exe .scratch\external-equity-capability-adoption\research\vibe-mcp-failure-probe.py` | `<7.9s` together with the following tamper probe | `3 passed`, `0 failed` | `server_crash`, `client_timeout`, `malformed_json_rpc` |
| `.venv\Scripts\python.exe .scratch\external-equity-capability-adoption\research\vibe-trading-run-card-tamper-probe.py` | `<7.9s` together with the preceding failure probe | `5 passed`, `0 failed` | External rehash detects mutation; no upstream verifier or self-hash |

`external_blocked`: none for the required Vibe core qualification. Docker,
Web/PDF, LLM, OAuth, API keys, broker access and personal account data were not
needed and were not treated as blockers.
## Reproducible evidence

Machine-readable observations and hashes are in
[`vibe-trading-runtime-evidence.json`](vibe-trading-runtime-evidence.json).
The static source audit is in
[`vibe-trading-mcp-source-and-correctness-audit.md`](vibe-trading-mcp-source-and-correctness-audit.md).
The qualification scripts and frozen fixtures are retained beside those files
under this effort's `research/` directory.

No production code, project dependency, schema, Web asset, persistence path, or
canonical application interface was changed while resolving this Wayfinder
ticket.
