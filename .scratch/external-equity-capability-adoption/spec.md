# 外部股票能力资格化与采用实现级 Spec

Status: `adversarially-audited`
Date: `2026-07-24`
Goal Prompt SHA-256: `ca1148516e14c148ac247123081ce7a2237863a725192779b3b9c7241fbee41d`

Label: `ready-for-agent`

## Problem Statement

tradingSystem 已有可审计的 DataProvider、ResearchWorkflow、Forecast、Valuation、WorkflowLedger 与 ResearchDecisionView，但当前 provider dispatch、official-disclosure ingestion、research request 和历史 cutover 仍暴露字符串路由、caller-authored payload、placeholder policy identity 与运行时旧 reader。四项外部候选只有少量协议知识合格；若直接接入会形成第二数据、研究、策略或报告路径，并削弱金融、PIT、rights、隐私和 fail-closed 门禁。

## Solution

将合格的 CNINFO、SZSE 与 SEC 官方协议知识以 clean-room 方式纳入现有 DataProvider seam；以版本化 QueryPolicy/SourcePolicy、不可变 official evidence 与 qualification receipt 绑定数据身份；以 ResearchWorkflowRequest@2 和 ResearchEvaluationPlan 从 frozen DataSnapshot 驱动本地 ResearchEvaluation；让 ResearchDecisionView@2 唯一派生 JSON、HTML、PDF、XLSX、Web 与 archive。所有 caller、schema、persistence、presentation、tests 和 docs 在同一 vertical slice 原子迁移并删除旧路径。Public Equity、聚合器、HKEX scraper 与 Vibe runtime 不进入 production；StrategyValidation 在没有两个真实 adapters 前保持 unavailable 且不建 placeholder。

## User Stories

1. 作为研究用户，我希望只提交 Security、截至边界、frozen DataSnapshot 与 ResearchEvaluationPlan，从而无需构造内部 manifest、自由 mapping 或 artifact。
2. 作为研究用户，我希望 official facts 不足时得到明确的 data-insufficient memo，从而不会把缺失数据误作估值结论。
3. 作为研究用户，我希望研究视图区分 Fact、Assumption、Forecast、Valuation、风险和反证，从而能理解什么证据会改变当前看法。
4. 作为研究用户，我希望 JSON、HTML、PDF、XLSX 与 Web 展示同一 ResearchDecisionView，从而不同输出不会产生数字或语义漂移。
5. 作为平台运营者，我希望 Tushare-compatible market data 与 official disclosure roles 只通过一个 DataSynchronization path，从而不存在 Skill 脚本或 CLI/Web 直连端点。
6. 作为平台运营者，我希望 SourcePolicy 明确 source priority、rights、freshness、completeness 与允许的 fallback，从而失败不会静默切换到未资格化来源。
7. 作为平台运营者，我希望合法 empty、partial、stale、rate-limit、401/403、timeout、schema drift 与 wrong Security identity 保持不同 typed outcome，从而 unknown 不会变成 zero。
8. 作为数据审计者，我希望每个 accepted fact 绑定 published、available、retrieved、source、policy、adapter、code 与 raw object identity，从而能够执行 PIT 重放。
9. 作为数据权利负责人，我希望代码许可证与端点数据权利分别审查，从而禁止缓存或派生的数据不会被持久化。
10. 作为本地数据所有者，我希望 0013/0014 在完整 backup 后原子迁移，从而任何无法唯一 backfill 的历史都会失败关闭并可恢复。
11. 作为历史审计者，我希望旧 request bytes 只作为 immutable audit evidence 保留，从而新 runtime 不需要兼容 decoder、dual read 或 legacy fallback。
12. 作为研究维护者，我希望 ResearchEvaluation 隐藏 source/PIT/quality、Forecast、Valuation、Simulation 和 publication policy，从而 workflow 只管理 lifecycle 而 caller 不复制领域决策。
13. 作为平台维护者，我希望 provider、workflow 与 ledger 的超大多职责文件按完整行为深化，从而不会用 helpers、forwarders 或镜像 ports 伪装模块化。
14. 作为安全维护者，我希望 production acceptance 自行验证 command receipt、artifact bytes 与 identity lineage，从而 caller-authored JSON、boolean 或孤立 hash 不能授权自己。
15. 作为组合纪律规划者，我希望六张开放 planning tickets 引用新的 canonical architecture，从而未来 MarketRegime、持仓研究、驾驶舱与计划验收不再依赖退休 seam。
16. 作为本地用户，我希望研究与估值永不自动改变 AccountSnapshot、TradePlan、PlanEvaluation、authorization 或 order state，从而平台始终保留用户控制权。

## Implementation Decisions

- 唯一 public seams 是 named application tasks、现有 DataProvider、WorkflowLedgerPort 与 ResearchWorkflow；不新增 service locator、镜像 Facade 或第二 persistence/presentation graph。
- Candidate decision 只使用 adopt-external、adapt-code、keep-local、reject；qualification state 单独记录。
- 生产迁移由四张完整 vertical slices 完成，随后一张 planning slice 回写当前组合纪律 Map；final release proof 是 Goal gate而不是延期 cleanup ticket。
- Schema 0013/0014、migration-only decoder 隔离、large-file deepening、PDF projection、rights/source policies 与 deletion targets 以本文 detailed contract 为唯一实现依据。
- 每张 implementation issue 一个本地 commit；old/new runtime 不得同时保留以换取绿色测试。

## Testing Decisions

- 最高测试 seam 优先使用 public CLI application tasks、ResearchWorkflow、WorkflowLedgerPort query、production composition root 与真实浏览器；private helper tests 随退休 seam 删除。
- 每个 DataProvider adapter 覆盖 normal、empty、partial、stale、auth/rate/timeout、schema/identity/time/market semantics、fixture replay 与一次 identity-bound live probe。
- 0013/0014 覆盖 fresh、prior/populated、fault、rollback、restore、active-old-workflow refusal 与 identity-stable retry。
- material production gates运行完整 canonical verifier；presentation切换同时运行 Web build、real CDP、PDF render与workbook reconciliation。
- release acceptance只信任由 production provider-qualify 持久化并可回查 command/object/ledger lineage 的 receipt artifact。

## Out of Scope

真实或模拟券商下单、order lifecycle、盘中做 T、个性化买卖/仓位建议、Public Equity runtime、完整外部 Skill/App/MCP/Web/persistence、HKEX scraper、未授权数据 feed、Vibe wrapper、StrategyValidation placeholder，以及六张portfolio planning tickets中尚未授权的新产品实现均不在本 Spec 范围。

## Further Notes

本 Spec 已完成 Standards + Spec 独立对抗审计并清空 Wayfinder fog；它描述待实施目标，不宣称 production migration 已完成。Public Equity plugin 仍精确 external_blocked，HK licensed feed 未资格化，Vibe runtime 已 reject；这些状态不阻塞当前 I01–I05 canonical frontier。

## Detailed implementation contract
## 1. 目标与完成边界

