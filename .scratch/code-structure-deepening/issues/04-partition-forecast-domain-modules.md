# 决定 Forecast 深模块拓扑

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

决定 `forecast.py` 中事实/假设与数量契约、DataSnapshot、ForecastGraph 不变量与 replay、通用节点计算、公司/分部期间构建、金融机构与生物医药 shell 的目标模块拓扑：保留哪一个稳定 Forecast 外部接口，各行为应完整迁移到哪个深模块，哪些类型属于真正跨 seam 的合同，如何删除直接测试内部构建细节的旧测试而保持确定性、lineage、单位与 fail-closed 语义。

## Answer

### 决策

Forecast 只保留一个稳定的外部 seam：

`ForecastEngine.build(ForecastRequest) -> ForecastGraph`

它继续是 deterministic、无 I/O 的 in-process interface；`ResearchEngine` 和 scenario valuation 是现有两个真实 caller。不得增加 `build_segment`、`build_company_period`、`validate_graph`、`route_archetype` 或 shell-specific public methods，也不得在 `ApplicationFacade` 再镜像 Forecast。当前 3093 行单文件迁移为一个 forecast package，但文件数量不是目标；package 只有一个外部 interface，内部按完整行为形成三个深 module：

1. **`ForecastEvidence`**：事实/计算/假设、quantity dimensions、DataSnapshot content identity 和 ForecastRequest cross-object invariants；
2. **`ForecastGraph`**：公式执行、node/edge compilation、DAG/lineage/dimension validation、monitoring metadata、canonical graph identity 与 replay；
3. **`ManufacturingForecast`**：通用/多分部/周期制造与资源类的分部期间推进、公司汇总、三张表勾稽和 valuation-input gate。

`ForecastEngine` 自身拥有 archetype routing、template selection、统一 error seam 和三个 module 的组合，不再拥有每条公式和每个 period 的构建细节。删除 `ForecastEngine` 会把 archetype policy 和组合决策散回 `ResearchEngine`、scenario 和 tests，因此它具有 leverage；删除三个内部 module 则会分别把 PIT/evidence、graph algebra、manufacturing economics 的复杂度散进其他两个 module，因此也通过 deletion test。任何只把参数从 `ForecastEngine` 转发给同名 builder 的 class 不通过 deletion test，不能创建。

全部依赖均为 in-process：

`ResearchEngine` / `ScenarioValuation` -> `ForecastEngine` -> `ForecastEvidence` -> `ManufacturingForecast` -> `ForecastGraph`

`ForecastEngine` 的 financial/biopharma shell 也直接产出 `ForecastGraph` blueprint，再由同一 `ForecastGraph` module compile。没有 remote/local I/O、没有 production/test adapter 差异，因此不引入 port、repository、factory registry 或 dependency injection seam。

### `ForecastEvidence` module

其内部 interface 是：

`validate(ForecastRequest) -> ValidatedForecastInput`

它拥有当前散在 `ForecastQuantity`、`SnapshotFact`、`SegmentBaseline`、`CompanyOpeningBalanceSheet`、`DataSnapshot`、`ForecastAssumption`、`ForecastNarrativeStatement`、`SegmentForecastOverride` 和 `ForecastRequest.__post_init__` 的完整不变量：

- 所有数值为 finite `Decimal`，scale 为正，unit/currency/period/as-of 完整；ambient Decimal precision 不得改变 normalized value、reconciliation 或 hash；
- DataSnapshot 的 Security/as-of/segment/opening-balance identity、Fact uniqueness、PIT availability、raw/calculated/model-derived evidence classification、derivation refs、official basis、quantity-to-Fact exact binding；
- 分部 working capital 与公司 opening balance、资产与负债权益、period 和 reporting currency 的 exact reconciliation；
- assumption availability、Fact lineage、quantified/qualitative dimension完整性、narrative basis 与 evidence resolution；
- forecast periods 单调且严格晚于 baseline，override 只命中一个 requested segment/period，growth/utilization/probability 等范围 fail closed；
- `DataSnapshot.content_hash` 继续按 security、as-of、sorted typed baselines/opening balance/facts 的当前 canonical JSON 算法生成并校验。

