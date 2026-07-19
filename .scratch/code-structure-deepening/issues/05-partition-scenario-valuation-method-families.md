# 决定 Scenario valuation 方法族深模块拓扑

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 04

## Question

决定 `scenario.py` 中通用情景/概率/估值桥合同、DCF/SOTP/reverse DCF/relative、周期资源、金融机构、生物医药、方法隔离与加权的目标模块拓扑：保留哪一个稳定 valuation 外部接口，各方法族如何完整拥有 applicability、输入验证、投影、计算、敏感性与失败语义，forecast 依赖放在哪个内部 seam，并删除测试对 `_discount_times`、`_financial_from_forecast` 等私有方法的直接依赖。

## Answer

### 决策

Scenario valuation 只保留一个稳定外部 seam：

`ScenarioValuationEngine.run(DeterministicScenarioRequest) -> DeterministicScenarioResult`

它继续是 deterministic、无 I/O 的 in-process interface。目标不是把当前 4615 行 `ScenarioValuationEngine` 的每个私有方法变成一个 class，而是把 `scenario.py` 迁移为一个 scenario-valuation package：外部 engine 本身就是 **Scenario Set Valuation** 深模块的公开类，另外形成一个共享 **Valuation Basis** 深模块和四个完整方法族：**Industrial Valuation**、**Cyclical/Resource Valuation**、**Financial Institution Valuation**、**Biopharma Valuation**。结果合同与方法局部失败政策放在 package 内唯一的 method-result contract 中；不得建立旧 engine facade、同名 forwarding service、每方法一个 wrapper 或 speculative registry。

目标依赖方向为：

`formal Research task` -> `ScenarioValuationEngine` -> `ForecastEngine` -> `ValuationBasis` -> selected method families -> `financial` quantities/equity bridge

这里的箭头表达调用方向：engine 构造 reference/scenario ForecastGraph，并把 package-private immutable `ValuationContext` 交给方法族；方法族只消费 context、自己的 typed spec 和共享 result/basis contract。全部 seam 都是进程内纯计算，没有 provider、repository、clock、network 或 production/test adapter 差异，因此不引入 port、DI container、factory registry 或 application-facade mirror。正式 workflow 后续应在既有 Research task 内调用该 interface，不能把 valuation 升格成第二应用入口。

### Scenario Set Valuation module

`ScenarioValuationEngine.run` 完整拥有一次 scenario-set task，而不是转发给另一个 orchestrator：

- 校验 request subject/as-of、恰好 stress/base/improvement 三分、唯一 scenario id、同一互斥 partition、每个 segment-period 全 driver 覆盖；
- 校验 `ScenarioProbabilityEvidence` 的版本、PIT calibration facts、sample/count replay、同一 calibration basis 与精确概率和；证据不完整或不存在时只允许 `conditional_only`；
- 通过唯一 `ForecastEngine.build` 构建每个 scenario graph。周期方法真实需要的无 override reference graph 也在这里至多构建一次并作为 context 输入，不再由每个周期 method/sensitivity 重复调用 ForecastEngine；
- 保持当前方法顺序与 archetype routing：所有路径先得到 industrial DCF/SOTP/reverse/relative 的 ready/disabled 结果，再只为 cyclical、financial 或 biopharma 追加对应方法族结果；
- 组合每个 `ScenarioValuationResult`，并且只在三种情景都有可信概率时对**同一 method_id** 做 evidence-weighted range；value basis、horizon、formula version、per-share availability 或 dimensions 任一不一致即不加权并给 diagnostic；
- 永远不跨估值方法合成 composite，`cross_method_composite` 继续序列化为 `null`。

request/partition/calibration/weighting 的结构错误统一抛 `ScenarioInvariantError(code, message)`，因为它们使整组情景无效。一个方法的数据、applicability 或计算失败不能关闭其他方法：唯一 method-result contract 将已知 `FinancialInvariantError`、`ForecastInvariantError` 和 package-private method-block failure 转成 `ScenarioMethodResult(status="blocked", diagnostics, lineage_refs)`；未知编程错误不得 broad-catch 成 blocked。方法族负责声明 method id、适用性、value basis、horizon、formula version、blocked lineage，并负责其内部哪个条件属于 method-local failure；公共 contract 只统一结果形状和异常到结果的转换。

