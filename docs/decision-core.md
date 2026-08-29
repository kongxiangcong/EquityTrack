# EquityTrack 决策核心

> 状态：合成通路已验证
> 实现状态：六个 Module、八个 Application operation、SQLite Adapter、Fixture Adapter、迁移恢复与唯一 Skill/CLI 路径已通过合成验收
> 真实状态：真实 Provider、真实来源和真实数据根未配置、未访问、未验证

本文是 EquityTrack 当前唯一的产品、架构与验收基线。它定义目标系统，不把设计意图写成已经实现的事实，也不授权本轮修改运行时代码或真实数据。

## 1. 产品定义

EquityTrack 是面向单一投资者、围绕真实持仓运行的本地投资决策系统。它帮助用户形成、约束、确认和复盘判断，不自动下单，不承诺收益，也不替用户决定证券行动。

当前闭环只有：

```text
账户事实
   +
宽松证据集
   ↓
AI 投资研究
   ↓
确定性估值
   ↓
确定性风险限制 + AI 决策依据
   ↓
用户确认的交易计划
   ↓
规则监控与复核任务
   ↓
过程复盘与结果复盘
```

当前只支持一个用户、一个默认账户、单证券决策闭环。多账户、自动下单、盘中执行、通用策略平台、回测平台、因子挖掘、组合优化、复杂图表、多格式报告和外部 Agent 框架均不属于当前系统，也不为它们预留 Interface、表、空包或 feature flag。

## 2. 最高权威分工

> **AI 提出含义与判断；Python 核实事实、计算数字、执行约束并保存真值；用户确认账户、计划和实际执行。**

| 权威 | 负责 | 不负责 |
| --- | --- | --- |
| AI / Skill | 证据语义理解，事实与假设区分，投资论点、反方、因果链、风险、证伪条件、不确定性和复盘判断 | 凭空生成财务数据、账户结果、估值数字、风险上限或计划触发结果 |
| Python | 数据解析与标准化、会计与日期处理、估值公式、风险限制、规则评估、校验、幂等、事务、SQLite、迁移与恢复 | 用规则树或脚本拼接投资观点，在业务运行时调用 LLM，生成研究性叙述 |
| 用户 | 确认账户事实、交易计划和实际执行声明 | 手工拼接内部命令、内部请求或数据库写入 |

Python Module 只有在拥有确定性计算、领域不变量、原子事务、状态变化、持久化、恢复或真实外部协议转换时才成立。仅转发参数、重命名字段、重包装结果或复制 Skill 工作流的 Module 必须删除。

## 3. 领域记录

### 3.1 证据与研究

- `EvidenceItem`：一个输入值及其 `source_id`，或一个明确 `missing_reason`。
- `EvidenceSet`：具有统一 `as_of` 的 EvidenceItem 集合；没有全局通过状态。
- `InvestmentCase`：AI 形成的唯一规范研究结果，包含论点、反方、驱动、风险、证伪条件和不确定性，不包含估值或交易动作。
- `ValuationAssessment`：用户明确请求后由 Python 确定性计算的估值记录；数据不足是其正式状态。

EvidenceSet 不承担全局质量审批。缺失项继续流动，只在消费该项的估值、风险或监控规则处产生局部 `insufficient`。

### 3.2 账户、风险与计划

- `AccountSnapshot`：用户确认的唯一账户事实。
- `PortfolioState`：由 AccountSnapshot、价格和已确认执行记录临时计算的不可变值，不单独持久化。
- `RiskLimitResult`：风险政策针对一个 PortfolioState 的确定性结果。
- `DecisionCard`：引用 InvestmentCase、可选 ValuationAssessment 和 RiskLimitResult 的决策依据；不能覆盖风险结果。
- `TradePlanDraft`：等待用户确认的计划候选，具有稳定内容哈希。
- `TradePlan`：一次明确确认形成的不可变计划；修订通过 `plan_family_id`、`revision` 和 `supersedes_plan_id` 连接。
- `PlanClosed`：没有替代计划时的追加关闭记录。
- `PlanEvaluation`：有限类型规则的确定性评估。

