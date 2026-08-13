# Bridgewater PAT Research 与 DCF Valuation Governance 候选技能评估

日期：2026-08-01
审计基线：`848836ab44948058b6a2a022da16d10bf39018fd` 及当前工作树中的权威 `AGENTS.md`、`CONTEXT.md`
候选版本：`bridgewater-pat-research@1.0.1`、`dcf-valuation-governance@1.0.1`（`skills/.redskill-lock.json:4-18`）

## 1. 结论先行

两个候选都**不适合直接安装为本项目的 active Skill、CLI 或第二套业务运行时**，也都没有为本项目获取真实投研数据：

- `bridgewater-pat-research` 是一个“权限声明 + typed DataFrame DAG + 静态验证器”的公开参考实现。它没有数据连接器、权限执行器、代码执行沙箱、持久化缓存或生产编排器；研究数据必须由未随包提供的外部 permission harness 注入。最有价值的是字段级能力绑定、严格 DataFrame 语义、节点级 hash/后代失效、故障修复与 Teach 回归闭环。这些应当 **adapt** 到现有 `ResearchWorkflow`、`SourcePolicy`、`DataSnapshot`、`ArtifactManifest`，不能复制其平行的五套 schema 和脚本入口。
- `dcf-valuation-governance` 的公开实现只是读取本地 JSON 的三情景 FCFF 示例计算器，明确“不抓取市场数据”。它的文档方法论强于公开代码：假设档案、反证和 falsifier、独立复算、工作簿硬检查、不可变发布清单值得吸收；但公开 CLI 不验证来源、PIT、单位谱系或六道治理门，却能返回 `PASS`，不能成为项目的正式估值权限判定器。
- 项目现有流程在官方来源优先、PIT 冻结、公司类型路由、ACT/365 折现、股权桥、无校准证据不加权、缺数按方法降级、输出边界方面明显更强。候选的贡献主要是**把现有流程做得更细粒度、可复用、可挑战、可复算**，不是替换现有投研或估值引擎。
- 两个安装包的代码复用权都未达到可接受证据门槛。PAT 的 `NOTICE.md:20-24` 声称原创部分适用 MIT，但安装树没有实际 `LICENSE` 文本；DCF 安装树没有 `LICENSE` 或 `NOTICE`。在来源和许可证得到确认前，只能根据思想独立实现，不能复制代码或大段文档。

整体裁决：

| 对象 | 整包裁决 | 可吸收部分 | 不得进入项目的部分 |
|---|---|---|---|
| Bridgewater PAT Research | `reference-only`；直接运行路径 `reject` | 能力先绑定、typed DataFrame 契约、节点 hash/失效、结构化与非结构化证据分离、Teach 回归 | 平行 schema/CLI、运行时生成 Python、未提供的 permission harness、把静态 AST 当沙箱、把计划兼容当真实缓存复用 |
| DCF Valuation Governance | 文档 `reference-only`；公开 CLI `reject` | 假设档案、反证/falsifier、同一引擎的 WACC×g surface、独立复算验证、发布清单硬门 | 默认 25/50/25 权重、`target_price` 反推接口、整数年折现、单一 FCFF 套所有公司、无来源仍可 `PASS`、第二套估值计算器 |

这里的 `adopt` 表示保留并强化已经存在的项目原则；`adapt` 表示按项目现有类型和状态语义独立实现；`reference-only` 表示只能作为设计清单；`reject` 表示不得进入 canonical runtime。

## 2. 证据边界与审计方法

本次完整阅读了两个候选中的 Skill/README/AGENTS/SECURITY/NOTICE、references、schemas、scripts、examples、tests、安装标记和 RedSkill lock metadata；同时对照了：

- `AGENTS.md` 与 `docs/prompts/trading_platform_codex_prompt_optimized.md`；
- `CONTEXT.md` 的领域语言；
- `skills/SKILL.md`、`skills/tasks/equity-research.md`；
- `skills/references/source-manifest.md`、估值 router、行业矩阵与 DCF gate；
- 当前 `ResearchWorkflow`、冻结证据编译、财务模型输入编译、Forecast、ScenarioValuation、工业 DCF/reverse DCF、工作簿投影和测试。

按任务约束没有联网，也没有调用候选声称的数据源。因此：

- PAT 所列 LangChain 视频与 Bridgewater AI 风险页只被视为**候选声明的一手来源**，没有被本次审计确认仍在线、内容未变或与其 timestamp trace 完全一致。
- `scripts/verify_sources.py` 的通过只证明本地 manifest 与脚本内硬编码常量一致，并确认被排除的第三方文件没有随包分发；该脚本自己明确“不重新下载或认证第三方内容”（`references/source-boundary.md:36`）。
- DCF README 中“31/31、24 sheets、10,358 formulas”等数字明确属于未公开的私有系统，不是公开 CLI 的验收证据（`README.md:17-29`）。本报告不把这些数字当成已验证能力。

