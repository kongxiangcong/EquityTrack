# 外部能力替换与删除矩阵

## 范围与判定口径

本矩阵以当前 checkout 的正式代码、schema、测试和 ticket 01 锁定的上游身份为事实源。这里的“决策”是后续资格化票要证实或推翻的候选路由，不代表外部能力已经 adopted。只有后续票同时给出运行证据，并能在同一实现切片原子切换 callers、tests、docs、persistence 与 presentation、删除被替代对象，`adopt-external` 才能成为最终采用结论。

四个值只表示：

- `adopt-external`：外部引擎填补已证实的空白；它必须位于本地拥有的窄 interface 之后，且不得把外部应用架构带入主项目。
- `adapt-code`：只移植并重写一个可验证的协议或解析行为；不执行上游 Skill，不保留上游运行时，不建立新 canonical path。
- `keep-local`：当前深模块及其不变量继续作为唯一实现。
- `reject`：能力不进入 production interface；不得以 wrapper、fallback、feature flag、兼容读取或平行报告保留。

## Canonical replacement / deletion matrix

| 能力 | 当前 canonical implementation | 外部候选 | 决策 | 采用条件 | 删除对象 | 拒绝原因 |
|---|---|---|---|---|---|---|
| 应用任务入口与静态组合 | `trading_platform.application` 的 named task contracts；`bootstrap.open_*` 静态组合；CLI/Web 只调用 task | 四个候选的 hosted workflow、Skill 脚本、CLI、MCP、Web/Agent 入口 | `keep-local` | 外部能力只能作为现有 task 背后的真实 adapter/engine；不得新增 lookup、task bag、镜像 Facade 或第二入口 | 无；后续采用必须删除任何临时直调脚本、service locator、外部 Facade 或旁路 caller | 候选都不拥有本仓库的 application policy、权限、事务、PIT、审计与失败语义 |
| 结构化行情/基础数据端口 | `DataProvider` typed port，经 `DataSynchronization` / `DataSyncService`、`DataRepository` 写 immutable snapshot | `a-stock-data`、`global-stock-data` 的端点协议与解析知识 | `adapt-code` | 每个端点分别证明 authority/terms、PIT、字段/单位、限流、typed failure、unknown-not-zero；改写为同一 `DataProvider` seam 的真实协议 adapter；禁止执行 Skill | 被新 adapter 完全替代的 provider-specific 请求构造、解析和重复 fixture；不能删除 `DataProvider`、同步任务或 repository | 两个上游均不是稳定包，且自由脚本存在 empty-on-error、unknown→0、TLS/凭据/写盘或推荐字段风险 |
| Tushare-compatible 数据能力 | `TushareCompatibleProvider` + 当前网关 provenance；正式同步仍经唯一 `DataProvider` path | `a-stock-data` / `global-stock-data` | `keep-local` | 外部端点只能补充独立 dataset/source role，不能冒充、代理或 fallback 到 Tushare | 无；若后续抽离协议所有权，删除 `DataSyncService` 内被新深模块取代的 Tushare-shaped 参数条件分支 | 外部 Skill 不提供等价 entitlement、provenance、PIT 与正式网关身份 |
| Source policy、provider 选择与失败关闭 | `DataSyncService` 记录 attempts/quality/cursor/snapshot，但当前按 provider 序列尝试且构造 Tushare-shaped params | 两个数据 Skill 的 source-order/fallback 示例 | `keep-local` | 后续必须由本地 source policy 对 dataset/source role 作显式选择；网络/解析/权利失败保留 typed evidence，不能切旧源冒充成功 | 资格化实现落地时，删除 service 内隐式 provider-order fallback、dataset 条件请求拼装及任何新增 legacy fallback；相关测试原子迁移 | 上游 fallback/空结果语义会掩盖来源失败，违反唯一路径与 fail-closed |
| 官方披露关键财务事实与 source manifest | 研究任务的正式 source gates、manifest、authority 与 missing 语义 | Public Equity Investing、两个数据 Skill、Vibe loader | `keep-local` | 关键数字仍需官方披露 authority 和 `source_id`；外部只可提供候选发现/交叉检查 | 无；删除任何把第三方聚合值升格为 critical fact 或跳过 manifest 的分支 | 四个候选都未证明可替代 CNINFO/交易所/SEC/HKEX 等官方披露 |
| Forecast 与证据图 | `ForecastEngine`、`ForecastGraphIdentity@2`、typed forecast evidence 与 lineage | Public Equity Investing 的研究提示；Vibe Agent/report | `keep-local` | 外部研究只能作为控制面质量对照，不得成为 runtime 或 canonical artifact | 无；删除任何 raw external narrative 到 Forecast artifact 的直写/映射捷径 | hosted 工具不可复现；Vibe narrative/Agent 不拥有本地证据图身份和反证不变量 |
| Scenario Valuation 与公司类型路由 | `ScenarioValuationEngine` 及 archetype-specific contracts/gates | Public Equity Investing 的 valuation story；两个 Skill 的 target/recommendation 字段；Vibe report | `keep-local` | 所有估值仍通过本地 method router、applicability/data gates、official-source boundary | 无；删除任何外部 target/rating 字段进入正式 valuation 的映射、兼容 key 或并列 renderer | 外部候选不能证明方法适用性、关键输入和金融输出边界；推荐/目标价字段默认不允许 |
| Valuation Simulation | `ValuationSimulationEngine` 模拟企业经营/估值不确定性并记录假设、分布、相关性、seed、quantiles | Vibe Monte Carlo/收益路径 | `keep-local` | 只能用本地估值语义；策略收益模拟不得复用或覆盖 valuation artifact | 无；若策略验证落地，删除任何共用 schema/kind/renderer 的试探实现 | Vibe 的收益/价格路径不是企业价值 Monte Carlo，模拟对象不同 |
| Market Path Simulation | 独立 `MarketPathSimulation`，与企业估值隔离 | Vibe 价格/收益模拟 | `keep-local` | 后续策略统计必须使用自己的 typed identity 与输入冻结，不得改写 market-path 或 valuation 结果 | 无；删除任何把外部策略结果写入现有 market-path artifact 的旁路 | 当前边界已防止 value/market 混同；外部完整模拟栈没有本地 PIT/lineage 契约 |
| StrategyValidation：回测、Walk-Forward、成本与泄漏检查 | 当前没有 production `StrategyValidation`/完整交易回测；acceptance 明确 `full_trade_backtest: not_applicable` | Vibe-Trading 的 backtest / validation engine | `adopt-external` | ticket 06 必须在 pinned checkout 的 `uv` + CPython 3.11 `.venv` 中，以最小 allowlist stdio MCP 证明 initialize/list/call、determinism、PIT、防泄漏、成本、Walk-Forward、timeout/crash/malformed typed failure；只接受 repository-owned frozen fixture；生产 adapter 与 deterministic test adapter 共同服从一个本地深模块 interface | 在同一实现切片删除所有临时 subprocess/MCP harness、raw JSON/report 直通、重复策略统计、并行 backtest schema/CLI/Web 路径；若任一原子切换条件失败则改判 `reject`，不保留占位 adapter | 完整 Vibe 应用、Agent、文件/web/search/memory/swarm、loader、report、persistence 和交易域全部超出允许边界 |
| Live/simulated order、broker 与订单生命周期 | 本 Goal 无 canonical 能力，长期边界排除自动/真实交易 | Vibe 内部 app registry 的 place/cancel/order/broker connectors | `reject` | 无；不创建主项目 interface、fixture、credential schema 或 future placeholder | 删除任何意外引入的 order/broker contract、route、migration、dependency、test 或 docs | 明确 out of scope，具有外部副作用和个人账户风险；Goal 永久排除 |
| Research workflow、WorkflowLedger 与 ArtifactLineage | `ResearchWorkflow.handle(StartResearchWorkflow)`；`WorkflowLedgerPort` / SQLite ledger；typed immutable lineage | Public Equity hosted flow、两个 Skill 脚本、Vibe runs/files/reports | `keep-local` | 外部执行只可作为某个本地 task 内部的隔离 engine call，并由本地 ledger 记录 typed evidence | 无；策略验证若采用，删除上游 run/file identity 的正式持久化、raw report 索引和平行 workflow | 外部 lifecycle/persistence 不能维护本地对象身份、事务、重放与审计不变量 |
| ResearchDecisionView@2 cutover 的 migration-only indirection | `ResearchDecisionViewMaterializerPort`、单一 materializer 与每次 research start 的 cutover-complete gate | 四个外部候选均不能复用该迁移 seam | `keep-local` | 先由最低支持 data/schema version 证明 cutover 已永久完成；此前不得删除或泛化 | 条件满足时原子删除 callback port、materializer、重复 runtime gate、migration-only adapter/operations/tests/docs；否则无删除 | 它不是外部结果 adapter seam；泛化会制造 wrapper。是否删除取决于迁移事实，不取决于外部候选 |
| ResearchDecisionView@2 与正式 presentation | `ResearchDecisionViewBuilder` 生成 canonical view；当前 JSON/HTML/workbook/Web 均消费本地 typed artifacts | Public Equity UI、Vibe HTML/PDF/Web、Skill stdout | `keep-local` | 若新增 StrategyValidation artifact，必须版本化迁移同一 presentation model，并经真实页面验收；默认视图遵守渐进披露 | 无；删除 raw upstream HTML/PDF 嵌入、并行报告页、第二 renderer 和旧 view-version callers | 外部 presentation 会制造平行平台，且不能保证 provenance、unknown、金融输出和可访问性边界 |
| Public Equity Investing production runtime、数据、估值与 presentation | 当前正式研究/预测/估值链；没有该 hosted app 的 runtime dependency | OpenAI hosted Public Equity Investing | `reject` | 无 production 采用条件；ticket 03 只做控制面对照，不改变本行 | 删除任何 plugin/runtime dependency、正式数据源声明、artifact schema、外部报告、自动行动或评分映射 | 当前精确 lookup 为 `plugin_not_found`；无 source/manifest/entitlement 可审计，且示例含 add/trim/exit、sizing、target/recommendation |
| Public Equity Investing 控制面研究质量对照 | 本地 Codex/Skill 控制面指令；正式 facts 仍进入 typed Forecast/valuation path | 可由 ticket 03 黑盒观察的 hosted workflow 行为 | `keep-local` | 可用时只针对同一 frozen、non-personal source manifest 做黑盒比较；当前不可用则保持精确 `external_blocked`，不得猜测隐藏提示或工作流 | 无 production 删除对象；比较输出仅作非权威研究证据，不能形成第二 checklist/runtime path | 当前没有可验证行为足以支持 `adapt-code`；hosted app 不能成为 runtime、provider、估值权威或行动决策者 |
| 上游自由 Skill/完整应用执行 | 无；正式入口均为本地 application task | `a-stock-data`/`global-stock-data` Skill；Vibe 完整 CLI/Web/API/MCP surface | `reject` | 无 | 删除任何 Skill runner、通用 exec adapter、完整 MCP proxy、外部 Web mount、双数据库、共享用户目录或主项目 dependency | 攻击面、权利、失败语义和架构范围不可接受；会直接形成旁路或平行平台 |

