# 使用最少的规范决策记录

研究、估值、风险、计划和复盘分别以 `InvestmentCase`、`ValuationAssessment`、`RiskLimitResult`、`DecisionCard`、不可变 `TradePlan` 和 `DecisionReview` 表达；账户事实仍只属于 `AccountSnapshot`，`PortfolioState` 只是临时派生值。旧的研究运行与完整报告、PortfolioSnapshot、TradePlanVersion、计划图与规则 AST、周期复盘和通用工作流记录不进入新领域模型，应用操作使用领域动词而不使用阶段名或 `-case` 任务后缀。