系统不再使用 TradePlanVersion、计划图、通用规则 AST、持仓 sleeve、可变计划 aggregate 或通用生命周期事件框架。

### 3.3 监控与复盘

- `DecisionTask`：计划规则真实触发后幂等创建的待复核事项。
- `DecisionReview(PROCESS)`：只使用当时冻结信息评价决策过程。
- `DecisionReview(OUTCOME)`：结果窗口结束后引用对应 PROCESS 记录评价结果。

数据缺失不会创建 DecisionTask。周期汇总只是 DecisionReview、账户事实和开放任务的只读投影，不形成另一套复盘真值。

## 4. 六个深 Module

每个 Module 只有一个小 Interface，Interface 同时是调用面和测试面。删除一个 Module 后，如果其复杂行为会散落到多个调用者，说明它具有 Depth；如果删除后只需要把同样的调用搬到别处，它是浅层转发，应当删除。

### 4.1 evidence

**拥有**：EvidenceItem、EvidenceSet、`as_of` 一致性、来源或缺失的最小表达。

**隐藏**：输入标准化、来源登记解析、重复项处理和未来真实 Provider 的外部协议转换。

**Interface 结果**：一个允许缺失的 EvidenceSet。

Provider 位于真实外部 seam。当前只有合成 Fixture Adapter；真实凭据到位后才增加一个正式 Adapter。不存在 Provider fallback 链。

### 4.2 portfolio

**拥有**：AccountSnapshot、执行事实、PortfolioState、风险政策和 RiskLimitResult。

**隐藏**：账户聚合、未知值传播、币种与单位处理、组合计算和风险限制公式。

**Interface 结果**：确认账户事实、读取账户视图、计算风险限制。

行情与 Provider 不能修改现金、数量或执行事实。

### 4.3 research

**拥有**：InvestmentCase 的结构、不变量和提交。

**隐藏**：结构校验、引用一致性和确定性派生字段。研究含义、反证和叙述由 Skill 中的 AI 工作流完成。

**Interface 结果**：一个已提交或局部受限的 InvestmentCase。

research 不拥有估值、计划、报告渲染或通用工作流运行记录。

### 4.4 valuation

**拥有**：估值方法路由、方法输入、公式、敏感性和 ValuationAssessment。

**隐藏**：行业适用性、会计桥接、单位与币种检查以及方法计算。

**Interface 结果**：`completed` 或 `insufficient` 的 ValuationAssessment。

AI 可以提出方法和假设，最终方法门与数字由 valuation Module 决定和计算。

### 4.5 planning

**拥有**：DecisionCard、TradePlanDraft、TradePlan、PlanClosed、有限 PlanRule 和 PlanEvaluation。

**隐藏**：风险引用检查、草稿哈希、确认时效、修订关系和规则冲突。

**Interface 结果**：准备草稿、确认计划、评估计划。

planning 不计算风险，不自动修改计划，也不产生订单。

### 4.6 review

**拥有**：DecisionTask 和两阶段 DecisionReview。

**隐藏**：任务幂等、PROCESS/OUTCOME 关联和结果窗口规则。

**Interface 结果**：创建或读取复核任务，提交 PROCESS 或 OUTCOME 复盘。

`monitor` 是 application workflow，不是第七个领域 Module。它组合 EvidenceSet、planning 的 PlanEvaluation 和 review 的 DecisionTask。

## 5. 依赖方向与 seam

```text
Skill / CLI / future Provider
             ↓
      application Interface
             ↓
    six domain Modules
             ↓
       persistence ports
             ↓
       SQLite Adapter
```

- application task 负责跨 Module 编排；Module 不访问彼此的 repository、表或私有函数。
- Module 只交换公开、不可变、类型化记录。
- 共享内核只允许 Money、SecurityId、时间和少量稳定标识；不建立膨胀的 common、utils 或 DTO 仓库。
- Port 只出现在真实变化 seam：外部 Provider 与 SQLite 均有生产和测试 Adapter；单一实现不建立投机 Interface。
- CLI、Skill、测试和未来展示调用同一个 application Interface。

