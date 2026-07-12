# 11 — 生成验收证据并分类生产资格

**What to build:** 在全新 data root 上通过生产 composition root 完成固定纵向旅程和所有反例，生成不可变、机器可读的验收证据。fixture-backed slice acceptance 与生产 Provider live qualification 分开裁决；任何外部凭据、许可或网络阻塞都精确标记，而不会把 fixture 成功冒充生产就绪或长期平台完成。

**Blocked by:** 10 — 完成 Windows 运维、备份恢复与统一 Skill.

**Status:** resolved

- [x] 分层 suite 覆盖 domain、Provider contract、persistence/migration、application journey、fault/recovery、browser、Windows maintenance、architecture/security 和 legacy regression。
- [x] AC-001 至 AC-051 的本地确定性阻断项全部实际执行；本切片范围内没有 skip/xfail，任何失败使 `slice_acceptance=failed`。
- [x] acceptance applicability ledger 对总任务强制测试逐项记录 passed、failed、not_applicable 或 external_blocked 及理由；Position 会计和完整交易回测等非目标有反能力测试且不伪造实现。（AC-050）
- [x] machine-readable evidence manifest 记录 Spec、workflow/node/evaluator/model/policy/canonicalization 版本，code/config/environment/fixture hashes，suite 结果，golden entities，determinism，全部 artifact refs 和 final manifest identity。（AC-038）
- [x] golden journey 的 doctor、browser、backup/restore、legacy regression、research equivalence、fixture rights 和 applicability evidence 都由 hash 引用，不使用静态截图、直接 DB seed、手工复制或自然语言声明替代执行证据。
- [x] 同一固定时钟和 fixture 在新 data root 重跑产生等价 canonical identities；dirty source、policy、fixture 或依赖变化会改变相应身份且阻止错误复用。（AC-044）
- [x] fixture member 权利 profile 逐项验证；未获再分发授权的 raw 不进入 Git 或发布包，分发资格可以 external_blocked 而本机 replay acceptance 仍独立裁决。（AC-051）
- [x] 配置允许时，生产 Provider 通过同一合同执行独立 live qualification；结果严格分类为 qualified、external_blocked 或 failed，并保留真实网关身份、来源权威边界、terms 和 attempts。
- [x] `slice_acceptance` 只代表 fixture-backed 第一纵向切片；manifest 始终记录 `long_term_platform_complete=false`，不把未评估策略、组合、账户或多市场能力描述为完成。
- [x] 最终验收证明整个旅程没有业务 LLM/prompt、交易执行副作用、明文 secret、个人绝对路径泄漏或个性化投资建议输出。

## Implementation Evidence

- `trading-platform acceptance` executes a fixed nine-layer pytest/Node JUnit plan; callers cannot submit suite, criterion, fixture or live-qualification verdicts. Every AC maps to one or more required executed assertion IDs, and skip/xfail/failure/missing assertions fail closed.
- The authoritative golden journey uses one fresh data root and only `PlatformOperations` plus public facade commands/queries: 2026-07-07 research creation, restart, 2026-07-11 sync with effective 2026-07-10, outer-workflow reuse of the same research snapshot/JSON/HTML identities with `ROUTINE_MARKET_ONLY_INPUTS` and three-day staleness, annotation, user-input plan, market/evaluation, restart, history/manifest/workspace/detail queries and doctor.
- `GoldenJourneyEvidence@1` records original and outer WorkflowRun IDs, frozen/reused research and artifact refs, downstream entity refs, final manifest identity, dispositions, reason and staleness. The runner validates this typed record instead of scanning SQLite.
- Committed derived-fact fixture members are loaded by the fixture Provider and verified against trusted-root relative paths, JSON payloads, hashes, source/rights/terms profiles. Raw gateway redistribution remains separately `external_blocked`.
- Acceptance evidence is canonical, content-addressed, atomically published and read-only; post-write verification checks hash/schema/51 criteria/permissions. A stable `acceptance_identity` excludes volatile run timing while binding code/config/lock/migration/workflow/frontend/fixture/policy/test identities.
- Live qualification is runner-owned and currently `external_blocked` because no trusted production live-qualification adapter/entitlement runner is configured; a caller cannot upgrade it to qualified. `slice_acceptance=passed` remains fixture-only and `long_term_platform_complete=false`.
- Final controlled acceptance passed with manifest SHA-256 `b7d74f4ee8c195d84a4ff6efb567078cb47ca92f632563c203ac5c1753627ada`. Final full regression passed: Python 159, frontend 8, production build, compileall and `git diff --check`.
- Independent review from fixed point `c35facd`: Standards PASS and Spec PASS after all valid findings were fixed and reverified.
