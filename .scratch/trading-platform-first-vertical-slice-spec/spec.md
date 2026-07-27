# 个人投研交易策略平台：第一条纵向切片实现级 Spec

> 历史边界：本文件锁定第一纵向切片的设计与验收背景。交易纪律内核的当前实现、
> named application task、迁移与 replace-and-delete 要求，以
> `../trading-discipline-kernel/trading-discipline-kernel-spec.md` 及其票据为权威；
> 本文件中已被后续切换取代的 facade、脚本或旧 read-model 描述不得作为兼容路径保留。

Status: `implementation-ready`
Spec-Version: `0.2.0`
Decision-Gate: `adversarial-audit-passed`

本 Spec 综合 Wayfinder 已关闭的审计、研究、领域、原型与设计票据，定义第一条纵向切片的实施合同。0.2.0 已通过[八视角对抗性审计](spec-adversarial-audit.md)并关闭审计发现的实施前缺口；当前文件本身仍不代表平台、数据库、Web UI、Provider 或纵向切片已经实现。

长期范围、金融边界和完成定义以[总任务 Prompt](../../docs/prompts/trading_platform_codex_prompt_optimized.md)为最高约束；领域命名以[领域词汇表](../../CONTEXT.md)为准。

本 Spec 只批准第一纵向切片进入实现，不宣称长期平台、完整开源调研、账户/组合、策略回测或总任务 Prompt 的全部交付已经完成。第一切片的外部技术结论已汇总到[开源项目与第一纵向切片技术研究总表](../../docs/open-source-research.md)；后续量化/组合技术栈仍为 `not_assessed / not_approved`。

## 1. 目标与完成边界

第一条纵向切片必须让单用户在 Windows 本地环境中，围绕一个观察项完成以下真实闭环：

```text
观察项
  -> 用户授权增量同步并冻结 DataSnapshot
  -> 通过既有 ResearchEngine seam 复用或新建 ResearchRun
  -> 查看版本化 K 线并持久化 ChartAnnotation
  -> 编辑、确认并显式启用 TradePlanVersion
  -> 构建当日 MarketSnapshot 并确定性执行 PlanEvaluation
  -> 从 WorkflowRun 历史回看全部版本、证据、产物和运行记录
```

完成不是“文档写完”“目录搭好”“静态页面可看”或“自然语言报告生成”。只有第 17 节定义的本地确定性验收门全部通过，才可声明 fixture-backed 第一纵向切片通过；生产 Provider 的 live qualification 必须另列，不能由 fixture 通过替代。

## 2. 当前事实与目标设计的严格分界

| 范围 | 当前 checkout 的事实 | 本 Spec 的目标 |
|---|---|---|
| 研究 | 已有无 I/O 的 `ResearchEngine.run(ResearchRequest) -> ResearchRun`、CLI adapter、报告 renderer 和 35 项行为测试 | 原样复用公共 seam；只在外部增加 snapshot-to-request adapter、持久化和工作流引用 |
| 数据 | 有版本化研究输入映射和历史输出，但没有业务 Provider、raw cache、PIT snapshot 或数据游标 | 增加 typed Provider、不可变 raw、normalized version、DataSnapshot、质量和 freshness 合同 |
| 存储 | 没有数据库、schema migration、run journal 或 artifact manifest | SQLite 事务权威 + SHA-256 内容寻址不可变 object store |
| 图表 | 只有遗留静态图工具；Wayfinder 原型使用 `localStorage` 验证了 DTO round-trip | 正式本地 Web K 线、SQLite 标注版本链、刷新与进程重启恢复 |
| 计划/市场 | `conditional_plan` 只是研究复核项；没有交易计划状态机、市场快照或规则引擎 | 用户输入草稿、不可变版本、显式生效历史、透明市场组件和只读确定性评估 |
| 工作流/运维 | 没有 platform facade、workflow registry、恢复 journal 或九项维护入口 | 单进程模块化单体、稳定 ApplicationFacade、可恢复工作流与跨平台入口 |

这些事实由[当前股票投研 MVP 实现审计](../../current-product-state-audit.md)和[审计当前投研 MVP 与可复用边界](issues/01-audit-current-mvp-and-reuse-seams.md)支撑。任何实施文档、页面或完成摘要都必须继续使用“当前/目标”时态，不得把本 Spec 的目标描述为现状。

## 3. 证据化采用、改造与拒绝矩阵