## 6. Application Interface

| Operation | 输入 | 结果 | Mutation |
| --- | --- | --- | ---: |
| `account.confirm` | 用户确认的账户候选 | AccountSnapshot | 是 |
| `account.show` | 账户与可选截至时点 | 账户只读视图 | 否 |
| `research.commit` | Security、as_of、EvidenceSet、AI 研究候选 | InvestmentCase | 是 |
| `valuation.assess` | InvestmentCase、EvidenceSet、方法请求与假设 | ValuationAssessment | 是 |
| `planning.prepare` | InvestmentCase、ValuationAssessment、AccountSnapshot、风险政策 | RiskLimitResult、DecisionCard、TradePlanDraft | 是，单事务 |
| `planning.confirm` | draft_id、content_hash、用户明确确认 | TradePlan | 是，单事务 |
| `monitor.evaluate` | 活动 TradePlan 与最新 EvidenceSet | PlanEvaluation，可选 DecisionTask | 是，单事务 |
| `review.commit` | PROCESS 或 OUTCOME 复盘候选 | DecisionReview | 是 |

研究候选由 Skill 生成；Python 只校验和提交。估值数字、风险限制和计划规则结果只由 Python 生成。

所有 mutation 共用一个 application command 幂等记录：

```text
operation + idempotency_key + request_digest -> result_ref
```

同一 key 与同一请求返回原结果；同一 key 与不同请求返回 `IDEMPOTENCY_CONFLICT`。领域 Module 不再创建各自的 receipt 类型。

## 7. 事务、失败与持久化

- 一个 application operation 拥有一个短事务；领域 Module 不自行提交。
- 长时间 AI 研究不保持数据库事务；先形成候选，再短事务提交。
- SQLite 是唯一业务真值。
- JSON 是即时标准响应；Markdown 是按需只读投影。用户未明确导出时二者都不落地。
- 不保存 artifact manifest、lineage、HTML、PDF、workbook、复杂图表或重复报告目录。

稳定顶层失败只有：

- `INVALID_INPUT`
- `NOT_FOUND`
- `STALE_INPUT`
- `IDEMPOTENCY_CONFLICT`
- `PERSISTENCE_FAILURE`
- `INTERNAL_FAILURE`

数据缺失、估值不适用和风险无法判断属于正常 `insufficient` 结果，不属于异常。

## 8. Skill 结构

仓库只保留一个公开 `skills/SKILL.md`，由它路由到：

```text
skills/tasks/account.md
skills/tasks/research.md
skills/tasks/valuation.md
skills/tasks/planning.md
skills/tasks/monitoring.md
skills/tasks/review.md
```

每份 task 文档只描述一个 AI 工作流，使用明确输入、输出和停止条件。Instruction 是默认实现；只有确定性行为或外部工具调用才使用脚本。业务运行时不内置 LLM。

当前 `skills/SKILL.md` 描述已通过合成验收的唯一运行时任务合同。

## 9. 当前不包含量化研究平台

当前决策核心没有以下 Module、依赖或占位 Interface：

- Vibe-Trading 或其 MCP；
- Microsoft Qlib；
- 因子发现、因子库、alpha 挖掘或自动因子组合；
- 通用策略生成、Walk-Forward、回测、Bootstrap 或策略 Monte Carlo；
- vectorbt、Lean、PyPortfolioOpt、Riskfolio-Lib；
- 自动策略晋升、组合优化或模拟下单。

当前仓库历史研究的结论是：

- Vibe-Trading 的生产 MCP、通用 backtest、所谓 Walk-Forward、Bootstrap 和策略 Monte Carlo 已被拒绝；没有生产 Adapter、依赖或 allowlist。
- 信号滞后、PIT masking 和部分 A 股执行规则只作为历史 `adapt-code` 思路，不是当前能力，也不授权建立 StrategyValidation。
- Qlib 等完整量化栈为 `not_assessed / not_approved`，没有进入 live runtime。
- 当前代码中的“复权因子”是行情标准化输入，不是投资因子挖掘。

