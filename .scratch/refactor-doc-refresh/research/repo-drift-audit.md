# EquityTrack live HEAD 与 Phase 1 重构方案漂移审计

审计日期：2026-08-23

审计基线：`main @ 7d043873fad616fa00cc325d558c3500b36ba444`（`feat: unify research evidence and data paths`）

审计性质：只读仓库审计；未运行测试、未启动外部数据源、未修改 `docs/refactor/`。本文件是唯一审计输出。

工作树边界：审计开始时 `docs/refactor/` 已是用户未跟踪内容；审计过程中 `.scratch/refactor-doc-refresh/` 由本轮文档工作创建。两者均不得被清理、重置或广泛暂存。

## 1. 结论先行

1. **当前仓库不是“尚未形成平台的报告 MVP”，而是已经实现但边界过宽的本地交易纪律平台。** 它已有唯一 Skill 入口、正式应用命令信封、SQLite/对象存储、PIT 证据、账户快照、风险政策、复杂计划图、人工复核、任务/执行日志、纪律复盘、Web 读写工作台和研究发布链。Phase 1 应收缩这些能力并迁移权威，而不是在旁边重新搭一套骨架。
2. **Phase 1 的产品收缩方向正确，迁移拓扑错误。** 文档提出“新命名空间并行构建”“独立命令/数据命名空间”“可回滚开关”（`.scratch/refactor-doc-refresh/source-phase1.md:241,482-488`），直接违反仓库的“一条规范路径、禁止并行实现/兼容层、显式单向迁移并删除旧运行时”规则（`AGENTS.md:18-21,31-35`），也违反“不复制为平行系统”的长期基线（`AGENTS.md:8-11`）。`src/equitytrack_v2/ + V1 frozen` 不能作为实施结构落地。
3. **五个内部工作流、七个 V2 对象和金融 Bench 均是目标态，不是当前能力。** 对 `src/`、`tests/` 的精确标识符扫描中，`EvidenceSnapshot`、`InvestmentCase`、`ValuationCase`、`DecisionCard`、`DecisionReview`、`LESSON_CANDIDATE`、`VALIDATED_PLAYBOOK_RULE`、`INSUFFICIENT_EVIDENCE` 均为 0；仓库也没有 `bench/`。现有对象只能作为迁移输入，不能在文档中写成 V2 已实现。
4. **当前研究链确实是隐藏的巨型原子任务。** `ResearchWorkflow` 表面只有 `evaluate_research` 与 `publish_run_manifest` 两个节点（`src/trading_platform/workflows/research.py:66-107`），但一次 evaluation 会同时计算 Forecast、情景估值、估值路由、估值模拟、近期趋势与市场路径（`src/trading_platform/research/bundle.py:75-185`），并在同一 checkpoint 生成 JSON、HTML、PDF 与 workbook（`src/trading_platform/workflows/research.py:410-525`）。当前没有“研究成功后由用户显式进入估值”的运行时门。
5. **现有风险、确认和历史能力值得保留，但 V2 所声称的硬风险闭环尚不存在。** 当前风险政策对十个阈值做确定性校验和顺序约束（`src/trading_platform/domain/risk_policies.py:21-125`）；然而计划编译器只用 NAV 乘单证券/单计划阈值，超限时写入 `requires_review`，并不按文档公式拒绝计划（`src/trading_platform/application/plan_compiler.py:517-545,593-652`）。`W_max = min(...)`、压力损失、流动性/相关性约束汇总必须新实现并由硬门验收。
6. **数据权威存在必须先解决的当前矛盾。** 根规则仍规定 Tushare 为主要结构化源、Kimi 只可作控制面辅助且不得成为业务运行时依赖（`AGENTS.md:71-83`）；live runtime 却把 Kimi agent-gw 设为第一优先结构化 Provider，并绑定 Wind/iFinD 路由（`src/trading_platform/provider_config.py:79-180,218-249`），Skill 数据源表也宣称业务运行时只走 Kimi（`skills/references/data-source-map.md:1-11`）。Phase 1 又写 Fuyao/Kimi `EvidenceProvider`，但仓库中 Fuyao 为 0 命中。实施前必须一次性统一 AGENTS、Prompt、Skill、runtime 与 provenance，不能在 V2 再增加一层万能 Provider 包装。
7. **DSH/DeepSeek Harness 在当前仓库完全不存在。** 对 `src/`、`skills/`、`tests/`、`migrations/`、`pyproject.toml`、`README.md` 搜索 `DSH`、`deepseek-harness`、`Cordis`、`@equitytrack/dsh-plugin` 为 0 命中。Phase 2 必须被描述成后续适配，不得在 Phase 1 架构图中暗示已有 seam 已验证。

## 2. 证据等级与盘点方法

本审计使用以下互斥状态：

