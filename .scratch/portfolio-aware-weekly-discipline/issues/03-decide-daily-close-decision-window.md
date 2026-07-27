# 决定收盘后评估与下一交易日窗口语义

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

在第一版明确不支持盘中做 T 的前提下，锁定 A 股“当前完整交易日收盘数据 -> 收盘后冻结输入和评估 -> 下一交易日可查看决策状态”的时间合同：requested/effective/as_of/available_at 如何落位，周末与节假日如何回退，涨跌停、停牌、T+1、复权、公司行动冲突和缺失当日数据如何阻断，日线信号为什么不得假设在同一收盘价无摩擦执行？给出可测试的正常与反例矩阵。

## Answer

### 决定

第一版采用单向时间语义：

`用户请求日 -> 已完整且在 PIT cutoff 前可用的有效交易日 -> 不可变日终输入/评估版本 -> 下一开放交易日决策状态`

日终评估是研究与纪律状态，不是订单，也不产生同日或次日必然成交的假设。即使 2026 年 7 月 6 日起沪深市场允许全部 A 股在 15:05-15:30 进行盘后固定价格交易，本切片仍明确排除该同日执行窗口：只有盘后阶段结束、要求的数据集均完成发布并满足 `available_at <= as_of_at` 后，才能冻结输入；最早面向 `next_session_date` 展示决策状态。上交所现行规则的生效时间与盘后交易扩围见[《上海证券交易所交易规则（2026年修订）》](https://big5.sse.com.cn/site/cht/www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)，深交所现行规则的交易时间、T+1、涨跌幅、停牌和除权除息条文见[《深圳证券交易所交易规则（2026年修订）》](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)。

### 时间字段合同

| 字段 | 唯一语义 | 不变量 |
|---|---|---|
| `requested_date` | 用户希望评估的 `Asia/Shanghai` 市场自然日，不代表该日一定开市或数据已经可用。 | 原样保留，不得被回退日期覆盖。 |
| `requested_at` | 用户或调度器发出请求的带时区时间。 | 用于审计，不参与伪造数据可见性。 |
| `as_of_at` | 本次冻结允许观察到信息的 PIT cutoff；必须带时区并落在评估实际发生时点或之前。 | 任一成员的 `available_at > as_of_at` 均不得进入快照。 |
| `effective_session_date` | 版本化交易日历中 `<= requested_date` 的最近开放日，且该市场日的强制日终数据在 cutoff 前完整可用。 | 只能由已冻结的交易日历决定，不能用“工作日”推算。开放日数据未完成时不得静默回退为更早日期。 |
| `next_session_date` | 同一冻结日历中严格晚于 `effective_session_date` 的首个开放日。 | 只是决策状态面向的最早交易日，不是成交日期或价格承诺。 |
| `published_at` | 数据源声称该事实被发布/生效的时间。 | 不等于平台何时可知。 |
| `available_at` | 该版本最早可被本系统实际观察并用于 PIT 推演的时间。 | 是能否纳入本次快照的核心门。 |
| `retrieved_at` | 本系统取得原始响应的时间。 | 必须保留来源链；不得用它覆盖源端 `published_at` 或推早 `available_at`。 |
| `calendar_version` / `source_policy_version` / `freshness_policy_version` | 决定日期解析、来源资格和 freshness 的版本身份。 | 必须进入快照身份；版本变化生成新快照，不改写旧快照。 |

冻结结果必须有 `ready | blocked | superseded` 状态。`ready` 要求交易日历、证券身份、未复权日线、停复牌/涨跌停状态、公司行动检查以及本次规则需要的账户/研究输入全部通过各自 freshness/quality gate；任何关键输入缺失时输出 typed blocker，而不是沿用旧值冒充当日值。

### 日期回退与缺失数据

- 周末、法定节假日或交易所公告休市日：`requested_date` 保持原值，`effective_session_date` 回到版本化日历中的最近开放日，`next_session_date` 指向之后首个开放日。交易所规则明确周一至周五之外，法定假日和交易所公告休市日也休市，因此不得用简单 weekday 算法。
- 请求发生在开放日但盘后数据尚未完成：状态为 `blocked / CLOSE_DATA_NOT_READY`；待数据可用后以新的 `as_of_at` 重试。不得悄悄回退到前一交易日。
- 市场开放且证券缺少日线：有同日权威停牌状态时，以“停牌、无可执行价格”进入 constraint；没有可解释的停牌/摘牌/公司行动证据时为 `blocked / SECURITY_DAILY_MISSING`。
- Provider 后补或修订：旧快照保持不可变；新 `available_at` 只能创建并列的新版本与新快照。前一版本可标记 `superseded`，但历史评估继续指向原 identity。
- 交易日历本身缺失、冲突或版本过期：`blocked / TRADING_CALENDAR_UNQUALIFIED`，不推测有效日和下一交易日。

### 交易可行性与价格口径

- **T+1**：现行交易规则规定买入证券在交收前不得卖出，回转交易品种除外。普通 A 股规则只允许把日终状态面向下一开放日；账户若没有 `available_to_sell` 或可证明的持仓批次，卖出可行数量为 `unknown`，不得把总持仓当成可卖数量。
- **停牌**：停牌状态不影响市场级 `effective_session_date`，但该证券的执行可行性为 `blocked`；评估仍可保存“规则是否满足”的分析结果，但必须与“是否可执行”分栏。
- **涨跌停**：触及限制价不等于一定不能成交，也不等于一定成交。结果为 `execution_feasibility=constrained/unknown`，需要下一交易日实时盘口才能重新判断；不得用收盘价填充成交价。
- **复权**：执行阈值、涨跌停和市值口径使用 `adjustment_mode=none` 的可交易价格；趋势/收益序列可使用明确版本的前/后复权序列。两类价格不能在同一条件中混算，输出必须带 adjustment identity。
- **公司行动**：除权除息、送转、配股、证券代码/股份变化会改变价格和数量可比基础。现行深交所规则规定权益登记日次一交易日进行除权除息处理。公司行动数据缺失或与价格因子冲突时，跨日价格条件为 `blocked / CORPORATE_ACTION_CONFLICT`；不得把机械除权误判为基本面失效或价格触发。

### 为什么不能用同一收盘价成交

日线的收盘价、最终成交量和市场状态是信号输入；只有交易结束后且 Provider 将完整版本标记为可用，系统才“知道”这些输入。把据此产生的信号再回填到同一收盘价，使用了成交时尚不可得的信息，形成 look-ahead bias。除此之外，价格优先/时间优先、盘后时段、停牌、涨跌停、流动性、费用和 T+1 都会令信号价与可成交价分离。因而本合同只保存：

- `signal_session_date = effective_session_date`
- `decision_available_at = max(required_input.available_at)`
- `earliest_decision_session = next_session_date`
- `execution_price = unknown`

任何后续模拟或绩效归因至少使用下一交易日可观察的价格规则并显式建模滑点/未成交；本切片不生成订单或收益承诺。

### 可测试矩阵

| 编号 | 输入 | 预期 |
|---|---|---|
| N1 | 周三盘后，日历与全部强制数据在 cutoff 前完成 | `requested=effective=周三`，`next=周四`，`ready`。 |
| N2 | 周六请求，周五为开放日、周一非假日 | `requested=周六`，`effective=周五`，`next=周一`。 |
| N3 | 长假最后一天请求 | 回退至假前最后开放日，`next` 为交易所日历中的节后首个开放日。 |
| N4 | 同一原始版本重复请求且 cutoff/政策相同 | 快照 identity 与评估结果幂等复用。 |
| N5 | 后补公司行动或修订日线在更晚时点可用 | 创建新版本/新快照；旧评估可追溯且不被改写。 |
| X1 | 开放日 15:10 请求，最终日线/盘后量尚未可用 | `blocked / CLOSE_DATA_NOT_READY`，不得回退到昨日。 |
| X2 | 开放日缺失证券日线且无停牌证据 | `blocked / SECURITY_DAILY_MISSING`。 |
| X3 | 证券有权威全天停牌状态且无成交 | 市场日仍有效；证券执行 `blocked_suspended`，不伪造收盘成交。 |
| X4 | 收盘触及涨停或跌停 | 分析条件可计算；执行为 `constrained/unknown`，成交价仍未知。 |
| X5 | 手工账户只有总持仓，没有可卖数量/批次 | T+1 相关执行能力 `unknown`，不得将总量视为可卖。 |
| X6 | 原始价格阈值与复权序列混用 | `blocked / ADJUSTMENT_BASIS_MISMATCH`。 |
| X7 | 除权日价格跳变但公司行动或因子缺失/冲突 | `blocked / CORPORATE_ACTION_CONFLICT`，不触发价格失效结论。 |
| X8 | 交易日历缺失、过期或沪深状态冲突 | `blocked / TRADING_CALENDAR_UNQUALIFIED`。 |
| X9 | 数据 `published_at` 在 cutoff 前但 `available_at` 在 cutoff 后 | 排除该版本；不得以发布时间假设系统已知。 |
| X10 | 用周三收盘信号和周三收盘价计算“可实现收益” | 验收失败，必须从周四的显式执行价格规则开始。 |

### 对后续地图的约束

- MarketRegime v2、持仓 readiness、计划评估和 weekly review 必须共同引用同一个冻结的 `effective_session_date`、`next_session_date`、`as_of_at` 与日历 identity。
- 每日 orchestrator 必须先完成冻结，再计算确定性规则，最后发布下一交易日 inbox；不得让 Web 在读取时临时拼接不同 cutoff 的最新数据。
- UI 主视图必须把“规则状态”和“执行可行性”分开显示，并对 stale、blocked、unknown 和 superseded 做清晰差异提示。
