# Equity Research Skill Patch Plan

审计日期：2026-07-02  
范围：`E:/workspace/tradingSystem/skills/`  
约束：本文件只给修改方案，不直接修改任何技能源文件。

## 总体修复目标

把当前技能从“完整研报自动生成器”调整为“可审计、可降级、行业适配的投研辅助技能”。核心方向：

- 先确认数据源和行业，再选择估值方法。
- 官方披露优先，所有关键数字进入 source manifest。
- DCF 从默认动作改为受门禁控制的方法之一。
- 模型输出必须通过 workbook validator，而不是只靠报告文本 validator。
- 投资建议语言降级为教育性研究和估值视角。
- 创新药、金融、周期、地产、资源品、SaaS、半导体、互联网等建立行业化框架。

## 修复优先级

### Phase 0：安全门禁

1. 禁止默认 BUY/HOLD/SELL 和目标价式结论。
2. DCF 增加适用性门禁。
3. 关键数据不可验证时停止估值结论。
4. 新增 source manifest 作为所有模型和报告的输入。

### Phase 1：模型与数据可复现

1. 实现 XLSX `model_validator.py`。
2. 实现 source manifest validator。
3. 修改 financial model spec，把 source annotation 变为 mandatory。
4. 修复数据源优先级，把官方公告放到第一层。

### Phase 2：行业估值路由

1. 新增 industry valuation matrix。
2. 新增 financials、biopharma rNPV、cyclical/resources、real estate、SaaS/software、semiconductor 等方法模块。
3. 输出 schema 增加 method router 结果和禁用方法说明。

### Phase 3：Codex 工程化

1. 移除写死环境路径。
2. 增加内部链接检查。
3. 增加报告、模型、source manifest 联动验证。
4. 加入 AGENTS.md 规则。

## 按文件修改方案

### `skills/SKILL.md`

建议修改点：

- 在 frontmatter description 中删除或弱化“能不能买”“值得投吗”作为直接研报触发。改为触发“教育性研究流程/估值框架”，不直接触发投资建议。
- 在 `## Core Principles` 后新增 `## Financial Safety and Output Boundary`：
  - 不提供个性化投资建议。
  - 默认不输出 BUY/HOLD/SELL。
  - 默认输出 `valuation_view`、`risk_reward_summary`、`data_quality_grade`。
  - 用户明确要求机构研报风格时才允许评级语言，并必须附“非投资建议”边界。
- 在 equity report 路由处加入：
  - 先运行 data availability check。
  - 再运行 industry and lifecycle classification。
  - 再运行 valuation method router。
- 将 L2 定义从“完整三表 + DCF + comps + sensitivity”改为：
  - “完整三表或行业适配模型 + 至少两种适用估值方法 + 敏感性/情景 + 方法禁用说明”。

应写入 `SKILL.md` 的内容：

- 触发和安全边界。
- 任务路由。
- 何时降级。
- 哪些 reference 必须按需加载。
- 最终产物类型与禁止事项。

不应写入 `SKILL.md` 的内容：

- DCF 公式细节。
- 行业估值大表。
- 数据源 API 字段。
- Excel 单元格规格。

### `skills/SKILL-equity-task1.md`

建议修改点：

- 在 `Phase 1: Data Collection` 前新增 `Phase 0: Source and Method Feasibility Gate`：
  - 确认市场：A/HK/US/dual listed。
  - 确认官方财报来源。
  - 确认交易货币、报表货币、单位。
  - 确认行业和生命周期。
  - 生成 `source_manifest.md/json` 草稿。
  - 运行 valuation method router。
- 修复 web search cap 与 `output/report-layout.md` 的冲突：
  - 官方 filings/API 不计入 web search cap。
  - 普通 web search 用于二级来源、行业背景、新闻。
- 在 `Phase 2.5: Valuation Framework` 中：
  - 不再强制 L2 做 DCF。
  - 要求列出 `selected_methods` 和 `disabled_methods`。
  - DCF 被禁用时必须写 `disabled_reason`。
- 在输出章节中修复“Task 1 不含估值计算”与 `§XII Preliminary Valuation Inputs` 的冲突：
  - Task 1 只收集估值输入和方法路由，不计算目标价。