- **implemented**：生产代码已由 composition root 接线，存在正式入口/持久化或测试使用。
- **specified-only**：只存在于 DOCX、Prompt、Skill 说明或 `.scratch` ticket，没有 live runtime 权威路径。
- **prototype-only**：仅位于 `.scratch/**/prototypes` 或独立实验，不是生产路径。
- **absent**：代码、测试、迁移和活动文档均无对应实现。
- **obsolete / retirement candidate**：当前仍可能运行，但与收缩后的 V2 主链冲突；应冻结、单向迁移后从活动路径删除，不能被当成新实现范式。

静态盘点命令包括 `git status --short --branch`、`git rev-parse HEAD`、`rg --files`、`rg -n`、按目录类/数据类统计、SQL migration 扫描和 DOCX 文本结构抽取。静态规模结果：

| 项目 | live HEAD 结果 | 说明 |
|---|---:|---|
| 仓库文件 | 395 | `rg --files`，不含被忽略文件 |
| Python 源文件 / 行数 | 154 / 68,830 | `src/**/*.py` |
| `trading_platform.domain` | 27 文件 / 12,656 行 / 199 类 / 136 dataclass | 对象面已经很宽 |
| `trading_platform.application` | 36 / 8,479 / 198 / 136 | 应用任务与命令对象很多 |
| `trading_platform.persistence` | 27 / 13,433 | `workflow_ledger.py` 2,300 行、`plans.py` 2,072 行 |
| `equity_research` | 25 / 19,532 / 141 / 107 | 金融计算仍是大实现面 |
| 最大合同文件 | 3,016 行 | `src/equity_research/scenario_valuation/contracts.py` |
| SQL migrations | 25（0001—0025） | `README` 仍写 0001—0024，已漂移；0025 已被 runner 特判（`src/trading_platform/persistence/migration.py:128,145-146`） |
| migration 历史 CREATE TABLE | 141 次 / 125 个唯一表名 | 是迁移历史统计，不是当前最终 schema 表数 |
| 测试文件 / 静态 test 函数 | 93 / 563 | 只是库存；本审计未执行，不能据此声称当前通过 |

高复杂度热点与 Phase 1 判断一致：`scenario_valuation/contracts.py` 3,016 行、`workflow_ledger.py` 2,300 行、`persistence/plans.py` 2,072 行、`simulation.py` 1,483 行、`application/plan_compiler.py` 1,374 行、`artifact_lineage.py` 1,248 行、`domain/plans.py` 996 行。问题不是缺少模块，而是太多业务知识与发布治理被一个用户任务同时要求理解。

## 3. 当前实际调用链

### 3.1 入口与应用层：implemented，但不是五个 V2 workflow

- `skills/SKILL.md` 已是唯一公开入口，并公开账户查看、状态更新、周期复盘、股票研究、计划创建、计划更新六类任务（`skills/SKILL.md:2-46`）；它还规定正常回答隐藏 CLI、内部 ID、hash、manifest，并把计划检查压成三种用户语言（`skills/SKILL.md:48-66`）。这是可复用的产品入口和呈现原则。
- 当前股票研究任务明确要求 Forecast、stress/base/improvement 情景、估值路由、模拟门、趋势和 JSON/HTML/PDF/workbook 发布；文档还承认完整 assumption dossier 与 WACC surface 尚不是 fail-closed runtime 门（`skills/tasks/equity-research.md:3-11`）。因此“当前研究已是独立 InvestmentCase”不成立。
- `ApplicationCommandEnvelope@1` 有 **21** 个有限 mutation command：账户 4、风险政策 1、计划 4、图表 1、人工复核 1、任务 2、执行记录 2、纪律复盘 2、计划影响 1、计划变更提案 3（`src/trading_platform/application/command_envelope.py:73-95`）；dispatcher 明确将同一集合标为 implemented（`src/trading_platform/application/commands.py:115-160`）。
- CLI 是维护/适配入口，不是五技能接口：它包含 bootstrap/doctor/migrate/health、backup/restore、research/archive、application-command、sync/serve/acceptance、账户导入等大批子命令（`src/trading_platform/cli.py:53-157`）。Phase 1 不应新增第二个 `equitytrack_v2` CLI；应在现有应用任务 seam 上逐任务替换调用者。
- Web 不是 README 所暗示的只读查看器。它允许 14 种本地 mutation command（`src/trading_platform/application/web_command_policy.py:14-44`），`POST /api/application-commands` 会授权并 dispatch 正式命令（`src/trading_platform/web_server.py:102-146`）。Phase 1 应冻结 Web 扩张，而不是依据错误的“只读”假设设计迁移。

### 3.2 研究与估值：implemented as one bundle；V2 separation absent

当前真实链为：