本 Spec 把 Public Equity Investing、`a-stock-data`、`global-stock-data` 与 Vibe-Trading 的已完成资格化，转化为 tradingSystem 的唯一 implementation frontier。

完成状态要求：

1. 合格的官方协议知识只进入一个深化后的 `DataProvider -> DataRepository -> DataSnapshot` path；
2. 研究调用者只提交 frozen snapshot references 与 typed `ResearchEvaluationPlan`；
3. ResearchEvaluation、CompanyForecast、ScenarioValuation、ValuationSimulation、ArtifactLineage、WorkflowLedger 与 ResearchDecisionView 保持本地 canonical owners；
4. 旧 provider dispatch、wire-param 泄漏、free mappings、caller-authored artifacts 和 migration-only runtime readers 被单向删除；
5. rejected/blocked 外部能力没有 dependency、placeholder、schema、route、fallback、report 或第二 persistence/Web；
6. fresh/old/populated data roots、public tasks、真实 provider canary、正式 presentation 和浏览器行为都通过与风险相称的验收。

本 Spec 不宣称上述生产改造已经完成。当前 checkout 仍是 migration `0012`、`ResearchWorkflowRequest@1`、字符串 `provider_type`、generic `HttpJsonProvider`、hard-coded policy identity 和 research-view runtime cutover seam。实现必须由后续 implementation issues 完成。

## 2. 权威输入与事实等级

### 2.1 权威仓库边界

- 根 `AGENTS.md`、长期 Prompt、`skills/SKILL.md`、本 effort Goal Prompt 和 resolved tickets 是约束源。
- 当前源代码/schema/tests 是“当前实现事实”。
- `research/` 中 pinned upstream、terms、runtime probe、fixture replay 与 verifier-authored evidence 是“资格化事实”。
- 本 Spec 中以“目标”“必须”“待实施”描述的内容是设计，不是完成证明。
- 上游 README、Skill、示例、raw response、自由 JSON、HTML/PDF 或营销描述不能自行证明 production 能力。

### 2.2 关键证据

- [upstream manifest](research/upstream-manifest.md)
- [replacement/deletion matrix](research/replacement-deletion-matrix.md)
- [Public Equity black-box decision](research/public-equity-investing-blackbox-quality.md)
- [A-share qualification](research/a-stock-data-runtime-qualification-and-decision.md)
- [US/HK qualification](research/global-stock-data-runtime-qualification-and-decision.md)
- [Vibe qualification](research/vibe-trading-runtime-qualification-and-decision.md)
- [ResearchEvaluation/StrategyValidation interface decision](research/research-evaluation-strategy-validation-interface-decision.md)
- [three-market vertical slices](research/market-validation-slice-decision.md)
- [one-way migration/deletion/upgrade decision](research/one-way-migration-deletion-and-upgrade-decision.md)

票 08 verifier 的 semantic manifest identity 是
`c9867b798c56d3ebf786d6e543f1a7c96190195566b6b8509c99428cee2ccc39`。
它证明三个隔离切片都 fail-closed；它不证明生产 adapters 已存在。

## 3. 当前事实与目标设计

| Concern | 当前已证实事实 | 待实施目标 |
|---|---|---|
| Production provider composition | 每次只装配一个 provider；`DataSyncService` 能按 tuple 顺序 fallback | typed `SourcePolicy@1` 显式选择 source roles、优先级与允许的失败处置；critical official source 不降级到 aggregator/secondary，未声明或退休来源永不 fallback |
| Provider protocol | orchestration 构造 Tushare wire params；generic HTTP provider/normalizer解释协议 | concrete adapter 完整拥有 wire、schema、failure translation |
| Policy identity | repository 写死 `query@1` / `source@1` | migration 0013 后 attempt/snapshot绑定 canonical typed policy identity |
| Official facts | 无完整 official filing/financial fact production ingestion；测试存在 direct SQL/caller fixtures | typed immutable filing/fact persistence，只经 public sync 写入 |
| A股 official data | CNINFO/SZSE protocol 可达；raw bodies未保存，available_at/target parser未完成 | clean-room CNINFO/SZSE adapters，经 rights/PIT/identity gates进入唯一 path |
| US official data | SEC submissions/companyfacts 可达；无 production parser与 truthful UA | cohesive SEC submissions/companyfacts/Archives adapter |
| HK official data | HKEX/issuer IR PDF hash一致；无自动许可/adapter | 保持 blocked/逐发行人 keep-local；不建 HKEX placeholder |
| Research request | Request@1 携带 projection/free mappings/caller artifacts | Request@2 只携带 snapshot refs + `ResearchEvaluationPlan@1` |
| Research execution | 本地 engine/workflow/deep modules已存在 | concrete `ResearchEvaluation` 从 frozen evidence构造 artifacts |
| Strategy validation | 无 production engine/schema/caller；Vibe 全 runtime reject | 当前 typed unavailable；不创建 port/engine/table/artifact |
| Presentation | `ResearchDecisionView@2` 是唯一正式 view，但 runtime保留旧 cutover reader且没有 canonical PDF projection | migration 0014 materialize/migrate 后删除旧 reader；JSON/HTML/PDF/XLSX/Web/archive 都只投影 View@2，PDF 不重算语义 |
| Dependencies | Python runtime dependencies为空 | clean-room stdlib优先；无外部 runtime adoption |

## 4. 最终候选决策矩阵

| Candidate / capability | Decision | Qualification state | 唯一允许角色 | 明确禁止 |
|---|---|---|---|---|
| Public Equity Investing production runtime/data/valuation/UI | `reject` | rejected | 无 | plugin dependency、source authority、target/rating/action、第二报告 |
| Public Equity control-plane quality comparison | `keep-local` | `external_blocked` | 未来对同一 frozen synthetic manifest 的非权威 canary | 猜隐藏 prompt、个人数据、runtime LLM、第二 checklist |
| `a-stock-data` Skill/package/parsers | `reject` | rejected | 无 | direct execution、mootdx、cache/files、fallback、unknown→0 |
| CNINFO statutory disclosure protocol | `adapt-code` | qualified-for-clean-room-implementation | clean-room typed official source role | 复制 cleartext/guessed ID/parser/fallback |
| SZSE statutory disclosure protocol | `adapt-code` | qualified-for-clean-room-implementation | clean-room typed official source role | disabled TLS、raw text、Eastmoney fallback |
| SSE/SZSE public trading records | `keep-local` | evidence-only | 无 current named caller | adapter/registry placeholder |
| `global-stock-data` Skill/aggregators/parsers | `reject` | rejected | 无 | Yahoo/EM/Sina/Tencent production path、rating/target |
| SEC submissions/companyfacts/Archives | `adapt-code` | qualified-for-clean-room-implementation | clean-room SEC official source role | copy upstream parser、ticker-only identity、raw JSON result |
| SEC ticker discovery | `keep-local` | evidence-only | future discovery only after new need | second security master |
| HKEX website scraper | `reject` | rejected | 无 | programmatic website extraction |
| licensed HKEX feed | `reject` | `external_blocked` / unqualified | future separately licensed qualification only after a new decision | empty adapter/table/config |
| issuer IR | `keep-local` | per-issuer-qualification-required | per-issuer terms/identity cross-check | global assumption or authority upgrade |
| Vibe MCP/backtest/WF/bootstrap/MC/report | `reject` | runtime-rejected | 无 | adapter/proxy/subprocess/report/persistence |
| Vibe lag/PIT/execution/hash ideas | `keep-local` | evidence-only | future target-owned design input only | code copy或外部 engine identity |
| StrategyValidation target capability | `keep-local` | unavailable | typed capability-unavailable disposition only | port、fake adapter、result artifact、route |