删除 Scenario Set module 会把 partition、reforecast、routing、method isolation、same-method weighting 和 no-composite 政策散回四个方法族与 caller，因此它有 leverage；再增加一层 `ScenarioService` 只会转发 `run`，不通过 deletion test。

### Valuation Basis module 与 Forecast 内部 seam

`ValuationBasis.bind(ForecastGraph, ForecastRequest) -> ValuationContext` 是 package-private deep seam。`ValuationContext` 是 immutable value，不是第二份 Forecast artifact，也不复制 graph；它绑定原 graph/reference graph、Security、periods、as-of 和 valuation-input lineage。Valuation Basis 完整拥有当前跨全部方法散布的：

- 按 Forecast template 识别 `valuation.fcff.*`、`financial.horizon.*`、`biopharma.horizon.*` 的 valuation horizon、as-of 与 lineage，且只依赖 04 号票决定的 canonical forecast package contract，不使用 root re-export；
- ISO、季度、半年度和年度 period end 的 exact ACT/365 schedule，以及严格递增、晚于 valuation-as-of 的失败语义；
- `ForecastQuantity -> FinancialQuantity` 的 scale/unit/currency/period/as-of/lineage 归一化；
- opening/terminal `EquityBridgeSpec` 对 frozen official facts、roll-forward assumption、balance-sheet period、diluted shares 和 method horizon 的绑定校验；
- enterprise/equity basis 到 common equity/per-share 的唯一 `EquityBridge` 执行、cash/debt node selection、其他 adjustments、dilution multiplier、bridge trace 与 low/base/high range 构造。

方法族仍决定使用 opening 还是 terminal bridge、enterprise 还是 equity basis，以及自己的经济输入 node；Valuation Basis 只执行一次共有的维度、时间和 bridge 语义。bridge 校验在每个 method 请求时发生，不能在 context 构造时一次性让坏 terminal bridge 阻塞 opening methods。删除该 module 会把 template-specific graph extraction、ACT/365、金额转换和权益桥复制进四个方法族，因而它是深模块；把 `graph.quantity` 原样转发成一组 accessor 则是浅层，禁止创建。

Forecast 与 Valuation 领域含义保持分离：ForecastGraph 仍是事实与假设驱动的可证伪 projection；Scenario valuation 只读取其 typed quantities 并执行确定性估值，不把 regulatory-capital、resource NAV 或 pipeline rNPV 经济学回写或复制进 Forecast。现有 `CONTEXT.md` 已足以表达该分界，无需新增术语或 ADR。

### Industrial Valuation family

一个 `IndustrialValuation.evaluate(ValuationContext, ValuationPlan) -> tuple[ScenarioMethodResult, ...]` 内部 interface 完整拥有：

- `fcff_dcf` 的 DCF gate replay/binding、特殊 archetype 禁用、显式 FCFF、ACT/365 discount、terminal spread/share、terminal-value risk diagnostics 和 WACC/growth sensitivity；
- `sotp` 的完整 segment coverage、terminal metric/multiple time basis、component aggregation、terminal bridge 和 multiple sensitivity；
- `reverse_dcf` 的 observed enterprise-value PIT gate、implied terminal growth求解与 present bridge；
- gated relative methods 的现有 MethodResult adapter、peer/source/currency/accounting gate、method-specific id/basis/multiple range；financial/biopharma generic relative 继续 disabled；
- 这些方法各自的 applicability、input validation、calculation、formula version、assumptions、sensitivity、lineage、diagnostics 与局部 blocked 语义。

它是一个方法家族而不是四个 class：DCF、SOTP、reverse DCF 和 relative 共用 industrial enterprise-value/segment-multiple 语义与 bridge policy，拆成一层一个方法只会增加宽 interface。普通 FCFF 继续对 cyclical/resource、financial institution 和 biopharma fail closed；不得为了让所有 archetype 有结果而回退到通用 DCF。

### Cyclical/Resource Valuation family

