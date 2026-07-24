# Vibe-Trading MCP source and correctness audit

## Audit envelope

- Upstream: `https://github.com/HKUDS/Vibe-Trading.git`
- Pinned checkout: `E:\workspace\tradingSystem-upstreams\Vibe-Trading`
- Audited commit: `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6`
- Method: source-only inspection of the pinned checkout. No network access, dependency installation, provider call, MCP execution, or production-code change was performed in this audit.
- Scope: the MCP entry point and schemas; backtest, validation, run-card, and report implementations; correctness and reproducibility controls; failure semantics; and surfaces that must not cross the target adoption boundary.
- Runtime observations belong to the separate black-box qualification task. This document does not promote source claims to runtime evidence.

## Executive decision

**Do not adopt the Vibe-Trading MCP server or its generic `backtest` tool as the production `StrategyValidation` seam.**

At this commit the server exposes 54 decorated tools through one FastMCP instance, including file writes, arbitrary path reads, web access, mutable local state, broker/account data, swarm/LLM execution, and Shadow Account persistence. The one generic backtest tool accepts only `run_dir: str`, reads executable Python and configuration from disk, can fetch mutable network data through fallback chains, and writes artifacts. It does not accept a typed frozen market snapshot or return identity-bearing typed evidence.

The source does contain **adapt-code candidates**, not drop-in capabilities:

1. per-symbol one-bar signal shifting and next-bar-open execution;
2. deterministic SHA-256 inventorying of config, strategy, and artifacts;
3. deterministic RNG usage and finite-JSON validation output;
4. an A-share T+1 / no-short / lot / fees / slippage skeleton;
5. point-in-time filtering for optional Tushare fundamentals and RSS events.

Each needs to be re-expressed behind the repository's own typed contracts and strengthened. No reviewed item qualifies as `adopt-external`, and the server as a whole is `reject`.

## Package and entry-point facts

| Fact | Primary source | Implication |
|---|---|---|
| Package is `vibe-trading-ai` version `0.1.12`, Python `>=3.11`. | `pyproject.toml:2-5` | Pinning must bind both commit and package/dependency identity. |
| MCP console entry point is `vibe-trading-mcp = "mcp_server:main"`. | `pyproject.toml:71` | The audited production entry is `agent/mcp_server.py:main`. |
| Direct dependencies include LangChain/OpenAI, FastMCP, pandas/numpy/scipy, data-source clients, Jinja/matplotlib/WeasyPrint, and server packages. | `pyproject.toml:8-61` | The package is a broad agent/trading application, not a narrow validation service. |
| The hash lock pins, among others, FastMCP 3.4.4, langchain-openai 1.3.5, numpy 2.4.6, OpenAI 2.46.0, pandas 2.3.3, scipy 1.17.1, and WeasyPrint 69.0. | `requirements-lock.txt:903`, `requirements-lock.txt:1516`, `requirements-lock.txt:2112`, `requirements-lock.txt:2200`, `requirements-lock.txt:2355`, `requirements-lock.txt:3398`, `requirements-lock.txt:4014` | Any qualification result is dependency-set-specific. The current run card does not record this lock identity. |

## Real MCP handshake and catalogue

### Initialize and transport

The application creates one `FastMCP("Vibe-Trading", version=APP_VERSION)` instance (`agent/mcp_server.py:62-72`). There is no repository-owned `initialize` handler: FastMCP supplies JSON-RPC/MCP initialization, `tools/list`, schema derivation, and tool dispatch from the decorated Python callables.

The CLI supports `stdio` (default), legacy `sse`, and Streamable HTTP; HTTP is mounted as `/mcp`, and network transports receive Host/Origin middleware (`agent/mcp_server.py:2105-2156`). The registry is deliberately pre-warmed before serving because lazy initialization previously deadlocked the first tool call (`agent/mcp_server.py:2133-2136`).

First-party tests establish only these handshake contracts:

