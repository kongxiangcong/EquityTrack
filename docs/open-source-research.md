# 开源项目与第一纵向切片技术研究总表

Status: `first-slice-decision-baseline`
Evidence as of: `2026-07-11 Asia/Shanghai`

本文件是总任务 Prompt 要求的 `docs/open-source-research.md` 汇总入口。它只批准第一条纵向切片实际使用的技术边界；详细证据仍保存在固定提交源码审查和专题 research 资产中。未进入第一切片的量化、组合和回测框架在本文件中明确保持 `not_assessed / not_approved`，不得据此宣称长期 Phase 1 或完整平台调研已经结束。

## 证据方法

- 投研/Agent 项目使用本地只读固定提交，检查源码、测试、CI、依赖、提交元数据与根许可证；没有把 README 功能声明直接当成实现事实。
- Provider、图表、存储研究检查固定客户端/包版本、核心接口、许可证或服务条款、Windows 行为、失败恢复及本机 probes。
- 金融方法只采用 CFA Institute 与 Aswath Damodaran 等一手方法资料作为约束，不复制第三方估值默认值。
- 开源代码许可证不自动覆盖外部数据、模型服务、网页端点或再分发权；这些边界分别进入 Provider/fixture 的 `source_terms_profile`。

## 第一切片决策矩阵

| 对象 | 固定证据 | 许可/归属 | 可借鉴能力 | LLM/外部服务与数据严谨性 | Windows/恢复/测试 | 结论 |
|---|---|---|---|---|---|---|
| TradingAgents v0.3.1 | [固定提交源码审查](research/upstreams/tradingagents.md) | 根 `LICENSE` 为 Apache-2.0 | typed state、节点/边、checkpoint、错误与工程回归 | 业务核心依赖 LLM；无确定性估值、组合账户或真实执行，A 股正式披露/PIT 不足 | CI 覆盖 Python 3.10-3.13；本机 3.14 未建专用环境，不能算上游失败 | `reference only`；吸收工作流/恢复思想，拒绝运行时 Agent 架构 |
| FinRobot 固定提交 | [源码对照研究](research/upstreams/finrobot.md) | 根 `LICENSE`/`NOTICE` 为 Apache-2.0 | 分析制品与报告渲染拆分、局部能力降级、report-data seam | 默认估值输入与主观 confidence 加权不可接受；测试偏 smoke | 不作为第一切片运行依赖 | `reference only`；吸收 artifact pipeline，拒绝默认估值与点值合成 |
| daily_stock_analysis 固定提交 `d083748` | [固定提交源码审查](research/upstreams/daily_stock_analysis.md) | 根 `LICENSE` 为 MIT | Provider fallback、缓存、任务/历史 UI、结构化错误与测试习惯 | 运行时深度依赖 LLM/外部源；财务权威与估值实现不足 | 有 FastAPI/Web/桌面与大量测试；模块热点和隐式依赖使直接集成成本高 | `adapt patterns only`；借鉴 adapter/UX，不引入其运行时或评分结论 |
| UZI-Skill 固定提交 `fce996c` | [固定提交源码审查](research/upstreams/uzi-skill.md) | 根 `LICENSE` 为 MIT | 顶层最窄路由、provider registry、能力级降级、报告 UX、bug 回归 | Agent 会改写制品；估值存在无来源默认值和市场价格循环；输出越过本项目金融边界 | 本机部分测试因 import-time 缺依赖未收集；上游无持续 CI 证据 | `adapt patterns only`；吸收控制面/报告模式，拒绝业务运行时和默认金融输出 |
| CFA / Damodaran 方法资料 | [估值与分析方法论复核](research/methodology-assessment.md) | 教学/研究资料，只引用不复制实现 | 现金流-折现率匹配、股权桥、行业适配、再投资/增长、敏感性边界 | 作为确定性实现 invariant；不提供默认公司输入 | 由本地 worked-example/unit tests 验证 | `adopt methodology constraints` |
| 官方披露 + Tushare-compatible gateway + AKShare/BaoStock | [Provider/PIT 研究](../.scratch/trading-platform-first-vertical-slice-spec/research/data-providers-pit-cache.md) | 客户端许可与数据服务/网页条款分开；逐 adapter 保存 terms profile | 官方权威、结构化行情、增量 cursor、回退和交叉核验 | 必须保存四类时间、真实来源、未复权 canonical；第三方不能恢复官方财务权限 | 固定 adapter、contract suite、offline fixture、live qualification | 官方权威 `adopt`；Tushare/AKShare `adapt`；BaoStock `reference only` |
| Kimi Datasource 3.2.0 | [源码与 live probes](../.scratch/trading-platform-first-vertical-slice-spec/research/kimi-datasources-provider.md) | CLI/plugin 许可不解决自动化与数据留存许可 | 低频来源发现和候选采集 | LLM 选择工具/参数，缺上游/PIT 元数据，存在 empty-exit-0 与偏航 | 只允许控制面 staging + transcript verifier | `adapt control-plane bridge`; `reject runtime Provider` |
| KLineChart 10.0.0 | [图表/许可证研究](../.scratch/trading-platform-first-vertical-slice-spec/research/chart-libraries-and-annotation-models.md) | Apache-2.0，分发需保留 LICENSE/NOTICE/归属 | K 线、成交量、overlay 和时间/价格坐标 | 不承担行情、日历、复权或持久化 | 已做 Windows Chromium 原型；正式采用仍需自动 E2E、重启、离线、生命周期/性能门 | `adapt`，仅在 chart adapter 后使用 |
| Lightweight Charts 5.2.0 | [图表/许可证研究](../.scratch/trading-platform-first-vertical-slice-spec/research/chart-libraries-and-annotation-models.md) | Apache-2.0 + 页面归属要求 | primitive、hit-test、lifecycle 与上游测试 | 交互绘图需自建 | 作为 KLineChart 门失败时的候选 | `reference only` |
| ECharts 6.1.0 | [图表/许可证研究](../.scratch/trading-platform-first-vertical-slice-spec/research/chart-libraries-and-annotation-models.md) | Apache-2.0/NOTICE | 通用分析可视化 | 不是金融绘图编辑器 | 第一 K 线切片集成成本较高 | `reference only` |
| SQLite + SHA-256 object store | [本地存储/恢复研究](../.scratch/trading-platform-first-vertical-slice-spec/research/local-runtime-store-and-recovery.md) | SQLite public domain；自有 object protocol | 单用户事务权威、在线备份、短事务、不可变产物 | 支撑 PIT/version/journal，不提供业务语义 | 本机锁/backup probes；WAL 有已知版本门 | `adopt` |
| DuckDB/Parquet | [本地存储/恢复研究](../.scratch/trading-platform-first-vertical-slice-spec/research/local-runtime-store-and-recovery.md) | 采用前重新生成第三方清单 | 列式分析 | 不承担交易计划、journal 或 manifest 权威 | 只有真实 benchmark 证明需要后启用 | `defer / not approved` |
| PostgreSQL | [本地存储/恢复研究](../.scratch/trading-platform-first-vertical-slice-spec/research/local-runtime-store-and-recovery.md) | 采用前重新核验 | 多写者、远程和数据库级恢复 | 当前单用户切片无需求证据 | Windows server 运维成本过高 | `reject for first slice` |
| 当前 Yahoo/manifest 资产 | [当前 MVP 审计](../current-product-state-audit.md) | 未保存完整服务条款/可回放 raw | 研究回归输入 | 非 A 股关键事实权威，无 Provider/PIT/cache | 继续跑既有回归 | `regression fixture only`; `reject production` |

