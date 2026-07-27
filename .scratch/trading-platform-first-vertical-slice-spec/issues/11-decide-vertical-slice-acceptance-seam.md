# 决定纵向切片最高层验收 seam

Type: `grilling`
Mode: `HITL`
Status: resolved
Blocked by: 06, 07, 08, 09, 10

## Question

哪一个最高层、最少穿透实现细节的测试 seam 能证明第一条纵向切片真实完成，而不是静态 UI、自然语言报告或空目录？基于已决的数据、运行时、图表和计划接口，定义从标的选择到增量同步、现有投研复用、标注持久化、计划版本创建、引用当日市场状态评估、历史回看的端到端验收，并把 Provider 契约、幂等缓存、断网陈旧度、迁移、计划版本不可变、标注重启恢复、现有 MVP 回归、Windows 备份/恢复和运行时无 LLM 的强制测试安排到最合适的层级。

## Comments

- 第一个 grilling 问题：哪一层是证明纵向切片完成的唯一权威 seam？直接采用推荐答案：以生产 composition root 创建的 `ApplicationFacade` 公共命令/查询序列作为权威语义验收缝；测试只替换 Provider 为同契约的离线 fixture adapter、时钟和 data root，不 mock facade 内部服务。Web、CLI 都是该 seam 的 adapter 验收，不能取代它。
- 第二个 grilling 问题：是否为验收增加一个 `run_vertical_slice_acceptance` 万能生产接口？直接采用推荐答案：不增加。验收驱动器只组合用户和 Codex 实际会调用的公开能力；测试专用编排留在 tests，避免形成绕过真实工作流、持久化或确认点的后门。
- 第三个 grilling 问题：固定验收环境怎样同时可复现又不伪造生产成功？直接采用推荐答案：每次从新的临时 data root 开始，使用锁版本、可离线回放、包含真实可追溯意华股份 raw 数据及来源/许可/时间/hash manifest 的 fixture pack，固定 `Asia/Shanghai` 时钟和请求日 `2026-07-11`，并在进程级禁止网络。fixture 与生产 adapter 走同一个 normalize/quality/PIT/cursor path，但报告只能声称 fixture-backed acceptance，不能冒充 live Provider 同步。
- 第四个 grilling 问题：如何准备 `2026-07-07 ResearchRun` 而不直接向数据库塞结果？直接采用推荐答案：Given 阶段也通过公开 facade 在 `2026-07-07` cutoff 上执行一次真实确定性 workflow，形成 canonical ResearchRun 后重启应用；随后用户旅程的 `2026-07-11` 更新必须复用该原始运行。fixture loader 只提供 raw 响应，不写领域表、不预造 run ID。
- 第五个 grilling 问题：观察项选择怎样进入同一公开 seam？直接采用推荐答案：第一切片必须暴露最小 `add_watchlist_item`、`list_watchlist_items` 和 security workspace/query 能力；验收通过正常命令建立观察项并在重启后查询它，不能把观察项作为隐藏数据库 seed。UI 的“选择”可保持视图状态，但被选 Security identity 必须来自 query facade。
- 第六个 grilling 问题：权威端到端主路径包含哪些不可省略动作？直接采用推荐答案：`bootstrap/migrate -> add/list WatchlistItem -> 7 月 7 日准备 ResearchRun -> 重启 -> 更新至今天 -> 查询同步/研究复用原因 -> 查询 K 线 -> 创建标注 -> 重启并恢复标注 -> 创建草稿 -> 确认并启用 v1 -> 评估 -> 从 history timeline 回看全部引用`；每一步只通过公开 typed command/query，不能直接调 repository、ResearchEngine 内部函数或 SQL。
- 第七个 grilling 问题：最高层断言采用整份 JSON/HTML golden 还是语义不变量？直接采用推荐答案：使用版本化 schema 加小型 semantic assertion ledger，断言身份、日期、状态、关系、不可变 hash、created/reused disposition、reason code、坐标和能力边界；不锁随机 WorkflowRun ID、时间戳、HTML 像素或整份 JSON 字节。内容完整性另由 manifest/hash verifier 与 `doctor` 证明。
- 第八个 grilling 问题：怎样证明研究是真复用而不是把旧报告文案复制到页面？直接采用推荐答案：新 WorkflowRun 必须引用同一个 `ResearchRun` identity、原始 `as_of_date=2026-07-07`、原 DataSnapshot/请求/artifact hashes，journal disposition 为 `reused` 并给稳定 reason code；`2026-07-11` 请求日和 `2026-07-10` 有效交易日只能属于外层 workflow/market evaluation，不能改写研究运行。
- 第九个 grilling 问题：幂等与“每次执行都有历史”如何同时验收？直接采用推荐答案：相同 `invocation_id` 重试返回同一 WorkflowRun；新 invocation 产生新 WorkflowRun/attempt，但复用 raw object、normalized version、DataSnapshot、ResearchRun、MarketSnapshot 和同一评估幂等键的 PlanEvaluation，不推进无变化 cursor、不新增领域版本；journal 必须记录每次 reused/cache-hit 尝试。
- 第十个 grilling 问题：Provider 测试和 live 数据源资格如何区分？直接采用推荐答案：所有 adapters（fixture 与生产）必须通过同一 contract suite，覆盖字段、时间精度、单位/币种、未复权语义、状态、空响应、partial、rate limit、cursor 和 provenance；另设带凭据/权益的 live qualification smoke。live 不可用可记 `external_blocked`，不能跳过为 pass，也不能据 fixture 声称实时同步成功。
- 第十一个 grilling 问题：离线、陈旧和缺失要在什么层验收？直接采用推荐答案：Provider/data contract 测精确 freshness 计算，application integration 用三个独立场景验证合法缓存、stale 缓存和 missing；stale/missing 仍需持久化可解释的受限 WorkflowRun，但不得生成完整当日 MarketSnapshot 或正常 PlanEvaluation，历史查询仍可读取旧结果。
- 第十二个 grilling 问题：迁移怎样避免只测试空库建表？直接采用推荐答案：migration integration suite 同时覆盖空库初始化、锁定的 N-1 fixture DB 升级、重复 migrate、migration hash 漂移、未知未来版本、date-only precision 保留、注入中途失败与 backup-first 回滚；禁止通过删库重建通过测试。
- 第十三个 grilling 问题：标注持久化的完成证据是什么？直接采用推荐答案：application test 断言 v1 创建后关闭并重新创建 facade 仍恢复完全相同的 Security/interval/adjustment/data-snapshot/factor refs、market timestamps 和 exact decimal prices；浏览器测试再覆盖页面刷新与真实 server restart。修改、tombstone、恢复和跨周期/复权无法唯一映射的 fail-closed 属于同层强制反例。
- 第十四个 grilling 问题：计划版本不可变只需断言 v1 存在吗？直接采用推荐答案：必须建立 v1 后创建基于 v1 的 v2 草稿，证明未确认时 daily 仍评估 active v1；确认并启用 v2 后原子切换，v1 canonical content/hash/activation history/旧评估完全不变。直接 UPDATE、删除历史、ended 复活和复权阈值静默重算都必须失败。
- 第十五个 grilling 问题：评估主路径怎样证明没有交易副作用？直接采用推荐答案：断言评估精确引用 active plan version 与 `2026-07-10 MarketSnapshot`，逐规则保存 operands、reason codes 和 evidence refs；命中只形成复核/限制/失效候选。公共 facade/schema/manifest 中不得出现 order、broker、execution 或订单导出结果，重复评估也不得产生计划状态变更。
- 第十六个 grilling 问题：崩溃恢复应该塞进浏览器主路径吗？直接采用推荐答案：不塞进脆弱 UI 测试；在真实 SQLite/object store 的 application fault-injection suite 对 temp write、rename、DB/cursor/node/final-manifest commit 边界注入崩溃，再通过公开 `resume` 验证 attempt 单调、checkpoint 复用、无半 cursor/missing object/重复领域记录。最高层旅程只做一次正常重启恢复。
- 第十七个 grilling 问题：Windows 备份恢复怎样进入完成门？直接采用推荐答案：在受支持 Windows 环境以真实 subprocess 调用统一维护入口，执行 acceptance data root 的 `backup -> restore 到新 root -> doctor -> serve/query history`；逐项验证 SQLite/FK/schema/domain、object/manifest hashes、历史关系和 loopback 行为，且 restore 永不覆盖 live root。模拟 copy 或只看退出码不算通过。
- 第十八个 grilling 问题：Web E2E 的责任边界是什么？直接采用推荐答案：保留一条薄但完整的浏览器旅程，验证 B 画布优先工作台、更新授权、研究复用说明、K 线/标注、计划确认、评估和历史跳转，以及 reload/server restart、blocking banner、键盘焦点、目标窗口宽度、减少动态效果和非颜色单一编码；它通过公开 HTTP/DOM 驱动真实 facade，不直接查 DB，但不重复承担全部故障矩阵。
- 第十九个 grilling 问题：现有 MVP 回归如何证明是复用而不是平行重写？直接采用推荐答案：35 项现有测试必须原样通过；另加一个 platform-to-research adapter integration，验证平台只调用一次 `ResearchEngine.run(ResearchRequest) -> ResearchRun` 公共 seam、canonical run 与独立 CLI 对同输入一致，且 Web/计划/数据库模块没有导入研究内核内部实现。
- 第二十个 grilling 问题：怎样证明业务运行时无 LLM、prompt、券商执行路径？直接采用推荐答案：组合静态 architecture test（生产依赖、AST/import、资源与公共 command/schema denylist）、composition test（业务包不能解析 Skill/prompt 资源）、运行时网络 spy（离线全旅程零外连，live 仅允许配置 Provider destinations）和 public-surface snapshot；docs/skills 中允许控制面说明，但不得进入业务 wheel/import graph。任何命中都是阻断失败，不能只靠人工 grep 声明。
- 第二十一个 grilling 问题：总任务要求的反前视和 A 股特殊规则在无回测/执行引擎的首切片怎样落地？直接采用推荐答案：不虚构 backtest 能力；使用带未来 `available_at` 的泄漏 sentinel fixture，证明共享 PIT snapshot policy 拒绝它，并明确该测试只覆盖首切片的数据时间门禁。A 股特殊规则选择停牌/涨跌停和非交易日回退：它们形成透明市场限制与 `review_feasibility`，不产生模拟成交或 T+1 执行结论；未来真正回测仍需独立的执行时点反前视套件。
- 第二十二个 grilling 问题：最终 pass 应输出什么，哪些情况绝不能称为完成？直接采用推荐答案：生成 machine-readable acceptance evidence manifest，逐项列 suite/version/environment/fixture hash/result/artifact refs 与 live qualification 状态。只有全部本地确定性阻断门通过才可记 slice acceptance passed；live qualification external_blocked 时必须单列且不得声称 live sync complete。静态 UI、手工截图、直接 DB seed、mock facade 内部、跳过 Windows 恢复、只跑 happy path、失败测试被 skip/xfail 或自然语言报告都不能计入完成。