## 当前 checkout 的已证实缺口

这些缺口是后续 deepening/adoption 的约束，不是本票授权的实现清单：

1. Production `open_*` 每次只组合一个 provider；多-provider 顺序只是 `DataSyncService` 能力和 fixture 测试，没有版本化 production source policy、retry/rate/circuit policy。
2. `DataSyncService` 直接生成 `ts_code`、`exchange`、`list_status` 等 Tushare wire 参数；`normalize` 同时承担 canonical validation 与 Tushare `fields/items` 协议解析。新增外部端点前必须深化 provider seam，并原子删除这两处 source-specific 泄漏。
3. `stock_basic`/full-universe 路径把每行复用为请求的单一 `security_id`，cursor/scope 也按单股；当前没有可用的逐行 Security Master/identifier resolution。
4. `forecast_actual` 只有 generic version/hash，没有 typed payload persistence；Forecast Review 测试仍另外持有 caller-authored actual。
5. `financial_fact`、`filing`、`news_event`、`corporate_action`、adjustment factor 没有完整 production ingestion/persistence；现有 official filing fixture 直接写 SQL，只是缺口证据。
6. Research assembler 验证 caller-supplied frozen manifest，却不会从 normalized official facts/filings 组装统一 EvidenceSnapshot。
7. adjusted/corporate-action lineage 已有下游校验，但 Chart/ingestion 仍只接受 unadjusted/no-factor；不能用第二张外部 OHLCV 表规避。
8. provider transport failure typing 仍缺 response-size、retry-after、schema identity 和精细 timeout/rate-limit taxonomy；上游 empty/zero fallback 不得复制。
9. Web 只读取 snapshot-bound canonical persistence；它没有也不得新增直接外部 fetch route。
10. StrategyValidation 是真实空白，不是一个待保留的本地 backtest；现有 acceptance 明确 `full_trade_backtest: not_applicable`，migrations/CLI/Web 均无策略验证路径。
## Caller、persistence 与 presentation 影响

