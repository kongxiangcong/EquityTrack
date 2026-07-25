# 15 — I04 ResearchEvaluation、Request@2、migration 0014 与 canonical PDF

**What to build:** 让研究用户只用 immutable ResearchWorkflowRequest@2 引用 Security、frozen DataSnapshot 与 ResearchEvaluationPlan，由唯一 ResearchWorkflow 管理lifecycle、concrete ResearchEvaluation执行source/PIT/quality、Forecast、ScenarioValuation、ValuationSimulation与publication policy，并由WorkflowLedger原子持久化artifacts和一个ResearchDecisionView@2 manifest。JSON、HTML、PDF、XLSX、Web与archive只投影该view。0014在完整backup后把安全旧历史变为read-only plan audit record并删除active projection、Request@1 decoder和research-view cutover runtime；三个超大owner先完成有行为意义的深化，不能增加forwarder、mirror port或第二persistence path。

**Blocked by:** 13 — I02 A股 OfficialDisclosure vertical slice 与 migration 0013（resolved）。

**Status:** resolved

Issue 14 已完成 A股-only scope migration，不建设 SEC/美股/港股 runtime，因此不再构成本票依赖。Vibe-Trading 不接入、不安装、不配置；StrategyValidation unavailable 不阻断本票的 ResearchEvaluation、交易计划或 presentation 主流程。

## Public seam first

- [x] 先在ResearchWorkflow和public CLI/Web application tasks写失败测试：只接受Request@2 snapshot refs + ResearchEvaluationPlan；Request@1、ResearchProjection、free mappings、caller artifacts/manifest/estimates/classification均被拒绝。
- [x] ResearchWorkflow保持唯一run/lease/checkpoint/retry/cancel/transition owner；ResearchEvaluation是concrete local deep module，不新增port或plugin registry。
- [x] ResearchEvaluation只通过existing WorkflowLedgerPort typed query加载frozen evidence；不依赖concrete persistence、raw SQL、object store或caller payload。
- [x] method router、official-source/PIT/quality、financial output和publication gates保留最终否决权；StrategyValidation unavailable不产生result/artifact/route/config。
- [x] research/valuation执行前后AccountSnapshot、TradePlan、PlanEvaluation、authorization与order state保持不变。

## Mandatory deepening before added behavior

- [x] 记录 `domain.workflow` 当前职责审计，并抽出拥有ResearchEvaluationPlan、research artifact canonicalization、invariants、fingerprints与typed factories的完整domain behavior；不是contracts-only或forwarding module。
- [x] 记录 `workflows.research` 当前职责审计，并把source/PIT/quality、Forecast/Valuation/Simulation/publication orchestration完整交给ResearchEvaluation；workflow只保留lifecycle/checkpoint policy。
- [x] 记录 `persistence.workflow_ledger` 当前职责审计，并抽出私有、事务完整的research artifact commit behavior；WorkflowLedgerPort仍是唯一public persistence owner，不新增镜像repository或method-for-method delegate。
- [x] 删除行为从旧owner完全移出；deletion test证明新module拥有不可复制的领域、事务或protocol depth，无helpers/common/utils/mixins/forwarder。

## Migration 0014 and presentation cutover

- [x] 精确实现Spec定义的ResearchEvaluationPlan record、rebuilt ResearchRun record、Request@2 new-write trigger、immutability/no-delete gates，并删除active research_input_projection schema。
- [x] migrate-only Request@1 decoder只在指定migration namespace中由schema<14的MigrationRunner调用；application/CLI/Web/server/recovery不得import。
- [x] preflight拒绝queued/running old workflow、non-unique projection、missing/corrupt artifact、hash/identity mismatch；historical plan只封装existing identity/audit artifact，不解释free facts。
- [x] migration backup-first、single transaction、fault rollback、new-root restore、identity-stable retry；migration后没有Request@1 runtime decode/resume/replay/fallback/cutover reader。
- [x] 每个成功或受限成功workflow恰好产生一个View@2 manifest；JSON/HTML/PDF/XLSX/Web/archive从persisted view投影且不重算research/valuation semantics。
- [x] PDF是deterministic local projection，绑定view/schema/media/content hash并通过page/render检查；不得使用upstream raw PDF作为正式报告或数值来源。若新增renderer dependency，先资格化、pin并更新NOTICE/lock。

## Caller migration and deletion

- [x] CLI/daily/browser/workflow/recovery/workspace/archive/presentation、tests、fixtures、Skill/current docs与generated Web assets全部原子迁入Request@2/View@2 path。
- [x] 删除Request@1、ResearchProjection、free ResearchInputs、caller manifest/estimates/member classification/analysis artifacts、serialized draft decoder、ResearchRunner fake variation、research-view cutover/materializer/runtime gates/faults/tests和old presentation readers。
- [x] public-interface tests建立后删除retired private-seam tests；search证明active runtime/current docs/generated assets无旧symbol或parallel renderer/persistence hit。

## Acceptance and verification

- [x] narrow command通过：`python -m pytest -q tests/test_forecast_graph.py tests/test_research_engine.py tests/platform/test_research_workflow.py tests/platform/test_workflow_ledger.py tests/platform/test_workflow_ledger_recovery.py tests/platform/test_company_outlook_journeys.py tests/platform/test_decision_research_view.py tests/platform/test_web_application_tasks.py tests/platform/test_valuation_workbook_adapter.py tests/platform/test_research_decision_pdf.py`。
- [x] 0014 fresh/prior/populated/active-workflow/fault/rollback/restore matrix和Request@1/cutover/free-mapping/caller-artifact absence gates通过。
- [x] full phase gate通过：`python -m trading_platform.cli test --repo-root .`。
- [x] `web`目录执行`npm test`与`npm run build`，并通过production bootstrap/local HTTP/real CDP browser verifier；验证reload/restart/security/keyboard/narrow viewport/reduced motion与hashed dist assets。
- [x] PDF MIME/schema/hash/page/render一致性和workbook reconciliation通过；所有required check无skip/timeout。
- [x] `git diff --check`、完整status/diff/staged diff和code review无未处理finding。

## Commit scope

- [x] 一个local commit包含deep-module extractions、Request@2/Plan/ResearchEvaluation、0014、all callers、View@2 PDF/presentation、tests/docs/assets、旧runtime/schema删除和本票evidence。
- [x] 精确stage本票owning paths；不提交data roots、browser runtime artifacts、personal/provider data、secrets、gateway参数、`docs/data/**`、external checkout或unrelated dirty；不push/PR。

## Resolution evidence

- Narrow suite: 91 passed; workbook suite rerun with bundled runtime: 4 passed, no skip.
- Full pytest: 406 passed, 1 intentionally deselected by repository policy, no skip or timeout.
- Canonical phase gate: passed in 115.574s; all named suites passed.
- Web: 18 tests passed; Vite production build passed.
- Browser: `production-browser-cdp@1` / `BrowserAcceptanceEvidence@1` passed with reload, restart, keyboard, responsive, reduced-motion and security-header evidence in `research/issue15-browser-evidence.json`.
- PDF: deterministic two-page ReportLab projection rendered through Poppler; workbook formula scan/reconciliation and six-sheet visual QA passed.
