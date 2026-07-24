# ResearchEvaluation 与 StrategyValidation interface 决定

Date: 2026-07-24
Scope: Wayfinder ticket 07；仅锁定 interface、seam、迁移和删除边界，不授权生产实现。

## 结论

保留唯一公开 application path：

```text
ResearchWorkflow.handle(StartResearchWorkflow(ResearchWorkflowRequest@2))
  -> ResearchWorkflowResult
```

`ResearchEvaluationPlan` 是调用者可选择的不可变 typed value，不是 port、Facade、provider selector 或执行器配置。`ResearchEvaluation` 是目标系统内进程的深模块，隐藏研究证据准入、研究质量、预测、方法路由、情景估值、估值模拟、发布许可和 artifact 构造。它不形成第二条 application path。

当前不得建立 `StrategyValidationPort`：Vibe-Trading 已整体拒绝，主项目又没有可资格化的 production implementation，所以该 port 有零个真实 production adapter。未来只有在目标系统的确定性实现、真实 caller、typed lineage、ledger transaction 和测试能够同一原子切换时，才引入具体的 `StrategyValidationEngine.run(request) -> result`。在此之前，请求策略验证只能得到 typed `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`，不得生成假的验证结果或 artifact。

## 当前 checkout 证据

- 公开研究任务已经是 `ResearchWorkflow.handle(...)`；CLI、`DailyResearchCycle`、浏览器验收 fixture 和 public-seam tests 都经此入口。
- `ResearchWorkflow` 已拥有 replay、lease、cancel、PIT、source admission、analysis gate、artifact lineage、ledger transaction 和 publication，属于深模块。
- `ResearchWorkflowRequest@1` 仍让 caller 提交 `ResearchProjection.manifest`、`estimates` 等自由 mapping，并允许 caller 提交 `analysis_artifacts`。这把证据解释和 artifact 构造泄漏到 application seam。
- `ResearchEngine.run(ResearchRequest) -> ResearchRun` 与 `ResearchExecution` 已拥有主要确定性分析行为；`ResearchDecisionView@2` 是唯一正式 presentation model。
- `DataProvider.fetch(FetchRequest) -> FetchBatch` 是真实外部 seam，现有 production HTTP/Tushare-compatible adapters 与 deterministic `FixtureProvider`。
- provider 顺序、官方权威和版本目前没有一个完整 typed source policy；wire 参数和字符串 `provider_type` 仍泄漏到 orchestration/config。
- `WorkflowLedgerPort` 与 SQLite `WorkflowLedger` 已是唯一持久化 owner。无需另建转发式 Strategy repository。
- 当前 `ArtifactLineage` 没有 strategy-validation kind；仓库也没有 StrategyValidation caller、table、CLI/Web route 或 production adapter。
- Vibe-Trading 的通用 backtest、伪 Walk-Forward、IID Bootstrap、交易 P&L 次序置换模拟和 Shadow/generic reports 已在票 06 拒绝，production MCP allowlist 为 `[]`。
- Public Equity Investing 当前不可执行且 production 角色已拒绝，不能据此建立 `ResearchEvaluationPort`。

详细符号、caller、tests 与 schema 证据见
[current seam audit](research-evaluation-strategy-validation-current-seam-audit.md)。

## Design It Twice 比较

三套设计均先保留 `ResearchWorkflow.handle`，再从不同方向收敛。

| 设计 | 优点 | 删除测试 / 风险 | 采用结论 |
|---|---|---|---|
| 最小接口 | 不新增公开 Facade 或 port；未来只留具体 Strategy engine | 仍保留 caller-authored projection mapping 与 artifacts，旧 seam 泄漏未删除 | 采用单入口与无 port 原则，拒绝保留 Request@1 形状 |
| 策略灵活性优先 | closed typed unions、明确质量 decision、完整策略 request/result 与失败语义 | 若把每种 policy 都抽象成 Protocol，会制造无真实变化点的 seam | 采用 typed unions、失败和策略证据约束；策略与质量模块保持具体 |
| 调用者易用性优先 | caller 只新增一个 plan，不知道 provider/engine/adapter；默认值可版本化 | 用 identity 引用未准入对象仍会变成隐式 registry；同样未删除 projection/artifact 泄漏 | 采用单一 plan 和版本化默认；identity 只能引用 ledger 已准入的 typed frozen evidence |

最终设计是三者的严格交集，并额外要求一次性删除 Request@1 的自由 mapping 和 caller-authored artifact seam。

## 公开 application contract

目标 `ResearchWorkflowRequest@2`：

