# 审计当前每周决策旅程与可复用 seam

Type: `task`
Mode: `AFK`
Status: `resolved`

## Question

以当前 checkout、未提交修改、真实 CLI/Provider/浏览器结果和既有第一纵向切片为事实源，回答从“形成当前账户状态”到“收盘后计划评估、下一交易日查看、周末复盘”的实际调用链现在能走到哪里；锁定可复用的窄应用任务接口、领域能力和持久化所有权，并严格区分已实现、部分实现和未实现。

## Answer

### 当前结论

当前 checkout 已完成从聚合 Facade 到窄任务接口的切换。唯一允许的应用入口是 `trading_platform.application` 暴露的任务合同以及 `application.bootstrap.open_*` composition functions；CLI/Web 通过这些入口调用账户、同步、研究、图表、计划、市场和工作区能力，`WorkflowLedger` 是工作流持久化唯一所有者。后续切片不得恢复聚合 Facade、不得新增转发包装层，也不得让 CLI/Web 直连 SQLite 或领域私有实现。

代码结构和发布证据已闭合动态标的身份、图表错误失败关闭、账户空状态文案、真实浏览器身份绑定与 fresh-checkout 静态资产验证。当前产品旅程仍未闭合的核心不是这些已修复问题，而是：

- 没有 `UserDeclaredAccountSnapshot` 的草稿、确认、版本与 capability 产品入口；
- 没有可供真实用户创建和修订计划草稿的完整任务/UI；
- `DailyResearchCycle` 仍是配置 job 驱动的单次 sync/research/market/evaluation，不是从账户持仓派生 universe 的组合级日终 orchestrator；
- 工作区仍围绕调用者给定的 `security_id + snapshot_id`，没有冻结后的下一交易日 inbox、跨持仓优先级和相对前日变化；
- 没有用户行动/例外日志和不可变 weekly review artifact。

### 当前调用链与复用边界

| 旅程阶段 | 当前事实 | 结论 |
|---|---|---|
| 账户形成 | 已有同花顺 preview、账户初始化/展示、历史导入和 acceptance；账户与组合快照保持不可变/受限能力语义。 | **部分实现**：文件导入可复用；手工声明起点尚未实现。 |
| 日终数据冻结 | `DataSynchronization`/`DataSyncService` 生成带 `requested_date`、`effective_session_date`、PIT cutoff、freshness、quality 和版本身份的快照。 | **底层已实现，组合产品未实现**：没有从账户派生全持仓范围的一次性冻结任务。 |
| 公司研究 | `open_research_workflow`、`WorkflowInspection`、`ResearchArchive` 与类型化 artifact/ForecastReview 可复用。 | **单标的已实现，组合 readiness 未实现**。 |
| K 线与标注 | `open_chart_workspace` 和 `open_chart_annotations` 分别提供读取与生命周期任务，真实浏览器路径已纳入发布验收。 | **已实现**；不得建立第二套图表或标注持久化。 |
| 计划 | `PlanService`/`open_trade_plan` 保留版本、确认和状态机能力。 | **领域已实现，真实 authoring 旅程未实现**。 |
| 市场与评估 | `open_market` 暴露冻结市场快照和只读确定性计划评估；freshness、停牌、涨跌停、公司行动冲突已有 typed 降级基础。 | **单计划已实现，组合日终循环未实现**。 |
| 下一交易日工作区 | `open_decision_workspace` 聚合指定身份的冻结视图。 | **部分实现**：缺少日终发布的 next-session inbox 和跨持仓任务路由。 |
| 周末复盘 | 现有工作流账本可承载不可变 artifact。 | **未实现**：尚无 weekly review、行动纪律、规则变更与证伪对象。 |

### 必须沿用的深 seam

1. 应用层只新增“完成一个用户任务”的窄接口；composition root 只负责装配，不承载第二套业务流程。
2. 账户来源可以新增手工声明适配器，但确认后必须落入共享的不可变账户快照语义；不得伪装成券商导入或伪造历史。
3. 日终闭环应成为一个拥有冻结、幂等、失败恢复和发布事务的深应用任务，而不是由 Web 串联 sync/research/market 私有调用。
4. 计划、市场评估、研究证据和工作流历史继续使用现有领域模型与 `WorkflowLedger`；替换接口时同步迁移调用者并删除旧路径。
5. 工作区只读取已经发布的同一 cutoff 版本，不在页面加载时拼接“各自最新”的账户、行情与研究数据。

### 对后续地图的影响

- 用户声明账户票据负责手工输入的来源信任、unknown 与 capability。
- 日终时间合同票据负责完整收盘数据、PIT cutoff、下一开放日以及交易限制。
- 计划/市场/每日与每周工作流票据负责组合级 orchestrator、inbox、行动日志和 weekly review。
- 真实旅程验收必须从空数据根经公共任务接口走完，不能以预置数据库或直接领域调用替代产品可用性。