### `skills/SKILL-task2-model.md`

建议修改点：

- 修复 `Environment Skills Integration`：
  - 删除 `/app/.agents/skills/xlsx/reference/` 硬路径。
  - 改为“发现当前 Codex 可用 spreadsheet/xlsx 工具；不可用时使用 Python openpyxl fallback”。
  - 修复未闭合 markdown 标记。
- 修改 build order：
  - 先加载 source manifest。
  - 再加载 method router result。
  - 只有 DCF allowed 才创建 DCF tab；否则创建 `Valuation Method Rationale` tab。
- 修改 `Valuation Analysis Document`：
  - 默认不输出 BUY/HOLD/SELL。
  - 输出 `method_selected`、`data_quality`、`valuation_range`、`key_sensitivities`。
  - 如果用户明确要求 rating，单独开启 rating section。
- 在 `Model Validation Required` 中增加：
  - 必须运行 `scripts/model_validator.py`。
  - 必须运行 `scripts/source_manifest_validator.py`。
  - validator 不通过时不得进入 Task 3 报告生成。
- 修复 comparable extraction 章节号：从 `§V` 改为模板实际章节 `§XII` 或改为标题定位。

### `skills/SKILL-task3-report.md`

建议修改点：

- 报告生成前要求：
  - Task 1 source manifest passed。
  - Task 2 workbook validator passed。
  - method router result exists。
- 报告中所有图表必须引用 source_id 或 workbook range。
- 报告不应补写模型中没有的数据。
- 如果模型被降级为数据不足，报告必须输出“数据不足研究备忘录”，而不是完整目标价研报。

### `skills/valuation/dcf-and-sensitivity.md`

建议修改点：

- 文件顶部新增 `DCF Applicability Gate`：
  - allowed / caution / disabled 三态。
  - required fields。
  - disabled scenarios。
- 增加公式刚性要求：
  - `FCFF = EBIT * (1 - tax_rate) + D&A - CapEx - ΔNWC`
  - `EV = Σ FCFF_t / (1 + WACC)^t + TV / (1 + WACC)^n`
  - `TV = FCFF_(n+1) / (WACC - g)`
  - `Equity Value = EV - gross_debt - lease_debt - preferred - minority_interest - pension_deficit + cash + non_operating_assets + associates_JV_value`
- 增加输入来源要求：
  - 每个 WACC 组件必须有 source_id。
  - beta 必须说明 raw beta、unlevered beta、relevered beta 或禁用原因。
  - ERP/country risk/size premium 不得重复计算。
- 增加校验：
  - `WACC > g`
  - terminal value percent of EV。
  - terminal implied multiple vs mature peers。
  - terminal ROIC and reinvestment consistency。
  - share count dilution and SBC。
  - currency consistency。

### `skills/valuation/comparable.md`

建议修改点：

- 将粗粒度 `Metric Selection by Company Type` 拆成行业矩阵，或引用新增 `valuation/industry-valuation-matrix.md`。
- peer 选择标准增加：
  - 会计准则。
  - 市场/上市地。
  - 生命周期。
  - 盈利状态。
  - 业务分部相似度。
  - 杠杆差异。
- peer 数量标准统一：
  - Task 2 当前要求 5-10，comparable.md 当前要求 3-5，需统一为“目标 5-10，最低 3；低于 3 必须降级”。
- 增加负利润处理：
  - 负 EPS 不得使用 PE。
  - 负 EBITDA 不得使用 EV/EBITDA。
  - 高增长 SaaS 或 pre-profit 公司必须配合 unit economics。

### 新增 `skills/valuation/valuation-method-router.md`

建议内容：

- 输入：
  - market
  - industry
  - business model
  - lifecycle
  - profitability
  - cash flow stability
  - leverage/debt type
  - available official filings
  - data quality grade
- 输出：
  - selected_methods
  - caution_methods
  - disabled_methods
  - required_data
  - missing_data
  - reason