## Answer

第一条纵向切片的最高层权威验收 seam 固定为：**由生产 composition root 创建真实 `ApplicationFacade`，在新的 data root 上依次调用正常公开命令与查询，最后只通过 query facade、run journal、不可变 manifests 和 `doctor` 验证用户可观察的完整关系图。**

它不是一个新生产 API，也不是 UI 截图测试。测试驱动器可以注入固定时钟、临时 data root 和实现同一 Provider contract 的离线 fixture adapter，但不得 mock facade 内部 workflow、repositories、`ResearchEngine`、计划/市场服务、SQLite 或 object store。

### 1. 权威 seam 与 adapter 责任

```text
versioned acceptance fixture + fixed clock + isolated data root
                         |
production composition root
                         |
               ApplicationFacade
       commands ---------------- queries
          |                         |
Workflow/Provider/Research/Market/Plan/Annotation
                         |
 SQLite + immutable object store + manifests/journal
```

- facade acceptance 是业务闭环的唯一权威语义测试；它必须走真实迁移、SQLite、object publish、workflow registry、研究 adapter、计划评估和历史 projection。
- 不创建 `run_vertical_slice_acceptance`、测试专用“完成全部步骤”或可直接写领域状态的生产接口。tests 中的 driver 只是组合真实公开调用。
- Web browser E2E 证明 HTTP/DOM adapter 与实际用户体验接通；维护 subprocess tests 证明 `scripts/platform.py`、锁、退出码和 Windows 文件系统行为。二者都消费同一应用 seam，但都不另立业务权威。
- 第一切片因此必须补齐最小观察项命令/查询，以及图表、标注、计划和历史的公开 application contracts；UI/CLI 不得直接访问 repository、SQLite 或 `ResearchEngine` 内部函数。

