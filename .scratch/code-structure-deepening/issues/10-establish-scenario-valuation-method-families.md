# 10 — 建立 canonical Scenario Valuation 方法族

**What to build:** 让研究运行通过唯一 `ScenarioValuationEngine.run` 完成 Scenario Set、Valuation Basis、方法路由、确定性估值与同方法跨场景汇总。industrial、cyclical、financial-institution 与 biopharma 各自由完整方法族拥有行业经济学；全部调用者和测试迁入公开 engine contract，旧 scenario monolith、root aliases、私有计算 seam 与重复 valuation policy 在本票内删除。

**Blocked by:** 09 — 建立 canonical Forecast contract 与 GraphIdentity@2.

**Status:** resolved

- [x] `ScenarioValuationEngine.run` 成为唯一对外 scenario-valuation 操作，并直接消费 canonical Forecast contract，而不是旧 Forecast 内部结构。
- [x] Scenario Set 完整拥有场景定义、概率、假设覆盖、可比性和同方法跨场景聚合规则；概率不一致或不可比场景以 typed failure/disabled reason 失败关闭。
- [x] Valuation Basis 完整拥有方法选择、适用性、Forecast binding、币种、会计口径、peer gates、净债务/稀释/equity bridge 和 source-quality 边界。
- [x] industrial、cyclical、financial-institution 与 biopharma 方法族分别完整拥有其确定性计算与行业约束，不以转发 wrapper 或共享条件分派器重新制造单体模块。
- [x] 普通 FCFF/WACC DCF 不用于金融机构；biopharma 使用 rNPV/SOTP 与 cash runway；cyclical/resource 使用 mid-cycle/NAV；peer 数量和来源门禁保持 fail-closed。
- [x] 只允许同一适用方法在不同 Scenario 间按概率聚合；跨方法 probability-weighted target、无来源关键输入和不适用方法不得产生 valuation conclusion。
- [x] 所有正式调用者、canonical imports 与 public-engine tests 已迁移；旧 scenario 单体、root aliases、私有 projection/discount/helper tests、重复 router 与 renderer-side calculation 已删除并搜索清零。
- [x] 公开行为矩阵覆盖四个方法族、Scenario probability、Forecast binding、currency/accounting/peer/source gates、equity bridge、sensitivity、determinism、disabled methods 与 typed failures。
- [x] 研究语言字段、data-insufficient degradation 和非投资建议边界保持不变；缺失官方关键证据时不输出目标价、rating 或概率加权目标。
- [x] 受影响的 scenario valuation、router、ResearchEngine、outlook、market-path、simulation 与 report-boundary suites 全部通过；本票作为一个 commit 完成 contract 替换和旧实现删除。

## Resolution evidence

- Canonical package: `scenario_valuation/{contracts,basis,industrial,cyclical,financial_institution,biopharma,engine}.py`; `ScenarioValuationEngine.run` builds at most one cyclical reference Forecast plus one Forecast per scenario, binds each through `ValuationBasis`, and returns the unchanged typed result/serialization contract.
- Ownership: Engine owns the scenario partition, probability evidence, method-order comparability, same-method weighting and no-composite rule; Basis owns Forecast/timing/quantity/equity-bridge semantics; each industry family owns its calculations, applicability and typed projections/ledgers. Industrial owns DCF/relative gate replay, including WACC, PIT/source/accounting, minimum-sample and percentile verification.
- Cleanup: deleted the 8,009-line `src/equity_research/scenario.py`, removed 37 root aliases, migrated platform/test imports, and verified zero retired `scenario` imports, `_financial_projections`, `_financial_from_forecast`, old `_discount_times`, compatibility branches, cross-module private builders, and family-local `ForecastEngine` calls.
- Focused gate: `python -m pytest -q tests/test_scenario_valuation.py tests/platform/test_outlook_artifacts.py tests/platform/test_company_outlook_journeys.py` -> `80 passed in 84.76s`.
- Static/compile gates: `python -m pyflakes src/equity_research/scenario_valuation tests/test_scenario_valuation.py`, `python -m compileall -q src/equity_research/scenario_valuation`, and the canonical package seam/dependency test passed.
- Full project gate: `python -m trading_platform.cli test --repo-root .` -> all named Python and Web suites passed in `94.079s`; core `188 passed`, platform-1 `29 passed, 3 skipped`, platform-2 `62 passed, 1 deselected`, platform-3 `50 passed`; skipped/deselected checks were reported, not converted to passes.
- Independent review loop: Ticket 10 Spec review PASS and Standards review PASS after three rounds; final review found no remaining ownership, construction-seam, routing, serialization, cleanup or test-boundary findings.