### 数据能力的原子迁移面

1. Callers 仍只调用 `DataSynchronization` 等 named application task，不知道 provider 名称、端点或 fallback 顺序。
2. Persistence 继续由 `DataRepository` 写 raw/normalized/immutable snapshot 与 provenance；第三方端点未证明缓存/派生权利时不得持久化。
3. Presentation 只消费 typed snapshot/quality；不得显示上游 stdout、自由 dict 或失败后空数组。
4. 后续若资格化一个端点，同一 ticket 必须替换 request/parse/source-policy tests 与文档，并删除被替代分支；不能让退休实现作为 fallback。多个仍被独立资格化、承担不同 source role 的 adapter 只能由显式版本化 policy 选择并记录全部 attempt。

### StrategyValidation 的原子迁移面

1. Callers 只能看到一个本地 task-level `StrategyValidation` interface，不知道 MCP tool 名、subprocess、上游文件或 report。
2. Persistence 必须先定义独立 typed artifact identity、冻结输入摘要、engine/upstream identity、PIT/leakage/cost/Walk-Forward evidence 和 typed failure；不得复用 Valuation Simulation、Market Path 或 Vibe run directory。
3. Presentation 只能扩展同一 canonical decision view；不得嵌入 Vibe HTML/PDF 或创建第二 Web。
4. 在正式实现 ticket 中，production adapter、deterministic test adapter、ledger/persistence、view migration、CLI/Web callers、acceptance 和删除对象必须一起切换。无法做到则候选由 `adopt-external` 改判 `reject`。