`ValidatedForecastInput` 是 package-private immutable value；它不是第二份 snapshot，也不产生新的 artifact。DataSnapshot 仍符合 glossary 中“按明确数据版本冻结的不可变输入集合”；`SnapshotFact.evidence_kind` 继续明确区分 reported/source-extracted/calculated/model-derived，不能把带 Assumption lineage 的 model-derived value冒充 official Fact。这里没有出现需要修改 `CONTEXT.md` 的新领域概念。

这些 type constructors 可以保留 scalar-local validation，但所有需要查看多个 facts、baselines、assumptions 或 Security 的规则只在 `ForecastEvidence.validate` 做一次。`ForecastEngine`、`ManufacturingForecast`、`ForecastGraph` 和 scenario 不得各自再次验证 PIT、Fact binding 或 request scope。

### `ForecastGraph` module

其内部 build interface 是：

`compile(ForecastBlueprint) -> ForecastGraph`

`ForecastBlueprint` 只在 forecast package 内跨 internal seam，声明 input quantities、derived equations、semantic node kind、period、probability 与 monitoring policy；它不包含预先算好的 `ForecastNode`/`ForecastEdge`。`ForecastGraph` module 完整拥有：

- `growth/product/minimum/sum/ratio/positive_tax/passthrough/consensus/valuation_gate` 的 exact Decimal calculation；
- operand role/signature、coefficient、unit/scale/currency algebra、same/prior period rules与 node-kind dependency rules；
- topological compilation、cycle detection、input/derived distinction、lineage propagation和 formula replay；
- node IDs、edge records、leading indicators、trigger/invalidation thresholds、review metadata 与 node/edge canonical ordering；
- graph serialization、`quantity(node_id)`/`node(node_id)` read access、`replay()` 以及 graph identity。

因此 `ManufacturingForecast` 只声明“什么经济关系应存在”，不手算 quantity后再让 Graph 重算一次；当前 `_derived_node` 先调用 `_calculate_formula`、`ForecastGraph.__post_init__` 再重复校验/replay 的双重知识收敛为一个 compiler。Graph 的 immutable result 仍保留 `nodes`/`edges`，因为它们是 `ForecastArtifact@1` 的机器可读审计内容，scenario 也真实消费 `ForecastGraph`/`ForecastQuantity`；但外部 caller 不构造 Node/Edge 来控制计算。

Graph failure 继续统一为 `ForecastInvariantError(code, message)`，保留现有 `FORECAST_GRAPH_*`、formula、dimension、period、currency、lineage、monitoring、reconciliation 和 replay code 语义。compiler 不返回部分图；cycle、未知公式、维度不成立、lineage 不完整、statement checks 非零或负的 cash/debt/net PPE valuation gate 都 fail closed。

### Graph identity 必须统一 version

当前代码存在有证据的 identity collision：financial shell 的 request 仅增加一个合法、Fact-bound `ForecastAssumption` 后，两份 graph 的 `to_dict()` 不同，但实测均得到 `fg_9fe1b77610eb130d2e94aa78`。原因是 manufacturing hash 包含 assumptions/narratives，而 `_build_financial_institution_shell` 与 `_build_biopharma_shell` 的 hash payload 不包含它们；三条路径也各自维护 identity payload。

目标 `ForecastGraph` module 必须使用唯一 `ForecastGraphIdentity@2` policy：对 graph 的完整 semantic content（Security、DataSnapshot identity/hash、template/routing identity、periods/review date、assumptions、narratives、nodes、edges、formula与 monitoring metadata）做 canonical hash，排除仅自引用的 `graph_id`。新 graph ID 使用明确 versioned identity（例如 `fg2_...`），所有 template path 共用这一算法，不保留 old/new hash dispatch。

