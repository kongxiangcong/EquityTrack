# 09 — 建立 canonical Forecast contract 与 GraphIdentity@2

**What to build:** 让研究运行通过唯一 `ForecastEngine.build` 完成所有受支持证券 archetype 的确定性 Forecast，并由明确的 evidence、driver graph 与制造业三表行为所有者维护内部规则。全部正式调用者和测试迁入该 contract；新 graph identity 能区分不同 archetype 语义，既有不可变 Forecast 历史仍可审计，但旧 monolith、公开别名、私有 helper seam 与兼容分支在本票内删除。

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] `ForecastEngine.build` 成为唯一对外 Forecast 操作，输入输出、确定性、typed failure 与金融输出边界保持稳定。
- [x] `ForecastEvidence` 完整拥有 fact、assumption、evidence normalization 与 source-quality 规则；调用者不再重复分类或补默认值。
- [x] `ForecastGraph` 完整拥有 driver graph 构造、代数、不变量、序列化与 identity；调用者不再拼装 graph 或直接调用 graph 私有方法。
- [x] `ManufacturingForecast` 完整拥有制造业销量、产能、利用率、ASP、成本、营运资本、资本开支、三表勾稽与现金流推演，不形成转发 shell。
- [x] 新 Forecast graph 使用 `ForecastGraphIdentity@2` 与 `fg2_` identity，并证明不同 archetype 或不同 graph 语义不会碰撞、相同规范输入可精确重放。
- [x] 既有 immutable Forecast graph bytes 与 identity 保持不变且可由历史 inspection 读取；新 runtime 不通过旧 decoder、fallback 或再生成来兼容它们。
- [x] 所有 production callers、canonical package imports 与 public-interface tests 已迁移；旧单体实现、root aliases、直接私有 helper tests 和重复 exports 已删除并搜索清零。
- [x] 公开行为矩阵覆盖全部受支持 archetype、evidence/assumption 分类、driver graph invariants、制造业三表 reconciliation、determinism、tamper、identity collision 与 typed failures。
- [x] 依赖检查证明 Forecast domain 不导入 CLI、Web、presentation 或 concrete persistence，且没有新增 forwarding module、speculative port、feature flag 或 old/new comparison path。
- [x] 受影响的 Forecast、ResearchEngine、outlook、market-path、valuation-simulation 与 runtime-boundary suites 全部通过；本票作为一个 commit 同时包含 caller migration、旧路径删除与测试替换。

## Implementation Evidence

- Canonical operation: production callers now import `ForecastEngine` and contracts from `equity_research.forecast`; root aliases and the 3,093-line `forecast.py` monolith were deleted.
- Deep owners: `ForecastEvidence` owns request/evidence validation, `ForecastGraphCompiler` compiles minimal declarations and exclusively materializes nodes/edges plus monitoring policy, and `ManufacturingForecast` owns manufacturing drivers and three-statement projection.
- Identity: all six supported archetypes produce `ForecastGraphIdentity@2` `fg2_` IDs; tests cover deterministic replay, semantic changes, financial/biopharma routing, and pairwise archetype uniqueness.
- Historical audit: `tests/fixtures/legacy_forecast_graph_fg1.json` is a committed immutable byte fixture with its original `fg_` identity; inspection reads and canonical-round-trips it without a legacy decoder, fallback, or regeneration path.
- Static boundaries: runtime tests reject retired root aliases, forbidden outward dependencies/runtime branches, and cross-module underscore imports inside the Forecast package.
- Focused verification: `python -m pytest -q tests/test_forecast_graph.py tests/platform/test_outlook_artifacts.py tests/platform/test_runtime_skeleton.py` — 54 passed.
- Canonical verification: `python -m trading_platform.cli test --repo-root .` — core 186 passed; platform shards 32 + 51 + 53 + 65 passed; 3 skipped; 1 deselected; Web 18 passed; overall status passed.
- Independent review: Spec PASS and Standards PASS after the final declaration/compiler and package-boundary hardening.