```python
@dataclass(frozen=True)
class ResearchWorkflowRequest:
    schema_version: Literal["ResearchWorkflowRequest@2"]
    invocation_id: str
    security_id: str
    requested_date: str
    effective_session_date: str
    data_snapshot_id: str
    evaluation_plan: ResearchEvaluationPlan
    workflow_snapshot_id: str | None = None
    market_data_snapshot_id: str | None = None
```

规则：

1. 请求只引用 ledger 中已经准入、hash-bound、PIT-frozen 的 snapshot；caller 不提交 manifest、estimates、member classification 或 `ImmutableArtifactDraft`。
2. workflow 从 canonical snapshot/ledger 读取 typed evidence，验证 security、cutoff、source-policy identity 和 content hash。
3. `ResearchWorkflowRequest@1` decoder、codec、callers、fixtures 和 tests 必须在同一迁移中替换并删除；不得 dual-read、fallback 或 alias。
4. replay fingerprint 包含 plan canonical hash、snapshot content hash 和 policy identities。

## ResearchEvaluationPlan

```python
@dataclass(frozen=True)
class ResearchEvaluationPlan:
    schema_version: Literal["ResearchEvaluationPlan@1"]
    purpose: EvaluationPurpose
    horizon: EvaluationHorizon
    required_dimensions: tuple[ResearchDimensionId, ...]
    disconfirming_evidence: DisconfirmingEvidencePolicy
    scenarios: ScenarioSelection
    valuation_methods: ValuationMethodSelection
    assumption_overrides: tuple[TypedAssumptionOverride, ...]
    valuation_simulation: ValuationSimulationSelection
    market_path_simulation: MarketPathSimulationSelection
    strategy_validation: StrategyValidationSelection
    allowed_degradation: AllowedDegradationPolicy
```

`EvaluationPurpose`、`ResearchDimensionId`、估值方法、scenario、distribution family、dependency model、degradation 和 strategy selection 都是 closed typed unions。数值使用 Decimal-compatible string 语义；不允许 binary float。

plan 可表达：

- 研究目的、as-of/forecast/review horizon；
- 必需研究维度与反证要求；
- typed scenario set；
- 估值方法意图，但 canonical method router 保留最终否决权；
- typed assumption override，且每项必须引用已准入 Evidence；
- 已校准分布、相关/依赖模型、seed、sample budget 和 convergence policy；
- 是否要求 market-path simulation；
- 是否请求策略验证；
- 允许的 typed degraded outcomes。

plan 不可表达：

- provider、source priority、adapter、engine、module、class、import path、MCP tool、endpoint 或 registry key；
- 官方来源权威、PIT、per-share、方法适用性或金融输出 gate 的豁免；
- Python/callable、prompt、自由 JSON、raw report、caller-authored hash；
- BUY/HOLD/SELL 或个性化行动结论。

canonical encoder 排序 identity-insensitive collections，并从完整 canonical content 派生 `evaluation_plan_identity`。版本化的 `standard(...)` constructor 必须把默认值实化到 value 后再 hash；replay 不读取 mutable ambient defaults。

## 研究质量深模块

目标为具体的内进程 module，而非外部 port：

```python
@dataclass(frozen=True)
class ResearchEvaluationRequest:
    plan: ResearchEvaluationPlan
    frozen_evidence: FrozenResearchEvidence
    source_policy_identity: str

@dataclass(frozen=True)
class ResearchEvaluationResult:
    status: Literal["ready", "partial", "blocked"]
    reason_codes: tuple[ResearchEvaluationReason, ...]
    dimension_results: tuple[ResearchDimensionResult, ...]
    forecast: Forecast | None
    valuation: Valuation | None
    valuation_simulation: ValuationSimulation | None
    market_path_simulation: MarketPathSimulation | None
    strategy_validation: StrategyValidationResult | None
    publication_permissions: PublicationPermissions
    evaluation_plan_identity: str

class ResearchEvaluation:
    def evaluate(
        self, request: ResearchEvaluationRequest
    ) -> ResearchEvaluationResult: ...
```

这个 module 隐藏 substantial behavior：source/PIT/quality admission、研究维度、反证、Forecast、方法路由、Scenario Valuation、simulation、degradation、发布许可和 typed artifact factory inputs。删除它会把这些规则重新分散到 workflow、CLI、daily cycle 和 tests，因此通过 Depth、Leverage 与 Locality 的删除测试。

`ResearchWorkflow` 仍负责任务生命周期、replay、lease/cancel、retry classification、ledger transaction、lineage validation 和唯一 presentation materialization。CLI/Web/daily 不得调用 `ResearchEvaluation`。

## DataProvider 与 source policy