- 路由规则：
  - 金融：P/B x ROE/COE、DDM、residual income；禁用 FCFF/WACC DCF。
  - 创新药：rNPV/SOTP；禁用普通 DCF/PE。
  - 周期/资源：mid-cycle / NAV；DCF 只能使用周期均值。
  - 地产：NAV/RNAV/项目现金流。
  - SaaS：EV/Sales、Rule of 40、成熟期 FCF DCF。
  - 消费成熟：PE/PEG/DCF/EV EBITDA。

### 新增 `skills/valuation/industry-valuation-matrix.md`

建议内容：

- 行业 x 推荐方法 x 禁用/谨慎方法 x required data。
- 覆盖：
  - 消费
  - 周期
  - 金融
  - 医药成熟
  - 创新药
  - 半导体
  - 软件/SaaS
  - 互联网
  - 地产
  - 资源品
- 每个行业给出：
  - preferred primary method
  - secondary cross-check
  - sensitivity variables
  - common traps
  - minimum data gate

### 新增 `skills/valuation/biopharma-rnpv.md`

建议内容：

- rNPV 适用场景。
- 必需输入：
  - asset、indication、phase、geography、rights ownership。
  - target population、penetration、net price、peak sales、ramp curve。
  - launch year、LOE、patent cliff。
  - COGS、SG&A、continuing R&D、trial costs。
  - phase-specific PoS、regulatory PoS、commercial PoS。
  - upfront、milestone、royalty、profit share。
  - cash runway、net debt、corporate overhead。
- 公式：
  - `asset_rNPV = Σ probability_adjusted_FCF_t / (1 + r)^t`
  - `equity_value = Σ asset_rNPV + marketed_products_value + cash - debt - corporate_overhead_value`
- 校验：
  - PoS 必须有来源。
  - 阶段、适应症、技术路径不可混用同一概率。
  - license-out 权益比例不可与 100% 销售额重复计算。
  - 研发费用不能既作为 pipeline cost 又在 corporate overhead 中重复扣除。

### `skills/analysis/revenue-model.md`

建议修改点：

- 将“至少 3 个收入分部”的硬规则改为行业适配：
  - 消费/制造：分品类或量价。
  - SaaS：ARR、NRR、客户数、ARPA、churn。
  - 金融：资产规模、NIM、手续费、拨备、资本。
  - 地产：项目、货值、去化、结转。
  - 资源：产量、价格、品位、成本。
  - 创新药：按 asset/indication/region，不按传统收入分部。
- 若公司披露不足，允许使用管理层披露分部；不足时降级，不强造分部。

### `skills/analysis/projection-assumptions.md`

建议修改点：

- 增加行业假设包：
  - Financial assumptions pack。
  - Biopharma pipeline assumptions pack。
  - SaaS unit economics pack。
  - Cyclical normalization pack。
  - Real estate project cash flow pack。
- 增加特殊会计处理：
  - R&D capitalization。
  - lease liabilities。
  - SBC dilution。
  - minority interests。
  - associates/JVs。
  - non-recurring items。
- 每个前瞻数字必须绑定：
  - source_id 或 assumption_id。
  - base/bull/bear value。
  - rationale。
  - sensitivity tag。

### `skills/analysis/scenario-deep-dive.md`

建议修改点：

- Bull/Base/Bear 概率不再固定。
- 新增 `probability_basis`：
  - historical frequency
  - market implied
  - consensus distribution
  - clinical PoS
  - commodity curve
  - user-defined
  - not quantified
- 没有 probability basis 时，不计算 probability-weighted target。
- 增加 reverse valuation：
  - 当前股价隐含 revenue CAGR。
  - 当前股价隐含 margin。
  - 当前股价隐含 terminal growth。
  - 创新药当前股价隐含 PoS 或 peak sales。

### `skills/analysis/risk-framework.md`

建议修改点：

- 新增风险类别：
  - data quality risk
  - model risk
  - valuation method risk
  - source conflict risk
  - investment advice misuse risk
- 对 DCF/rNPV/comps 分别列出模型风险。
- 每个 top risk 要写“会影响哪个 valuation driver”。

### `skills/references/data-sources.md`

建议修改点：

