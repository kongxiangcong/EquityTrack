# 持仓研究与条件估值计划门控：当前证据与 readiness 矩阵

Date: 2026-07-26
Scope: Wayfinder Issue 06 的背景研究；只核对当前 checkout 的一手源码、测试与已解决 adoption tickets，不授权实现。

## 结论

当前生产路径已经能把一个 A 股 `Security`、frozen `DataSnapshot`、
`ResearchEvaluationPlan@1` 和一次 `ResearchRun` 固定到唯一持久化
`ResearchDecisionView@2`。但它尚不能为“研究状态驱动的计划规则”提供完整
readiness：

1. 当前 A 股 official ingestion 只实现 CNINFO/SZSE document evidence；没有另行
   资格化的语义抽取器时，PDF 不得生成 critical financial facts。因而已验收的
   A 股公司旅程真实结果是 `ResearchRun.status = blocked`、
   `valuation_view.status = not_ready`，Forecast/Valuation/Simulation artifact
   refs 均为 `None`，`key_drivers/scenarios` 为空，`audit.permissions` 六项均为
   `false`。
2. `ResearchDecisionView@2` 当前保留研究、快照、模型、policy 和 plan identity，
   以及 publication permissions；但没有投影 typed snapshot freshness/quality/
   coverage、official semantic-field coverage、technical dimension result 或 typed
   event window。仅凭 `data_quality_grade`、摘要文本或总状态，不能安全重建这些
   语义。
3. 当前计划指标目录只支持证券价格/交易状态、四个 market component 和两项账户
   指标。计划版本必须引用一个已持久化 `ResearchRun`，但验证器并不检查该
   ResearchRun 的 readiness；已有测试证明 blocked research 仍可作为历史研究引用，
   同时独立评估价格、市场和账户规则。
4. 因此第一版必须按规则依赖逐项门控。公司研究、Forecast、条件估值、技术研究或
   事件字段缺失时，只阻断或标记无法判断对应规则；不得把它们塞进
   `MarketSnapshot.status` 造成所有独立规则一起阻断。用户编制/确认计划、查看历史、
   以及证据充分的价格/账户规则不应因公司估值不可用而消失。
5. `StrategyValidation` 保持 capability unavailable 且非阻断：未请求是
   `not_requested`；显式请求是 `requested_unavailable` +
   `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`。本切片不接入 Vibe-Trading，
   不产生验证结果/artifact，也不影响研究、计划编制或计划评估主流程。

范围只含 A 股。本文定义的是研究/规则能力与证据边界，不提供个性化投资建议，
不产生仓位或交易动作指令。

## 一手证据索引