### 2. 固定 acceptance fixture

fixture pack 固定意华股份 `002897.SZ`，至少包含：

- 证券身份、深交所/CNY/`Asia/Shanghai` 与能证明 `2026-07-11 -> 2026-07-10` 回退的交易日历；
- 截至 `2026-07-10` 的 canonical 未复权 OHLCV、公司行动/复权因子输入和四组件市场状态所需的锁版本 universe/benchmark 数据；
- 截至 `2026-07-07` 可用的官方披露和研究输入，且 7 月 8—10 日没有会改变研究 cache key 的新研究材料；
- Provider 原始 bytes、真实来源身份、许可/保存边界、四类时间及精度、adapter/schema/policy versions、逐项 SHA-256 和 fixture manifest；
- 明确标为 `user_fixture_input` 的标注、计划规则、阈值和风险预算，不含真实账户、持仓、现金或个人身份。

fixture adapter 必须禁止网络，并与生产 adapter 共用 normalizer、quality、PIT、cursor、snapshot 和 provenance 路径。测试进程还要用 network spy 确认整个离线旅程零外连。fixture 通过只证明确定性离线闭环；生产 Provider 是否真实可用由独立 live qualification 记录，二者不得混写。

### 3. 一条可复现的 golden journey

Given 阶段也必须走公开 seam：

