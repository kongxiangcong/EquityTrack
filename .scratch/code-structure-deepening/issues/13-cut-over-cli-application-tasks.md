# 13 — 切换 CLI application tasks 并退役旧研究路径

**What to build:** 让 Codex 维护入口和正式研究 CLI 通过静态注入的 named application tasks 完成 bootstrap、health、data sync、watchlist、daily research、provider qualification、Research Workflow、inspection、archive、account、market 与 maintenance journeys。用户继续使用同一稳定平台入口并获得 typed diagnostics；旧 file/V3 research entry、重复脚本、legacy HTML renderer、root aliases 和全部非 Web Facade methods 在本票内删除，文档与测试只描述 canonical path。

**Blocked by:** 12 — 原子切换 Research Workflow 与 canonical DecisionView.

**Status:** resolved

- [x] composition bootstrap 只静态 wiring named tasks 与 lifetime；不返回 root、task bag、字符串 service lookup，不承载 business policy。
- [x] CLI 的 bootstrap、health、sync、watchlist、daily research、provider qualification、Research Workflow、inspection、archive、account、market、migration、backup、restore、doctor、test 与 acceptance operations只调用各自完整 task interface。
- [x] Daily Research Cycle 是唯一 daily cross-task orchestrator，provider qualification 是唯一 qualification orchestrator；CLI 和测试不重复其 policy。
- [x] Watchlist identity、idempotency 与 transaction 行为完整归属于 canonical Watchlist task，不保留 persistence forwarding wrapper。
- [x] data、account、market、plan 与 research application journeys 通过 typed results/inspection views 验证；只有 owning repository adapter、migration 或 corruption tests 可访问 storage fault seam。
- [x] `ApplicationFacade` 在本票结束时不再包含任何 CLI、research、data、watchlist、account、market、health 或 maintenance method；它只暂时服务尚未迁移的 Web routes且不得新增方法。
- [x] 旧 equity-research console entry、file/V3 runtime route、重复 research script、legacy ResearchRun HTML branch 与旧 report renderers已删除，且正式研究只存在 canonical platform CLI path。
- [x] 旧 CLI tests、HTML-only assertions、root Forecast/Scenario/View aliases、private repository getters 与 Facade forwarding tests 已由 public task、canonical DecisionView HTML 和 adapter ownership tests替换。
- [x] runtime dependency guard要求 callers从 canonical package interface导入，并禁止 package-private imports；active source、tests、scripts、Skill、README、examples 与 architecture docs中的旧入口和 compatibility symbols搜索清零。
- [x] CLI JSON envelopes、typed/redacted diagnostics、created/reused research、workflow recovery、data PIT、provider qualification、account opening/import/history、watchlist persistence、market evaluation、backup/restore 与金融边界行为保持稳定。
- [x] 项目稳定 verification command及所有受影响 suites通过；README、Skill instructions、examples、runtime metadata 和 regression ledger只命名当前入口，旧测试计数不再被固定为未来完成标准。
- [x] 本票作为一个 commit完成所有非 Web caller cutover、旧入口/renderer删除、公开测试替换与文档同步；不得提交 forwarding task、compatibility alias、feature flag 或 dual runtime。

## Implementation Evidence

- `trading_platform.application` 现在是 CLI 唯一公开导入面；静态 named-task factories、typed codecs/results 和只读 readiness gate 取代 root/task-bag/Facade 转发。账户、研究、数据、市场与维护任务只由各自 owning task 执行，只有 `PlatformOperations.bootstrap/migrate` 能改变 schema 或执行 DecisionView cutover。
- `ResearchInputs` 只由 `trading_platform.domain` 拥有，严格拒绝未知字段和错误 JSON 类型；研究输出只发布 `ResearchDecisionView@2` 与 `ResearchSourceIdentityHtml@1`，旧 console/file/V3 路径、报告 renderer、兼容 alias 与重复脚本已删除。
- 测试通过 typed task results、WorkflowInspection、ResearchArchive 或命名的 adapter/corruption seam 验证；普通 journey 不再依赖 root aliases、Facade forwarding 或任意 store 暴露。
- `python -m trading_platform.cli test --repo-root .` 最终在 204.704 秒内通过：core 187、platform 35/51/79/80、Web 18，共 450 passed；4 skipped、1 deselected、0 failed。前一次高并发运行仅心跳时序用例出现一次 `RUNTIME_BUSY`，该用例独立重跑通过，随后完整命令通过。
- 配置 bundled Node 运行 `python -m pytest -q tests/platform/test_valuation_workbook_adapter.py`：4 passed、0 skipped；未声称 live 外部 provider 验证，qualification 使用 loopback fixture。
- `python -m mypy --follow-imports=skip ...` 对 Ticket 13 边界的 23 个 source files 通过；扩大到既存 account 实现会报告 12 个旧类型问题，未将其误报为通过。`python -m compileall -q src tests` 与 `git diff --check` 通过。
- Standards 与 Spec 最终双轴复审均无 actionable findings。