| 证据 | 当前事实 |
| --- | --- |
| [`src/trading_platform/domain/research_evaluation.py`](../../../src/trading_platform/domain/research_evaluation.py), lines 10-104 | `ResearchEvaluationPlan@1` 的 closed dimensions、horizon、degradation 与 StrategyValidation 两种状态。 |
| 同文件，lines 107-217 | `ResearchWorkflowRequest@2` 只接受 frozen snapshot refs + typed plan；请求日期、effective session 和 plan as-of 必须一致。 |
| 同文件，lines 219-344 | `ResearchDecisionViewFactory` 当前投影的唯一 View@2 顶层字段、audit 内容，以及当前 `not_ready`/`not_comparable` 降级。 |
| [`src/trading_platform/research/evaluation.py`](../../../src/trading_platform/research/evaluation.py), lines 39-109 | concrete ResearchEvaluation 校验 snapshot/security/purpose/PIT/freshness/quality/member availability；missing freshness 与 blocking quality fail closed。 |
| 同文件，lines 110-172 | 当前 manifest 为 A 股/CNY/PRC-GAAP，但每次显式声明 revenue、net income、cash、debt、diluted shares 缺少 qualified semantic facts。 |
| [`src/trading_platform/research_view.py`](../../../src/trading_platform/research_view.py), lines 12-78 | View@2 的精确顶层字段；`audit` 和其他 mappings 只做结构类型检查，没有 typed nested readiness contract。 |
| [`src/equity_research/policies.py`](../../../src/equity_research/policies.py), lines 22-106, 266-345 | 每项研究/估值 capability 的 required official/sourced fields，以及 ready/limited/ready_with_estimates/blocked 判定。 |
| [`src/equity_research/engine.py`](../../../src/equity_research/engine.py), lines 197-316, 418-474 | integrity fail-closed、method routing、publication permissions、overall completed/completed_with_limits/blocked。 |
| [`src/equity_research/narrative.py`](../../../src/equity_research/narrative.py), lines 19-27, 229-293 | `technical` 与 `sentiment_events` 目前只是 ResearchRun 的 evidence-constrained narrative dimensions；status 是 ready/limited/blocked。 |
| [`src/trading_platform/domain/plans.py`](../../../src/trading_platform/domain/plans.py), lines 190-243 | 当前唯一 rule kinds/effects/metric catalog；没有 research、valuation、technical 或 event metric。 |
| 同文件，lines 246-363 | 计划必须精确引用一个 resolved `ResearchRun` 和至少一个 Evidence ref，但没有读取 View@2 readiness。 |
| [`src/trading_platform/domain/market.py`](../../../src/trading_platform/domain/market.py), lines 586-647, 650-869 | evaluator 的 triggered/not-triggered/unable/blocked/not-applicable 映射；missing metric 是 unable，blocked component 是 blocked。 |
| [`tests/platform/test_company_outlook_journeys.py`](../../../tests/platform/test_company_outlook_journeys.py), lines 13-77 | 当前 A 股 official journey、semantic-input 缺失和 StrategyValidation nonblocking 的 public-seam 证明。 |
| [`tests/platform/test_market_evaluation.py`](../../../tests/platform/test_market_evaluation.py), lines 1-220 | blocked research reference 与只读 PlanEvaluation 共存；价格/市场/账户规则按各自 evidence 评估且不改 plan lifecycle。 |
| [adoption Issue 13](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md) | CNINFO/SZSE official document vertical slice 与 0013 已解决；document evidence 不等于 semantic financial facts。 |
| [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md) | Request@2、ResearchEvaluation、0014、View@2/PDF canonical projection 已解决；研究/估值不得写账户、计划、授权或 order state。 |

## 当前 canonical dataflow 与不可跨越边界

```text
A-share Security
  + SourcePolicy@1
  + frozen DataSnapshot
  + ResearchEvaluationPlan@1
      -> ResearchWorkflow
      -> concrete ResearchEvaluation
      -> ResearchRun
      -> persisted ResearchDecisionView@2
      -> JSON / HTML / PDF / XLSX / Web / archive

persisted ResearchDecisionView@2
  + user-authored TradePlanVersion
  + separately frozen MarketSnapshot / AccountSnapshot
      -> future per-rule readiness gate
      -> deterministic PlanEvaluation
```

- Web、计划 caller 或 evaluator 不得重跑 ResearchEvaluation、读取 raw research JSON 后
  自行重建方法语义，或从文本猜测状态。
- research/valuation 是只读决策证据，不能写
  AccountSnapshot、TradePlan、PlanEvaluation、authorization 或 order state。
- Forecast、Valuation、ValuationSimulation、MarketPath 和 StrategyValidation 是不同
  语义与 identity；存在一个 artifact 不能替代另一个。
- `key_uncertainties`、`what_would_change_the_view`、`risk_reward_summary`、
  `story.summary` 等文本可以帮助用户复核，但不能成为 rule operand。
- `technical` narrative dimension 不是 `security.close_*` 或 `market.*` 的别名；
  后两者属于独立 MarketSnapshot 证据。

## View@2 逐字段 readiness 矩阵

状态语义：

- `ready`：字段存在、typed、identity/PIT/freshness/quality 均通过，并且该字段正是
  本规则所需语义。
- `limited`：核心证据可用于展示或人工复核，但缺增强字段；不能自动升级为数值条件。
  第一版机器规则统一映射为 `unable`。
- `unknown`：字段/能力未实现、未请求或 View 中没有可验证的 typed 表达；对应规则
  结果应为 `unable`。
- `blocked`：字段是本规则必需项，且存在已知 identity、PIT、quality、freshness、
  official-source 或 method gate 失败。
- `nonblocking_unavailable`：只用于 StrategyValidation；不参与第一版 readiness 合取。

