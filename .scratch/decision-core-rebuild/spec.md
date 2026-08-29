# EquityTrack 决策核心重构 Spec

Status: `ready-for-agent`

## Problem Statement

EquityTrack 当前 live runtime 已经积累账户、研究、估值、计划、监控、复盘、工作流、图表和多格式产物等多套相互交叉的模型。应用层、领域层和持久化层存在过宽接口、重复事实、跨模块访问、专属幂等回执、计划图与通用工作流状态；当前数据库还背负 25 个增量 migration。旧 Skill 任务、README 和测试仍描述这些既有能力，目标设计尚未实现。

这使投资研究中最重要的判断边界变得模糊：AI、确定性 Python 和用户确认的权威没有被一个最小工作流清楚分开；证据缺失可能被全局门放大；研究、估值、风险、计划和复盘拥有重复记录；JSON、Markdown、HTML、PDF、workbook 和 artifact manifest 可能形成多份业务真值。继续在旧结构上增补能力会扩大项目，而平行建设新版本、兼容层或双读写又会永久保留两套系统。

用户需要一次原位、删除优先的彻底重构，把系统收缩为单用户、单默认账户、单证券的投资决策闭环。开发和验收先只使用合成数据与 Fixture Adapter；在系统达到“合成通路已验证”后，用户才另行提供真实凭据并授权真实数据迁移与验收。重构期间不得访问或修改真实数据根，也不得为了未来可能性预建 DSH、量化研究、回测、因子挖掘或其他扩展框架。

## Solution

系统将按领域所有权原位替换为 `evidence`、`portfolio`、`research`、`valuation`、`planning`、`review` 六个 deep Module，并通过一个由完整用户任务组成的 Application Interface 对外提供行为。Skill、CLI、测试和以后可能出现的展示层都只穿过该 Application Interface；Module 之间只交换公开、不可变、类型化记录，不访问彼此的 repository、表或私有函数。`monitor` 是组合 planning 与 review 的 application workflow，不是第七个 Module。

权威边界固定为：AI 提出含义与判断；Python 核实事实、计算数字、执行约束并保存真值；用户确认账户、计划和实际执行。研究语义由 Skill 完成，确定性计算和持久化由 Python 完成，业务 runtime 不调用 LLM。SQLite 是唯一持久化业务真值；JSON 只作为即时响应，Markdown 只作为按需只读投影。

替换按治理收敛、基线净化、模块构建、合成切换演练、原子切换与删除、真实集成的顺序推进，但这些名称只描述工作顺序，不进入包名、类型名、函数名、表名或领域记录。每个 owned seam 必须在同一变更单元内完成新实现、合成旧 schema 迁移、调用方切换、公开 Interface 测试、文档更新及旧实现删除。不能安全迁移的不可替代事实必须阻塞该 seam；不得用兼容代码掩盖未知。

## User Stories

