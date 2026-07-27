# 决定交易计划状态机与市场状态评估接口

Type: `grilling`
Mode: `HITL`
Status: resolved
Blocked by: 02, 06, 07, 08

## Question

第一条纵向切片中的 `TradePlan`、不可变 `TradePlanVersion`、结构化 `PlanRule`、当日 `MarketSnapshot` 和 `PlanEvaluation` 应采用什么最小状态机与接口，才能表达用户确认、激活、触发、失效、取消和后续修改而不覆盖历史，也不越界成自动下单或个性化投资指令？需要用具体场景决定规则输入/输出、市场状态的透明组件与版本、缺失/陈旧数据处理、禁止交易条件、证据与数据快照引用、同日重复评估幂等性，以及评估结果如何说明触发/未触发/原因并可回看。

## Comments

- 第一个 grilling 问题直接采用推荐答案：未确认内容不属于 `TradePlan` 或 `TradePlanVersion`，统一称为 `TradePlanDraft`。首次草稿可以尚未关联 `TradePlan`；首次确认才在同一事务创建稳定 `TradePlan`、不可变 `TradePlanVersion v1`、版本内规则/风险约束和确认记录。已确认计划后续最多保留一个 open draft，草稿引用 `based_on_version_id`、使用递增 revision 与 optimistic concurrency；保存草稿可更新工作副本并追加审计记录，丢弃草稿不影响当前启用版本。确认时必须展示完整内容、来源引用和相对基线版本的 diff；语法或单位无效、引用不存在、规则无法由已注册确定性 evaluator 解释时拒绝确认。`TradePlanDraft` 已立即补入根目录[领域词汇表](../../../CONTEXT.md)。
- 第二个 grilling 问题直接采用推荐答案：`TradePlan` 的最小生命周期只有 `inactive / active / ended`，每次变更都追加不可改写的 transition。`ended` 是终态并要求 `end_reason=cancelled | invalidated | completed`；结束后不能复活，只能从旧版本复制出一个全新的草稿，确认后形成新的 `TradePlan` identity。`triggered` 绝不是计划状态，而是某个 `PlanEvaluation` 中一条或多条规则的结果；规则触发、失效条件满足、到期或市场门控命中都不得自动改变计划生命周期。用户必须显式执行 activate/deactivate/end；首切片主路径提供一次明确的“确认并启用”原子动作，但底层确认与启用语义仍分开记录。
- 第三个 grilling 问题直接采用推荐答案：版本内容与生效历史分离。`TradePlanVersion` 只保存确认时的完整不可变内容，不在其行上覆盖 `active` 标志；`plan_activation` 记录每次启用/停用区间和原因，同一 `TradePlan` 在任一时点最多一个有效版本。编辑 active v1 只创建基于 v1 的草稿，v1 继续参与 daily；确认并启用 v2 时在同一事务创建 v2、结束 v1 的生效区间并开始 v2 的区间，失败则 v1 完全不变。确认但不启用的版本可保留为 inactive 历史；daily 在命令调用时选择当前 active 版本，再与最近完整市场 session 的快照配对，因此 7 月 11 日确认的版本可以相对 7 月 10 日快照评估。显式审计重放可选择任一确认版本；选择原因/当时当前版本由 WorkflowRun ref 记录，不进入 PlanEvaluation 内容或幂等键，也不能借“最新版本”隐式替换。
- 第四个 grilling 问题直接采用推荐答案：每个确认版本是自足的完整快照，至少固定 `security_id`、`version_no`、`based_on_version_id`、用户输入来源声明、研究/证据/数据快照 typed refs、计划期限与 `review_by`、规则全集、风险预算、市场门控策略、metric catalog/evaluation policy version、确认人/时间与 canonical content hash。首切片从 `WatchlistItem` 进入且没有账户/持仓，因此风险预算只允许用户或验收 fixture 明确输入的 CNY 绝对约束，例如 `max_planned_notional` 与 `max_planned_loss`；不得由平台推荐，也不得声称已验证真实组合暴露。缺少 Position 时，任何依赖实际仓位、成本或账户净值的风险规则必须返回 `not_applicable` 或 `unable_to_determine`，不能用零值代替。
- 第五个 grilling 问题直接采用推荐答案：`PlanRule` 采用版本内不可变 typed rule，`rule_key` 在版本间保持逻辑连续性用于 diff，`rule_version_id` 唯一指向当次内容。最小 `rule_kind` 为 `entry_review / adjustment_review / exit_review / invalidation / risk_limit / market_gate / observation`；最小 `effect` 为 `prompt_review / mark_invalidation_candidate / mark_risk_limit_breach / block_user_intent / observe`，并可用 `applies_to=entry | increase | decrease | exit | plan` 限定范围。所有 effect 只描述“用户原先写入的条件已满足，需要复核/受其规则约束”，不得生成订单、数量、委托价、券商 payload 或平台自创的操作建议。市场门控阻止 entry/increase 时也不能压掉 exit、invalidation 或风险规则结果；冲突规则逐条并列显示，不合成为一个系统动作。
- 第六个 grilling 问题直接采用推荐答案：规则条件是受版本控制的 AST，不接受 Python/SQL/JavaScript、自由文本公式或 prompt。叶子仅可引用 metric catalog 中带类型/单位/时间语义的 `metric_ref`，使用 `eq/ne/lt/lte/gt/gte/between/crosses_above/crosses_below/changed_to` 等白名单运算符；组合只允许 `all/any/not`。常量使用 exact decimal、受控 enum、日期或布尔值并显式单位/币种；窗口、基准、当前/前一完整 session 都写入条件，禁止隐含“latest”。`crosses_*` 必须在同一快照中具有当前和前一完整观测。叶子结果为 `true / false / unknown / blocked / not_applicable`；逻辑组合按保守四值规则传播，任何可能改变结论的 missing/conflict 不得被当作 false。
- 第七个 grilling 问题直接采用推荐答案：绝对价格阈值以 canonical 未复权 CNY exact decimal 保存，并固定 `price_basis=unadjusted`；从前/后复权 K 线创建规则时，chart adapter 必须使用该图表引用的 factor-set/derived snapshot 做确定性反算，同时保存源图表坐标、factor-set ref 和转换证据。不能唯一反算、遇到公司行动冲突或单位/币种不匹配时禁止确认规则。评估始终对 snapshot 中同一 canonical 未复权口径比较；以后因公司行动形成新因子版本不会改写旧计划阈值、旧标注或旧评估。UI 可按当前明确 factor set 投影展示，但投影值不是计划权威内容。
- 第八个 grilling 问题直接采用推荐答案：首切片的 target-scoped `MarketSnapshot` 不生成黑箱总分，只保存透明、可单独引用的组件。A 股固定 fixture 以版本化 `CN_A_SHARE` universe 和沪深 300 `000300.SH` benchmark 为基线：`market.trend` 在 close 同时高于 SMA20/SMA60 且 SMA20[t] > SMA20[t-5] 时为 `up`，同时低于两条均线且斜率向下时为 `down`，其余 `mixed`；`market.breadth` 保存有效样本数、上涨占比和高于 SMA20 占比，以两项均不低于 60% 为 `broad`、均不高于 40% 为 `narrow`、其余 `mixed`。breadth universe 采用 cutoff 时仍上市的全部 A 股，不静默排除 ST；当前停牌、少于 20 个合法历史 session 或有 blocking 质量问题者从当日分母排除并按原因计数。`market.liquidity` 保存全市场成交额及其在不含当日的此前 252 个完整交易日中的 percentile（最少 120 个样本），以 70/30 分位分为 `ample/normal/thin`；`market.volatility` 用 benchmark 日对数收益计算 20 日、`sqrt(252)` 年化实现波动率，并保存其相对不含当日的此前 252 个滚动观测的 percentile（最少 120 个样本），以 80/20 分位分为 `high/normal/low`。另保存 `security.price_context`：目标证券 canonical 未复权 close、日变化、SMA20/SMA60、停牌/完整 session/涨跌停事实和公司行动冲突状态。所有窗口、阈值、年化因子、样本剔除、benchmark/universe/calendar identity 均属于 `market_model_version`。宏观、资金、新闻、社交情绪、相关性/拥挤度和行业轮动明确记为 `unsupported_in_first_slice`，不能默认为中性；完整平台后续扩展但不得反向改写旧快照。
- 第九个 grilling 问题直接采用推荐答案：`build_market_snapshot(BuildMarketSnapshotRequest)` 只接收 `security_id, market_scope_id, requested_at, effective_session_date, data_snapshot_id, market_model_id/version, freshness_policy_version`，输出不可变 `MarketSnapshot`，不得自行读取“最新”数据。快照 identity/fingerprint 由这些 canonical 输入、模型/代码身份和有序组件结果 hash 决定；相同输入重跑复用同一快照，不因 WorkflowRun 或 wall clock 变化。快照保存 `requested_at`、有效 session、cutoff、input DataSnapshot、component coverage、每项 `observed_through/freshness/quality/value/classification/evidence refs` 以及 `status=complete | limited | blocked`。历史快照的 freshness 是相对创建请求日冻结的事实，日后查看不把它动态改成 stale；新的请求日也不得把旧快照冒充当日快照。
- 第十个 grilling 问题直接采用推荐答案：缺失/陈旧/冲突不进行中性填充。`blocked` 用于 DataSnapshot/hash/PIT/identity 不变量失败、目标证券或有效 session 不一致、canonical OHLCV/交易日历陈旧或缺失、公司行动冲突，以及规则实际引用的 metric 为 stale/quarantine/blocking/conflicted；此时仍可持久化一个没有正常分类值的 blocked snapshot/result 来解释缺口，但不能称为完整当日市场状态。`limited` 用于未被当前规则引用的可选组件缺失或首切片明确 unsupported；可继续评估可确定的规则，并把 completeness 标为 partial。请求发生在盘中或非交易日时按已决定的交易日历回退到最近完整 session，同时展示 requested/effective date；不得把未收盘数据混入日终快照。只有历史回看可以使用旧 session 的当时合法快照，新的 daily 不能用它代替当前有效 session。
- 第十一个 grilling 问题直接采用推荐答案：禁止条件分两层。系统硬门禁只保护评估完整性和金融边界，包括未确认草稿、版本/hash/schema 不匹配、关键输入不可得、规则 DSL/单位不可解释，以及业务包中任何券商连接、订单、导出或执行接口；前者产生 blocked evaluation，后者在产品/API 层根本不存在。停牌、涨跌停、市场未开或用户自写的高波动/窄宽度限制是 snapshot 中的市场事实或 `market_gate` 规则，不阻止其他可计算规则求值；命中时只输出 `review_feasibility=restricted` 或 `block_user_intent` 及适用范围。它不能替用户决定交易，也不能遮蔽 exit/invalidation/risk 结果。
- 第十二个 grilling 问题直接采用推荐答案：`evaluate_plan(PlanEvaluationRequest)` 的权威输入只有 `plan_version_id, market_snapshot_id, evaluator_id/version, evaluation_policy_version`，WorkflowRun/trigger 只在外层引用，不进入领域结果。输出 `PlanEvaluation` 分三轴：execution `status=completed | blocked`，结论 `outcome=triggered | not_triggered | unable_to_determine`（blocked 时无结论），覆盖度 `completeness=complete | partial`。逐条 `PlanRuleEvaluation` 保存 `triggered / not_triggered / unable_to_determine / blocked / not_applicable`、稳定 reason codes、实际 operands/单位/观测时点、effect/applies_to 和证据 refs。只要至少一条规则确定触发，总体 outcome 为 triggered，即使其他规则 unknown，并以 partial 明示；无触发但有可能改变结论的 unknown 则为 unable_to_determine；全部适用规则确定为 false 才是 not_triggered。界面文案使用“用户规则条件已满足/未满足/无法判断/评估受阻”，禁止转换为买卖指令或评级。
- 第十三个 grilling 问题直接采用推荐答案：每个叶子求值都必须可追溯到 `plan_rule_version_id`、`market_snapshot_component_id`、其 `DataSnapshot/derived_dataset/normalized_version` 输入、metric/model/evaluator version 和 canonical operand hash；研究论点只通过 `ResearchRun + Evidence` typed refs 提供上下文，不能在评估时重新解析自然语言。`PlanEvaluation` 保存完整输入/输出 canonical JSON artifact、reason-code 集合、创建时间、代码/政策版本与 workflow refs；人类说明由稳定 code 和冻结 operands 渲染，说明文本不是权威。完整 provenance、hash、样本成员与参数进入可展开“数据详情/证据”，默认页只展示发生了什么变化、哪些用户规则命中、限制与下一步复核。
- 第十四个 grilling 问题直接采用推荐答案：`PlanEvaluation` 的领域幂等键/唯一约束是 `plan_version_id + market_snapshot_id + evaluator_id/version + evaluation_policy_version`；相同组合无论 confirmation、daily、Web 重试或新 WorkflowRun 再次请求都复用同一不可变结果，并在新 run journal 中记录 `reused`。同一 session 因 Provider 修订、source policy、模型版本或组件内容变化而形成新的 DataSnapshot/MarketSnapshot 时，必须产生新的 evaluation；v2 也必须产生新的 evaluation。不得把 evaluation timestamp、invocation/run ID 或 UI 选项放入幂等键。若旧 evaluator 已不可用，历史结果仍可回看但不得用新代码覆盖；显式用新 evaluator 评估会生成并列的新结果。
- 第十五个 grilling 问题直接采用推荐答案：规则命中没有领域副作用。entry/adjustment/exit 规则只产生对应复核项；invalidation 规则命中产生 `mark_invalidation_candidate`，计划继续 active，直到用户查看引用证据并显式 `end(reason=invalidated, evaluation_id=...)`；用户无论是否有触发都可显式 `end(reason=cancelled)`，但必须记录理由且未来 daily 不再选择该计划。到达 `review_by` 或计划期限只产生 `review_overdue/plan_expired` 结果，不自动结束。对已 ended 计划只能回看和重放历史；若用户改变看法，复制旧版本形成新草稿并在确认时创建新的 TradePlan，避免改写失效/取消历史。
- 第十六个 grilling 问题直接采用推荐答案：application facade 的最小命令为 `create_plan_draft`、`update_plan_draft(expected_revision)`、`discard_plan_draft`、`confirm_plan_draft(expected_revision, activation_mode)`、`activate_plan_version(expected_transition_seq)`、`deactivate_plan`、`end_plan(reason, expected_transition_seq)`、`build_market_snapshot` 和 `evaluate_plan`；查询为 current plan/draft、version diff、snapshot/evaluation detail 与 history timeline。所有 mutation 使用 invocation id + optimistic concurrency，返回 typed identity/status/version/hash；确认/启用/结束是短事务，不让 WorkflowRun 等待用户。接口中明确不存在 `place_order/submit_order/export_order/broker`，也不接受自然语言规则作为可执行输入。
- 第十七个 grilling 问题直接采用推荐答案：第一切片专用 schema 只增加 `trade_plan`（稳定 identity/current lifecycle projection）、`trade_plan_transition`（append-only 状态历史）、`trade_plan_draft`（open/discarded/confirmed、revision、base version、content）、`trade_plan_version`（不可变 header/hash/refs）、`plan_rule` 与 `plan_rule_condition`（版本内 typed AST）、`plan_risk_constraint`、`plan_activation`（版本生效区间）、`market_snapshot` 与 `market_snapshot_component`（输入/模型/coverage/typed values/refs）、`plan_evaluation`、`plan_rule_evaluation` 和 `plan_evaluation_evidence`。核心金额/阈值/状态/外键使用 typed columns 与 exact decimal representation，不能只藏 JSON；canonical JSON 作为 schema-versioned artifact。全部外键引用票据 07 的 Security/DataSnapshot/derived/artifact identities 和票据 08 的 workflow refs，状态投影更新必须同事务追加 transition，历史版本/结果不得 DELETE/UPDATE 覆盖。
- 第十八个 grilling 问题直接采用推荐答案：默认页面遵循设计驱动基线，只先显示计划状态/版本、有效 session、数据限制、相对上次评估的变化、命中的用户规则与“需要复核”的原因；四个透明市场组件用原值+分类+变化呈现，不显示单一黑箱热度分。草稿编辑器按“依据与期限、规则、风险预算、市场门控”组织，确认页优先展示相对上一版本 diff、引用和明确“用户输入、非平台建议、不会执行交易”的确认语义。完整 operands、模型窗口、snapshot membership、hash、source/version 和 run journal 通过“数据详情/证据/历史”渐进披露。正常 pass 不堆徽标；blocked/partial 必须就近说明当前仍可做什么以及需要什么数据，不能只给内部 error code。
- 第十九个 grilling 问题直接采用推荐答案并锁定反例：v2 草稿未确认时 daily 仍评估 active v1；v2 确认并启用后才原子切换且产生新 evaluation。相同 version/snapshot/evaluator 重跑只复用结果；同一 session 的 Provider 修订形成新 snapshot/evaluation，旧结果保留。只有上一交易日缓存时，历史回看可用而 2026-07-10 当日评估 blocked；缺失未被规则引用的 breadth 时结果可 completed+partial，引用它的规则则 unable/blocked 并给原因。invalidation 命中只提示候选，用户显式结束后才停止 daily。停牌/涨跌停与 entry gate 同时命中时并列显示，不生成交易动作，也不遮蔽 exit/risk 规则。复权图上的价格不能反算时禁止确认；公司行动修订不会改写旧阈值。冲突规则全部保留，不合成买卖建议。ended 计划不能复活，复制后形成新 plan identity。fixture 中所有规则/金额均标记为用户或验收输入，不得描述成平台推荐。