| Gate / View 来源 | `ready` 必要条件 | `limited` / `unknown` | `blocked` | 当前 checkout |
| --- | --- | --- | --- | --- |
| View identity：`schema_version`, `view_id`, `workflow_run_id`, `research_run_id`, `security_id`, `data_snapshot_id`, `as_of`, `model_identity`, `policy_identity` | schema=`ResearchDecisionView@2`；holding/plan security 精确等于 View security；所有 ID 非空且从 persisted view 加载；编制时选中的 exact View/Run/Snapshot/readiness identity 已冻结进 PlanVersion；snapshot/view hashes 可解析 | 没有适用的 research run 是 `unknown`；可以提示创建 canonical data-insufficient View，但不得借其他证券/日期的 view | 任一 identity mismatch、tamper、future-as-of、artifact resolution failure，或评估时动态 `latest` lookup | 字段已存在；这是当前唯一可直接判定为可实现的研究门控基础 |
| A 股 scope | security master 证明标的是沪深北 A 股，且 holding、snapshot、View 指向同一 stable security identity | instrument/venue 未知 | 非 A 股或 identity 冲突 | View 只有 `security_id`；market/instrument type 仍须由 canonical Security task 验证，不能从 ticker 文本猜测 |
| Evaluation intent：`audit.evaluation_plan`, `audit.evaluation_plan_identity` | plan schema、purpose、horizon、required dimensions 与 identity 一致；所消费维度确实被请求 | 某维度未请求时该维度为 `unknown`，不是 failure | plan identity/hash 不一致 | 已投影，可用 |
| Source policy：`audit.source_policy_identity` | 与 frozen DataSnapshot 的实际 `SourcePolicy@1` identity 精确一致 | identity 存在但没有 admission detail，只能证明 policy 绑定，不能证明字段 ready | 空、placeholder、mismatch | 已投影 identity；尚不足以单独判定 official/freshness readiness |
| Snapshot/PIT admission：应含 `freshness_status`, `stale_by_days`, `quality_status`, coverage, effective session, cutoff, calendar/source/freshness policy identities 和 member availability | pinned research snapshot 被纳入当次 PlanEvaluation frozen evidence bundle；按当次 effective session/PIT cutoff 和其 freshness policy 重判为 valid；quality=`pass`/允许的 warning；coverage 满足该维度；all `available_at <= cutoff`；PIT/security/scope 一致 | optional coverage 缺失可 limited；字段未投影或 capability 未实现为 `unknown -> unable` | missing/stale required input、blocking/quarantine、coverage missing、PIT/identity conflict；不能用 `research.as_of <= cutoff` 代替 freshness admission | ResearchEvaluation 内部执行部分校验；fixture 实测的 View@2 `audit` 不含 typed freshness/quality/coverage/official-source summary。计划 gate 当前不能复核，已请求的研究依赖项保持 blocked，未实现维度保持 unknown |
| Official semantic coverage：应按 field 给出 authority、evidence ID、period/unit/currency、published/available/retrieved 和 readiness | 本规则所需 critical fields 全部解析到 qualified official semantic facts | 辅助行情/secondary 只能补充 context；estimate 只能维持明确 limited | required official field missing/stale/conflicted/quarantined，或该 venue source 尚未实现 | CNINFO/SZSE document ingestion ready；semantic facts unavailable。SSE/BSE/IR ingestion 仍 unavailable；所有需要 critical financial facts 的规则 blocked |
| Overall research：`status`, `data_quality_grade`, `audit.permissions` | overall `completed`/`completed_with_limits` 且目标维度 permission 为真；仍须继续检查 dimension/method | overall limited 只允许逐维度判断；`data_quality_grade` 不可替代具体证据 | `status=blocked`、integrity error 或所需 permission=false | 当前 official fixture journey 为 `blocked` / `insufficient`，`audit.permissions` 全 false |
| Company research（plan-consumer dimension） | EvaluationPlan 已请求 `source_quality`；ResearchRun 无 integrity failure 且 overall 非 blocked；typed evidence admission、required official semantic coverage 和 typed story 均 ready；`audit.permissions.research_report=true`。其他维度造成的 overall=`completed_with_limits` 不改变本维度结果 | 未请求 `source_quality` 为 `unknown -> unable`；company 自身 admission/official coverage/story 核心可用但有限为 `limited -> unable`，仅展示/人工复核。不能因 Forecast/valuation 等别的维度受限而降级 company | 已请求 `source_quality`，但 integrity/overall blocked、company admission blocked、report permission false、typed story blocked 或 required official semantic coverage 缺失 | `company_research` 不是 EvaluationDimension enum，而是上述 plan-consumer 合取。当前已请求 `source_quality`，但 overall blocked、permission false、semantic facts 缺失，故 blocked |
| Forecast：`forecast_artifact_record_id`, `story`, `key_drivers`, `scenarios` | non-null artifact ref；artifact identity、security/snapshot/as-of/forecast horizon 与 View 一致；typed Forecast status ready；drivers/scenarios 指向同一 artifact | 未请求/能力未实现为 `unknown -> unable`；partial Forecast 仅供人工复核并映射 `unable`；只有 story 文本不能升级 readiness | 已请求但 artifact 缺失、artifact mismatch、required official inputs/PIT invalid 或 Forecast status blocked | 当前 evaluation plan 请求 Forecast，但 artifact ref=`None`、story blocked、drivers/scenarios empty，故 blocked |
| Scenario valuation：`valuation_artifact_record_id`, `valuation_view`, `value_market_divergence` | EvaluationPlan 已请求 `valuation`；non-null artifact ref；selected method applicability ready/caution-as-explicit-policy；required official inputs、currency/unit/equity bridge 完整；conditional range identity 绑定同一 Forecast/Scenario | 未请求 `valuation` 为 `unknown -> unable`；method limited/caution 只可展示并映射 `unable`；`not_comparable` 不得变成阈值 | 已请求 `valuation` 但 artifact 缺失，或 artifact mismatch、method blocked/disabled/not-ready、formal permission false、per-share bridge 不完整 | 当前已请求 `valuation`，但 artifact ref=`None`、`valuation_view.status=not_ready`、divergence=`not_comparable`，故 blocked |
| Valuation simulation：`simulation_artifact_record_id`, `valuation_simulation` | non-null ref；dependency model、distribution/calibration、correlation、seed、sample/quantiles 与 valuation identity 完整 | 未请求/无 artifact 为 `unknown`，不影响非 simulation 规则 | artifact mismatch 或 valuation base blocked | 当前 `None`；unknown，且不能支持概率阈值 |
| Market path：`market_path_artifact_record_id`, `market_price_paths` | non-null ref 且与价值模拟分离，PIT/data/process/calibration identity 完整 | 未请求/无 artifact 为 `unknown` | 将 intrinsic value simulation 当价格路径，或 identity mismatch | 当前 `None`；unknown |
| Technical research：当前没有 View@2 typed field；ResearchRun 内部存在 `analysis.dimensions.technical` | 未来必须由 View@2 投影 typed dimension status、metric IDs、units/windows/as-of/evidence refs；每个指标有确定性定义 | narrative dimension limited 或字段不存在为 `unknown`；可展示但不可比较阈值 | evidence/PIT/adjustment/identity conflict | 当前 View 不含该维度；unknown。可用的 `security.close_*`/MarketSnapshot 指标是独立能力，不得冒充技术研究 ready |
| Events：当前没有 View@2 typed event/window field；ResearchRun 内部存在 `sentiment_events` 与 free-form catalysts | 未来需 stable event ID、event type、published/available time、window、status、official/evidence refs 和 as-of | 只有文本 catalyst、story 或 filing title 为 `unknown` | event identity/time/authority conflict，或 required official event missing | 当前无 typed event；unknown。official filing metadata 不能自动推断事件语义 |
| Review cues：`key_uncertainties`, `what_would_change_the_view` | 可作为原样展示的人工复核清单，保留 view identity | 文本不能成为 AST operand，也不能自动变成阈值/动作 | 文本含身份冲突、越界动作语言或来自未持久化 caller | 当前字段存在；仅 display/manual review 可用 |
| Financial boundary：`boundary`, `audit.permissions` | `personalized_investment_instruction=false`、rating permission false；输出只表达证据、条件、未知与复核 | 不适用 | permission 越权、renderer/caller 重写语义 | 当前 factory 和 ResearchEngine 均 fail closed |
| StrategyValidation：`audit.strategy_validation` | 第一版不要求 ready | `not_requested`；`requested_unavailable` 是 `nonblocking_unavailable` | 伪造 result/artifact、将 unavailable 当 backtest proof | 当前 contract 正确；不接入 Vibe-Trading |

