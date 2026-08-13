# 研究分析计划与能力绑定

本项目把候选方法中的“先设计分析、再执行计算”吸收到唯一
`ResearchWorkflow`，但不引入第二个 Skill、CLI、执行器、缓存或数据格式。
运行时仍是确定性的本地应用流程，不执行模型生成的代码，也不依赖 LLM。

## 数据从哪里来

`ResearchAnalysisPlan@1` 不抓取数据。数据仍通过现有唯一链路进入：

1. `ProviderJob@2` 按 `SourcePolicy`、用途与权限选择 provider；
2. 原始响应经 normalize、质量门和 PIT 门形成版本化成员；
3. `DataSnapshot` 冻结成员、来源政策、截至时点和质量状态；
4. `ResearchWorkflow` 只从该冻结快照编译分析计划并执行研究。

Tushare-compatible 网关只属于非官方结构化证据。A 股关键财务事实仍以
CNINFO、交易所公告和公司 IR 为第一权威。计划中的 capability binding
只描述已经冻结的能力，不会把候选数据、估计或聚合数据升级为官方事实。

## 编译边界

`ResearchAnalysisPlanCompiler@1` 的调用者只能提交正式
`ResearchWorkflowRequest` 与仓储返回的 `SnapshotEvidence`。编译器从
`ResearchEvaluationPlan` 和冻结成员确定：

- `FrozenCapabilityBinding@1`：可用 dataset、成员身份、来源权威、质量状态
  与类型化字段合同；
- 闭合 DAG：evidence binding、research core、Forecast、情景估值、方法路由、
  估值仿真决定、近期趋势、市场路径决定和最终投影；
- 每个节点的依赖、输出合同、校验器，以及 `required` 或 `supporting` 身份；
- 直接能力摘要、依赖哈希和节点哈希。

`required` 表示节点必须产生一个有类型的结果；该结果可以合法是 `limited`、
`blocked` 或 `not_run`。数据不足只限制依赖它的方法或投影，除非身份、PIT、
权限、来源或计算完整性失效，否则不得升级成全局失败。

调用方不能提供自定义节点、自由公式或生成代码。该计划也不等于平台级
`WorkflowRun` 或 `DynamicWorkflow`；它是研究任务内部的不可变分析分解。

## 类型化模型输入合同

确定性财务模型只消费 dataset 为 `research_model_input` 的冻结字段。每个字段
必须同时满足：

- `subject_id` 与研究证券一致；
- `model_path` 非空、无首尾空白，并与 `field_name` 完全相同；
- `semantic_role = typed_research_model_input`；
- `period`、`unit`、`currency` 与 value 完整；
- 同一组件内 `model_path` 唯一。

其他 dataset 即使携带同名 `model_path` 也不能进入模型。旧的或畸形的直接
快照证据不会被兼容读取；它只使依赖的类型化模型输出受限，并保留明确原因。
从官方与结构化事实自动生成这些字段需要独立的一次性 schema/lineage 迁移，
不得用隐式映射或运行时 fallback 代替。

## 执行凭据与失效传播

最终 DecisionView 的审计区同时保存分析计划和
`ResearchAnalysisExecutionReceipt@1`。每个 receipt 绑定节点哈希、输出合同、
required/supporting 身份、实际状态、产物身份和原因码。这样可以区分：

- 证据或能力合同不满足；
- 分析节点本身受限、阻断或未运行；
- 最终报告或工作簿投影失败。

当前节点哈希用于身份、审计和确定性失效边界；现有 checkpoint 仍以正式
workflow 节点为单位。节点级复用必须先完成版本化 ledger/cache 迁移和
descendant invalidation 验收，不能从哈希存在推断缓存已经复用。

## 纠错与回归

候选 Teach 流程只吸收为 review discipline，不引入自修改 runtime。用户纠错先
形成脱敏的最小失败样例，在项目已确认的公开 seam 上证明 red，再做最小实现并
运行 focused/full regression。测试记录可进入本地 issue/evidence；生产逻辑
不会根据自由文本自动改写，也不会把一次纠错变成未经 review 的全局规则。

当前公开 seam 是 `ResearchWorkflow` 的 DecisionView/typed failure，以及
`ValuationWorkbookAdapter` 的交付验证。

## 与估值治理的连接

分析计划先确认冻结能力，之后才运行 Forecast、方法路由和估值计算。当前
runtime 的 DCF 方法权限由已实现的适用性、来源/PIT/官方事实、类型化输入、
FCFF 与方法数学、`WACC > g` 和 equity bridge 门控制。

完整 assumption challenge dossier、完整 WACC x g 参数面，以及跨
DecisionView 的独立验证/release receipt 目前只作为研究复核流程和迁移验收，
尚未成为 fail-closed runtime gate，不得声称已经强制。工作簿只是 canonical
DecisionView 的投影；交付前由 Python 从 raw OOXML 将 canonical 行和值与导出
时的 `ResearchDecisionView` 做 `Decimal` 对账，再复算工作簿已发布的 equity
bridge/per-share 链。它不是完整 DCF，也不是相对 persisted ledger 的独立二次
来源校验。失败只阻止 XLSX 交付，不抹掉已完成
的研究报告。
