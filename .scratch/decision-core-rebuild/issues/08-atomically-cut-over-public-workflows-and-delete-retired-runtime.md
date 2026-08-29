# 08: 原子切换公开工作流并删除旧运行时

**What to build:** 在一个切换单元中让唯一公开 Skill、CLI、Application Interface、SQLite persistence 和只读投影全部使用决策核心，并删除其余退休 runtime、schema、测试、文档、产物格式和依赖，使仓库在切换结束时只剩一条当前路径。

**Blocked by:** 07 / 演练完整合成迁移与恢复.

**Status:** completed

- [x] 唯一公开 Skill 路由 account、research、valuation、planning、monitoring、review 六个高内聚自然语言任务。
- [x] Skill instruction 负责证据语义、InvestmentCase 候选、反方、证伪、不确定性和复盘判断；脚本只执行确定性处理或外部工具调用。
- [x] CLI、Skill、测试和投影只调用八个 Application operation，不访问 persistence、raw SQL、领域私有函数或退休研究入口。
- [x] composition root 只 wiring implementation 和 lifetime，不暴露 service locator、root Facade、task bag 或业务编排。
- [x] SQLite 是唯一持久化业务真值；JSON 只即时返回，Markdown 只按需投影且默认不落地。
- [x] 删除 artifact manifest、lineage、HTML、PDF、workbook、复杂图表、多格式报告目录及其 renderer、schema、测试、资产和依赖。
- [x] 删除 ResearchRequest、ResearchAnalysisPlan、ResearchRun、CompleteReport、DataSnapshot、EvidenceSnapshot、PortfolioSnapshot、InvestmentThesisVersion 和通用 workflow runtime。
- [x] 删除 TradePlanVersion、master aggregate、计划 graph/AST/sleeve、activation framework、PlanConfirmationChallenge、UserApprovalReceipt 和领域专属 receipt。
- [x] 删除 PlanImpactAssessment、PlanChangeProposal、ActionLogEntry、DisciplineReviewVersion 及重复复盘/监控真值。
- [x] 删除所有旧命令、旧 schema、旧 migration decoder、fixture、私有接口测试、文档、示例、生成资产和不再使用的依赖；更新第三方 notice（若依赖范围变化）。
- [x] 不保留兼容 shim、alias、dual read、dual write、version dispatcher、feature flag、fallback-to-old、平行 package 或旧到新转换 facade。
- [x] 当前应用不包含 DSH、Vibe-Trading、Qlib、因子挖掘、通用回测、组合优化、自动订单、runtime LLM 或它们的占位 seam。
- [x] 默认账户仍为单用户、单默认账户；真实 Provider 和真实数据根继续保持未配置、未访问状态。
- [x] 所有公开结果遵守金融输出边界，不生成个性化买卖建议、默认评级或缺少关键官方事实支持的目标价结论。
- [x] 窄回归和切换测试通过；任何剩余调用方或不可删除事实都阻塞本 ticket，不能以兼容层或 TODO 关闭。

## Answer

唯一 Skill/CLI/Application/SQLite 路径已切换；旧 runtime、25 migrations、旧测试/fixture、Web、多格式产物与依赖已删除。最终保留套件：`61 passed`；活动控制面退休搜索为零。
