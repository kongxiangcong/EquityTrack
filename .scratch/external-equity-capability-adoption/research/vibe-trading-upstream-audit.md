# Vibe-Trading upstream identity, licence, rights, and attack-surface audit

Captured at: `2026-07-24T09:57:43.216Z`

## Scope

This is ticket-01 evidence only. It pins repository identity, licence,
dependencies, external capabilities and attack surface. It does not install the
package, run a strategy, qualify numerical correctness, or pre-empt the later
ticket “验证 Vibe-Trading 的回测、Walk-Forward 与模拟可信度”.

The repository was cloned non-destructively to the prevalidated external path
`E:\workspace\tradingSystem-upstreams\Vibe-Trading`. It is outside the product
repository and remains clean.

## Pinned identity

| Field | Evidence |
|---|---|
| Canonical repository | <https://github.com/HKUDS/Vibe-Trading> |
| Configured origin | `https://github.com/HKUDS/Vibe-Trading.git` |
| Branch | `main` |
| Pinned HEAD | `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` |
| Nearest release | `v0.1.12`; checkout describes as `v0.1.12-78-g0aa45a9` |
| Package | `vibe-trading-ai`, declared version `0.1.12` |
| Python | `>=3.11` |
| Licence | MIT |
| NOTICE | Present; attributes HKUDS and bundled/reimplemented factor material, including Microsoft Qlib definitions under Apache-2.0 |
| History at capture | 1,013 commits, 331 `test_*.py` files under `agent/tests`, three GitHub workflow files |

Pinned file hashes:

| File | SHA-256 |
|---|---|
| `LICENSE` | `399b7c624a8feb0388293c17782e04a87da7741c5362cfa36f80452b58385802` |
| `NOTICE` | `ff585653f9f7b3b3792175e837ca8897ef3f9a0bed3d94ce8f09366aebac56ae` |
| `pyproject.toml` | `af07cebb666de3bf53f604741047f261693c303fc531333ebfff7f2b2c2631a0` |
| `README.md` | `27e77f16299956263421f757d7aec9b9308d8974c83864af9ac571e7c7176711` |
| `requirements-lock.txt` | `b5a1bb3e28bc78d519537a72b00014f5aaca9df55986a6de541e639e6b45d841` |

The pinned HEAD is newer than the latest tag, so qualification must pin the full
commit, not install an unqualified moving `main` or assume the `0.1.12` package
contains the same code.

## Runtime and dependency surface

The base package is a full application, not a narrow backtest library. Its
declared dependencies include LangChain/LangGraph and LLM providers, FastAPI,
FastMCP, WebSockets/SSE, scientific/data stacks, document/PDF/HTML rendering,
Tushare, yfinance, AkShare, CCXT, DuckDB and web search. Optional extras add
broker SDKs, MetaTrader 5, communications channels and more LLM providers.

It ships CLI and MCP entrypoints:

```text
vibe-trading = cli:main
vibe-trading-mcp = mcp_server:main
```

The repository has a hash-oriented `requirements-lock.txt`, tests and CI, which
is materially stronger than the two Skill repositories. No dependency was
installed for this ticket; compatibility and lock reproducibility remain for
ticket 06.

## External data and rights boundary

The README lists 23 market-data loader families, including Tushare, yfinance,
AkShare, BaoStock, Tencent, mootdx, CCXT/exchanges, Futu, Eastmoney, Sina,
Stooq, Finnhub, Alpha Vantage, Tiingo, FMP, Longbridge, MetaTrader 5, QVeris and
Indian broker paths. It also exposes SEC filings, research reports, news,
options, macro and market-screening tools.

MIT covers repository code, subject to included notices. It does not grant
rights to broker data, exchange data, commercial feeds, web results, research
reports, news, filings or any loader response. The repository NOTICE covers
bundled code/formula attribution, not endpoint storage, cache, redistribution,
commercial-use or entitlement terms.

Every future data input therefore remains unqualified for tradingSystem until
its own authority, terms, PIT timing, cache/redistribution, rate-limit,
provenance and identity contract passes the repository source policy. Vibe's
loader fallback chain cannot become a silent alternative DataProvider route.