## 当前计划能力矩阵

| 计划能力 | 研究状态 blocked/unknown 时 | 还需要的独立证据 | 第一版 disposition |
| --- | --- | --- | --- |
| 创建、编辑、确认、版本化用户草稿 | canonical View 可以是 blocked；resolved ResearchRun ref 只证明 lifecycle 与审计历史，不证明研究 ready。完全没有 View 时先运行 canonical ResearchWorkflow 生成 data-insufficient View | exact Security/View/ResearchRun/research DataSnapshot/readiness/Evidence refs、用户输入 provenance、计划版本 invariant | 有 exact persisted View 时 `available`，并把 refs 冻结进版本；评估禁止 `latest` lookup。UI 就近显示研究限制 |
| 回看历史 View/plan/evaluation | 可继续 | persisted identities 和 immutable artifacts | `available` |
| 证券未复权/合格复权价格条件 | 不依赖公司研究 | qualified MarketSnapshot price context；复权条件还需 factor-set evidence | 逐指标 `ready/unknown/blocked` |
| 停牌、涨跌停与执行窗口约束 | 不依赖公司研究 | typed A 股 market constraints、effective session、PIT | 逐指标 `ready/unknown/blocked` |
| 市场趋势/宽度/流动性/波动率条件 | 不依赖公司研究，但不能用 fixture 证明 production ready | Issue 05 规定的 A 股-only `930903.CSI` target package 与完整资格化 receipt | 当前 capability/receipt 未实现，故 `unknown -> unable`；未来指定 snapshot 的已知 admission failure 才是 `blocked` |
| 持仓数量、组合净值等账户条件 | 不依赖公司研究 | 当前账户快照该字段的 capability/provenance/reconciliation | 可按账户字段独立判断；unknown 不是 zero |
| 研究是否需复核 | 可展示 View status、uncertainties、what-would-change；不能自动执行交易效果 | persisted View identity；未来 typed review status/review-by metric | 当前仅 display/manual review；AST metric `unknown` |
| thesis/Forecast invalidation | 不可从 story/文本自动触发 | typed Forecast artifact、invalidation ID、observation/evidence/time status | 未请求/未实现为 `unknown -> unable`；当前已请求 Forecast 但 artifact 缺失，故 `blocked` |
| 条件价值区间、价值偏离或方法状态规则 | 不可用 | ready valuation artifact、method/bridge/currency/unit/as-of/permission identities | 当前 `blocked` |
| 技术结构规则 | 不能消费 ResearchRun narrative | 未来 typed technical metrics；或改用已资格化的独立 price/market metrics | current research-technical=`unknown` |
| 财报、解禁、政策、行业价格等事件窗口 | 不能从标题、free text 或摘要推断 | typed event identity/window/PIT/authority/evidence | 当前 `unknown`；required event gate 时阻断对应规则 |
| 策略验证/回测绩效规则 | 不可用，但不阻断其他能力 | future target-owned StrategyValidation 才可能提供；本切片不建 placeholder | `nonblocking_unavailable` |
| 对 account/plan/lifecycle/order 产生副作用 | 永远不可由研究/估值触发 | 不适用 | `forbidden`；PlanEvaluation 只记录确定性结果 |