| 决策对象 | 结论 | 第一切片中的使用方式 | 证据 |
|---|---|---|---|
| 既有研究内核 | 直接复用公共 seam | 平台只调用 `ResearchEngine.run(ResearchRequest) -> ResearchRun`；不复制证据、估值、叙事或 renderer 内部实现 | [MVP 审计](../../current-product-state-audit.md)、[复用边界决策](issues/01-audit-current-mvp-and-reuse-seams.md) |
| 官方披露渠道 | 采用权威性、改造接入 | CNINFO、SSE/SZSE/BSE、公司 IR 为公告、关键财务和公司行动的权威 raw；adapter 必须可替换且遵守条款 profile | [Provider/PIT 研究](research/data-providers-pit-cache.md) |
| Tushare-compatible gateway | 可选生产 adapter | 配置和权益允许时用于主数据、日历、OHLCV、复权因子、市场横截面及披露索引；保留真实网关身份，不冒充官方披露权威 | [Provider/PIT 研究](research/data-providers-pit-cache.md)、[Tushare 与 Kimi 对比](research/kimi-experiments/tushare-vs-kimi-datasource.md) |
| AKShare 1.18.64 | 回退/交叉核验 adapter | 固定版本、补重试/熔断/schema/provenance；聚合财务数据不升级为官方事实 | [Provider/PIT 研究](research/data-providers-pit-cache.md) |
| BaoStock 0.9.2 | 仅参考 | 可做 OHLCV/日历/复权交叉核验或 fixture 候选，不作为唯一生产依赖 | [Provider/PIT 研究](research/data-providers-pit-cache.md) |
| Kimi Datasource | 控制面低频采集桥；拒绝运行时 Provider | 只能由用户明确触发、在 Codex/Skill 隔离 staging 中使用，并经确定性 transcript/file verifier 后作为次级候选；`sync/daily/Web` 不得启动 Kimi CLI | [Kimi Datasource 研究](research/kimi-datasources-provider.md) |
| 当前 Yahoo/manifest 资产 | 仅研究回归；拒绝生产 | 保留现有 `ResearchEngine` 回归，不作为 Provider cache、PIT 数据或生产行情源 | [Provider/PIT 研究](research/data-providers-pit-cache.md)、[MVP 审计](../../current-product-state-audit.md) |
| SQLite + object store | 采用 | SQLite 为唯一事务权威；raw 和大产物进入 SHA-256 内容寻址不可变文件库 | [本地存储/恢复研究](research/local-runtime-store-and-recovery.md)、[数据合同决策](issues/07-decide-data-storage-and-pit-contracts.md) |
| DuckDB/Parquet | 延后 | 只有真实列式 benchmark 证明 SQLite baseline 不足时，才作为不可变分析层 adapter；不承担事务权威 | [本地存储/恢复研究](research/local-runtime-store-and-recovery.md) |
| PostgreSQL | 当前拒绝 | 仅在多写者、远程访问或数据库级 PITR 成为硬需求时重新研究 | [本地存储/恢复研究](research/local-runtime-store-and-recovery.md) |
| Alembic/SQLAlchemy | 当前不引入 | 第一切片使用不可变顺序 SQL migration；未来若另有证据采用 SQLAlchemy，再评估 Alembic | [本地存储/恢复研究](research/local-runtime-store-and-recovery.md)、[数据合同决策](issues/07-decide-data-storage-and-pit-contracts.md) |
| `klinecharts@10.0.0` | 受控改造 | 只在薄 chart adapter 后使用；领域 DTO、版本、复权和持久化均与图库解耦 | [图表研究](research/chart-libraries-and-annotation-models.md)、[原型决策](issues/09-prototype-chart-and-annotation-seam.md) |
| Lightweight Charts 5.2.0 | 本切片仅参考 | 借鉴 primitive、坐标和 lifecycle；若 KLineChart 正式门禁失败则升为候选 | [图表研究](research/chart-libraries-and-annotation-models.md) |
| ECharts 6.1.0 | K 线交互面仅参考 | 不承担首切片交互 K 线；后续非 K 线可视化另行评估 | [图表研究](research/chart-libraries-and-annotation-models.md) |
| 高阶 TradingView 产品、Widgets、KLineChart Pro | 本切片拒绝 | 不把开源基础包许可外推到不同商业/托管产品 | [图表研究](research/chart-libraries-and-annotation-models.md) |
| TradingAgents v0.3.1 | 仅参考 | 只吸收 typed state、checkpoint、错误和回归思路；业务运行时拒绝 Agent/LLM 架构 | [固定提交源码审查](../../docs/research/upstreams/tradingagents.md)、[研究总表](../../docs/open-source-research.md) |
| FinRobot 固定提交 | 仅参考 | 只吸收 artifact pipeline/局部降级；拒绝无来源默认估值与 confidence 点值合成 | [固定提交源码审查](../../docs/research/upstreams/finrobot.md)、[研究总表](../../docs/open-source-research.md) |
| daily_stock_analysis 固定提交 | 改造模式、拒绝运行时 | 借鉴 Provider fallback、缓存和任务/历史 UX；不引入其 LLM、评分或浅层根接口 | [固定提交源码审查](../../docs/research/upstreams/daily_stock_analysis.md)、[研究总表](../../docs/open-source-research.md) |
| UZI-Skill 固定提交 | 改造模式、拒绝金融默认值 | 借鉴最窄 Skill 路由、能力级降级和报告 UX；不复制 Agent 制品写入、默认估值和交易语义 | [固定提交源码审查](../../docs/research/upstreams/uzi-skill.md)、[研究总表](../../docs/open-source-research.md) |
| CFA / Damodaran 方法约束 | 采用方法、不复制代码 | 保留现金流/折现率匹配、单位/币种、股权桥、行业适配和敏感性门 | [估值方法论复核](../../docs/research/methodology-assessment.md) |
| Qlib/Lean/vectorbt/PyPortfolioOpt/Riskfolio/yfinance | 未评估、未批准 | 不预装、不作为第一切片设计依据；策略/组合切片前必须独立 research | [研究总表的未批准清单](../../docs/open-source-research.md#明确未批准的后续框架) |

## 4. 产品边界与固定用户故事

### 4.1 用户与样例

- 用户是本地单用户；入口是 `WatchlistItem`，不是 `Position`。
- 固定样例证券是深市 A 股意华股份 `002897.SZ`，交易所时区 `Asia/Shanghai`，币种 CNY。
- 固定请求自然日为 `2026-07-11`；交易日历回退后的有效完整交易日为 `2026-07-10`。两者都必须保存和展示。
- Given 阶段通过公开 facade 在 `2026-07-07` cutoff 上生成既有 `ResearchRun`。7 月 11 日工作流应复用同一研究身份，保留原 cutoff，并说明陈旧 3 个自然日；不得改写成 7 月 10 日研究。
- fixture 不含真实账户、持仓、现金、成本、数量或个人身份。标注、计划规则、金额与风险约束必须标记为 `user_fixture_input`，不得描述为平台建议。
- 7 月 11 日工作流的市场用途 `DataSnapshot` 与旧 ResearchRun 的研究用途 `DataSnapshot` 是两个不同不可变对象；历史页必须同时展示并解释各自 cutoff、purpose 和 membership，不能以“同一次快照”简化关系。

完整裁决见[固定纵向切片用户故事与示例标的](issues/06-fix-slice-user-story-and-security-fixture.md)。

### 4.2 用户可观察主路径

1. 打开本地平台，只读取本地记录，不联网、不自动运行研究。
2. 从观察列表选择意华股份，点击“更新至今天”，明确授权本次联网增量同步。
3. 查看请求日、有效交易日、同步结果、数据限制，以及研究复用/新建的原因。
4. 查看截至有效日的 K 线并创建至少一条标注。
5. 创建或编辑结构化计划草稿。
6. 查看完整内容、引用和版本差异，显式“确认并启用”，形成不可变 v1。
7. 相对确切的 `2026-07-10 MarketSnapshot` 执行只读、确定性的评估。
8. 从历史页回看工作流、快照、研究、标注、计划版本、评估、证据和产物清单。

### 4.3 金融与执行边界

- 平台只重现用户确认的规则是否满足、为什么满足及哪里无法判断；不替用户作交易判断。
- 公共 API、schema、manifest、Web 路由和依赖图中不存在券商连接、订单、委托导出或自动执行能力。
- 规则命中不改变计划状态、不生成数量/价格/订单 payload；计划结束必须由用户显式执行。
- 研究输出继续遵守仓库既有数据门禁和 `data_insufficient_memo` 降级边界。

## 5. 统一领域语义

实现必须直接使用[领域词汇表](../../CONTEXT.md)中的定义。本切片特别锁定以下不可混用关系：

- `Security` 是稳定证券身份；代码和名称进入带有效区间的 identifier history。
- `WatchlistItem` 是关注关系，不是虚拟持仓。
- `Evidence` 是不可变最小引用；`DataSnapshot` 是冻结输入集合；`MarketSnapshot` 是由冻结数据推导的可解释市场状态。
- `ResearchRequest` 是不可变研究意图；`ResearchRun` 是不可覆盖结果；`WorkflowRun` 是更外层的平台执行记录。
- 遗留 `conditional_plan` 迁移语义是 `ResearchReviewItem`，绝不能导入为 `TradePlan` 或 `PlanRule`。
- 未确认内容是 `TradePlanDraft`；首次确认才创建 `TradePlan` 与不可变 `TradePlanVersion`。
- `PlanEvaluation` 配对一个确切计划版本与一个确切市场快照；它不是执行记录。
- `ChartAnnotation` 有稳定身份和 append-only 版本链；删除是 tombstone，不抹除历史。
- `ArtifactManifest` 是不可变目录，不是产物本身或可变文件列表。

## 6. 目标架构与模块边界

### 6.1 运行形态

第一切片采用纯 Python 单进程模块化单体。Codex 位于进程外，负责读取 Skill、选择并调用稳定入口；业务运行时不读取 Skill/prompt，不调用任何 LLM API。

```text
Codex                          Local Web
  |                               |
scripts/platform.py          HTTP/DOM adapter
          \                   /
              ApplicationFacade
              /      |       \
    WorkflowRunner  short commands  query facade
       |        |          |             |
  Provider   Research   Market/Plan   History/Chart
   ports      adapter     services      projection
       \        |          |             /
        SQLite repositories + artifact publisher
                       |
           SQLite + immutable object store
```

`ApplicationFacade` 是唯一应用命令/查询边界。CLI 与 Web 均不得直接访问 Provider、SQLite、repository、`ResearchEngine` 内部函数或以 subprocess 相互调用。

### 6.2 目标代码布局

实施应沿以下边界演进；目录名可以在不改变依赖方向的前提下做机械调整：

```text
src/equity_research/                 # 既有研究深模块，保持公共 seam
src/trading_platform/
  application/                      # facade、命令、查询、DTO、composition root
  domain/                           # Security/watchlist/annotation/plan/market 纯规则
  workflows/                        # registry、runner、node contracts、resume
  data/                             # Provider ports、normalizer、quality、PIT、snapshot
  research/adapter.py               # 唯一平台到 equity_research 的适配点
  market/                           # 市场模型与 metric catalog
  plans/                            # rule AST、plan/evaluation services
  persistence/sqlite/               # repositories、transactions、migration runner
  artifacts/                        # object store、publisher、manifest verifier
  web/                              # loopback HTTP adapter；不持有领域权威
migrations/                         # 不可变顺序 SQL
scripts/platform.py                 # 跨平台维护入口
skills/trading-platform/SKILL.md    # Codex 控制面统一 Skill 入口
web/                                # 本地前端静态资产、chart adapter、锁定依赖
```

依赖方向固定为 adapters -> application -> domain/ports；persistence/provider/research 是 ports 的实现。`src/trading_platform` 只能从 `equity_research` 包根导入批准的公共类型，不得导入 `evidence.py`、`policies.py`、`valuation.py`、`narrative.py` 或 renderer 私有函数。

### 6.3 既有研究 seam 的接入合同

```text
purpose=research DataSnapshot
  -> ResearchInputProjection(research_input_policy@1)
  -> SnapshotToResearchRequestAssembler
  -> ResearchEngine.run(ResearchRequest)  # 最多一次
  -> canonical ResearchRun JSON
  -> derived HTML
  -> research_run_record + artifacts + workflow_run_ref
```

- `DataSnapshot` 必须带 `snapshot_purpose`；daily 的 `workflow/market` snapshot 不能直接冒充旧研究运行的 `research` snapshot。
- `research_input_policy@1` 对候选 snapshot members 做版本化、角色化投影并生成 `research_input_fingerprint`。第一固定 fixture 中，7 月 8—10 日 routine OHLCV extension 只进入市场/计划用途，不改变 7 月 7 日研究输入；新官方披露、财务修订、公司行动冲突、研究显式引用的 metric/source 或 ResearchRequest schema/policy 变化必须令 fingerprint 变化。
- 复用时不组装一个虚假的 7 月 10 日 `ResearchRequest`：工作流只链接原 7 月 7 日 ResearchRun、原 request、原 research snapshot 和 artifacts，同时登记候选新 members、被 policy 排除的 market-only members、policy version、陈旧度与 reason code。
- fingerprint 变化时才构建新的 purpose=research DataSnapshot/ResearchRequest 并调用引擎一次；旧运行不可覆盖。
- assembler 只翻译冻结 research projection、显式 estimate overlay 和 context，不自行计算或复制研究逻辑。每个 financial/evidence member 必须保留 source authority、period/scope、unit/currency/scale、published/available/retrieved、restatement/supersedes、股本稀释与净债务桥所需 identity；缺失或第三方候选不得被升级成 official。
- adapter 的 capability/valuation permission 必须单调不增：相对同一 canonical ResearchRequest 的既有 CLI/core 行为，它只能保持或因新增质量问题降级，不能恢复被官方来源、单位、股本、桥接或方法门禁关闭的权限。
- 输入变化时创建新 `ResearchRun`，旧运行不可覆盖。
- canonical JSON 与 HTML 是两个独立 artifact；HTML 可重渲染，但旧 artifact 不改写。
- 任何研究失败都记录 attempt/diagnostic；不得写入空壳 `ResearchRun`。

## 7. 数据、时间与 Provider 合同

### 7.1 四层数据

| 层 | 权威落点 | 不变量 |
|---|---|---|
| Raw | `<data_root>/objects/sha256/<prefix>/<hash>` + SQLite envelope | 原始 bytes 不可变；相同 hash 复用；保存真实来源和条款 profile |
| Normalized | SQLite version header + dataset-specific typed payload | 逻辑记录稳定，内容修订追加版本；金融主字段不用单个 JSON/EAV 隐藏 |
| Derived | SQLite identity/算法/输入，小型结果 typed，较大序列进 object store | 必须引用冻结 snapshot、算法/参数/因子版本 |
| Artifacts | object store + SQLite artifact/manifest | ResearchRun JSON、HTML、诊断、验收证据分别登记并哈希 |

### 7.2 时间与 PIT

- `event_at`/`period_end`：经济事实时点或期间，不代表当时可见。
- `published_at`：发布者原值，连同 `time_precision` 保存；日期精度不得伪造时刻。
- `available_at`：唯一 PIT admission gate；只有 `available_at <= as_of_at` 才可进入 `DataSnapshot`。
- `retrieved_at`：本机取得时间，只作采集审计。
- cutoff 权威是 UTC `as_of_at`；另存 `market_timezone`、交易日历版本和 `session_date`。
- `availability_basis` 限定为 `publisher_timestamp`、`conservative_next_session`、`market_close_plus_provider_delay`、`documented_provider_schedule`、`retrieved_only`。缺失 basis 的版本不可进入快照。
- `DataSnapshot` 固化 cutoff、`snapshot_purpose`、query/source/freshness policy versions、有序 member IDs、membership hash、质量和 freshness；历史读取不得重新求“当前最佳来源”。purpose 至少区分 `research / workflow / market / chart`，可共享相同 normalized versions，但不能共享或改写身份语义。
- A 股横截面必须使用 cutoff 时冻结的 `market_universe_version` 与有序 members；listing/delisting/ST/market identity 带有效区间与来源版本。今天的 security master 不能回填历史 universe，新上市/已退市 sentinel 必须按 cutoff 正确纳入或排除。

### 7.3 行情、公司行动与复权

- Normalized OHLCV 只保存未复权 canonical 数据和 exact decimal/定点数。
- 公司行动是官方来源的 append-only 版本；第三方因子只作输入或交叉核验。
- `none/forward/backward` 序列属于 Derived，identity 包含 Security、interval、range、adjustment mode、factor-set、input snapshot 和 algorithm version。
- 后续公司行动或因子修订创建新 derived version，不迁移或覆盖旧图、旧标注、旧计划阈值、旧评估。
- 财务更正、重述和会计口径变化必须沿 source revision/supersedes 链追加 normalized version；snapshot builder 按 cutoff 选择当时合法版本。unit、currency、scale、statement scope 或 period 不兼容时不得合并或交给研究 adapter 静默换算。

### 7.4 Provider port

```text
fetch(FetchRequest) -> FetchBatch[RawEnvelope]
normalize(RawEnvelope) -> NormalizedBatch
```

`FetchRequest` 至少包含 provider/adapter version、dataset/endpoint、Security/market、range、canonical params、dataset cursor 与不可逆 `credential_scope_id`。不得含明文 secret。

`RawEnvelope` 至少包含 object hash、真实 source URL、脱敏参数、响应状态和必要 headers、retrieved time、source/terms profile、时间精度。生产与 fixture adapter 实现同一合同，走同一 normalizer/quality/PIT/cursor 路径；fixture adapter 必须硬性禁止联网。

结果状态限定为 `complete / partial / missing / failed / rate_limited`。fallback 成功不得抹除前序 attempt。Provider 不直接写领域表；raw、normalized、quality、artifact 和 cursor advance 由编排事务登记。

### 7.5 缓存、cursor、质量与幂等

- raw request key = provider + adapter version + dataset/endpoint + canonical params + credential scope 的确定性 hash。
- freshness 使用版本化 dataset policy，不设全局 TTL；`force_refresh` 只绕过 freshness 并新增 revalidation attempt。
- 相同 raw hash/object/normalized version 复用；内容变化追加 revision。
- cursor 以 provider + adapter version + dataset + scope + cursor-schema version 标识。只有 complete 或明确支持安全 checkpoint 的 partial batch 才能与数据/质量/object 同事务推进。
- 空响应、rate limit、schema drift、quarantine、blocking、缺 object 都不得推进 cursor；空响应只进入有界 negative cache，不能写零值或“无事件”事实。
- 质量分 `pass / warning / quarantine / blocking`。warning 可进入快照并传播；quarantine 不进入；blocking 终止相关 capability。
- 同级来源无法解释的冲突 fail closed，不平均、不用最后抓取值覆盖。
- offline 模式禁止网络；可回看 cutoff 合法缓存并返回 `stale_by/freshness_basis/last_success_at`，无缓存为 missing。

## 8. SQLite、object store 与 migration 设计

### 8.1 SQLite 运行门

- 第一切片继承当前项目 `requires-python >=3.10`；任何提高最低版本的决定必须先修改 `pyproject.toml`、给出依赖证据并保留既有研究回归。`doctor` 读取实际 Python/SQLite/build identity，拒绝未声明或未验证的组合，不能让运行时隐式选择另一解释器。
- 默认使用本机卷上的 rollback journal、`foreign_keys=ON`、受测 synchronous/busy timeout 和单短 writer。
- `doctor` 只有在精确识别 SQLite 3.51.3 或官方回补修复构建后，才允许显式启用 WAL；当前已审计环境的 SQLite 3.50.4 不满足此门。
- 活跃数据库不得位于 OneDrive、SMB、NAS 或其他网络/同步卷。
- 单 data root 同时只允许一个 mutation/maintenance writer；第二写者返回 `RUNTIME_BUSY` 与当前 run ref。

### 8.2 原子对象发布

固定顺序为：同卷 sibling temp 写入 -> flush/fsync -> SHA-256 -> `os.replace` 到内容地址 -> 短 SQLite 事务登记 object、artifact、manifest、领域引用、node success 和 cursor。

崩溃只允许留下 temp、可回收 orphan 或完整 committed 引用。committed manifest 出现 missing/hash mismatch 时，`doctor/resume` 必须 fail closed。

### 8.3 migration 切分

采用不可变顺序 SQL 和 `schema_migration(version,name,sha256,applied_at,app_version)` ledger。建议按依赖顺序切为：

1. `0001_core_identity_objects.sql`：migration ledger、Security/identifier、watchlist、object/artifact 基础。
2. `0002_provider_normalized_snapshot.sql`：attempt/cursor、normalized record/version、typed dataset payload、质量、snapshot、derived。
3. `0003_workflow_research_manifest.sql`：run/node/attempt/transition/ref、manifest、research_run_record、command receipt。
4. `0004_chart_annotation.sql`：annotation identity/version/link 与 tombstone/history constraints。
5. `0005_market_trade_plan.sql`：draft/version/rule/activation、market snapshot/components、evaluation/evidence。

`command_receipt` 或等价结构为非 workflow 短命令保存 `invocation_id`、command、request fingerprint 和 typed result ref，使 annotation/plan/watchlist mutation 同样具备响应重放幂等性。

迁移必须覆盖空库、N-1 升级、重复执行、hash drift、未知未来版本、date-only precision 保留和失败注入。已有 data root 的迁移先生成并验证 backup、取得 maintenance lock，失败保留旧库并拒绝半升级；禁止删库重建。

### 8.4 最小表责任

第一切片至少需要以下 typed tables；canonical JSON 只作版本化 artifact，不能替代核心字段约束：

- 数据基础：`schema_migration`, `security`, `security_identifier`, `watchlist`, `watchlist_item`, `object_blob`, `artifact`, `artifact_relation`。
- Provider/PIT：`provider_attempt`, `sync_cursor`, `normalized_record`, `normalized_version`, `market_session_version`, `market_universe_version`, `market_universe_member`, `ohlcv_version`, `corporate_action_version`, `filing_version`, `financial_fact_version`, `data_quality_issue`, `data_snapshot`, `data_snapshot_member`, `derived_dataset`, `derived_input`。
- Workflow：`workflow_run`, `workflow_node_run`, `workflow_node_attempt`, `workflow_transition`, `workflow_run_ref`, `artifact_manifest`, `artifact_manifest_member`, `research_run_record`, `command_receipt`。
- 标注：`chart_annotation`, `chart_annotation_version`, `chart_annotation_link`。
- 计划/市场：`trade_plan`, `trade_plan_transition`, `trade_plan_draft`, `trade_plan_version`, `plan_rule`, `plan_rule_condition`, `plan_risk_constraint`, `plan_activation`, `market_snapshot`, `market_snapshot_component`, `plan_evaluation`, `plan_rule_evaluation`, `plan_evaluation_evidence`。

所有版本/attempt/transition/manifest/member/evaluation 历史不可 DELETE 或原地改写。可变 projection 行每次更新必须在同一事务追加历史 transition/audit。

## 9. ApplicationFacade 与工作流合同

### 9.1 维护入口

`scripts/platform.py` 必须真实支持：

| 命令 | 第一切片语义 |
|---|---|
| `bootstrap` | 幂等创建 data root/非秘密配置并执行 migration；不覆盖不兼容数据 |
| `doctor` | 只读检查运行版本、SQLite 门、路径、schema/hash、FK/integrity、object/manifests、配置和 Provider readiness |
| `migrate` | backup-first、独占锁、不可变 SQL migration 和升级后完整性检查 |
| `sync` | 对明确 Security/datasets/cutoff 执行增量或 offline 同步并冻结 DataSnapshot |
| `daily` | 执行 `watchlist_update@1`，生成请求日/有效日、同步、研究、市场和可用计划评估记录 |
| `serve` | 只绑定 `127.0.0.1`，启动不联网、不自动同步；重复启动返回现有地址或 busy |
| `test` | 运行分层测试，保留真实退出码并输出结构化摘要 |
| `backup` | 生成并验证 frozen DB + referenced objects + hash manifest bundle |
| `restore` | 恢复到新 data root，校验后才允许显式切换；永不原地覆盖 |
| `resume --run-id` | 验证旧 definition/checkpoint/hash 后从未提交节点恢复 |

stdout 返回稳定 JSON envelope，至少含 `operation`, `status`, `error_code`, 适用时的 `workflow_run_id`, `artifacts`；失败为非零退出码。用户不需要手工记忆这些命令，由 Codex 或 Web 调用。

### 9.2 公共业务命令

至少暴露以下 typed commands，全部经 facade、使用 invocation id 和 optimistic concurrency：

- 观察项：`add_watchlist_item`, `remove_watchlist_item`。
- 图表标注：`create_annotation`, `revise_annotation`, `delete_annotation`, `restore_annotation`, `migrate_annotation_coordinates`。
- 计划：`create_plan_draft`, `update_plan_draft(expected_revision)`, `discard_plan_draft`, `confirm_plan_draft(expected_revision, activation_mode)`, `activate_plan_version(expected_transition_seq)`, `deactivate_plan`, `end_plan(reason, expected_transition_seq)`。
- 市场/评估：`build_market_snapshot`, `evaluate_plan`。

接口不得接受可执行自由文本公式、Python/SQL/JavaScript/prompt，也不得出现 broker/order/export/execute 命令。

### 9.3 公共查询

至少提供：

- `list_watchlist_items`, `get_security_workspace`；
- `get_sync_status`, `get_research_reuse_decision`, `get_chart_series`；
- `get_annotation_history`；
- `get_current_plan`, `get_plan_draft`, `get_plan_version_diff`；
- `get_market_snapshot_detail`, `get_plan_evaluation_detail`；
- `get_workflow_run`, `get_history_timeline`, `get_artifact_manifest`。

历史查询从结构化 journal、领域版本表和 manifests 投影，不扫描文件夹拼状态。

### 9.4 Workflow registry

registry 是代码内版本化定义，不是 prompt、用户 YAML 或在线插件。第一切片注册：

```text
sync_security_snapshot@1:
  resolve_effective_session
  -> sync_required_datasets
  -> build_data_snapshot

watchlist_update@1:
  resolve_effective_session
  -> sync_required_datasets
  -> build_data_snapshot
  -> decide_research_reuse
  -> run_or_link_research
  -> build_market_snapshot
  -> evaluate_confirmed_plans
  -> publish_run_manifest
```

图表读取、标注编辑、计划草稿和确认是短 application commands，不让一个 `WorkflowRun` 跨越用户思考时间。完整八步旅程由多个短命令/运行通过 typed refs 串联。

每个 node 声明 node/version、typed input/output schema、precondition、required/optional、cache/retry policy、稳定 failure codes。fingerprint 包含 workflow/node version、canonical typed input、snapshot membership、provider/normalizer/source/freshness/query-policy versions、相关配置和确定性代码身份；排除 wall clock、run/attempt ID、绝对路径、秘密和纯展示选项。

所有 fingerprint 使用同一版本化 canonicalization contract：UTF-8、稳定字段/成员排序、UTC instant、保留 source date precision、exact decimal 字符串、显式 null/enum、禁止 binary float 和 locale-dependent 格式。canonicalization version 自身进入 hash；版本变化不能复用旧 cache，必须生成并列结果。

## 10. WorkflowRun、恢复 journal 与 ArtifactManifest

### 10.1 身份和状态

- 每次明确执行生成唯一、非内容寻址 `WorkflowRun`，另存 request fingerprint。
- 同一 `invocation_id` 的双击、重放或响应丢失重试返回原 run；新 invocation 创建新 run，即使输入相同。
- run 状态：`queued / running / succeeded / succeeded_with_limits / failed / cancelled`。
- node 状态：`pending / running / succeeded / skipped / blocked / failed`。
- attempt 结果：`succeeded / reused / failed / abandoned`。
- `skipped` 必须有 typed precondition reason；受治理的缺失/陈旧可以是带 limits 的成功，契约/hash/PIT/schema/identity/persistence 不变量破坏才是 failed。

状态 projection 可以推进，但每次推进必须同事务追加 `workflow_transition`；attempt/transition 永不改写或删除。

### 10.2 Checkpoint 与 manifest

- 每个成功或复用 node 产生不可变 checkpoint manifest；终态产生完整 run manifest。
- manifest identity 由有序成员、角色、方向、producer、media/schema/hash 决定。
- 失败 attempt 可发布脱敏 diagnostic artifact，但不能产生成功 checkpoint。
- `ResearchRun` 通过 `research_run_record` 登记其 request fingerprint、DataSnapshot、engine/schema/code identity、原始 cutoff/status、canonical JSON 与 HTML artifacts。

### 10.3 Resume、重试与取消

- running run/attempt 使用 owner token、lease expiry 和 heartbeat。
- `resume` 取得 lease，将过期 attempt 标为 abandoned，再逐节点验证 workflow/node/schema/fingerprint 和 object hashes。
- 合法 checkpoint 的 succeeded/reused node 不重算；未提交节点创建递增 attempt。
- 旧 node version 不可用、checkpoint 损坏或 hash mismatch 时原 run fail closed；只能创建显式关联的新 run，禁止半程换代码。
- 网络超时、rate limit、SQLite busy 可按有界策略重试；schema drift、PIT/质量 blocking、未知版本和领域不变量不可重试。
- cancel 只在节点事务边界生效，不回滚已提交历史。

### 10.4 可复现 code/config identity

每个 WorkflowRun、ResearchRun record、derived dataset、MarketSnapshot、PlanEvaluation 和 acceptance manifest 必须引用结构化 `code_identity`：

- Git commit；若 worktree dirty，另存受控 tracked/untracked source tree hash 或规范化 diff hash，不能只写 `dirty=true`；
- Python package/build metadata、Python/npm lockfile hashes、migration set hash、workflow registry hash、metric/model/evaluator/policy hashes；
- 前端静态 bundle hash和第三方 dependency/license inventory hash；
- 脱敏 config hash，只含影响确定性行为的非秘密字段；secret 只以不可逆 credential scope 标识。

所有算法继续使用确定性代码。没有随机性的运行显式记录 `random_seed=null` 与 `determinism_basis=deterministic`；未来若某节点使用随机性，seed 必须是 typed input、进入 fingerprint/manifest，并由重跑测试证明一致。

## 11. K 线与 ChartAnnotation

### 11.1 UI 方向

正式页面采用[原型化 K 线与持久化标注 seam](issues/09-prototype-chart-and-annotation-seam.md)的 HITL 结论：B“画布优先驾驶舱”为默认及全屏共用视图，C 的不可变版本账本作为可收起侧栏；A 的持续 provenance 控制台不进入主视图。原型及验证见[原型说明](prototypes/chart-annotation-prototype/README.md)和[验证记录](prototypes/chart-annotation-prototype/VALIDATION.md)。

默认主视图只常驻 Security、interval、adjustment mode、有效截止日和当前任务动作。完整 source、snapshot/factor identity、provider attempt、hash 与质量明细放入“数据详情/证据/历史”。真正影响能力的 missing、blocking stale、冲突或无法迁移必须在图表附近显示可处理 banner。

### 11.2 Chart adapter

- 锁定 `klinecharts@10.0.0` 和 package integrity，离线打包、不依赖 CDN。
- chart adapter 只做 `DTO -> overlay` 和图库事件 -> validated domain command。
- 不持久化 pixel、array index、runtime overlay id、回调、Canvas 或图库序列化对象。
- 默认与全屏复用同一 chart component、selection、adapter 和 annotation state。
- 绘制必须清楚呈现起点、终点、最终确认和持久化反馈。

### 11.3 标注版本 DTO

每个 `ChartAnnotationVersion` 至少保存：

- 稳定 `annotation_id`、version id/no、`supersedes_version_id`、`status=active|deleted`；
- `security_id`, interval, adjustment mode, `data_snapshot_id`, 可选 factor snapshot/ref；
- 一个或多个市场 timestamp + exact decimal price anchor；
- 白名单 annotation kind/style、作者、创建时间；
- ResearchRun/Evidence/TradePlanVersion/事件的 typed links。

创建为 v1；修改追加版本；删除追加 tombstone；恢复再追加 active 版本。刷新页面、关闭 facade、重启 server 后坐标和引用必须一致。

跨周期/复权/公司行动坐标只有在目标 derived snapshot、factor version 和确定性映射均存在时才允许生成新版本。无交易日 anchor、bucket 不唯一、因子修订或无法唯一反算时返回 `unresolved_requires_confirmation`，保留旧坐标，禁止静默吸附。

## 12. TradePlan 状态机与规则合同

### 12.1 草稿、版本与生命周期

```text
TradePlanDraft(open, revision N)
        | confirm
        v
TradePlan + immutable TradePlanVersion
        | explicit activation history
        v
inactive <-> active -> ended
                       cancelled | invalidated | completed
```

- 首次确认才创建 `TradePlan` 和 v1。一个计划最多一个 open draft，引用 `based_on_version_id`。
- `TradePlanVersion` 是完整不可变内容；`plan_activation` 保存生效区间，同一计划同一时点最多一个 active version。
- “确认并启用”是原子动作，但确认和启用分别有审计语义。
- active v1 上创建 v2 草稿时，daily 仍评估 v1；v2 只有确认并启用成功后才原子切换。
- `ended` 是终态且不可复活；需要继续时复制内容形成新 draft，并在确认时创建新的 `TradePlan` identity。
- `triggered` 不是计划状态；任何评估结果都不能自动 activate/deactivate/end。

### 12.2 版本内容

确认版本至少固定 Security、version/baseline、`user_input_source`、ResearchRun/Evidence/DataSnapshot refs、期限与 `review_by`、规则全集、CNY exact risk constraints、market gate policy、metric/evaluator policy versions、确认记录和 canonical content hash。

第一切片没有 Position/账户；风险预算只支持用户/fixture 输入的 `max_planned_notional`、`max_planned_loss` 等绝对约束。依赖实际持仓、成本或组合净值的规则返回 `not_applicable` 或 `unable_to_determine`，不得用零值替代。

确认时必须校验所有金额为有限、非负 exact decimal，币种与计划一致，`max_planned_loss <= max_planned_notional`，期限/review_by 有序且不以隐含 wall clock 解释。若缺少 Position/account，UI 和 artifact 必须明确写“未验证组合可行性”；流动性、集中度、相关性、尾部风险和真实可执行仓位不得由该绝对约束推断。任何依赖这些输入的规则只能 `not_applicable/unknown`，不能恢复为通过。

### 12.3 PlanRule AST

`rule_kind` 最小集合：`entry_review`, `adjustment_review`, `exit_review`, `invalidation`, `risk_limit`, `market_gate`, `observation`。

`effect` 最小集合：`prompt_review`, `mark_invalidation_candidate`, `mark_risk_limit_breach`, `block_user_intent`, `observe`，并以 `applies_to=entry|increase|decrease|exit|plan` 限定范围。

条件是版本化 typed AST：

- 叶子只能引用 metric catalog 中有类型、单位和时间语义的 `metric_ref`；
- 运算符白名单为 `eq/ne/lt/lte/gt/gte/between/crosses_above/crosses_below/changed_to`；
- 组合只允许 `all/any/not`；
- 常量为 exact decimal、受控 enum、日期或 bool，并显式单位/币种/窗口/current/previous complete session；
- 叶子结果为 `true/false/unknown/blocked/not_applicable`，按保守多值逻辑传播；missing/conflict 不得当作 false。

绝对价格阈值以 canonical 未复权 CNY exact decimal 保存。从复权图创建时必须保存 factor-set 反算证据；无法唯一反算、单位不匹配或公司行动冲突时禁止确认。

## 13. MarketSnapshot 与 PlanEvaluation

### 13.1 MarketSnapshot 输入与身份

```text
build_market_snapshot(
  security_id,
  market_scope_id,
  requested_at,
  effective_session_date,
  data_snapshot_id,
  market_model_id/version,
  freshness_policy_version
) -> immutable MarketSnapshot
```

服务只能消费指定 `DataSnapshot`，不得读取“最新数据”。identity/fingerprint 由 canonical 输入、模型/代码身份和有序组件 hash 决定；相同输入复用。

### 13.2 A 股首切片透明组件

不输出黑箱总分。固定 `CN_A_SHARE` universe 和 `000300.SH` benchmark，保存原值、分类、窗口、样本数、剔除原因和 evidence refs：

| 组件 | 确定性定义 |
|---|---|
| `market.trend` | benchmark close 同时高于 SMA20/SMA60 且 SMA20 五日斜率向上为 `up`；同时低于且斜率向下为 `down`；其余 `mixed` |
| `market.breadth` | cutoff 的冻结 A 股 universe 中排除停牌或少于 20 合法 session 的结构性不适用成员；上涨占比和高于 SMA20 占比均 >=60% 为 `broad`，均 <=40% 为 `narrow`，其余 `mixed` |
| `market.liquidity` | cutoff universe 的全市场成交额相对不含当日的前 252 完整 session percentile，至少 120 样本；70/30 分位为 `ample/normal/thin` |
| `market.volatility` | benchmark 日对数收益 20 日、`sqrt(252)` 年化波动率，相对不含当日的前 252 滚动观测 percentile，至少 120 样本；80/20 分位为 `high/normal/low` |

另保存 `security.price_context`：未复权 close、日变化、SMA20/SMA60、完整 session、停牌/涨跌停和公司行动冲突事实。宏观、资金、新闻、情绪、相关性/拥挤度和行业轮动标记 `unsupported_in_first_slice`，不得填成中性。

`market.breadth` 和 `market.liquidity` 的 coverage gate 是 fail-closed：cutoff universe membership 必须 100% 可解释；停牌、上市不足 20 个合法 session 等只有在 PIT 数据可证明时才是结构性排除。Provider missing、schema drift、quarantine 或无来源的缺行不能当作排除；任一非结构性缺口都令相应组件无分类值并为 blocked。全市场成交额也必须覆盖所有当日应交易且非合法停牌成员，否则 liquidity blocked。每个组件保存 expected/eligible/excluded/missing counts 与有序 exclusion reason refs。

快照状态为 `complete / limited / blocked`。PIT/hash/identity 失败、关键 OHLCV/日历陈旧或缺失、公司行动冲突、被规则引用的关键 metric 不可用时 blocked；未引用的可选组件缺失或明确 unsupported 时可 limited。请求在盘中/非交易日只使用最近完整 session，并同时保留 requested/effective date。

### 13.3 PlanEvaluation

```text
evaluate_plan(
  plan_version_id,
  market_snapshot_id,
  evaluator_id/version,
  evaluation_policy_version
) -> immutable PlanEvaluation
```

上述四项构成领域幂等键。WorkflowRun、trigger、wall clock 和 UI 选项不进入键。数据修订、新计划版本、新 evaluator/policy 产生并列新结果，旧结果不覆盖。

结果三轴：

- execution `status=completed|blocked`；
- `outcome=triggered|not_triggered|unable_to_determine`，blocked 时无 outcome；
- `completeness=complete|partial`。

每条规则保存 `triggered/not_triggered/unable_to_determine/blocked/not_applicable`、reason code、actual operands、单位、观测时点、effect/applies_to 和 evidence refs。至少一条确定触发则总体 triggered 并可为 partial；无触发但 unknown 可能改变结论则 unable；全部适用规则确定 false 才是 not_triggered。blocked 不被其他触发覆盖。

首切片 reason-code family 至少包括：`CONDITION_TRUE`, `CONDITION_FALSE`, `INPUT_MISSING`, `INPUT_STALE`, `INPUT_CONFLICTED`, `QUALITY_BLOCKING`, `UNIT_OR_BASIS_MISMATCH`, `SNAPSHOT_SCOPE_MISMATCH`, `RULE_NOT_APPLICABLE`, `PLAN_REVIEW_OVERDUE`, `PLAN_EXPIRED`, `MARKET_CONSTRAINT_MATCHED`, `USER_GATE_MATCHED`, `INVARIANT_VIOLATION`。

## 14. Web 与产品交互合同

- 本地服务只绑定 loopback；启动/打开不隐式联网。
- loopback 不是身份边界。server 启动生成高熵本地会话凭据，凭据不放 URL、日志或持久化 artifact；Host 只允许精确配置的 `127.0.0.1/localhost` 与端口，拒绝未知 Host/DNS rebinding。mutation 禁止 GET，要求同源 Origin/Referer、CSRF token 与受控 content type；cookie 若使用必须 `HttpOnly + SameSite=Strict`，并按实际能力设置 `Secure`。
- 所有静态资源本地打包，默认 CSP 至少 `default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`，并按最小能力收紧 script/style/connect。禁止 CDN、外部字体、遥测和第三方 analytics；live Provider 网络只发生在服务端 allowlist adapter，不暴露 secret 给浏览器。
- annotation label、计划文本、source title/URL、Provider error 和 artifact preview 一律按文本/typed URL 处理并自动转义；禁止未经 sanitizer 的 HTML/Markdown 注入。API 设置请求体、字符串、数组和上传大小上限，拒绝控制字符、路径型输入和超长 payload。
- canonical ResearchRun HTML 或其他主动内容不得在持有本地会话凭据的 privileged app origin 中直接执行。第一切片默认作为下载/独立文件打开；若提供预览，只能使用无 `allow-scripts/allow-same-origin` 的 sandboxed opaque-origin iframe 或等价隔离，并由 canonical JSON 在主应用内安全渲染摘要。
- 默认首页先显示观察项、数据日期与真正影响能力的陈旧/阻断信息，不展示系统流水线墙。
- Security 工作区优先回答“发生了什么变化、与什么相比、为什么重要、哪些用户规则命中、哪里不确定、下一步需要复核什么”。
- 正常 provenance、hash、版本、节点和 Provider attempt 通过“数据详情/证据/历史”渐进披露。
- 计划编辑按“依据与期限、规则、风险预算、市场门控”组织；确认页优先显示相对上一版本 diff、引用、`user_input` 和“不会执行交易”的边界。
- blocked/partial 状态必须使用用户语言说明发生了什么、当前仍可做什么和缺少什么，不能只显示内部 error code。
- 默认/全屏/历史复用同一领域状态和组件 seam。
- 必须验证键盘、焦点、对比度、缩放文字、非颜色单一编码、目标窗口宽度与 `prefers-reduced-motion`。
- Web transport 只是一层可替换 adapter：无论选用何种 HTTP library，都必须固定版本、离线安装、映射同一 facade DTO/error contract，并通过 Host/Origin/CSRF/CSP/XSS/size-limit 测试；框架选择不得改变领域或成为第二套业务 seam。

设计完成门继承[总任务 Prompt 的七项设计验收](../../docs/prompts/trading_platform_codex_prompt_optimized.md#4-设计验收门)，并由浏览器 E2E 在真实页面而非静态稿上验证。

## 15. 失败、降级与安全矩阵

| 情形 | 必须结果 |
|---|---|
| 断网且存在 cutoff 合法缓存 | 允许历史读取；显示 freshness。若不满足当日能力则 MarketSnapshot/评估受阻 |
| 断网且无缓存 | `missing`；不造假、不偷偷联网、不生成完整当日快照 |
| Provider HTTP 200 空 payload | 有界 negative cache/error；不写零值、不删除旧数据、不推进 cursor |
| rate limit/网络超时 | 记录 attempt，尊重 `Retry-After`，有界重试；fallback 不抹除失败 |
| schema drift/非法 OHLC/单位或身份冲突 | quarantine/blocking；相关 capability fail closed |
| `available_at > as_of_at` | 泄漏 sentinel 永不进入 DataSnapshot |
| 官方修订 | 新 raw/version/snapshot；修订前 cutoff 仍解析旧版本 |
| 公司行动改变复权历史 | 新 factor/derived；旧图、标注、阈值和评估不变 |
| stale research input | 可明确复用旧 ResearchRun 并显示原 cutoff/陈旧原因；不得改写 |
| stale canonical OHLCV | 历史回看可用；新的当日 MarketSnapshot/正常评估 blocked |
| 计划规则输入缺失 | 按是否破坏完整性形成 partial/unknown 或 blocked；不按 false |
| invalidation 规则命中 | 只标记候选；计划保持 active，直到用户显式结束 |
| 进程在 object/DB/cursor/node 边界崩溃 | resume 后仅有 temp/orphan 或完整 committed 引用；无半 cursor/重复版本 |
| 明文 secret/个人绝对路径进入日志或 artifact | 阻断失败；只允许不可逆 credential scope 和脱敏摘要 |
| 业务 import graph 出现 LLM SDK/prompt/Skill 或交易执行 surface | 阻断失败 |
| 当前 security master 回填历史 universe | survivor/leakage sentinel 失败；不得生成 breadth/liquidity 分类 |
| 横截面只有部分证券或成交额缺行 | provider missing 不能算结构性排除；相应市场组件 blocked |
| 研究 adapter 改变 unit/currency/scale 或把第三方候选升级为 official | adapter equivalence/permission monotonicity 失败，ResearchRun 不得发布 |
| dirty worktree 变化但 code identity 未变化 | 阻断复用与验收；必须生成新的 source/diff hash |
| Web Host/Origin/CSRF 不合法或文本含脚本 payload | 请求拒绝且无 mutation；渲染只显示转义文本 |
| restore/对象路径含绝对路径、`..`、symlink、hardlink 或 reparse point | 解包/恢复拒绝，不得在新 root 外创建或覆盖任何对象 |

## 16. Windows 运维、备份与恢复

- `bootstrap` 默认创建用户本地 data root、SQLite 文件、`objects/sha256/`、非秘密配置和锁文件；不得把运行数据写入 Git 工作树。
- secret 只从进程环境或可替换的 OS credential adapter 注入；默认不创建明文 `.env`，数据库、非秘密配置、backup 和 restore report 只保存 `credential_scope_id/configured|missing`。`doctor` 不回显值。
- Web 使用进程内串行 mutation queue；跨进程使用 data-root scoped OS lock + DB lease。网络等待期间不保持 SQLite 长事务。
- `migrate`、restore switch 和改变 schema/root 的 bootstrap 步骤取得 exclusive maintenance lock，并要求没有活跃 server/workflow。
- backup 是用户/Codex 指定目标目录中的 timestamped immutable bundle，包含 SQLite online frozen backup、冻结副本引用的全部 objects、版本化 `backup_manifest.json`、schema/app/config-safe versions 和逐项 SHA-256。
- 目标位于 live data root 内直接拒绝；同卷给出灾难隔离告警。
- restore 永不覆盖活跃 root：恢复到新 root，校验 hash、SQLite integrity/FK/schema/domain、journal/artifact refs、最小查询，生成不可变 restore report 后才允许显式切换。
- backup/restore 对所有输入执行 canonical path containment；bundle member 只能使用版本化 manifest 允许的相对路径和 hash-derived object path，拒绝绝对路径、上跳、ADS、symlink/hardlink/junction/reparse point、大小/数量越界与 hash/path 不匹配，防止 zip-slip 和链接逃逸。
- 第一切片不自动上传云端、不自动轮换/删除、不自建加密密钥管理。敏感备份依赖用户控制的受限目录及 BitLocker 或等价加密卷，`doctor` 明确提示。

## 17. 验收合同与逐条 Acceptance Criteria

权威最高层 seam 是：由生产 composition root 创建真实 `ApplicationFacade`，在新 data root 上只使用公开命令/查询完成旅程，再通过 query facade、journal、manifests 和 `doctor` 验证关系图。测试可替换固定时钟、data root 和同合同 fixture Provider，但不得 mock facade 内部 workflow、repositories、研究内核、SQLite 或 object store。详见[决定纵向切片最高层验收 seam](issues/11-decide-vertical-slice-acceptance-seam.md)。

### 17.1 固定 acceptance fixture

fixture pack 必须包含真实、可追溯且可合法保存/回放的：Security identity、交易日历、截至 2026-07-10 的未复权 OHLCV、公司行动/因子输入、四组件市场所需 PIT universe/benchmark 数据、截至 2026-07-07 的官方披露和研究输入，以及 source/license/time/adapter/schema/policy/hash manifest。fixture loader 只提供 raw envelope，不直接写领域表或预造 run。

每个 fixture member 的权利 profile 分别记录 `local_storage_allowed / deterministic_replay_allowed / repository_redistribution_allowed / packaged_distribution_allowed`、证据/条款版本和复核日期。可本地回放不等于可提交 Git 或随包分发；后两项没有明确许可时，raw 只留在用户本地 ignored pack，仓库保存脱敏 manifest/hash 和确定性导入说明。验收可以在该本机通过，但分发资格必须单列 `external_blocked`，不能伪装成可再发布 fixture。

### 17.2 Golden journey

- **AC-001**：空 data root 上 `bootstrap/migrate` 成功；重复执行幂等，不删库或重建历史。
- **AC-002**：通过公开命令创建 `WatchlistItem`，重启 composition root 后仍可通过 query 读取稳定 identity。
- **AC-003**：通过公开 workflow 在 2026-07-07 cutoff 生成真实 canonical `ResearchRun`，不直接 seed 结果。
- **AC-004**：启动/打开/serve 本身零外连；只有“更新至今天”授权 online sync。
- **AC-005**：更新保存 requested date `2026-07-11` 与 effective session `2026-07-10`，并引用交易日历版本。
- **AC-006**：同步记录所有 Provider attempts、cache disposition、raw hashes、cursor、质量和 source/terms profile。
- **AC-007**：`DataSnapshot` 只含 cutoff 合法成员，membership hash 可重算，未复权/单位/币种/time basis 明确。
- **AC-008**：7 月 11 日工作流复用同一 7 月 7 日 `ResearchRun` identity、request/snapshot/artifact hashes，记录 `reused` reason 和 3 日陈旧说明；不调用研究引擎、不复制报告、不改 cutoff。
- **AC-009**：查询返回截至 7 月 10 日的版本化日 K 线，带 adjustment mode、snapshot/factor refs 和 freshness。
- **AC-010**：公开 annotation command 创建 v1；关闭并重建 facade 后 identity、timestamp、exact price、interval、adjustment 和 refs 完全一致。
- **AC-011**：公开命令创建 `user_fixture_input` 计划草稿，确认页/结果展示完整内容、引用、diff、hash 和不会执行交易的边界。
- **AC-012**：“确认并启用”原子创建 `TradePlan`, v1, activation 与 transition；失败时不留下半版本或半激活。
- **AC-013**：`PlanEvaluation` 精确引用 active v1 与 `2026-07-10 MarketSnapshot`，逐条保存 operands、reason codes、effects 和 evidence refs。
- **AC-014**：评估只产生复核/限制/失效候选，不改变计划生命周期，不产生任何交易副作用。
- **AC-015**：历史 timeline 可从 WorkflowRun 通过公开查询遍历 DataSnapshot、ResearchRun、ChartAnnotationVersion、TradePlanVersion、MarketSnapshot、PlanEvaluation 与 ArtifactManifest，并区分 created/reused。
- **AC-016**：`doctor` 验证 schema ledger/hash、SQLite/FK/integrity、domain invariants、object hashes、manifest membership 和全部 refs。

### 17.3 强制反例与不变量

- **AC-017**：同一 invocation 重放返回同一 run；新 invocation 生成新 run/attempt，但复用相同 raw/normalized/snapshot/research/market/evaluation，不重复推进 cursor或新增领域版本。
- **AC-018**：offline valid/stale/missing 三场景分别得到正确能力；stale/missing 不伪装完整当日快照或正常评估，历史仍可回看。
- **AC-019**：带未来 `available_at` 的 sentinel 被 PIT builder 拒绝；此测试只声明首切片 PIT 门，不冒充完整 backtest 反前视。
- **AC-020**：Provider contract 覆盖字段、精度、单位/币种、未复权、partial/empty/rate-limit、cursor、provenance 和同 raw 同 normalizer/quality path。
- **AC-021**：官方/Provider 修订产生新 raw/version/snapshot/market/evaluation；旧成员和结果按原 hash 仍可回放。
- **AC-022**：v2 草稿未确认时 daily 继续评估 v1；v2 确认并启用后原子切换，v1 hash/content/activation/旧评估不变。
- **AC-023**：ended 计划不可复活；复制内容后确认创建新 plan identity。
- **AC-024**：标注修改、tombstone、恢复均追加版本；跨周期/复权/公司行动不能唯一映射时 fail closed，旧坐标不漂移。
- **AC-025**：停牌、涨跌停、market gate 与 exit/invalidation/risk 结果并列显示；不合成为系统动作或改变状态。
- **AC-026**：复权价格不能确定性反算时计划规则不能确认；因子修订不改写旧阈值。
- **AC-027**：temp write、rename、DB/cursor/node/final-manifest commit 边界的 crash injection 后，`resume` 使 attempt 单调增加、合法 checkpoint 不重算、无半 cursor/missing object/重复领域记录。
- **AC-028**：stale lease 第二 owner 被拒绝；旧 node version 不可用、artifact 损坏和不可重试错误均 fail closed。
- **AC-029**：migration suite 覆盖空库、N-1、重复、hash drift、未来版本、date-only precision、失败保留旧库；禁止删库重建。
- **AC-030**：真实 Windows subprocess 完成 `backup -> restore 新 root -> doctor -> serve/query history`，逐项验证 hashes 和关系，restore 不覆盖 live root。

### 17.4 Web、架构与回归

- **AC-031**：一条薄但完整 browser E2E 覆盖 B 画布优先工作台、更新授权、研究复用说明、K 线/标注、计划确认、评估、历史跳转、reload 和 server restart。
- **AC-032**：browser E2E 验证 blocking banner、版本侧栏、渐进披露、键盘/焦点、目标宽度、reduced motion 和非颜色单一编码。
- **AC-033**：九项维护入口和 `resume` 在 Windows 输出稳定 JSON/退出码并正确执行锁语义；不得以 no-op 通过。
- **AC-034**：现有 35 项测试原样通过；platform-to-research integration 证明只调用一次公共 `ResearchEngine.run` seam，canonical 输出与独立 CLI 对同输入一致。
- **AC-035**：architecture test 禁止平台模块导入研究内部实现；禁止生产依赖/import/resource/public surface 中出现 Skill/prompt/LLM 或交易执行能力。
- **AC-036**：离线旅程 network spy 为零外连；live 模式只允许配置的 Provider destinations；所有 secret 和个人路径脱敏。
- **AC-037**：fixture 所有计划阈值/金额/规则均标记 `user_fixture_input`，页面与 artifact 不把它们写成平台建议。
- **AC-038**：生成不可变 machine-readable acceptance evidence manifest，记录 suite/version/environment/code/fixture hashes、每项结果、artifact refs、doctor/browser/backup/legacy evidence 和独立 live qualification 状态。
- **AC-039**：research adapter 对同一 7 月 7 日 canonical request 与既有 CLI/core 输出保持 schema/hash/capability/valuation permission 等价；千元/元、币种、期间、scope、重述、稀释股本、净债务或 source authority 变异会 fail closed，权限不得单调增加。
- **AC-040**：7 月 11 日 history 同时保存 7 月 10 日 workflow/market snapshot 和 7 月 7 日 research snapshot；`research_input_policy@1` 记录候选、market-only 排除与 reason，复用时不构造伪 7 月 10 日 ResearchRequest。
- **AC-041**：PIT universe sentinel 证明后来上市证券不会提前出现、后来退市证券不会从历史消失；universe/member/source-policy identity 进入 MarketSnapshot fingerprint。
- **AC-042**：breadth/liquidity 只有在 universe 100% 可解释且所有非结构性排除成员数据完整时分类；任一 provider missing/quarantine/成交额缺行使相应组件 blocked，并保存 expected/eligible/excluded/missing counts。
- **AC-043**：计划确认拒绝负数、非有限值、币种不匹配、`max_planned_loss > max_planned_notional` 与无效期限；无 Position/account 时组合可行性和相关规则明确 `not_applicable/unknown`。
- **AC-044**：相同 commit 的 dirty source 改变会改变 `code_identity`；canonicalization/lock/migration/workflow/frontend/config hash 可重算。确定性节点记录 `random_seed=null`，不得因 locale、字段顺序或等价 decimal/time 编码改变 identity。
- **AC-045**：恶意 Host/DNS rebinding、跨源 mutation、缺 CSRF、GET mutation、错误 content type、超大 payload 与脚本型 annotation/source/error/report artifact 全部被拒绝、转义或以无脚本/同源权限的 sandbox 隔离；无状态改变、无 session/secret/绝对路径泄漏，CSP/无外部资源成立。
- **AC-046**：Python/npm lock 与 package integrity 可重算，生成 dependency/license inventory 和适用的 `THIRD_PARTY_NOTICES`/LICENSE/NOTICE/页面归属；离线 build/runtime 无 CDN、遥测或自动安装。
- **AC-047**：restore bundle 的绝对路径、`..`、ADS、symlink/hardlink/junction/reparse、hash/path mismatch、大小/数量炸弹全部被拒绝，测试证明新 root 外没有文件变化。
- **AC-048**：`skills/trading-platform/SKILL.md` 能由 Codex 选择并调用 bootstrap/doctor/migrate/sync/daily/serve/test/backup/restore/resume，用户不拼零散命令；业务 wheel/import graph 不包含该 Skill 或 prompt。
- **AC-049**：迟到公告、官方更正、用户 rationale 修改或 evaluator 升级只生成并列新 snapshot/run/version/evaluation；历史页仍从冻结 refs、当时 policy/reason/operands/artifacts 渲染旧解释，禁止用当前 policy 重算旧历史。
- **AC-050**：acceptance applicability ledger 对总任务强制测试逐项给出 `passed/failed/not_applicable/external_blocked`。既有估值公式回归与 adapter 金融不变量必须 passed；Position 会计、完整回测成交/费用/T+1 因 Watchlist/no-account/no-execution 明确 `not_applicable`，附理由且 `long_term_platform_complete=false`，不得伪造能力。
- **AC-051**：fixture 权利 profile 逐成员区分本地保存、回放、Git 再分发和打包分发；未授权 raw 不进入 Git/发布包，分发资格为 `external_blocked`，同时本机 hash/replay acceptance 仍可独立验证。

只有 AC-001 至 AC-051 的本地确定性阻断项全部通过，且失败项没有被 skip/xfail，才允许 `slice_acceptance=passed`。其中 `not_applicable` 只能用于 Spec 明确排除且有反能力测试的长期项，不能用于逃避本切片范围内的失败。

## 18. 测试分层

| 层 | 责任 |
|---|---|
| Domain/unit | PIT admission、freshness、交易日回退、exact decimal/单位、市场四组件/coverage、计划 AST/多值传播/风险输入、复权坐标映射、canonical hash |
| Provider contract | fixture/生产 adapter 的字段、时间、未复权、PIT universe、状态、cursor、raw/provenance、权利 profile 和失败语义 |
| Persistence/migration | schema、append-only versions、原子 object publish、单 writer、N-1、failure rollback |
| Application acceptance | Golden journey、幂等缓存、研究复用、断网陈旧、计划不可变、标注重启、评估和 history graph |
| Fault/recovery | lease、retryability、crash injection、resume、checkpoint/cursor/manifest 原子性 |
| Browser E2E | 用户主路径、B 工作台、异常表达、版本侧栏、可访问性和 server restart |
| Maintenance/Windows E2E | 入口 JSON/退出码/锁、rollback-journal writer、backup/restore/doctor/serve |
| Architecture/security | import/dependency/resource/public-surface denylist、network allowlist、Host/Origin/CSRF/CSP/XSS/path safety、secret redaction、license inventory、无 LLM/执行能力 |
| Legacy regression | 原有 35 项、估值 worked examples 及 platform-to-research unit/currency/source/capability 一致性 |

本切片以非交易日回退、停牌和涨跌停覆盖目标市场规则，不虚构 T+1 成交或回测能力。未来策略/回测切片仍需单独实现信号时点、成交时点、费用、滑点和完整反前视套件。

## 19. 实现顺序与提交边界

实现按可回滚 tracer slices 推进，每一步保持既有研究 MVP 测试通过：

1. **保护 seam、证据与 composition skeleton**：冻结 35 项回归和估值 worked examples，固定 `docs/open-source-research.md`/依赖许可门，增加 architecture boundary test，建立 `trading_platform` package、facade DTO、canonical/code identity 和公开研究 adapter contract，但不复制研究代码。
2. **持久化基础**：实现 data root、object store、migration runner、`0001`；完成原子发布与 doctor 基础检查。
3. **Provider/PIT 基础与真实 fixture pack**：实现 `0002`、fixture rights、PIT universe、normalizer/quality/cursor/purpose-scoped snapshot；先通过 leakage/修订/coverage/offline/幂等测试，再接生产 adapter。
4. **Workflow/journal/research reuse**：实现 `0003`、registry/runner/manifest/resume、`research_input_policy@1`、snapshot-to-request assembler 与 research record；完成 7 月 7 日生成和 7 月 11 日双 snapshot 复用路径及 adapter permission monotonicity。
5. **观察项与 K 线/标注**：实现 watchlist/query、`0004`、chart read DTO、annotation commands 和 KLineChart adapter；先过 application restart，再过 browser reload/server restart。
6. **市场与计划领域**：先用 unit tests 实现 metric catalog、四组件、typed AST、多值逻辑、draft/version/state/evaluation；再落 `0005` 和 facade commands。
7. **纵向 UI 与历史投影**：先实现 Host/Origin/CSRF/CSP/escaping/size limits，再接通更新授权、研究复用说明、B 工作台/版本侧栏、计划 diff/确认、评估和 as-recorded history timeline；完成设计验收。
8. **运维闭环**：补齐统一 Skill、九项入口、resume、single-writer、backup/restore 新 root、安全路径解包、Windows subprocess、secret/network 和 dependency/license 门禁。
9. **Acceptance evidence**：运行全分层 suite，生成 machine-readable manifest；live qualification 单独执行并如实分类。

每一步只在自身测试通过后推进。schema migration、DTO schema、workflow/node/evaluator version 和 fixture hash 一旦进入验收资产不得无版本修改。

## 20. 明确非目标

- 真实账户、持仓批次、组合会计、现金对账、真实个人风险暴露。
- 券商接入、订单、委托导出、自动下单或模拟真实执行。
- 完整策略实验平台、回测执行引擎、T+1 成交模拟、费用/滑点模型。
- Monte Carlo、完整估值模型扩展、多市场全覆盖。
- 宏观、资金、新闻、社交情绪、拥挤度、行业轮动等完整市场模型。
- 微服务、任务队列、Redis/Celery、运行时 Agent、业务 LLM API。
- DuckDB/Parquet/PostgreSQL，除非后续独立证据满足启用门。
- 自动云备份、自动轮换删除、自建备份加密密钥管理。
- 把 K 线原型代码或 `localStorage` 直接合并为生产实现。
- 重写、复制或绕过现有研究内核。

## 21. 外部资格与已知实施风险

这些项不阻塞 Spec 或 fixture-backed 实施，但限制完成声明：

- 官方披露站点的批量自动化、限流/SLA、保存与再利用边界需要逐 adapter 保存条款 profile；明确禁止时必须停用自动 adapter。
- Tushare-compatible gateway 的实际 entitlement、频次和数据许可由 live qualification 记录；其结构化数据不替代官方披露。
- AKShare 上游端点/schema 可漂移，必须固定版本并 fail closed。
- KLineChart 10.0.0 正式采用仍需自动 browser E2E、生命周期/性能、离线 bundle 和许可证归属门；失败时按研究结论切换候选，不在领域层打补丁。
- 当前 checkout 的现有 manifest 没有完整可回放 raw；实施必须建立新的合法、最小、版本化 fixture pack。
- fixture 的本地保存/回放权不自动授予 Git 或打包再分发权；未确认的 raw 只能留在用户本地 ignored pack，分发资格单列外部阻塞。
- Qlib/Lean/vectorbt/PyPortfolioOpt/Riskfolio/yfinance 与完整策略/组合技术栈没有被本 Spec 批准；后续相关切片前必须独立调研，不能沿用第一切片的 `not_applicable` 越过门禁。
- live qualification 为 `external_blocked` 时可交付通过的本地 fixture 闭环，但不得声称真实生产同步通过或长期平台完成。

## 22. Acceptance evidence manifest 最小字段

最终 manifest 至少记录：

```text
acceptance_schema_version
slice_spec_version
workflow/node/evaluator/model/policy versions
canonicalization_version
code_identity: commit + dirty source/diff hash + package/lock/migration/workflow/frontend hashes
config_safe_hash + credential_scope_ids
os/python/sqlite versions
fixture_pack_id + source/license profile + member hashes
fixed_clock + network_policy
suites[]: name/version/status(passed|failed|not_applicable|external_blocked)/rationale/start/end/failure_code/artifact_refs
golden_entities[]: typed identity + created/reused disposition
random_seed + determinism_basis
dependency_license_inventory_ref + third_party_notices_ref
applicability_ledger_ref
final_artifact_manifest_id
doctor_report_ref
browser_evidence_ref
backup_restore_report_ref
legacy_regression_ref
live_qualification: qualified | external_blocked | failed
slice_acceptance: passed | failed
long_term_platform_complete: false
```

静态截图、直接 DB seed、mock facade 内部、手工复制备份、自然语言报告、未执行 Windows 恢复、缺失 manifest/hash 或被跳过的失败测试均不能进入通过证据。

## 23. Wayfinder 追踪

本 Spec 的输入决策分别位于：

- [审计当前投研 MVP 与可复用边界](issues/01-audit-current-mvp-and-reuse-seams.md)
- [统一平台领域语言与上下文边界](issues/02-sharpen-platform-domain-language.md)
- [调研数据 Provider、point-in-time 与增量缓存](issues/03-research-data-providers-pit-and-cache.md)
- [调研 K 线库、标注能力与许可证](issues/04-research-chart-libraries-and-annotation-models.md)
- [调研本地运行时、存储与恢复基线](issues/05-research-local-runtime-store-and-recovery.md)
- [固定纵向切片用户故事与示例标的](issues/06-fix-slice-user-story-and-security-fixture.md)
- [决定分层存储、时间语义与同步契约](issues/07-decide-data-storage-and-pit-contracts.md)
- [决定 Codex 控制面、确定性运行时与 run journal 边界](issues/08-decide-control-plane-runtime-and-run-journal.md)
- [原型化 K 线与持久化标注 seam](issues/09-prototype-chart-and-annotation-seam.md)
- [决定交易计划状态机与市场状态评估接口](issues/10-decide-trade-plan-and-market-evaluation.md)
- [决定纵向切片最高层验收 seam](issues/11-decide-vertical-slice-acceptance-seam.md)

0.2.0 已由[对抗性审计 Spec 并关闭实施前缺口](issues/13-adversarially-audit-and-close-spec-gaps.md)从财务/数据时间/量化/风险/软件运维/安全许可/工作流/后见之明八个视角完成审计；具体反例、缺口与关闭方式见[审计资产](spec-adversarial-audit.md)。Wayfinder 关闭后，下一阶段可以按第 19 节从第一 tracer slice 开始实现；这不改变本文件“设计已就绪、平台尚未实现”的时态边界。

## 24. 对抗性审计关闭摘要

| 视角 | 实施前关闭的核心门 |
|---|---|
| 财务/估值 | research adapter 保留 source/period/scope/unit/currency/scale/restatement/股本/净债务 identity，capability/valuation permission 单调不增 |
| 数据时间 | purpose-scoped snapshots、PIT universe、survivor sentinel、横截面 100% 可解释 coverage、修订不回写 |
| 量化 | canonicalization/code/config identity、dirty tree hash、random seed 适用性、明确不冒充完整回测 |
| 组合风险 | exact/non-negative/currency/loss-notional 校验；无 Position 时不宣称组合可行性 |
| 软件运维 | safe restore containment、single writer、crash recovery、N-1 migration、Windows 新 root 恢复 |
| 安全许可 | local session/Host/Origin/CSRF/CSP/XSS/size limit、secret adapter、依赖/NOTICE、fixture 权利分层 |
| Codex 工作流 | `research_input_policy@1` 双 snapshot 复用、统一 Skill/维护入口、业务 import graph 无 prompt/LLM |
| 后见之明 | late data、用户 rationale、evaluator/policy 升级只生成新版本；历史按冻结 refs/as-recorded artifacts 渲染 |

没有剩余的第一切片实施前决策或 fog。未完成的量化/组合框架调研、长期文档和平台实现属于后续独立 effort，不得被本 Wayfinder 的关闭误报为长期平台完成。
