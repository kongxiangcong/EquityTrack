# 估值与分析方法论复核

复核日期：2026-07-10
适用范围：个人股票研究系统，不涉及自动下单。外部校准只使用 CFA Institute 与 Aswath Damodaran 的公开一手教学/研究材料。

## 总体判断

当前 `skills/valuation/` 的方向大体正确：L2 不等于默认 DCF；FCFF 必须匹配 WACC；金融企业、创新药、周期资源等需要不同模型；同业样本必须做币种、会计和生命周期检查。问题主要不在“知道哪些方法”，而在“如何把方法变成可执行、可降级、可验证的系统”。

CFA 的自由现金流估值材料强调，FCFF/FCFE 需要从财务信息计算，预测未来现金流是依赖公司经营、融资和行业理解的高要求工作，而不是套用一个默认增长率即可完成。[CFA Institute: Free Cash Flow Valuation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation)

Damodaran 对 firm valuation 与 equity valuation 的核心约束是现金流和折现率必须匹配：FCFF 用 WACC，FCFE 用 cost of equity；混用会造成系统性偏差。[Damodaran: Valuation](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/val.html) 这条约束应成为可执行 invariant，而不是报告中的文字提醒。

## DCF 复核

### 保留

- `FCFF = EBIT × (1-t) + D&A - CapEx - ΔNWC` 的基本桥；Damodaran 也将 FCFF定义为税后经营利润减去净资本开支和非现金营运资本变化。[Damodaran: Financial Measures and Ratios](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/definitions.html)
- FCFF/WACC 与 FCFE/Ke 不混用。
- `WACC > terminal growth`。
- 终值、显性期、股权桥和每股稀释必须分开展示。
- DCF 只在业务和现金流可建模时启用；不稳定公司应使用情景或其他方法交叉检查。

### 调整

1. **季度字段不应一刀切。** 最近年度官方 D&A 与 CapEx 可以支持年度预测基线；最新季度未披露 D&A 时，应降低 freshness/quality 并限制短期桥，而不是自动让所有研究失效。只有当该缺口对所选 DCF 的现金流或企业价值桥具有实质影响时，才禁用正式 DCF。
2. **租赁负债按定义和重要性处理。** Damodaran 将 operating leases 的处理列为需要重述盈利、现金流和债务的特殊问题，而不是所有公司的统一固定字段。[Damodaran: Research and Papers](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/papers.html) 新系统应记录采用 pre-IFRS16 还是 post-IFRS16 口径，并避免在 EV、EBITDA 与租赁负债之间重复调整。
3. **WACC 必须由证据构成。** 当前方法文档的“典型 WACC 区间”只适合作为诊断。Damodaran 将 WACC 定义为不同融资来源成本按市场价值权重组合；每一项输入应有来源和日期。[Damodaran: Estimating Inputs for DCF](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/dcfinput.html)
4. **增长与再投资联动。** 长期增长不能独立于资本回报和再投资率。Damodaran 强调，用基本面增长率能迫使高增长假设同时支付相应再投资成本。[Damodaran: An Introduction to Valuation](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/background/valintro.htm)
5. **终值占比是诊断，不是硬门槛。** 50%-70% 或 80% 只能提示模型对远期假设敏感；真正的检查是稳态增长、稳态利润率、再投资率、ROIC 与 WACC 是否彼此一致。
6. **优先提供 reverse DCF。** 数据不足但市场价格可靠时，反推市场隐含增长/利润率通常比强行输出一个点值更有解释力。它应被建模为“市场预期诊断”，不等于正式内在价值结论。

### 可执行 DCF 的最小接口

```text
evaluate(dcf_case, evidence) -> MethodResult

dcf_case:
  valuation_date
  forecast_periods[]
  revenue / margin / tax / reinvestment drivers
  discount_rate_components
  terminal_state
  equity_bridge
  diluted_share_bridge

MethodResult:
  status
  enterprise_value_range
  equity_value_range
  diagnostics[]
  sensitivities[]
  evidence_ids[]
  disabled_reasons[]
```

当前 v2 计算器已经要求预测币种与单位、可重算的 WACC components、可用来源证据、`WACC > g` 和完整股权桥；peer 与历史带进一步解析到具体 `source_id + field_name + period`。`not_applicable` 的结构化 materiality schema 尚未实现，因此现阶段未知桥接项不会静默视为零；真实零值也必须由来源明确记录，否则只禁用 DCF。

任何默认值只能存在于明确标注的探索情景，不能在没有来源时静默进入正式结果。

## 股权桥与每股价值