| 能力 | seam 结论 | production adapter | deterministic test adapter |
|---|---|---|---|
| 外部结构化数据 | 保留 `DataProvider` port | HTTP/Tushare-compatible provider | `FixtureProvider` |
| source authority/order/admission | typed、versioned、in-process policy；不是 port | 不适用 | 直接测 policy value/behavior |
| research evaluation | concrete in-process deep module；不是 port | 不适用 | 经 public workflow + fault injection 测试 |
| strategy validation | 当前不引入 port 或 placeholder | 0，因此禁止 port | fake 不能替代 production variation |
| persistence | 保留现有 `WorkflowLedgerPort` | SQLite `WorkflowLedger` | temp SQLite 真实 adapter |
| presentation | 保留唯一 `ResearchDecisionView` | canonical renderer chain | public-seam fixtures |

Data synchronization 拥有 source policy；provider protocol adapter 拥有 wire parameter translation。composition root 静态装配 typed policy，不使用字符串 `provider_type`、service locator、registry 或 dynamic import。snapshot identity 必须记录实际 source-policy version。ResearchEvaluation 和未来 StrategyValidation 只消费 frozen snapshots，绝不直接调用 DataProvider。

## StrategyValidation 目标 contract

以下是 future design target，不是本票生产占位符。只有具体目标实现、caller、lineage、ledger persistence 与 tests 可原子进入时才创建类型。

```python
@dataclass(frozen=True)
class StrategyValidationRequest:
    schema_version: Literal["StrategyValidationRequest@1"]
    validation_invocation_id: str
    strategy: FrozenStrategyDefinition
    scope: FrozenStrategyScope
    market_data: FrozenMarketDataIdentity
    walk_forward: WalkForwardDesign
    execution: ExecutionRules
    benchmark_identity: str
    resampling: ResamplingPolicy
    requested_checks: tuple[StrategyValidationCheck, ...]

@dataclass(frozen=True)
class StrategyValidationResult:
    schema_version: Literal["StrategyValidationResult@1"]
    validation_run_id: str
    status: Literal["ready", "partial", "blocked"]
    reason_codes: tuple[StrategyValidationReason, ...]
    engine_identity: str
    code_identity: str
    dependency_lock_identity: str
    request_fingerprint: str
    folds: tuple[WalkForwardFoldResult, ...]
    aggregate_in_sample_metrics: tuple[ValidationMetric, ...]
    aggregate_out_of_sample_metrics: tuple[ValidationMetric, ...]
    drawdown: DrawdownResult | None
    turnover: str | None
    costs: CostResult | None
    fill_diagnostics: FillDiagnostics
    resampling_quantiles: tuple[ValidationMetric, ...]
    convergence: ConvergenceResult
    quality_diagnostics: tuple[StrategyQualityDiagnostic, ...]
    artifact_hashes: tuple[str, ...]
    result_content_hash: str

class StrategyValidationEngine:
    ENGINE_VERSION = "TargetOwnedStrategyValidation@1"

    def run(
        self, request: StrategyValidationRequest
    ) -> StrategyValidationResult: ...
```

request 必须绑定：

- security 或 frozen universe/membership identity；
- snapshot/content hash、source policy、calendar、adjustment、corporate action 和 availability cutoff；
- declarative validated Strategy identity/version/signal/position/risk/execution rule/code/config hashes；
- train/test folds、purge/embargo/refit 和 Walk-Forward identity；
- signal lag 与 next-tradeable price basis；
- A 股 T+1、停牌、涨跌停、lot、fee、slippage、turnover、volume 和 partial-fill 规则；
- benchmark；
- statistical algorithm/version、seed、sample budget 与 convergence；
- requested diagnostics。

result 必须绑定所有 request/engine/code/dependency/data/universe/policy identity，并分开报告 in-sample/out-of-sample fold、parameter identity、drawdown、turnover、cost、fill/unfilled/invalid、resampling quantiles、convergence、look-ahead、survivorship、coverage 和 quality diagnostics。

不得接受 Python path、callable、prompt、MCP envelope、raw report、generic `backtest(run_dir)` 或自由 configuration mapping。

## Artifact identity、lineage 与 ledger

- plan canonical hash 进入 request fingerprint 和每个研究 artifact 的 policy identity。
- workflow 使用专用 typed factories 从 evaluation result 建立 immutable artifacts；caller 不再提交 artifact drafts。
- 未来 strategy evidence 需要专用 `StrategyValidationArtifactDraft.from_result(...)` 和行为特定 lineage invariants；仅给 generic kind enum 增加一个字符串不算实现。
- strategy artifact parents 至少绑定 StrategyDefinition、DataSnapshot/MarketDataSnapshot、universe membership、source/execution/statistical policies、engine/code/dependency lock identities。
- checkpoint、artifact manifest、lineage edges 与 final result 由现有 WorkflowLedger owner 在一个原子 transaction 中写入；不得新建转发 repository 或旁路文件。
- `ResearchDecisionView` 仍是唯一正式 presentation。若 strategy result 成为 decision-relevant 字段，必须原子升级 view schema 及 JSON/HTML/Web/workbook callers，不得 dual view。当前 plan identity 和 disabled reason 可进入既有 audit/policy identity。