## Answer

第一条纵向切片采用“**可编辑草稿 -> 用户确认的不可变版本 -> 显式生效历史 -> 只读确定性评估**”模型。计划规则可以表达用户自己的进入、调整、退出、失效、风险和市场门控，但平台只说明条件是否满足及为什么，绝不把结果变成订单、券商动作或个性化投资建议。本答案是后续 Spec/实现的设计合同，不代表平台代码已经存在。

### 1. 计划身份、状态与版本

```text
TradePlanDraft(open, revision N)
        | confirm
        v
TradePlan + immutable TradePlanVersion v1
        | activate/deactivate explicitly
        v
TradePlan lifecycle: inactive <-> active -> ended
                                           reason: cancelled | invalidated | completed
```

- 未确认内容是 `TradePlanDraft`，不是 `TradePlan` 或版本。首次确认才创建稳定计划 identity 与 v1；后续一个计划最多有一个 open draft，并引用 `based_on_version_id`。
- `TradePlan` 只有 `inactive / active / ended`。`ended` 终态不可复活；用户只能复制历史内容形成新草稿，确认后创建新计划。
- `TradePlanVersion` 是确认时的完整不可变内容。生效区间由 append-only `plan_activation` 保存，不覆盖版本状态；任一时点最多一个有效版本。
- 首切片提供明确的“确认并启用”原子动作。编辑 active v1 时 v1 继续 daily；只有 v2 确认并启用成功才原子结束 v1 生效区间并启用 v2。daily 在命令调用时选择当前 active 版本，再与最近完整 market session 的快照配对；因此 `2026-07-11` 确认的版本可以相对 `2026-07-10` MarketSnapshot 评估。
- `triggered` 是评估结果，不是计划状态。规则命中、到期或失效条件满足都不自动改变计划；只有用户显式 activate/deactivate/end 才改变生命周期。

