# Personal Research and Trading Strategy Platform

This repository is a local-first, deterministic research and decision-support
platform. It preserves immutable evidence, point-in-time data, workflow history,
Forecast and Scenario Valuation artifacts, and a canonical
`ResearchDecisionView@2`. It does not place orders or provide personalized
investment instructions.

## Canonical control plane

Users operate the product by asking Codex for exactly one of the three
natural-language Skill tasks:

- research an account security and generate or revise its discipline-plan draft;
- review today's holdings and watchlist;
- run a cycle discipline review.

Codex resolves identities and constructs the formal requests. Users do not
write request JSON, command envelopes, or fragmented CLI commands.
For the holdings/watchlist review, Codex invokes
`manual_portfolio_review.run@2` with exactly `account_id`, `requested_at`, and `session_selection` fixed to `latest_proven_complete_session`.
The application selects the latest proven complete session, prior successful
cutoff, current code/config identities, and the holdings plus default watchlist
universe.

Codex and maintainers use these deterministic maintenance adapters:

```powershell
python -m trading_platform.cli bootstrap --data-root <root>
python -m trading_platform.cli health --data-root <root>
python -m trading_platform.cli doctor --data-root <root>
python -m trading_platform.cli migrate --data-root <root>
python -m trading_platform.cli sync --data-root <root> --job-file <job.json>
python -m trading_platform.cli research --data-root <root> --request-file <request.json>

python -m trading_platform.cli history --data-root <root> --workflow-run-id <id>
python -m trading_platform.cli archive --data-root <root> --kind manifest --id <id>
python -m trading_platform.cli provider-qualify --data-root <root> --job-file <job.json>
python -m trading_platform.cli serve --data-root <root> --web-root web/dist --account-id <id> --security-id <id>
python -m trading_platform.cli backup --data-root <root> --archive <outside-root.zip>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <new-root>
python -m trading_platform.cli test --repo-root .
```

For internal adapter integration and diagnostics only, Codex or a maintainer
may invoke:

```powershell
python -m trading_platform.cli application-command --data-root <root> --envelope-file <command.json>
```

Codex creates that ephemeral envelope; it is not a user-authored product input.

The canonical `TradePlanDetailView@1` is decision-first: its default `decision_summary` uses user language for lifecycle, horizon and review date, quantities, trigger behavior, risk constraints, evidence freshness, and the current evaluation plus next step. Internal identities, complete provenance, and version history are available only through progressive disclosure.

The production chart path is likewise singular: `ChartWorkspaceView@1` selects one frozen daily OHLCV frame, and `chart_annotation.apply@1` appends immutable annotation versions using exact market timestamps and decimal prices. The retired `/api/chart-series` and `/api/annotations` routes remain absent.

Every command emits one JSON envelope. Failures retain a typed code and only
redacted diagnostics. A present process environment scope is the explicit
credential override; otherwise Windows reads the namespaced Credential Manager
target `tradingSystem/<scope>`. Values are never written to jobs, artifacts,
backups, or Git.

`ProviderJob@2` has three statically composed production roles. The
Tushare-compatible role supplies non-official structured market data and reads
only `TUSHARE_TOKEN`. The CNINFO and SZSE roles supply A-share statutory filing
documents and use `credential_env = not_applicable`; they never read a token.
See the versioned examples under `examples/platform/`. Official filing sync
persists the verified PDF and immutable filing/PIT identity, but does not infer
financial facts from PDF names or free text.

## Research path

New research always follows the platform workflow:

```text
Frozen DataSnapshot
  -> Forecast
  -> stress / base / improvement Scenario Valuation
  -> ValuationSimulationDecision / MarketPathDecision
  -> RecentTrendAssessment
  -> ResearchDecisionView@2
  -> persisted JSON / HTML / PDF / typed workbook slot
  -> application-owned OPEN TradePlanDraft
```

`ResearchWorkflow.handle` owns lifecycle policy. `WorkflowInspection`,
`ResearchArchive`, and `ForecastReview` are separate named tasks. Presentation
loads the persisted DecisionView bytes and does not recompute research or
valuation semantics.

## Data and financial boundaries

- Official disclosures are authoritative for critical financial facts.
- CNINFO/SZSE filing documents enter only through the canonical
  `sync`/`provider-qualify` path; no aggregator fallback is configured.