当前没有 `adopt-external` 行；availability/qualification state 不再冒充 decision value。
## 5. 用户与运营故事

1. 作为研究用户，我只提交研究对象、日期、frozen snapshots 和分析计划，不需要构造 manifest dict 或 artifacts。
2. 作为研究用户，我在 official facts 不足时得到明确 `data_insufficient_memo`，而不是估值结论或猜测值。
3. 作为研究用户，我能看到 source authority、PIT、quality、uncertainty 与 what-would-change，但不会收到个性化买卖/加减仓指令。
4. 作为平台运营者，我能通过一个 sync path 使用 Tushare-compatible market data 与明确的 official disclosure roles；provider 失败不会静默切换。
5. 作为平台运营者，我能区分合法 empty、partial、stale、rate-limited、rights denied、schema drift 与 wrong identity。
6. 作为本地数据所有者，我的旧研究历史在 migration 前有完整 backup；无法安全迁移时升级整体失败。
7. 作为审计者，我能从 WorkflowLedger、DataSnapshot、source policy、raw/object hash 与 artifact lineage 重放每个正式结果的身份。
8. 作为维护者，我能通过 absence gates 证明 retired symbols、fallback、dual readers/writers、外部 runtime 和 parallel reports 已清零。

## 6. 统一领域语义

- **SourcePolicy**：平台拥有的 versioned value，声明 dataset/source role、authority、rights、required/optional completeness 与 failure disposition。不是 port、provider registry 或 fallback table。
- **OfficialFilingVersion**：绑定 security/issuer、authority、document/accession identity、published/available/retrieved、raw object hash、correction/supersession 的 immutable typed record。
- **FinancialFactVersion**：绑定 filing、taxonomy/concept/context/period/unit/currency/scale/Decimal value/source fact identity 的 immutable fact。
- **FrozenResearchEvidence**：由一个 DataSnapshot及其 hash-bound typed members形成的 PIT evidence bundle；raw payload或 caller JSON不是该 bundle。
- **ResearchEvaluationPlan**：用户对目的、时域、分析选择、反证要求、模拟和允许降级的 immutable typed value；不是数据 payload或实现 selector。
- **ResearchEvaluation**：在 frozen evidence 上执行 source/PIT/quality、CompanyForecast、method routing、ScenarioValuation、ValuationSimulation、反证与 publication permission 的本地深模块。
- **CompanyForecast**：公司经营驱动、假设和可证伪预测的 typed ForecastGraph；当前由本地 `ForecastEngine` 拥有。
- **ScenarioValuation**：按公司类型与 applicability gates 对 typed Forecast/Scenario 执行本地估值；不能接受上游 target/rating。
- **ValuationSimulation**：企业经营和估值不确定性的本地模拟，绑定假设、分布、依赖/相关、seed、quantiles和convergence。
- **MarketPathSimulation**：市场价格路径的独立本地模拟；不得与企业价值或策略验证复用 artifact identity。
- **StrategyValidation**：对 declarative Strategy、frozen universe/data、Walk-Forward、execution/cost与统计政策进行历史验证。它不是 TradePlan、PlanEvaluation、broker/order或ValuationSimulation。
- **TradePlan**：用户拥有的条件化未来行动草案和生命周期；不由外部策略验证自动创建或执行。
- **ResearchDecisionView**：唯一正式 presentation model；renderers只投影已持久化 view，不重新解释研究。

`CONTEXT.md` 是启动时已有的用户-owned dirty asset，本 effort 不修改它。

## 7. 目标模块与唯一数据流

```text
CLI / Web / Codex Skill adapter
  -> named application tasks
  -> DataSynchronization
       -> concrete SourcePolicy@1
       -> DataProvider.fetch(TypedDatasetQuery)
            -> TushareCompatibleProvider
            -> CninfoStatutoryDisclosureProvider
            -> SzseStatutoryDisclosureProvider
            -> SecOfficialDisclosureProvider
            -> FixtureProvider (deterministic tests only)
       -> DataRepository
            -> provider attempt + raw object
            -> typed normalized/official records
            -> immutable DataSnapshot
  -> ResearchWorkflow.handle(StartResearchWorkflow(Request@2))
       -> load frozen snapshot evidence through the existing WorkflowLedgerPort query
       -> ResearchEvaluation.evaluate
            -> CompanyForecast / ForecastEngine
            -> ScenarioValuationEngine
            -> ValuationSimulationEngine
            -> optional existing MarketPathSimulation
            -> StrategyValidation unavailable decision
       -> typed artifact factories
       -> ArtifactLineage validation
       -> WorkflowLedger atomic checkpoint/manifest/refs
       -> ResearchDecisionView@2
            -> canonical JSON
            -> decision-first HTML
            -> deterministic PDF projection
            -> reconciled XLSX
            -> Web/archive projections
```

依赖方向：

```text
CLI/Web/provider protocol adapters
  -> application tasks
  -> domain deep modules/ports
  <- persistence adapters
```

禁止反向依赖、service locator、万能 Manager、镜像 Facade、raw connection/object-store access和presentation semantic recomputation。

## 8. DataProvider 与 SourcePolicy contracts

### 8.1 Typed query

目标 `TypedDatasetQuery` 是 closed union，至少包含：

- `TradingCalendarQuery`
- `DailyOhlcvQuery`
- `SecurityMasterQuery`
- `OfficialFilingQuery`
- `OfficialFilingDocumentQuery`
- `SecCompanyFactsQuery`

共同 identity：

```text
invocation_id
dataset/query schema version
canonical security + issuer identity
market/exchange
requested/effective/as_of boundary
range/cursor identity
source role
network authorization
credential scope identity (never secret)
```

query 不含 endpoint、provider class、MCP tool、module path或自由 wire mapping。

### 8.2 Fetch result

`DataProvider.fetch(query) -> FetchBatch` 隐藏 protocol translation，并返回：

```text
provider/adapter/source/source-policy identity
retrieved_at
typed attempt status/failure
raw bytes or explicit absence
raw SHA-256
response schema/MIME/size/completeness
typed normalized candidates or parser failure
cursor candidate
```

DataRepository 先 durable publish raw object，再在单一 transaction 中写 attempt、typed versions、quality、cursor与snapshot membership。失败的 raw/attempt evidence可记录；不合格数据不能进入 snapshot。

### 8.3 Source policy

`SourcePolicy@1` 的 canonical content至少包含：