- 重写优先级：
  - A 股财报/公告：CNINFO、SSE/SZSE、公司 IR PDF；iFind 作为二级结构化校验。
  - 港股：HKEXnews、公司 IR；iFind/Yahoo 作交叉验证。
  - 美股：SEC EDGAR filings、companyfacts/companyconcept XBRL、公司 IR。
  - 行情：交易所、终端、Yahoo 可用，但必须保留查询时间。
- 新增 critical data gate：
  - 缺少最近一期财报官方来源：不得建三表。
  - 缺少股本/净债务/少数股东权益：不得输出每股价值。
  - 缺少管线权益/阶段/PoS：不得输出 rNPV。
  - 缺少 peer 市值/口径一致性：不得输出 comps 结论。
- 增加 source conflict resolution：
  - 官方披露优先于商业终端。
  - 同源不同日期以最新公告为准。
  - restatement 需重跑历史数据。

### `skills/references/data-sources-detail.md`

建议修改点：

- 将 iFind/Yahoo/Tianyancha API 标记为 optional connectors。
- 增加官方源抓取说明：
  - SEC EDGAR submissions/companyfacts/companyconcept。
  - CNINFO/SSE/SZSE 公告 PDF。
  - HKEXnews 公告搜索。
  - 公司 IR annual/interim report。
- 增加 raw artifact 保存规范：
  - PDF/HTML/XBRL 保存路径。
  - SHA256。
  - extracted table CSV。
  - extraction method。
  - extraction confidence。

### 新增 `skills/references/source-manifest.md`

建议 schema：

```yaml
source_manifest_version: 1
company:
  name:
  ticker:
  market:
  reporting_currency:
sources:
  - source_id:
    tier: official | terminal | secondary | news | estimate
    publisher:
    title:
    url_or_api:
    retrieved_at:
    query_params:
    filing_period:
    report_date:
    currency:
    unit:
    raw_file_path:
    raw_file_sha256:
    page_or_table:
    extracted_fields:
      - field_name:
        period:
        value:
        unit:
        currency:
        extraction_method:
        confidence:
    cross_checks:
      - source_id:
        status: match | mismatch | not_checked
        notes:
```

### `skills/references/financial-model-spec.md`

建议修改点：

- Raw Data：
  - source annotation 从 optional 改为 mandatory。
  - 每个历史数据点必须引用 source_id。
- Operating Drivers：
  - 每个假设必须有 assumption_id、source_id 或 explicit model assumption。
- Revenue Model：
  - 取消所有公司至少 3 个分部的硬规则，改为行业适配。
- DCF Tab：
  - 只有 method router 允许 DCF 时才 required。
  - 增加 lease debt、pension deficit、SBC dilution、associates/JV、non-operating assets。
- Model Quality Checks：
  - 删除 universal `FCF positive base case` 硬门禁，改为“如果 base case FCF 长期为负，必须解释融资、runway 或禁用 DCF”。
  - 增加 `WACC > g` hard fail。
  - 增加 source_id coverage hard fail。
  - 增加 formula lineage hard fail。

### `skills/references/output-schema.md`

建议修改点：

- Financial data schema 增加：
  - source_id
  - currency
  - unit
  - reporting_period
  - accounting_standard
  - restated flag
- Valuation schema 增加：
  - industry_classification
  - lifecycle
  - method_router_result
  - selected_methods
  - disabled_methods
  - dcf_applicability
  - rnpv_assets
  - model_validation_status
  - source_manifest_status
- Final conclusion schema：
  - 默认 `valuation_view`，不是 `rating`。
  - `rating` 字段只在 user_requested_rating=true 时允许。

### `skills/references/research-document-template.md`

建议修改点：

- Data Sources table 改为 source manifest 摘要，不再只写 Source/Retrieval/Reliability。
- Valuation section 先展示 method router：
  - selected
  - caution
  - disabled
  - missing data
- DCF section：
  - 如果 disabled，展示 disabled reason。
  - 如果 allowed，展示公式、输入、校验和敏感性。
- 创新药模板增加 pipeline rNPV table。
- Rating/target price section 默认隐藏或改成 valuation view。

### `skills/output/report-layout.md`

建议修改点：

