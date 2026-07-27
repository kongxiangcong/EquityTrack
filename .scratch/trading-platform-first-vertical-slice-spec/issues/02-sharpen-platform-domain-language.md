# 统一平台领域语言与上下文边界

Type: `grilling`
Mode: `HITL`
Status: resolved
Blocked by: 01

## Question

在总任务 Prompt 已固定的 fact、assumption、forecast、valuation、trade plan、strategy、backtest、dynamic workflow 和 complete 定义上，结合当前代码现实，第一条纵向切片应如何精确定义并区分 `Security`、`WatchlistItem`、`Position`、`ResearchRequest`、`ResearchRun`、`Evidence`、`DataSnapshot`、`MarketSnapshot`、`TradePlan`、`TradePlanVersion`、`PlanRule`、`PlanEvaluation`、`WorkflowRun`、`ArtifactManifest` 与 `ChartAnnotation`？需要解决 `conditional_plan` 与 `trade plan` 的命名冲突、实体身份和不可变/版本化关系，并把真正达成共识的术语写入 `CONTEXT.md`；不要把实现细节写进 glossary。

## Answer

已通过逐项 grilling 达成共识，并将统一语言写入根目录[领域词汇表](../../../CONTEXT.md)。用户明确确认了 `Security`、`WatchlistItem`、`Position`、`ResearchRequest`、`ResearchRun`、`Evidence` 与 `DataSnapshot` 的建议边界，并授权剩余术语直接采用同一套推荐原则继续收敛。

### 核心身份边界

- `Security` 是具有连续法律与交易身份的可交易证券，不是公司、发行人、简称或 ticker。不同市场或股份类别是不同证券；仅改名或换代码不改变身份。
- `WatchlistItem` 是证券进入一个观察列表后形成的一段关注关系，不是虚拟持仓。移出观察列表结束该关系；以后重新加入是新的关注关系，从而保留前后两段历史。
- `Position` 是账户、证券和时点共同确定的实际持有状态，不是长期可任意覆盖的“证券属性”，也不是交易或持仓批次。清仓后没有当前持仓，但历史交易、批次和组合快照仍保留。
- `ChartAnnotation` 是稳定的逻辑标注身份，锚定市场时间/价格坐标而非屏幕像素；修改形成新版本，删除只终止有效状态，不抹除历史。

### 研究、证据与数据快照

- `ResearchRequest` 是一次确定性研究执行的不可变意图；`ResearchRun` 是该请求的一次不可覆盖结果。重新执行、输入变化或代码变化形成新的研究运行，不修改旧运行。
- `Evidence` 是最小不可变引用单元；`DataSnapshot` 是一次运行可复现的冻结输入集合。前者回答“该判断依据什么”，后者回答“该运行当时看到了哪一版数据”。
- 当前核心的 `EvidenceItem.evidence_id` 是 `ResearchRun` 内局部身份，不能把单独的 `E0001` 当成平台全局引用；跨运行引用在领域上必须同时指明所属研究运行。是否增加全局内容身份由后续存储契约决定。
- `DataSnapshot` 可以被多个请求或运行复用，但其内容一旦冻结不得被修订数据原地覆盖。修订形成新快照。
- `MarketSnapshot` 不是 OHLCV 行情集合，而是基于确定 `DataSnapshot` 对特定时点市场状态形成的不可变、可解释描述；后续计划评估引用它，而不是自行重新读取“最新行情”。

### `conditional_plan` 命名冲突

现有 `ResearchRun.conditional_plan` 的真实内容是 `watch / validation_trigger / invalidation / review_window`，报告也将其呈现为“条件验证与复核计划”。它没有用户确认、风险预算、入场/调整/退出规则、版本、状态机或市场快照评估，因此不属于 `TradePlan`。

统一领域名称采用 `ResearchReviewItem（研究复核项）`：一个研究运行可包含多个研究复核项，用于决定何时重新检查研究观点。`conditional_plan` 仅作为当前 MVP 的遗留序列化字段理解，后续迁移不得把它导入或升级为交易计划，也不得把研究复核项称为 `PlanRule`。

### 交易计划的稳定身份与版本链

- `TradePlan` 是用户针对一个证券确认的稳定逻辑身份和版本链；它不是研究输出、评级、建议、策略或订单。
- `TradePlanVersion` 是一次用户确认后的完整、不可变计划内容。修改必须创建新版本，旧版本不能覆盖；后续评估永远引用当时的确切版本。
- `PlanRule` 隶属于一个交易计划版本，表达可确定性判断的条件及其决策含义。它最多产生状态或用户复核提示，不提交交易。
- `PlanEvaluation` 是将一个确切计划版本与一个确切市场快照配对后形成的不可变结果，必须保留触发、未触发、受阻或无法判断及原因。它不是执行记录，也不能反向修改计划版本或市场快照。
- 计划生命周期、规则键、评估幂等键和缺失/陈旧市场数据语义仍由[决定交易计划状态机与市场状态评估接口](10-decide-trade-plan-and-market-evaluation.md)决定；本票据只固定领域边界。

### 平台工作流与产物

- `DynamicWorkflow` 是可版本化的流程定义；`WorkflowRun` 是一次平台级执行的稳定身份和可追溯历史。工作流状态可以推进，但已完成节点、检查点和引用结果不得通过覆盖历史来“改写成功”。
- `ResearchRun` 是工作流可能产生或复用的研究结果，不等于 `WorkflowRun`。一个工作流还可包含同步、验证、计划评估、持久化和发布等非研究节点。
- `ArtifactManifest` 是某次工作流运行或可恢复检查点的不可变产物目录，不是产物本身。新检查点或新输出集合形成新的清单版本，旧清单保留。
- 领域关系确定为 `WorkflowRun` 引用 `ResearchRun`、`PlanEvaluation` 和 `ArtifactManifest`；`ArtifactManifest` 再标识输入与输出产物。引用在数据库中采用外键、内容地址还是嵌入式文档，留给后续存储与 run-journal 票据，不写入 glossary。
- canonical `ResearchRun` JSON 可以作为清单中的结构化产物；HTML 报告是从它派生的另一产物，两者不能冒充同一对象。

### 继承的固定术语与刻意排除

总任务 Prompt 已固定的 `Fact`、`Assumption`、`Forecast`、`Valuation`、`Strategy`、`Backtest` 和 `DynamicWorkflow` 已按原边界写入词汇表，没有弱化数据时间、确定性计算、反前视或运行时无 LLM 的要求。

`complete` 是项目交付与验收状态，不是本领域独有的业务对象，因此刻意不写进 glossary；其含义继续以总任务 Prompt 的“实现、迁移、测试、文档、可追溯数据和验收用例全部通过”为准。

本次收敛没有新增未覆盖问题：数据快照的物理身份和修订语义由[决定分层存储、时间语义与同步契约](07-decide-data-storage-and-pit-contracts.md)处理；`WorkflowRun`、`ResearchRun` 和产物清单的持久化/恢复关系由[决定 Codex 控制面、确定性运行时与 run journal 边界](08-decide-control-plane-runtime-and-run-journal.md)处理；标注序列化由[原型化 K 线与持久化标注 seam](09-prototype-chart-and-annotation-seam.md)验证；计划状态机和评估接口由[决定交易计划状态机与市场状态评估接口](10-decide-trade-plan-and-market-evaluation.md)决定。
