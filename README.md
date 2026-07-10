# Personal Equity Research System

这是一个面向个人研究流程的、可审计的股票投研内核。它把原先完全由长篇 Skills 驱动的 Task 1/2/3，重构为确定性的：

```text
ResearchRequest -> ResearchRun -> JSON + HTML
```

Skills 仍可用于寻找资料和撰写受证据约束的研究叙事；来源完整性、能力门禁、估值方法、DCF invariant、权限、诊断和报告渲染由 Python 实现。

## 解决了什么

- 不再用一个 23 字段布尔门禁阻断全部流程；
- 缺 D&A 只影响依赖 D&A 的模型，缺 peer 只影响可比估值；
- 事实、推导值和估算值保持不同身份；
- as-of 日期按公开可得时间执行；overlay 标的身份和所有结构化 evidence refs 都会确定性校验；
- DCF 只接受显式 FCFF、WACC、终值和股权桥，不使用无来源默认值；
- 完整性错误 fail-closed 为数据不足备忘录，不执行或展示数值估值；
- HTML 和 JSON 从同一个 `ResearchRun` 生成；
- 默认输出条件研究计划，不生成个性化投资指令。

## 一条命令运行意华股份样例

```powershell
python scripts\research.py run `
  --manifest examples\yihua-002897\source_manifest.json `
  --estimates examples\yihua-002897\estimate_overlay.json `
  --context examples\yihua-002897\research_context.json `
  --as-of-date 2026-07-07 `
  --output-dir outputs\yihua-v2
```

产物：

- `research_run.json`：canonical evidence、capability matrix、method registry、permissions、plans 和 diagnostics；
- `research_report.html`：自包含、响应式、可打印的研究报告。

样例预期结果：

| 项目 | 状态 |
|---|---|
| 基础研究 | `ready` |
| 盈利质量 | `ready` |
| 财务模型与情景 | `ready_with_estimates` |
| DCF | `blocked`，只限制该方法 |
| 可比公司法 | `blocked`，缺合格 peer set |
| 研究报告 | `ready` |
| 总运行 | `completed_with_limits` |

## 代码结构

```text
src/equity_research/
  models.py       # ResearchRequest / ResearchRun 稳定契约
  evidence.py     # manifest integrity、字段规范化、事实与估算分层
  policies.py     # capability matrix
  valuation.py    # method registry、DCF、comps、历史带
  output_policy.py # 默认金融语言边界
  engine.py       # 唯一确定性执行入口
  report.py       # canonical ResearchRun -> self-contained HTML
  cli.py          # 文件系统 adapter

skills/
  SKILL-v2.md     # agent/skill 的 v2 操作规约
  references/capability-matrix.md

examples/yihua-002897/
  source_manifest.json
  estimate_overlay.json
  research_context.json

tests/
  test_research_engine.py
  test_cli.py
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

尚未实现为计算器的行业模型会明确路由/禁用，不会伪装成已完成能力，包括 rNPV、NAV、residual income、DDM 和完整 mid-cycle builder。

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
- [v2 Skill 工作流](skills/SKILL-v2.md)

## 研究边界

本项目用于公开资料研究、估值框架、风险分析和条件验证，不连接券商下单，不替用户作个性化投资决定。正式数值方法必须满足自身证据要求；估算字段只能进入明确标注的探索情景。