- stdio sends `initialize` with protocol version `2024-11-05`, sends `notifications/initialized`, calls `tools/list`, then calls pure-CPU `analyze_options`; the test's client-side budgets are 30 seconds for initialize/list and 15 seconds for that call (`agent/tests/test_mcp_server_smoke.py:36-44`, `agent/tests/test_mcp_server_smoke.py:160-215`);
- Streamable HTTP initializes with protocol version `2025-03-26`, expects a session header, and asserts legacy `/sse` is absent for HTTP transport (`agent/tests/test_mcp_server_http_transport.py:90-126`);
- catalogue regressions enforce only a floor of 30 tools, not an exact allowlist (`agent/tests/test_mcp_regression.py:118-137`).

Therefore the exact schema is FastMCP-version-derived. The pinned source has **54** `@mcp.tool` registrations. A consumer must capture and hash the actual `tools/list` response during qualification rather than treat this static list as sufficient evidence.

### Decorated tool inventory

The source catalogue is:

- local skill/goal state: `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status` (`agent/mcp_server.py:407-643`);
- analysis: `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition` (`agent/mcp_server.py:651-767`);
- web/document/file: `read_url`, `read_document`, `web_search`, `write_file`, `read_file` (`agent/mcp_server.py:775-856`);
- broker/account: `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history` (`agent/mcp_server.py:887-1090`);
- swarm start: `list_swarm_presets`, `run_swarm` (`agent/mcp_server.py:1098-1119`);
- data/discovery: `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search` (`agent/mcp_server.py:1251-1718`);
- swarm lifecycle: `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run` (`agent/mcp_server.py:1781-1939`);
- journal/Shadow Account: `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals` (`agent/mcp_server.py:1947-2097`).

`bash` and `background_run` are not decorated MCP functions. They are conditionally included in the internal registry. The module-level default is fail-closed, but `--enable-shell-tools` or `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` enables them (`agent/mcp_server.py:81-90`, `agent/mcp_server.py:2126-2135`; tests at `agent/tests/test_mcp_regression.py:185-236`). This is not an acceptable production control: the target must never expose or enable the broad server in the first place.

### Relevant input schemas

FastMCP derives JSON Schema from these Python signatures; return annotations are uniformly `str`, so structured JSON is transported as text rather than a typed MCP output schema.

| Tool | Source-level input schema | Static return contract | Decision |
|---|---|---|---|
| `backtest` | required string `run_dir` | JSON string produced by `run_backtest` | `reject` as production seam |
| `factor_analysis` | required strings `factor_csv`, `return_csv`, `output_dir`; integer `n_groups=5` | registry-produced string | `reject`: path read/write contract |
| `analyze_options` | required numbers `spot`, `strike`, integer `expiry_days`; optional `risk_free_rate=0.03`, `volatility=0.25`, `option_type="call"` | registry-produced JSON string | `reject` for this goal; useful network/key-free MCP smoke probe |
| `pattern_recognition` | required string `run_dir` | registry-produced string | `reject`: artifact-path contract |
| `render_shadow_report` | Shadow Account identifiers/options, not generic backtest evidence | path-bearing report result | `reject`: wrong domain plus home-directory persistence |

Signatures and descriptions are at `agent/mcp_server.py:651-767` and `agent/mcp_server.py:2047-2076`. There are **no decorated generic MCP tools named** `walk_forward`, `bootstrap`, `monte_carlo`, `run_card`, or generic `render_backtest_report`. Those capabilities are optional internals of `backtest`; the HTML/PDF renderer is Shadow Account-specific.

## What can run without an LLM or API key

“No LLM/API key” does not mean “offline,” “read-only,” or “acceptable.”

| Capability | LLM needed | Key needed | Other I/O | Finding |
|---|---:|---:|---|---|
| `analyze_options` | no | no | pure CPU | Suitable only as a handshake smoke probe; out of goal scope. The upstream stdio smoke test uses it (`agent/tests/test_mcp_server_smoke.py:197-220`). |
| `factor_analysis` | no | no | reads two caller paths and writes an output directory | Not admissible through target MCP boundary. |
| `pattern_recognition` | no | no | reads run artifacts | Not admissible through target MCP boundary. |
| `backtest` with a prepared run directory and `local` source | no | no | reads executable/config/data files and writes artifacts/subprocess logs | Still inadmissible as-is because its contract is path- and code-execution-based. |
| `backtest` with `yfinance`, `okx`, `akshare`, `ccxt`, or many `auto` routes | no | often no | network data fetch | Source doc labels these free/no-key, but they are mutable network inputs (`agent/mcp_server.py:652-666`). |
| `web_search` | no | no | network | Explicitly free/no-key and explicitly forbidden (`agent/mcp_server.py:809-825`). |
| `run_swarm` | yes | provider-dependent | persistent run state plus workers | Forbidden. |