- 修复 web search cap 冲突。
- Valuation section 不再强制 DCF。
- 增加 `Data Quality and Reproducibility` section：
  - source manifest coverage。
  - official source coverage。
  - unresolved conflicts。
  - model validator status。
- 图表脚注必须引用 source_id。
- 若数据/模型 validator fail，报告只能生成 audit memo，不得生成完整研报。

### `skills/modules/valuation.md`

建议修改点：

- 修复 `Related File: modules/comparable.md` 为 `valuation/comparable.md`。
- 模块内容应引用 `valuation-method-router.md`。
- 不再把 valuation table 作为所有公司通用模板。

### `skills/modules/stock-chart.md`

建议修改点：

- 保留当前无 mock 数据、数据验证和跳过逻辑。
- 补充 source manifest 输出：
  - price_source_id
  - benchmark_source_id
  - adjustment_method
  - retrieval timestamp

### `skills/modules/equity-report-charts.md`

建议修改点：

- 图表数据来源必须来自 workbook range 或 source manifest。
- 图表生成脚本不得自行补数据。
- 缺少来源时跳过图表并记录 missing chart reason。

### `skills/scripts/report_validator.py`

建议修改点：

- 保留 HTML/结构/图表/引用检查。
- 新增读取 model validation result 和 source manifest validation result。
- 如果模型 validator 未通过，报告 validator hard fail。
- DCF 文本检查改为：
  - 若 DCF disabled，必须存在 disabled reason。
  - 若 DCF allowed，必须出现公式、输入表、校验表、敏感性。
- 增加 anti-investment-advice 检查：
  - 默认输出不得包含 BUY/HOLD/SELL。
  - 若出现 rating，必须有 `user_requested_rating` 和免责声明。

### 新增 `skills/scripts/source_manifest_validator.py`

建议检查：

- manifest schema valid。
- 每个关键财务字段有 source_id。
- source_id 引用的 raw file 存在。
- raw file hash match。
- 官方来源覆盖率：
  - financial statements 100% official required。
  - market price can be terminal/Yahoo but requires timestamp。
- 币种/单位/期间一致。
- source conflicts 是否 unresolved。
- missing critical data 是否触发降级。

### 新增 `skills/scripts/model_validator.py`

建议检查：

- Workbook required sheets。
- Sheet headers and named ranges。
- Raw Data source_id coverage。
- Historical financials tie to Raw Data。
- BS balances。
- CF ties to cash movement。
- Revenue model ties to Operating Drivers。
- Forecast cells not hardcoded。
- DCF formula lineage。
- WACC components and formula。
- Terminal value formula and `WACC > g`。
- Equity bridge completeness。
- Sensitivity center equals base case。
- rNPV assets probability and economics checks。
- Disabled method not accidentally used.

### 新增 `skills/scripts/link_validator.py`

建议检查：

- skill 内部相对路径是否存在。
- SKILL 文件引用的章节标题是否存在。
- broken references，例如 `modules/comparable.md`。

### `skills/scripts/embed_charts.py`

建议修改点：

- 删除默认 `source_label = "Model calculation; public filings"`。
- `source_label` 必填。
- 允许传入 source_id list。
- 缺少 source_id 时 fail 或 skip，不生成带假来源的图表。

### `skills/scripts/chart_generator.py`

建议修改点：

- JSON 输入增加 source_id。
- 输出 SVG metadata 写入 source_id、retrieved_at、model_range。
- validator 检查 chart 数据与 workbook/source manifest 是否一致。

## 哪些内容应放进 `SKILL.md`

- 技能触发边界。
- 金融安全与非投资建议规则。
- 高层工作流：
  - source feasibility gate
  - industry classification
  - valuation method router
  - task1 research
  - task2 model
  - validators
  - task3 report
- 失败降级策略：
  - data insufficient memo
  - no valuation conclusion
  - no rating
- 最终产物类型和必须通过的 validator。

## 哪些内容应拆到 `references/`

- source manifest schema。
- 数据源优先级和官方源抓取说明。
- financial model spec。
- output schema。
- DCF validation spec。
- accounting adjustments：
  - R&D capitalization
  - leases
  - SBC dilution
  - minority interest
  - associates/JVs
  - non-recurring items
- citation and reproducibility rules。

