# 决定类型化 Research decision view seam

Type: `grilling`
Mode: `AFK`
Status: `resolved`
Blocked by: 03, 05

## Question

决定 `ResearchDecisionViewBuilder` 当前对 Forecast、Valuation、Simulation、MarketPath 和 divergence 原始 Mapping 的解析、artifact 完整性校验、金融数值解释、story 组装与展示文本之间的职责分界：建立什么类型化 presentation input 和单一 decision-view 输出，哪些解释规则属于领域/应用而非展示，如何让 view 模块不重新推导估值或证据语义，并删除调用其私有静态方法的测试。

## Answer

### 决策

保留一个稳定的 Research decision-view 外部 seam，但把宽 keyword/Mapping interface 收缩成一个类型化输入：

`ResearchDecisionViewBuilder.build(ResearchDecisionInput) -> ResearchDecisionView`

`ResearchDecisionViewBuilder` 所在 module 是无 I/O 的 in-process deep module；它不是 HTML builder，也不是 artifact reader。删除它会把展示许可、决策相关字段选择、情景并列、分布可比性、story/evidence 组装、audit projection 和金融输出边界散回 workflow、workspace、Python HTML、Web 和 XLSX，因而具有 depth、leverage 与 locality。不得再加一个 `ResearchViewService` 转发 `build`，也不得把当前 898 行 implementation 按 `_scenario/_method/_story` 机械拆成同样宽的 helper classes。

依赖方向固定为：

`ResearchExecution` -> `ResearchDecisionInput` -> `ResearchDecisionViewBuilder` -> `ResearchDecisionView`

`Research archive/decision query` -> persisted canonical `ResearchDecisionView` -> Web/Python HTML/XLSX adapters

`ArtifactLineage` 与 `WorkflowLedger` 位于输入和持久化两侧，不能被 view module 反向依赖：

`WorkflowLedger` -> `ArtifactLineage` -> validated artifact bundle -> `ResearchExecution`

HTML、Web、XLSX adapters 只消费同一个 view；它们不能读 Forecast/Valuation artifacts、ResearchRun payload 或 permissions 来补算字段。

### 唯一 typed `ResearchDecisionInput`

`ResearchDecisionInput` 是 package-level immutable contract，不持久化为第二份 artifact。它不包含任意 `Mapping[str, Any]`，而包含：

- `workflow_run_id` 以及一个已经绑定的 `ResearchIdentity`：research run、platform Security/subject、DataSnapshot、model-data snapshot、as-of、model/policy/code identity；
- typed ResearchRun presentation source：status、现有 research capabilities/permissions、sources、declared missing、synthesis/narrative 与 diagnostics；不包含旧 HTML；
- typed `DataSnapshot` decision evidence：facts、official/source identity、diluted-share candidate 与 audit refs；
- 04 号票 canonical `ForecastGraph` contract和 05 号票 `DeterministicScenarioResult` contract；
- optional typed `ValuationSimulationResult`、`MarketDataSnapshot`/calibration 与 `MarketPathResult`；
- `ValidatedArtifactGraph` receipt：每个 artifact record/content/source/schema/formula identity及精确 parent edges；
- `PresentationEvidence`：trusted-source gate结果和 frozen diluted-share binding。它只保存上游已经验证的 evidence，不接受 caller 声明 `allow_per_share=True`。

`ResearchExecution` 完整拥有 fresh/reused artifact payload 到该 input 的 strict assembly；每个 owning domain module提供当前 canonical schema 的类型化 decoder，不能让 view module按 key 猜 schema。decoder 只支持迁移后的唯一 current schema；不保留 `ResearchDecisionView@*`/legacy ResearchRun 二选一、`get("run_id")` fallback、prefix version dispatch 或 Mapping duck typing。历史 cutover 由 08 号票安排一次性 materialization/migration，不能用永久 runtime compatibility 掩盖。

artifact 完整性分三层且每条规则只有一个 owner：