```text
Skill / CLI
  -> ResearchWorkflowRequest@2
  -> frozen SnapshotEvidence + ResearchAnalysisPlan@1
  -> ResearchEvaluation(ResearchEngine)
  -> ResearchBundleAssembler
       -> Forecast
       -> scenario valuation
       -> valuation method route
       -> valuation simulation decision
       -> recent trend
       -> market path decision
  -> ResearchDecisionView@2
  -> JSON + HTML + PDF + workbook checkpoint
  -> publication 再生成 report JSON/HTML/PDF/workbook/price chart
```

证据：

- analysis plan 的封闭节点图包含 evidence、research core、forecast、scenario valuation、valuation route、simulation、trend、market path 和 decision projection（`src/trading_platform/research/analysis_plan.py:35-157`）。所谓 `required/supporting` 只是节点属性（`src/trading_platform/research/analysis_plan.py:281-315`），并未阻止 bundle assembler 执行这些组件。
- `ResearchDecisionView@2` 已有 `valuation_view`、风险收益、数据质量、不确定性、what-would-change、驱动、情景和 market-implied expectations（`src/trading_platform/research_view.py:13-44`），是 V2 `InvestmentCase` 的重要迁移来源；但它仍带 valuation/simulation/market-path artifact IDs，且没有一等 `antithesis`、`base_rates`、可观察 `falsifiers` 合同，不能直接改名充当新对象。
- `InvestmentThesisVersion@1` 已保存 claims、drivers、risks、invalidation tests、evidence manifest 与 research run IDs（`src/trading_platform/domain/strategies.py:24-65`），但它属于策略目录域，未成为 research task 的单一输出。V2 需要把语义完整迁到一个权威 InvestmentCase，而不是再写一个同步副本。
- publication 应用任务无条件发布 report JSON/HTML/PDF/workbook/price chart（`src/trading_platform/application/research_publication.py:156-202`）。因此 Phase 1 所说“renderer 不参与任务成功”是目标态，不是当前事实。
- `ArtifactLineage` 是无 I/O 的不可变 typed graph validator，但单类 1,248 行并强制 DataSnapshot、Forecast/Valuation/Simulation/MarketPath 父链（`src/trading_platform/domain/artifact_lineage.py:131-212,459-742`）。应保留 PIT/身份/不可变校验知识，替换“所有产物同图完成”的接口。

### 3.3 计划、风险与监控：implemented complex model；有限 FSM absent

- 当前计划主对象的 lifecycle 只有 `inactive/active/ended`，草稿是 `open/rejected/discarded/confirmed`（`src/trading_platform/domain/plans.py:215-334`），不是 Phase 1 的 `DRAFT/ACTIVE/REVIEW_REQUIRED/SUPERSEDED/CLOSED` 聚合状态。
- 已确认 `TradePlanVersion` 固定 `plan-rule-ast@2`、graph seal、risk policy/version、确认 receipt；规则包含 scope、priority、candidate intent 与递归 `RuleAstV2`（`src/trading_platform/domain/plans.py:466-577`; `src/trading_platform/domain/rules.py:288-325`）；图还包含 sleeves、rules、evidence 和 adjusted-price evidence（`src/trading_platform/domain/plans.py:619-709`）。这是 Phase 1 明确要退出的复杂模型。
- 用户公开计划起草目前只接受 `existing_position_review`，自动选择最新完整研究和账户，把整个持仓设为 core floor，并固定使用 `trend_hold_break_exit`（`src/trading_platform/application/plan_drafting.py:25-103`）。它不是通用 `DecisionCard -> finite triggers`，也没有可选 ValuationCase。
- 当前人工复核结果是四态：`NO_CHANGE`、`MONITOR`、`REVIEW_REQUIRED`、`DRAFT_UPDATE_PROPOSED`（`src/trading_platform/domain/manual_review.py:17-21`）；Phase 1 的 `INSUFFICIENT_EVIDENCE` 三态尚未实现。复核 item 同时携带 sleeve graph、rule routing、conflict resolution、plan impact 与 proposal IDs（`src/trading_platform/domain/manual_review.py:137-170`），说明监控仍绑定旧图模型。
- 可复用的是“未确认不激活、精确 digest challenge、活动计划唯一、不可变版本、触发只产生任务/提案”的治理知识；应替换 AST、sleeve、strategy catalog 和四态复核合同。

### 3.4 账户、组合与复盘：账户强，组合/DecisionReview 不完整