- Tushare-compatible structured data is an aggregator, not official disclosure.
- Every critical number resolves to source identity or is explicitly missing.
- Missing gates produce a typed data-insufficient result, never fabricated data.
- Default outputs use research language and contain no buy/sell/hold instruction,
  target-price conclusion, or house rating.

## Repository map

```text
src/equity_research/       deterministic evidence, Forecast, and valuation domain
src/trading_platform/      application tasks, workflows, persistence, CLI, and Web
migrations/                one-way local schema migrations
skills/SKILL.md            sole Codex/Skill operating entry
tests/                     domain, application, adapter, and acceptance suites
web/                       local decision workspace
```

Architecture and operating constraints are defined by
`docs/prompts/trading_platform_codex_prompt_optimized.md` and `AGENTS.md`.


## 中文使用手册

### 项目定位与边界

这是一个本地优先、可审计、可复现的股票研究与交易纪律支持平台。它可以管理账户快照、结构化市场数据、官方披露、公司研究、情景估值、K 线标注、版本化纪律计划、每日人工复核和周期复盘。

平台不自动下单，不接入实盘交易，也不提供个性化买卖建议。缺少关键证据时会明确返回 `limited`、`blocked`、`not_run` 或 `data_insufficient_memo`，不会补造数据、目标价或评级。

| 能力 | 使用方式 | 关键边界 |
| --- | --- | --- |
| 账户与持仓 | 确认本地账户快照与组合风险政策 | 缺失值保持 `unknown`，用户声明不冒充券商对账 |
| 数据同步 | 冻结行情、财务索引和官方披露 | Tushare-compatible 是聚合数据，不是官方披露 |
| 公司研究 | Forecast、三种情景、估值适用性和近期趋势 | 关键官方证据缺失时不输出正式估值结论 |
| 纪律计划 | 研究后生成应用拥有的 `OPEN` 草稿 | 用户确认精确版本后才形成不可变计划版本 |
| 今日复核 | 复核最近已证明完整交易日的持仓与观察池 | 未申报执行不等于未执行 |
| 周期复盘 | 创建 weekly 或 custom 复盘草稿 | 系统不替用户打分 |
| 本地 Web | 今日、组合、研究与计划、周期复盘、K 线标注 | 只绑定 `127.0.0.1` |

真实自动下单、券商订单生命周期、收益承诺和业务运行时 LLM 调用不在当前范围内。

### 最简单的使用方式

普通用户不需要手写 JSON、命令信封或记忆 CLI。打开本仓库的 Codex 任务，直接提出以下三类主任务：

1. 研究账户中的一只证券，并生成或修订纪律计划草稿；
2. 复核今天的持仓和观察池；
3. 进行 weekly 或自定义周期的纪律复盘。

例如：

```text
请使用本地平台研究 kong 账户中的 002407.SZ，数据口径截至 2026-07-30。
先展示证据质量、关键缺口、三种情景和近期趋势；满足门槛时生成纪律计划草稿，
但不要替我确认计划。
```

Codex 会解析账户、证券身份和时间边界，按 [`skills/SKILL.md`](skills/SKILL.md) 调用唯一入口。涉及账户、风险政策、计划、执行记录或复盘确认时，必须先展示精确内容，再等待用户明确确认。

### 首次安装

当前主要验证环境为 Windows PowerShell。项目要求 Python `>= 3.10`，锁文件当前按 Windows CPython 3.14 资格化。Node.js 与 npm 仅在重建或完整验证 Web 时需要。

