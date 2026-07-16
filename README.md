# Personal Equity Research System

这是一个面向个人研究流程的、可审计股票投研平台。当前公司未来推演主链以 frozen DataSnapshot、typed Forecast 和 typed Valuation 为事实源：

```text
Frozen evidence -> Forecast Graph -> Scenario Valuation
                -> optional Monte Carlo / market paths
                -> ResearchDecisionView@2
                -> canonical JSON + decision-first HTML + reconciled XLSX
```

`ResearchRun@3` 与自由 `context` 只保留为历史输入兼容层。新平台执行先把旧输入迁移为 `ResearchInputs@1`，正式展示不再从 `analyses/debate/synthesis/scenarios/dcf_case` 等 magic keys 直接取数。

## 解决了什么

- 不再用一个 23 字段布尔门禁阻断全部流程；
- 缺 D&A 只影响依赖 D&A 的模型，缺 peer 只影响可比估值；
- 事实、推导值和估算值保持不同身份；
- as-of 日期按公开可得时间执行；overlay 标的身份和所有结构化 evidence refs 都会确定性校验；
- DCF 只接受显式 FCFF、WACC、终值和股权桥，不使用无来源默认值；
- 完整性错误 fail-closed 为数据不足备忘录，不执行或展示数值估值；
- 公司、行业、基本面、技术、情绪事件、估值、治理风险成为一等分析维度；
- 正反质询必须绑定 evidence IDs，Research Manager 记录分歧与未解决问题；
- HTML 正文以公司研究为主，能力、方法、来源和诊断收进折叠审计附录；
- 正式 HTML、JSON 和 XLSX 从同一个 `ResearchDecisionView@2` 生成；
- XLSX 逐步重算 enterprise/equity/per-share bridge，核心输出硬编码或断链即失败；
- 默认输出条件研究计划，不生成个性化投资指令。

## 运行遗留 V3 兼容样例

以下文件式 CLI 用于读取历史 `research_context.json`。它会发出版本化迁移诊断，不是平台新执行的输入接口。

意华股份：

```powershell
python scripts\research.py run `
  --manifest examples\yihua-002897\source_manifest.json `
  --estimates examples\yihua-002897\estimate_overlay.json `
  --context examples\yihua-002897\research_context.json `
  --as-of-date 2026-07-07 `
  --output-dir outputs\yihua_002897_20260707\v3
```

多氟多：

```powershell
python scripts\research.py run `
  --manifest examples\duofuduo-002407\source_manifest.json `
  --context examples\duofuduo-002407\research_context.json `
  --as-of-date 2026-07-03 `
  --output-dir outputs\dfd_002407_20260703\v3
```

产物：

- `research_run.json`：canonical evidence、`AnalysisBundle`、多空质询、综合观点、能力与方法状态；
- `research_report.html`：自包含、响应式、可打印的专业公司研究报告；审计信息默认折叠。

样例预期结果：

| 项目 | 状态 |
|---|---|
| 基础研究 | `ready` |
| 盈利质量 | `ready` |
| 财务模型与情景 | `ready_with_estimates` |
| DCF | `blocked`，只限制该方法 |
| 可比公司法 | `blocked`，缺合格 peer set |
| 专业研究报告 | `ready` 或 `limited`，取决于多维分析完整度 |
| 总运行 | `completed_with_limits` |

## 代码结构

```text
src/equity_research/
  models.py       # ResearchRequest / ResearchRun 稳定契约
  evidence.py     # manifest integrity、字段规范化、事实与估算分层
  policies.py     # capability matrix
  valuation.py    # method registry、DCF、comps、历史带
  narrative.py    # AnalysisBundle、证据约束质询与 ResearchSynthesis
  output_policy.py # 默认金融语言边界
  engine.py       # 唯一确定性执行入口
  research_inputs.py # typed inputs + legacy context adapter
  report.py       # 遗留 ResearchRun 兼容渲染
  professional_report.py # 遗留专业报告兼容渲染
  cli.py          # 文件系统 adapter

skills/
  SKILL.md        # 唯一入口：V3 多维分析、质询、综合与交付规约
  references/capability-matrix.md