1. `WorkflowLedger` 读取 object/envelope/relation并验证 bytes、content hash 与数据库一致；
2. `ArtifactLineage` 验证 `DataSnapshot -> Forecast -> Valuation -> optional Simulation` 和 `Simulation + MarketDataSnapshot -> MarketPath` 的 dependency graph，以及 research/snapshot/security/subject/as-of/model/policy/code identity；
3. `ResearchDecisionInput` 构造只接受上两层 receipt并校验 presentation completeness，例如必要三件套存在、optional chain不能断裂、typed payload与 envelope schema一致。

`ResearchDecisionViewBuilder` 不再重复 `_validate_artifacts` 的 relation/envelope/identity规则。它只验证输入中影响 decision view 的语义，例如三情景可展示、typed quantities可比较、permission evidence完整。这样 artifact corruption仍在最接近 persistence/lineage 的 seam fail closed，而不是被包装成任意展示错误。

### 单一 typed `ResearchDecisionView@2`

`ResearchDecisionView` 保留现有顶层 schema、`view_id` 算法与 `to_dict()` canonical shape，但所有内部 `Mapping` 字段替换为 immutable typed values：

- `DecisionStory`；
- `DriverView`；
- `ScenarioView` / `ValuationMethodView` / `ValuationPointView`；
- `MarketImpliedExpectation`；
- optional `ValuationDistributionView`、`MarketPathView` 与 `ValueMarketComparison`；
- `ResearchAuditView` 与固定 non-investment-advice boundary。

这些 nested types 是同一个 presentation model的一部分，不是额外 public builders。`to_dict()` 是 JSON/Web/process adapter 的唯一 serialization seam；in-process Python renderer和 workbook adapter只接受 `ResearchDecisionView`，不接受 `Mapping | ResearchDecisionView`、schema prefix或任意 dict。Web 在 JSON seam 后消费 exact `to_dict()`，不得自行从 raw artifacts建立第二个 view。

`view_id` 继续按 `ResearchDecisionView@2 + workflow_run_id + ordered artifact content hashes` 计算，同一 workflow/bundle deterministic，相同 ResearchRun在不同 workflow、model或artifact bundle下仍形成不同历史 view。结构迁移本身不升级 `ResearchDecisionView@2`、typed artifact envelope、数据库 schema或现有 identity算法。

### View module 拥有的决策支持政策

view module只解释上游 typed results，不重新计算 Forecast、Valuation、Simulation 或 MarketPath：

- 固定按 stress/base/improvement 三角色并列；使用 Forecast contract提供的 terminal horizon、node kind/metric identity、typed quantity、narrative、leading indicators和 invalidation conditions，不再扫描 `.volume.` suffix、猜 `*E` 年份或从任意 node_id拆 metric；
- key drivers与关键财务结果只从 typed Forecast decision projection选择，不手算收入、EBIT、FCFF或公司 archetype-specific指标；financial/biopharma shell没有 industrial metric时必须显示 typed limited state，不能以“数据不足”掩盖错误通用模板；
- method view直接使用 Valuation contract的 status、applicability、value basis、horizon、formula version、conditional range、bridge trace、sensitivity和diagnostics；不重跑 equity bridge、method applicability、概率或估值公式；
- market-implied expectation只接受 Valuation typed contract标记的 reverse-DCF expectation，不能靠 `method_id == reverse_dcf` 加 `sensitivity.name` 字符串组合重新发明方法语义；
- simulation/path fields只投影 typed quantiles、tail、calibration、dependency、budget和diagnostics，不从 raw payload补 unit/currency/period；
- story只组合 typed ResearchSynthesis/Forecast narrative、实际 scenario outcome与 monitoring/invalidation evidence。它可以确定性地选择和排序，但不能硬编码“事件 → Driver → 财务预测”或假设所有 archetype都有 revenue/EBIT/FCFF，也不能创造上游不存在的因果关系；
- audit完整保留 artifact/source/fact/formula/parameter/diagnostic/version/permission evidence，默认通过渐进披露呈现；exact Decimal始终在 canonical view/audit保留，视觉 adapter可按统一 formatting policy舍入但不得改 underlying value。

用户可读的 applicability/diagnostic说明属于该 application-level decision policy，不属于 HTML/JS renderer；它由 typed status/diagnostic tag和 quantity生成，不再对英文异常文本做 substring translation。原始 method diagnostics继续进入 audit。这样 Python、Web和XLSX看到同一解释，而 renderer只负责 escaping、布局、可访问性和媒介格式。