### 2. 版本内容、规则与风险边界

每个确认版本至少固定 Security、顺序版本号与基线版本、用户输入来源声明、ResearchRun/Evidence/DataSnapshot 引用、期限与 `review_by`、规则全集、风险预算、市场门控策略、metric/evaluation policy versions、确认记录和 canonical content hash。

首切片没有账户与 Position，因此风险预算只支持用户或验收 fixture 输入的 CNY 绝对约束，如 `max_planned_notional`、`max_planned_loss`。平台不推荐这些数值；依赖真实仓位、成本或账户净值的规则返回 `not_applicable` 或 `unable_to_determine`，不能以零值代替。

`PlanRule` 的最小类型为：

- `entry_review / adjustment_review / exit_review`
- `invalidation / risk_limit / market_gate / observation`

effect 限定为 `prompt_review / mark_invalidation_candidate / mark_risk_limit_breach / block_user_intent / observe`，并用 `applies_to` 指明 entry/increase/decrease/exit/plan 范围。它们只重现用户预先确认的规则含义，不产生数量、委托价、订单或系统动作。冲突规则逐条保留；entry/increase 门控不能遮蔽 exit/invalidation/risk 结果。

条件使用版本化 typed AST：白名单 metric、exact decimal/enum/date/bool、显式单位/币种/窗口/session，以及 `eq/ne/lt/lte/gt/gte/between/crosses_above/crosses_below/changed_to` 和 `all/any/not`。不接受自由文本公式、代码、SQL 或 prompt。`crosses_*` 必须同时具备当前与前一完整 session；missing/conflict 按保守多值逻辑传播，不能当作 false。

