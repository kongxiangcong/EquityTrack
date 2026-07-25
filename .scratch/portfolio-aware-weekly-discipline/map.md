# 组合感知的每周交易纪律闭环 Wayfinder Map

Label: `wayfinder:map`
Status: `open`

## Destination

形成一份与当前代码、真实浏览器行为和数据能力一致、可以直接进入实施阶段的“组合感知的每周交易纪律闭环”实现级 Spec。该 Spec 必须让用户以手工声明或券商导入形成当前账户快照，在日线收盘后冻结市场与研究输入，创建并确认版本化规则计划，在下一交易日窗口前查看确定性触发/阻断结果，并在每日及周末保留不可改写的计划与复盘历史。

## Notes

- [总任务 Prompt](../../docs/prompts/trading_platform_codex_prompt_optimized.md) 和根目录 `AGENTS.md` 是不可弱化的长期边界；本 map 只消除下一条垂直切片的决策 fog，不实施平台。
- 用户已固定第一版执行时间边界为“收盘后评估 -> 下一交易日窗口”；盘中做 T、分钟级触发和真实下单不属于本切片。
- 用户已确认账户快照可以手工填写，不再要求完整 XLS。手工输入必须形成 `UserDeclaredAccountSnapshot`，显式保留 `as_of`、用户声明来源与能力限制；不得伪造交易流水、费用、税费、收益、历史成本批次或券商级对账状态。
- 既有同花顺导入继续作为可选的高证据输入，不是本切片的强制前置条件。手工快照与券商导入快照必须共享不可变快照/版本语义，但保持不同 provenance 和 capability。
- 稳定业务 seam 是 `trading_platform.application` 暴露的窄任务接口及 `bootstrap.open_*` composition functions；CLI/Web 必须经这些任务接口进入领域能力，`WorkflowLedger` 是工作流持久化唯一所有者。不得恢复已删除的聚合 Facade，也不得从适配器绕过任务接口。
- 当前已验证的工程事实包括：代码结构切换和发布证据已经闭合，动态标的身份、图表失败关闭、账户空状态文案和生产浏览器验收已有覆盖；账户手工声明、计划草稿编制、组合级日终编排、下一交易日 inbox 与周末复盘仍是本 map 要消除的产品缺口。
- 外部能力 adoption 已收敛为 A 股-only canonical architecture：结构化行情经版本化 `SourcePolicy@1` 和唯一 `DataProvider` application path；当前实现并验证的 official disclosure provider 只有 CNINFO/SZSE，SSE、BSE 与公司正式 IR ingestion 仍是 future/unavailable，不能被写成 ready。研究只接受 `ResearchWorkflowRequest@2` + `ResearchEvaluationPlan@1`，唯一持久化 owner 是 `WorkflowLedger`，JSON/HTML/PDF/XLSX/Web/archive 只投影 `ResearchDecisionView@2`。实现与生产验收证据见 [adoption Issue 15](../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md)。
- `StrategyValidation` 当前 capability unavailable：未请求时状态是 `not_requested`；若计划显式选择该能力，则只能记录非阻断 `requested_unavailable` 及 `STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`，没有 adapter、result、artifact、route 或配置。第一版组合纪律产品不接入 Vibe-Trading，不增加回测、broker、order、自动交易或盘中做 T。
- 输出是风险约束、条件状态、触发/未触发/阻断/无法判断和待用户确认的计划草稿，不是 BUY/HOLD/SELL、买入/卖出/持有、加减仓指令、收益承诺或自动订单。
- 每个 Wayfinder 会话最多解决一个 ticket。HITL 票据必须由用户真实参与；不得由 Agent 替用户选择风险偏好。

## Decisions so far

<!-- Closed-ticket index only. Detailed answers live in the resolved ticket. -->

- [审计当前每周决策旅程与可复用 seam](issues/01-audit-current-weekly-decision-journey.md) — 复用窄应用任务接口、不可变账户/研究/计划/市场/工作流能力；手工账户、计划创建、组合日终编排、下一交易日任务与周末复盘尚未形成真实可走的产品闭环。
- [决定用户声明账户快照的信任与降级合同](issues/02-decide-user-declared-account-snapshot-contract.md) — 截图、自然语言与文件先形成草稿；确认快照按来源信任和字段 capability 双轴降级、保持不可变，且不得从状态差额伪造账户历史。
- [决定收盘后评估与下一交易日窗口语义](issues/03-decide-daily-close-decision-window.md) — 只用截至 PIT cutoff 已完整可用的数据冻结当日快照；周末/节假日按版本化交易日历回退，但开放日数据缺失、停牌/涨跌停、T+1、复权或公司行动冲突必须显式阻断或降级，决不把日线信号回填成同收盘价成交。
- [资格化 MarketRegime v2 的数据与最小组件](issues/05-qualify-market-regime-v2-data.md) — 最小目标包固定 A 股-only `930903.CSI` 中证 A 股指数的趋势/波动率，并按逐 session PIT 成分计算宽度/流动性且不合成黑箱分；runtime 仍以 typed `instrument_type=A_SHARE` fail closed。当前单证券 receipt 和 legal-empty constituent probe 不足以证明这些输入，planning disposition 为 `blocked_data_qualification`，行业轮动与资金流第一版 disabled。

## Not yet specified

- 在 Provider 资格和行业分类来源确定前，跨持仓相关性、行业集中度和风格暴露应采用何种最小可审计方法仍处于 fog。
- 当前 frontier 是 [决定持仓研究与条件估值的计划门控](issues/06-decide-holding-research-readiness-gates.md)；它将把 MarketRegime 的 `blocked_data_qualification` planning disposition 映射为现有 typed blocked/unknown capability limit，不能假设四组件已生产可用。需要主动提示还是渐进披露的交互问题由既有驾驶舱原型票解决，不再重复留在 fog。

## Out of scope

- 真实券商下单、自动成交、委托导出，以及任何绕过用户确认的执行副作用。
- 第一版的盘中做 T、分钟级行情、分钟级策略触发和日内执行优化。
- 个性化买入、卖出、持有、加减仓指令或由系统替用户决定交易。
- 为了接受手工快照而伪造完整账户历史、历史收益、费用税费拆分、持仓批次或券商级对账。
- 大规模参数搜索、完整策略实验平台、全量回测框架或未经数据时间审计的收益优化；这些属于后续独立 effort。
- 推倒重写现有研究、账户、计划、市场状态或 Web 工作台。