- 账户快照已把 cash/nav/fees 与持仓字段建模为 known/unknown，且草稿、确认版本、correction、graph seal 和 capability 都是不可变合同（`src/trading_platform/domain/account_snapshots.py:27-126`）。这是 V2 最强的可复用资产之一。
- `EstimatedAccountState` 会从确认快照和 execution records 确定性折叠，并保留 blocking/unverified/drift（`src/trading_platform/domain/account_state.py:47-106`）。
- 目前没有一个等价于 V2 `PortfolioSnapshot` 的权威对象。历史 `portfolio_snapshot` 表只有 cash、market value、total equity、reconciliation 与 limitations（`migrations/0009_account_opening_state.sql:9`）；账户状态、组合 workspace、风险政策和持仓暴露分散在不同对象/投影。exposures、concentration、realized/unrealized PnL、benchmark state 不能写成已统一实现。
- discipline review 明确只构建证据分类，**不做 behavioral scoring**（`src/trading_platform/domain/discipline_reviews.py:229-230`），主要归集 unrecorded/overridden/skipped/deferred/unverified（`src/trading_platform/domain/discipline_reviews.py:251-386`）。它没有 process vs outcome、收益归因、counterfactual、固定错误分类或 lesson lifecycle。
- `ForecastReviewEngine` 已实现 Brier score、数值误差、区间覆盖和 driver decomposition，并明确“单次复核不证明模型有效”（`src/equity_research/forecast_review.py:240-370,678-703`）；应用包装也可写入 research artifact（`src/trading_platform/application/research_tasks.py:76-108`）。但 production composition、CLI 和 Skill 没有暴露这个任务，而且它强依赖 forecast + valuation + simulation 三个父 artifact。应复用计算规则，重做 V2 review task 合同，不能声称 DecisionReview 已就绪。

### 3.5 持久化与投影：implemented and mature；不能另建第二真值

- 25 次 migration 已覆盖 raw/normalized/PIT snapshot、workflow/artifact、chart、plan/rule/evaluation、account snapshot/history、strategy/manual review/task/journal、discipline review、plan impact/proposal 和 risk policy。关键表可见 `migrations/0001_core_identity_objects.sql:32-33`、`0002_provider_normalized_snapshot.sql:107-131`、`0003_workflow_research_manifest.sql:1-60`、`0015_account_snapshot_version.sql:1-128`、`0016_strategy_plan_model_b.sql:110-379`、`0017_manual_review_journal.sql:1-199`、`0019_portfolio_risk_policy.sql:1`。
- 读取模型已覆盖 portfolio、holding、trade plan detail、review、research index、chart、account editor（`src/trading_platform/application/read_models.py:21-157`）。Phase 1 的 Markdown 只应成为这些规范对象的一个新投影 adapter；不能创建第二 presentation model 与旧模型长期并存。
- 当前 composition root 已分别装配 research、application commands、manual review、decision tasks/journal、discipline review、plan impact、read models、market、accounts、strategies 等正式任务（`src/trading_platform/application/bootstrap.py:253-632`）。它是迁移 seam；不要恢复已删除的聚合 facade，也不要让 V2 adapter 直连 repository。

## 4. V2 目标与 live HEAD 漂移矩阵

