# EquityTrack V2 Phase 1：一手来源核验与文档修正建议

> 研究日期：2026-08-23
>
> 访问日期：除非单独说明，全部 URL 最后访问于 2026-08-23。
>
> 用途：为 `EquityTrack_V2_Phase1_Skills_Fast_Path_CN` 的重写提供证据底稿。本文不提供个股评级、目标价或个性化投资建议。
>
> 来源边界：只采用论文原文、期刊/出版社、作者或大学主页、CFA Institute、NIST、SEC、美联储等一手或权威机构来源；未采用 Consensus 等摘要聚合页。

## 1. 结论先行

用户提出的产品收缩方向总体有充分依据，但必须把三类内容分开：

1. **文献直接支持的事实**：结果偏差存在；概率预测应使用严格适当评分并区分校准与分辨率；适当性和风险约束必须在组合层面判断；Kelly 对输入和短期回撤敏感；价格隐含预期是一种有效研究视角；反复搜索会造成回测过拟合；Monte Carlo 的输出质量受输入分布、相关性和结构假设支配；高换手在若干大样本个人投资者研究中与显著的净业绩损失相关；AI 评测需要真实任务、定量与定性方法、边界案例和领域专家复核。
2. **有依据、但必须限定的设计选择**：EquityTrack 采用“隐含预期优先”、把风险约束做成硬门、默认先用情景/敏感性/压力测试、让 LLM-as-judge 只能评软质量，均是合理的安全设计；它们不应被写成所有投资流程都必须遵循的唯一学术结论。
3. **项目自定义政策**：七个核心对象、五个内部 Skill、`Wmax` 公式、少于三家可比公司即禁用、G0—G5 分层、G0—G3 任一失败即全案失败、20 个初始案例、错误分类和经验晋升状态机，都是 EquityTrack 的领域合同或保守阈值，不是外部文献已经证明的通行标准。文档应明确标注为 `V2 policy`，并通过 Bench 演进。

### 1.1 主张核验矩阵

| Phase 1 候选主张 | 结论 | 可进入文档的强度 |
|---|---|---|
| 决策过程质量应与随机结果分开评价 | **直接支持** | 可写成产品不变量 |
| Brier score 可以衡量概率校准 | **需修正** | Brier 衡量整体概率预测质量；校准只是其可分解的一部分 |
| 风控不是概率判断之后的附属步骤 | **作为产品政策支持** | 可写成硬约束设计原则，不写成概率论定理 |
| Kelly 不应默认生成基本面投资仓位 | **充分支持且保守** | 可写为禁用默认路径，最多做诊断 |
| 反向估值/隐含预期应优先 | **方法有依据，优先级是项目选择** | 写成 V2 默认研究顺序，不写成唯一正确估值法 |
| 金融机构应禁用普通 FCFF/WACC DCF | **方向支持、措辞需限定** | 在债务是经营原料且再投资无法可靠定义时默认禁用；不等于所有 DCF/权益估值都失效 |
| 少于 3 家可比公司不能形成估值结论 | **未发现通行标准** | 只能写成 EquityTrack 的保守硬门 |
| 无分布依据的 Monte Carlo 只是伪精确 | **充分支持** | 可写成启用门；还应增加结构变化和参数不确定性 |
| 大量参数搜索容易回测过拟合 | **直接支持** | 可写成 Bench/研究治理不变量 |
| 个人投资者频繁交易通常付出业绩代价 | **样本层面直接支持，外推需限定** | 写成经验风险信号，不写成所有交易的因果定律 |
| 长期、宽样本下 LLM 投资优势退化 | **特定研究支持** | 只能归因于具体 KDD 2026 研究及其设定，不能泛化到所有 LLM 策略 |
| 金融 Agent 应用“硬不变量 + 软 rubric” | **组合证据支持，具体分层是项目政策** | 硬门由确定性验证器执行；软质量由领域 rubric/专家抽审；不得互相抵消 |
| 20 个冻结案例足以证明金融质量与概率校准 | **不支持** | 只能称“第一批回归/安全种子集”，不能称统计验证 |

## 2. 决策过程、结果偏差与概率校准

### 2.1 结果偏差：过程和结果必须分表

#### 来源 A：Baron & Hershey（1988）