1. As a 单一投资者, I want 系统围绕一个默认账户和一只证券完成一次决策闭环, so that 我不用理解内部工作流或数据结构。
2. As a 单一投资者, I want 账户事实、研究判断、估值、风险限制、计划、监控和复盘按固定顺序衔接, so that 每一步的依据和责任清楚可查。
3. As a 单一投资者, I want 系统帮助我形成和检验判断而不替我作证券行动决定, so that 最终决策权始终属于我。
4. As a 单一投资者, I want 默认输出使用研究语言而不是买卖评级, so that 不完整证据不会被包装成个性化投资建议。
5. As a 单一投资者, I want 只在确认账户、确认最终 TradePlan 和声明实际执行时作明确决定, so that 日常研究过程不会反复打断我。
6. As a 单一投资者, I want 所有缺失数据被明确表示为未知而不是零, so that 账户和估值不会产生虚假精度。
7. As a 单一投资者, I want 非关键缺失只限制直接依赖它的判断, so that 一个来源缺口不会阻塞整个工作流。
8. As a 单一投资者, I want 查看的是一个当前、简洁、决策相关的结果, so that 内部 ID、hash、迁移和诊断不会占据默认界面。
9. As a 账户所有者, I want 通过一次明确确认形成不可变 AccountSnapshot, so that 账户事实有唯一权威来源。
10. As a 账户所有者, I want 新信息形成新的 AccountSnapshot 而不覆盖历史, so that 过去决策仍绑定当时事实。
11. As a 账户所有者, I want 未知现金、成本或可用数量保持未知并局部降级, so that 系统不会从不完整声明推导不存在的账户事实。
12. As a 账户所有者, I want 行情更新只能改变临时 PortfolioState, so that Provider 不能修改现金、持仓数量或执行历史。
13. As a 账户所有者, I want 用户声明的 ExecutionRecord 与券商核验状态分开, so that 我的声明不会被误称为券商成交事实。
14. As a 研究用户, I want 每个 EvidenceItem 要么记录值和 source_id 要么记录 missing_reason, so that 所有关键输入都有最小来源边界。
15. As a 研究用户, I want 一个 EvidenceSet 绑定统一 as_of, so that 不同时间口径的数据不会被无提示混合。
16. As a 研究用户, I want EvidenceSet 没有全局通过或失败状态, so that 证据质量由实际消费者按需判断。
17. As a 研究用户, I want AI 把事实、假设、估计和缺失分开, so that InvestmentCase 的推理链可以被反驳和更新。
18. As a 研究用户, I want InvestmentCase 同时记录论点、反方、驱动、风险、证伪条件和不确定性, so that 研究不是单向结论。
19. As a 研究用户, I want InvestmentCase 不包含估值或交易动作, so that 研究语义不会越过确定性计算和用户权威。
20. As a 研究用户, I want Python 只校验并提交 AI 研究候选, so that 代码不会用硬编码提示、评分树或模板拼接投资观点。
21. As a 估值用户, I want 估值只在我明确请求时执行, so that 研究不会自动产生价格结论。
22. As a 估值用户, I want valuation Module 负责方法路由、单位、币种、会计桥接、公式和敏感性, so that 数字来自可重复的确定性计算。
23. As a 估值用户, I want 方法关键输入缺失时得到 insufficient ValuationAssessment, so that 系统不会编造输入完成估值。
24. As a 估值用户, I want 不适用的方法被明确禁用并给出原因, so that DCF 或可比估值不会被机械套用。
25. As a 估值用户, I want 条件情景在没有校准证据时不附加主观概率, so that 情景结果不会伪装成概率加权目标价。
26. As a 风险约束维护者, I want RiskPolicy 只包含用户确认的确定性限制, so that 风险边界不会变成主观打分或交易信号。
27. As a 风险约束维护者, I want RiskLimitResult 绑定明确 PortfolioState 和输入引用, so that 风险计算可重放且不能被 DecisionCard 覆盖。
28. As a 计划用户, I want planning.prepare 在一个事务中保存 RiskLimitResult、DecisionCard 和 TradePlanDraft, so that 不会出现半完成计划依据。
29. As a 计划用户, I want DecisionCard 引用 InvestmentCase、可选 ValuationAssessment 和 RiskLimitResult, so that 计划依据完整但不重复拥有这些事实。
30. As a 计划用户, I want TradePlanDraft 带稳定 content_hash 且不参与监控, so that 未确认内容不能产生复核任务。
31. As a 计划用户, I want 通过 draft_id、content_hash 和一次明确确认生成不可变 TradePlan, so that 确认只适用于我看到的最终内容。
32. As a 计划用户, I want TradePlan 修订通过 plan_family_id、revision 和 supersedes_plan_id 连接, so that 历史不被覆盖且无需版本聚合框架。
33. As a 计划用户, I want 没有替代计划时通过 PlanClosed 追加关闭, so that 关闭不会修改或删除原计划。
34. As a 计划用户, I want PlanRule 是有限类型且只产生复核条件, so that 系统不会演变成通用策略语言或自动订单引擎。
35. As a 监控用户, I want monitor.evaluate 确定性地产生 PlanEvaluation, so that 每个触发、未触发或无法判断都有明确依据。
36. As a 监控用户, I want 只有真实触发才幂等创建 DecisionTask, so that 数据缺失不会制造待处理事项。
37. As a 监控用户, I want insufficient PlanEvaluation 保留受影响规则和缺失原因, so that 我知道补充什么证据才能继续判断。
38. As a 复盘用户, I want PROCESS 复盘只使用决策当时冻结的信息, so that 结果偏差不会倒推改写当时理由。
39. As a 复盘用户, I want OUTCOME 复盘在结果窗口结束后引用对应 PROCESS 记录, so that 过程质量和结果评价保持分离。
40. As a 复盘用户, I want 周期汇总只是现有记录的只读投影, so that 系统不会建立第二套复盘真值。
41. As a Skill 维护者, I want 一个公开 Skill 入口路由六个自然语言任务, so that 用户不需要学习内部命令。
42. As a Skill 维护者, I want account、research、valuation、planning、monitoring 和 review 各有一个高内聚任务文档, so that AI 工作流边界与领域 Module 一致。
43. As a Skill 维护者, I want instruction 默认完成语义工作而脚本只处理确定性行为和外部工具, so that Python 保持辅助事实处理而不取代 AI 投研判断。
44. As a 应用调用者, I want account.confirm、account.show、research.commit、valuation.assess、planning.prepare、planning.confirm、monitor.evaluate 和 review.commit 构成唯一 Application Interface, so that CLI、Skill 和测试没有旁路。
45. As a 应用调用者, I want 每个 mutation 使用同一个 application command 幂等合同, so that 重试行为一致且无需领域专属 receipt。
46. As a 应用调用者, I want 相同 idempotency key 和相同请求返回原结果, so that 安全重试不会重复写入。
47. As a 应用调用者, I want 相同 idempotency key 和不同请求返回 IDEMPOTENCY_CONFLICT, so that 冲突不会被静默覆盖。
48. As a 应用调用者, I want 稳定失败只有少量顶层代码并保留具体子步骤诊断, so that 自动化可判断失败而用户仍得到可行动解释。
49. As a 持久化维护者, I want 一个 SQLite 保存全部规范业务记录, so that JSON、Markdown 和 artifact 目录不会成为竞争真值。
50. As a 持久化维护者, I want 每个 application mutation 拥有一个短事务, so that 跨 Module 写入要么全部成功要么全部回滚。
51. As a 持久化维护者, I want 长时间 AI 研究在事务外完成候选, so that 数据库不会因模型思考长期持锁。
52. As a 持久化维护者, I want Provider 与 SQLite Adapter 位于真实外部 seam, so that 领域规则不依赖具体协议或存储。
53. As a 测试维护者, I want 合成 Fixture Adapter 覆盖所有开发输入, so that 没有真实凭据也能验证完整工作流。
54. As a 测试维护者, I want 端到端测试只穿过 Application Interface, so that 测试不会固化 repository、SQL 或私有函数。
55. As a 测试维护者, I want Skill eval 与 Python 测试分别验证 AI 判断和确定性行为, so that 两类权威不会被同一套脆弱断言混淆。
56. As a 迁移维护者, I want 使用合成旧 schema fixture 验证一向迁移和恢复, so that 真实切换前可以反复演练故障。
57. As a 迁移维护者, I want 每个 owned seam 在调用方切换后立即删除旧代码、schema、测试和文档, so that 仓库不会长期保留两套实现。
58. As a 迁移维护者, I want 无法无歧义迁移的不可替代业务事实阻塞切换并报告精确原因, so that 兼容层不会掩盖数据损失。
59. As a 迁移维护者, I want 真实切换前生成并验证可恢复备份, so that 用户数据在迁移失败时可以恢复。
60. As a 迁移维护者, I want 用户关闭回滚窗口后压平为一个当前 schema 基线并删除临时 migration, so that 数据库历史不会无限膨胀。
61. As a 维护者, I want 删除 ResearchRun、DataSnapshot、PortfolioSnapshot、TradePlanVersion、工作流账本、计划图和多格式产物等退休运行时, so that 活动代码只描述当前领域模型。
62. As a 维护者, I want 删除 PlanConfirmationChallenge 和 UserApprovalReceipt 并把确认元数据保存在 TradePlan, so that 用户确认没有重复领域对象。
63. As a 维护者, I want 删除 PlanImpactAssessment、PlanChangeProposal 和 ActionLogEntry 等重叠概念, so that 监控与复盘只使用 PlanEvaluation、DecisionTask、DecisionReview 和 ExecutionRecord。
64. As a 维护者, I want 每个 Module 通过删除测试证明其具有 Depth, so that 浅转发文件不会以模块化名义增加复杂度。
65. As a 维护者, I want dependency guard 阻止领域层导入 CLI、展示或具体 persistence, so that 依赖持续向内。
66. As a 维护者, I want 最终搜索不到退休 symbol、命令、schema、fixture、测试、文档或依赖, so that Git 历史而不是活动仓库承担归档。
67. As a 维护者, I want 进展只报告设计已确认、合成通路已验证或真实通路已验证, so that 计划名称不会被误认为实现证据。
68. As a 维护者, I want 包名、类型名、函数名和表名不包含阶段或项目进展标签, so that 代码表达领域含义而不是临时计划。
69. As a 维护者, I want 当前工作不创建 DSH、Vibe-Trading、Qlib、因子挖掘、回测或组合优化扩展点, so that 未经验证的未来能力不会污染核心设计。
70. As a 维护者, I want 真实 Provider 仅在用户以后明确提供凭据和授权后实现, so that 合成验证与真实验收不会被混为一谈。