绝对价格阈值以 canonical 未复权 CNY exact decimal 保存。从复权 K 线创建时必须依据确切 factor-set 反算并保存转换证据；无法唯一反算、公司行动冲突或单位不一致时禁止确认。未来因子修订不改写旧计划、标注或评估。

### 3. 透明 MarketSnapshot

`build_market_snapshot` 的输入固定为 Security、市场范围、请求时点、有效交易日、DataSnapshot、market model/version 与 freshness policy/version；它只消费冻结输入，不读取“最新数据”。相同 canonical 输入和组件 hash 复用同一不可变快照。

A 股第一切片以版本化 `CN_A_SHARE` universe 和 `000300.SH` benchmark 建立四个透明组件，不输出黑箱总分：

| 组件 | 原值与分类 |
|---|---|
| `market.trend` | benchmark close 同时高于 SMA20/SMA60 且 SMA20 五日斜率向上为 `up`；同时低于且斜率向下为 `down`；其余 `mixed` |
| `market.breadth` | cutoff 时仍上市的 A 股中，排除当日停牌、少于 20 个合法 session 或 blocking 数据者并记录原因；上涨占比和高于 SMA20 占比均 >=60% 为 `broad`、均 <=40% 为 `narrow`、其余 `mixed` |
| `market.liquidity` | 全市场成交额相对不含当日的前 252 个完整 session 的 percentile，至少 120 样本；70/30 分位为 `ample/normal/thin` |
| `market.volatility` | benchmark 日对数收益的 20 日、`sqrt(252)` 年化实现波动率，相对不含当日的前 252 个滚动观测的 percentile，至少 120 样本；80/20 分位为 `high/normal/low` |