## 哪些内容应拆到 `valuation/`

- valuation method router。
- industry valuation matrix。
- DCF and sensitivity。
- comparable company selection。
- financial institutions valuation。
- biopharma rNPV。
- cyclical/resources mid-cycle valuation。
- real estate NAV/RNAV。
- SaaS/software valuation。
- semiconductor valuation。
- internet platform SOTP。

## 哪些内容应写成 `scripts/`

- `source_manifest_validator.py`
- `model_validator.py`
- `link_validator.py`
- `report_validator.py` enhancement
- optional official data fetch helpers：
  - `sec_edgar_fetcher.py`
  - `cninfo_pdf_fetcher.py`
  - `hkexnews_fetcher.py`
  - These should be optional helpers and must respect network/tool availability.
- chart/source consistency checker。

## 哪些规则应写入 `AGENTS.md`

建议在仓库根目录或 `skills/AGENTS.md` 增加以下规则：

- 金融输出边界：
  - 不提供个性化投资建议。
  - 默认不输出 BUY/HOLD/SELL。
  - 默认不说“可以买/不能买”。
  - 输出应表述为“研究视角”“估值区间”“关键假设”“风险”。
- 数据规则：
  - 禁止伪造财务数据、市场数据、共识数据和引用。
  - 关键财报数据没有官方来源时，不得输出估值结论。
  - 每个关键数字必须追溯到 source manifest。
- 估值规则：
  - 不得默认 DCF。
  - DCF 必须通过 applicability gate。
  - 金融企业禁用普通 FCFF/WACC DCF。
  - 创新药公司优先 rNPV。
  - 周期/资源公司必须做 mid-cycle 或 NAV。
- 模型规则：
  - 没有通过 model validator，不得进入最终报告。
  - 不得用报告文本 validator 替代模型 validator。
- 降级规则：
  - 缺关键数据时输出 data insufficient memo。
  - 工具/API 不可用时记录缺口，不得编造。
- 用户交互：
  - 当用户要求买卖建议时，改为解释研究框架和风险，不给个性化建议。

## 需要新增的测试或 validator

### Source manifest tests

- 有效 manifest 通过。
- 缺 source_id 失败。
- raw file hash 不匹配失败。
- official financial source 缺失失败。
- 币种/单位冲突失败。
- 有 unresolved source conflict 失败。

### Model validator tests

- 三表平衡通过。
- BS 不平失败。
- 历史数字不等于 Raw Data 失败。
- 预测单元格硬编码失败。
- DCF `WACC <= g` 失败。
- 终值占 EV 超过阈值 warning/hard fail 根据规则触发。
- 金融企业出现 FCFF/WACC DCF 失败。
- 创新药没有 rNPV 却输出目标价失败。
- sensitivity center 不等于 base case 失败。

### Report validator tests

- DCF disabled 时缺 disabled reason 失败。
- DCF allowed 时缺公式/输入/校验/敏感性失败。
- 默认报告出现 BUY/HOLD/SELL 失败。
- 图表缺 source_id 失败。
- source manifest validator fail 时报告 fail。
- model validator fail 时报告 fail。

### Link validator tests

- `modules/comparable.md` 这类 broken path 被发现。
- SKILL 文件中引用的 reference 文件不存在时失败。
- 章节标题引用不存在时 warning。

### rNPV tests

- pipeline probability 不在 0-100% 失败。
- phase 缺失失败。
- license-out royalty 与 100% revenue 重复计算失败。
- R&D cost 双重扣除 warning。
- 缺 cash runway 时 pre-revenue biotech 估值失败。

## 验收标准

修复后技能应满足：

- 不依赖不可见的 iFind/Yahoo 工具作为唯一来源。
- A/HK/US 财报数据优先官方披露。
- 每个关键数字可追溯、可复核、可复现。
- DCF 只有在适用时运行；不适用时明确禁用原因。
- 金融、创新药、周期、地产、资源品、软件、互联网、半导体有独立估值路由。
- Excel 模型有公式级 validator。
- 报告 validator 检查模型和来源验证结果。
- 默认输出不是投资建议。
- 缺关键数据时自动降级，而不是补写或编造。