一个 `CyclicalValuation.evaluate(ValuationContext, CyclicalResourceValuationSpec) -> tuple[ScenarioMethodResult, ...]` 完整拥有 `mid_cycle_ev_ebitda`、`resource_nav` 和 `cyclical_historical_band`：

- versioned/PIT commodity curve、asset/segment coverage、reserve/life/schedule/currency/tax/capex/grade/production/cost evidence 与 peak-threshold 校验；
- scenario graph 对 reference graph 的 price/volume/yield/unit-cost/opex/capex transmission；reference graph 由 engine 一次构造后注入 context；
- mid-cycle normalization、finite reserve-backed after-tax NAV、历史样本的 PIT peak exclusion；
- price、production、grade/yield、unit cost、opex、maintenance capex 与 multiples/discount-rate sensitivities；
- 三个方法独立 blocked，资源输入缺失不能阻止非资源 cyclical manufacturer 的合法 mid-cycle route，resource over-extraction 也不能关闭 mid-cycle。

该 family 不调用旧 engine、不重建 Forecast policy、不保留 `_cyclical_methods/_mid_cycle/_resource_nav/...` wrapper。stable-growth ordinary DCF 禁用仍由 Industrial family表达，避免相同 guard 在两个家族实现。

### Financial Institution Valuation family

一个 `FinancialInstitutionValuation.evaluate(ValuationContext, FinancialInstitutionValuationSpec, ScenarioRole) -> tuple[ScenarioMethodResult, ...]` 完整拥有 `justified_pb`、`dividend_discount_model` 和 `residual_income`：

- financial shell horizon、opening book/regulatory capital/RWA、clean-surplus、capital ratio、institution-specific metrics、risk limit、period/as-of/PIT lineage 与 scenario case 校验；
- 一份 package-private typed `FinancialProjection`，统一计算 ROE/COE、payout/dividends、book roll-forward、residual income、regulatory headroom、operating exposure 和 dilution；不再用 `dict[str, Any]` 作为三个方法之间的隐式 seam；
- P/B x ROE/COE、DDM 与 residual-income 的完整公式、terminal guards、ACT/365 discount、共同 assumptions/sensitivities/diagnostics、equity-value bridge 与 method-local failure；
- ordinary FCFF 和 industrial relative/SOTP 继续 disabled，deposits/policyholder liabilities/regulatory capital 不被重解释为工业债务。

三个方法共享同一 financial projection 是家族内部复用，不是 public projection API。`_financial_projections` 删除后不能重现为只供测试调用的 public helper。

### Biopharma Valuation family

一个 `BiopharmaValuation.evaluate(ValuationContext, BiopharmaValuationSpec, ScenarioRole) -> tuple[ScenarioMethodResult, ...]` 完整拥有 `pipeline_rnpv` 和 `pipeline_sotp`：

- asset/indication unique economic rights、event DAG/closure、calibrated probabilities、milestone/license/royalty/ownership/launch-delay cash flows、period/as-of/currency/PIT evidence；
- shared-parent event只计算一次、依赖事件失败传播、finite rNPV、asset contribution SOTP、discount-rate cases；
- opening cash、corporate burn、committed financing exact terms、runway path、minimum buffer、share dilution 与 preferred/common equity gate；
- 完整 component trace、assumptions、event/ownership/royalty/delay sensitivities、diagnostics 与方法局部 blocked。

rNPV 与 pipeline SOTP 共享同一 package-private typed projection/event ledger，而不是分别重算或暴露当前 `dict[str, Any]`。它们仍是两个可审计方法结果，不做概率加权目标或 mature-revenue fallback；ordinary FCFF 和 generic industrial SOTP/relative 继续 disabled。

### 合同、serialization 与导出边界

必须保持 `DeterministicScenarioRequest/Result`、`ScenarioDefinition/ProbabilityEvidence`、`ValuationPlan`、family specs、bridge spec、method/scenario/weighted result 的现有字段、method ids、method order、formula versions、`to_dict()` 形状和 Decimal/quantity semantics。`ValuationArtifact@1` envelope、source-identity algorithm、formula identities、ready/partial status 和 dependency kind `Forecast` 均不因本次结构迁移改变。04 号票决定的 `ForecastGraphIdentity@2` 会让新 graph/source identity按新 code identity自然产生新 artifact version，但本票不再引入 Scenario/Valuation schema 或 identity version。

