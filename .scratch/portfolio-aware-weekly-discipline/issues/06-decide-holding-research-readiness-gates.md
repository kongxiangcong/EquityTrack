# 决定持仓研究与条件估值的计划门控

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01, 02, 05

## Question

对于手工声明账户中的每个当前持仓，哪些 ResearchRun、官方证据、Forecast、Valuation、技术结构、事件和 freshness 状态必须存在，才能支持周计划中的不同规则；缺少公司研究、估值方法受阻、官方证据过期或只有市场行情时，哪些计划能力仍可用、哪些必须 blocked/unknown？锁定研究复核项与交易计划规则的边界，禁止把语言模型观点或条件价值区间直接变成行动指令。

## Current canonical baseline

- 门控必须读取已持久化的 `ResearchDecisionView@2`，不得由 Web/计划 caller 重跑或重新解释研究。`DataProvider` 由 `SourcePolicy@1` 约束并经 application synchronization 形成 frozen DataSnapshot；application `ResearchWorkflow` 接受 [`ResearchWorkflowRequest@2` + `ResearchEvaluationPlan@1`](../../../src/trading_platform/domain/research_evaluation.py)，concrete ResearchEvaluation 只通过 [`WorkflowLedgerPort`](../../../src/trading_platform/application/workflow_ledger.py) typed query 加载 frozen evidence，再由同一 `WorkflowLedger` 原子持久化 View@2。精确实现与 production acceptance 见 [adoption Issue 15](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。
- 当前门控证据必须保留 frozen DataSnapshot identity、`SourcePolicy@1`、official-source/PIT/freshness/quality 状态和 valuation router 的 disabled/not-ready/not-comparable 原因。当前只有 CNINFO/SZSE official ingestion 已实现；SSE、BSE 与公司正式 IR 仍是 future/unavailable。任何 required official evidence 缺失、过期、部分、quarantined、身份不一致或来源尚未实现，都不能被辅助行情升级为 ready；A 股 official vertical slice 证据见 [adoption Issue 13](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md)。
- 本票要决定不同计划规则可消费 View@2 的哪些明确字段和失败状态；不能把 Forecast、条件估值区间、语言模型文本或 unavailable capability 转换成买卖/加减仓动作。
- `StrategyValidation` 未请求时显示 `not_requested`；显式选择时只可显示非阻断 `requested_unavailable` 与 `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`。第一版持仓 readiness 不依赖它，不产生回测结果或 artifact，也不接入 Vibe-Trading、broker、order、自动交易或盘中做 T。

## Answer

第一版采用**逐能力、逐规则门控**，不设置一个把整份计划一起判死的“研究总分”。
完整证据矩阵与当前代码差距见
[持仓研究与条件估值计划门控](../research/holding-research-readiness-gates.md)。

### Canonical gate

计划侧未来只消费由 `ResearchEvaluation` 构造、随 persisted
`ResearchDecisionView@2` 保存的 domain-owned frozen
`HoldingResearchReadiness@1`，以及该 View 引用、由
`WorkflowLedgerPort` typed query 加载的 frozen DataSnapshot evidence。
该类型拥有 closed enums/invariants/canonical identity；View loader 必须把
nested payload 解码为该类型并在缺字段、未知状态或 identity/hash 不一致时
fail closed。它不是只写了 `schema_version` 的任意 `audit` mapping，也不是
第二份研究报告、Web mapping 或 caller reconstruction：

- identity gate 必须绑定同一 A 股 `security_id`、`research_run_id`、
  `view_id`、`data_snapshot_id`、`as_of`、evaluation-plan identity、
  model/policy identity 和 source-policy identity；
- evidence admission 必须保留 effective session、PIT cutoff、freshness、
  stale days、quality、coverage、official semantic-field coverage、reason
  codes 和 evidence refs；
- `company_research`、`forecast`、`valuation`、`technical`、`events` 五个
  dimension 分别返回 `ready|limited|unknown|blocked`，不得用 overall
  `completed_with_limits`、`data_quality_grade` 或文本替代逐维度判断；
- `company_research` 是 plan-consumer dimension，不伪装成新的
  `ResearchEvaluationPlan` enum。它只在 plan 已请求 `source_quality` 时，
  由 typed evidence admission、ResearchRun integrity/blocked 状态、
  `audit.permissions.research_report` 和 typed story status 合取：全部通过为
  `ready`；其他维度造成的 overall `completed_with_limits` 不得连带降级
  company research；只有 company 自身核心证据有限才为
  `limited -> unable`；未请求为
  `unknown -> unable`；已请求且 admission/overall/report permission/story
  任一 required gate 失败为 `blocked -> blocked`；
- artifact ref 必须解析到同一 security/snapshot/as-of/model/policy graph。
  缺 ref、身份冲突、未来可得证据、required official field 缺失、stale、
  quarantine/blocking quality 或 coverage missing 均 fail closed。
- 编制时可以向用户展示最新可用 View 作为候选，但每个
  `TradePlanDraft`/`TradePlanVersion` 必须精确冻结 `view_id`、
  `research_run_id`、research `data_snapshot_id` 及 readiness identity。
  收盘后评估只读取版本内引用，禁止 `latest` lookup；评估 evidence bundle
  还要绑定当次 effective session、PIT cutoff、calendar/source/freshness
  policy，并据此重判 pinned research 是否 stale。

状态映射锁定为：未请求或 capability 未实现为 `unknown -> unable`；已请求且
required artifact 缺失，或出现 identity/PIT/freshness/quality/coverage/
official/method gate 已知失败，为 `blocked -> blocked`；`limited` 只允许展示
与人工复核，机器规则结果为 `unable`。实现票不得自行合并这些状态。

当前 View@2 的 `audit` 尚未携带上述 typed admission/dimension payload；
当前 fixture 实测为 `status=blocked`、
`valuation_view.status=not_ready`、Forecast/Valuation/Simulation refs
均为 `None`、`key_drivers/scenarios` 为空且 permissions 全 false。因此
`HoldingResearchReadiness@1` 是后续实现目标，不是现有能力；在它完成前，
当前 evaluation plan 已请求 `source_quality`/Forecast/valuation：
company research 因 overall blocked、report permission false 而 blocked，
Forecast/valuation 因 required artifact 缺失而 blocked；未实现的
technical/events 为 `unknown -> unable`。

### Plan capability disposition

| 能力 | 研究缺失、过期或 blocked 时 | 第一版决定 |
|---|---|---|
| 创建、编辑、确认和回看不可变计划 | 研究结论可 blocked，但必须已有 canonical persisted View；resolved ResearchRun 只表示 lifecycle 已终结，不表示 readiness | 保留当前 exact ResearchRun 引用，并把 exact View/Snapshot/readiness identity 冻结进版本。完全没有 View 时先运行 canonical ResearchWorkflow 产生 data-insufficient View；评估禁止动态换成新 View。 |
| 价格、停牌/涨跌停、账户数量/NAV 规则 | 只读各自 frozen MarketSnapshot/AccountSnapshot capability | 按自身 evidence 独立 `triggered/not_triggered/unable/blocked`；unknown 不是零。 |
| MarketRegime 规则 | 不依赖公司估值，但依赖 Issue 05 的 A 股-only production qualification | capability/receipt 尚未实现时是 `unknown -> unable`；若已有指定 snapshot 但 freshness/quality/coverage 等 gate 明确失败则 `blocked -> blocked`，均不阻断其他规则。 |
| 研究复核 | 可原样展示 persisted View 的 status、`key_uncertainties` 与 `what_would_change_the_view` | 仅 display/manual checklist；free text 不是 AST operand。 |
| Forecast / thesis invalidation | 未请求/未实现为 `unknown`；已请求却缺 typed Forecast artifact、invalidation identity 或 observation evidence为 `blocked` | 当前 plan 已请求 Forecast 而 artifact 缺失，故 `blocked`；ready 后也只允许 `prompt_review`、`observe` 或有证据的 `mark_invalidation_candidate`。 |
| 条件估值、价值偏离或概率 | 缺 ready valuation artifact、method applicability、currency/unit/equity bridge、formal permission 或同一 lineage | `blocked`；不得从条件价值区间直接生成价格阈值、仓位或动作。 |
| 技术结构 | 当前 View@2 没有 typed technical dimension | research-technical 为 `unknown`；已有 `security.close_*`/market metrics 是独立市场能力，不能冒充技术研究 ready。 |
| 事件窗口 | 当前只有 official filing document metadata，没有 typed event identity/type/window | `unknown`；公告标题、catalyst 文本和“无返回”都不能推导为事件或无事件。 |
| StrategyValidation | `not_requested` 或 `requested_unavailable` | 非阻断，不进入 readiness 合取，不产生 result/artifact/route/config。 |

official document evidence 不等于 official semantic financial facts。当前
CNINFO/SZSE document ingestion 已实现，但 critical semantic facts 仍缺；
SSE、BSE 与公司正式 IR ingestion 仍 unavailable。辅助行情、语言模型观点、
摘要文字或 caller-authored JSON 均不能把相应 dimension 升级为 ready。

研究与估值只提供版本化证据、限制和人工复核线索；它们永远不能写
AccountSnapshot、TradePlan、PlanEvaluation、authorization 或 order state，
也不能生成买卖、加减仓、持有、目标价结论或任何执行副作用。