同一 target-scoped snapshot 另含 `security.price_context`：未复权 close、日变化、SMA20/SMA60、完整 session、停牌/涨跌停和公司行动冲突事实。窗口、阈值、样本剔除、benchmark/universe/calendar 和算法都属于版本。宏观、资金、新闻、情绪、相关性/拥挤度和行业轮动在首切片明确为 `unsupported_in_first_slice`，不能填成中性。

快照逐组件保存 `observed_through`、freshness、quality、typed value/classification 与证据引用，整体状态为 `complete / limited / blocked`：

- PIT/hash/identity 失败、关键 OHLCV/日历陈旧或缺失、公司行动冲突，或计划实际引用的 metric 不可用时为 blocked；可保存解释缺口的 blocked 记录，但不能冒充完整当日状态。
- 未被规则引用的可选组件缺失或首切片明确未覆盖时为 limited；可继续求值可确定规则，结果标记 partial。
- 盘中或非交易日只使用最近完整 session，并同时展示请求日与有效日。历史快照的 freshness 相对原请求冻结；新的 daily 不能拿旧 session 冒充当前有效日。

### 4. 确定性 PlanEvaluation

```text
evaluate_plan(
  plan_version_id,
  market_snapshot_id,
  evaluator_id/version,
  evaluation_policy_version
) -> immutable PlanEvaluation
```

