# 个人投研交易策略平台第一条纵向切片 Wayfinder Map

Label: `wayfinder:map`
Status: `resolved`

## Destination

在完整审计当前股票投研报告 MVP、完成必要且证据化的外部技术调研后，形成一份与当前代码库一致、可以直接进入实现阶段的“个人投研交易策略平台第一条纵向切片 Spec”。该 Spec 必须覆盖一只持仓股或观察股从增量同步、复用投研、K 线标注、版本化交易计划、当日市场状态评估，到数据版本、证据、结果和运行记录持久化回看的完整闭环。

## Notes

- [总任务 Prompt](../../docs/prompts/trading_platform_codex_prompt_optimized.md) 是本项目不可违反的长期任务声明、范围边界和验收基线；任何 ticket 只能在其约束内消除 fog，不能修改或弱化它。
- 每次工作前读取本 map、根目录 `AGENTS.md`、总任务 Prompt，以及与当前 ticket 相关的既有决策。长期边界包括：Codex 是控制面、业务运行时无 LLM API/分析 prompt、本地优先、Windows 可用、用户不手工拼 CLI、不破坏现有 MVP、无真实自动下单、关键结果可追溯可复现。
- 产品与交互采用设计驱动：默认只展示当前判断所需的关键信息，过程/provenance 数据渐进披露，优先解释变化、比较、影响与不确定性；视觉与交互借鉴 Apple 的清晰、克制、层级、一致性和直接操作思想。异常只有在影响能力时打断主视图，且必须保持可访问性和非个性化投资建议边界。
- 每个 Wayfinder 会话最多解决一个 ticket。研究票据使用 `/research`；原型票据使用 `/prototype`；需要用户决策的票据使用 `/grilling`，并持续用 `/domain-modeling` 校准统一术语。
- 外部调研必须形成独立 research ticket 和链接资产，检查固定版本的许可证、NOTICE/归属、核心源码、数据模型、扩展接口、测试、维护状态、Windows 支持、失败恢复、数据许可与 LLM 依赖；不得只看 README、Star 或宣传截图。
- 当前代码实况基线：稳定 seam 是 `ResearchEngine.run(ResearchRequest) -> ResearchRun`；CLI 是文件系统 adapter；35 项行为测试通过；当前没有数据库、迁移、本地 Web/K 线交互、Provider 同步层、版本化交易计划、市场状态评估或持久化 run journal。`conditional_plan` 是研究观察项，不等同于总任务 Prompt 定义的 `trade plan`。
- 本 map 只做 wayfinding 与 Spec 收敛，不直接大规模实现平台。研究资产和审计资产可作为 ticket 输出；平台代码、数据库迁移和 UI 实现留给 Spec 之后的实现阶段。

## Decisions so far

<!-- Closed-ticket index only. The detailed answer lives in exactly one ticket. -->