```text
policy version/content hash
dataset -> source roles
provider/adapter/source identities
authority and rights profile
required/optional role
allowed persistence/derived/distribution use
freshness/completeness policy
typed failure disposition
```

SourcePolicy 是静态 composition value，不是 caller 选择器或运行时 registry。其 canonical route 还必须声明候选顺序、`no_fallback | qualified_equivalent`、允许 fallback 的 failure codes 与 substitution disposition。只有同一 dataset role、同一 authority class、同一 rights/persistence envelope，且每个 candidate 均独立资格化时，才可使用 `qualified_equivalent`；只允许对 policy 列出的 transient transport 或 typed unavailable code 依次尝试。每次 attempt 都持久化，替代成功只能是 `complete_with_substitution`/`partial`，并绑定失败 attempts 与实际 source identity。critical official facts 默认 `no_fallback`，不得降级到 aggregator/secondary；未声明来源、退休实现和旧路径永远不能参与 fallback。

## 9. Official evidence 与 PIT contract

每个 critical record必须绑定：

- canonical security/issuer/listing/source identity；
- raw object SHA-256、MIME、size和terms profile；
- event/report/period identity；
- `published_at`；
- 有证据的 `available_at` 与 basis；
- repository-owned `retrieved_at`；
- timezone/precision；
- correction/amendment/restatement/supersedes；
- completeness/page/shard/coverage；
- unit/currency/scale/statement scope；
- source policy/query/adapter/code identity。

规则：

- unknown 永远不是 zero；
- unavailable/ambiguous `available_at` 不得由 `published_at` 猜测；
- raw HTML/PDF/JSON/free text只能是 source artifact，不能直接成为 typed fact/result；
- caller-authored fact、manifest、hash或pass boolean不能授权自己；
- official authority不自动授予automation/cache/derived/redistribution rights；
- rights不允许持久化时，该 source不能进入需要持久化/replay的正式路径。

## 10. ResearchWorkflowRequest@2

目标公开 contract：

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

不再允许：

- `ResearchProjection.manifest` / `estimates`；
- free-mapping `ResearchInputs`；
- caller member classifications；
- `analysis_artifacts`；
- raw provider/report payload；
- caller-authored artifact/content hash。

workflow加载并核验 snapshot subject、cutoff、content hash、policy identity、membership/coverage和quality。plan canonical hash进入 request fingerprint、replay identity与artifact policy identity。

## 11. ResearchEvaluationPlan@1

目标 fields：

```text
schema_version
purpose
horizon(as_of, forecast_end, review_by)
required_dimensions
disconfirming_evidence policy
typed scenario selection
typed valuation-method intent
typed assumption overrides + evidence refs
valuation simulation policy
market-path simulation policy
strategy-validation selection
allowed degradation policy
```

closed unions 覆盖 purpose、dimension、valuation method、scenario、distribution family、dependency/correlation model、degradation和strategy selection。所有数值用 Decimal-compatible string；seed/sample budget/convergence显式且有versioned bounds。

plan不能选择 provider、source authority、adapter、engine、module、class、endpoint、MCP tool、registry key或financial-output bypass。canonical method router、source/PIT/per-share/output gates拥有最终否决权。

## 12. ResearchEvaluation result 与 artifact contract

```text
ResearchEvaluation.evaluate(
  plan,
  FrozenResearchEvidence,
  source_policy_identity
) -> ResearchEvaluationResult
```

result：

```text
status: ready | partial | blocked
reason_codes
dimension results
Forecast | none
ScenarioValuation | none
ValuationSimulation | none
MarketPathSimulation | none
StrategyValidationResult | none
publication permissions
plan identity
input/output fingerprints
```

workflow—not caller—使用专用 factories 创建 DataSnapshot、Forecast、Valuation、Simulation、MarketPath、ForecastReview artifacts。每个 artifact绑定：

```text
schema/kind/content hash
research/workflow run identity
data/model snapshot identity
security/subject/as_of
source/input/model/formula/code/policy identities
status/summary
typed parent relations
```

WorkflowLedger 在一个 transaction 中写 checkpoint、artifact records、relations、manifest、run refs和transition；raw file/report不能绕过 ledger。

## 13. StrategyValidation boundary

当前 production state：

```text
capability = unavailable
production adapters = 0
Vibe allowlist = []
```

因此当前实现仅允许：

```text
not_requested
或
blocked + STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE
result = null
artifact = none
```

当前不得创建 `StrategyValidationPort`、`VibeTradingMcpAdapter`、fake engine、table、migration、artifact kind、CLI/Web route或placeholder config。

未来重新资格化时，完整的一个原子 slice必须同时具备：

- declarative Strategy identity/code/config hash；
- frozen security/universe membership；
- snapshot/source/calendar/adjustment/corporate-action identity；
- purged/embargoed Walk-Forward folds；
- signal lag/next tradeable price；
- T+1、停牌、涨跌停、lot、fee、slippage、volume/partial-fill；
- benchmark；
- block bootstrap/statistical algorithm/version/seed/budget/convergence；
- IS/OOS metrics、drawdown、turnover、cost/fill/unfilled/invalid；
- look-ahead/survivorship/coverage diagnostics；
- engine/code/dependency/result/artifact hashes；
- real caller、ledger lineage、DecisionView migration（若需要）、public acceptance。

在同一 slice 之前不得提交任何生产类型。

## 14. Financial、source、privacy 与 fail-closed gates

### 14.1 Source/data

- critical fact 必须有 official authority与 `source_id`，否则 marked missing；
- missing official source => no formal valuation/rating/target；
- less than 3 usable peers => comps不能支持 conclusion；
- provider/tool unavailable => typed failure，不造数据、不fallback；
- A-share Tushare-compatible gateway identity按实际非官方兼容网关记录。

### 14.2 Valuation

- 先跑 valuation method router；
- DCF 前跑 applicability gate；
- financial firms禁用 ordinary FCFF/WACC DCF；
- biopharma route rNPV/SOTP/cash runway；
- cyclical/resource route mid-cycle/NAV；
- diluted shares、pension deficit、SBC dilution或equity bridge缺失时 per-share fail-closed；
- incompatible value/market basis => `not_comparable`。

### 14.3 Financial output

默认正式输出只用：

```text
valuation_view
risk_reward_summary
data_quality_grade
key_uncertainties
what_would_change_the_view
```

禁止 personalized BUY/HOLD/SELL、买入/卖出/持有、add/trim/exit、仓位、收益承诺或无门禁目标价。只有 explicit `user_requested_rating=true` 且全部 data/output gates pass 时允许有边界的 rating language。

### 14.4 Privacy/security

- credentials只由 approved credential adapter读取，不进 jobs/logs/artifacts/database/backups；
- external probes禁止个人账户、持仓或券商数据；
- endpoint host allowlist、TLS hostname verification、bounded sizes、timeouts与redacted diagnostics；
- no arbitrary file/user-home writes、dynamic import、subprocess generated code、web/search/memory/swarm/broker/order；
- Web只读 canonical persistence，不直连 provider。