## Implementation Decisions

- 本 Spec 实现唯一权威设计，不重新解释或削弱已确认的领域词汇和 ADR。当前 live runtime 是迁移来源，不是目标架构的先例。
- 最高权威分工固定为：AI 提出含义与判断；Python 核实事实、计算数字、执行约束并保存真值；用户确认账户、计划和实际执行。
- 业务 runtime 不调用 LLM。Skill 负责证据语义、InvestmentCase 候选、反方、证伪条件、不确定性和复盘判断；Python 负责解析、标准化、确定性估值、风险限制、计划规则、校验、幂等、事务、SQLite、迁移和恢复。
- 建立 `evidence`、`portfolio`、`research`、`valuation`、`planning`、`review` 六个 deep Module。每个 Module 拥有完整不变量和一个小公开 Interface；不得为拆文件而创建转发 Module。
- `evidence` 拥有 EvidenceItem、EvidenceSet、as_of 一致性、来源或缺失表达、输入标准化和重复项处理。当前生产输入只有合成 Fixture Adapter；以后真实 Provider 是独立授权的正式 Adapter，不建立 fallback 链。
- `portfolio` 拥有 AccountSnapshot、ExecutionRecord 的账户影响、PortfolioState、RiskPolicy 和 RiskLimitResult。PortfolioState 是临时派生值，不单独持久化；行情不能改变账户事实。
- `research` 拥有 InvestmentCase 结构、不变量、引用一致性和提交。它不拥有估值、计划、报告渲染、ResearchRun 或通用工作流状态。
- `valuation` 拥有方法路由、输入合同、行业适用性、会计桥接、单位与币种校验、公式、敏感性和 ValuationAssessment。结果只有 `completed` 或 `insufficient`，不生成评级或个性化行动建议。
- `planning` 拥有 DecisionCard、TradePlanDraft、TradePlan、PlanClosed、有限 PlanRule 和 PlanEvaluation。它检查风险引用、草稿哈希、确认时效、修订关系和规则冲突，但不计算风险、不修改计划、不产生订单。
- `review` 拥有 DecisionTask 与 PROCESS/OUTCOME 两类 DecisionReview。OUTCOME 必须引用 PROCESS；数据缺失只产生 insufficient PlanEvaluation，不创建 DecisionTask。
- `monitor` 是 application workflow，不是领域 Module。它读取 EvidenceSet 和活动 TradePlan，调用 planning 形成 PlanEvaluation，并只在真实触发时调用 review 幂等创建 DecisionTask。
- 依赖方向固定为外部 Adapter 到 Application Interface，再到六个领域 Module，再到 inward-facing persistence port，最后到 SQLite Adapter。Module 不访问其他 Module 的 repository、表或私有函数。
- 共享内核只允许 Money、SecurityId、时间和少量稳定标识。禁止通用 DTO 仓库、膨胀 common/utils、service locator、root Facade 和业务方法镜像。
- Application Interface 只公开八个完整操作：`account.confirm`、`account.show`、`research.commit`、`valuation.assess`、`planning.prepare`、`planning.confirm`、`monitor.evaluate`、`review.commit`。
- `account.confirm` 接收用户确认的账户候选并形成 AccountSnapshot；`account.show` 提供只读账户视图。账户修订或纠错形成新的不可变快照，不覆盖历史。
- `research.commit` 接收 Security、as_of、EvidenceSet 和 AI 研究候选，在短事务中校验并持久化 InvestmentCase。AI 思考发生在事务外。
- `valuation.assess` 接收 InvestmentCase、EvidenceSet、方法请求和假设，持久化 completed 或 insufficient ValuationAssessment。
- `planning.prepare` 在一个事务中计算并持久化 RiskLimitResult、DecisionCard 和 TradePlanDraft。不存在 `monitor_only` 分支，风险结果不得由 Skill 或调用者预先计算后注入。
- `planning.confirm` 只接受 draft_id、content_hash 和用户明确确认。确认时间、确认者和渠道直接记录于 TradePlan；不再使用 challenge 或独立 approval receipt。
- `monitor.evaluate` 在一个事务中持久化 PlanEvaluation，并按触发结果选择是否创建 DecisionTask。没有活动计划、输入不足和规则无法判断都是正常类型化结果。
- `review.commit` 接收 PROCESS 或 OUTCOME 候选并形成不可变 DecisionReview；OUTCOME 的关联、结果窗口和时序由 review Module 校验。
- 所有 mutation 共用 `operation + idempotency_key + request_digest -> result_ref` 的 application command 记录。相同 key 和相同请求重放原结果；不同请求返回 `IDEMPOTENCY_CONFLICT`。
- 顶层失败集合固定为 `INVALID_INPUT`、`NOT_FOUND`、`STALE_INPUT`、`IDEMPOTENCY_CONFLICT`、`PERSISTENCE_FAILURE`、`INTERNAL_FAILURE`。底层保留脱敏子步骤诊断；证据缺失、估值不适用和风险无法判断不进入失败集合。
- EvidenceItem 的最小合同是值加 source_id，或 missing_reason。EvidenceSet 只有统一 as_of，不包含全局 completeness、rights、quality grade 或 pass/fail gate；缺失由直接消费者局部处理。
- SQLite 是唯一持久化业务真值和唯一 persistence path。每个 application mutation 使用一个短事务；领域 Module 不自行提交，composition root 只负责 wiring 和 lifetime。
- JSON 是 application operation 的即时标准响应；Markdown 是按需生成的只读投影。除非用户明确导出，两者都不持久化；不再保存 artifact manifest、lineage、HTML、PDF、workbook、复杂图表或重复报告目录。
- 保留的规范记录限于 EvidenceItem、EvidenceSet、InvestmentCase、ValuationAssessment、AccountSnapshot、ExecutionRecord、PortfolioState、RiskPolicy、RiskLimitResult、DecisionCard、TradePlanDraft、TradePlan、PlanClosed、PlanRule、PlanEvaluation、DecisionTask 和 DecisionReview。
- 退休并删除 ResearchRequest、ResearchAnalysisPlan、ResearchRun、CompleteReport、DataSnapshot、EvidenceSnapshot、PortfolioSnapshot、InvestmentThesisVersion、TradePlanVersion、计划 graph/AST/sleeve、DisciplineReviewVersion、DynamicWorkflow、WorkflowRun、ArtifactManifest、PlanConfirmationChallenge、UserApprovalReceipt、PlanImpactAssessment、PlanChangeProposal 和 ActionLogEntry 的 runtime、schema、测试、fixture、文档、导出与依赖。
- AccountSnapshot、ExecutionRecord、已确认 TradePlan 和 DecisionReview 等不可替代事实必须通过显式、版本化、单向迁移保存。可重建投影和生成产物直接删除。不能无歧义映射的事实阻塞对应 seam，不增加 decoder、alias、fallback 或双读。
- 替换按 ownership seam 原位完成。一个迁移单元必须同时包含目标实现、合成旧 schema 迁移、全部调用方切换、公开 Interface 测试、文档更新和旧路径删除；不得提交只增加新路径而保留旧路径的中间兼容状态。
- 工作顺序是治理收敛、基线净化、模块构建、合成切换演练、原子切换与删除、真实集成。该顺序不使用阶段编号，也不进入代码标识。
- 基线净化必须固定当前代码与 schema 清单、以虚构证券和账户替换测试中的真实标的示例、将旧测试分类为保留行为、替换行为或删除行为，并形成精确退休 symbol 清单。
- 模块构建期间新路径不向 Skill 或 CLI 公开。只有六个 Module、Application Interface、SQLite Adapter、迁移和合成端到端同时满足验收后，才允许一次原子切换所有公开调用方。
- 合成切换演练只使用临时数据根和合成旧 schema fixture，覆盖初始化、升级、故障注入、原子回滚、重启、备份、恢复、doctor 和完整决策闭环。不得读取、复制或修改真实数据根。
- 真实集成是以后独立授权的工作。只有用户提供真实凭据后才实现一个正式 Provider Adapter，并在迁移前验证真实备份；合成通过不能表述为真实 Provider 或真实数据通过。
- 真实回滚窗口关闭必须由用户明确确认。窗口内保留迁移工具与真实备份；窗口关闭且全部数据根恢复验证通过后，将 schema 压成一个当前初始化基线，删除旧 migration、临时迁移工具和旧 schema fixture。真实备份没有授权不得删除。
- 仓库最终仍只保留一个公开 Skill 入口，并路由 account、research、valuation、planning、monitoring、review 六个任务。当前 Skill 在原子切换前继续描述 live runtime，不能提前声称目标能力已经实现。
- Instruction 是 AI 研究和复盘的默认实现。脚本只用于确定性事实处理、计算、校验和真实外部工具调用；不为 Skill 建立运行时 Agent graph、prompt orchestration framework 或 Python 叙述模板。
- 进展只使用“设计已确认”“合成通路已验证”“真实通路已验证”。不得在标题、包名、类名、函数名、表名、操作名或 schema 中使用阶段编号或临时计划标签。
- 当前明确排除 DSH、Vibe-Trading、Qlib、因子发现、alpha 挖掘、通用回测、策略生成、Walk-Forward、Bootstrap、策略 Monte Carlo、组合优化、模拟或真实下单、自动执行、复杂图表、多格式报告和 runtime LLM。不得为这些能力预留 seam、Adapter、表、配置、feature flag、空包或测试占位。
- 财务输出始终禁止未经明确请求和完整门约束的评级、目标价结论和个性化买卖建议。缺少关键官方事实或方法输入时保留研究结构并返回局部 insufficient。
- 实现完成的证据是公开 Interface 测试、Skill eval、合成迁移恢复、最终 diff 与退休 symbol 搜索；设计文档、Spec、issue 数量和规划状态都不能证明 runtime 已实现。

