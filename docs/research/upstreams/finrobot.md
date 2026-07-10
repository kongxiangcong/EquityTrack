# FinRobot 对照研究

上游：[`AI4Finance-Foundation/FinRobot`](https://github.com/AI4Finance-Foundation/FinRobot)
本地浅克隆：`.research/upstreams/FinRobot`
审计提交：`297a8d28d099be328c8a8eb658b4f782b93f3651`
审计范围：equity research pipeline、估值、敏感性、图表、HTML 和测试。结论只依据该提交的源代码与项目 README。

## 最值得借鉴的实现

### 1. 把分析和报告拆成可复用的制品流水线

FinRobot 明确把财务分析与报告渲染拆成两个命令：第一步获取/处理财务数据、预测和同业分析并写 CSV/JSON/TXT，第二步读取这些中间制品生成图表和 HTML。[README 的 pipeline](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/README.md#L66-L82) 比当前仓库依赖会话上下文和临时文件名的 Task 1/2/3 更确定。

本地应借鉴“中间制品可独立检查”的思想，但应收敛成一个版本化 `ResearchRun`，避免很多松散 CSV/TXT 再次形成隐式接口。

### 2. 可选能力失败时局部降级

同业数据为空或请求失败时，FinRobot 记录 warning 后继续，不让整个基础分析停止；敏感性分析也被设计成可选步骤，异常时继续生成剩余产物。[同业局部回退](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/generate_financial_analysis.py#L195-L225) 与[敏感性局部回退](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/generate_financial_analysis.py#L301-L342) 正好对应本项目最需要的 capability-level degradation。

应借鉴的不是吞掉异常，而是“一个能力失败只影响该能力”。本地实现仍须保存结构化诊断和来源缺口，不能只打印 warning。

### 3. 报告层有独立 module 与统一 `report_data`

报告入口先组装 `report_data`，再调用专业 HTML renderer；图表生成也集中在独立 module 中。[报告数据组装](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/create_equity_report.py#L504-L542)、[图表处理](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/create_equity_report.py#L543-L568) 和[统一 HTML 输出](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/create_equity_report.py#L999-L1009) 说明报告无需为每家公司重写脚本。

专业模板把财务、估值、敏感性、催化剂、风险和多种图表组织为完整页面，还提供数据来源与生成时间。[专业模板数据映射](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/html_template_professional.py#L1006-L1059) 可作为本地报告信息架构的参考。

### 4. 报告 section 本身携带来源和 AI 标记

`ReportSection` 同时记录内容、图表、数据来源与是否由 AI 生成；管理器能生成来源章节和 AI disclosure。[section 模型](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/report_structure.py#L15-L43)、[来源汇总](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/report_structure.py#L234-L253) 与 [AI disclosure](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/report_structure.py#L255-L284) 值得吸收。

本地应进一步做到 claim/exhibit 级别的 `evidence_ids`，而不只在 section 级记录来源名称。

### 5. 图表库覆盖报告需要的主要视觉语言

上游提供收入/EBITDA、EPS×PE、同业 EV/EBITDA、利润率、股价、雷达、敏感性热图、技术指标、估值瀑布、季度比较和现金流等多类图表。图表函数统一样式并返回可嵌入结果。[图表实现](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/chart_generator.py#L21-L108) 可用于校准本地报告的视觉完整性。

## 不能照搬的部分

### 1. 估值引擎包含不可接受的无来源默认值

当历史倍数不存在时，EV/EBITDA 直接使用 `12.0x` 和 `3.0x` 标准差；净债务被假设为企业价值的 10%。[默认倍数与净债务](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/valuation_engine.py#L84-L105) 这会产生看似精确、实际无证据的每股价值。

DCF 默认使用 10%/5% 两阶段增长、2.5% 永续增长、10% WACC；如果没有 FCF，则假定 `FCF = EBITDA × 60%`，股权桥仍把净债务设为 EV 的 10%。[DCF 默认假设](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/valuation_engine.py#L216-L256) 这些做法与本项目的来源边界、行业路由和财务一致性要求冲突。

本地必须坚持：缺少方法专属输入时禁用该方法或运行明确标注的 exploratory scenario；不能让任意默认值进入正式估值。

### 2. 多方法综合使用主观 confidence 加权点价格

上游按固定 confidence 权重综合多个 target price，并输出 upside/downside。[综合估值实现](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/valuation_engine.py#L312-L366) 这种“不同方法点估值加权”掩盖了方法之间的假设差异，固定权重也没有统计或经济依据。

本地应展示方法区间、关键 driver、冲突原因和哪个证据会改变视角；默认不生成个人化建议或 house-style target。

### 3. 敏感性不是统计置信区间

上游的 `calculate_confidence_interval` 固定假定 15% 标准差，再套用正态分布 z-score；没有历史残差、模型误差或分布证据。这只是启发式范围，却被命名为 95% confidence interval。[实现位置](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/src/modules/sensitivity_analyzer.py#L194-L238)

本地必须区分 deterministic sensitivity、scenario range 与 statistical confidence interval；没有统计样本时不得使用“95% 置信区间”标签。

### 4. 报告入口过大，异常处理大量吞错

虽然 module 划分比本地当前状态更清楚，`create_equity_report.py` 仍是近千行 orchestrator，并在很多局部使用宽泛 `except` 后继续。这样容易生成“看起来完整但某些数据已静默缺失”的报告。

本地应由 capability 状态控制 section 是否出现；renderer 不负责猜测数据是否可用，也不自行创建金融假设。

### 5. 测试偏 smoke，不足以保护金融行为

测试主要验证 module 可导入、函数能运行和返回若干方法；估值测试甚至断言 football field 至少有三种方法，却没有对默认假设或财务桥做独立 worked-example 校验。[测试入口](https://github.com/AI4Finance-Foundation/FinRobot/blob/297a8d28d099be328c8a8eb658b4f782b93f3651/finrobot_equity/core/tests/test_modules.py#L210-L269)

本地测试应围绕公开 seam 验证：缺 D&A 只禁用 DCF、缺 peers 只禁用 comps、估算不升级为官方事实、HTML 与 JSON 使用同一 `ResearchRun`、禁止性语言不泄漏。

## 对本地重构的直接影响

| FinRobot 观察 | 本地采用方式 |
|---|---|
| 分析与报告用中间制品解耦 | 采用版本化 `ResearchRun`，不采用松散 CSV/TXT 接口 |
| 同业与敏感性可局部失败 | 建立 capability matrix 和 `completed_with_limits` |
| 独立 chart/report modules | 建立通用 HTML renderer 与 exhibit registry |
| section 携带来源/AI 标记 | 提升为 claim/exhibit 的 `evidence_ids` |
| 11+ 图表类型 | 选择与当前数据匹配的图表，不为凑数量生成空图 |
| 默认倍数、默认 WACC、固定净债务比例 | 明确拒绝；所有正式方法输入必须有来源或可审计推导 |
| 固定 confidence 加权 target | 改为方法区间、假设分歧和 capability diagnostics |

## 总体判断

FinRobot 最有价值的是产品化流水线和报告呈现，不是估值严谨性。它证明“数据处理、Agent 叙事、图表、HTML/PDF”可以被拆成可重用 module，并且可选能力不必阻断全部产出；同时它也展示了为什么本项目不能为了顺畅而使用无来源金融默认值。重构应吸收前者，并用本项目已有的来源与方法门禁修正后者。
