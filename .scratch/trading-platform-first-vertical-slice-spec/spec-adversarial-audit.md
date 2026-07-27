# 第一纵向切片 Spec 0.1.0 对抗性审计

Audit date: `2026-07-12 Asia/Shanghai`
Audited artifact: [`spec.md@0.1.0`](spec.md)
Disposition: `gaps found and patched into 0.2.0`

## 结论

0.1.0 的模块边界、PIT 基础、版本化计划、恢复 journal 和最高层验收 seam 成立，但尚不能直接升为实施基线。审计发现 10 个可构造的关键失败路径；它们均可在不增加平台范围的前提下通过 typed contract 和验收门关闭。修改后的 0.2.0 不新增真实账户、执行、回测或平台代码。

## 八视角 findings

| ID | 视角 | 具体反例/失败用例 | 0.1.0 缺口 | 0.2.0 关闭方式 |
|---|---|---|---|---|
| F-01 | 财务/估值 | `financial_fact` 原值为 CNY 千元，assembler 当作 CNY 元；或第三方聚合值被标成 official，从而错误恢复估值权限 | 只说“不复制研究逻辑”，没有约束 snapshot-to-request 的单位、口径、修订、股本/净债务和 capability 等价性 | 增加 purpose-scoped research projection、source/period/scope/unit/currency/restatement checks、权限单调不增与 adapter equivalence AC |
| F-02 | 数据时间 | 用今天的 Security master 计算 2026-07-10 宽度，已退市证券消失、新上市证券提前出现 | MarketSnapshot 没有 PIT universe identity/member schema | 增加不可变 `market_universe_version/member`、listing intervals 和 survivor/leakage sentinel |
| F-03 | 数据时间/市场 | 只抓到少量证券仍计算 `broad/narrow`，或全市场成交额漏行仍给 liquidity 分类 | 没有 universe completeness/metric coverage 门 | 只有 100% universe membership 被解释，且所有非结构性排除成员数据完整时才分类；provider missing/quarantine 不得当结构性排除 |
| F-04 | 量化/复现 | dirty worktree A 与 B 共用同一 Git commit，产生不同规则/报告却记录同一 `code_identity`；不同 JSON 数字/时区编码产生不同 hash | code identity 与 canonicalization 未定义，random seed 未显式 | 增加 commit + dirty diff/tree + lock/migration/frontend hashes、canonicalization version、`random_seed=null/not_applicable` |
| F-05 | 组合/风险 | 用户输入负的最大损失、损失大于计划名义金额、币种不匹配，仍可确认；缺 Position 却显示组合可执行 | 只说 exact CNY 与 N/A，没有确认时领域不变量 | 增加非负、币种、损失不大于名义金额、期限/review 校验；明确不证明组合可行性，Position 规则必须 N/A/unknown |
| F-06 | 软件/运维 | restore bundle 含 `../`、绝对路径、NTFS reparse point 或 symlink，覆盖 data root 外文件；object path 与 hash 不匹配 | 有 hash 和新 root，但没有安全解包/路径 containment | 增加 canonical containment、拒绝绝对/上跳/链接/reparse、hash-derived object path 和 restore 攻击测试 |
| F-07 | 安全/Web | 恶意网页向 `127.0.0.1` 发 mutation，DNS rebinding 绕过 loopback；annotation/source title 注入脚本 | 只有 loopback/no external network，缺 Host/Origin/CSRF/CSP/escaping | 增加随机本地会话凭据、Host/Origin allowlist、CSRF、无 GET mutation、SameSite/HttpOnly、CSP、自有静态资源和 XSS tests |
| F-08 | 安全/许可 | npm/Python 依赖未固定或遗漏 NOTICE；真实 fixture 无再分发权却被提交 Git/备份共享 | 只有 KLineChart integrity 和 terms profile，没有全依赖/fixture 分发门 | 增加 lock/inventory/THIRD_PARTY_NOTICES/no telemetry 与 fixture `storage/replay/redistribution` 权利三分 |
| F-09 | Codex/工作流 | 7 月 10 日 workflow snapshot 因新增 OHLCV 变化；模糊 cache key 既可能错误重跑，也可能把 7 月 10 日输入冒充 7 月 7 日 ResearchRun | 未区分 workflow/market snapshot 与 research-purpose snapshot/fingerprint | 增加 `research_input_policy@1`、purpose-scoped DataSnapshot、记录候选/排除成员；复用不组装伪新请求，历史同时保留两个 snapshot |
| F-10 | 后见之明 | 迟到公告或官方更正到达后，历史页用当前 source policy 重算旧 run；用户修改 rationale 后旧评估解释随之变化 | 数据/计划版本大体不可变，但 projection/as-recorded contract 不完整 | 历史只读取冻结 refs、canonical artifacts、当时 policy/reason/operands；late data 新建并列 snapshot/run/evaluation，不回写旧解释 |

## 长期 Prompt 边界审计

- 当前 checkout 已有完整 MVP audit、四个固定提交上游源码审查、估值方法论、Provider/PIT、图表/许可和本地存储/恢复专题研究；不是 README-only。
- 缺少统一 `docs/open-source-research.md` 是文档门缺口，已用现有第一手资产建立总表。
- Qlib/Lean/vectorbt/PyPortfolioOpt/Riskfolio/yfinance 未完成固定版本深审；它们不进入第一切片，状态必须是 `not_assessed / not_approved`。未来策略/组合切片前必须另起 research effort。
- 总任务 Prompt 的持仓会计和完整回测测试与本切片的 Watchlist/no-account/no-execution 用户故事冲突时，不伪造实现：acceptance evidence 必须记录 `not_applicable`、理由与 `long_term_platform_complete=false`。既有确定性估值公式回归和新增 adapter 单位/权限测试仍是本切片阻断门。

## 关闭门

0.2.0 必须新增或加强：research projection、PIT universe、市场覆盖、canonical/code identity、风险输入、Web/path 安全、依赖/fixture 许可、Codex Skill、as-recorded history 与 applicability ledger。所有新增 AC 必须连续编号、可分层执行，并进入 acceptance evidence manifest。

关闭验证映射：F-01 -> AC-039；F-09 -> AC-040；F-02 -> AC-041；F-03 -> AC-042；F-05 -> AC-043；F-04 -> AC-044；F-07 -> AC-045；F-08 -> AC-046/AC-051；F-06 -> AC-047；Codex 入口补强 -> AC-048；F-10 -> AC-049；长期强制测试适用性 -> AC-050。Spec 0.2.0 共 AC-001—AC-051，连续且无重复。
