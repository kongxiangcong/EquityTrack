# Goal Prompt：按依赖顺序完成代码结构深模块改造 09–14

在 `E:\workspace\tradingSystem` 中持续实施
`.scratch/code-structure-deepening/spec.md` 与下列锁定的 implementation issues，直到
09–14 全部按依赖顺序完成、验证、review、独立提交并标记为 `resolved`：

1. `09-establish-canonical-forecast-contract.md`
2. `10-establish-scenario-valuation-method-families.md`
3. `11-make-workflow-ledger-sole-persistence-owner.md`
4. `12-cut-over-research-workflow-and-decision-view.md`
5. `13-cut-over-cli-application-tasks.md`
6. `14-cut-over-web-tasks-and-remove-facade.md`

本 Goal 授权完成这些既有票据声明的生产代码、测试、一次性 migration、文档、生成资产、
验证与本地 Git commit；不授权扩大产品范围、创建新功能、push、开 PR、清理无关改动或修改
个人金融数据。

## 锁定的依赖图与执行顺序

依赖图为：

```text
09 -> 10
11
09 + 10 + 11 -> 12 -> 13 -> 14
```

每轮都必须从 tracker 当前状态重新计算 frontier。可执行票据必须是
`ready-for-agent`、其全部 `Blocked by` 已 `resolved`，且没有被其他会话认领。若同时有多个
frontier，严格按编号选择最小者。因此在当前初始状态下，预期执行顺序是
`09 -> 10 -> 11 -> 12 -> 13 -> 14`。不得因为 11 初始无 blocker 而跳过编号更小的 09 或 10。

01–08 是已完成的 Wayfinder 决策历史，只能读取，不能重新 claim、改写或当作 implementation
票据。不得新增、合并、拆分或重新编号 09–14；若实施证据证明现有票据边界本身无法安全成立，
记录精确 blocker 并停止，不得用兼容层绕过，也不得自行创建第 15 张票。

## Goal 首次启动的 tracker baseline

1. 从仓库根目录工作，先执行只读检查：当前 branch、`git status --short`、`git diff`、
   `git diff --cached`、当前 `HEAD`。把启动时已有的 modified/deleted/untracked 项目视为用户改动，
   不得覆盖、清理或顺手提交。
2. 当前 `.scratch/code-structure-deepening/` 可能仍整体 untracked。若 map、spec、01–14 issues 与
   本 Goal prompt 尚未 tracked，则在任何生产实现前，先逐文件检查其内容，只将
   `.scratch/code-structure-deepening/` 这一 effort 的规划资产加入一个独立的
   `chore: record code structure deepening plan` baseline commit。该 commit 不得包含生产代码、
   其他 `.scratch/` 目录或启动时已有的任何无关 dirty file。
3. 若这些规划资产已经 tracked，或已有等价 baseline commit，则跳过该步骤。不得 amend、rebase、
   reset 或重写既有 commit。
4. baseline commit 只用于锁定任务源，不算完成任何 implementation issue；09 仍须另有自己的
   implementation commit。

## 每次 Goal 续轮的固定流程

1. 完整读取当前 `AGENTS.md`、
   `docs/prompts/trading_platform_codex_prompt_optimized.md`、
   `docs/agents/issue-tracker.md`、`docs/agents/triage-labels.md`、`CONTEXT.md`、
   `.scratch/code-structure-deepening/spec.md`，以及 `implement`、`tdd`、`code-review` skills。
   读取当前票涉及的 ADR；不存在时静默继续。直接适用的仓库规则和票据 acceptance criteria
   高于本提示词中的一般建议。
2. 只读取 09–14 每个文件的标题、`Blocked by` 与 `Status` 来计算 frontier。若存在一个
   `claimed` 票据，先结合工作树 diff、测试证据和票据内容判断它是否是本 Goal 上一续轮中断的
   当前票；证据一致时恢复该票，不另选新票。若它属于并发会话或归属无法证明，停止并报告，
   不得双重实施。
3. 选中 frontier 后，在读取其完整实现细节和修改任何生产文件之前，先把
   `**Status:** ready-for-agent` 改为 `**Status:** claimed` 并保存。然后完整读取该票、Spec 中
   相关 contracts、当前公开接口、所有真实 callers、tests、schema/migrations、artifact identities、
   runtime/docs references。
4. 记录本票的 base `HEAD` 和启动 dirty baseline。使用 `rg` 搜索真实调用链和删除面；能从当前
   checkout 查明的事实不得询问用户。不得把旧文档、fixture 或静态代码当成运行可用性的证明。
