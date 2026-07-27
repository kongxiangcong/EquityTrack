# 对抗性审计 Spec 并关闭实施前缺口

Type: `task`
Mode: `AFK`
Status: resolved
Blocked by: 12

## Question

综合 Spec 是否逐条满足总任务 Prompt、AGENTS.md、既有 MVP 回归和第一条纵向切片 Destination，并且已经消除进入实现前的所有关键决策？从财务/估值、数据时间、量化前视、组合风险、软件运维、安全许可证、Codex 工作流和后见之明八个视角给出具体反例或失败用例，检查外部研究不是 README-only、许可证和 Provider 数据边界有证据、Windows/本地优先/备份恢复可验收、运行时无 LLM、计划不等于自动下单、数据版本/证据/结果/run 可回看；发现缺口时回写 Spec 或新增精确 ticket，只有没有未决实施前问题时才确认 Destination 已到达。

## Answer

已完成八视角 AFK 对抗性审计并形成独立资产：[第一纵向切片 Spec 0.1.0 对抗性审计](../spec-adversarial-audit.md)。审计没有以“整体合理”代替失败用例，而是构造了 10 个可执行反例，并将全部实施前缺口回写到[第一纵向切片实现级 Spec 0.2.0](../spec.md)。Spec 状态现为 `implementation-ready`，decision gate 为 `adversarial-audit-passed`。

主要关闭项：

- 财务/估值：snapshot-to-request adapter 现在必须保留 source/period/scope/unit/currency/scale/restatement/稀释股本/净债务 identity，并证明 capability/valuation permission 相对既有 core 单调不增；
- 数据时间：新增 purpose-scoped 双 DataSnapshot、`research_input_policy@1`、PIT market universe/member 和 100% 可解释横截面 coverage，消除研究复用歧义与幸存者/缺行偏差；
- 量化/复现：固定 canonicalization、dirty source tree、lock/migration/workflow/frontend/config hashes 和 `random_seed` 适用性；不把首切片 PIT sentinel 冒充完整回测；
- 组合风险：计划金额、币种、期限和 loss/notional 关系在确认时 fail closed；无 Position/account 时不得宣称组合可行性；
- 软件/运维：backup/restore 拒绝绝对路径、上跳、ADS、链接/reparse、hash/path mismatch 和大小炸弹；保留 Windows single-writer、崩溃恢复与新 root 恢复门；
- 安全/许可：补齐 local session、Host/Origin/CSRF/CSP/XSS/主动 HTML 隔离、payload limit、secret adapter、依赖 lock/NOTICE、无遥测，以及 fixture 本地回放和再分发权分离；
- Codex 工作流：统一 Skill 必须可调用九项入口和 resume，业务 wheel/import graph 不含 Skill/prompt/LLM；研究复用不再构造伪新 ResearchRequest；
- 后见之明：迟到公告、重述、rationale 或 evaluator/policy 变化只产生并列新版本，历史按冻结 refs、当时 operands/reason/artifacts 渲染。

总任务 Prompt 的 Phase 1 汇总文件原先缺失，现已基于固定提交源码/测试/CI/许可证、估值一手方法、Provider/图表/存储专题研究建立[开源项目与第一纵向切片技术研究总表](../../../docs/open-source-research.md)。Qlib/Lean/vectorbt/PyPortfolioOpt/Riskfolio/yfinance 没有被伪造为已研究或已拒绝；它们明确为 `not_assessed / not_approved`，不进入第一切片，未来策略/组合切片前必须另起独立 research effort。

验收标准从 38 条扩展为连续无重复的 AC-001—AC-051，新增 adapter 金融等价、双 snapshot、PIT universe/coverage、风险输入、dirty-code identity、Web/restore 攻击、依赖/fixture 许可、统一 Skill、as-recorded history 与 applicability ledger。Position 会计和完整回测因固定 Watchlist/no-account/no-execution 边界只能记录 `not_applicable`，且 acceptance manifest 强制 `long_term_platform_complete=false`；这不会被误报为相关能力已经实现。

验证证据：Spec 57 个、审计资产 1 个、研究总表 14 个 Markdown 链接均可解析且无缺失；AC-001—AC-051 连续唯一；关键合同词全部存在；`python -B -m unittest discover -s tests -v` 当前 35/35 通过。

审计没有留下新的第一切片实施前决策或 fog，因此不新增 Wayfinder ticket，Destination 已到达。这里的“到达”只表示 Spec 可以交给后续实现 effort；当前仍没有实现平台代码、数据库、Provider、正式 Web UI 或纵向切片，也不表示长期总任务已经完成。