| Phase 1 目标 | 当前状态 | 证据与真实差距 | 文档应怎样改 |
|---|---|---|---|
| 一个公开入口 | **implemented** | `skills/SKILL.md` 已是唯一入口，但有六类用户任务，不是五内部 workflow | 保留入口；把五工作流写成迁移目标，不写成已存在目录 |
| 五个内部 Skill/workflow | **specified-only** | `research-case`、`valuation-case`、`plan-case`、`monitor-plan`、`review-decision` 无 runtime 对象或 direct application operations | 先定义五个任务级深模块的接口和验收，再逐任务替换当前调用链；不要创建五个只转发的浅包装 |
| 七个核心对象 | **specified-only / absent identifiers** | exact 类型均不存在；相近语义分散在 SnapshotEvidence、ResearchDecisionView、InvestmentThesisVersion、TradePlanGraph、AccountSnapshot/State、DisciplineReview/ForecastReview | 增加“旧对象 -> 新权威 -> 退役对象”的逐字段单向迁移表，不得笼统写“适配” |
| 研究与估值显式分离 | **absent** | bundle assembler 总会产生 forecast/valuation route/simulation/trend/path；workflow 同 checkpoint 发布所有产物 | 先切出 `research_case` 完整成功点，再把 valuation 变成独立命令；同时修改 plan drafting 对完整 ResearchDecisionView 的依赖 |
| 反向估值优先 | **specified-only** | 现有 routing/valuation 很强，但没有一个用户显式触发的 `ValuationCase` 任务，也没有默认 reverse-implied-expectation 门 | 将现有确定性公式放入一个估值深模块，先实现 method applicability + implied expectations；禁用不适用方法要成为正式结果 |
| 有限六触发器 + 简单 FSM | **absent** | 当前是 recursive AST v2 + core/grid sleeves + strategy catalog + conflict policy | 需要 schema migration、活动计划转换、旧 evaluator 删除；不能在新触发器外再保留 AST fallback |
| 硬风险 `W_max` | **absent / partial prerequisites implemented** | 有风险阈值与确定性校验，但无 stress-loss/min constraint calculator；当前超限仅 `requires_review` | 明确输入可用性、unknown 语义、每一约束来源与 BLOCKED 规则；G3 必须验证不能绕过 |
| 三态增量 monitor | **specified-only** | 当前 ReviewOutcome 四态且绑定完整 graph；Skill 的三种自然语言只是一层呈现 | 领域合同改成 `NO_CHANGE/REVIEW_REQUIRED/INSUFFICIENT_EVIDENCE`，用调用跟踪证明不执行完整 research/valuation |
| DecisionReview 过程/结果分离 | **absent** | discipline review 不评分且无收益归因；forecast review 有校准但不在产品入口 | 合并规则知识而非对象包装；新增 outcome attribution、fixed error taxonomy、lesson candidate + 人工晋升 |
| EvidenceProvider (Fuyao/Kimi) | **partially implemented but authority-conflicted** | live Kimi + CNINFO/SZSE provider；Fuyao 0；AGENTS 仍要求 Tushare primary | 先做权威 ADR/规则切换；复用现有 `DataProvider`/SourcePolicy seam，只有真实变化需要时才引入新 port |
| JSON + Markdown，其他 renderer 可选 | **specified-only target** | JSON 已有；HTML/PDF/workbook/chart 仍是研究和 publication 强路径 | 改成功条件、checkpoint schema 与测试；renderer 从任务结果移出，但历史 artifact 保留审计可读性 |
| 20 个冻结金融 Bench 案例 | **absent** | 无 `bench/`；现有 93 测试和 35 项 acceptance 主要验证软件合同，fixture 明示 synthetic-only 且固定 20 步（`tests/fixtures/trading_discipline_kernel/expected-manifest.json:1-30`; `src/trading_platform/acceptance.py:91-126,232-262,397-476`） | 不得把现有 acceptance 冒充金融 Bench；可把它们作为 G0—G4 的回归种子，另建 G5 corpus |
| DSH adapter/runtime | **absent** | repo-wide 0 命中 | Phase 1 只固定 runner-neutral JSON contract；Phase 2 再验证 DSH 版本/API/session/workspace 语义 |

## 5. `.scratch` 与 README：只能作为历史证据，不能当 live truth

- 根规则明确 `.scratch/trading-platform-first-vertical-slice-spec/` 只是 Wayfinder 决策记录，不授权平台实现（`AGENTS.md:8-11`）。
- `.scratch/trading-platform-first-vertical-slice-spec/prototypes/chart-annotation-prototype/` 是唯一明确的 prototype-only 目录；其结论已部分被正式 Web/chart 实现吸收，不能再作为 V2 UI 基础。
- `.scratch/portfolio-aware-weekly-discipline/map.md` 仍是 `Status: open`，且自称“只消除决策 fog，不实施平台”（`:1-17`）；其“账户手工声明、计划草稿、组合日终、复盘仍缺失”的旧描述已被后续账户/计划/纪律实现部分超越，必须按 live code 重写或归档。
- `.scratch/kimi-datasource-unification/map.md` 说 issue 03 未认领（`:23-25`），而 live code 已完全绑定 Kimi runtime；`skills/references/data-source-map.md:33-35` 又说切换尚未落地。tracker、Skill 与 code 三者漂移。
- `README.md` 一方面列出复杂 AST/core-grid 和 discipline kernel 为完成能力，另一方面把 Web 描述为只读、把 migrations 写到 0024；Phase 1 切换时必须和 Skill、tests、runtime 同单元更新，不能让 README 继续充当第二套产品事实。

## 6. 复用、替换、冻结/删除映射

### 6.1 直接保留或作为新深模块实现来源

| 现有资产 | 决策 | 理由 / 新 seam |
|---|---|---|
| `SourcePolicy`、PIT `published_at/available_at/retrieved_at`、snapshot membership、unknown/blocked semantics | **保留** | 是 EvidenceSnapshot 验证器的核心不变量，不应重写成 prompt |
| `AccountSnapshotVersion`、estimated state/drift、用户确认 | **保留并收敛** | 作为 PortfolioSnapshot 的账户真值输入；不要复制账户表 |
| `PortfolioRiskPolicyService` | **保留并深化** | 在同一模块内增加可复算的 hard sizing/risk result；不要另建只转发 `RiskServiceV2` |
| canonical hash、幂等 invocation、confirmation challenge/receipt、不可变版本 | **保留** | 新对象和状态转换必须继承这些安全资产 |
| Forecast/valuation 的 Decimal 计算、行业 applicability、equity bridge、Brier/误差公式 | **通过窄任务接口复用实现** | `equity_research` 继续是实现，不是第二应用入口（`AGENTS.md:40-46`） |
| `ResearchDecisionView@2` 的不确定性、market implied expectations 与默认金融输出边界 | **字段级迁移来源** | 迁入 InvestmentCase/ValuationCase；旧 view 不再作为两类对象的共享真值 |
| SQLite transaction、migration ledger、backup/recovery、object digest | **保留** | 已满足本地单用户需要；无证据支持新建事件存储或第二数据库 |
| read-model progressive disclosure 与正常用户隐藏内部细节 | **保留原则** | Markdown/UI 都从同一新对象投影 |