5. 每次续轮只实施一张票。使用 `/implement` 的流程，以预先约定的最高 public seam 做 TDD：
   先建立失败的目标 contract/acceptance test，再实现最小完整 vertical slice，持续运行窄测试、
   type/compile/static checks，最后运行该票要求的全部 tests 和一次完整项目 verification。
6. 同一票内完成 target interface、全部 production/test caller migration、旧实现/导出/fixture/
   docs/dependency 清理与删除门。禁止把空 package、forwarding class、compatibility alias、old/new
   adapter、feature flag、dual read/write、schema guessing、fallback、service locator、mirror Facade
   或“下一票再删”的旧路径带过 commit 边界。
7. 实施只保护正式平台 observable behavior、领域语义、typed failures、不可变历史、持久化数据、
   security/privacy 和 artifact identity。不得为了保留旧私有 API、旧 file/V3 CLI、重复脚本、旧
   renderer 或私有测试而引入兼容代码。
8. 涉及 migration 时必须遵守 ticket 的 backup-first、terminal-workflow preflight、single-writer、
   atomic transaction、exact replay 与 fail-closed 约束。不得对真实用户 data root 试跑破坏性迁移；
   使用 fresh/temp、fixture 和明确的 populated test root。旧 immutable bytes 是历史证据，不是保留
   旧 runtime decoder 的理由。
9. 每票结束前运行 `/code-review`，固定 review 起点为该票记录的 base `HEAD`，同时检查 Standards
   与 Spec。修复全部有效发现，重跑受影响 tests，并再次 review，直到没有未处理的 actionable
   finding。14 在自身 ticket review 之外，还必须以 09 implementation commit 的 parent 为 fixed
   point 对 09–14 全范围做一次 Standards + Spec 跨票复审；所有有效的跨模块集成发现必须在 14
   关闭前修复、重测并复审。不得用“已有技术债”作为新增违规的理由。
10. 只有该票全部 acceptance criteria 有真实证据时，才把 checkbox 从 `[ ]` 改为 `[x]`，把
    `**Status:** claimed` 改为 `**Status:** resolved`，并在票据末尾追加 `## Implementation Evidence`：
    列明关键目标接口、删除清零结果、migration/identity evidence、exact commands、pass/fail/skip
    counts、timeouts、外部检查状态、生成 artifacts 与 code-review 结论。不得把 skipped、timeout、
    未运行或 external-blocked 写成 pass。
11. 精确暂存本票声明范围内的生产代码、测试、必要文档/生成资产和当前票据文件。逐项检查
    `git diff --cached --name-status` 与 `git diff --cached`，确认没有其他 issue、其他 `.scratch/`
    effort、启动 dirty changes、secret、个人账户数据或 `docs/data/**`。然后为当前票创建一个本地
    commit；commit message 明确引用票号。不得把两张 issue 合并到一个 commit，也不得为同一票
    留下未提交实现尾巴。
12. commit 成功后重新检查 `git status`、当前 `HEAD` 和本票 diff，确认用户原有 dirty changes
    仍被保留且本票没有遗漏。随后结束本轮；让 Goal 自动续轮重新加载规则、tracker 和 frontier。
    不得在同一续轮开始下一票。

## 每票验证最低要求

- 运行票据列出的全部 narrow suites 和静态/删除 gates；测试 public behavior，不直接保护被退休的
  private seam。
- 定期运行 compile/type/static checks；在 commit 前至少运行一次
  `python -m trading_platform.cli test --repo-root .`。记录每个 suite identity、duration、passed、
  failed、skipped、deselected 与 timeout；不得用旧的固定测试数量替代当前 collection 事实。
- Web 受影响时运行 `npm test` 与 `npm run build`。生成的 `web/dist` 必须来自当前 source build，
  并核对 package/lock/license/NOTICE；不得覆盖启动时已有的无关 dist 改动，若发生范围冲突先证明
  ownership，否则停止。
- workbook 受影响时使用 workspace bundled runtime，明确设置 `CODEX_ARTIFACT_NODE` 与
  `CODEX_ARTIFACT_NODE_MODULES`，执行 ticket 要求的 workbook tests；要求 0 skipped 的票不得以环境
  未配置降级通过。
- 真实浏览器、migration/restore、release acceptance 与最终 forbidden-symbol 全量 gate 由 14 强制
  完成；较早票若 acceptance criteria 要求其中某项，也必须在该票执行，不能推迟。
- Provider 或网络不可用只能记录精确 typed `external_blocked`，不能伪造 qualified、引用旧 live
  artifact冒充当前检查，或把结构测试通过解释成真实连通。
- 最终检查必须包含 `git diff --check`、依赖方向/私有 import guard、superseded symbol 搜索、
  `git status` 和完整 staged diff。任何 incomplete、skip、timeout、未 review 或未 commit 都意味着
  当前票仍未完成。