候选声明的外部架构来源：

- [LangChain: How Bridgewater Built an AI Analyst...](https://www.youtube.com/watch?v=lXZb21CfeIY)
- [Bridgewater: Risks Associated with Use of AI Tools](https://www.bridgewater.com/risks-associated-with-use-of-ai-tools)

以上链接来自候选 `NOTICE.md:9-16`，本次未联网复核。

## 3. 两个候选的数据究竟如何获取

### 3.1 Bridgewater PAT Research

它包含两类“数据”，必须分开看。

第一类是**构建该候选时使用的公开架构材料**：

- 本地 manifest 记录视频元数据、英文字幕 hash、Bridgewater 网页 hash 和 timestamp mapping；
- 完整字幕、逐字稿、译稿、网页 HTML 和原始抓取元数据均被排除（`references/source-manifest.json:21-68`）；
- `verify_sources.py` 只把 manifest 字段与硬编码 hash/视频 ID 对比，并检查排除文件不存在（`scripts/verify_sources.py:20-90`），不访问网络也不重算第三方原始文件 hash。

第二类是**用户真正研究时所需的市场、宏观、公司和文档数据**：

1. `research-request.v1` 由调用方声明允许使用的 dataset、document collection、tool、版本和字段；只保存 capability reference，不保存凭据（`SKILL.md:35-43`）。
2. 计划把这些声明编译为一个 typed DataFrame DAG。
3. 候选不提供 connector 或 fetcher。外部 permission harness 应先解析资源，再把输入 receipt 注入 task；生成代码被要求只能转换已注入输入，不能打开文件、联网、调用 broker、起进程或写数据（`SKILL.md:90-102`）。
4. 对外部 capability 的 receipt hash 实际只对 `{id, version, fields}` 做 canonical JSON SHA-256，并不绑定下载响应或输入 artifact 的真实字节（`scripts/pat_core.py:1071-1084`）。这意味着它能检查“声明与 receipt 一致”，不能证明“收到的数据就是该版本的数据”。

所以 PAT **没有获取真实数据**；它定义的是数据进入分析前后的声明和校验边界。它也没有本项目所需的 official/structured/secondary 权威等级、published/available/retrieved 三时点、raw payload hash、provider terms/rights、失败重试和 provider qualification。

### 3.2 DCF Valuation Governance

公开 CLI 的数据路径更简单：

1. 从 `--input` 指定的本地 JSON 文件读取 case；
2. case 内直接提供 bear/base/bull 三组 revenue、margin、tax、D&A、CapEx、NWC、WACC、g、概率和股权桥；
3. 在内存中计算 FCFF、Gordon terminal value、EV、equity value、per-share、概率加权值和 5×5 WACC×g 表；
4. JSON 输出到 stdout。

脚本开头明确写明“不抓取市场数据，也不替代 integrated production workbook”（`skill/dcf-valuation-governance/scripts/dcf_cli.py:2-6`），case reference 也重复这一点（`references/case-schema.md:1-35`）。公开 schema 没有 `source_id`、来源等级、published/available/retrieved、raw hash、会计口径、单位 scale、PIT 截止或来源授权字段。

Skill 文档要求历史事实追溯到 primary disclosures，并要求 evidence/assumption dossier（`SKILL.md:28-32`），但公开 CLI 没有实现该门。换言之，它是**用户手工准备输入的透明演示计算器**，不是数据采集或正式模型治理系统。

### 3.3 本项目当前的真实数据路径

本项目已有候选不具备的数据运行链：

- Tushare-compatible provider 负责结构化市场和财务索引，但固定标记为 `structured_aggregator`、非官方证据；provider runtime、SourcePolicy、rights、adapter identity 和失败码均为 typed contract（`src/trading_platform/provider_config.py:74-159`、`src/trading_platform/data/providers.py:198-287`）。
- SZSE/CNINFO adapters 负责精确 issuer 解析、公告发现和 PDF 获取（`src/trading_platform/data/official_disclosures.py:152-478,494-869`）。
- 数据按 Raw → Normalized → Derived → Artifacts 分层；研究输入冻结为 `DataSnapshot`。当前 evaluation 会核验 snapshot、scope、purpose、effective session、quality 和 `available_at <= as_of cutoff`（`src/trading_platform/research/evaluation.py:117-142`）。
- source manifest 保留真实 source authority、URL/API、retrieved_at、available_at、published_at 和字段覆盖（`src/trading_platform/research/evaluation.py:147-220`）。关键数字必须 `source_id` 覆盖或明确 missing；缺失官方来源只禁用依赖它的方法，不伪造数据（`skills/references/source-manifest.md:90-108`）。

因此候选的 capability binding 应当增强现有 SourcePolicy/DataSnapshot，而不是替换现有 provider、manifest 或冻结证据链。

## 4. Bridgewater PAT Research 深度评估

### 4.1 输入、输出与工作流

候选定义五个版本化对象，JSON Schema 只描述 interchange shape，Python validator 才是其接受权威（`references/contracts.md:1-3`）：

| 对象 | 主要内容 | 候选状态/门 |
|---|---|---|
| `research-request.v1` | 身份、research-only 目标、as_of、dataset/document/tool capability 与字段范围 | 权限和语义先闭合 |
| `analysis-plan.v1` | typed task DAG；每个 task 一个 DataFrame，含 grain、PK、column dtype/unit/frequency/currency/semantic/nullability | 编译时拒绝 cycle、orphan、未授权字段和版本偏差 |
| `task-result.v1` | 代码文本/hash、输入 receipts、materialized rows/hash、七类 validator receipt、cache receipt、lineage | 所有 validator 声明 PASS 才接受 |
| `research-package.v1` | conclusions、task results、DataFrames、charts、sources、diagnostics、lineage、execution trace、AI risk notice | 所有引用可解析且每个 task 恰有一个 passing receipt 才 `RESEARCH_READY` |
| `teach-case.v1` | 最小失败输入、复现 hash、修复提议、focused/full regression receipt | 只到 `PR_REVIEW_REQUIRED`，不自动修改生产 |

其流程是：澄清问题 → 先绑定 capability → 建 typed natural-language Python project → 编译 DAG/权限/hash → 每次只给 Coding Agent 一个 task → 外部普通运行时执行 → 验证/局部修复 → 静态 cache impact → 打包 research-only 结果 → 人工 review Teach case（`SKILL.md:35-145`）。

### 4.2 真正优势

1. **计划本身是可验证产品。** DataFrame 的 grain、主键、频率、单位、币种、语义和 nullable 在执行前闭合，能减少“同名字段、不同含义”或跨频率/币种静默 join。
2. **先权限后计划。** dataset/document/tool 的字段范围和版本先绑定，deny 不得通过错误信息、代码、lineage 或 cache metadata 泄露。这一模式能补强项目当前以 dataset/source route 为主、字段级 entitlement 尚不够显式的部分。
3. **结构化与非结构化证据分离。** 文档先提取为 typed claims DataFrame，再与时间序列 join；叙述不能静默覆盖数值（`references/investment-research-patterns.md:14-16`）。这非常适合官方公告语义事实与 Tushare 结构化数值并行的 A 股流程。
4. **节点级变更影响分析。** task plan hash 绑定 task slice、capability digest、as_of 和上游 task-plan hashes；下游图表变化理论上不应让上游计算全部重跑（`references/contracts.md:48`）。
5. **诊断和修复以最小层为单位。** 它把 schema、range、frequency、currency、dimension、prior 分开，失败不能被统一抹成一个 generic error。
6. **Teach 是 review-only 回归闭环。** 用户纠正先形成最小失败样例和 focused/full regression evidence，不直接自我修改生产逻辑。
7. **来源声明层级清楚。** `pat-architecture-trace.md` 区分 `explicit_talk` 与 `local_implementation_guard`，避免把公开演讲扩张成私有系统事实。

### 4.3 必须正视的缺口

1. **没有生产数据和执行实现。** 候选自己明确 `PAT_SKILL_VALIDATED` 不证明 real data access、model correctness、persistent orchestration、real cache replay 或 production readiness（`SKILL.md:182`）。
2. **receipt 不是可信数据证明。** 外部数据 hash 只绑定能力声明，不绑定真实 bytes；receipt 也没有签名、trusted issuer 或与本项目 raw/normalized artifact 的关联。
3. **七类 validation 中多项是自证。** contract validator 对 schema、PK、missingness 和部分类型可重算，但 range/frequency/currency/dimension/prior 主要只检查调用方提供 `status: PASS` 和非空 evidence；文档也承认 domain range/prior 没有被 contract validator 独立重跑（`references/contracts.md:50-62`、`scripts/pat_core.py:1148-1172`）。
4. **静态 AST denylist 不是沙箱。** `_validate_generated_source` 解析 AST 并禁止部分 imports/calls/attributes（`scripts/pat_core.py:859-970`），但没有实际运行隔离、资源限额、包版本锁定或副作用证明。项目 deterministic business runtime 不应执行模型生成代码。
5. **没有真实 cache。** analyzer 只返回 `plan_compatible_task_ids`，`reusable_task_ids` 固定为空，状态为 `RECEIPT_MATCH_REQUIRED`（`scripts/pat_core.py:1333-1354`）。它没有 cache store、TTL、读取、原子提交或 replay。
6. **结论证据只做引用完整性。** package validator 检查 evidence ref 能解析，不检查 evidence 是否语义上支持结论（`scripts/pat_core.py:1770-1790`）。
7. **安装包不完整。** `validate_schemas.py` 固定读取 `examples/validated-oil-investigation/*`（`scripts/validate_schemas.py:13-21,37-50`），但该目录未随安装包提供，导致 schema/release suite 无法通过。`validate_public_release.py:144-211` 的大多数 CLI acceptance 同样依赖该缺失目录。
8. **会制造第二控制面。** 五套候选 schema、多个 CLI 脚本和 `RESEARCH_READY` 状态与项目 `skills/SKILL.md`、application task、`ResearchEvaluationBundle`、`completed_with_limits` 重叠，直接采用违反 one canonical path 和 no compatibility code。

## 5. DCF Valuation Governance 深度评估

### 5.1 文档方法论

文档要求先按公司类型路由：普通经营公司 FCFF；金融机构 FCFE/DDM/residual income/fair-PB；地产/资源 NAV 或 SOTP；复杂分部 SOTP（`references/valuation-routing.md:7-14`）。随后要求：

- primary disclosure evidence dossier；
- 每个重大假设有 base、bear/base/bull range、evidence、counter-evidence 和 falsifier；
- FCFF 必须由经营模型桥接，不接受无来源的独立现金流序列；
- sensitivity、独立复算、公式错误扫描、run manifest/hash；
- 六道 gate 全通过才 `PASS`，否则 `DRAFT_REVIEW` 或 `BLOCKED`（`references/governance-gates.md:3-41`）。

这套治理叙述与项目方向高度一致，尤其“反证 + falsifier”和“发布前独立复算”比项目当前默认展示更明确。

### 5.2 公开实现实际做了什么

公开 CLI 只实现普通 FCFF：

- `NOPAT = EBIT × (1-tax)`；
- `FCFF = NOPAT + D&A - CapEx - ΔNWC`；
- 每年末整数年折现；
- Gordon growth terminal value；
- EV 减 net debt/minority、加 non-operating investments，再除 diluted shares；
- 三情景概率加权；
- base case 以 WACC ±0.5/1.0%、g ±0.5/1.0% 生成 5×5 surface（`dcf_cli.py:125-233`）；
- reverse 模式从名为 `target_price` 的输入反推 implied terminal growth（`dcf_cli.py:239-273`）。

结构校验覆盖有限数值、三情景齐全、数组等长、概率和为 1、`WACC > g`、正 diluted shares、汇率缺失警告和 terminal share >80% 警告（`dcf_cli.py:49-122,217-235`）。

### 5.3 真正优势

1. **假设档案强调可挑战性。** evidence 之外还要求 counter-evidence、falsifier 和“什么会改变结论”，适合将模型从静态输入表提升为可复核研究判断。
2. **WACC×g surface 可直接暴露 terminal assumptions 的非线性。** 中心格与 base 值一致的单测是简洁有效的模型一致性门。
3. **独立复算和发布清单。** 验证器与工作簿 writer 分离、公式 token scan、输入/运行时/产物 hash 绑定，是比“文件成功生成”更强的发布语义。
4. **24-module workbook contract 是完整性 checklist。** 它覆盖 sources、assumptions、operating schedules、FCFF、equity bridge、sensitivity、reverse DCF 和 release checks；适合作为缺口审计清单，不适合机械复制 24 个 sheet。
5. **reverse DCF 被视为挑战模型的工具。** 这与项目“市场预期诊断，而非正式内在价值结论”的方向一致。

### 5.4 必须拒绝或修正的部分

1. **文档 PASS 与 CLI PASS 冲突。** 文档要求六道 gate 和独立复算；CLI `validate` 只做 JSON 结构校验就返回 `PASS`（`dcf_cli.py:287-310`）。因此 CLI status 不能映射到项目正式输出权限。
2. **没有来源/PIT/单位谱系。** 一个用户手填或合成 case 可直接产生 per-share 与概率加权值；这与项目 official evidence 和 selected-method gate 冲突。
3. **默认概率不可接受。** synthetic case 的 0.25/0.50/0.25 没有校准证据。项目要求没有完整 calibration evidence 就保持 `conditional_only`，不允许默认 base probability（`skills/valuation/valuation-method-router.md:140-148`）。
4. **整数年折现弱于现有引擎。** 候选用 `(1+wacc)^year`；项目 canonical industrial DCF 为 `fcff_dcf_act365@3`，按 valuation date 到 period end 的实际日数/365 折现（`scenario_valuation/basis.py:403-429`、`industrial.py:42,248-280`）。
5. **经营模型不够 integrated。** revenue 与若干比率数组直接生成 FCFF，缺少项目 ForecastGraph 的结构、单位、lineage、opening/terminal bridge、现金债务滚动和公司类型深模块。
6. **公司类型只写在文档里。** 公开代码只有 FCFF；FCFE、DDM、residual income、fair-PB、NAV、SOTP 和资源/生物医药方法均未实现。
7. **`target_price` 命名违反默认金融输出边界。** reverse DCF 应继续使用项目现有的 observed PIT enterprise value，并输出“market-implied expectation diagnostic”，不能新增 target-price CLI 或结论。
8. **terminal share 80% 只能是诊断，不是唯一 hard gate。** 项目现有 methodology 已正确把它当模型脆弱性提示，并要求 cross-check；不能因阈值自动把模型事实化或否定。
9. **不能增加第三套 DCF。** 当前 legacy `equity_research/valuation.py:480-527` 已有 5×5 surface，canonical ScenarioValuation 则输出低/中/高三点 sensitivity。正确动作是把能力收敛到同一 canonical scenario engine/view/workbook，再删除被替代的重复计算，而不是复制候选 CLI。

## 6. 与本项目当前流程的充分对照

| 维度 | 本项目当前 canonical 方向 | PAT 候选 | DCF 候选 | 结论 |
|---|---|---|---|---|
| 入口 | `skills/SKILL.md` → application task → `ResearchWorkflow` | 自带 Skill 与多个 validator/compile CLI | 自带 Skill 与 `dcf_cli.py` | 两个候选入口均 `reject` |
| 数据获取 | Tushare-compatible structured + SZSE/CNINFO official adapters；provider rights/policy/qualification | 无 connector；外部 harness 注入 | 无 connector；本地 JSON | 保留项目路径；PAT capability 语义 `adapt` |
| 来源权威 | official/structured/secondary，关键字段 official-first | capability id/version/fields，无官方等级 | prose 要 primary，schema/CLI 不执行 | 项目明显更强 |
| PIT | frozen snapshot；published/available/retrieved；`available_at <= as_of` | request 有 as_of，但外部 receipt 不绑定真实 artifact/timestamps | 只有 valuation_date 字符串 | 不采用候选事实权限 |
| 领域分类 | Fact/Assumption/Forecast/Valuation；origin 五态 | task/dataframe/lineage，来源语义较弱 | 文档有 evidence/assumption，代码无分类 | DCF dossier `adapt` 到现有领域语言 |
| 工作流 | workflow v6 仍只有 `evaluate_research` 与 `publish_run_manifest` 两个 persisted nodes；前者已绑定闭合 plan/receipt，但尚无计划节点级 checkpoint | typed DAG、node hash、后代失效 | 顺序 CLI | PAT 是明确的细粒度改进来源 |
| 缓存/恢复 | `evaluate_research` 有整体 fingerprint/checkpoint；resume/replay/lease 已实现 | 静态 impact 有设计，无真实 cache/replay | 无 | 将 node hash 语义内化到现有 ledger |
| 类型与维度 | ForecastQuantity/SourceEvidence/typed contracts；exact Decimal 与 lineage | DataFrame schema 很严格 | Python float + 松散 JSON | PAT typed columns `adapt`；DCF float 不采用 |
| 投研组织 | frozen evidence → ResearchEngine → Forecast/ScenarioValuation/decisions → DecisionView | 计划—执行—验证—修复—报告—Teach | 只有估值 case | PAT 只补分析计划与反馈闭环 |
| 估值路由 | 公司类型、数据门、selected-method inputs 决定 DCF/financial/rNPV/SOTP/mid-cycle 等 | 不负责估值 | 文档路由一致，代码只有 FCFF | 保留项目 router；文档 `adopt` 为检查清单 |
| DCF 输入 | integrated ForecastGraph、exact WACC components、terminal assumptions、完整 equity bridge | 不适用 | 独立 ratio arrays 与简化 bridge | 候选计算器 `reject` |
| 折现 | ACT/365、PIT as_of | 不适用 | 整数年末 | 保留项目 |
| 情景 | `stress/base/improvement` 互斥 partition | DAG 可承载任意 frame | `bear/base/bull` | 不加 alias/兼容层；保留项目语言 |
| 概率 | 无证据 `conditional_only`；证据需同 partition/horizon/as_of/calibration，精确和为 1（`scenario_valuation/engine.py:240-366`） | 无估值概率治理 | case 强制概率且总是输出 weighted | DCF 默认权重 `reject` |
| reverse DCF | observed PIT enterprise value → implied g，市场预期诊断 | 不适用 | `target_price` → implied g | 保留项目接口和语义 |
| sensitivity | 文档要求 WACC×g；legacy 有 5×5；canonical scenario result 目前主要是三点 | 不适用 | 5×5 已实现并有 center test | 只吸收 surface contract/test，统一到现有引擎 |
| 工作簿 | `ResearchDecisionView@2` → 6-sheet workbook；公式 error scan、bridge reconciliation；renderer 缺失返回 typed limitation | chart contract 但无 renderer | 24-module 文档；公开实现不生成 workbook | 选择性 `adapt`，不机械追求 24 sheets |
| 发布 | ArtifactManifest、formula/model identity、ready/limited/blocked | package refs/hash；AI risk | 文档 run manifest/hash；CLI 无 manifest | 强化现有 manifest，不加第二 package |
| 失败语义 | typed code；按能力/方法降级，完整报告可 `completed_with_limits` | 多 validator code，但大量自证 receipt | BLOCKED/DRAFT/PASS，粒度粗 | 保留项目状态；吸收具体诊断 |
| 安全 | 凭据适配器隔离；runtime 不依赖 LLM；输出边界 | 不存凭据，但生成代码与外部 runtime 未实现 | stdlib、本地 JSON；SECURITY 禁私密 case | 不执行候选生成代码，不复制 CLI |
| 许可 | 项目需维护 notices 和依赖身份 | NOTICE 宣称 MIT，缺 LICENSE | 无许可证文本 | 许可确认前只独立实现思想 |

## 7. 建议吸收矩阵

### 7.1 `adopt`：保留并写成验收标准，不另造实现

| 方法 | 理由 | 项目落点 |
|---|---|---|
| structured/unstructured evidence 分开，先 typed extraction 再 join | 防止公告叙述覆盖结构化数值 | 现有 official filing extraction + `SnapshotEvidence`/source manifest |
| 公司类型先路由、DCF 非默认 | 项目已有更严格 router | `valuation-method-router.md` 与 ScenarioValuation deep modules |
| reverse DCF 是预期诊断 | 项目已使用 observed enterprise value，语义更安全 | `IndustrialScenarioEvaluator._reverse_dcf` |
| missing 不填零、按依赖方法降级 | 与项目 `data_insufficient` 一致 | source manifest、ResearchEngine、DecisionView |
| 工作簿公式错误与 bridge reconciliation 必须通过 | 当前已有实现 | `ValuationWorkbookAdapter` 与 `render_valuation_xlsx.mjs` |

### 7.2 `adapt`：候选最值得进入产品的增量

1. **FieldCapabilityBinding**
   - 从现有 `SourcePolicy.routes`、provider qualification、dataset schema 和用户权限派生 dataset/field/version scope；
   - binding 只存 identity/hash，不存凭据；
   - 纳入 `ResearchEvaluationPlan.identity` 和 node fingerprint；
   - denied 字段不得出现在 diagnostics、artifact、lineage 或 cache metadata。

2. **Canonical node plan 与后代失效**
   - 由 application 内部根据已闭合的 `ResearchEvaluationPlan` 编译，调用方不能提交任意 DAG；
   - 只沿有独立产物、事务和失败语义的深模块切节点，例如：冻结证据/模型输入编译、Forecast、ScenarioValuation、decision composition、artifact projection、manifest publication；
   - node receipt 必须绑定真实 snapshot member/raw-normalized hash、as_of、source policy/capability digest、代码/公式版本、上游 artifact hash 和输出 hash，而不是 PAT 的 `{id,version,fields}` 自证 hash；
   - 一个 presentation-only 改动只失效 view/artifact 后代，source/as_of/model 输入改动失效所有依赖后代；
   - 持久化和 resume/replay 继续使用现有 workflow ledger，不创建 PAT cache service。

3. **Assumption dossier / challenge contract**
   - 扩展现有 Forecast/ValuationAssumption，而不是增加 DCF case schema；
   - material assumption 应包含 origin、base/low/high、evidence refs、counter-evidence refs、falsifier/invalidation、review date、owner/model identity；
   - `observed_official` 事实不能被 assumption 覆盖；estimated 必须继续经过 bounded-estimate/calibration gate；
   - dossier 不完整只限制依赖它的方法或结论权限，不把整个研究包抹成失败。

4. **Canonical `SensitivitySurface`**
   - 从同一个 ACT/365、exact Decimal、typed equity bridge 计算内核投影 WACC×g surface；不得调用候选 CLI，也不得保留 legacy/canonical/候选三套公式；
   - 每格携带 WACC/g quantity identity、币种、scale、period、as_of、lineage 和 `WACC > g` 可行状态；
   - center cell 必须精确 reconcile 到 base DCF；不可行格显示 typed `not_applicable`，不是 0；
   - 将 surface 放入 canonical ScenarioMethodResult/DecisionView 后再投影 HTML/PDF/workbook。

5. **Independent recalculation receipt**
   - verifier 可以独立重算作“验证”，但不能成为第二个对外估值路径；
   - 复算输入只来自 canonical typed quantities，结果只产生 match/mismatch、容差和 hash receipt；
   - mismatch 阻止 workbook/release 晋级，不静默选择任一版本；
   - workbook renderer 不可用继续输出 typed limitation，不让辅助格式阻塞仍然有效的研究正文。

6. **Teach-style review cases**
   - 用户纠正转化为脱敏的最小失败 fixture、focused test、full regression 和 tracker item；
   - 必须 review 后才进入代码；不运行时自我修改、不保存私人持仓/凭据、不把真实公司受限材料放入 fixture。

7. **Source-claim trace**
   - 研究方法引用应区分 external-primary、external-secondary、local-implementation、inference；
   - 该层级可纳入研究方法文档和 ArtifactManifest，不应成为第二个 source manifest schema。

### 7.3 `reference-only`

- PAT 的 Chat Agent/Coding Agent 分工：可用于 Codex control-plane 任务分工，但生产 runtime 不执行生成代码。
- PAT 的五套 JSON Schema：可作为 edge-case checklist，不作为项目新协议。
- DCF 24-module workbook：用来查漏，不要求 24 sheet，也不能引用私有 10,358 formulas 为验收。
- DCF 私有引擎回归数字：无源码/产物/运行记录，不能用于项目能力声明。

### 7.4 `reject`

- 在 `skills/` 下保留第二 active entry，或 README/测试继续教用户调用候选 CLI；
- 运行 PAT 生成的 Python/Pandas 作为业务 runtime；
- 用 self-attested receipt、静态 AST 或引用可解析性替代真实数据 hash、sandbox 和语义验证；
- 直接使用 DCF CLI 的 `PASS`、概率加权 per-share、`target_price`；
- 给 `bear/bull` 增加兼容 alias；项目继续使用 `stress/base/improvement`；
- 复制许可证未确认的候选代码或文档；
- 为兼容候选保留双 schema、双 read/write、wrapper 或 fallback。

## 8. 融入当前工作流的目标形态

保持用户路径不变：

```text
自然语言任务 / Skill
  -> canonical application task
  -> ResearchWorkflowRequest@2 + closed ResearchEvaluationPlan
  -> SourcePolicy + frozen DataSnapshot + FieldCapabilityBinding
  -> application-owned typed node plan
       evidence/input compile
       -> Forecast
       -> routed ScenarioValuation + SensitivitySurface
       -> DecisionView
       -> JSON / HTML / PDF / workbook projections
  -> ArtifactManifest + node/recalculation receipts
```

关键约束：

- plan 由应用根据 task type、公司 archetype、数据可用性和风险约束确定性生成；LLM/Codex 只负责控制面解释和资料组织，不生成数值公式或 runtime Python。
- public interface 仍只有现有 task，persistence 仍只有 workflow ledger/artifact repository，presentation 仍只读 `ResearchDecisionView`。
- 本次 implemented slice 已把 workflow v5 一次性替换为 workflow v6 /
  `evaluate_research@4`，并在同一个 persisted node 中绑定单次编译的闭合 plan
  与执行 receipt；计划内部节点仍未成为独立 checkpoint。后续节点化必须继续做
  versioned one-way migration，并在同一变更删除被替代的 node contract/测试。
- 工作簿目前已经有 Summary、Canonical Inputs、Bridge Trace、Reconciliation、Sources Audit、Checks 六页，并执行 formula token scan 和 reconciliation（`scripts/render_valuation_xlsx.mjs:25-31,253-275,322-349`）。新增的 assumption challenge、sensitivity surface、release receipt 应按 progressive disclosure 加到同一 projector；不要另造一个 DCF workbook renderer。

## 9. 建议实施顺序与验收条件

### 阶段 A：权威与许可

1. 把本报告作为 adoption evidence，确认候选上游身份、版本与许可证。
2. 未确认前不复制候选源码；若候选目录只是临时安装物，最终 change 应把它们移出 active `skills/`，并同步清理 `skills/.redskill-lock.json` 中相应条目。
3. 在 `skills/SKILL.md` 和 application task 中只描述最终 canonical path。

### 阶段 B：能力绑定与 node receipts

验收：

- 未授权 dataset/field/version 在 plan compile 前失败，且 diagnostics 不泄露 denied 内容；
- receipt 绑定真实 snapshot/artifact hash；修改 bytes 但不改 capability version 也必须失效；
- 修改 as_of、source policy、model/formula identity 或上游 output 会失效所有依赖后代；
- 只改 report layout 不重算 Forecast/ScenarioValuation；
- crash 后从已提交节点恢复，未提交输出不被当成 cache hit。

### 阶段 C：假设挑战与 DCF surface

验收：

- 每个 material assumption 都有 evidence/counter-evidence/falsifier/invalidation；缺失时只限制相关方法；
- source origin 不被 assumption 升格，关键 official fact 缺失仍禁止 formal valuation；
- WACC×g center 与 base DCF exact reconcile；所有格使用 ACT/365、同一 equity bridge、相同 currency/scale/as_of；
- `WACC <= g` 为 typed infeasible，不填 0；
- 无 probability evidence 时没有 probability-weighted output；
- reverse DCF 只接收 observed PIT enterprise value，不出现 target-price conclusion。

### 阶段 D：工作簿、复算与发布

验收：

- independent recalculation mismatch 阻止 workbook/release 标记 ready，并保留具体差异；
- workbook formula scan、bridge、per-share、surface center 均可重算；
- renderer timeout/缺失只产生一个 typed limitation artifact；
- manifest 绑定 source revisions、plan/node/model/formula identity、artifact hashes 和 recalculation receipt；
- JSON/HTML/PDF/workbook 对 readiness、missing、conditional_only 的表达一致；
- 默认输出不含 BUY/HOLD/SELL、买入/卖出/持有、target price、默认概率目标或个性化动作。

### 阶段 E：Teach 回归与清理

验收：

- 纠错样例已脱敏，focused/full tests 通过后才合入；
- 搜索并删除候选 CLI、schema、status 名称、bear/bull alias、重复 DCF 公式、过时文档和 fixtures；
- 最终只有一个 application path、一个估值引擎、一个 persistence path、一个 DecisionView/projector family。

## 10. 本次可复现验证

所有 Python 命令均禁用 bytecode 写入；没有网络请求。

| 目录 | 命令 | 结果 | 能证明什么 / 不能证明什么 |
|---|---|---|---|
| `skills/bridgewater-pat-research` | `python -B -X utf8 scripts\verify_sources.py` | exit 0；`PUBLIC_SOURCE_REFERENCE_PASS`，21 timestamp rows，5 excluded artifacts | 只证明本地 reference manifest/常量一致及排除文件未分发；不认证线上来源 |
| 同上 | `python -B -X utf8 scripts\check_purity.py .` | exit 0；`purity: PASS` | 证明该静态扫描规则未发现私有依赖；不证明生成代码运行安全 |
| 同上 | `python -B -X utf8 scripts\validate_schemas.py` | exit 1；缺少 `examples/validated-oil-investigation/request.json` | 安装包缺失其公开验收依赖的 fixtures，schema suite 不可运行 |
| 同上 | `PYTHONDONTWRITEBYTECODE=1; python -B -X utf8 scripts\self_test.py` | 沙箱外复跑 `LOCAL_SELF_TEST_PASS`，91/91 passed | 证明候选本地静态/契约 self-test 自洽；不证明真实数据、permission harness、生产 cache、代码执行隔离或研究结论正确 |
| `skills/dcf-valuation-governance` | `python -B -X utf8 -m unittest discover -s tests -v` | 8/8 passed，0 failed，约 0.004s | 证明 synthetic calculator 的八个 mechanics regression 通过；不证明真实数据、工作簿或治理门 |
| 同上 | `python -B -X utf8 ...\dcf_cli.py validate --input examples\synthetic-consumer-case.json` | exit 0；`PASS`、无 warning | 暴露 CLI PASS 只依赖结构校验 |
| 同上 | `python -B -X utf8 ...\dcf_cli.py run --input examples\synthetic-consumer-case.json` | exit 0；`DRAFT_REVIEW`；terminal share >80% warning | 证明公开 FCFF、加权值和 5×5 mechanics 可运行；输入是 synthetic，无来源权限 |
| 同上 | `python -B -X utf8 ...\dcf_cli.py reverse --input examples\synthetic-consumer-case.json --target-price 42` | exit 0；implied g `0.07162031` | 只证明代数反推；其接口命名和输入语义不应进入项目 |

初次沙箱运行产生的五个 `pat-*` 临时目录已按确切路径清理；最终沙箱外
self-test 为 91/91。候选目录未被修改，既有 dirty/untracked 工作未被处理。

## 11. 最终建议

最合理的 adoption 不是“把两个 Skill 接到项目里”，而是一次**现有 canonical path 的纵向深化**：

1. 用 PAT 的 capability/DataFrame/node-receipt 思想细化现有 SourcePolicy、ResearchEvaluationPlan 和 workflow ledger；
2. 用 DCF skill 的 assumption challenge、independent recalc、release checklist 强化现有 Forecast/ScenarioValuation/DecisionWorkbook；
3. 把项目文档已经要求、legacy 代码已有、canonical view 尚未统一的 WACC×g surface 收敛进同一 ACT/365 typed DCF deep module；
4. 保持官方来源/PIT、conditional-only、data-insufficient 和金融输出边界不变；
5. 完成 one-way migration 后删除候选运行入口和所有重复估值路径。

这样可以获得两个候选最实用的优点，同时避免数据来源虚假、PASS 语义降级、第三套 DCF、运行时生成代码、许可证不明和长期兼容层。
