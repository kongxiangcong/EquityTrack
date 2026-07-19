# 代码结构深模块改造 Wayfinder Map

Label: `wayfinder:map`
Status: `resolved`

## Destination

形成一份可以直接进入 `/to-spec` 的完整架构决策：明确 `ApplicationFacade`、forecast、scenario valuation、workflow repository、workflow execution 和 research view 的目标深模块、唯一接口、职责归属、依赖方向、一次性迁移顺序、旧代码删除条件与公开行为验收边界，使后续 `/to-tickets` 能拆出无胶水、无旁路、无兼容和无新旧并行实现的 tracer-bullet 实施票据。

## Notes

- 根目录 `AGENTS.md` 和 [长期任务 Prompt](../../docs/prompts/trading_platform_codex_prompt_optimized.md) 只提供不可弱化的长期约束；本 map 是代码结构优化的任务规划载体，不把任务清单写回 `AGENTS.md`。
- 本 map 只消除架构决策 fog，不修改生产代码。地图完成后进入 `/to-spec`，再进入 `/to-tickets`；实施阶段每票使用新上下文运行 `/implement`。
- 只保护正式平台路径的可观察行为、领域语义、历史产物可追溯性和持久化数据。旧 V3/file CLI、重复脚本、旧渲染器及私有接口不受兼容保护；迁移仍在使用的调用者后直接删除。
- 本 effort 只重构现有能力，不新增研究、估值、交易、UI 或数据源功能。测试执行基础设施已经完成，不属于本地图的优化目标。
- 完成标准是深模块的接口杠杆、职责 locality、依赖方向、旧实现删除和公开行为回归，不以文件数量或任意行数配额作为独立指标。
- 结构迁移默认不改变数据库 schema 和既有 artifact identity。确需变更时，只允许版本化、backup-first 的一次性迁移；迁移后不保留双读、双写或旧 schema fallback。
- 迁移顺序由内向外：行为基线 -> workflow persistence/领域校验 -> workflow execution -> forecast/scenario valuation -> research view -> `ApplicationFacade` 收口。
- 每张票只解决一个架构决策。用户已授权直接采用 Agent 基于代码证据给出的推荐答案，不因选择题等待人工确认；事实不足、权限变化或长期金融边界冲突仍必须停止。
- 使用 `/codebase-design` 的 module/interface/seam/depth/leverage/locality 词汇。内部模块可以有私有 seam，但不得为了测试暴露浅层接口；替换测试覆盖公开接口后删除旧私有 seam 测试。
- 当前事实基线：`scenario.py` 约 8009 行、`forecast.py` 约 3093 行、`workflows/repository.py` 约 1998 行、`workflows/research.py` 约 909 行、`research_view.py` 约 942 行；`ApplicationFacade` 公开大量底层镜像方法。行数仅用于定位，不作为完成定义。

## Decisions so far

<!-- Closed-ticket index only. Detailed answers live in the resolved ticket. -->

- [锁定受保护行为与目标模块依赖基线](issues/01-lock-protected-behavior-and-dependency-baseline.md) — 只保护正式 task 行为、不可变历史、持久化数据与 artifact identity；目标深模块公开回归建立后删除镜像 Facade、跨 seam SQL、旧入口、兼容分支及直接私有方法测试。
- [决定 Workflow persistence 与 artifact lineage seam](issues/02-place-workflow-persistence-and-lineage-seam.md) — 以纯 `ArtifactLineage` 校验 typed frozen evidence、由单一 `WorkflowLedger` 原子拥有 SQL/锁/对象/manifest；沿用现有 schema 与 artifact identity，不建立转发 repository 或双路径。
- [决定 Workflow 状态机与研究执行 seam](issues/03-separate-workflow-state-machine-and-research-execution.md) — 由唯一 `ResearchWorkflow` 拥有 run/lease/checkpoint/retry/cancel 状态机，`ResearchExecution` 只执行被选定节点与研究门禁；view、inspection 和 forecast review 各归独立任务 seam。
- [决定 Forecast 深模块拓扑](issues/04-partition-forecast-domain-modules.md) — 保留唯一 `ForecastEngine.build` seam，以 `ForecastEvidence`、`ForecastGraph`、`ManufacturingForecast` 集中输入、图代数与三表推演；shell 不升格为浅模块，并以 versioned identity 修复跨 archetype graph-id collision。
- [决定 Scenario valuation 方法族深模块拓扑](issues/05-partition-scenario-valuation-method-families.md) — 保留唯一 `ScenarioValuationEngine.run` seam，以 Scenario Set、Valuation Basis 和 industrial/cyclical/financial/biopharma 四个完整方法族集中情景政策、Forecast 绑定、权益桥与行业经济学；只做同方法跨情景加权。
- [决定类型化 Research decision view seam](issues/06-define-typed-research-decision-view.md) — 以 `build(ResearchDecisionInput)` 生成唯一 typed `ResearchDecisionView@2`，集中展示许可、决策解释和可比性；workflow只构建一次、workspace加载持久化view，renderers不得重算语义。
- [决定 Application task interfaces 并收缩 Facade](issues/07-shrink-application-task-interfaces.md) — 删除 shallow `ApplicationFacade`，由按用户任务命名的 deep modules直接注入 CLI/Web，并以组合 query取代 raw getters；不建立总线、locator或兼容 wrapper。
- [锁定替换迁移、删除和验证顺序](issues/08-lock-replacement-migration-and-verification-order.md) — 以六个 blockers-first tracer bullets原子替换 Forecast、Scenario、Workflow、DecisionView和应用 callers；每票同提交删除旧路径，最终以完整备份迁移、Python/Web/Chromium/release gates证明无兼容期。

## Not yet specified

- 无；implementation拆分、私有测试归类、旧入口/renderer删除和完成 gates已全部毕业到[锁定替换迁移、删除和验证顺序](issues/08-lock-replacement-migration-and-verification-order.md)。

## Out of scope

- 新的研究方法、估值方法、交易策略、账户能力、Provider、数据源、自动交易或个性化投资建议。
- 产品信息架构、视觉样式或 Web 功能扩展；只有保持现有正式行为所必需的调用迁移属于本 effort。
- 为减少行数而机械拆文件、建立转发模块、保留兼容别名、双路径运行或大爆炸式重写。
- 与目标模块无关的性能优化、依赖升级、构建系统替换和仓库清理。