当前 `equity_research.__init__` root-reexport 37 个 scenario 名字。实施时：

- 正式平台 caller 最终仍经 Research task；需要直接构造 typed valuation request 的内部 caller/tests 从唯一 canonical scenario-valuation package interface 导入；
- `ScenarioValuationEngine`、request/result/error、Scenario/Probability/ValuationPlan、family-specific input specs和结果 schema 是真实 contract，可留在 package interface；leaf result types是 read-only artifact schema，不是另一套 builder API；
- `ValuationContext`、typed family projections、event/runway ledgers、method-block exception、calculation tuples、routing tables、normalizers和公式 helpers全部 package-private；
- callers 与 artifact type checks 迁移后，同一 change 删除 37 个 root aliases；不保留 import alias、旧 `scenario.py` wrapper 或 old/new engine dispatch。

### State、副作用与 failure locality

- 所有模块无外部 mutable state、I/O、clock 或 randomness；固定 request、ForecastGraph、Decimal policy 和 formula version 产生相同 typed result与 bytes。
- scenario partition/calibration/request identity failure 属于 Scenario Set module并抛 `ScenarioInvariantError`；Forecast graph/input failure保留 `ForecastInvariantError`；financial quantity/bridge failure保留 `FinancialInvariantError`；方法可预期的 applicability/input/calculation failure只变成该方法 blocked result。
- family 不得 broad-catch `Exception`，也不得因一个 blocked method跳过其他方法；重复或不一致 method id是结构错误，不能静默覆盖。
- weighted output只比较同一方法跨情景，保留 exact probability quantity、lineage、dimension和 blocked diagnostics；禁止任何 cross-method composite、target-price conclusion或 rating language。

### Replace-don't-layer 测试与删除门

本轮重新执行 `python -m pytest -q tests/test_scenario_valuation.py`，结果为 `55 passed in 13.04s`。这组公开回归保护三分情景、全部 archetype route、局部 fail-closed、PIT/equity bridge/dimensions、ACT/365、formula/lineage、probability weighting和 no-composite；`test_outlook_artifacts.py` 与 `test_company_outlook_journeys.py` 继续保护 typed Valuation artifact identity、Forecast dependency与重启可读。

替换测试分层如下：

- `ScenarioValuationEngine.run` interface tests保留完整三分重预测、路由顺序、每方法 ready/blocked、same-method weighting、no-composite和 deterministic serialization；
- 每个 family 的真实 `evaluate` internal interface tests覆盖其完整经济行为与局部 failure，不测试 `_dcf/_mid_cycle/_financial_pb/_biopharma_projection` 等迁移后的 method bodies；
- 当前直接调用 `_financial_projections` 的 ACT/365 financial test改为通过 Financial family完整结果或 public `run` 重放期望 value，projection继续 package-private；
- 当前直接调用 `_discount_times` 的测试迁移到真实 `ValuationBasis` ACT/365 interface，因为四个家族都会消费它；不在 engine 上再暴露 timing helper；
- 当前直接调用 `_financial_from_forecast` 的 scaled-money test迁移到 `ValuationBasis` 完整 bridge interface，断言最终 equity/per-share quantity和 trace，不把转换 helper变成 public API；
- 新 interface与现有 artifact journeys全部通过后，同一 implementation unit删除 8009 行旧单文件、旧 engine method bodies、重复 Forecast extraction/reference rebuild、dict-shaped projections、37 个 root aliases及被替代私有测试。不得保留旧 engine作为 facade、让新 family调用旧 private method、双跑结果比较或两套测试长期并存。

本决策解除 06 号 typed Research decision view seam 的阻塞；具体文件切换、ForecastGraphIdentity@2 协同、caller/export迁移与删除顺序继续由既有 08 号票统一锁定，不新增 child issue，不修改生产代码、schema、artifact envelope、`CONTEXT.md` 或 ADR。