### 6.2 必须替换，不应再包一层兼容适配器

| 当前模块/合同 | 替换目标 | 原因 |
|---|---|---|
| `ResearchWorkflow` + `ResearchBundleAssembler` + mandatory artifact checkpoint | `research_case` 与显式 `valuation_case` 两个任务级深模块 | 当前任务耦合过高；简单 adapter 仍会执行旧全链 |
| `ResearchDecisionView@2` 作为研究+估值+趋势+模拟混合权威 | 独立 `InvestmentCase@1`、`ValuationCase@1` | 对象必须可独立成功、失败、保存、重放 |
| `TradePlanGraph` / `RuleAstV2` / sleeve graph / strategy-specific compiler | finite `TradePlan@1` + six trigger types + FSM | V2 主链明确不需要通用表达力 |
| `ManualPortfolioReview` 四态与 graph routing | `monitor_plan` 三态结果 + deterministic delta comparator | 增量监控不能继续依赖旧图、冲突策略和全量 research |
| `DisciplineReviewVersion` + 非入口 ForecastReview | `DecisionReview@1` | 必须把过程、结果、归因、校准和经验候选放在一个可证伪复盘合同中 |
| Kimi/Tushare/Fuyao 冲突文档和 runtime | 单一、诚实、版本化 source policy | 先做权威决策，再改所有调用者；禁止并存 fallback |

### 6.3 冻结后从活动运行时删除的候选

以下不是立刻物理删除历史数据，而是**停止扩展 -> 用新合同迁移活动状态/调用者 -> 删除退役运行时代码和测试 -> 保留不可变历史材料**：

- 默认 valuation simulation、market path simulation、复杂 Monte Carlo 输入图；
- core/grid sleeves、recursive plan AST、通用 strategy catalog 与 conflict policy；
- 研究成功所必需的 PDF、workbook、HTML、price-chart 生成；
- Skill 中强制六图/完整报告布局和可能绕过正式 application path 的旧图表脚本；
- Phase 1 的 Web/K 线新页面、市场状态引擎、回测/策略市场扩张；
- 已被正式应用路径替代的 `.scratch` prototype 和过时 tracker 状态。

旧计划 graph、artifact 与确认记录不能被丢失，但也不能成为 runtime compatibility 的理由。正确做法是：对活动/可变状态做版本化单向迁移；把旧内容作为不可变审计 blob 保留；切换全部调用者；同一变更删除旧 evaluator/renderer/写路径。若无法证明转换安全，迁移必须 BLOCKED，而不是增加 `if v1 else v2`。

## 7. Phase 1 DOCX 必须纠正的具体结论