The loader registry accepts 24 named sources plus `auto` (`agent/backtest/loaders/registry.py:27-58`). Its fallback chains traverse public, key-gated, local-terminal, and local-file providers (`agent/backtest/loaders/registry.py:125-147`). This means “no key” is not a stable data-lineage or availability guarantee.

## Generic backtest implementation

### Boundary and failure envelope

`backtest(run_dir)` forwards directly to `run_backtest` (`agent/mcp_server.py:651-674`). `run_backtest`:

1. validates the path with `safe_run_dir`;
2. parses `config.json`;
3. requires a supported `source`;
4. requires `code/signal_engine.py`;
5. launches `backtest/runner.py` in a subprocess with a 300-second wall timeout;
6. returns a text-encoded object containing `status`, numeric `exit_code`, the last 2,000 characters of stdout/stderr, discovered artifact paths, and the caller's run directory (`agent/src/tools/backtest_tool.py:15-74`).

This result has no stable typed failure code, engine/commit/lock identity, input-snapshot identity, or evidence hash. Expected preflight failures return `{"status":"error","error":"..."}`, while subprocess timeout is not caught by `run_backtest`: `subprocess.TimeoutExpired` escapes `Runner.execute` because its `try/finally` only cleans the temporary home (`agent/src/core/runner.py:527-546`). FastMCP may convert the exception into an MCP error response, but the repository defines and tests no application-level timeout code or payload for it.

The path policy is broader than the target contract. `safe_run_dir` accepts several application, current-working-directory, and home-directory run roots, including Shadow Account storage (`agent/src/tools/path_utils.py:313-352`). The tool is correctly marked non-read-only in the internal registry (`agent/src/tools/backtest_tool.py:77-94`).

### Config and executable-code contract

The runner's Pydantic schema requires non-empty `codes`, `start_date`, and `end_date`; defaults `source="tushare"`, `interval="1D"`, `engine="daily"`, and positive finite `initial_cash`; validates interval, engine, source, optional fundamentals, and event feeds; and rejects inverted dates (`agent/backtest/runner.py:68-161`). Crucially, `extra="allow"` permits undeclared config keys (`agent/backtest/runner.py:71`).

The strategy is caller-supplied Python. The AST scanner rejects common network/process/dynamic-exec/file-write operations, but the source explicitly says runtime methods otherwise run with no runtime sandbox and documents residual bypass through `builtins.getattr`/aliasing; it is defense in depth, not a kernel boundary (`agent/backtest/runner.py:262-282`). The subprocess tries to use an ephemeral home, UID drop, resource limits, and a wall timeout, but falls back to inherited HOME when sandbox-home creation fails and persists library cache access through the real home (`agent/src/core/runner.py:497-540`).

**Decision: `reject`**. The target validation operation must accept typed strategy/snapshot inputs and never make arbitrary Python/file paths part of its public contract.

### Execution timing and look-ahead

The core aligner shifts each symbol's signal on that symbol's own calendar by one bar, then forward-fills target positions on a unified calendar (`agent/backtest/engines/base.py:133-227`). This is a sound anti-look-ahead concept and has a regression test asserting position at `t` equals signal at `t-1` (`agent/tests/test_signal_alignment_perf.py:326-344`).

Execution sizing uses the current bar's open, explicitly to avoid sizing from the current close (`agent/backtest/engines/base.py:650-667`). Optional fundamentals and events are attached before signal generation; the Tushare provider filters on disclosure/PIT dates and the event provider has per-bar look-ahead tests (`agent/backtest/loaders/tushare_fundamentals.py:136-226`, `agent/backtest/loaders/tushare_fundamentals.py:264-339`; `agent/tests/test_rsshub_events_lookahead.py:1-94`).

Limits:

- only optional fundamentals/events have explicit PIT semantics; OHLCV, membership/universe, and provider response identity are not frozen by the tool contract;
- requested symbols are caller-selected and no historical constituent membership or delisting/survivorship contract is enforced;
- unified-calendar close and positions are forward-filled for five bars in one market or ten bars cross-market (`agent/backtest/engines/base.py:153-177`, `agent/backtest/engines/base.py:211-216`);
- symbols with no usable overlap are dropped with a log warning rather than represented in typed coverage evidence (`agent/backtest/engines/base.py:179-188`);
- provider adjustment policies differ: BaoStock and AKShare request forward adjustment, Yahoo Finance disables auto-adjustment, and Longbridge requests no adjustment (`agent/backtest/loaders/baostock_loader.py:131`, `agent/backtest/loaders/akshare_loader.py:146-178`, `agent/backtest/loaders/yfinance_loader.py:104-115`, `agent/backtest/loaders/longbridge.py:345-371`).

**Decision: `adapt-code`** for per-symbol signal shift/open execution and the PIT masking tests; **reject** the surrounding mutable loader/universe contract.

## A-share execution realism

`ChinaAEngine` implements no shorting, same-day-sale blocking, 100-share buy-lot rounding, bilateral commission with a ¥5 minimum, sell-side stamp tax, bilateral transfer fee, and direction-adjusted fixed-rate slippage (`agent/backtest/engines/china_a.py:1-97`).

The implementation is only a skeleton:

- limit-up/down is inferred from daily `pct_chg` or close versus previous close even though execution occurs at open (`agent/backtest/engines/china_a.py:64-71`, `agent/backtest/engines/china_a.py:123-134`);
- the docstring mentions ST 5%, but `_price_limit` cannot detect ST and returns 10% for those ordinary codes; it handles only 300/688 as 20%, `8xxxxx` as 30%, and otherwise 10% (`agent/backtest/engines/china_a.py:137-155`);
- there is no explicit IPO/no-limit-day regime, historical board-rule versioning, tick-size queue/liquidity model, partial fill, or typed unfilled-order reason;
- suspension is approximated by missing bars/limited forward fill rather than a first-class execution status;
- fee and tax defaults are config values with no effective-date identity in evidence.

The unit suite covers basic no-short, T+1, lots, limits, fees, and slippage but does not establish ST/IPO regime history, suspended/unfilled semantics, corporate actions, or liquidity (`agent/tests/test_china_a_engine.py:1-258`).

**Decision: `adapt-code` only after replacing heuristics with dated rules and typed fill/rejection evidence.**

## Walk-Forward, Bootstrap, and Monte Carlo

These are not independent MCP tools. They run only when `config["validation"]` is populated; the engine writes `artifacts/validation.json` and embeds the result in the run card (`agent/backtest/engines/base.py:597-623`).

### “Monte Carlo”

`monte_carlo_test` permutes the order of the exact realized trade-PnL vector, then compares the observed path's Sharpe/drawdown to those reorderings (`agent/backtest/validation.py:29-89`). It does not resample markets, signals, fills, parameters, or return blocks and cannot establish strategy robustness against alternative market paths. `_path_metrics` annualizes per-trade path returns by `sqrt(252)` regardless of actual trade spacing (`agent/backtest/validation.py:92-101`).

It uses `np.random.default_rng(seed)` and validates a non-negative seed, but the returned payload omits seed, bit-generator/algorithm identity, and convergence diagnostics (`agent/backtest/validation.py:29-89`).

**Decision: `reject` for target Monte Carlo evidence.** At most retain as an explicitly named “trade-order permutation diagnostic,” never as the production Monte Carlo capability.

### Bootstrap

`bootstrap_sharpe_ci` performs IID resampling with replacement of individual equity-curve percentage returns (`agent/backtest/validation.py:107-165`). It does not use blocks, preserve serial dependence, model overlapping positions, or surface sensitivity to block length. It uses a deterministic seed but omits the seed/algorithm from output and has no convergence/stability check across simulation budgets.

**Decision: `reject` for target robustness evidence.** Replace with an explicitly specified bootstrap appropriate to dependence structure, with seed, algorithm, sample budget, convergence/stability, and data identity in typed evidence.

### “Walk-Forward”