## 15. Typed failure matrix

| Layer | Representable outcome/failure |
|---|---|
| Job/request admission | schema unsupported、field/path invalid、identity/PIT mismatch |
| Rights/network | rights blocked、network unauthorized、access forbidden、auth failed |
| Transport | DNS/connection/timeout/rate-limited/HTTP/oversize/MIME |
| Parser | malformed/schema mismatch/wrong security/unit/context/coverage |
| Data quality | empty confirmed/partial/stale/missing/quarantine/blocking |
| Research | dimension incomplete、disconfirming evidence missing、source insufficient |
| Valuation | method not applicable/input missing/not comparable |
| Strategy | not requested/capability unavailable/data incomplete/nonconvergent/partial folds |
| Persistence | identity conflict/hash mismatch/immutable/transaction/backup/restore |

Expected insufficiency produces typed partial/blocked result。contract/integrity violation在执行前或 owning substep失败；transient transport可 retryable。application diagnostics只含 stable code、retryability、substep和redacted cause type，不泄漏 raw payload、URL params、path、secret或generic error。

## 16. Schema 与 one-way migration

### 16.1 Provider config and qualification receipt cutover

- 唯一新 config schema 是 `ProviderJob@2`；old job立即拒绝，无 default、alias或dual decoder。
- canonical `provider-qualify` 必须把 production command receipt、request/query/source-policy identity、provider/adapter/code identity、attempt/raw/snapshot hashes和时间边界注册到 data root，返回 `ProviderQualificationReceipt@1` artifact id。
- `acceptance` 只接受该 artifact id并回查 ledger/object/command receipt；删除任意 caller-authored `--live-qualification-file`、JSON或boolean授权路径。
- I01不改变database schema；使用当前 artifact/command receipt ownership。

### 16.2 Migration `0013_source_policy_official_evidence.sql`

Migration 0013 的唯一目标结构如下；实现不得自行发明第二套 policy、rights或official-fact schema：

- `query_policy_record(query_policy_identity TEXT PRIMARY KEY, schema_version TEXT NOT NULL CHECK(schema_version='QueryPolicy@1'), content_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL, created_at TEXT NOT NULL)`。
- `source_policy_record(source_policy_identity TEXT PRIMARY KEY, schema_version TEXT NOT NULL CHECK(schema_version='SourcePolicy@1'), content_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL, created_at TEXT NOT NULL)`；typed codec验证 routes、authority、rights、fallback mode/codes，DB只保存canonical bytes。
- `source_rights_profile(rights_profile_id TEXT PRIMARY KEY, subject_type TEXT NOT NULL CHECK(subject_type IN ('source','fixture_member')), subject_id TEXT NOT NULL, source_identity TEXT NOT NULL, terms_version TEXT NOT NULL, automation_allowed INTEGER NOT NULL CHECK(automation_allowed IN (0,1)), local_storage_allowed INTEGER NOT NULL CHECK(local_storage_allowed IN (0,1)), derived_use_allowed INTEGER NOT NULL CHECK(derived_use_allowed IN (0,1)), repository_redistribution_allowed INTEGER NOT NULL CHECK(repository_redistribution_allowed IN (0,1)), packaged_distribution_allowed INTEGER NOT NULL CHECK(packaged_distribution_allowed IN (0,1)), reviewed_on TEXT NOT NULL, evidence_sha256 TEXT REFERENCES object_blob(sha256), UNIQUE(subject_type,subject_id,terms_version))`；它单向取代 `fixture_rights_profile`，fixture rows逐项迁移后删除旧表。
- rebuild `provider_attempt`，保留0002所有列并新增 `query_policy_identity TEXT NOT NULL REFERENCES query_policy_record`, `source_policy_identity TEXT NOT NULL REFERENCES source_policy_record`, `rights_profile_id TEXT NOT NULL REFERENCES source_rights_profile`；status closed set加入 `empty`、`complete_with_substitution`，禁止 placeholder/default。
- rebuild `data_snapshot`，把 `query_policy_version`/`source_policy_version` 替换为 non-null `query_policy_identity`/`source_policy_identity` FKs；unique key同步使用两项identity。
- `official_filing_version(normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version, security_id TEXT NOT NULL REFERENCES security, issuer_identity TEXT NOT NULL, authority TEXT NOT NULL, document_identity TEXT NOT NULL, accession_or_document_id TEXT NOT NULL, filing_type TEXT NOT NULL, report_period_end TEXT, document_object_sha256 TEXT NOT NULL REFERENCES object_blob, content_type TEXT NOT NULL, byte_size INTEGER NOT NULL CHECK(byte_size>=0), correction_status TEXT NOT NULL CHECK(correction_status IN ('original','amended','corrected','superseded')), filing_identity_hash TEXT NOT NULL UNIQUE)`；published/available/retrieved与supersedes只取 owning `normalized_version`。
- `financial_fact_version(normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version, filing_normalized_version_id TEXT NOT NULL REFERENCES official_filing_version, taxonomy TEXT NOT NULL, concept TEXT NOT NULL, context_identity TEXT NOT NULL, period_start TEXT, period_end TEXT, instant TEXT, unit TEXT NOT NULL, currency TEXT, scale INTEGER NOT NULL, value_decimal TEXT NOT NULL, statement_scope TEXT NOT NULL, source_fact_identity TEXT NOT NULL, fact_identity_hash TEXT NOT NULL UNIQUE, CHECK((instant IS NOT NULL AND period_start IS NULL AND period_end IS NULL) OR (instant IS NULL AND period_end IS NOT NULL)))`。
- new policy/rights/official tables与rebuilt attempt/snapshot均有 identity-column update trigger和no-delete trigger；只允许同值 idempotent insert，不允许 late mutation。

Backfill mapping是确定的：对每个旧 attempt，以其现有 dataset/provider/adapter/source/authority/terms字段生成 canonical QueryPolicy@1、SourcePolicy@1和rights record；同一旧 tuple必须映射同一content hash。snapshot只可由其members的attempt identities得到唯一 pair。任何空 member、混合 identity、hash conflict或无法证明rights的row使transaction失败 `SOURCE_POLICY_IDENTITY_UNMIGRATABLE`。不得修改0001–0012。

### 16.3 Migration `0014_research_evaluation_cutover.sql`

Migration 0014 的目标结构：