WorkflowRun 与触发来源只在外层引用，不改变领域结果。唯一幂等键就是上述四项；confirmation、daily、Web 重试或新工作流对同一组合均复用结果。同一 session 的数据修订产生新 MarketSnapshot，从而产生新评估；新计划版本或新 evaluator/policy 同理。旧结果永不覆盖。

结果分三轴：

- execution `status=completed | blocked`
- `outcome=triggered | not_triggered | unable_to_determine`（blocked 时无结论）
- `completeness=complete | partial`

每条规则保存 `triggered / not_triggered / unable_to_determine / blocked / not_applicable`、稳定 reason code、actual operands/单位/观测时点、effect/applies_to 与证据。至少一条确定触发则总体 triggered，即使其他规则 unknown，并标 partial；没有触发但 unknown 可能改变结论时为 unable；全部适用规则确定 false 才是 not_triggered。

首切片 reason-code family 至少固定 `CONDITION_TRUE`、`CONDITION_FALSE`、`INPUT_MISSING`、`INPUT_STALE`、`INPUT_CONFLICTED`、`QUALITY_BLOCKING`、`UNIT_OR_BASIS_MISMATCH`、`SNAPSHOT_SCOPE_MISMATCH`、`RULE_NOT_APPLICABLE`、`PLAN_REVIEW_OVERDUE`、`PLAN_EXPIRED`、`MARKET_CONSTRAINT_MATCHED`、`USER_GATE_MATCHED` 与 `INVARIANT_VIOLATION`。普通缺失且不破坏快照完整性可以形成 completed+unable/partial；stale、conflicted、blocking quality 或 identity/PIT/hash 失败使 status=blocked。blocked 不能被其他 triggered 结果覆盖；必须修复输入后用新快照/版本重新评估。