`walk_forward_analysis` divides one already-produced equity curve into equal non-overlapping windows and computes post-hoc statistics; trades are assigned by entry timestamp (`agent/backtest/validation.py:176-253`). It has no training window, test window, re-fit/re-optimization step, embargo, parameter identity, fold-level input snapshot, or IS/OOS distinction. The tests describe and assert window splitting, not walk-forward model selection (`agent/tests/test_validation.py:6-7`, `agent/tests/test_validation.py:180-266`).

**Decision: `reject` and do not label it Walk-Forward in the target system.**

### Statistical test quality

The validation tests cover basic shape/ranges, invalid arguments, and same-seed repeatability. They do not include complete byte-for-byte artifact reproducibility, different-seed distribution checks, known-answer statistical properties, false-positive/power bounds, dependence-aware bootstrap tests, or convergence across increasing budgets (`agent/tests/test_validation.py:1-266`).

## Run card and reports

### Generic run card

`write_run_card` writes JSON and Markdown schema version `0.1`; it records generation time, run directory, a selected config summary, config/strategy SHA-256, source names, scalar metrics, warnings, and hashes/sizes for config, strategy, and files already under `artifacts/` (`agent/backtest/run_card.py:25-95`, `agent/backtest/run_card.py:102-167`).

Useful properties:

- JSON serialization is sorted, indented, finite-only, and ends with a newline;
- config and strategy hashes are deterministic;
- artifact paths, sizes, and SHA-256 values are inventoried;
- tests verify deterministic config hash, strategy hash, artifact inventory, and JSON/Markdown output (`agent/tests/test_run_card.py:15-125`).

Missing production evidence:

- engine commit/version, dependency-lock hash, operating environment, algorithm identities, random seeds, and effective execution-rule version;
- immutable market-data snapshot, symbol coverage, provider retrieval timestamps, adjustment mode, calendar/universe identity, and input data hashes;
- fold identities and IS/OOS parameter lineage;
- convergence evidence;
- a signed/externally anchored manifest or production verifier.

`_list_artifacts` runs before `run_card.json` and `run_card.md` are written, so the card does not inventory itself (`agent/backtest/run_card.py:62-94`, `agent/backtest/run_card.py:147-167`). No run-card verification function or tamper test exists in the reviewed module/tests. Anyone able to write the run directory can replace both artifacts and card; hashes are descriptive, not trust proof.

**Decision: `adapt-code` for canonical hashing/inventory ideas; `reject` the card as acceptance evidence without an independent verifier and full identities.**

### HTML/PDF

The generic backtest produces CSV/JSON plus Markdown run cards; no generic MCP HTML/PDF backtest-report tool is registered. `render_shadow_report` belongs to Shadow Account and writes under `~/.vibe-trading/shadow_reports` (`agent/mcp_server.py:2047-2076`, `agent/src/api/uploads_routes.py:95-110`).

**Decision: `reject` as the requested generic report capability; it is absent at this boundary.**

## Failure, timeout, crash, and malformed-result semantics

| Case | Defined behavior at source | Gap |
|---|---|---|
| Missing/invalid run path, missing files, malformed `config.json`, unsupported source | text JSON with `status="error"` and free-form `error` (`agent/src/tools/backtest_tool.py:24-47`) | no stable error code or typed details |
| Backtest subprocess exits non-zero | text JSON with `status="error"`, exit code, truncated stdout/stderr, artifact paths (`agent/src/tools/backtest_tool.py:57-74`) | truncation may discard causality; no substep/error taxonomy |
| Backtest exceeds 300 seconds | `subprocess.TimeoutExpired` escapes `Runner.execute` (`agent/src/core/runner.py:527-546`) | no application-owned timeout result; depends on FastMCP exception conversion |
| MCP server crashes/exits | stdio smoke helper observes EOF/process status only (`agent/tests/test_mcp_server_smoke.py:81-105`) | no server recovery/resume or typed crash evidence |
| Tool returns malformed/non-JSON string | tools are declared as returning `str`; no server-side generic JSON-result validator | a successful MCP content envelope can carry unusable application text |
| Client call timeout | only test/client budgets are explicit for this server; separate remote-client adapter tests do not define the server's tool semantics | caller policy, not server contract |