1. 在空临时 data root 上通过统一入口执行 `bootstrap`/`migrate`；重复执行仍成功且不重建历史。
2. 通过 `add_watchlist_item` 建立意华股份观察项，并从 query facade 读取稳定 `Security`/`WatchlistItem` identity。
3. 以 `2026-07-07` cutoff 执行真实 workflow，建立 canonical `ResearchRun`；不得由 fixture loader 直接写研究结果。
4. 完全关闭应用并以同一 data root 重新创建 production composition root。

When/Then 主路径：

1. `list_watchlist_items` 能看到重启前的观察项、本地数据日期和陈旧状态；打开/serve 本身不联网。
2. 以新 invocation 执行“更新至今天”，请求日为 `2026-07-11`，有效完整交易日为 `2026-07-10`。
3. `WorkflowRun` 成功或在明确可接受时 `succeeded_with_limits`，并通过 refs 指向真实 Provider attempts、cursor、`DataSnapshot`、`MarketSnapshot`、ResearchRun 与 final `ArtifactManifest`。
4. `run_or_link_research` 必须复用 Given 阶段同一 ResearchRun，保留其 `2026-07-07` cutoff、请求/data snapshot、canonical JSON/HTML hashes，并记录 `disposition=reused`、稳定原因和 3 个自然日陈旧说明；不得复制报告或创建伪新 run。
5. 通过 query facade 读取截至 `2026-07-10` 的版本化日 K 线，明确未复权/有效 session/data snapshot/factor refs；通过正常 annotation command 创建一条 exact decimal 时间/价格标注。
6. 关闭并重新创建 facade 后，标注 identity、v1、坐标、interval、adjustment mode、snapshot/factor refs 完全一致。
7. 用明确的 `user_fixture_input` 创建 `TradePlanDraft`，确认并原子启用不可变 `TradePlanVersion v1`；确认页/命令结果包含内容 hash、引用和“非平台建议、不会执行交易”的边界。
8. 对 active v1 与确切 `2026-07-10 MarketSnapshot` 执行 `PlanEvaluation`；逐规则返回 typed operands、单位、观测时点、reason codes、effect/applies_to 与证据 refs，只产生复核/限制/失效候选。
9. 从 history timeline 以 WorkflowRun 为入口，能够通过公开查询遍历 `DataSnapshot -> ResearchRun -> ChartAnnotationVersion -> TradePlanVersion -> MarketSnapshot -> PlanEvaluation -> ArtifactManifest`，并区分 created/reused、请求日/有效日和数据限制。
10. `doctor` 对 schema ledger、FK/integrity、domain invariants、object hashes、manifest membership 和全部 references 返回通过。

