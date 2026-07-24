# 绘制外部能力与现有模块的替换删除矩阵

Type: `task`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

以当前 checkout 的 `trading_platform.application`、DataProvider、Forecast、Scenario Valuation、Valuation Simulation、Strategy/Backtest、WorkflowLedger 与 ResearchDecisionView 正式路径为事实源，逐项映射四个外部候选能提供的行为、现有 canonical implementation、真实缺口、caller/persistence/presentation 影响和必须删除的旧对象；对每行只允许形成 `adopt-external`、`adapt-code`、`keep-local` 或 `reject` 的候选结论，并用 deletion test 排除 wrapper、fallback、dual-read/write 和平行平台。

## Answer

### 结论

逐能力替换/删除矩阵已经锁定。它按行为而不是按整个上游仓库决策，并把候选结论、采用条件、caller/persistence/presentation 影响和原子删除对象放在同一行：

- [总替换与删除矩阵](../research/replacement-deletion-matrix.md)
- [Application/Data 详细审计](../research/replacement-matrix-application-data.md)
- [Research/Artifacts 详细审计](../research/replacement-matrix-research-artifacts.md)
- [Strategy/External 详细审计](../research/replacement-matrix-strategy-external.md)

当前 named application tasks、`DataProvider -> DataSyncService -> DataRepository`、Forecast、Scenario Valuation、Valuation Simulation、`MarketPathEngine`、ResearchWorkflow、WorkflowLedger/ArtifactLineage 与 `ResearchDecisionView@2` 都是 `keep-local` 的 canonical owners。两个数据 Skill 的完整执行/编排是 `reject`；只有后续逐端点证明权利、PIT、字段/单位、失败语义与官方交叉验证的协议/解析行为，才是 `adapt-code` 候选，并且只能进入深化后的同一 Provider seam。

Public Equity Investing 的 production runtime、数据、估值与 presentation 是 `reject`；当前控制面质量对照是 `keep-local` 且精确 `external_blocked`，没有黑盒证据前不能声称 `adapt-code`。Vibe-Trading 只有针对当前不存在的 StrategyValidation（backtest、Walk-Forward、strategy bootstrap/return Monte Carlo）是有条件 `adopt-external` 候选；ticket 06 任一必需门禁失败都将其改判 `reject`，不得增加 local fallback。其 live/simulated order、broker、order lifecycle、file、web/search、memory、swarm、Agent、完整 Web/report/persistence 永久 `reject`。

### 已证实的结构缺口与删除边界

当前 production 只有 singleton provider composition，没有版本化 source policy；`DataSyncService` 泄漏 Tushare wire 参数，generic normalizer 也混有 Tushare 协议解析。full-universe identity、typed forecast actual、official filing/financial fact/news/corporate-action ingestion、EvidenceSnapshot assembly 与 adjusted-price path 均不完整。后续实现必须把协议变化完全移入真实 Adapter、建立一个 canonical source/evidence path，并删除旧 job decoder、caller-owned wire params、source-specific generic-normalizer branches、test-only direct-SQL evidence 与退休 fallback；不得平行保留。

StrategyValidation 当前没有 production engine/schema/CLI/Web route，acceptance 明确 `full_trade_backtest: not_applicable`。因此 Vibe 若资格化，填补的是空白，不是包装本地实现；正式采用必须同一切片完成 typed identity/lineage、ledger persistence、唯一 view migration（若需 presentation）、所有 callers/tests/docs 切换，并删除 raw upstream JSON/HTML/PDF、临时 MCP/subprocess harness 和旧 `not_applicable` acceptance。Forecast、两类 valuation/market simulation 与 canonical presentation 不得被替换或复用。

Deletion test 同时拒绝了 Skill runner、通用 external provider、MCP tool mirror Facade、provider fallback、dual-read/write、raw report viewer 与第二 Web。`ResearchDecisionView@2` cutover 的 callback/materializer/runtime gate 只是条件性 migration-only 删除候选：只有最低支持数据版本证明 cutover 永久完成后才可原子删除，严禁把它泛化为外部结果 wrapper。

### 对地图前沿的影响

本票不做端点或算法资格化，也不锁定最终 StrategyValidation 字段。下一数字优先 frontier 是“黑盒评估 Public Equity Investing 的研究质量与输出边界”；其 `external_blocked` 不会阻断后续 a-stock-data、global-stock-data 与 Vibe 票继续。