1. **删除“V1 冻结 + V2 并行命名空间”与 `src/equitytrack_v2/` 方案。** 改成“在现有 `trading_platform.application` 任务 seam 上逐能力替换；一个任务只有一个写路径；每个切换包含 schema migration、调用者/测试/文档切换和旧 runtime 删除”。Phase 1 当前第 6、12 节与 `AGENTS.md` 直接冲突。
2. **删除“V1 模块桥接”“独立命令/数据命名空间”“可回滚开关”字样。** 一个只做字段重包装的 V1 bridge 是被禁止的胶水；运行时 rollback/dual reader 是兼容层。回滚能力应来自 Git/备份与前置 migration backup，而不是活动代码分支。
3. **把七对象/五工作流全部标为 target contracts，补上逐对象 cutover 表。** 尤其说明 `SnapshotEvidence/DataSnapshot -> EvidenceSnapshot`、`ResearchDecisionView + InvestmentThesisVersion -> InvestmentCase`、research components -> `ValuationCase`、graph plan -> finite `TradePlan`、AccountSnapshot/State -> `PortfolioSnapshot`、Discipline+Forecast Review -> `DecisionReview` 的字段来源、丢弃字段、迁移门和旧对象删除点。
4. **将“风险由确定性代码执行”区分为 current asset 与 missing hard gate。** 当前有 policy validation，没有文档公式、correlation/liquidity/stress-loss 汇总，也没有“越界不能生成有效计划”。这些应成为 M3 交付，不能出现在 2.1“已具备资产”中而不加限定。
5. **把研究完成条件的当前事实写清楚。** 现在 valuation/simulation/trend/market path/artifacts 强耦合；显式估值是重大 breaking change，不是增加一个 workflow markdown。必须同时重构 persistence checkpoint、artifact lineage、publication、plan drafting 和相关 tests。
6. **修正监控与复盘现状。** Skill 呈现虽已有三种中性语句，领域仍是四态；discipline review 不做行为评分、收益归因和错误分类。ForecastReview 只是可复用计算模块且不在正式产品入口。
7. **统一数据源权威再定义 EvidenceProvider。** 文档不能同时说 Fuyao/Kimi 可替换、AGENTS 说 Tushare primary、runtime/Skill 说 Kimi-only。Fuyao 是未来适配器，不是当前资产。已有 `DataProvider + SourcePolicy` 是真实 seam；除非新合同能隐藏重大规范化行为并至少有生产/测试 adapter，否则不要增加同义 port。
8. **将 Bench 完成门从“至少 12 个”恢复为原始要求的 20 个冻结案例。** 12 个可以是 M2/M3 的早期门，但 Phase 1 完成定义应是 20 个；并明确现有 synthetic acceptance 不等于金融 G5。至少覆盖用户列出的 10 基础类型与 8 类对抗案例，其余补组合/复盘边界。
9. **修正 Web、migration、provider 与 tracker 的已知文档漂移。** Web 有正式写能力；live migration 是 0025；Kimi 已进入 runtime；`.scratch` ticket 状态并非实施权威。最终 Markdown 必须只把 live code 事实写成“当前”。
10. **M0 增加真实保护基线。** 当前 HEAD 没有任何 tag 指向它；文档写“V1 tag”只是未来动作。M0 必须先创建经授权的冻结 tag/commit、记录 public task 旅程和持久化 schema，再进入切换。
11. **把长期总 Prompt 作为必须同步变更的产品权威。** 它仍要求 K 线、回测、Monte Carlo、完整市场状态、大量实体与 artifact manifest（`docs/prompts/trading_platform_codex_prompt_optimized.md:148-323`），并将旧纵向切片定义为报告+K线+计划+市场评估（`:5-18`）。Phase 1 的产品收缩若不同时修订该权威文件，将从第一天制造冲突。
12. **不要把 DSH 进入条件写成“连续两个合同版本无 breaking change”而不说明谁验证。** Phase 1 应交付 runner-neutral contract tests、replay corpus 和 version lock；Phase 2 再验证 DSH plugin/session/workspace，DSH 不拥有业务真值。

## 8. 迁移风险与必须提前封闭的断点

| 风险 | 为什么高风险 | 必须的迁移证据 |
|---|---|---|
| 计划 AST/graph 已持久化并参与 hash、seal、confirmation receipt | 直接改 schema 会让历史确认失真；保留双读又违反兼容禁令 | 活动计划 inventory；每个转换的 old/new digest receipt；迁移前备份；旧 evaluator 删除测试 |
| plan drafting 依赖完整 `ResearchDecisionView` 和 recent trend | research/valuation 拆开后当前计划入口会立即失效 | 新 DecisionCard 输入合同与计划 task E2E 先就绪，再切旧 drafting |
| ForecastReview 强依赖 valuation/simulation parent artifacts | valuation 变可选后当前 review 无法复用 | 新 review 输入允许 absent/not-run，并用明确 comparability/limited 语义 |
| artifact lineage 与 workflow ledger 绑定整套 typed graph | 仅把 renderer 标成 optional 不会解除 persistence 强耦合 | 新 checkpoint schema；已有 DB upgrade；重放/恢复/幂等验证；退役 artifact graph 写路径删除 |
| provider authority 冲突 | provenance、许可、PIT 与生产可用性都会漂移 | 单一 ADR；AGENTS/Prompt/Skill/runtime/job fixtures 同变更；实网验证单独记录，不能用 fixture 冒充 |
| 账户/组合字段分散 | 新 PortfolioSnapshot 容易成为第二真值或伪造历史收益 | 明确账户事实 vs 确定性派生；unknown 不补零；只从确认快照/执行记录派生 |
| Web、Skill、CLI、tests 都是现有调用者 | 只切一个入口会留下旁路 | superseded symbol/command/schema/fixture/docs 全仓搜索为 0；所有调用者穿同一 application seam |
| 当前无 V1 tag，工作树有用户未跟踪 DOCX | 基线不可重现且容易误包含用户文件 | 经用户授权后精确 tag/commit；只暂存明确路径；不触碰 `docs/refactor` 原件 |

## 9. 建议写入 Phase 1 的验收基线

### 9.1 权威与迁移门

- `AGENTS.md`、长期 Prompt、`skills/SKILL.md`、README、runtime 与 tests 对产品边界和 provider 权威无矛盾。
- 一个任务只有一个正式 application operation、一个持久化 owner、一个 presentation model；仓库不存在 V1/V2 runtime switch、dual write、dual read、legacy fallback 或第二 CLI。
- 每次替换均附 one-way migration、现有数据库升级 fixture、迁移前备份、调用者切换、退役 symbol/依赖清理。