```powershell
py -3.14 -m venv .venv
\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-build.lock
\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

修改 Web 时再进入 `web` 目录执行 `npm ci` 和 `npm run build`。仓库已提交生产构建到 `web/dist`，日常启动不必重复构建。个人数据目录应放在 Git 仓库之外，或使用已忽略的 `.research/`。

### 初始化本地数据根

推荐请求：

```text
请把本项目初始化到 E:\trading-data\personal，并运行 health 和 doctor；
只报告脱敏检查结果，不要显示任何凭据。
```

维护者对应命令：

```powershell
\.venv\Scripts\python.exe -m trading_platform.cli bootstrap --data-root E:\trading-data\personal
\.venv\Scripts\python.exe -m trading_platform.cli health --data-root E:\trading-data\personal
\.venv\Scripts\python.exe -m trading_platform.cli doctor --data-root E:\trading-data\personal
```

初始化会创建 `platform.sqlite3` 和内容寻址对象目录。命令只输出一个 JSON envelope；失败时保留 typed failure code 和脱敏诊断。

### 配置数据来源

生产组合有三个固定 Provider 角色：

- `tushare-compatible`：非官方结构化市场数据，凭据作用域为 `TUSHARE_TOKEN`；
- `cninfo-official`：巨潮资讯官方披露，不读取 token；
- `szse-official`：深交所官方披露，不读取 token。

版本化示例位于 [`examples/platform/`](examples/platform/)。Codex 会复制适用示例并填写新的 `invocation_id`、证券身份、日期和 `as_of_at`，不会把凭据写入作业文件。

凭据只允许来自当前进程环境，或 Windows Credential Manager 的 `tradingSystem/<scope>` 项。不要把 token 写进聊天、命令行参数、源码、`.env`、作业 JSON、日志、产物或 Git。详细来源边界见 [`TUSHARE_USAGE.md`](TUSHARE_USAGE.md)。

### 建立账户并运行研究

```text
请为本地账户 kong 建立 CNY 账户快照。先预览我提供的券商文件，列出现金、持仓、
未知项和来源边界；在我明确确认前不要提交，也不要推断缺失交易历史。
```

账户快照确认后，再确认组合风险政策。缺少这两项确认事实时，计划生成应失败关闭，而不是采用隐含默认值。

```text
请同步 002897.SZ 截至 2026-07-30 的 PIT 数据和可获得的官方披露，
然后运行完整公司研究。区分 observed_official、observed_structured、
derived、estimated 和 missing，并说明哪些方法没有运行及原因。
```

唯一研究链路为：

```text
Frozen DataSnapshot
  -> ResearchInputOrigin / BoundedEstimate
  -> Forecast
  -> stress / base / improvement Scenario Valuation
  -> ValuationSimulationDecision / MarketPathDecision
  -> RecentTrendAssessment
  -> ResearchDecisionView@2
  -> JSON / HTML / PDF / typed workbook slot
  -> application-owned OPEN TradePlanDraft
```

### 启动本地 Web

```text
请为 E:\trading-data\personal 中的 kong 账户启动本地 Web，默认打开 002407.SZ，
并把本机访问地址发给我。
```

维护者对应命令：

```powershell
\.venv\Scripts\python.exe -m trading_platform.cli serve `
  --data-root E:\trading-data\personal `
  --web-root web/dist `
  --account-id <account_id> `
  --security-id <security_id>
```

命令输出实际的 `http://127.0.0.1:<动态端口>`。Web 有 `今日`、`组合`、`研究与计划`、`周期复盘` 四个主目的地。K 线通过 `ChartWorkspaceView@1` 读取冻结日线帧；标注只经 `chart_annotation.apply@1` 追加不可变版本。

## 日常流程

### 研究到计划

1. 用户给出账户、证券和 as-of 日期；
2. 系统冻结证据，运行研究并持久化产物；
3. `trade_plan.author_draft@1` 接收有限 typed intent；
4. 应用解析已确认账户快照、风险政策和内置策略，编译完整 `TradePlanGraph`；
5. Codex 展示 `OPEN` 草稿、证据新鲜度、限制、revision、content hash 和精确 diff；
6. 用户确认该 revision 后，系统才签发并消费一次性 confirmation challenge。

`TradePlanDetailView@1` 默认先展示生命周期、期限、数量、触发行为、风险限制、证据新鲜度、当前评估原因与下一步；内部 ID 和完整 provenance 按需展开。

### 今日持仓与观察池复核

```text
请复核 kong 账户今天的持仓和默认观察池。若今天不是交易日，使用最近一个已证明完整的
A 股交易日，并明确告诉我用了哪一天。先列未解决 DecisionTask 和重要变化。
```

Codex invokes `manual_portfolio_review.run@2` with exactly `account_id`, `requested_at`, and `session_selection` fixed to `latest_proven_complete_session`. 应用负责选择交易日、上次成功 cutoff、代码/配置身份、持仓和默认观察池。

任务延期、处置和执行申报是彼此独立的用户命令。未知价格或费用保持未知；用户申报默认是 `user_declared_unverified`。