## 失败语义

可表示的研究/验证不足是 typed outcome：

- `RESEARCH_DIMENSION_INCOMPLETE`
- `DISCONFIRMING_EVIDENCE_MISSING`
- `VALUATION_METHOD_NOT_APPLICABLE`
- `VALUATION_METHOD_INPUT_MISSING`
- `SOURCE_AUTHORITY_INSUFFICIENT`
- `STRATEGY_VALIDATION_NOT_REQUESTED`
- `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`
- `STRATEGY_DATA_COVERAGE_INCOMPLETE`
- `STRATEGY_VALIDATION_NON_CONVERGENT`
- `STRATEGY_VALIDATION_PARTIAL_FOLDS`

它们产生 `partial`/`blocked` 与明确 reason codes，不伪造正式发布许可。能力尚未实现时，strategy selection 产生 `blocked + STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`，`strategy_validation` 为 `None`，且不生成 strategy artifact。

schema、PIT、identity、distribution/correlation、strategy definition 等 admission violation 在执行前以 stable code 和 field path 失败。timeout/transport 可标 retryable；typed result malformed、identity mismatch、look-ahead violation、artifact tampering、numeric inconsistency 为 terminal；persistence 使用 ledger typed failure。跨 application seam 的诊断仅保留 stable code、retryability、substep 与 redacted cause type，不泄漏 raw exception、URL、path、provider payload 或 generic `"error"`。

## 单向迁移与删除矩阵

未来实现票必须把下列替换视为一个原子切换：

| 替换 | 同票必须删除 |
|---|---|
| `ResearchWorkflowRequest@2` + frozen snapshot refs + plan | Request@1 decoder/codec、自由 `ResearchInputs` public seam、caller-owned projection manifest/estimates、caller-authored analysis artifacts、旧 fixtures/tests/docs |
| concrete `ResearchEvaluation` | `ResearchRunner` Protocol 及仅为 CountingEngine/decorator 建立的虚假变化点、重复质量/发布判断 |
| typed source policy | string `provider_type` dispatch、orchestration 中的 Tushare wire params、hard-coded source-policy identity、registry/service locator 倾向 |
| 专用 artifact factories | caller artifact draft construction、raw report persistence、重复 lineage decisions |
| future concrete StrategyValidationEngine | 任何 placeholder port、fake-only adapter、Vibe MCP wrapper、generic report/backtest path |

禁止的设计：

- `ResearchEvaluationFacade` 或 `StrategyValidationManager.run(kind, payload)`；
- 镜像现有 workflow/ledger 的 Facade 或 repository；
- string dispatch、dynamic import、service locator、万能 registry；
- generic HTTP-config adapter 或 caller 选择 provider/engine；
- 纯字段转发/repackage builder；
- compatibility decoder、dual-read/dual-write、旧路径 fallback；
- raw 外部 HTML/PDF/JSON/MCP 报告成为正式 artifact 或 presentation。

## Domain vocabulary

- **ResearchEvaluationPlan**：用户对研究目的、时域、分析选择、反证要求和允许降级的不可变 typed 选择；它既不是原始 `ResearchRequest`/数据 payload，也不是实现选择器。
- **ResearchEvaluation**：对冻结证据执行 source/PIT/研究质量、预测、估值、模拟和发布许可的目标内进程深模块。
- **StrategyValidation**：针对冻结数据和声明式 Strategy、显式 Walk-Forward、执行约束与统计政策的 evidence-constrained historical validation；它不是 TradePlan、PlanEvaluation、order、broker execution 或个性化建议。

`CONTEXT.md` 是启动时已有的 untracked 用户资产，无法安全区分 dirty ownership，因此本票不修改它。上述术语由本决定锁定，待独立、可归属的 domain-doc 迁移票处理。

## 验收决定

每个拟新增 port 均已完成真实 adapter 证明：只有既有 `DataProvider` 和 `WorkflowLedgerPort` 满足真实生产与可确定测试替身/环境；ResearchEvaluation、source policy 和 StrategyValidation 不满足或不需要外部变化点，因此不创建新 port。唯一 application path、内部深模块职责、future strategy contract、identity/lineage、ledger transaction、typed failures 和单向删除目标已锁定。

本票不修改生产代码，也不宣称 StrategyValidation 已实现或 Vibe-Trading 已采用。
