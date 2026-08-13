# 股票研究任务

1. 从自然语言解析证券代码、账户上下文、截止日期和研究目的。未指定截止日期时使用请求时点，不使用未来信息。
2. 先冻结结构化市场数据和可用官方披露。Tushare-compatible 网关是非官方结构化聚合证据；A 股关键财务事实优先使用 CNINFO、交易所公告和公司 IR。
3. 只走正式 `ResearchWorkflow`。先由冻结快照编译 `ResearchAnalysisPlan@1`，绑定可用数据能力、分析依赖、输出合同和 required/supporting 节点；调用方不得构造节点、公式或生成代码。细节见 [研究分析计划与能力绑定](../references/research-analysis-plan.md)。
4. 每个模型输入必须是官方观察、结构化观察、确定性派生、有界估计或缺失；未知不是零。类型化模型字段只从 `research_model_input` 进入，并同时绑定主体、路径、语义、期间、单位、币种和冻结成员。
5. 建立可证伪 Forecast 和 stress/base/improvement 三种条件情景。研究复核应为每个 material assumption 记录依据、反证、falsifier、范围和什么会改变判断；当前 runtime 可保存 rationale、bounds 和 invalidation condition，但完整 typed dossier 仍是迁移验收，不能声称其完整性已 fail-closed 强制。
6. 先运行估值方法路由，再判断 DCF、相对估值、行业方法、估值 Monte Carlo 和市场路径是否适用。当前 DCF 方法权限执行既有来源/PIT/官方事实、类型化输入、适用性、FCFF、方法数学、`WACC > g` 和 equity bridge 门；完整 assumption dossier、完整 WACC x g 参数面和跨 DecisionView release receipt 作为研究复核与迁移验收，尚不是 runtime 正式发布门。模拟门不通过时保留确定性情景和原因，不用任意分布填空。
7. 检查持久化 manifest 后，通过唯一研究发布任务生成可打开的 JSON、HTML、PDF、价格图表和 workbook 槽。workbook 只是 canonical DecisionView 投影；交付前用 Python `Decimal` 复算工作簿内部 equity bridge 和 per-share。该校验不是完整 DCF 重算，也不独立复核 ledger/DecisionView 来源；workbook 不可用只限制该投影。
8. 默认回答只给：研究 headline、关键判断、估值适用性、数据质量、关键不确定性、什么会改变观点，以及可以打开的真实产物。来源、模型、参数、seed 和内部身份按需展开。
9. 缺少官方关键事实、方法输入或治理门时，受影响估值使用 `data_insufficient_memo`，不得给出正式目标价、评级、概率加权目标或个性化买卖建议。
