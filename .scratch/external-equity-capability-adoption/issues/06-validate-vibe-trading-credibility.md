# 验证 Vibe-Trading 的回测、Walk-Forward 与模拟可信度

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

在指定仓库外隔离目录固定 `Vibe-Trading` commit，自动使用本机 `uv` 与 CPython 3.11 在该 checkout 内创建独立 `.venv` 并安装 pinned source；以绝对 executable path 启动 `vibe-trading-mcp` stdio，保存 `initialize`、`tools/list`、受限 `tools/call`、版本/schema/hash 以及 timeout/crash/malformed-result 证据。只允许无 LLM、OAuth、API Key、券商和个人账户的确定性能力；Docker/Web/PDF 缺失不是 blocker。以最小 MCP tool allowlist 和受控 artifact directory 验证 generic backtest、Walk-Forward、Bootstrap/策略收益 Monte Carlo、run card 与报告能力；覆盖已知答案、同收盘成交前视、train/test 泄漏、fold identity、universe PIT/survivorship、复权/公司行动、A 股 T+1/停牌/涨跌停、费用/滑点/未成交、seed 重现与分布变化、convergence 和 artifact tampering。永久排除 live trading、模拟下单、broker/order、文件、web/search、memory、swarm、上游 Web/persistence 及其主项目 interface/占位符；若无凭据路径不能提供可信核心能力，则以运行证据 `reject` 或 `keep-local` 并继续 Goal。
## Answer

已在仓库外 pinned commit
`0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` 的 checkout-local Python
3.11 `.venv` 中完成 stdio MCP 黑盒与源码资格化。真实 `initialize` /
`tools/list` 返回 54 个工具和稳定 schema hash；受限调用、crash、timeout、
malformed-result、算法对抗和 artifact tampering 均有可复现实验证据。上游 hash
lock 内部不可满足；实际无凭据 known-answer `backtest` 四次均以 MCP success
envelope 承载 application failure，并在 local loader 不可用后试图降级到要求 token
的 Tushare。所谓 Walk-Forward 只是事后窗口切分，Monte Carlo 只是已实现交易 P&L
顺序置换，Bootstrap 是 IID 单 bar 收益抽样；三者均缺少所需身份、依赖结构与收敛证据。

因此整个 Vibe MCP、`backtest(run_dir)`、Walk-Forward、Bootstrap、策略 Monte
Carlo 和 Shadow/generic report 路径均为 `reject`，生产 MCP allowlist 明确为
`[]`，不得建立 `VibeTradingMcpAdapter`、代理、placeholder 或第二报告路径。仅将
per-symbol one-bar lag/next-open、PIT masking、需补强的 A 股执行规则骨架，以及需由
独立 verifier 绑定完整身份的 hash inventory 列为 `adapt-code` 候选；这不等于采用
外部 runtime，也不提前授权创建 `StrategyValidation` port。

正式结论见
[Vibe-Trading runtime qualification and adoption decision](../research/vibe-trading-runtime-qualification-and-decision.md)，
机器可读证据见
[runtime evidence](../research/vibe-trading-runtime-evidence.json)，源码审计见
[MCP source and correctness audit](../research/vibe-trading-mcp-source-and-correctness-audit.md)。
本票未修改生产代码、项目依赖、schema、Web、persistence 或 application interface。