从企业价值到每股价值不是简单的 `EV - debt + cash`。Damodaran 对每股价值的讨论明确区分现金是否已经包含在所用现金流中，并要求处理非经营资产、交叉持股、潜在负债、期权/认股权和股数。[Damodaran: Getting to Equity Value per Share](https://pages.stern.nyu.edu/adamodar/New_Home_Page/littlebook/valuepershare.htm)

因此当前 23 字段列表不应全部变成全局必填，而应成为 equity bridge 的候选调整项：

- `cash`、`debt`、`diluted_shares` 通常是核心；
- `lease_debt` 是否进入取决于估值口径；
- `preferred_stock`、`minority_interest`、`pension_deficit`、`associates_jv_value`、`non_operating_assets` 只有在存在且具有实质性时才成为硬需求；
- 不适用项目可以通过公司/会计证据声明 `not_applicable`，不应要求每期重复证明零值。

## 可比公司与历史估值带

### 可比公司

当前“至少 3 个可用同业”的底线可保留，但必须是方法级门禁。可执行实现至少要记录：

- 选择/剔除理由；
- 估值日期与价格来源；
- LTM、NTM 或 FYx 分母的一致性；
- 币种、会计准则、租赁和少数股东口径；
- 负分母与极端值处理；
- 增长、利润率、ROIC、规模和生命周期差异。

系统应返回 peer distribution 与差异解释，不应只把中位数乘以公司指标。

### 历史估值带

历史带是 relative-to-self 方法，可以在 DCF 不可用时独立运行。它需要：

- 复权价格与当时可获得的滚动财务分母，避免未来信息泄漏；
- 处理会计重述、重大资产重组、股本变化和亏损期；
- 周期企业优先观察 P/B、EV/EBITDA 或 mid-cycle denominator，避免“盈利峰值导致 P/E 机械变低”的周期陷阱；
- 把结构性业务变化解释为 regime change，而不是机械回归均值。

## 金融企业

当前禁用普通 FCFF/WACC DCF 的方向应保留。Damodaran 指出，金融公司的债务更像经营原材料，企业价值和资本成本的通常定义可能失去意义，同时净资本开支和营运资本式再投资难以定义。[Damodaran: Financial Service Company Characteristics](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/financialsvccompanies.htm)

金融企业优先路由：

- P/B 与 ROE/COE 驱动；
- residual income / excess return；
- DDM 或监管资本可分配现金流；
- 银行关注资本充足率、信用成本、NIM 和资产质量；保险关注偿付能力、承保利润和准备金质量。

CFA 将 residual income 定义为净利润扣除股权资本机会成本，并给出每股 residual income 与 ROE-COE 的表达。[CFA Institute: Residual Income Valuation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/residual-income-valuation) 这为后续实现金融行业 adapter 提供了清晰接口。

## 周期、资源、地产、医药与软件

当前行业矩阵的方向可保留，但应将每类方法实现为独立 registry entry：

| 公司类型 | 主方法 | 关键执行约束 |
|---|---|---|
| 周期制造 | mid-cycle PE/EV/EBITDA、P/B | 价格、产能利用率、库存、成本和利润率回归中周期 |
| 资源 | NAV、储量/产量、成本曲线 | 资源量、品位、矿山寿命、商品曲线和维持性资本开支 |
| 地产 | NAV/RNAV、项目现金流、P/B | 土储、可售货值、去化、受限资金、债务期限 |
| 创新药 | rNPV/SOTP、cash runway | 资产/适应症/阶段、PoS 依据、权益归属、里程碑与研发成本 |
| SaaS | EV/Sales、Rule of 40、成熟期 FCF | ARR、NRR、churn、CAC payback、SBC 和 FCF margin |

在这些模型落地前，系统可以正确路由和解释“为什么暂不可执行”，但不能把文档清单宣称为已实现估值能力。

## 情景、敏感性与概率

必须区分三类概念：

- **敏感性**：在其他条件不变时改变一个或两个 driver，属于确定性计算；
- **情景**：一组相互一致的经营、财务和估值假设；
- **统计置信区间**：需要样本、误差模型和分布假设，不能用任意 ±15% 代替。

默认情景不分配概率。只有概率来源、校准方法和更新规则可审计时，才允许 probability-weighted result。

## 对本轮重构的验收标准

1. 意华股份缺少季度 D&A 与完整租赁债务时，`research_core` 和 `conditional_research_plan` 仍可用。
2. 这些缺口不会升级为官方事实；使用估算时状态必须是 `ready_with_estimates`。
3. DCF 只因 DCF 专属输入不足而受限，不再阻断 HTML 报告。
4. 同业样本不足只禁用 comps；历史带和观察倍数可独立评估。
5. 所有方法返回相同结构的 `MethodResult`，包含状态、假设、诊断和证据引用。
6. HTML 和 JSON 来自同一 `ResearchRun`，不存在报告脚本重新发明金融数字的路径。