### 9.2 20 个金融案例与六级门

- Phase 1 完成需要 **20 个** frozen cases；12 个只可作为中期里程碑。
- G0—G3 任一失败即案例失败；G4 重放/恢复达到全量；G5 用明确 rubric 与人工校核，不以文本相似度评分。
- 硬指标：重大无来源断言 0、PIT 泄漏 0、单位/币种/期间错误 0、风险越界激活 0、未确认状态变化 0、自动订单 0。
- 数据不足、来源冲突、方法不适用、计划过期和无可比较结果必须生成稳定 typed result，而不是异常或伪精确输出。

### 9.3 任务级完成门

- `research_case` 在不运行 valuation/simulation/market path/PDF/workbook 的情况下独立成功或正式 DATA_INSUFFICIENT，并有 antithesis、可观察 falsifiers、market-implied expectations 与 evidence refs。
- `valuation_case` 只能在显式命令后运行；每个方法输出 READY/LIMITED/DISABLED/NOT_RUN，确定性数值可复算。
- `plan_case` 通过 hard risk result 才能产生可确认草稿；确认精确绑定 ID/version/digest；一个账户/证券只有一个活动计划。
- `monitor_plan` 的调用跟踪证明不调用全量 ResearchWorkflow/valuation engine；结果只为三态之一，触发只创建复核事项。
- `review_decision` 分开保存 process/outcome，能计算 attribution/adherence/calibration，固定 error class，并且只产生 LESSON_CANDIDATE。

### 9.4 工程回归门

- 现有 93 个测试文件必须通过正式 `trading-platform test` 或新的唯一验证入口；报告精确给出通过/失败/跳过/超时。当前审计没有执行测试，不能把 563 个静态测试函数当成绿色基线。
- 空库 bootstrap、0001—0025 已有库升级、代表性现有账户/计划/研究历史升级、重复执行、故障恢复和备份恢复全部通过。
- 确定性字段在相同 frozen input 下完全相同；模型差异只能影响契约明确允许的叙述字段。
- 所有 renderer 都可缺失而不影响业务成功；若启用 renderer，其内容只能从规范对象生成。

## 10. 推荐的 Phase 1 切换顺序（与当前仓库约束一致）

1. **M0：统一权威。** 修订长期 Prompt/AGENTS/Skill/README 的产品与 provider 冲突；冻结 live HEAD、记录真实旅程；建立 20-case contract，不写实现骨架。
2. **M1：先切 ResearchCase。** 在现有 `trading_platform.application` 中建立一个拥有完整行为的任务级 interface；把现有证据/PIT 与研究叙述字段迁入 InvestmentCase；修改 checkpoint 使研究无需估值/renderer 即成功；切调用者并删除旧混合 research task。
3. **M2：显式 ValuationCase。** 复用确定性估值实现，建立独立状态/持久化；更新 plan 输入；从研究默认路径删除 valuation/simulation。
4. **M3：风险、DecisionCard 与有限 TradePlan。** 先实现 hard risk result；库存现有活动计划；单向迁移；切换 Skill/Web/CLI/tests；删除 AST/sleeve/strategy evaluator 活动路径。
5. **M4：增量 Monitor 与 DecisionReview。** 迁移四态 manual review 和 discipline/forecast review；保证只消费 delta；加入 attribution/error/lesson candidate。
6. **M5：投影与清理。** Markdown 从同一规范对象生成；PDF/HTML/workbook/chart 变可选；清理旧 Skill 模块、renderer、schema、tests、依赖和 `.scratch` prototype。
7. **M6：20-case 发布门。** G0—G5、迁移、恢复、端到端与用户入口全部有证据后，才允许 Phase 2 锁定 DSH 版本并写薄 adapter。

这一路径不是“大爆炸”，也不是并行 V2。每一步都在既有 seam 上让一个完整用户任务获得新的唯一权威，然后删除被替代的运行时路径，符合当前仓库的深模块与单向迁移规则。

## 11. 最终审计判定

Phase 1 DOCX 对产品问题的诊断大体准确，对当前实现的复杂度也抓住了主因；真正需要重写的是**实施架构和“现状/目标态”措辞**。当前文档若直接执行，最可能形成 `equitytrack_v2`、V1 bridge、独立 CLI/DB、rollback switch 与两套测试/renderer——恰好复制本轮要消除的复杂度，并违反项目最高优先级规则。

可执行的 Phase 1 必须把以下一句作为工程总约束：

> 在现有正式 application seam 上，按研究、估值、计划、监控、复盘逐任务建立新的唯一权威；每次切换都完成单向数据迁移、全部调用者切换、旧运行时删除与 Bench 验收，不建立平行 V2、兼容层或第二真值。
