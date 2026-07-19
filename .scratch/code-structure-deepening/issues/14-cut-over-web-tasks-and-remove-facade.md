# 14 — 切换 Web tasks、删除 ApplicationFacade 并完成 release proof

**What to build:** 让本地 Web workspace 通过窄的 DecisionWorkspace、ChartWorkspace、ChartAnnotations、TradePlan 与 update-authorization tasks 完成现有 chart、annotation、plan、account、market、research history 和 DecisionView journeys，同时保持 HTTP、安全、无障碍、reload 与 restart 行为。全部 remaining callers 迁移后彻底删除 `ApplicationFacade`、mirror ports 与 private root；最终以静态删除、完整 Python/Web、workbook、真实 Chromium、数据迁移恢复和 release acceptance 证明平台只有一条正式路径。

**Blocked by:** 13 — 切换 CLI application tasks 并退役旧研究路径.

**Status:** ready-for-agent

- [ ] Web server构造时显式接收窄的 DecisionWorkspace、ChartWorkspace、ChartAnnotations、TradePlan/Plan Confirmation 与 update-authorization interfaces，不接收 root、container、Facade 或 nullable backing object。
- [ ] GET routes 只投影 task 返回的 canonical workspace views；POST annotation/plan routes只调用一个 typed lifecycle command，不读取 history、series 或 storage后自行决定领域操作。
- [ ] chart、annotation、TradePlan、PlanEvaluation、AccountSnapshot、MarketSnapshot、ResearchRun、WorkflowRun 与 DecisionView 的现有 HTTP shapes、immutable history、typed failures、安全和金融边界保持稳定。
- [ ] production browser verifier通过 production bootstrap与canonical fixture tasks启动真实本地 server，不导入 test-private bootstrap/helper。
- [ ] 所有 production/test callers 已迁移后，`ApplicationFacade`、mirror ports、root Facade access、private store/repository exposure、nullable backing objects与 forwarding assertions全部删除并搜索清零。
- [ ] composition bootstrap只保留 wiring/lifetime；删除 Facade后不得出现 replacement bus、service locator、generic task bag、compatibility wrapper、dual route 或 adapter-side business workflow。
- [ ] chart、plan 与 market persistence 的 direct-storage coverage只存在于各自 owning repository adapter tests；application/Web journeys只经 public tasks验证。
- [ ] Web source tests覆盖 canonical projections、mutation lifecycle、authorization、security headers、keyboard、narrow viewport 与 reduced motion；build output从当前 source重新生成，依赖、lock、license与third-party notices无漂移。
- [ ] 静态 release gate执行 diff/whitespace、AST dependency与forbidden-symbol检查；active runtime、tests、scripts和文档对 Facade、旧 workflow/repository、compatibility decoder、duplicate renderer、旧 CLI/script、root getter与被直接测试的 private helpers零命中。
- [ ] canonical full Python verification 的全部 suites通过，测试清单中的每项恰好执行一次；Web tests与production build通过。任何 skipped、timeout、external check未运行或 nonzero 都不得记录为 pass。
- [ ] bundled workbook runtime验收为4 passed、0 skipped，并覆盖 exact canonical DecisionView、reconciliation和tamper failures。
- [ ] 真实 Chrome/Edge CDP验收覆盖HTTP、reload、server restart、chart/annotation lifecycle、plan confirmation、workspace DecisionView、security headers、keyboard、narrow viewport与reduced motion，并生成不泄露私密路径的 evidence。
- [ ] fresh、prior-version fixture与created/reused populated roots均通过 canonical `backup -> migrate -> doctor -> history/archive -> backup -> restore -> doctor`，验证backup hashes/counts、database integrity、object hashes、GraphIdentity@2共存、source pointers、唯一 decision manifest、fault rollback与exact retry。
- [ ] release-acceptance suite为0 skipped，随后canonical acceptance CLI在fresh root和fixture manifest上通过ledger、全部criteria、command identity、browser/backup/legacy-replacement evidence与immutable manifest自校验；provider不可用只能明确记录为`external_blocked`。
- [ ] 最终行为/failure矩阵覆盖create/replay/conflict、restart、workflow lifecycle、artifact corruption、Forecast archetypes、Scenario方法族、DecisionView permission/comparability、chart/plan/account/market history、CLI JSON、HTTP security与金融输出边界，并保留owning module typed code与redacted substep evidence。
- [ ] 最终检查确认README、Skill、examples、tests、runtime、dependencies、lock、notices与built assets只描述一个current path；无关dirty changes未被清理、覆盖、暂存或纳入本票。
- [ ] 本票作为一个commit完成remaining caller cutover、Facade删除和全部release proof；任何未通过 gate、未声明真实 caller或无法安全迁移的数据都保持本票未完成，不以fallback/alias绕过。