这是本 effort 中唯一被代码证据证明必要的 Forecast artifact identity 变化；不改变 `ForecastArtifact@1` envelope、DataSnapshot hash、既有 persisted payload、node/edge字段或 schema。旧 immutable artifacts 保持原字节与旧 source identity 只读；cutover 后相同输入由新 code/model identity 产生新 artifact version，不更新旧 row、不 dual-read/dual-write，也不为了旧 `fg_` 继续执行旧 builder。08 号迁移票必须把 identity cutover、running-workflow drain 和 acceptance fixture更新纳入一次性替换顺序。

### `ManufacturingForecast` module

其内部 interface 是：

`project(ValidatedForecastInput) -> ForecastBlueprint`

它完整迁移当前 `_validate_baselines`、`_company_baseline`、`_assumption_node`、`_build_segment_period` 和 `_company_period` 的经济行为：

- general/multi-segment/cyclical manufacturing/resource 的 segment/baseline exact match 与 template/routing policy；
- 每个 period 的 demand、capacity、utilization、volume、ASP、unit cost、opex、capex、depreciation、working capital、tax、debt-change drivers；
- volume 受 demand 与 available capacity 的 minimum constraint，所有 override/default assumption lineage显式进入图；
- segment revenue/COGS/gross profit/margin/EBIT，再按公司汇总；不同 segment tax rate 时要求显式 tax entity，不能静默平均；
- NOPAT、CFO/CFI/CFF、cash change、FCFF、PPE、debt、other assets/liabilities、equity、balance-sheet/cash-flow checks 与 valuation gate；
- 跨 period `_SegmentState/_CompanyState` 只作为 implementation 内局部状态，绝不进入 interface或 artifact。

该 module 不生成 `ForecastGraph` identity、不拥有 generic FormulaId implementation、不验证 Graph DAG，也不路由 financial/biopharma。cyclical template 继续使用现有 explicit volume/utilization/price/cost/tax/maintenance-capex driver语义，且下游 stable-growth valuation 禁用规则仍由 scenario valuation 接管；本票不新增资源 NAV 或行业模型。

### Financial institution 与 biopharma shell

当前两个 shell 分别只有 horizon passthrough（biopharma 额外带 opening cash/debt），真正的 regulatory-capital/residual-income 与 asset/indication/rNPV/runway 经济性位于 `scenario.py`。它们删除后只会把约 100 行 routing blueprint 移回 `ForecastEngine`，不满足独立 deep module 的 deletion test。

因此二者保留为 `ForecastEngine` implementation 内的 typed blueprint producers，不建立 `FinancialInstitutionForecast`、`BiopharmaForecast` public module、port 或 speculative template registry。它们继续返回同一个 `ForecastGraph` contract，明确说明 industrial FCFF/manufacturing template 被禁用。05 号票若把 scenario method families 形成真实深模块，可消费这些 shell graph 与 specialized typed specs；在 Forecast 中复制 regulatory-capital 或 pipeline valuation 将形成第二套方法实现，明确禁止。

### 真正跨 seam 的合同与导出

Forecast package 的外部 caller 必须知道：

- task/result：`ForecastEngine`、`ForecastRequest`、`ForecastGraph`、`ForecastInvariantError`；
- shared numerical/result contract：`ForecastQuantity`；
- 为构造 typed request 必需的 `Security`、`CompanyArchetype`、`DataSnapshot`、`SnapshotFact`、`SegmentBaseline`、`CompanyOpeningBalanceSheet`、`ForecastAssumption`、`ForecastNarrativeStatement`、`NarrativeBasis/Category`、`SegmentForecastOverride`；
- `ForecastGraph` 返回值中的 read-only node/edge/monitoring/formula enums，因为它们属于 artifact schema，但 caller 不以它们为 builder interface。

`_SegmentState`、`_CompanyState`、`ForecastBlueprint`、compiler builder、formula registry、archetype blueprint producers 和 monitoring construction全部 package-private。