- `research_evaluation_plan_record(evaluation_plan_id TEXT PRIMARY KEY, schema_version TEXT NOT NULL CHECK(schema_version='ResearchEvaluationPlan@1'), content_hash TEXT NOT NULL UNIQUE, plan_artifact_id TEXT NOT NULL REFERENCES artifact, source_request_artifact_id TEXT REFERENCES artifact, data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot, security_id TEXT NOT NULL REFERENCES security, as_of_date TEXT NOT NULL, policy_identity TEXT NOT NULL, disposition TEXT NOT NULL CHECK(disposition IN ('active','historical_migrated_read_only')), created_at TEXT NOT NULL)`，含identity update/no-delete triggers。
- rebuild `research_run_record` 为 `(research_run_id PK, research_input_fingerprint, evaluation_plan_id FK, research_snapshot_id FK, request_fingerprint, engine_schema_version, engine_code_identity, original_cutoff_date, status, decision_manifest_id FK artifact_manifest, UNIQUE(research_input_fingerprint,engine_code_identity))`；删除 `research_projection_id` 和固定 JSON/HTML artifact columns。
- 删除 active `research_input_projection` table；旧 projection/request bytes只保留为 immutable artifact，并由 `source_request_artifact_id`审计引用。
- research workflow 的 `workflow_run_request` new insert trigger要求 `request_schema_version='ResearchWorkflowRequest@2'`；其他 workflow schema不受影响。

迁移前必须确认旧 workflow terminal、source request/projection/DecisionView/HTML/manifest/object hash-valid。migrate-only typed decoder固定在 `trading_platform.persistence.migrations.research_evaluation_0014`，只由 MigrationRunner在schema<14时调用；application/CLI/Web/server/recovery模块不得import，且迁移后没有Request@1 runtime decoder、resume/replay、cutover reader或fallback。历史 plan只封装已有identity和audit artifact，不解释free facts。任一 queued/running workflow、非唯一projection、缺失artifact、hash mismatch或不一致identity使整个migration失败并恢复backup。

### 16.4 Backup/restore

- backup-first并验证hash、size、object count、SQLite integrity/FK；
- 每个migration单transaction，fault injection证明rollback；
- restore只到new root并验证schema/object/artifact/domain invariants；
- rollback只能恢复整个pre-migration backup并运行old binary，不是new-runtime dual path；
- 不为StrategyValidation预留migration、table、artifact kind或config。

## 17. Blocker-first implementation and planning issues

这些 slices 在票11审计通过、`/to-spec`核验且`/to-tickets`发布后执行。随后先创建只含本 effort planning assets 的baseline commit。I01–I04每票是完整production vertical slice和一个local commit；I05是目标明确的post-implementation planning backwrite和一个local commit。最终release proof是Goal gate，不是“以后清理”票。

### I01 — ProviderJob@2、SourcePolicy 与 qualification receipt cutover

Blocked by: none。

同票完成 typed query/source policy、Tushare-compatible/Fixture `DataProvider` path、static composition、public sync/daily/provider-qualify/acceptance callers、qualification receipt persistence、tests/docs/config/operations；schema明确不变。删除 `provider_type`、class lookup、generic `HttpJsonProvider`、orchestration Tushare wire params、implicit provider-order fallback、old job codecs/docs/tests/examples/exports和caller-authored live evidence。运行narrow tests、absence gates和完整canonical verifier。

### I02 — A股 official-disclosure vertical slice 与 migration 0013

Blocked by: I01。

同票完成0013全部schema/backfill/restore、CNINFO与SZSE clean-room production adapters、existing deterministic `FixtureProvider` adapter coverage、public sync/qualify callers、raw object/typed filing persistence、snapshot membership、rights/PIT/identity/failure gates、target fixtures/live receipt/docs/NOTICE。A股PDF在本票只形成filing identity/metadata/raw hash；未另行资格化的PDF语义抽取不得生成financial facts。删除旧rights表、placeholder policy identities、direct SQL/caller fact fixtures、cleartext/guessed-ID/disabled-TLS/raw-text/aggregator fallback。首次新DataProvider进入production后运行完整canonical verifier。

### I03 — SEC official-disclosure vertical slice

Blocked by: I02。

同票在0013唯一schema上完成SEC submissions/companyfacts/Archives production adapter、FixtureProvider deterministic coverage、truthful User-Agent/rate/Retry-After、CIK/accession/context/unit/amendment/coverage/PIT/hash、public sync/qualify、raw/filing/fact/snapshot persistence、live receipt/docs/NOTICE；schema无新增。删除generic/ticker-only/caller SEC facts、raw SEC→research path及aggregator/Skill fallback。不得建HKEX/IR registry。运行narrow suites和完整canonical verifier。

### I04 — Request@2、ResearchEvaluation、migration 0014 与 canonical PDF

Blocked by: I03。

同票完成ResearchEvaluationPlan@1、Request@2 codec与全部CLI/daily/browser/workflow/recovery callers、concrete ResearchEvaluation、workflow-owned artifact factories、0014 historical cutover、WorkflowLedger query/atomic commit、View@2-derived JSON/HTML/PDF/XLSX/Web/archive、real-browser与PDF render verification、docs/config/generated assets。

在新增行为前必须记录并执行超大文件职责审计：

- 从 `domain/workflow.py` 抽出拥有research artifact/plan canonicalization、invariants与fingerprints的完整 `domain/research_evaluation.py`，不是contracts转发文件；
- 从 `workflows/research.py` 抽出拥有source/PIT/quality、forecast/valuation/simulation/publication orchestration的concrete `ResearchEvaluation`；workflow只拥有lifecycle/checkpoints；
- 从 `persistence/workflow_ledger.py` 抽出私有、事务完整的research artifact commit behavior；`WorkflowLedgerPort`仍是唯一public persistence owner，不新增镜像port或转发API；
- migrate-only Request@1 behavior只存在于16.3指定migration namespace。

同票删除Request@1/ResearchProjection/free mappings/caller manifests/estimates/member classification/analysis artifacts、`ImmutableArtifactDraft.from_serialized`、ResearchRunner fake variation、research-view cutover/materializer/runtime gates/faults/tests、old projection schema/examples/docs和所有旧presentation reader。Research/valuation不得写account、TradePlan、PlanEvaluation、authorization或order state。运行narrow suites、0014 matrix、完整canonical verifier、Web build/real browser与PDF verification。

### I05 — 回写 portfolio-aware weekly-discipline 当前规划

Blocked by: I04。

重新审计 `.scratch/portfolio-aware-weekly-discipline/`，只更新以下六张开放票，使其明确引用新的SourcePolicy/official evidence/ResearchEvaluationPlan/View@2 architecture、capability-unavailable StrategyValidation与真实acceptance seam：MarketRegime v2数据、持仓研究门控、每周驾驶舱、计划/指标合同、真实旅程验收、最终implementation Spec。不得重开已resolved账户/日终票，不实现新产品功能。验收为六文件精确diff、resolved历史零改动、该Map frontier仍真实、adoption Spec与six-ticket links一致。

## 18. Same-issue surface ledger

| Issue | Caller/application | Persistence/schema | Presentation | Tests/docs | Mandatory deletion |
|---|---|---|---|---|---|
| I01 | sync/daily/qualify/acceptance | current artifact/receipt owners; no schema change | unchanged | config/task/operations/full verifier | old codec/dispatch/fallback/caller JSON |
| I02 | public sync/qualify A roles | 0013 + raw/filing/snapshot | View@2 unchanged | fixtures/live receipt/restore/docs/full verifier | old rights/placeholders/direct SQL/unsafe A paths |
| I03 | public sync/qualify SEC role | exact 0013 tables; no new schema | View@2 unchanged | fixtures/live receipt/docs/full verifier | generic/caller/raw SEC and aggregator paths |
| I04 | all research callers Request@2 | 0014 + ledger query/atomic commit | View@2 JSON/HTML/PDF/XLSX/Web/archive | public/recovery/browser/PDF/docs/full verifier | all Request@1/projection/cutover/old readers |
| I05 | no production caller | planning assets only | planning references only | six-ticket diff/link/frontier checks | stale planning assumptions only |