系统硬门禁只保护评估完整性与范围边界。停牌、涨跌停、市场状态或用户 market gate 是事实/规则输入；命中时只显示 `review_feasibility=restricted` 或用户意图受其规则限制，不阻止其他可计算规则，也不触发交易。invalidation 命中只标记候选，用户显式 `end(reason=invalidated, evaluation_id=...)` 后计划才结束。

### 5. 证据、接口与持久化

每个叶子结果都引用 rule version、snapshot component、DataSnapshot/derived/normalized inputs、metric/model/evaluator version 与 operand hash；研究上下文只通过 ResearchRun/Evidence typed refs 关联，不在运行时解析自然语言。canonical input/output JSON 与 reason codes 是权威，默认 UI 只展示变化、用户规则命中、限制和复核点；完整来源、窗口、成员、hash 和 journal 渐进披露。

application facade 最小命令为 `create/update/discard_plan_draft`、`confirm_plan_draft`、`activate_plan_version`、`deactivate_plan`、`end_plan`、`build_market_snapshot` 与 `evaluate_plan`。mutation 使用 invocation id 和 optimistic concurrency，均为短事务；接口中不存在 order/broker/export/execute 能力。

首切片新增的最小 typed tables 为：`trade_plan`、`trade_plan_transition`、`trade_plan_draft`、`trade_plan_version`、`plan_rule`、`plan_rule_condition`、`plan_risk_constraint`、`plan_activation`、`market_snapshot`、`market_snapshot_component`、`plan_evaluation`、`plan_rule_evaluation` 和 `plan_evaluation_evidence`。核心状态、金额、阈值和外键不能只藏 JSON；canonical JSON 作为版本化 artifact。全部实体引用既定 Security/DataSnapshot/derived/artifact 与 workflow identities，历史不得覆盖或删除。

### 6. 强制验收场景

1. v2 草稿未确认时 daily 仍评估 active v1；确认并启用成功后才原子切换至 v2。
2. 同一 version/snapshot/evaluator/policy 重跑复用一个结果；同 session 数据修订产生新 snapshot/evaluation，旧结果仍可回看。
3. 只有上一交易日缓存时可以回看历史，但请求 `2026-07-10` 的当日评估 blocked；缺失未引用组件可 completed+partial，引用缺失组件则 unable/blocked。
4. invalidation 命中不改状态；用户显式结束后 future daily 才不再选择计划。
5. 停牌/涨跌停、market gate 与其他规则同时命中时全部并列显示，无任何交易副作用。
6. 复权价格无法确定性反算时禁止确认；公司行动修订不改变旧阈值或历史结果。
7. 规则冲突不合成平台建议；真实 Position 不存在时不伪造风险暴露。
8. ended 计划不能复活；复制内容后确认得到新 TradePlan identity。
9. fixture 中规则、阈值和金额明确标为用户/验收输入，业务包没有 LLM API、券商、订单或执行路径。

本票只新增并澄清了 `TradePlanDraft` 领域术语，已同步到[领域词汇表](../../../CONTEXT.md)。状态机、规则 DSL、市场组件和表结构属于本 Spec 的实现合同，不另建 ADR；它们没有引出新的 Wayfinder fog 或新票据。下一张“决定纵向切片验收与复用 seam”现已解除本票阻塞。