`equity_research.__init__` 当前同时 root-reexport 25 个 Forecast 名字，与文件头宣称的“public seam deliberately small”矛盾。实施时正式 platform caller 继续只经 `ResearchEngine/ResearchRequest`；scenario 和需要直接构造 typed Forecast 的内部 caller改从单一 `equity_research.forecast` package interface 导入。迁移全部 callers/tests 后，同一 change 删除 root-level Forecast reexports，不保留 aliases。`ImmutableArtifactDraft.from_forecast_graph` 等 production type checks 也改到 canonical forecast package，不能把 root import 当 compatibility path。

### State、副作用与 failure locality

- 三个 module 都无外部 state、I/O、clock、randomness 或 global mutable registry；相同 request 在固定 Decimal policy 下产生相同 graph bytes与 identity。
- `ForecastEvidence` 拥有 input/PIT/content-hash failure；`ManufacturingForecast` 拥有 unsupported economics、segment/company construction与 reconciliation failure；`ForecastGraph` 拥有 algebra/topology/replay/identity failure。对 caller统一表现为稳定 `ForecastInvariantError`，不 broad-catch 成 `ValueError`。
- `ForecastEngine` 只翻译 routing failure `FORECAST_TEMPLATE_UNSUPPORTED`，不重写下游 code；financial/biopharma disabled-method语义通过 routing explanation与 scenario method status表达，不伪装成 ordinary FCFF output。
- Graph、snapshot 和 artifact identity 都不依赖对象地址、dict insertion order、ambient Decimal precision或测试运行顺序。

### Replace-don't-layer 测试与删除门

现有 `tests/test_forecast_graph.py` 的 31 个测试在本轮重新执行为 `31 passed in 0.77s`，证明当前要保护的行为包括 multi-segment driver transmission、routing shells、PIT/fact binding、snapshot hash、opening reconciliation、three statements、tax consolidation、unit/currency/period algebra、monitoring、lineage、determinism和 ResearchEngine integration。

替换测试分层如下：

- `ForecastEngine.build` interface tests 保留完整 archetype routing、multi-period deterministic graph、shell禁用语义和 exact public outcome；company-outlook/artifact journeys继续证明 persisted Forecast artifact、scenario caller与 restart identity。
- `ForecastEvidence.validate` interface tests覆盖 DataSnapshot/Fact/Assumption/quantity/request的 PIT、hash、dimension、reconciliation和 ambient-precision behavior；不直接调用零散 `__post_init__` helper。
- `ForecastGraph.compile/replay` internal interface tests用 typed invalid blueprints覆盖 cycle、operand signature、unit/currency/period、lineage、monitoring、valuation gate与 replay。现有通过 `dataclasses.replace(graph.nodes/edges)` 重建损坏 result 的测试迁移到 compiler seam 后删除；`ForecastEdge` 不再从 root public seam 构造。
- `ManufacturingForecast.project` interface tests只验证完整 segment/company period blueprint的经济关系；不得直接测试 `_build_segment_period/_company_period/_derived_node/_monitoring` 或 implementation state。
- `ForecastGraph.quantity/node/replay` 是真实 result interface，现有通过它们观察正式结果的 assertions不是私有测试，应保留。`tests/test_scenario_valuation.py` 不再从 `test_forecast_graph` 模块导入 fixture；改用共享 typed contract fixture，避免测试文件成为隐式生产 seam。

新 interface回归与现有 public journeys全部通过后，在同一 implementation unit 删除旧单文件 `forecast.py`、旧 `ForecastEngine` method bodies、重复 formula calculation/validation、shell hash implementations、root reexports和被替代的 construction-detail tests。不得保留旧文件作为 package wrapper、不得让新 compiler调用旧 `_calculate_formula`、不得同时运行旧/新 graph并比较结果。

本决策解除 05 号 scenario valuation method-family票的阻塞，并把已证实的 `ForecastGraphIdentity@2` cutover交给既有 08 号迁移顺序票；不需要新增 child issue或 ADR，也不修改生产代码、schema、artifact envelope或 `CONTEXT.md`。