## 推荐的最小 View@2 readiness 投影

当前顶层 View@2 字段集合已被 canonical presentation 采用；不应创建平行
`ResearchReadinessSnapshot`、第二份 research JSON reader 或 Web-only mapping。
实现必须定义 domain-owned frozen `HoldingResearchReadiness` 类型、closed
status/reason enums、invariants 与 canonical identity，由
`ResearchEvaluation` 直接构造，再由 typed `ResearchAudit` 随 View@2
持久化。`ResearchDecisionView.from_dict` 必须解码并验证该 nested contract；
只在现有 `audit: Mapping` 中塞一个带 `schema_version` 的自由 JSON 不算 typed。
计划/Web 只能消费验证后的类型。目标 canonical payload 形状例如：

```json
{
  "holding_readiness": {
    "schema_version": "HoldingResearchReadiness@1",
    "security_id": "same-as-view",
    "data_snapshot_id": "same-as-view",
    "as_of": "same-as-view",
    "evidence_admission": {
      "status": "ready|limited|unknown|blocked",
      "freshness_status": "valid|stale|missing",
      "quality_status": "pass|warning|quarantine|blocking",
      "effective_session_date": "YYYY-MM-DD",
      "coverage": {
        "expected": 0,
        "eligible": 0,
        "excluded": 0,
        "missing": 0
      },
      "official_semantic_fields": [],
      "reason_codes": [],
      "evidence_refs": []
    },
    "dimensions": {
      "company_research": {
        "status": "ready|limited|unknown|blocked",
        "reason_codes": [],
        "artifact_record_id": null
      },
      "forecast": {
        "status": "ready|limited|unknown|blocked",
        "reason_codes": [],
        "artifact_record_id": null
      },
      "valuation": {
        "status": "ready|limited|unknown|blocked",
        "reason_codes": [],
        "artifact_record_id": null
      },
      "technical": {
        "status": "ready|limited|unknown|blocked",
        "reason_codes": [],
        "metric_refs": []
      },
      "events": {
        "status": "ready|limited|unknown|blocked",
        "reason_codes": [],
        "event_refs": []
      }
    }
  }
}
```

