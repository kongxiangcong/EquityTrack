# 16 — I05 回写 portfolio-aware weekly-discipline 当前规划

**What to build:** 让仍开放的portfolio-aware weekly-discipline规划准确引用已经实现并验证的新canonical architecture：MarketRegime数据、持仓研究门控、每周驾驶舱、计划/指标合同、真实旅程验收和最终implementation Spec应使用新的SourcePolicy、official evidence、ResearchEvaluationPlan、ResearchDecisionView与capability-unavailable StrategyValidation边界。只回写当前规划，不重开已resolved账户快照/日终合同，不顺手实现新产品功能。

**Blocked by:** 15 — I04 ResearchEvaluation、Request@2、migration 0014 与 canonical PDF.

**Status:** resolved

## Exact planning surface

- [x] 重新完整审计portfolio-aware weekly-discipline Map、所有开放tickets与本Goal最终实现证据。
- [x] 只更新以下六张开放ticket：MarketRegime v2数据资格、持仓研究与条件估值门控、任务优先的每周纪律驾驶舱、计划编制与指标目录、真实每周纪律旅程最高层验收、综合implementation-ready Spec。
- [x] 每张票引用实际存在的application/DataProvider/WorkflowLedger/ResearchWorkflow/View@2 seams、schema versions、failure states与production acceptance；不得把future design写成current implementation。
- [x] StrategyValidation维持capability-unavailable且不进入第一版组合纪律产品；不得添加backtest、broker、order、自动交易或盘中做T范围。
- [x] 已resolved账户快照与日终执行窗口tickets内容和status保持byte-for-byte不变，除非有直接新证据推翻事实；本票预期无此证据。
- [x] portfolio Map只更新受影响frontier/context pointer，保持真实blocked edges；不复制adoption Spec或重写resolved history。

## Acceptance and verification

- [x] exact-path diff只包含六张开放tickets、必要的portfolio Map/context pointer以及本票status/evidence；任何额外portfolio文件变化使本票失败。
- [x] validator证明六张票的canonical seam、SourcePolicy/official evidence、ResearchEvaluationPlan/View@2、StrategyValidation unavailable与acceptance references相互一致且链接有效。
- [x] validator证明resolved账户/日终files hash与本票前baseline完全一致。
- [x] adoption implementation final evidence与planning statement逐项核对；未验证能力只能写blocked/unavailable，不能写done。
- [x] `git diff --check`、relative-link check、status/diff/staged diff和code review无未处理finding。

## Commit scope

- [x] 一个local planning commit只包含上述六张开放tickets、必要Map pointer与本票status/evidence；不含production code、未授权产品实现或其他planning efforts。
- [x] 精确stage允许路径；禁止`git add .`、`git add -A`，不提交startup dirty、personal/provider data、secrets、gateway参数、`docs/data/**`或external checkout；不push/PR。

## Goal-level handoff after this ticket

- [ ] I05关闭后不创建cleanup ticket；直接执行Goal final gates：full canonical verification、live qualification receipts、Vibe rejected-runtime evidence复核、Web/browser/PDF/workbook、migration/restore、license/NOTICE、final code review、forbidden-symbol/asset/dependency searches与dirty preservation。
- [x] 只有Goal Prompt全部完成条件由current evidence证明后才允许将Goal标记complete。

## Resolution evidence

- Exact planning surface: portfolio Map plus issues 05, 06, 07, 08, 11 and 12; no other portfolio file was edited or staged.
- Canonical-reference validator: all six tickets name application, `DataProvider`, `WorkflowLedger`, `ResearchWorkflow`, `SourcePolicy@1`, official evidence, `ResearchEvaluationPlan@1`, `ResearchDecisionView@2`, nonblocking `StrategyValidation` `requested_unavailable`, and production acceptance; all relative links resolve.
- Protected resolved-file SHA-256 values before and after the backwrite:
  - issue 02: `AAD15096D4E5965DFADED171C4185824E379DB212FB50456AF2290477FB93E8D`
  - issue 03: `13F65989A6BF88BD3572882E36A3E2A561D75267F3AFDE75771645C04A4EB13B`
- Adoption evidence reconciliation used resolved Issues 13-15 and current production symbols. Future portfolio capabilities remain explicitly future/blocked/unavailable; no product runtime, schema, dependency, generated asset or user data changed.
- `git diff --check`, exact-path, relative-link, canonical-reference, protected-hash and staged-diff checks passed. Independent Standards and Spec reviews initially found five substantive and two follow-up issues; all were fixed, and both final re-reviews passed with no remaining finding.