examples/yihua-002897/
  source_manifest.json
  estimate_overlay.json
  research_context.json

examples/duofuduo-002407/
  source_manifest.json
  research_context.json

tests/
  test_research_engine.py
  test_cli.py
```

平台正式展示模块位于：

```text
src/trading_platform/
  research_view.py          # typed artifacts -> ResearchDecisionView@2
  research_presentation.py  # canonical view -> decision-first HTML
  valuation_workbook.py     # canonical view -> reconciled XLSX adapter
scripts/render_valuation_xlsx.mjs
```

## CLI

只评估、不写文件：

```powershell
python scripts\research.py assess `
  --manifest examples\yihua-002897\source_manifest.json `
  --estimates examples\yihua-002897\estimate_overlay.json `
  --context examples\yihua-002897\research_context.json `
  --as-of-date 2026-07-07 `
  --pretty
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 估值实现边界

当前可执行层包括：

- 观察倍数：只显示已报告年度分母对应的市场倍数；
- peer comps：至少 3 个主体、语义角色和 evidence refs 均唯一且完成币种/会计口径检查的样本，计算四分位和每股映射；
- historical band：至少 12 个带日期和 canonical evidence refs 的截止日前观察，计算分布位置，不自动解释为均值回归；
- DCF：显式 FCFF 序列与单位、可重算 WACC components、`WACC > g`、完整且显式的股权桥和 5×5 敏感性；未知桥接项不会当作零。
- 周期与资源：mid-cycle、周期历史带和有限资源 NAV；
- 金融企业：P/B–ROE/COE、DDM、residual income / excess return；
- 创新药：管线 rNPV、SOTP 与现金跑道；
- 多情景 Monte Carlo：基于 frozen dependency model、事件和估值模型生成条件分布；市场价格路径与内在价值分布保持分离。

方法不适用或输入不足会在 typed artifact 中明确标记，不会用默认值补齐。

方法复核见 [methodology-assessment.md](docs/research/methodology-assessment.md)。

## 开源对照

参考仓库已克隆到本地 `.research/upstreams/`（该目录不进入版本控制）：

| 项目 | 固定提交 | 本地研究 |
|---|---|---|
| TradingAgents | `01477f9afb7a47b849ed4c9259d3a9a4738d9fda` | [tradingagents.md](docs/research/upstreams/tradingagents.md) |
| daily_stock_analysis | `d08374898c25f4718d61b1779ac4c1fedc9aa9a2` | [daily_stock_analysis.md](docs/research/upstreams/daily_stock_analysis.md) |
| UZI-Skill | `fce996c33e70eddce8e375f53cd252b549eb3d7c` | [uzi-skill.md](docs/research/upstreams/uzi-skill.md) |
| FinRobot | `297a8d28d099be328c8a8eb658b4f782b93f3651` | [finrobot.md](docs/research/upstreams/finrobot.md) |

## 文档

- [当前系统审计](docs/architecture/current-system-audit.md)
- [目标架构](docs/architecture/target-architecture.md)
- [估值与分析方法论复核](docs/research/methodology-assessment.md)
- [统一 Skill 工作流](skills/SKILL.md)

## 研究边界

本项目用于公开资料研究、估值框架、风险分析和条件验证，不连接券商下单，不替用户作个性化投资决定。正式数值方法必须满足自身证据要求；估算字段只能进入明确标注的探索情景。

## Tushare-compatible 平台接入

平台通过 job 中的 `provider_type: tushare_compatible` 使用确定性 HTTP adapter。无密钥示例见 `examples/platform/tushare-compatible-yihua-job.json`。job 只保存 `credential_env: TUSHARE_TOKEN`，不保存 token 值。

Codex 先执行 `bootstrap`，随后用同一个 job 执行 `doctor`、`sync`/`daily` 和 `provider-qualify`。资格产物只包含 provider 身份、数据集、状态、获取时间与 raw SHA-256，可通过 `acceptance --live-qualification-file <qualification.json>` 冻结进验收证据。该兼容网关始终标记为结构化聚合源，不替代 CNINFO、交易所或公司 IR 的正式披露权威。