这只是 Issue 06/08 的目标合同建议，不是当前 runtime 已实现事实。实现时必须：

1. 由 `WorkflowLedgerPort` 的 typed frozen-evidence query 补齐 snapshot freshness、
   stale days、coverage 与 official semantic coverage；不能让 Web/plan caller 查表或
   解码 raw provider payload。
2. 每个 dimension 独立判定；overall `completed_with_limits` 不能升级所有维度。
3. artifact refs 必须解析到同一 security/snapshot/as-of/model/policy graph。
4. Issue 08 只把 typed leaf 加入 metric catalog；free text 永远不是 operand。
5. gate 输出只允许 `ready/limited/unknown/blocked` 和 reason/evidence refs，再映射到
   evaluator 的 `triggered/not_triggered/unable/blocked/not_applicable`；不生成动作指令。
6. 保留现有 View@2 为唯一 presentation model，并完成一条单向迁移：能从
   persisted typed evidence 重建的历史 View 写入完整 readiness；证据不足的历史
   View 写入 `unknown` + typed migration reason，保持 read-only/audit-safe。
   migration 后 runtime 只接受新 typed contract，不保留 dual readers、
   compatibility aliases 或 caller reconstruction。
7. 编制时可以展示最新候选 View，但 `TradePlanVersion` 必须冻结 exact
   `view_id`/`research_run_id`/research `data_snapshot_id`/readiness identity；
   PlanEvaluation 绑定当次 evidence bundle/effective session/PIT cutoff/
   calendar/source/freshness policy，禁止评估时查询 `latest`。
8. 状态映射是 closed policy：未请求/未实现=`unknown -> unable`；已请求且
   required artifact 缺失或任何已知 gate failure=`blocked -> blocked`；
   `limited -> unable` 且只可展示/人工复核。

## Issue 06 可采用的决策摘要

- 编制时只从同 security/A 股 scope 的候选中选择 View；每个 PlanVersion 精确冻结
  `view_id`/`research_run_id`/research snapshot/readiness identity。评估只复用
  版本内引用并按当次 cutoff/freshness policy 判定 stale，禁止 `latest` lookup、
  跨证券或隐式换 snapshot。
- 计划草稿/历史能力与研究 readiness 解耦；readiness 只门控依赖该维度的 rule。
- 当前 plan 已请求 `source_quality`/Forecast/valuation：company research 因
  admission/overall/report permission 失败而 blocked，Forecast/valuation 因
  required artifact 缺失而 blocked；technical/events 未实现，故
  `unknown -> unable`；
  View identity、plan identity、source-policy identity 和 review text 可用于审计/展示。
- 当前 MarketRegime target package 仍未完成 production data qualification；不得借
  market fixture 或单证券 receipt 宣称四组件 ready。
- official document evidence 不是 official semantic fact。SZSE holding 也不能因已有
  CNINFO/SZSE PDF 而升级估值；SSE/BSE/IR 未实现更不能被辅助行情补成 ready。
- 条件价值区间、Forecast、技术研究、事件和语言文本都不能直接变成计划效果；
  只能在 typed evidence ready 后支持确定性 `prompt_review`/`observe` 等安全效果。
- StrategyValidation unavailable/nonblocking；无 Vibe-Trading、无回测 artifact、
  无 broker/order/自动交易/盘中能力。