## Testing Decisions

- 最高测试 seam 是 Application Interface。完整用户旅程、事务边界、幂等、失败映射和合成端到端都只通过八个公开 operation 观察，不直接调用 repository、SQLite、领域私有函数或旧 runtime。
- 六个 Module 的公开 Interface 是次级测试 seam，只测试由该 Module 独立拥有的确定性行为和不变量。测试不验证内部类数量、参数转发或文件布局。
- `evidence` 测试覆盖统一 as_of、值与 source_id、missing_reason、重复输入、来源解析、未知值传播以及局部缺失不阻塞无关消费者。
- `portfolio` 测试覆盖 AccountSnapshot 不可变性、修订与纠错、未知字段传播、ExecutionRecord 投影、PortfolioState 计算、单位和币种、RiskPolicy 与 RiskLimitResult，以及行情不得改变账户事实。
- `research` 测试覆盖 InvestmentCase 结构、引用一致性、缺失证据状态和提交幂等；不以精确措辞测试 AI 研究判断。
- `valuation` 测试覆盖方法路由、行业适用性、关键输入门、单位与币种、会计桥接、公式、敏感性、情景规则、completed/insufficient 以及金融输出边界。
- `planning` 测试覆盖 planning.prepare 的三记录原子提交、风险引用、草稿 content_hash、确认过期、旧 hash、计划修订、PlanClosed、有限 PlanRule、PlanEvaluation 和禁止自动订单。
- `review` 测试覆盖 DecisionTask 触发幂等、缺失数据不建任务、PROCESS/OUTCOME 时序、OUTCOME 引用、结果窗口和不可变性。
- Application Interface 测试覆盖每个 mutation 的成功、精确重放、幂等冲突、STALE_INPUT、子步骤持久化失败、事务回滚、重启后重放以及没有半写状态。
- SQLite Adapter 测试可以使用其明确拥有的 fault injection seam，并覆盖初始化、迁移、锁、并发 writer、commit 故障、损坏检测、备份、恢复和 doctor；更高层测试不得使用 raw SQL 构造业务结果。
- Fixture Adapter 合同测试必须证明合成数据具有虚构身份、明确 as_of、可控缺失、可控陈旧、可控 Provider 失败和确定性重放。测试 fixture 不包含真实证券、真实账户、真实凭据或真实来源声明。
- 合成端到端至少覆盖账户确认、研究提交、估值完成、估值 insufficient、计划准备、计划确认、未触发监控、真实触发监控、缺失证据监控、PROCESS 复盘、OUTCOME 复盘、重启读取和按需 Markdown 投影。
- 迁移测试从具有代表性的合成旧 schema 构建数据根，覆盖一向迁移、不可替代事实映射、可重建产物删除、歧义阻塞、失败回滚、精确重试、旧路径不可调用以及恢复后重新 doctor。
- Skill fixture/eval 独立覆盖事实、假设、估计和缺失区分；论点、反方、证伪条件与不确定性；局部降级；数据捏造；金融输出越界；PROCESS/OUTCOME 分离。Python 测试不通过固定文本代替这些 eval。
- 测试案例数量由风险和分支决定，不固定为历史数量。每个旧测试只有三种处置：迁移到新公开 Interface、由更高层行为测试替代、或随退休行为删除；不得叠加保留新旧套件。
- 复用当前仓库已有的账户快照迁移、风险政策、research workflow、workflow ledger、应用任务、SQLite migration 原子性、备份恢复和幂等冲突测试经验，但所有断言必须迁移到本 Spec 的目标 Interface 和领域词汇。
- 建立静态 dependency guard，验证领域 Module 不导入具体 persistence、CLI、展示或其他 Module 私有实现；验证外部 Adapter 不绕过 Application Interface。
- 每个 ownership seam 关闭前运行窄测试和完整保留套件，并报告通过、失败、跳过、超时、未运行外部检查及生成产物。超时或外部未运行不能表述为通过。
- 原子切换后执行退休搜索，要求旧 symbol、命令、schema、表、fixture、测试、Skill 指令、报告格式、依赖和生成资产在活动仓库中清零。仅明确标注为历史证据且不参与 runtime 或控制面的研究材料可以保留。
- “合成通路已验证”要求六个 Module 与 Application Interface 完整、全部保留 Python 测试和 Skill eval 通过、合成端到端与迁移恢复通过、SQLite 是唯一真值、退休搜索清零，并明确报告真实通路未验证。
- “真实通路已验证”必须以后使用真实 Provider、正式来源、真实数据根备份迁移和恢复证据重新验收，不能从合成测试推断。