golden journey 不断言随机 WorkflowRun ID、wall-clock、HTML 像素或整份序列化文本。它使用 schema validation 与 semantic assertion ledger，只断言不会因无关实现重构而变化的业务事实、身份关系、状态、reason code、hash 完整性和能力边界。

### 4. 同一 seam 上的强制反例

除 golden journey 外，application acceptance 必须覆盖：

1. 同一 `invocation_id` 重放返回同一 run；新 invocation 建新 run/attempt，但相同内容复用 raw、normalized、snapshot、ResearchRun、MarketSnapshot 和 PlanEvaluation，不重复推进 cursor或新增领域版本。
2. offline 有合法缓存时正常读取；stale 时可回看旧历史但当日能力受阻；missing 时不生成假数据、完整 MarketSnapshot 或正常评估。三者都保存 typed freshness/gap/reason。
3. v2 草稿未确认时 daily 仍选择 active v1；确认并启用 v2 后才原子切换。v1 内容/hash/activation/旧评估不可变；ended plan 不可复活。
4. 标注修改追加 v2，删除追加 tombstone，恢复再追加版本；跨周期、复权或公司行动坐标不能唯一映射时 `unresolved_requires_confirmation`，旧版本不漂移。
5. 同 session 的合法数据修订产生新 DataSnapshot/MarketSnapshot/PlanEvaluation；旧成员和结果仍按原 hash 可回放。
6. 停牌、涨跌停与用户 market gate 同时出现时并列解释 `review_feasibility=restricted`，不遮蔽 exit/invalidation/risk 规则，也不生成订单或计划状态副作用。
7. 带 `available_at > as_of_at` 的泄漏 sentinel 永远不能进入 DataSnapshot。该用例证明共享 PIT 门禁，但不得被宣传为已经实现完整 backtest 反前视能力。
8. 在 temp write、object rename、DB/cursor/node/final-manifest commit 边界注入崩溃后，`resume` 只能留下 temp/orphan 或完整 committed 引用；attempt 递增，合法 checkpoint 不重算，无半 cursor、missing object 或重复领域记录。

### 5. 测试分层与归属