### formal per-share permission 的唯一 owner

沿用 03 号票的两道门：

1. `ResearchExecution` publication pre-gate：typed Valuation/Simulation 声明 per-share output但没有 frozen diluted-share identity时，整个 artifact bundle不得发布。当前递归扫描任意 Mapping中的 `output_level/kind/unit` aliases不再是 interface；owner artifact的 typed output level直接给出结果。
2. `ResearchDecisionViewBuilder` presentation permission：artifact可以发布后，view决定是否展示 formal per-share数值。

presentation permission 必须同时满足：ResearchRun未 blocked且允许 report/scenario/formal-per-share、trusted-source validation通过、diluted-share identity精确绑定 DataSnapshot中的 official frozen fact、每个候选 ready method的 low/base/high bridge都以该 exact fact只除一次并在 stress/base/improvement三情景齐备、至少两个 method ids满足该绑定。任何一项失败只把 permission设为 false并降级到 equity/basis value；不能删除整个 view、不能显示未经许可的 per-share值，也不能让 renderer重新开启。

当前 `_diluted_share_binding/_share_bound_ready_methods/_presentation_permissions` 从 workflow移入 view module的 typed policy，implementation用 typed `ValuationPoint/EquityBridgeTrace` 而非 Mapping/Decimal猜测。`PresentationPermission` 是 view/audit的一部分；`ResearchExecution`只传 evidence，不计算最终 bool。

### value/market comparison 的唯一语义

`ValueMarketComparison` 属于 decision-view application interpretation，不属于 Simulation、MarketPath engine或 renderer。它只比较两边已经发布的 typed p50 quantity，并要求 exact value kind、unit、scale、currency、terminal period/horizon和 as-of一致；需要币种转换但没有 frozen FX evidence时必须 `not_comparable`。任一分布受限、缺失或 permission不允许相应 per-share level时返回 typed `limited/not_comparable/not_comparable_horizon`，不计算 difference。

满足全部条件时只计算同 dimension的 `market_path_p50 - valuation_p50`，状态为 `comparable_with_limits`，并保留“不同机制、不构成确定性价格结论或交易动作”的边界。它不是 valuation重算、target price、rating或交易信号。当前直接调用 `_value_market_divergence` 的测试必须迁移到完整 `build` seam，不能把 comparison再公开成第二 interface。

### canonical persistence、历史与 render adapters

每次 workflow 的 `ResearchExecution` 必须恰好构建并持久化一次 canonical `ResearchDecisionView@2` JSON及其 HTML projection，并在 final manifest中引用；same workflow replay复用同一 artifacts。ResearchRun core、typed analysis artifacts和 DecisionView是不同 immutable identities，DecisionView不得覆盖或冒充 ResearchRun source payload。

`WorkspaceService` 当前按 workflow SQL分组后再次读取六类 artifact并调用 builder，形成第二条展示政策执行路径，必须删除。目标 Research archive/decision query按 workflow/final-manifest读取该次已经持久化的 canonical view，strict-decode并返回；历史多个 workflow/model/policy/snapshot版本继续并列，绝不以“当前代码”重建旧 view而让历史叙事漂移。

当前 `research_run_record.canonical_json_artifact_id`、manifest member roles和旧 typed compatibility artifacts如何一次性归位，由 08 号迁移票安排 backup-first cutover：新路径必须把 ResearchRun source与workflow-scoped DecisionView分离；旧 immutable bytes保留审计，新 canonical view在迁移中 materialize并重新建立引用。迁移完成后只有一种 runtime lookup，不按 `ResearchRun@*`/`ResearchDecisionView@*`分支，不双读、不重建、不 fallback。

adapter职责固定为：

- Python HTML renderer消费 typed view，生成唯一正式 HTML并嵌入 exact canonical JSON；只做 escaping、number formatting、progressive disclosure、responsive/accessibility；
- Web workspace消费同一 JSON view并渲染交互区域。当前 JS `renderSandboxReport` 与 Python renderer重复整份报告语义，迁移后删除；若保留 iframe则加载已持久化 canonical HTML，不能在浏览器再生成第二份 report；
- XLSX adapter接收 typed view，在进程边界序列化为 exact JSON并验证公式链/reconciliation；不接受 schema-prefix Mapping或从 valuation artifact自行推导 summary；
- Web/Python/XLSX可以有媒介特有布局，但不拥有 field selection、permissions、diagnostic meaning、comparison或financial boundary。