### 周期纪律复盘

```text
请为 kong 创建覆盖 2026-07-20 至 2026-07-24 完整交易日的 weekly 纪律复盘草稿。
列出计划内外行为、延期、未记录或未核验事项和证据缺口，不要替我确认。
```

应用根据 task、action、execution、plan、snapshot、exception 和 evidence gap 分类，但不接受调用者提供分数。复盘不限于周五，也没有后台调度器自动触发。

## 场景示例

### 场景 A：证据充足时研究到计划

```text
研究 kong 账户的 002407.SZ，口径截至 2026-07-30。使用冻结数据和官方披露，
生成三种情景、估值适用性、关键不确定性和近期趋势；通过风险门后生成计划草稿。
```

预期：同一运行持久化 JSON、HTML、PDF 和 workbook slot；关键数字都有 source identity 或明确为 estimated/missing；计划保持 `OPEN`，不会自动生效。

### 场景 B：缺少官方关键数据

```text
研究 002897.SZ。如果官方披露或估值输入不完整，继续完成能完成的研究结构，
清楚列出缺口，不要生成目标价、评级或行动建议。
```

预期：模块返回 `limited`、`blocked` 或 `not_run` 及 reason code；估值使用 `data_insufficient_memo`；不会把聚合数据改称官方数据，也不会用零填补未知值。

### 场景 C：非交易日复核

```text
今天复核 kong 的持仓和观察池。如果今天休市，不要假造当日行情，改用最近完整交易日。
```

预期：明示实际交易日和 cutoff，优先显示 DecisionTask、重要变化及 unable/unknown 状态，不会自动确认计划或推断用户已行动。

### 场景 D：申报实际执行

```text
我要处理某个 DecisionTask。先展示它引用的计划版本和规则；我确认后，按我提供的数量、
生效时间和已知/未知价格费用状态申报执行，不要推断缺失值。
```

预期：只有 `execution_record.declare@1` 能把任务处置为 `executed`；action log、execution、task transition 和 receipt 原子提交；修正追加新事实，不覆盖原记录。

### 场景 E：备份与恢复演练

```text
把 E:\trading-data\personal 备份到 E:\trading-backups\personal-20260731.zip，
恢复到新的 E:\trading-data\restore-check 并运行 doctor；不要切换当前数据根。
```

预期：备份包含 SQLite、对象和哈希清单；restore 校验路径、大小、hash、schema、外键和对象图；只有用户另行要求时才切换数据根。

## 输出、验证与故障排查

```text
<data-root>/
  platform.sqlite3               事务、身份、版本、状态和审计索引
  objects/sha256/<前两位>/<hash>  不可变源数据与研究产物
```

研究 manifest 引用不可变 JSON、HTML、PDF、workbook 或 typed limitation artifact。不要直接修改；使用 `history`、`archive`、Web read model 或正式 application task 读取。备份必须位于数据根之外。

```powershell
# 完整验证
\.venv\Scripts\python.exe -m trading_platform.cli test --repo-root .

# README 与 Skill 入口契约定向验证
\.venv\Scripts\python.exe -m pytest -q tests/platform/test_skill_contract.py tests/test_skill_entrypoint.py
```

- `PLATFORM_NOT_BOOTSTRAPPED` / `DATA_ROOT_NOT_INITIALIZED`：先执行 `bootstrap`，再运行 `health` 和 `doctor`。
- `provider_readiness=not_configured`：检查 Provider 角色和本机凭据作用域，不要把 token 发到聊天中。
- `completed_with_limits`：表示报告结构完成但有明确限制，不代表关键数据已由官方确认。
- Web 无内容：确认账户、证券 ID 和 read model 已持久化，以 `serve` 返回的动态 URL 为准。
- `ok=false`：保留 `operation`、typed `error.code` 和脱敏 diagnostic，不要绕过失败步骤直接写库。

Timeout、skip、external check 未运行或 setup failure 都不是通过。

进一步阅读：[`docs/architecture/target-architecture.md`](docs/architecture/target-architecture.md)、[`docs/open-source-research.md`](docs/open-source-research.md)、[`skills/references/source-manifest.md`](skills/references/source-manifest.md) 和 [`skills/valuation/valuation-method-router.md`](skills/valuation/valuation-method-router.md)。