如果任一production issue需要old/new runtime同时存在才能通过，扩大该issue直到能原子删除；不创建compatibility follow-up。每票结束即完成owning cleanup；最终Goal gate只验证，不替任何issue收尾。
## 19. NOTICE、归属、依赖与升级

### 19.1 Current queue

- Python runtime dependencies应保持空，除非 stdlib不足由独立 dependency qualification证明。
- 不 vendor、不 submodule、不安装三个 upstream，不复制 source。
- clean-room protocol adapters属于本项目；当前不新增 Apache/MIT runtime NOTICE payload。
- research evidence保留 repository/commit/tag/license/file hashes与protocol attribution。
- provider data rights独立于 code license。

### 19.2 Code-copy gate

任何结构性/逐行复制都必须先重新分类为 external adoption，并在生产修改前完成：

- copied source commit/file hashes；
- license/NOTICE/transitive dependencies；
- project third-party notices；
- security/rights/failure qualification；
- unique runtime path与旧实现删除；
- public/release acceptance。

### 19.3 Upgrade gate

upstream、endpoint、schema、terms、entitlement、UA/rate policy或target parser变化必须新开qualification ticket并：

1. pin full commit/file hashes；
2. diff protocol/field/unit/time/identity/security surface；
3. review primary terms和data uses；
4. rerun normal/empty/partial/drift/wrong identity/error fixtures；
5. rerun controlled live/official cross-check；
6. rerun three-market verifier/tamper；
7. rerun policy/PIT/lineage/financial/privacy gates；
8. lock schema/NOTICE/deletion；
9. atomically update adapter/policy/fixtures/docs；
10. delete old version，不双版本/fallback。

## 20. Phase acceptance

所有命令从repo root、项目当前Python环境执行；外部网络状态必须记录，skip/timeout不是pass。I01、I02、I03、I04的narrow suite之后均执行 `python -m trading_platform.cli test --repo-root .`；I02覆盖首个新DataProvider production gate，I04覆盖WorkflowLedger/schema/identity migration与Web/presentation切换gate。

### 20.1 Narrow and phase-gate commands

I01：

```powershell
python -m pytest -q tests/platform/test_data_sync_pit.py tests/platform/test_provider_qualification.py tests/platform/test_cli_application_tasks.py tests/platform/test_acceptance_evidence.py
python -m trading_platform.cli test --repo-root .
```

I02：

```powershell
python -m pytest -q tests/platform/test_data_sync_pit.py tests/platform/test_provider_qualification.py tests/platform/test_external_official_disclosure.py tests/platform/test_operations_backup_restore.py
python -m trading_platform.cli test --repo-root .
```

I03：

```powershell
python -m pytest -q tests/platform/test_data_sync_pit.py tests/platform/test_provider_qualification.py tests/platform/test_external_official_disclosure.py
python .scratch/external-equity-capability-adoption/research/verify_market_validation_slices.py
python -m trading_platform.cli test --repo-root .
```

I04：

```powershell
python -m pytest -q tests/test_forecast_graph.py tests/test_research_engine.py tests/platform/test_research_workflow.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_company_outlook_journeys.py tests/platform/test_decision_research_view.py tests/platform/test_web_application_tasks.py tests/platform/test_valuation_workbook_adapter.py tests/platform/test_research_decision_pdf.py
python -m trading_platform.cli test --repo-root .
Push-Location web
npm test
npm run build
Pop-Location
python scripts/verify_issue05_browser.py --keep-artifacts --evidence-file .scratch/external-equity-capability-adoption/phase-i04-browser-evidence.json
```

I04还必须运行Request@1/cutover/free-mapping/caller-artifact absence gate、0014 fresh/prior/populated/fault/restore matrix，以及PDF MIME/schema/hash/page/render一致性检查。I05运行六张票的exact-path diff/link/status validator，并证明resolved history零改动。

### 20.2 Data-adapter acceptance matrix

每个production adapter及其deterministic fixture replay必须逐格产生typed evidence；与该dataset无语义关系的格只能记录 `not_applicable` + typed reason，不可记pass。

| Case | Tushare structured market | CNINFO/SZSE filing | SEC filing/facts |
|---|---|---|---|
| normal / legal empty / partial / stale | 各自fixture + status | 各自fixture + status | 各自fixture + status |
| rate limit / 401 / 403 / timeout | typed transport/auth outcome | typed transport/auth outcome | typed transport/auth outcome incl Retry-After |
| schema drift / wrong security identity | reject before snapshot | reject before snapshot | reject CIK/accession/listing mismatch |
| published/available/retrieved | all three or typed N/A basis | all three, no published→available guess | all three, amendment availability preserved |
| trading calendar | required fixture/live role | `not_applicable: filing_dataset` | `not_applicable: filing_dataset` |
| adjustment/corporate action | supported roles prove behavior; unsupported role is typed unavailable | `not_applicable: filing_dataset` | facts amendment/correction tested; price adjustment N/A |
| suspension/price limit/T+1 | supported role proves constraints or typed unavailable | `not_applicable: filing_dataset` | `not_applicable: filing_dataset` |
| authority/rights | gateway identity not official disclosure | official authority plus per-source rights | official authority plus SEC access policy |
| real connectivity | one canonical provider-qualify receipt | one controlled identity-bound receipt per production source | one CIK/accession-bound receipt |

合法empty必须由source response semantics证明；transport/outage/permission/parse error永远不能折叠为empty。A股PDF在无独立semantic extractor时只验证document identity、MIME/size/hash和malicious-content quarantine，不产生critical financial facts。

## 21. Final acceptance

### 21.1 Full verifier and presentation

```powershell
python -m trading_platform.cli test --repo-root .
Push-Location web
npm test
npm run build
Pop-Location
python scripts/verify_issue05_browser.py --keep-artifacts --evidence-file .scratch/external-equity-capability-adoption/final-browser-evidence.json
python -m pytest -q tests/platform/test_research_decision_pdf.py tests/platform/test_valuation_workbook_adapter.py
```

报告每个named suite、duration、pass/fail/timeout/skip与redacted failure；all discovered tests恰好一次。production bootstrap、real CDP、reload/restart、keyboard/narrow viewport/reduced motion、hashed dist assets、View@2 JSON/HTML/PDF/XLSX一致性均required。PDF renderer/dependency若不合格，I04与Goal不通过，不能以raw upstream PDF替代。

### 21.2 Release acceptance and live proof

