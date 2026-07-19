# 13 — 切换 CLI application tasks 并退役旧研究路径

**What to build:** 让 Codex 维护入口和正式研究 CLI 通过静态注入的 named application tasks 完成 bootstrap、health、data sync、watchlist、daily research、provider qualification、Research Workflow、inspection、archive、account、market 与 maintenance journeys。用户继续使用同一稳定平台入口并获得 typed diagnostics；旧 file/V3 research entry、重复脚本、legacy HTML renderer、root aliases 和全部非 Web Facade methods 在本票内删除，文档与测试只描述 canonical path。

**Blocked by:** 12 — 原子切换 Research Workflow 与 canonical DecisionView.

**Status:** ready-for-agent

- [ ] composition bootstrap 只静态 wiring named tasks 与 lifetime；不返回 root、task bag、字符串 service lookup，不承载 business policy。
- [ ] CLI 的 bootstrap、health、sync、watchlist、daily research、provider qualification、Research Workflow、inspection、archive、account、market、migration、backup、restore、doctor、test 与 acceptance operations只调用各自完整 task interface。
- [ ] Daily Research Cycle 是唯一 daily cross-task orchestrator，provider qualification 是唯一 qualification orchestrator；CLI 和测试不重复其 policy。
- [ ] Watchlist identity、idempotency 与 transaction 行为完整归属于 canonical Watchlist task，不保留 persistence forwarding wrapper。
- [ ] data、account、market、plan 与 research application journeys 通过 typed results/inspection views 验证；只有 owning repository adapter、migration 或 corruption tests 可访问 storage fault seam。
- [ ] `ApplicationFacade` 在本票结束时不再包含任何 CLI、research、data、watchlist、account、market、health 或 maintenance method；它只暂时服务尚未迁移的 Web routes且不得新增方法。
- [ ] 旧 equity-research console entry、file/V3 runtime route、重复 research script、legacy ResearchRun HTML branch 与旧 report renderers已删除，且正式研究只存在 canonical platform CLI path。
- [ ] 旧 CLI tests、HTML-only assertions、root Forecast/Scenario/View aliases、private repository getters 与 Facade forwarding tests 已由 public task、canonical DecisionView HTML 和 adapter ownership tests替换。
- [ ] runtime dependency guard要求 callers从 canonical package interface导入，并禁止 package-private imports；active source、tests、scripts、Skill、README、examples 与 architecture docs中的旧入口和 compatibility symbols搜索清零。
- [ ] CLI JSON envelopes、typed/redacted diagnostics、created/reused research、workflow recovery、data PIT、provider qualification、account opening/import/history、watchlist persistence、market evaluation、backup/restore 与金融边界行为保持稳定。
- [ ] 项目稳定 verification command及所有受影响 suites通过；README、Skill instructions、examples、runtime metadata 和 regression ledger只命名当前入口，旧测试计数不再被固定为未来完成标准。
- [ ] 本票作为一个 commit完成所有非 Web caller cutover、旧入口/renderer删除、公开测试替换与文档同步；不得提交 forwarding task、compatibility alias、feature flag 或 dual runtime。