## Git、隐私与工作树边界

- 在当前 branch 创建本地 commits；不得 push、开 PR、切换 branch、merge、rebase、amend、reset、
  clean、stash 或恢复用户文件。
- 一张 implementation issue 对应一个 implementation commit；唯一允许的额外 commit 是首次启动时
  必要的 tracker-baseline commit。
- 只暂存明确属于当前票的文件。不得使用宽泛 `git add .`、`git add -A` 或按目录吞入无关文件；
  必须使用核对后的显式路径。
- `docs/data/**`、本地 data roots、browser evidence中的私密路径、账户/现金/持仓/交易数据、tokens、
  gateway parameters、secrets 与用户提供的原始文件不得暂存、提交、复制到通用 artifacts 或输出。
- 保留本 Goal 启动前已有的 `.gitignore`、`AGENTS.md`、长期 Prompt、Web dist、其他 `.scratch/`、
  `CONTEXT.md`、research docs、provider notes 和所有未声明 dirty changes。只有当前票明确要求且能证明
  ownership 时才可修改重叠文件；无法安全区分时停止并报告具体冲突。
- 不得因为工作树脏而跳过 diff 审计，也不得把无关改动纳入“mandatory cleanup”。清理只覆盖当前票
  使其 obsolete 的 symbols、imports、commands、schemas、fixtures、tests、docs、assets 与 dependencies。

## 自动继续与真实 blocker

- 普通设计选择、代码量大、测试耗时、首次实现失败、review findings 或需要继续调查都不是 blocker；
  继续修复和验证。
- 若当前票发现可在其既有 acceptance scope 内解决的问题，直接处理，不请求用户逐项确认。
- 只有下列情况才停止并报告：需要新的外部权限或用户授权；缺少无法从 repo/fixture/官方来源取得的
  关键事实；真实用户数据会被不可逆修改；旧 artifact 无法唯一归位；running workflow 无法在旧
  code identity 下 drain；声明外 caller 使同票原子替换客观无法成立；或仓库长期约束与票据发生无法
  自行消解的冲突。
- blocker 报告必须包含当前票、已验证事实、exact command/error、受影响 contract、已尝试的安全
  alternatives 与解除 blocker 所需的最小用户动作。不得用 fallback、alias、临时 wrapper、伪造
  evidence 或扩大 scope 绕过。

## Goal 完成条件

只有同时满足以下全部条件，Goal 才能标记为 complete：

- 09–14 六张 implementation issues 均为 `**Status:** resolved`，全部 acceptance checkboxes 为 `[x]`，
  且各自拥有完整 `Implementation Evidence`。
- blocker graph 真实闭合：10 在 09 后完成，12 在 09/10/11 后完成，13 在 12 后完成，14 在 13 后
  完成；不存在错误跳票、并发重复实现或未完成的 `claimed` ticket。
- tracker baseline（如需要）与每张 issue 各有清晰本地 commit；每个 implementation commit只包含一张
  issue 的实现和证据，`git log`、票据状态和工作树能互相核对。
- Forecast、Scenario Valuation、Workflow persistence/lineage、Research Workflow/Execution、canonical
  DecisionView、CLI tasks 与 Web tasks 均只剩 Spec 指定的唯一正式 interface；旧 monolith、repository、
  Facade、ports、entry、renderer、private getters/tests、dual decoder 与 compatibility paths搜索清零。
- 14 的完整 release proof全部通过：静态删除与依赖 gates、完整 Python/Web、workbook 0 skipped、真实
  Chromium、fresh/prior/populated migration+backup+restore、release acceptance、行为/failure矩阵、
  dependency/license/NOTICE/dist、最终文档审计，以及从 09 parent 到 14 working tree 的跨票
  Standards + Spec review。任何 required skip、timeout、未运行、未处理 finding 或 nonzero 都不能关闭
  Goal。
- 正式平台 observable behavior、typed failures、金融输出边界、security/privacy、immutable history、
  ResearchRun source pointers、DecisionView manifests 与 artifact identities 均有当前 evidence。
- 最终 `git status` 中只剩 Goal 启动前的无关用户改动或明确报告的非本 effort文件；不存在本 effort
  未提交代码、未完成迁移、未生成资产或未记录测试证据。
- 未 push、未开 PR、未暂存或提交 `docs/data/**`、个人金融数据、secret 或无关 dirty changes。

完成时只报告：六票完成顺序与 commits、最终验证命令和精确结果、重要 migration/browser artifacts、
仍然明确标为 `external_blocked` 的真实外部资格（如有）、保留下来的用户 dirty changes，以及下一步
由用户决定是否 push 或创建 PR。不要自动 push、创建 PR 或继续扩大范围。