## Out of Scope

- 本 Spec 不执行实现、不生成 implementation issues、不提交或推送代码。
- 当前工作不访问、复制、备份、迁移、修复或删除真实数据根，也不配置或请求真实 API credential。
- 不实现 DSH 或任何外部 Agent runtime。
- 不实现 Vibe-Trading、Qlib、因子发现、alpha 挖掘、因子库、自动因子组合、通用策略生成、Walk-Forward、回测、Bootstrap 或策略 Monte Carlo。
- 不实现组合优化、策略市场、模拟交易、券商订单、盘中执行、自动执行或自动计划修改。
- 不实现多用户、多账户、多证券组合工作流、跨账户调仓或机构权限体系。
- 不实现 K 线标注、复杂图表、HTML、PDF、workbook、多格式报告或持久化 Markdown 报告。
- 不建立兼容 shim、旧接口 alias、版本 dispatcher、双读、双写、feature flag、并行新旧 package、fallback-to-old 或占位扩展 seam。
- 不在当前工作中删除真实备份；未来压平 migration 也必须等待真实切换完成和用户明确关闭回滚窗口。
- 不提供个性化买入、卖出、持有、加仓、减仓、规避建议，不默认输出评级或目标价结论。

## Further Notes

- 当前状态仍是“设计已确认”。本 Spec 的 `ready-for-agent` 只表示需求和 seam 已具备生成 issues 的条件，不表示 runtime 已经开始或完成重构。
- 用户将在以后单独、手动执行 `to-issue`。该步骤应按 blocker 顺序拆分 ownership seam，并确保每个 issue 都包含实现、迁移、调用方切换、测试、文档和旧路径删除，不能只建新结构。
- issue 标题与代码标识使用领域能力名称，不使用阶段编号、DSH 或临时项目标签。
- 当前 live Skill 和 README 在原子切换前继续描述既有 runtime；实现 issue 不得提前改写为尚未通过合成验收的能力。
- 真实 Provider 和真实数据验收属于以后独立授权的工作。用户没有提供凭据前，所有测试和演示必须使用明确虚构的数据。
- 发现不能无损迁移的账户、执行、计划或复盘事实时，应停止对应 seam 并记录输入身份、缺失关系和删除阻塞条件；不得扩大范围或添加兼容路径自行绕过。