No reviewed first-party MCP-server test deliberately sends malformed JSON-RPC, invalid tool arguments to `backtest`, forces the 300-second timeout, kills the child mid-run, or verifies malformed application output handling. The happy-path smoke test is valuable but insufficient for acceptance.

## Forbidden surface inventory

The target adapter must not forward the upstream server catalogue and must not expose any of these:

- **file/document**: `write_file`, `read_file`, `read_document`, plus path-based `factor_analysis`, `pattern_recognition`, and the current `backtest`;
- **web/external discovery**: `read_url`, `web_search`, every market/fundamental/news/filing/screen/search tool, and provider-fetching `backtest`;
- **broker/live/account/order**: all `trading_*` tools. `trading_orders` is source-documented as read-only and no decorated place/cancel order tool was found (`agent/mcp_server.py:985-1009`), but account/order/live-connection access is still outside scope;
- **memory/mutable local state**: research goals, connection selection, swarm run stores, journals, skills, and Shadow Account state;
- **swarm/LLM**: preset enumeration, start/status/result/list/reap/retry;
- **shell/process**: opt-in `bash` and `background_run`;
- **Shadow Account**: journal analysis, strategy extraction, shadow backtest, HTML/PDF report, and signal scan.

The current generic backtest cannot be cleanly allowlisted away from file/process/network behavior because those behaviors are intrinsic to its one-argument `run_dir` contract.

## Preliminary adoption matrix

| Upstream capability | Decision | Required target treatment |
|---|---|---|
| Entire Vibe-Trading MCP server | `reject` | Do not embed, proxy, or expose. Keep only in isolated qualification. |
| `backtest(run_dir)` MCP contract | `reject` | Define one target-owned typed validation operation over a frozen snapshot and declarative strategy identity. |
| Generated Python signal engine | `reject` | No executable caller-authored code in the production validation boundary. |
| Provider loader registry / `auto` fallback | `reject` | Data acquisition remains the platform's canonical provider path; validation consumes identity-bearing frozen data. |
| Per-symbol one-bar shift / open execution | `adapt-code` | Port the invariant with known-answer and anti-look-ahead tests. |
| Optional PIT fundamentals/events | `adapt-code` | Retain disclosure-time masking behind target provenance and snapshot contracts. |
| A-share engine skeleton | `adapt-code` | Add dated rule tables, adjustment/corporate-action policy, suspension/unfilled semantics, and coverage evidence. |
| Trade-order permutation “Monte Carlo” | `reject` | Do not present as market-path Monte Carlo. |
| IID return bootstrap | `reject` | Replace with declared dependence-aware method and convergence evidence. |
| Post-hoc window split “Walk-Forward” | `reject` | Implement genuine train/test/re-fit folds or disable the label. |
| Run-card config/strategy/artifact hashing | `adapt-code` | Extend into a target-owned verified evidence bundle bound to engine, dependencies, data, seeds, rules, and results. |
| Generic HTML/PDF report | `reject/absent` | Build presentation only from verified target evidence; do not reuse Shadow Account report. |
| Pure `analyze_options` | `reject` for goal | May remain a qualification-only no-network handshake probe. |

## Qualification assertions for the parent ticket

The parallel black-box qualifier should fail closed unless it can prove all of the following against the pinned environment:

1. `initialize` returns the expected server identity/version and the full `tools/list` plus input schemas can be canonicalized and hashed.
2. The actual catalogue matches the 54 decorated names above with shell tools absent.
3. Missing-file, malformed-config, unknown-source, subprocess failure, timeout, server crash, and non-JSON tool content are distinguished by the adapter rather than treated as a successful validation.
4. No network/provider fallback is exercised during qualification.
5. Same snapshot/strategy/config/seed produces byte-stable normalized evidence; any time/path fields are excluded only by an explicit canonicalization contract.
6. Different seeds and larger simulation budgets demonstrate expected variation and convergence where a stochastic method is claimed.
7. Look-ahead probes, A-share T+1/limits/suspension, adjustments/corporate actions, fees/slippage, universe coverage, and artifact tampering fail closed.

Given the source gaps documented here, a successful server handshake alone cannot change the production decision.