| 层级 | 必须证明什么 | 不应在这里证明什么 |
|---|---|---|
| Domain/unit | 计划 AST/多值传播、市场四组件公式、exact decimal/单位、交易日回退、PIT admission、freshness、复权坐标映射、hash/canonicalization | SQLite、HTTP、浏览器或完整用户旅程 |
| Provider contract | 生产/fixture adapter 的字段、时间精度、未复权、单位/币种、状态、partial/empty/rate-limit、cursor、raw/provenance；相同 raw 进入相同 normalizer/quality path | live Provider 永远可用或 UI 行为 |
| Persistence/migration integration | 空库与 N-1 升级、重复迁移、hash drift/未来版本/failure rollback、SQLite/FK、append-only versions、object publish 原子性、single-writer | 用户界面信息层级 |
| Application acceptance | 本答案的 golden journey、幂等缓存、研究复用、断网陈旧度、计划不可变、标注重启、评估与 history graph | DOM/CSS 像素或 OS subprocess 细节 |
| Fault/recovery integration | lease、retryability、crash injection、resume、checkpoint/cursor/manifest 原子性 | 把所有故障组合塞进浏览器 |
| Browser E2E | B 画布优先的完整 happy journey、blocking banner、reload/server restart、版本侧栏、渐进披露、键盘/焦点/宽度/reduced-motion/非颜色编码 | 直接查 DB、重复 Provider 全矩阵或替代 facade acceptance |
| Maintenance/Windows E2E | 九项入口与 `resume` 的 JSON/退出码/锁，真实 rollback-journal single writer，backup 到 bundle、restore 新 root、doctor、serve/query history | 用模拟文件复制宣称恢复成功 |
| Architecture/security | 生产 dependency/import/resource/public-surface denylist、业务运行时无 Skill/prompt/LLM/broker/order/export，离线网络 spy、live Provider destination allowlist、秘密脱敏 | 只做人工 grep |
| Legacy regression | 现有 35 项原样通过；platform adapter 只使用 `ResearchEngine.run(ResearchRequest) -> ResearchRun`，canonical 输出与 CLI 一致 | 让 legacy 全局 gate 重新成为平台权威 |

总任务中的“目标市场特殊规则”在第一切片以非交易日回退、停牌和涨跌停事实/门控验收；由于首切片没有账户和执行模拟，不伪造 T+1 成交测试。真正 backtest 的信号时点、成交时点、费用和未来泄漏仍是后续策略切片的独立完成门。

### 6. Provider live qualification 与完成声明

生产 adapter 还必须在配置了合法凭据/权益时执行小范围 live qualification，记录 adapter/provider identity、请求范围、retrieved time、raw hash、contract/quality result 和是否推进 cursor。它不进入每次离线 CI，也不得因网络波动让确定性 suite 失真。

- `qualified`：本次真实 Provider 调用及合同/质量门通过，可以声明该 adapter 的受测 live sync 成功。
- `external_blocked`：精确记录缺少的凭据、权限、许可或可达性；fixture acceptance 仍可通过，但最终摘要不得写“真实同步已完成”。
- `failed`：Provider 返回违反合同、schema drift 或质量 blocking；这是 adapter 失败，不得降级成 pass。

### 7. Acceptance evidence 与完成门

测试入口最终生成不可变、machine-readable acceptance evidence manifest，至少记录：

- acceptance schema/suite/workflow/node/evaluator versions、code identity、OS/Python/SQLite 版本；
- fixture pack identity、license/source profile、每项 hash、固定请求时钟与 network policy；
- 各 suite 的 `passed / failed / external_blocked / not_applicable`、开始/结束时间、稳定 failure code 和诊断 artifact refs；
- golden journey 的关键 entity refs、created/reused disposition、final manifest、doctor report、browser evidence、backup/restore report 与 legacy regression result；
- live qualification 独立状态，不能被本地通过覆盖。

只有所有本地确定性阻断门通过，才可写 `slice_acceptance=passed`。任何失败被 skip/xfail、直接数据库 seed、mock facade 内部、静态 UI、手工截图、自然语言报告、空目录、只跑 happy path、未执行 Windows 恢复、manifest/hash 不完整或业务运行时出现 LLM/订单能力，都必须令验收失败。若 live qualification 为 `external_blocked`，可以如实交付已通过的 fixture-backed slice 及外部阻塞，但不得把 live sync 或整个长期平台误报为完成。

本票没有新增业务领域概念。`ApplicationFacade`、acceptance driver、test layer 与 evidence manifest 都是架构/测试术语，不进入 `CONTEXT.md`；它也没有形成满足 ADR 三条件的新技术取舍。所有已知纵切验收边界已经可直接交给最终 Spec 综合票据，不新增 Wayfinder ticket 或 fog。