- [审计当前投研 MVP 与可复用边界](issues/01-audit-current-mvp-and-reuse-seams.md) — 保留 `ResearchEngine.run(ResearchRequest) -> ResearchRun` 作为研究深模块 seam；平台通过 snapshot/request 与 persistence adapters 接入，遗留全局门禁、临时产物协议和研究观察计划不得冒充平台运行时能力。
- [统一平台领域语言与上下文边界](issues/02-sharpen-platform-domain-language.md) — 以 `Security` 为可交易证券身份，区分冻结数据、证据、市场状态、研究运行与工作流运行；将 `conditional_plan` 定义为研究复核项，并以稳定 `TradePlan` 加不可变版本/规则/评估保留决策历史。
- [调研数据 Provider、point-in-time 与增量缓存](issues/03-research-data-providers-pit-and-cache.md) — 采用官方披露权威、可选 Tushare 与 AKShare/BaoStock 回退的运行时组合；Kimi Code CLI 0.23.5 + Datasource 3.2.0 live 复验后仍仅作 Codex 低频采集桥，生产同步须保留四类时间、未复权 canonical、内容寻址 raw、数据集级 freshness/cursor 和真实 provenance。
- [调研 K 线库、标注能力与许可证](issues/04-research-chart-libraries-and-annotation-models.md) — 精确锁定 `klinecharts@10.0.0` 作为 adapter 后的受控原型候选，以库无关版本化 DTO 持久化时间/价格锚点；Lightweight Charts 5.2.0 与 ECharts 6.1.0 在本 K 线交互面仅作参考，正式采用须先通过 Windows、重启、复权/跨周期和离线门禁。
- [调研本地运行时、存储与恢复基线](issues/05-research-local-runtime-store-and-recovery.md) — 保留 SQLite + 内容寻址不可变文件为最小对照候选并设置已修复 WAL runtime 门；DuckDB/Parquet 延后到真实分析瓶颈，PostgreSQL 仅由多写者或数据库级 PITR 触发，恢复采用 DB snapshot + hash manifest bundle。
- [固定纵向切片用户故事与示例标的](issues/06-fix-slice-user-story-and-security-fixture.md) — 以意华股份观察项为入口，固定 `2026-07-11` 请求回退至 `2026-07-10` 交易日、复用 7 月 7 日研究的八步闭环，并以真实可追溯市场 fixture、显式计划确认和绝无交易执行作为验收边界。
- [决定分层存储、时间语义与同步契约](issues/07-decide-data-storage-and-pit-contracts.md) — 锁定 SQLite 事务权威加内容寻址不可变文件、四类时间与保守 PIT、未复权 canonical、版本化 Provider/freshness/cursor/质量合同及第一切片最小 typed schema。
- [决定 Codex 控制面、确定性运行时与 run journal 边界](issues/08-decide-control-plane-runtime-and-run-journal.md) — 锁定 Codex 外部控制面、统一 application facade、九项真实维护入口、版本化确定性工作流、SQLite 恢复 journal、不可变 checkpoint manifests 与可验证的重跑/中断恢复语义。
- [原型化 K 线与持久化标注 seam](issues/09-prototype-chart-and-annotation-seam.md) — 以 B 画布优先驾驶舱为默认兼全屏视图，吸收 C 不可变版本账本为可收起侧栏；过程/provenance 数据按需查看，异常显式阻断，标注继续采用库无关版本 DTO 与跨视图 fail-closed。
- [决定交易计划状态机与市场状态评估接口](issues/10-decide-trade-plan-and-market-evaluation.md) — 锁定草稿到不可变版本的显式生效状态机、typed 规则 AST、四组件透明 A 股市场快照、只读多值评估、证据与幂等接口，并确保任何触发都不产生交易副作用。
- [决定纵向切片最高层验收 seam](issues/11-decide-vertical-slice-acceptance-seam.md) — 以生产 composition root 下的 ApplicationFacade 公开命令/查询旅程作为权威验收缝，分层锁定真实 fixture、复用/幂等/恢复、浏览器、Windows 运维、回归与无 LLM/交易副作用证据。
- [综合第一条纵向切片实现级 Spec](issues/12-synthesize-implementation-ready-spec.md) — 形成与当前代码严格分界、证据链接完整、含 38 条验收标准和九步实施顺序的 Spec 0.1.0，等待最终对抗性审计。
- [对抗性审计 Spec 并关闭实施前缺口](issues/13-adversarially-audit-and-close-spec-gaps.md) — 以 10 个可执行反例补强双快照/PIT universe、金融 adapter、复现身份、风险、安全许可和后见之明门，将 Spec 升为 0.2.0 与 51 条验收标准并确认第一切片实施前无剩余 fog。

## Not yet specified

（无；所有 child tickets 已关闭，第一纵向切片 Spec 0.2.0 已通过对抗性审计。后续平台实现应开启独立 implementation effort。）

## Out of scope

- 本 Wayfinder 阶段的大规模平台实现、数据库落地、Web UI 正式开发或现有 MVP 重写。
- 真实券商账户接入、真实自动下单、自动成交执行，以及把交易计划扩展成未经确认的执行指令。
- 个性化买卖建议、BUY/HOLD/SELL、目标价结论或收益承诺。
- 第一条纵向切片之外的完整多账户组合会计、全量策略实验平台、完整回测框架、Monte Carlo 平台和多市场全面覆盖；只在切片接口必须预留时写边界。
- 在业务运行时引入 LLM API、Agent 编排或硬编码分析 prompt。