未来若要增加量化研究，必须由用户启动独立设计与证据调研，证明真实用户任务和两个 Adapter 后再决定 Module 与 seam；本设计不为其预留扩展点。

## 10. 测试分工

Python 测试只覆盖：

- 确定性公式与领域不变量；
- 账户、估值、风险和计划规则；
- application transaction 与幂等；
- SQLite 初始化、迁移和恢复；
- Fixture Adapter 合同；
- 通过 Application Interface 完成的合成端到端闭环。

Skill fixture/eval 覆盖：

- 事实、假设、估计和缺失的区分；
- 投资论点、反方和证伪条件；
- 局部缺失的合理降级；
- 数据捏造与金融输出越界；
- 过程评价与结果评价分离。

案例数量由风险边界决定，不固定数量。新 Interface 测试建立后，删除穿透旧私有实现的测试；测试不重复验证 AI 与 Python 各自不拥有的职责。

## 11. 单向替换与删除

执行顺序使用能力名称，不使用阶段编号：

1. **治理收敛**：本文接管权威，旧 Prompt、Fast Path、DSH 文档和重复 DOCX 删除。
2. **基线净化**：固定本仓库源码路径，以合成 fixture 替换真实标的示例，分类旧测试并冻结删除清单。
3. **模块构建**：六个 Module 与 Application Interface 分别实现并通过各自 Interface 测试，新路径暂不公开。
4. **合成切换演练**：仅在临时合成数据根完成初始化、迁移、失败注入、恢复和完整闭环。
5. **原子切换与删除**：同一变更切换 Skill、CLI、调用方和持久化，删除旧代码、schema、测试、fixture、文档和依赖。
6. **真实集成**：用户提供凭据后实现一个正式 Provider Adapter，备份并迁移真实数据根，完成真实验收。

不建立平行 V2、双读写、feature flag、转换兼容层或旧路径 fallback。不可安全删除时停止相应 seam，并记录精确 blocker。

当前实现与验收只使用虚构 Fixture Adapter 和隔离临时数据根；未访问或修改 `E:\trading-data\kong`。真实集成仍须由用户以后单独授权。

## 12. 迁移生命周期

- 开发只使用合成旧 schema fixture。
- 真实切换期间保留迁移工具、迁移前备份和回滚窗口。
- 所有明确数据根迁移、新格式备份恢复验证以及用户关闭回滚窗口后，schema 压成一个当前初始化基线。
- 随后删除旧 migration、临时迁移工具和旧 schema fixture；Git 历史承担代码归档。
- 没有用户明确授权时不删除真实备份。

## 13. 验收状态

进展只使用三个事实状态：

- **设计已确认**：本文、领域词汇和 ADR 已收敛。
- **合成通路已验证**：实现、合成闭环、迁移恢复、测试和旧路径清理全部通过，但真实 Provider 尚未验证；当前状态。
- **真实通路已验证**：真实 Provider、真实来源、真实数据根迁移和恢复通过。

这些状态不进入包名、类名、函数名、表名或领域记录。

“合成通路已验证”要求：六个 Module 与 Application Interface 完整、所有保留测试和 Skill eval 通过、合成端到端与恢复通过、SQLite 为唯一真值、搜索不到 retired symbol/命令/schema/测试/文档，且明确报告真实通路尚未验证。

## 14. 文档权威

- `AGENTS.md`：项目操作与安全规则。
- `docs/decision-core.md`：唯一产品、架构和验收基线。
- `CONTEXT.md`：唯一领域词汇表。
- `docs/adr/`：少量难以逆转的决定及原因。
- `skills/SKILL.md` 与 `skills/tasks/`：当前已实现的 AI 工作流。
- `README.md`：当前 live runtime 使用说明和设计状态入口。

规划文档不能证明实现；代码、公开 Interface 测试、迁移证据和最终 diff 才能证明实现状态。