## MCP and local attack surface

The README declares 54 MCP tools. The default surface includes:

- `backtest` and factor/options/pattern analysis;
- `read_url`, `read_document`, `web_search`, `read_file`, `write_file`;
- market-data, news, reports, SEC, financial statement, options and screening
  tools;
- broker connection/account/positions/orders/quote/history tools;
- `run_swarm` and external MCP discovery;
- run listing/retry/reaping and Shadow Account extraction/backtest/report/signal
  tools.

The system also contains:

- HTTP/SSE/stdio MCP transports and a FastAPI/Web frontend;
- generated backtest code executed as a local Python subprocess;
- persistent files/configuration, uploads, runs, scheduler jobs, memories and
  strategy artifacts under repository paths or `~/.vibe-trading`;
- broad outbound network through data, search, LLM, messaging, broker and
  external MCP adapters;
- optional shell/background tools in the interactive CLI or when explicitly
  enabled;
- broker/live-trading and order/cancel paths;
- swarm workers and caller-configurable external MCP servers.

Upstream documents several guards: shell tools are opt-in outside the local CLI;
document/file roots are constrained by configured allowlists; generated
backtests receive a narrowed environment; broker secrets/live toggles are not
normally passed to generated code; and later security work added AST/network/
subprocess/eval/environment/open restrictions. These are useful evidence, not
permission to expose the full server.

For this Goal the production adapter must deny, not merely avoid invoking:

- live trading, order, cancel and broker-secret surfaces;
- `read_file`, `write_file`, arbitrary document/URL and web-search tools;
- shell/background execution;
- memory, scheduler, Web/API frontend and persistent application state;
- swarm and external MCP loading/discovery;
- access to the repository, user home, personal account data or arbitrary paths.

The only candidate surface is a separately launched, pinned, isolated MCP
process with a strict explicit allowlist for qualified strategy-validation
operations and a controlled artifact directory. Raw upstream JSON, HTML or PDF
is not authoritative.

## Maintenance and correctness posture

The repository has substantial tests, CI, releases and contributor history.
Its own recent changelog also records continuing correctness/security fixes:
timeframe interpretation, partial-universe fallback, look-ahead/OOS guards,
turnover/costs, broker/live safety, dependency-lock repair and finite JSON.
This active repair history is evidence that the project is maintained, but also
that the pinned version must face independent known-answer, PIT, execution-rule,
reproducibility, tampering and failure tests rather than relying on README
claims.

The upstream itself labels live broker capability experimental and not verified
against a real broker account. This Goal excludes it completely.

## Ticket-01 conclusion

1. Identity is pinned to `0aa45a9...`; it is 78 commits past `v0.1.12`.
2. Code licence is MIT with a non-empty NOTICE and additional attribution
   obligations; third-party data rights remain unproven.
3. Runtime maturity is materially stronger than the Skill candidates, but the
   full application attack surface is far broader than tradingSystem may accept.
4. Whole-application adoption, in-process import, Web embedding, memory sharing,
   live trading and unrestricted MCP are excluded.
5. Ticket 06 may evaluate only a pinned isolated process and a minimal
   strategy-validation allowlist. It must prove typed identity/lineage,
   known-answer correctness, PIT, A-share rules, seed reproducibility,
   convergence and hostile-result handling before an adoption decision.

## Reproduction commands

```powershell
git -C E:\workspace\tradingSystem-upstreams\Vibe-Trading remote -v
git -C E:\workspace\tradingSystem-upstreams\Vibe-Trading rev-parse HEAD
git -C E:\workspace\tradingSystem-upstreams\Vibe-Trading status --short
git -C E:\workspace\tradingSystem-upstreams\Vibe-Trading describe --tags --always
git -C E:\workspace\tradingSystem-upstreams\Vibe-Trading rev-list --count HEAD
Get-FileHash -Algorithm SHA256 LICENSE,NOTICE,pyproject.toml,README.md,requirements-lock.txt
rg -n "read_file|write_file|web_search|trading_|run_swarm|subprocess|memory" agent README.md
```