`trading_platform.__init__` 当前 root-reexport builder/result/error，caller迁移到 canonical module后删除 aliases；view builder只由 `ResearchExecution`调用，archive/query与renderers读取 result contract。`WorkspaceService.research_view_builder`、artifact-reader/run-reader callbacks及 `_research_views`重建路径同步删除，不能保留作 fallback。

### State、副作用与 typed failure

- builder无 state、I/O、clock、randomness或mutable registry；固定 typed input得到相同 view bytes与id。
- object/envelope/relation/identity failure归 `PersistenceError`/`ArtifactLineageError`；typed input decode/completeness failure由 `ResearchExecutionError`映射到既有 node failure；view-specific结构与政策错误归 `ResearchViewError(code, diagnostic=None)`，不暴露 raw payload、SQL、path或exception text。
- optional Simulation/MarketPath不存在是合法输入；optional dependency chain不完整或identity冲突是 input failure；分布存在但不可比较是 typed limited result，不是exception。
- permission false、blocked valuation method、declared missing和data limitation都是可展示状态，不能 broad-catch成空 view；unknown programming error也不能伪装成 limited。
- output始终保留金融边界，禁止 BUY/HOLD/SELL、买卖持有、target-price conclusion或house rating语言。

### Replace-don't-layer 测试与删除门

本轮执行：

- `python -m pytest -q tests/platform/test_decision_research_view.py tests/platform/test_market_path_simulation_artifact.py tests/platform/test_company_outlook_journeys.py tests/platform/test_valuation_workbook_adapter.py`：`30 passed, 3 skipped in 71.20s`；3项 workbook render/reconciliation测试因 bundled artifact runtime未配置而明确跳过，不计为 pass；
- `node --test tests/research-view.test.js`（`web/`）：`5 passed`。

替换测试分层如下：

- `ResearchDecisionViewBuilder.build(ResearchDecisionInput)` interface tests覆盖 exact typed JSON、三情景、key drivers、archetype-appropriate story、ready/blocked methods、permission false降级、trusted per-share permission、optional distributions、same/different dimension+horizon comparison、audit与boundary；
- `_value_market_divergence` 私有测试改为通过完整 build提供两种 typed distributions，断言最终 `ValueMarketComparison`；
- workflow对 `_share_bound_ready_methods`、`_presentation_permissions` 的直接测试改为 public workflow -> canonical view assertions，覆盖被篡改的一个 point、缺一个 range、重复 divide step、缺一个情景方法均使 permission false；`_has_per_share_output` alias测试改为 typed ResearchExecution publication pre-gate，不保留递归字符串扫描；
- workflow created/reused/restart测试断言一个workflow只产生一个 view、replay identity不变、不同 workflow/model形成并列view；workspace测试从 final manifest加载exact bytes并证明不调用builder；
- Python HTML测试继续证明embedded JSON exact equality、progressive audit与安全escaping；Web测试保留version selection/DOM rendering/formatting，删除 `renderSandboxReport`专属语义测试；XLSX测试使用typed view fixture并在bundled runtime可用时验证公式链和tamper failure；
- 新 interface回归与真实 consumers全部通过后，同一 implementation unit删除旧宽 `build` signature、全部 Mapping extraction helpers、`_validate_artifacts`重复identity逻辑、workflow permission helpers、workspace重建callbacks/path、`ResearchDecisionView@*` input compatibility branch、Python/JS双report语义、root aliases及其直接私有测试。不得保留 old builder wrapper、Mapping overload、schema prefix或旧新renderer双路径。

本决策解除 07 号 Application task interfaces票的 view-side阻塞，并把 ResearchRun/DecisionView reference归位、历史 materialization、consumer切换与删除顺序交给既有 08 号迁移票；没有新增 child issue。`ResearchDecisionView` 是 presentation model而非新的领域概念，故不修改 `CONTEXT.md`；该选择可随内部重构演进且没有独立不可逆技术承诺，不新增 ADR。