## 明确未批准的后续框架

Qlib、QuantConnect Lean、vectorbt、PyPortfolioOpt、Riskfolio-Lib、yfinance 以及完整策略/组合/回测技术栈不进入第一纵向切片。当前没有足以支持采用的固定版本、许可证/NOTICE、核心实现、Windows、数据许可、反前视和失败恢复矩阵，因此状态统一为 `not_assessed / not_approved`，不是 `reject`。

在任何策略、回测、组合优化或多账户切片开始前，必须新建独立 research effort 完成这些项目的固定提交源码与测试审查，并生成相应 `adopt / adapt / reference only / reject` 结论。第一切片不得预装这些依赖，也不得把 PIT sentinel 测试宣传成完整回测严谨性。

## 依赖与许可证实施门

第一切片引入的每个 Python/npm 包必须：

1. 在 lockfile 中固定版本与完整性；
2. 生成 machine-readable dependency/license inventory；
3. 在分发物中携带适用的 `THIRD_PARTY_NOTICES`、LICENSE/NOTICE 与页面归属；
4. 证明离线构建/运行不依赖 CDN、遥测或运行时自动安装；
5. 将代码许可与 Provider 数据/fixture 保存、回放、再分发权分开记录。

未通过上述门的依赖不得进入生产 composition root，未确认可再分发的 fixture 不得提交到 Git 或打入发布包。