```powershell
python -m pytest -q -m release_acceptance tests/platform/test_acceptance_evidence.py
python -m trading_platform.cli acceptance `
  --data-root <fresh-data-root> `
  --fixture-manifest tests/fixtures/platform_data/manifest.json `
  --repo-root . `
  --live-qualification-artifact-id <ProviderQualificationReceipt@1-artifact-id>
```

production verifier必须从data root回查由canonical `provider-qualify`实际生成的command receipt、request/policy/provider/code/run identities、attempt/raw/snapshot hashes和object bytes；任意caller file、JSON、boolean、孤立hash或字段自述均被拒绝。A/SEC required live receipt缺失、identity不匹配或过期时不能声称production qualified。

### 21.3 Migration/restore matrix

针对fresh、0012 populated、fault-injected roots分别执行：

```powershell
python -m trading_platform.cli backup --data-root <old-root> --archive <backup.zip>
python -m trading_platform.cli migrate --data-root <old-root>
python -m trading_platform.cli doctor --data-root <old-root>
python -m trading_platform.cli history --data-root <old-root> --workflow-run-id <id>
python -m trading_platform.cli archive --data-root <old-root> --kind manifest --id <id>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <restored-root>
python -m trading_platform.cli doctor --data-root <restored-root>
```

核对migration hashes、SQLite integrity/FK、object hashes/counts、policy/rights/official/evaluation-plan identities、old audit objects、Request@2 new writes、unique DecisionViews、rollback与identity-stable retry。queued/running old workflow、mixed policy members、unprovable rights与corrupt old artifact必须fail closed。

### 21.4 Cleanup and git

- 每票及最终运行 `git diff --check`、forbidden-symbol/dependency/generated-asset/current-doc searches、完整status/diff/staged diff inspection；
- 每票只精确stage owning paths，一票一个local commit；baseline commit只含本effort planning assets；
- preserve startup dirty/untracked user assets；不push/PR；
- final Goal gate复跑full verifier、live receipts、Vibe adversarial evidence（当前reject结论仍与pinned evidence一致）、Web/browser/PDF、license/NOTICE和final code review。

## 22. Acceptance Criteria

### Data/provider

- [ ] ProviderJob@2是唯一production job schema；SourcePolicy routes/fallback可审计且critical official no-fallback。
- [ ] DataSyncService不构造wire params、不做未声明provider fallback；concrete adapters拥有protocol/parser/failure。
- [ ] policy/rights identities非placeholder；official facts只经public sync/persistence进入snapshots。
- [ ] A股/SEC adapters逐格通过20.2 target fixtures与identity-bound live receipts。
- [ ] HK/Public Equity/Vibe/aggregators没有runtime surface。

### Research/presentation

- [ ] Request@2是唯一active research request，caller只提交snapshot refs + plan。
- [ ] ResearchEvaluation只经WorkflowLedgerPort读取frozen evidence并构造artifacts。
- [ ] Forecast/valuation/value simulation/market path/strategy semantics和identities保持分离。
- [ ] StrategyValidation unavailable不产生result/artifact且不创建port/route/config。
- [ ] View@2是JSON/HTML/PDF/XLSX/Web/archive唯一presentation model；renderers不重算语义。
- [ ] research/valuation不写account、TradePlan、PlanEvaluation、authorization或order state。

### Migration/deletion/modularity

- [ ] 0013/0014按16节唯一schema backup-first、transactional、fail-closed；old bytes只audit，无runtime decoder。
- [ ] Request@1/projection/free inputs/caller artifacts/runner/cutover及provider dispatch/generic helper/fallback/placeholders删除。
- [ ] I04三项>600-line owner完成有行为意义的拆分；无helpers/common/utils/forwarders、镜像port或第二persistence path。
- [ ] old tests/docs/examples/dependencies/generated assets同步清理。

### Safety/release/planning

- [ ] official-source、PIT、unknown-not-zero、rights、financial output、privacy/TLS/size/redaction gates通过。
- [ ] raw/caller authority、hindsight、wrong identity、malicious document和artifact tampering attacks被拒绝。
- [ ] 所有phase full gates、final verifier、migration matrix、workbook、Web/real browser、PDF和release acceptance通过，无required skip/timeout。
- [ ] 六张portfolio-aware开放票完成精确回写；resolved账户/日终历史未改写。
- [ ] 每票独立local commit；final status/diff只含授权effort changes与原有user assets。

## 23. Explicit non-goals

- auto/real/simulated broker trading、order lifecycle、盘中做T；
- personalized buy/sell/hold、仓位或收益承诺；
- Public Equity runtime、商业provider entitlement推断；
- entire external Skill/App/MCP/Web/persistence adoption；
- HKEX website scraping或未授权feed；
- external target/rating/recommendation；
- StrategyValidation placeholder或Vibe wrapper；
- second CLI/Web/report/database/artifact graph；
- compatibility aliases、dual read/write、legacy fallback、service locator；
- 实现六张portfolio discipline票所规划的新产品功能；本Goal只回写其当前规划。

## 24. Adversarial audit disposition and implementation preconditions

Standards + Spec独立审计的blockers已在本版关闭：decision enum、vertical slices、cleanup ownership、large-file deepening、portfolio backwrite、PDF、declared fallback、phase full gates、live proof、adapter matrix和0013/0014 schema均有唯一owner与acceptance。八视角失败用例及逐finding closure记录在 `research/adoption-spec-adversarial-audit.md`。

以下是implementation必须验证的preconditions，不是Wayfinder fog或已完成事实：A/SEC production adapters与live receipts尚未实现；A股raw document/security identity需在I02绑定；SEC operator contact需在I03配置；persisted roots需通过0013/0014 preflight；PDF renderer需在I04资格化。HKEX entitlement、Public Equity plugin和StrategyValidation当前分别维持reject/external_blocked/unavailable，不阻塞已选canonical path。

Fog: none。剩余工作是已明确的I01–I05 delivery queue，不是未决架构问题。

## 25. Published implementation frontier

- Wayfinder tickets 01–11 are resolved; Map is resolved and fog is empty.
- [12 / I01 ProviderJob@2、SourcePolicy 与 qualification receipt cutover](issues/12-i01-provider-source-policy-receipt-cutover.md) — `ready-for-agent`, no blockers, current frontier.
- [13 / I02 A股 OfficialDisclosure 与 migration 0013](issues/13-i02-a-share-official-disclosure-0013.md) — blocked by 12.
- [14 / I03 SEC OfficialDisclosure](issues/14-i03-sec-official-disclosure.md) — blocked by 13.
- [15 / I04 ResearchEvaluation、Request@2、migration 0014 与 PDF](issues/15-i04-research-evaluation-0014-pdf.md) — blocked by 14.
- [16 / I05 portfolio-aware planning backwrite](issues/16-i05-backwrite-portfolio-discipline-planning.md) — blocked by 15.
- `/to-spec` published-contract verification and `/to-tickets` publication are complete. After ticket audit, create one baseline local commit containing only this effort's planning assets, then claim ticket 12 in the next Goal continuation.
- This publication continuation does not start production implementation.
