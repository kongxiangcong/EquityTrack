# 12 — 原子切换 Research Workflow 与 canonical DecisionView

**What to build:** 让新研究运行只通过 `ResearchWorkflow.handle` 驱动 versioned workflow lifecycle、通过 `ResearchExecution.execute` 执行选定研究节点，并为每个成功 WorkflowRun 恰好持久化一个 canonical `ResearchDecisionView@2`。一次性 `ResearchDecisionViewCutover@1` 在完整备份后修复历史 ResearchRun source pointers 与 workflow-scoped DecisionView manifests；workspace、archive、HTML 与 workbook 只加载持久化 view。旧 workflow service/registry、双 schema decoder、重复 renderer 语义与私有测试在本票内删除。

**Blocked by:** 09 — 建立 canonical Forecast contract 与 GraphIdentity@2; 10 — 建立 canonical Scenario Valuation 方法族; 11 — 让 WorkflowLedger 成为唯一 Workflow persistence owner.

**Status:** ready-for-agent

- [ ] `ResearchWorkflow.handle` 唯一拥有 run、lease、checkpoint、retry、cancel 与 transition policy；`ResearchExecution.execute` 只执行被选定节点及研究门禁，不自行改变 workflow lifecycle。
- [ ] `WorkflowInspection.inspect` 与 Forecast Review 是独立 task/query seams；public registry、permission helper、retry/heartbeat helper、getter forwarding 与 workflow direct SQL 已删除。
- [ ] 新运行只使用 `research-workflow@2`；migration preflight 对任一 queued/running workflow 返回 `MIGRATION_WORKFLOW_NOT_TERMINAL`，要求在旧 code identity 下先 resume/cancel。
- [ ] completed workflow version 1 历史保持 read-only，failed/cancelled 历史只可 inspection；新 runtime 不执行 legacy definition，不修改旧 definition hash。
- [ ] `ResearchDecisionViewBuilder.build(ResearchDecisionInput)` 是唯一 builder；每个成功 workflow 恰好持久化一次 typed `ResearchDecisionView@2` 与 HTML projection。
- [ ] workspace、archive、HTML 和 workbook 只加载已持久化 DecisionView bytes；Mapping overload、schema-prefix guessing、renderer-side research/valuation recomputation、重复 validation 与 JavaScript report semantics 已删除。
- [ ] 每个成功或受限成功 WorkflowRun 拥有一个 immutable `workflow_decision_view@1` manifest，成员角色精确为 `decision_view_json` 与 `decision_view_html`，并由唯一 `decision_view_manifest` reference 指向。
- [ ] 每个 ResearchRun record 严格指回唯一 source JSON/HTML；匹配使用 exact run identity 与 engine schema，零个或多个候选返回 `RESEARCH_SOURCE_ARTIFACT_NOT_UNIQUE` 并回滚全部 migration。
- [ ] 已有合法 DecisionView 可严格验证后复用；只有 frozen typed DataSnapshot、Forecast 与 Valuation graph 完整时才能按 `ResearchDecisionViewMaterialization@1` 一次性 materialize，缺失输入使整次 cutover fail closed。
- [ ] `ResearchDecisionViewCutover@1` 不新增 SQL schema 或 shadow journal；cutover completeness 由 source-pointer uniqueness 和每个成功 workflow 的唯一完整 decision manifest 共同证明。
- [ ] canonical migration 先确认 server 不活跃且 workflow 全部 terminal，再创建并验证包含 database 与全部 object blobs 的 immutable full backup，取得 data-root writer lock，并在一个 transaction 中提交全部 pointer/ref/manifest 变更。
- [ ] cutover failure只允许留下可审计 orphan object且 database 回滚；retry identity-stable。populated root 未完整 cutover 时以 `RESEARCH_VIEW_CUTOVER_INCOMPLETE` 拒绝 serve/workflow，fresh empty root 视为完成。
- [ ] 旧 immutable objects、旧 final manifests 与旧 references 不改写不删除；`view_id`、`ResearchDecisionView@2` 和既有 artifact bytes identity 不变，runtime 不保留 dual decoder、fallback 或 compatibility view。
- [ ] migration矩阵覆盖 fresh root、empty legacy root、created/reused workflows、共享 ResearchRun、existing-view reuse、materialization、source zero/multiple、queued/running refusal、object/commit faults、exact retry、backup restore、legacy read-only 与 workflow version 2。
- [ ] workflow、recovery、DecisionView、outlook、forecast review、market/valuation simulation、secure workspace、backup/restore 和 Web projection suites 全部通过；workbook adapter为4 passed、0 skipped，Web tests无 semantic duplicate；本票一个 commit完成 vertical cutover。