## Deletion test

| 试探方案 | 删除该模块后会发生什么 | 判定 |
|---|---|---|
| “ExternalDataProvider” 只把 dataset 和参数转发给自由 Skill/HTTP helper | 调用细节原样搬回 `DataSyncService`，没有隐藏协议、权利、PIT 或失败不变量 | shallow wrapper，拒绝 |
| 在 provider 列表末尾保留 Tushare/旧端点 fallback | 删除 fallback 会改变失败为“成功”的表象，而非丢失合法能力 | 双路径并掩盖错误，必须删除 |
| 同时写旧 snapshot/schema 与新外部 raw/schema | 任一读者仍可选择旧数据，identity 和权利状态不再唯一 | dual-write/read，拒绝 |
| “VibeFacade” 镜像 54 个 MCP tools 或按字符串查找工具 | 删除后 callers 直接依赖外部 tool surface，模块没有拥有本地策略不变量 | service locator / mirror Facade，拒绝 |
| StrategyValidation 只暴露一次完整任务并拥有输入冻结、资格化 allowlist、失败语义和证据身份 | 删除后 callers 必须重新实现 PIT、成本、泄漏、Walk-Forward、隔离与 lineage policy | deep module 候选；仅 ticket 06 运行证据通过后成立 |
| 把 Vibe HTML/PDF 或 Public Equity 输出作为第二份正式报告 | 删除它不会损失本地 typed decision artifact，只移除重复 presentation | 平行 renderer，必须删除 |

## 后续票必须回答的证据缺口

- ticket 03：Public Equity Investing 可用时的黑盒质量与金融输出失败关闭；不可用时记录精确 `external_blocked`，不阻断其他路径。
- ticket 04：`a-stock-data` 每个 A 股端点的 primary terms、PIT、字段/单位、失败语义与官方交叉验证，决定哪些 `adapt-code` 行退回 `reject`。
- ticket 05：`global-stock-data` 每个美港股端点同样的资格化，特别验证 SEC identity、腾讯字段/单位和 recommendation 隔离。
- ticket 06：Vibe 的 pinned 本地 MCP 与算法可信度。只有该票通过，本矩阵中的 StrategyValidation `adopt-external` 才有资格进入 interface/adoption spec 设计。
- ticket 07 及其后：定义本地 interface、artifact identity、迁移顺序和精确删除对象；本票不提前把实现细节写入 `CONTEXT.md`。