- **来源**：Jonathan Baron & John C. Hershey, “Outcome Bias in Decision Evaluation,” *Journal of Personality and Social Psychology*, 54(4), 569–579。
- **发布日期**：1988。
- **可核验 URL**：[DOI](https://doi.org/10.1037/0022-3514.54.4.569)；[宾夕法尼亚大学作者 PDF](https://www.sas.upenn.edu/~baron/papers/outcomebias.pdf)。
- **直接支持**：在评价者获得相同的事前信息时，仅改变随机结果的好坏，评价者仍会改变对决策质量和决策者能力的评分。这是“结果偏差”的经典实验依据。
- **适合进入 Phase 1 的表述**：

  > `DecisionReview` 必须分别保存 `process_evaluation` 与 `outcome_evaluation`。过程评价只使用决策当时可获得的信息；结果评价记录事后收益和风险。盈利不能自动证明过程正确，亏损也不能自动证明过程错误。

- **限定**：实验支持“分离评价”，并不直接验证 EquityTrack 的具体错误标签，也不证明任何单笔交易可被客观归类为 `RANDOM_OUTCOME`；分类仍需预先定义规则和人工复核。

#### 来源 B：König-Kersting 等（2021）

- **来源**：Christian König-Kersting, Marc Pollmann, Jan Potters & Stefan T. Trautmann, “Good decision vs. good results: Outcome bias in the evaluation of financial agents,” *Theory and Decision*, 90, 31–61。
- **发布日期**：2020-09-17 在线发表；卷期年份 2021。
- **可核验 URL**：[出版社全文与 DOI](https://link.springer.com/article/10.1007/s11238-020-09773-1)。
- **直接支持**：三个实验中，委托人知道代理人的策略和随机生成机制，评价与奖励仍强烈受随机结果影响；违反委托人偏好的决策在随机盈利后，甚至可能比遵守偏好但随机亏损的决策得到更高评价。
- **适合进入 Phase 1 的表述**：

  > 复盘界面不得以最终收益作为过程评分的输入捷径。应先冻结并评分事前证据、假设、风险预算和计划遵守情况，再展示结果与归因。

- **限定**：该研究验证的是评价偏差，不是交易策略收益，也不提供 EquityTrack 评分权重。原需求中的 Consensus 聚合链接应替换为上述论文出版社链接。

### 2.2 概率校准：不能只存一个 Brier 分数

#### 来源 C：Brier（1950）

- **来源**：Glenn W. Brier, “Verification of Forecasts Expressed in Terms of Probability,” *Monthly Weather Review*, 78(1), 1–3。
- **发布日期**：1950-01。
- **可核验 URL**：[DOI/AMS 期刊页](https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2)。
- **直接支持**：为概率预测定义平方误差型评分。对二元事件，常用形式为 `BS = mean((p - y)^2)`，越低表示整体概率预测损失越小。
- **限定**：Brier score 同时受到校准、分辨率和事件基础率影响。它不是“校准误差”的同义词，也不能凭少量单笔决策判断一个人是否已校准。

#### 来源 D：Murphy（1973）

- **来源**：Allan H. Murphy, “A New Vector Partition of the Probability Score,” *Journal of Applied Meteorology*, 12, 595–600。
- **发布日期**：1973。
- **可核验 URL**：[DOI/AMS 期刊页](https://doi.org/10.1175/1520-0450(1973)012%3C0595:ANVPOT%3E2.0.CO;2)。
- **直接支持**：概率分数可分解为不确定性、可靠性（校准）和分辨率等部分，因此同一个总分可能掩盖不同类型的预测质量。
- **适合进入 Phase 1 的表述**：

  > 概率学习必须按同一事件定义和同一预测期限积累样本，并至少报告：样本数、Brier score、按概率区间的观测频率（reliability/calibration）、分辨率与基础率基准。样本不足时输出 `INSUFFICIENT_HISTORY`，不得输出“已校准”。

#### 来源 E：Gneiting & Raftery（2007）

- **来源**：Tilmann Gneiting & Adrian E. Raftery, “Strictly Proper Scoring Rules, Prediction, and Estimation,” *Journal of the American Statistical Association*, 102(477), 359–378。
- **发布日期**：2007。
- **可核验 URL**：[DOI](https://doi.org/10.1198/016214506000001437)；[华盛顿大学作者 PDF](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf)。
- **直接支持**：严格适当评分规则鼓励预测者如实报告其主观概率；预测质量还应区分校准与 sharpness/resolution。
- **工程含义**：`DecisionCard` 需要冻结概率、事件定义、判断时点、到期日和结果解析规则。若事后修改事件定义或把未发生/未知混成零，任何校准统计都失去含义。
- **限定**：文献不决定 EquityTrack 应使用哪些概率桶或最小样本数；这些必须在 Bench 中版本化。

## 3. 组合风险硬约束、风险预算与 Kelly 的边界

### 3.1 风险约束应独立于研究结论执行

#### 来源 F：CFA Institute Standard III(C) — Suitability

- **来源**：CFA Institute, Standard III(C): Suitability。
- **发布日期/版本**：页面标注 2024-04 更新。
- **可核验 URL**：[CFA Institute 官方标准](https://www.cfainstitute.org/standards/professionals/code-ethics-standards/standards-of-practice-iii-c)。
- **直接支持**：投资判断应结合整体组合的目标、风险承受能力和约束，而不能只看单一证券；即使完成适当性判断，仍不能保证避免损失。
- **适合进入 Phase 1 的表述**：

  > `InvestmentCase` 的概率和赔率不能覆盖 `RiskPolicy`。计划只有在组合层面的集中度、流动性、相关暴露、最大可承受损失和确认状态全部通过时，才可从 `DRAFT` 进入 `ACTIVE`。通过门禁不意味着保证盈利，只意味着风险在已声明政策内。

- **限定**：CFA 标准面向专业服务和客户适当性；EquityTrack 是单一用户产品，不应把该标准误写成适用于软件的法律义务。这里采用的是其组合约束原则。

#### 来源 G：CFA “Investment Objectives and Constraints”

- **来源**：CFA Institute, *Investment Objectives and Constraints* refresher reading。
- **发布日期**：2018 版本。
- **可核验 URL**：[CFA 官方 PDF](https://www.cfainstitute.org/sites/default/files/-/media/documents/article/refresher-readings-free/rr-2018-l2v6r47.pdf)。
- **直接支持**：风险承受能力同时取决于承担风险的意愿和财务能力；可用最大可接受损失等量化目标表达；风险预算从选择风险度量和确定总预算开始，再分配给组合中的投资。
- **工程含义**：风险政策应是确定性输入，至少规定总损失预算、单一标的集中度、流动性、暴露上限和缺失数据时的 fail-closed 行为。LLM 可以解释约束，但不得修改账户真值、计算公式或最终上限。

### 3.2 `Wmax` 是 V2 政策公式，不是文献定理

需求中的公式：

```text
Wmax = min(Rportfolio / Lstress,
           Wconcentration,
           Wliquidity,
           Wcorrelation,
           Wpolicy)
```

可作为保守上限聚合器，但文档必须补齐以下合同：

- `Rportfolio` 与 `Lstress` 的单位必须匹配。若前者是总资产损失比例，后者应是“单位仓位在指定压力情景下的损失比例”，且 `Lstress > 0`。
- `as_of`、价格、流动性窗口、压力情景版本和账户净值必须冻结；任何关键输入缺失时返回 `BLOCKED/INSUFFICIENT_EVIDENCE`，不能按零处理。
- `Wcorrelation` 不是天然存在的标量。相关性随样本窗口、市场状态和持仓变化而变；更清楚的命名是 `Wfactor_or_correlated_exposure_cap`，或者用确定性的边际风险/暴露计算产生上限。
- 该公式只计算**上限**，不生成“应该买多少”的建议；实际计划还要受允许动作、最大单次变化和人工确认约束。
- 所有 cap 的来源和版本必须可追溯。若多个约束并列，结果应返回实际起约束作用的 `binding_constraint`。

这是一项可测试的 EquityTrack 领域政策；外部文献支持“组合风险预算与约束”的原则，但未验证这组 `min(...)` 项就是唯一或最优公式。

### 3.3 Kelly 只适合诊断，不适合默认仓位生成

#### 来源 H：Kelly（1956）

- **来源**：J. L. Kelly Jr., “A New Interpretation of Information Rate,” *Bell System Technical Journal*, 35, 917–926。
- **发布日期**：1956-07。
- **可核验 URL**：[DOI](https://doi.org/10.1002/j.1538-7305.1956.tb03809.x)。
- **直接支持**：Kelly 准则在给定赔率和事件概率、可重复下注等假设下最大化长期对数财富增长率。
- **限定**：原始模型并不是最大损失、集中度或流动性的硬约束；它假设概率/赔率可描述且重复机会具有可利用的统计结构。个人基本面判断通常不满足这些输入条件。

#### 来源 I：MacLean, Thorp & Ziemba（2010）

- **来源**：L. C. MacLean, E. O. Thorp & W. T. Ziemba, “Long-term capital growth: the good and bad properties of the Kelly and fractional Kelly capital growth criteria,” *Quantitative Finance*, 10(7), 681–687。
- **发布日期**：2010-08-10 在线发表。
- **可核验 URL**：[DOI](https://doi.org/10.1080/14697688.2010.506108)；[加州大学机构仓储全文](https://escholarship.org/uc/item/5mr5k8qj)。
- **直接支持**：全 Kelly 具有长期增长优势，但短期风险高、可能建议很大的下注，在不利路径下可能损失大部分财富；分数 Kelly 可在增长与风险之间折中。
- **适合进入 Phase 1 的表述**：

  > Kelly 不得成为默认仓位生成器。只有当概率、赔率、重复性和估计误差都有可审计依据时，系统才可将 Kelly/分数 Kelly 作为只读诊断；其输出不得覆盖组合风险硬门，也不得直接创建或激活计划。

- **限定**：即使使用 fractional Kelly，也不能代替集中度、流动性、尾部损失和用户政策约束。

## 4. 隐含预期、反向估值与方法适用性

### 4.1 “隐含预期优先”有方法依据，但优先级是产品选择

#### 来源 J：Mauboussin & Rappaport（2021）

- **来源**：Michael J. Mauboussin & Alfred Rappaport, *Expectations Investing: Reading Stock Prices for Better Returns*，Columbia University Press。
- **发布日期**：2021-09。
- **可核验 URL**：[Columbia University Press 书籍页](https://cup.columbia.edu/book/expectations-investing/9780231554848/)。
- **直接支持**：从已知市场价格出发，反推该价格所隐含的未来经营结果，再判断哪些预期修正可能改变价值，是一套明确的研究方法。
- **适合进入 Phase 1 的表述**：

  > V2 的默认估值顺序是：先把当前价格映射为一组可解释的经营假设，再与基准率、企业驱动因素和可观察证据比较；只有在存在可说明的预期差且输入充足时，才继续做正向估值区间。

- **限定**：反向估值不是从价格“读出唯一真相”。同一价格可由不同增长、利润率、再投资、资本成本和终值组合解释；输出必须展示非唯一性和敏感性。

#### 来源 K：Damodaran 的 DCF 与 implied growth 教学材料

- **来源**：Aswath Damodaran, NYU Stern 官方估值课程材料。
- **发布日期**：课程页面未统一标注；按访问日记录。
- **可核验 URL**：[DCF 基本匹配规则](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/val.html)；[implied growth 示例 PDF](https://pages.stern.nyu.edu/~adamodar/pdfiles/dcfegs.pdf)。
- **直接支持**：FCFE 应按股权资本成本折现，FCFF 应按 WACC 折现，不得混用；可通过令 DCF 价值等于市场价格来求解价格隐含的增长/经营假设。
- **工程含义**：`ValuationCase` 应保存 cash-flow definition、discount-rate definition、单位/币种、股本、估值日和求解变量；反向估值必须能复算，并明确哪些变量被固定、哪个变量被求解。

### 4.2 三类主链是范围收缩，不是穷尽所有估值法

#### 来源 L：CFA Free Cash Flow Valuation（2026）

- **来源**：CFA Institute, “Free Cash Flow Valuation.”
- **发布日期/版本**：2026 refresher reading。
- **可核验 URL**：[CFA 官方页面](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation)。
- **直接支持**：DCF 把预期未来现金流折现为内在价值；FCFF/FCFE 的计算和预测要求高；FCFF 通常按 WACC 折现。自由现金流模型在股息与实际支付能力偏离、且现金流能在合理期限与盈利能力对齐时更有用。
- **Phase 1 限定**：DCF 不应因“有模型”就默认启用。需要明确可预测期、现金流定义、折现率、再投资、终值和数据质量，并在任何关键输入不足时禁用该方法。

#### 来源 M：CFA Market-Based Valuation（2026）与 Damodaran comparables

- **来源**：CFA Institute, “Market-Based Valuation: Price and Enterprise Value Multiples”；Aswath Damodaran, “Comparable Firms.”
- **发布日期/版本**：CFA 2026；Damodaran 页面未标注统一日期。
- **可核验 URL**：[CFA 官方页面](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples)；[NYU Stern comparables](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/comparables.htm)；[Damodaran 相对估值章节 PDF](https://pages.stern.nyu.edu/~adamodar/pdfiles/acf3E/book/ch12.pdf)。
- **直接支持**：相对估值要求选择可比较对象并控制增长、风险、现金流和会计差异；“同一行业”本身不保证真正可比，可比对象太少会让估计困难。
- **关键修正**：没有权威来源给出“可用 peers 少于 3 家则估值结论必然无效”的普遍阈值。可以保留为 EquityTrack 的保守规则，但字段应写成：

  ```text
  policy_id = MIN_USABLE_PEERS_V1
  threshold = 3
  consequence = METHOD_DISABLED_FOR_CONCLUSION
  rationale = conservative_project_policy
  ```

  同时记录被排除 peer 的原因，而不是只记录数量。

#### 来源 N：CFA Residual Income Valuation（2026）

- **来源**：CFA Institute, “Residual Income Valuation.”
- **发布日期/版本**：2026 refresher reading。
- **可核验 URL**：[CFA 官方页面](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/residual-income-valuation)。
- **直接支持**：剩余收益是会计净利润减去股权资本费用；公司即使报告正净利润，也可能未创造股东经济价值。该方法有自身的会计假设、优点和局限。
- **工程含义**：剩余收益不是“数据少时的 DCF 替代品”。必须验证账面价值、净盈余关系、会计调整、持续经营和资本成本输入。

### 4.3 金融机构：禁用普通企业 FCFF/WACC，不等于禁用所有现值法

#### 来源 O：Damodaran 金融服务公司估值材料

- **来源**：Aswath Damodaran, NYU Stern, “Valuing Financial Service Firms.”
- **发布日期**：页面/讲义未统一标注；按访问日记录。
- **可核验 URL**：[金融服务公司特征](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/financialsvccompanies.htm)；[金融公司估值论文 PDF](https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm09.pdf)；[官方估值表格说明](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/eqspread.htm)。
- **直接支持**：对银行等金融服务企业，债务往往是经营原料而非普通融资；企业价值、资本支出、营运资本和 FCFF 难以像工业企业那样定义。权益方法、股息方法或基于超额收益/账面价值的方法通常更自然。
- **适合进入 Phase 1 的表述**：

  > 当债务是经营投入且再投资/FCFF 无法可靠区分时，估值路由器默认禁用普通企业 FCFF/WACC。可在满足各自输入门时考虑 DDM、FCFE、剩余收益或 excess-return/PB-ROE 框架。不得把这一规则简写成“金融公司不能做 DCF”。

## 5. 回测过拟合与 Monte Carlo 的使用边界

### 5.1 多次尝试会让偶然结果看起来像能力

#### 来源 P：White（2000）

- **来源**：Halbert White, “A Reality Check for Data Snooping,” *Econometrica*, 68(5), 1097–1126。
- **发布日期**：2000-09。
- **可核验 URL**：[DOI](https://doi.org/10.1111/1468-0262.00152)；[Wiley 出版社 PDF](https://onlinelibrary.wiley.com/doi/pdf/10.1111/1468-0262.00152)。
- **直接支持**：在同一数据上反复搜索模型/规则再报告最佳结果，会产生 data snooping bias；好结果可能只是大量尝试后的偶然赢家。论文提出相对基准的 Reality Check。
- **适合进入 Phase 1 的表述**：

  > Bench 和策略试验必须记录全部尝试、参数搜索空间、选择规则和基准，不得只保存最终赢家。测试集一旦用于选择提示词、模型或阈值，就不再是未见过的最终验证集。

#### 来源 Q：Bailey 等（2017）

- **来源**：David H. Bailey, Jonathan M. Borwein, Marcos López de Prado & Qiji Jim Zhu, “The Probability of Backtest Overfitting,” *Journal of Computational Finance*。
- **发布日期**：期刊版本 2017（DOI 记录为 2016）。
- **可核验 URL**：[DOI](https://doi.org/10.21314/JCF.2016.322)；[加州大学机构仓储](https://escholarship.org/uc/item/4w1110bb)；[作者 PDF](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)。
- **直接支持**：投资回测中的普通 holdout 可能因样本短、非平稳和多重尝试而不可靠；论文提出估计 backtest overfitting probability 的组合交叉验证方法。
- **工程含义**：20 个案例适合做接口回归和高危错误防线，但不可能单独证明泛化能力、收益能力或概率校准。应保留未参与开发的封存集，并记录模型、prompt、工具、数据快照和 harness 版本。

#### 来源 R：Harvey, Liu & Zhu（2016）

- **来源**：Campbell R. Harvey, Yan Liu & Heqing Zhu, “… and the Cross-Section of Expected Returns,” *Review of Financial Studies*, 29(1), 5–68。
- **发布日期**：2016。
- **可核验 URL**：[杜克大学作者 PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF)。
- **直接支持**：在研究大量因子时，传统单次检验阈值不能控制多重检验带来的虚假发现；搜索次数越多，越需要提高证据门槛。
- **限定**：论文针对因子研究，不能机械决定 EquityTrack 的提示词试验统计方法，但清楚支持“记录所有试验并为多重搜索提高门槛”。

### 5.2 Monte Carlo 的最大风险在输入模型，不在抽样次数

#### 来源 S：CFA Backtesting and Simulation（2026）

- **来源**：CFA Institute, “Backtesting and Simulation.”
- **发布日期/版本**：2026 refresher reading。
- **可核验 URL**：[CFA 官方页面](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation)。
- **直接支持**：回测、历史情景、Monte Carlo 和敏感性分析解决不同问题；测试需警惕前视、幸存者偏差、结构变化、厚尾和尾部依赖。简单多元正态可能遗漏偏度、厚尾和极端共振；更复杂分布又会增加参数估计误差。
- **工程含义**：不能把 Monte Carlo 的样本量或图表平滑度当作模型有效性。需要单独验证结构、分布、参数、依赖关系、状态变化和输出敏感性。

#### 来源 T：Damodaran 的 uncertainty / simulation 材料

- **来源**：Aswath Damodaran, NYU Stern，估值不确定性与 Monte Carlo 教学材料。
- **发布日期**：课程材料未统一标注；按访问日记录。
- **可核验 URL**：[Monte Carlo 章节 PDF](https://pages.stern.nyu.edu/~adamodar/pdfiles/val3ed/c29.pdf)；[不确定性课程页](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/cbuncert.html)；[含相关性模拟示例](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/distresspaper.htm)。
- **直接支持**：最困难的步骤是选择输入分布并估计参数；分布应尊重经济可行范围、经验和变量相关性。如果输入分布是随意的，精美的输出分布没有信息价值。
- **适合进入 Phase 1 的表述**：

  > Monte Carlo 默认关闭。只有在每个随机变量的经济边界、数据/行业依据、参数不确定性、变量依赖、状态适用性和结果解释均已记录时才可启用。未通过时优先使用情景、敏感性、压力、盈亏平衡和反向估值，并明确这些工具同样依赖假设。

- **关键限定**：“有历史数据”不是自动通过。若存在结构变化、样本选择、厚尾或参数漂移，历史拟合也可能误导；系统必须保留模型风险说明。

#### 来源 U：Federal Reserve SR 11-7（模型风险类比）

- **来源**：Board of Governors of the Federal Reserve System, *Supervisory Guidance on Model Risk Management*, SR 11-7。
- **发布日期**：2011-04-04。
- **可核验 URL**：[美联储官方 PDF](https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107a1.pdf)。
- **直接支持**：模型风险来自错误的假设/输入以及错误使用；验证应覆盖概念合理性、持续监控、结果分析、敏感性和压力测试，且模型风险无法被完全消除。
- **限定**：SR 11-7 是对受监管银行的监管指导，不是个人投资软件的强制法规。Phase 1 只能把它作为模型治理类比，不能写成 EquityTrack 的合规义务。

## 6. 个人投资者交易频率与行为风险

### 6.1 高频交易的经验结论应写成“风险信号”，而不是普遍因果定律

#### 来源 V：Barber & Odean（2000）

- **来源**：Brad M. Barber & Terrance Odean, “Trading Is Hazardous to Your Wealth: The Common Stock Investment Performance of Individual Investors,” *Journal of Finance*, 55(2), 773–806。
- **发布日期**：2000-04。
- **可核验 URL**：[DOI](https://doi.org/10.1111/0022-1082.00226)；[UC Berkeley 作者 PDF](https://faculty.haas.berkeley.edu/odean/papers/returns/individual_investor_performance_final.pdf)。
- **直接支持**：研究 1991—1996 年一家美国折扣券商的 66,465 个家庭账户。交易最活跃组年化净收益显著低于市场和平均家庭；成本后的频繁交易与显著业绩损失相关。
- **适合进入 Phase 1 的表述**：

  > 交易频率和计划外交易应作为纪律与成本复盘信号。系统应展示换手、费用、滑点/税费、计划外交易比例和机会成本，而不是通过更多提醒诱导更多交易。

- **限定**：这是特定历史时期、美国折扣券商客户样本的观察研究，不能推出“每次频繁交易必然亏损”或“所有低频策略都更好”。交易频率可能与策略类型、税制、成本和投资者特征共同变化。

#### 来源 W：SEC Investor Alert（2017）

- **来源**：U.S. Securities and Exchange Commission / Investor.gov, “Investor Alert: Excessive Trading at Investors’ Expense.”
- **发布日期**：2017-01-09。
- **可核验 URL**：[SEC Investor.gov 官方页面](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/investor-42)。
- **直接支持**：与投资目标和风险承受能力不一致的频繁进出、高费用及异常交易是需要警惕的信号；即使账户价值上涨，过度交易仍可能伤害投资者。
- **限定**：该警示主要针对券商账户滥用/过度交易保护，不是策略收益研究。它支持 UI 提醒和审计，不支持软件阻止所有高换手行为。

### 6.2 关于 LLM 投资长期优势退化的具体核验

#### 来源 X：Li 等（当前版本 2026，KDD 2026）

- **来源**：Weixian Waylon Li, Hyeonjun Kim, Mihai Cucuringu & Tiejun Ma, “Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?”
- **发布日期**：arXiv v1 2025-05-11；v6 2026-06-26；当前记录注明 KDD 2026 Datasets & Benchmarks Track (Oral)。
- **可核验 URL**：[arXiv 原文与版本记录](https://arxiv.org/abs/2505.07078)；[关联 ACM DOI](https://doi.org/10.1145/3770854.3785702)。
- **直接支持**：作者在二十年、100 多个标的的框架中报告，先前展示的 LLM timing 策略优势在更宽横截面和更长周期下显著退化，并指出幸存者偏差和 data snooping 风险。
- **适合进入 Phase 1 的限定表述**：

  > 一项覆盖二十年和 100 多个标的的 KDD 2026 研究报告，在其测试的 LLM 择时框架中，短样本优势在扩大股票范围和期限后显著退化。这支持把宽样本、长周期、基准和偏差检查设为评测要求；它不证明所有 LLM 辅助投资流程都无效。

- **关键修正**：原需求的“近期研究显示原有优势会显著退化”必须附具体研究和测试对象，不能泛化为整个 LLM 金融领域的定论。该研究评价的是择时策略，不是 EquityTrack 这种研究/计划/复盘辅助系统。

## 7. 金融 Agent/LLM 工作流：硬不变量与软 rubric

### 7.1 外部证据支持混合评测，不直接规定 G0—G5

#### 来源 Y：NIST AI RMF Core / Measure

- **来源**：NIST, AI Risk Management Framework, Core — Measure。
- **发布日期**：AI RMF 1.0 于 2023-01 发布；在线 Core 持续维护。
- **可核验 URL**：[NIST AI RMF Measure 官方页面](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)。
- **直接支持**：评估可以采用定量、定性或混合方法；测试集、指标和工具应文档化；测试条件应接近部署环境；测量需要有效性、可靠性、限制说明和领域专家输入；安全残余风险应在容忍范围内，并考虑 fail-safe 行为。
- **适合进入 Phase 1 的表述**：

  > Bench 同时使用确定性验证和领域质量评价。Schema、PIT、计算、权限、风险政策和状态转换属于不可被文本质量抵消的硬不变量；投资假设清晰度、反方质量、证伪性和下一步可用性由版本化 rubric 评价，并定期接受领域专家抽审。

- **限定**：NIST 没有规定 EquityTrack 的 G0—G5 层，也没有规定“G0—G3 任一失败即整案失败”。后者是合理但明确属于项目的 fail-closed 政策。

#### 来源 Z：NIST Generative AI Profile（2024）

- **来源**：Autio 等，*Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile*, NIST AI 600-1。
- **发布日期**：2024-07-26；NIST 页面 2026-04-08 更新。
- **可核验 URL**：[NIST 官方页面](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)；[DOI](https://doi.org/10.6028/NIST.AI.600-1)。
- **直接支持**：生成式 AI 的测量与风险治理应覆盖生命周期和实际使用情境，记录评测限制并持续监测，而不是把单次 benchmark 分数当成完整安全证明。
- **工程含义**：每次 Bench 运行必须冻结和记录：模型版本、prompt/Skill 版本、工具版本、证据快照、账户快照、风险政策、harness、随机性/重试设置和输出。只保存最终 Markdown 无法重放或解释结果。

#### 来源 AA：FinQA（2021）

- **来源**：Zhiyu Chen 等, “FinQA: A Dataset of Numerical Reasoning over Financial Data,” *EMNLP 2021*。
- **发布日期**：2021。
- **可核验 URL**：[ACL Anthology 论文页](https://aclanthology.org/2021.emnlp-main.300/)；[论文 PDF](https://aclanthology.org/2021.emnlp-main.300.pdf)。
- **直接支持**：金融数值问答不仅比较最终文字答案，还构造可执行推理程序，并以程序执行结果检查数值推理。它说明金融任务评测需要结构化、可执行的中间表示，不能只做文本相似度比较。
- **限定**：FinQA 是财报数值问答数据集，不覆盖组合风险、PIT、计划状态或 Agent 工具链。它支持 G2 数值复算思路，不验证整个 EquityTrack rubric。

#### 来源 AB：OpenAI contextual evals（2025）与 GDPval（2025）

- **来源**：OpenAI, “How evals drive the next chapter in AI for businesses”；“Measuring the performance of our models on real-world tasks (GDPval).”
- **发布日期**：2025-11-19；2025-09-25。
- **可核验 URL**：[contextual evals 官方文章](https://openai.com/index/evals-drive-next-chapter-of-ai/)；[GDPval 官方文章](https://openai.com/index/gdpval/)。
- **直接支持**：评测应由业务目标和真实工作流驱动，加入高代价边界案例，使用明确 rubric 和领域专家；LLM grader 应由专家持续审计并查看行为日志。GDPval 使用行业专家、详细 rubric 和盲评，并明确自动 grader 尚不足以替代专家。
- **适合进入 Phase 1 的表述**：

  > LLM grader 只能辅助软 rubric，不能裁决 PIT 泄漏、金额复算、风险越权或状态非法等硬失败；软评分须保留证据定位和人工抽审。真实失败案例应持续回流到 Bench。

- **限定**：这些是 OpenAI 自身的方法与实践，不是独立监管标准。它们支持评测设计方向，但不证明某一具体 grader 对中文投资研究可靠。

### 7.2 建议的硬门/软评价格式

| 类型 | 例子 | 执行者 | 失败语义 |
|---|---|---|---|
| 硬合同 | JSON Schema、必填字段、引用完整、状态转换 | 确定性代码 | `FAIL`，不可被软分抵消 |
| PIT/证据 | `available_at <= as_of`、重大事实有来源、unknown 不当零 | 确定性验证器 + 可审计规则 | `FAIL` 或数据不足 |
| 数值 | 会计恒等、估值桥、单位/币种/股本、概率和为 1 | 确定性复算 | `FAIL` |
| 权限/风险 | LLM 不改账户事实、不激活计划、不越过 risk cap | 领域服务 | `FAIL` |
| 重放 | 幂等、确定性字段一致、版本/输入可追溯 | harness | `FAIL` |
| 软用途质量 | thesis/antithesis、隐含预期、可观察 falsifier、下一步可用性 | 版本化 rubric + 领域专家抽审；LLM grader 仅辅助 | `SCORE + evidence` |

这里的“硬失败优先”是 EquityTrack 的安全政策。其正当性来自风险边界和可复算性，而不是因为 NIST、FinQA 或 OpenAI 已经规定了同名门禁。

### 7.3 20 个案例的正确定位

第一批 20 个冻结案例应称为：

> **Phase 1 seed regression and safety suite（种子回归与安全集）**

它可以验证合同、PIT、计算、风险门、幂等和已知对抗情景；不能独立证明：

- 投资研究在总体分布上的质量；
- 未来收益能力；
- 概率校准；
- 不同市场、行业和制度下的泛化；
- LLM grader 与人类专家的一致性。

后续至少需要：封存的未见测试集、真实失败回流集、变形/对抗用例、重复运行、模型与工具版本交叉测试，以及随决策到期逐步积累的校准样本。开发者看过并据此修改系统的案例必须从“封存验证集”降级为“回归集”。

## 8. 可直接进入 Phase 1 文档的修订文本

### 8.1 产品目标与风险边界

> EquityTrack 不承诺稳定收益，也不优化表面上的“最高确定性”。它优化的是决策过程：在概率、估值和市场状态可能估错时，计划仍满足组合风险硬约束，损失预算可追溯，投资假设可证伪，行动需要明确证据和人工确认。研究结论与风险政策是两条独立输入；前者不能覆盖后者。

### 8.2 决策复盘与概率学习

> 复盘先评价决策时点可获得的信息和过程，再评价事后收益和归因，以降低结果偏差。任何概率预测必须冻结事件定义、预测概率、判断时点、到期日和结果解析规则。概率学习报告样本数、Brier score、校准/可靠性、分辨率和基础率；样本不足时明确输出数据不足，而不是宣称已经校准。

### 8.3 估值顺序

> V2 默认先做反向估值：从市场价格反推一组经营与资本成本假设，再用企业驱动因素、基准率和证据判断这些假设是否合理。反向估值不产生唯一答案，必须展示被固定的变量、被求解的变量、可替代解释和敏感性。正向 DCF、相对估值或剩余收益只在各自适用性和数据门通过后启用。

### 8.4 仓位与 Kelly

> 风险上限由确定性服务根据冻结账户、压力损失、集中度、流动性、相关暴露和用户政策计算，并返回生效约束。输入缺失或单位不一致时 fail closed。Kelly 只可在概率、赔率、重复性和估计误差有审计依据时作为只读诊断；不得覆盖风险上限、创建订单或激活计划。

### 8.5 Monte Carlo 与回测

> Monte Carlo 默认关闭。启用前必须记录变量的经济边界、数据依据、参数不确定性、依赖关系、状态适用性以及解释方式；仅有历史拟合或 LLM 给出的均值和标准差不构成通过。任何回测或提示词/模型比较必须记录全部尝试、基准、成本、PIT 规则和选择过程，保留未用于开发的封存验证集。

### 8.6 Bench

> Bench 先执行不可被软评分抵消的确定性门：合同、PIT、数值、权限、风险、状态和重放；通过后才评价假设、反方、隐含预期、证伪性和行动可用性。LLM grader 只辅助软 rubric，并需领域专家持续抽审。第一批 20 个案例是种子回归与安全集，不是收益能力、概率校准或总体泛化的统计证明。

## 9. 无法直接核验或必须降级的主张

1. **“系统最终实现稳定收益”**：不能由软件或上述文献保证。应改成提升可观察的过程指标：证据完整性、风险预算遵守、计划外交易、复算通过率、校准统计和复盘覆盖率。
2. **“风控在概率背后”或“风控与概率在理论上完全独立”**：前者容易误导；后者也不是文献定理。可准确写成：V2 把风险约束实现为不受研究概率覆盖的独立硬门，以应对模型错误。
3. **`Wmax = min(...)` 的具体形式**：未找到权威来源证明它是最佳或标准仓位公式。它是保守、可测试的 V2 policy；尤其需要重定义 `Wcorrelation`。
4. **“少于三家 peer 不能形成估值结论”**：未找到 CFA 或 Damodaran 的统一数字门槛。若保留，必须注明是项目政策并版本化。
5. **“隐含预期优先是专业投资流程的共同唯一框架”**：无法支持。它是 Expectations Investing 的有依据方法，也是合适的 V2 默认，但不是唯一专业流程。
6. **“金融机构不能做 DCF”**：过强。普通企业 FCFF/WACC 常不适用；权益 DDM/FCFE、剩余收益和超额收益框架仍可能适用。
7. **“有历史或行业分布依据即可使用 Monte Carlo”**：不充分。还需要经济边界、相关/尾部依赖、结构状态、参数误差和敏感性；历史数据也可能不再代表未来。
8. **“个人投资者频繁交易通常一定亏损”**：原始研究支持特定大样本中高换手的显著净业绩损失，但不能外推为每个账户或每种策略的因果定律。
9. **“LLM 投资优势在长周期和宽样本下一般都会退化”**：目前可核验的是特定 KDD 2026 研究对特定 LLM 择时框架的结果。应点名来源并限制外推范围。
10. **“20 个 Bench 案例能够稳定证明投资质量”**：不支持。20 个案例是起始回归/安全集；概率校准尤其需要同一定义下随时间到期的足量预测样本。
11. **“G0—G3 任一失败则整案失败”**：不是外部标准，但作为 EquityTrack 的 fail-closed 产品政策合理，应在 `BENCHMARK_SPEC` 中明确并测试。
12. **`THESIS_ERROR / VALUATION_ERROR / ... / RANDOM_OUTCOME` 与 lesson 状态机**：没有被上述来源验证为完整、互斥或稳定的通用分类。它们应先作为版本化候选 taxonomy，允许一案多标签，并通过实际复盘检验覆盖率和一致性。
13. **DSH 的版本、API 稳定性和 benchmark 能力**：本研究任务没有核验 DSH 仓库；相关表述须由 Phase 2 的 DSH 代码/文档审计单独给出，不能引用本笔记作为依据。

## 10. 对 Phase 1 Bench 合同的具体建议

为了让以上金融原则可执行，而不是变成报告章节，建议每个案例补齐以下字段：

```yaml
case_id: string
case_version: string
as_of: datetime
decision_horizon: string

frozen_inputs:
  evidence_snapshot_digest: string
  portfolio_snapshot_digest: string
  risk_policy_version: string
  prices_and_fx_as_of: datetime

runtime:
  skill_version: string
  prompt_version: string
  model_id: string
  tool_versions: object
  harness_version: string
  randomness_and_retry_policy: object

hard_invariants:
  - invariant_id: string
    expected: pass | blocked | data_insufficient
    validator_version: string

soft_rubric:
  rubric_version: string
  criteria: []
  evidence_location_required: true
  expert_audit_required: true

forecast_contract:
  event_definition: string | null
  probability: number | null
  forecast_made_at: datetime | null
  resolution_at: datetime | null
  resolution_rule: string | null

forbidden_outputs: []
```

最低限度的 Bench 报表应把以下指标分组，不能加成一个总分：

- **硬安全**：Schema 失败数、PIT 泄漏数、复算失败数、风险越权数、非法状态转换数、非幂等写入数。
- **运行可靠性**：端到端成功率、数据不足正确降级率、重试次数、用户干预次数、增量监控避免全量重算比例。
- **软用途质量**：thesis/antithesis、隐含预期、可观察 falsifier、证据覆盖和下一步行动清晰度，均附证据定位。
- **长期学习**：到期预测样本数、Brier score、可靠性/校准、分辨率、按 horizon/base rate 的分层结果。
- **真实纪律**：计划外交易、风险预算偏离、费用/换手、复盘完成率；这些是产品过程指标，不等同于软件创造的超额收益。

## 11. 来源使用边界小结

- 经典心理学与金融代理实验支持“过程/结果分离”，不支持自动生成完整错误归因。
- 概率评分文献支持“严格适当评分 + 校准/分辨率分解”，不支持小样本下宣称个人概率已校准。
- CFA 支持组合适当性、约束和风险预算原则，不替 EquityTrack 选择具体仓位公式。
- Mauboussin/Rappaport 与 Damodaran 支持隐含预期和反向求解方法，不支持从市场价格得到唯一答案。
- CFA/Damodaran 支持方法路由和适用性门；固定 peer 数阈值仍是项目政策。
- White、Bailey、Harvey 支持记录搜索、多重检验与封存验证；20 个案例不足以做统计泛化结论。
- CFA/Damodaran 支持 Monte Carlo 输入和依赖关系治理；模拟不是精确性的证明。
- Barber/Odean 支持把高换手视为成本与纪律风险信号，但不支持无条件压制所有交易。
- NIST、FinQA 和真实任务 eval 实践共同支持“确定性硬门 + 专家软 rubric”；G0—G5 的具体命名、优先级和 fail-closed 规则仍应作为 EquityTrack 领域合同明确声明。
