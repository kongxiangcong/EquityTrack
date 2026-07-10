# UZI-Skill 上游研究与本地根接口建议

> 研究对象：`wbh604/UZI-Skill`
> 固定快照：[`fce996c33e70eddce8e375f53cd252b549eb3d7c`](https://github.com/wbh604/UZI-Skill/commit/fce996c33e70eddce8e375f53cd252b549eb3d7c)（2026-07-07，`fix flow and data contract regressions (#85)`）
> 本地只读副本：`.research/upstreams/UZI-Skill`
> 证据边界：只使用该固定提交的源码、README、仓库文档、测试及 Git 提交元数据；没有把 README 的宣传数字当作已验证事实。

## 结论先行

UZI-Skill 已经不是一个纯 prompt 仓库。它包含一键 CLI、数据 provider chain、结构化采集结果、并发 pipeline、确定性打分与估值函数、可恢复缓存、机械自查、HTML/SVG 渲染以及较大的回归测试集。它证明了“个人投研默认一条命令就能得到可看的 HTML”在工程上可行。

但它也不是可直接照搬的机构级估值或交易决策引擎。当前主路径仍是新旧实现混合：新 pipeline 的 21 个 fetcher 都只是 legacy `fetch_*.py` 的 adapter，最终 synthesis/render 仍委托 legacy `stage2`。更关键的是，DCF 会用收入、净利率甚至市值反推 FCF，LBO 的入场价格不取当前 EV，缺失数据会得到中性甚至“安全”分，最终还会按现价比例自动生成买入区间、50% 起步仓位、止损和目标位。这些行为与本地项目的来源门禁、方法适用性和非投资建议边界不兼容。

对本地重构最有价值的启示是：保留严谨性，但把它放进一个深的根模块；普通调用只需要 `analyze("002897.SZ")`。数据缺口应只禁用依赖该数据的能力，不应再让 Task 1 的一个全局布尔值阻断整个研究流程。

## 1. 仓库事实与成熟度

- 固定快照共有 225 个提交、434 个 tracked files、197 个 Python 文件和 81 个 Markdown 文件。首个提交是 2026-04-16 的 `v2.0.0`，三个月内迭代很快；这也解释了明显的文档漂移。
- 根 `SKILL.md` 将请求路由到 `deep-analysis`、`investor-panel`、`lhb-analyzer`、`trap-detector` 或具体 command，并明确要求选择最窄工作流；同时给出一键 CLI。这是一个有效的顶层分流思路。[`SKILL.md:14-47`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/SKILL.md#L14-L47)
- 版本元数据并不完全一致：根 `SKILL.md` 仍写 `3.9.1`，[`SKILL.md:1-9`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/SKILL.md#L1-L9)，而 package manifest 是 `3.9.2`，[`package.json:1-4`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/package.json#L1-L4)。README、skill 和源码中也同时出现 50、51、52、65、66 位评委等不同口径。
- HEAD 本身就是一次 flow/data-contract 回归修复，改动 20 个文件并新增 182 行回归测试；说明项目有真实用户反馈驱动的维护能力，也说明接口和数据形状仍在频繁变化。[`test_v3_9_2_flow_bugfixes.py:1-66`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/tests/test_v3_9_2_flow_bugfixes.py#L1-L66)

## 2. Skill 组织：有效的路由，过重的实现平面

### 2.1 实际分层

| 层 | 实际职责 | 判断 |
|---|---|---|
| 根 skill | 根据自然语言选择深度分析、评委、龙虎榜、反欺诈或专项 command | 路由清晰，但只是文档约定，不是可验证的结构化接口 |
| `commands/*.md` | 给 agent 具体 shell、文件读写、sub-agent 数量和 JSON 修改步骤 | 把流程实现复制进多个 prompt，容易漂移 |
| `skills/deep-analysis/SKILL.md` | 同时承担角色、状态机、门禁、数据补全、agent 编排、产物 schema 和完成定义 | 是控制平面，也是实现平面，调用者必须学习太多顺序约束 |
| `run.py` | 面向普通用户的一键入口，参数解析、依赖安装、环境探测、pipeline/legacy 回退、报告交付 | 最接近真正根接口，但副作用和错误语义仍不稳定 |
| `lib/pipeline/*` | 采集、规约、打分、合成入口 | 已有骨架，但还没有完全接管 legacy 实现 |
| `lib/report/*` + HTML template | 报告 section、SVG 图元、交互与分享卡 | 产品完成度高，适合借鉴视觉层思路 |

根 skill 的“最窄匹配”原则值得保留，但 commands 复制了大量工作流。例如 `analyze-stock` 要求 agent 手工读取/覆盖 `panel.json`、编写 `agent_analysis.json`、再运行 stage2，[`commands/analyze-stock.md:10-23`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/commands/analyze-stock.md#L10-L23)、[`commands/analyze-stock.md:72-94`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/commands/analyze-stock.md#L72-L94)。同一约束又在主 skill 中重复。这样的模块很浅：接口几乎和 implementation 一样复杂，无法给调用者提供足够 leverage。

### 2.2 确定性脚本与 prompt 的正确分工，以及当前偏差

UZI 明确提出“数据靠脚本、判断靠 agent”，并把流程拆成 Stage 1（采集、模型、规则骨架）→ agent 介入 → Stage 2（合成与报告）。[`skills/deep-analysis/SKILL.md:464-490`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/SKILL.md#L464-L490)

这个方向是对的：

- 脚本适合做 ticker 解析、字段规约、来源记录、财务计算、估值、规则校验、视图模型和渲染。
- agent 适合做证据约束下的行业解释、冲突识别、关键不确定性、情景叙事和“什么会改变观点”。
- agent 不应直接改权威数值文件，也不应生成无法被脚本复核的价格、仓位和评分。

当前实现的偏差在于 agent 被要求直接覆盖 `panel.json` 并写大量流程状态；prompt 因此成为数据库迁移器和工作流引擎。默认 CLI 又设置 `UZI_CLI_ONLY=1`，把缺少 agent analysis 降为 warning，[`run.py:471-474`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L471-L474)，所以“严谨 skill 流程”和“普通一键 CLI”实际上是两个语义不同的产品。

本地重构应保留这两档体验，但由同一个代码状态机表达：`standard` 可以没有 agent role-play，`deep` 才执行证据型 agent synthesis；两者返回相同的 `ResearchResult`，而不是依赖 prompt 是否恰好执行完整。

## 3. 真实端到端链路

### 3.1 一键 CLI

默认入口是：

```text
python run.py <ticker> --no-browser
```

`run.py` 负责环境探测、可选深度、resume、对比/组合分支、pipeline 执行和最终报告定位。正常股票默认进入新 pipeline；任何异常会捕获后整体回退 legacy，[`run.py:593-619`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L593-L619)。这是强可用性设计，但 catch-all 会隐藏“实际走了哪条 implementation”；结果对象也没有结构化记录该回退。

入口还有两个不适合本地复制的行为：

- 缺依赖时自动运行 `pip install` 并轮询镜像，是隐式环境写操作。[`run.py:125-167`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L125-L167)
- 报告不存在时只打印并 `return`，CLI 可能以 0 退出，自动化调用者无法可靠判断失败。[`run.py:724-731`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L724-L731)

### 3.2 Pipeline

`run_pipeline()` 的顺序是 preflight → collect → 写兼容 `raw_data.json` → score → legacy stage2 render。[`lib/pipeline/run.py:19-63`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/run.py#L19-L63)

采集使用三波顺序：基础信息先跑、无依赖维度并发、依赖行业的维度最后跑；单维度错误会变成结构化 error 结果而不终止整股研究。[`lib/pipeline/collect.py:67-151`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/collect.py#L67-L151)

但新 pipeline 仍是迁移壳：

- registry 中的每个 adapter 通过 `importlib` 调旧 `fetch_X.main()`，并把各种返回形状规约成 dict；不是独立的新 fetcher implementation。[`lib/pipeline/fetchers/registry.py:23-67`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/fetchers/registry.py#L23-L67)
- `pipeline.synthesize` 明确只是 legacy stage2 wrapper。[`lib/pipeline/synthesize.py:1-19`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/synthesize.py#L1-L19)
- renderer registry 虽注册 21 个 section，但主 assemble 仍使用另一套 report modules/template replacement，形成两套渲染抽象。[`lib/pipeline/renderer/registry.py:26-59`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/renderer/registry.py#L26-L59)

这说明“先放 adapter、再迁移 implementation”可降低重构风险，但本地项目不应在最终架构中永久保留双主干。

### 3.3 数据契约与产物链

主 skill 把 `raw_data.json → dimensions.json → panel.json → agent_analysis.json → synthesis.json → HTML/PNG` 作为文件闭环。[`skills/deep-analysis/SKILL.md:1005-1022`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/SKILL.md#L1005-L1022)

优点是断点恢复、人工检查和问题复现都很直观。缺点是多个文件可被脚本和 agent 原地改写，缺少不可变的 run snapshot、schema version、依赖图和统一状态日志。`data-contracts.md` 自身也已经落后：仍称 5 个 Task，缓存目录示例未列 `agent_analysis.json`，[`assets/data-contracts.md:1-5`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/data-contracts.md#L1-L5)、[`assets/data-contracts.md:281-293`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/data-contracts.md#L281-L293)。

本地应把这些文件收敛为一个版本化、不可变的 `ResearchRun` snapshot；HTML、JSON、Excel 和 PDF 都只能从同一 snapshot 派生。

## 4. 数据、指标与失败降级

### 4.1 值得借鉴

`DimResult` 明确区分 `full / partial / missing / error`，并携带 `source`、`data_gaps`、cache 和 latency 元信息。[`lib/pipeline/schema.py:16-47`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/schema.py#L16-L47) 统一空值逻辑也明确规定缺失不是 0，[`lib/pipeline/validators.py:18-38`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/validators.py#L18-L38)。这些是本地应直接吸收的领域概念。

provider framework 也形成了真实 seam：多个 provider 可按市场和维度排序，失败后自动尝试下一个，并统一返回 `(data, provider_name)`。[`lib/providers/__init__.py:83-153`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/providers/__init__.py#L83-L153) 这比把 AkShare、Yahoo、Tushare 调用散在各 skill 中更有 locality。

数据缺口不一定阻止出报告：系统生成 gap 清单，agent 可确认仍无法获取的字段，HTML 显示 banner 和缺失标记。[`README.md:571-580`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/README.md#L571-L580) 这正是本地从“全局 fail-closed”改成“能力级降级”可借鉴的方向。

### 4.2 不能照搬的隐藏错误

- adapter 丢失底层真实 source：legacy 结果的 `source` 被 unwrap 后丢弃，`BaseFetcher` 最终只写 spec 中第一个静态 source。[`lib/pipeline/fetchers/registry.py:47-56`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/fetchers/registry.py#L47-L56)、[`lib/pipeline/base_fetcher.py:75-90`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/base_fetcher.py#L75-L90)。本地必须保留实际 adapter、请求、时间、period、单位和原始证据 ID。
- `cache_ttl_sec` 在 schema 中声明，但 resume 只检查 data 非空和非 error，没有校验时间；旧行情或财务快照可能无限复用。[`lib/pipeline/schema.py:114-125`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/schema.py#L114-L125)、[`lib/pipeline/collect.py:157-170`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/collect.py#L157-L170)
- pipeline 所谓 future timeout 放在 `as_completed()` 之后；future 已完成才会被 yield，因此 `f.result(timeout=120)` 无法限制尚未完成的任务。[`lib/pipeline/collect.py:113-126`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/collect.py#L113-L126)
- 多数维度没有 required fields，`partial/full` 并不代表对研究结论真的够用；质量规则和方法输入要求没有连接成 capability graph。

## 5. 分析、评分和交易计划的可行性

### 5.1 维度评分

评分是确定性函数，便于回归，但大量维度是固定中性分：宏观 6、行业 7、原材料 6、期货 5、政策 6、护城河 6；没有数据也会进入综合分。[`lib/pipeline/score_fns.py:107-159`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/score_fns.py#L107-L159) 更危险的是 trap 维度直接“safe by default, 9 分”。[`lib/pipeline/score_fns.py:242-254`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/score_fns.py#L242-L254)

因此 UZI 的 overall score 更像交互式启发分，不是可校准、可回测的投资信号。本地可保留“证据覆盖率、质量、风险状态”分数，但不应把异质维度压成一个买卖总分；更不能把 missing 当 neutral。

### 5.2 DCF

优点：实现了 CAPM/WACC、两阶段 FCF、终值、EV→equity bridge、每股价值和 5×5 敏感性，且返回 methodology log。[`lib/fin_models.py:51-75`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/fin_models.py#L51-L75)、[`lib/fin_models.py:129-200`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/fin_models.py#L129-L200)

不可作为正式估值的原因：

1. 对所有公司默认运行，没有金融、周期、资源、pre-revenue、负 FCF 等方法适用性 gate。
2. FCF 缺失或为负时，先用 `revenue × net_margin × 0.8`，再用 `market_cap × 5%` 反推；后一种直接用市场价格构造“内在价值”，形成循环。[`lib/fin_models.py:104-113`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/fin_models.py#L104-L113)
3. 默认 rf、ERP、beta、债务比例、增长和 g 都是静态常数，没有 as-of、币种和公司资本结构证据。[`lib/fin_models.py:26-37`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/fin_models.py#L26-L37)
4. `WACC <= g` 时终值静默变成 0，而不是方法失败；proxy 是否被使用也没有进入质量状态。
5. `compute_dim_20` 不论内部是否使用 proxy 或返回 error，都统一写 `fallback: False`。[`compute_deep_methods.py:40-45`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/compute_deep_methods.py#L40-L45)、[`compute_deep_methods.py:116-133`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/compute_deep_methods.py#L116-L133)

本地现有的 valuation method router 和 DCF applicability gate 应保留，并升级为代码 method registry；UZI 的 DCF 只能作为 UI/敏感性实现参考。

### 5.3 Comps、三表与 LBO

- Comps 有中位数、四分位、目标分位和隐含价，结构可用；但没有最少 3 家 peer gate、币种/会计口径/期间一致性、异常值处理和 peer 选择证据，只要 list 非空即可计算。[`lib/fin_models.py:255-329`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/fin_models.py#L255-L329)
- “3-statement” 实际是收入/利润假设、简化现金流和仅有 retained earnings 的 equity roll-forward；没有完整资产负债表、债务、现金和 balance check，不能称 linked three-statement model。[`lib/fin_models.py:336-421`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/fin_models.py#L336-L421)
- Quick LBO 的 entry EV 固定为 `8×EBITDA`，entry debt 固定 `5×EBITDA`，完全不使用当前市值或企业价值。因此它回答的是一个假设交易，而不是“按今天股价买入”的交叉验证；在相同默认假设下结果高度机械化。[`lib/fin_models.py:428-476`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/fin_models.py#L428-L476)

### 5.4 评委与策略输出

persona panel 适合作为“多角度问题清单”和报告交互，不适合作为估值证据。它要求 LLM 模拟真实投资者并可覆盖规则引擎分数，本质上不可稳定复现。[`skills/deep-analysis/SKILL.md:751-824`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/SKILL.md#L751-L824)

UZI 的默认 synthesis 会在 agent 未覆盖时按当前价自动生成四类买入区间，并生成“50% 起步”、止损与 1.25× 目标位。[`lib/pipeline/score_fns.py:1277-1311`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/score_fns.py#L1277-L1311) 这些不是由风险承受能力、组合约束、流动性、回测或可信估值推导，免责声明不能修复其方法缺陷。

本地应输出 `conditional_research_plan`：观察变量、验证触发、失效条件、事件风险、最大数据陈旧度、复核日期和“什么会改变观点”。默认不输出 buy/sell/hold、仓位、目标价或止损指令。

## 6. 报告系统：最值得借鉴的部分

UZI 把 HTML 当作产品，而不是把 Markdown 换一个皮肤：

- assemble 前运行机械自查，critical 阻止完整 HTML、warning 可带留痕继续。[`assemble_report.py:341-370`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/assemble_report.py#L341-L370)
- 报告包含核心结论、多空冲突、评委、聊天室、深度卡、机构模型、风险、区间、数据 gap banner 和 share card；section 通过独立 Python renderer/SVG primitive 生成。[`assemble_report.py:473-577`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/assemble_report.py#L473-L577)
- template 有明暗主题、sticky TOC、scroll-spy、响应式布局、reduced-motion、评委筛选和术语 tooltip。[`report-template.html:2738-2751`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/report-template.html#L2738-L2751)、[`report-template.html:3336-3410`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/report-template.html#L3336-L3410)、[`report-template.html:3452-3518`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/report-template.html#L3452-L3518)
- 独立脚本可把头像内联为 self-contained HTML，并用 Playwright 截取分享卡。[`inline_assets.py:17-54`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/inline_assets.py#L17-L54)、[`render_share_card.py:19-49`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/render_share_card.py#L19-L49)

不应复制的是 3,568 行单体 template + 全局字符串替换。主 report helpers 没有统一 HTML escaping；安全修复只明确覆盖 versus/portfolio。[`test_v3_7_2_html_escape.py:1-11`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/tests/test_v3_7_2_html_escape.py#L1-L11) 本地应使用类型化 `ReportViewModel`、模板自动转义、组件级 snapshot 测试和浏览器视觉回归。

## 7. 测试与实际可用性

固定快照中可找到 62 个 `test_*.py` 文件和 657 个显式 test functions，但仓库没有 `.github/workflows/`，因此 README 的“全过”不是该提交上由 CI 持续证明的状态。[固定 `.github` tree](https://github.com/wbh604/UZI-Skill/tree/fce996c33e70eddce8e375f53cd252b549eb3d7c/.github)

本次在不安装上游依赖、禁用 pytest cache 和 Python bytecode 写入的环境中运行：

```text
python -m pytest skills/deep-analysis/scripts/tests/pipeline -q -p no:cacheprovider
77 passed, 2 failed in 1.02s
```

两处失败都发生在测试 monkeypatch 之前直接 import legacy fetcher，因为本机没有 `akshare`；不是业务断言失败。对应测试没有通过 dependency seam 注入 fake，而是依赖 import-time package availability。[`test_fetcher_registry.py:44-71`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/tests/pipeline/test_fetcher_registry.py#L44-L71)

可借鉴其 bug 驱动回归习惯，但本地测试应在根 Interface 上使用 in-memory adapters，避免测试穿透 seam。

## 8. 对本地项目：建议的深根模块

### 8.1 Seam 与 Interface

建立一个 `equity_research` 根 Module。外部 seam 位于 CLI/skill 与代码引擎之间；所有 skill、命令行、未来 Web UI 都只调用同一个 Interface。

```python
Depth = Literal["quick", "standard", "deep"]
RunStatus = Literal["complete", "partial", "needs_input", "failed"]

@dataclass(frozen=True)
class AnalyzeOptions:
    depth: Depth = "standard"
    as_of: date | None = None       # None 只表示在入口锁定为当前日期
    refresh: bool = False

@dataclass(frozen=True)
class ResearchResult:
    run_id: str
    status: RunStatus
    as_of: date
    report_html: Path | None
    snapshot_json: Path
    capabilities: Mapping[str, CapabilityResult]
    issues: tuple[ResearchIssue, ...]

class ResearchSystem:
    def analyze(
        self,
        target: str,
        options: AnalyzeOptions = AnalyzeOptions(),
    ) -> ResearchResult: ...

    def resume(self, run_id: str) -> ResearchResult: ...
```

最常见调用不再询问 Tear Sheet/L1/L2，也不暴露 Task 1/2/3：

```python
result = system.analyze("002897.SZ")
```

CLI 只是薄 adapter：

```text
python -m equity_research analyze 002897.SZ
python -m equity_research analyze 002897.SZ --depth deep --as-of 2026-07-10
python -m equity_research resume <run_id>
```

`standard` 默认生成一份可用 HTML、结构化 snapshot、基础研究、适用的估值视角和 conditional research plan。`quick` 缩小采集计划，`deep` 扩大官方来源、方法和 agent evidence synthesis；三档不改变结果 schema。

### 8.2 Interface invariants

1. **日期锁定**：入口立即解析并保存 `as_of`；一次 run 内所有数据、行情、财报和叙事使用同一 cutoff。
2. **来源闭环**：每个 observed value 都有 `evidence_id/source_id/period/as_of/unit/currency/adapter`；derived value 有公式和输入 IDs；estimated value 单独标记，不伪装成 sourced。
3. **缺失语义**：missing 永远不是 0、neutral 或 safe；状态必须显式。
4. **能力级门禁**：`research_brief`、`comps`、`dcf`、`historical_band`、`conditional_plan`、`full_model` 各自有 requirements。一个字段缺失只会把依赖它的 capability 标为 `limited/disabled`。
5. **方法适用性**：method router 先于任何估值计算；金融、pre-revenue 生物医药、周期资源股不会落入普通 FCFF/WACC DCF。
6. **确定性数值**：LLM/agent 不能修改财务事实、模型结果或评分；其输出只接受 schema 化 commentary、uncertainties、evidence_ids 和 view-change triggers。
7. **输出边界**：默认只输出 `valuation_view`、`risk_reward_summary`、`key_uncertainties`、`what_would_change_the_view` 和 `conditional_research_plan`；不自动输出 buy/sell/hold、目标价、仓位或止损。
8. **单一事实源**：HTML、JSON、Excel/PDF 全部从同一不可变 `ResearchRun` snapshot 渲染；报告中的每个关键表格/图表/结论可回指 evidence IDs。
9. **可恢复且可审计**：resume 不原地改变旧 snapshot；每个阶段记录 prompt/version、adapter、cache hit、fallback、issue 和 artifact hash。
10. **错误可判定**：Interface 永远返回结构化 `ResearchResult`；除编程错误或 snapshot 损坏外，不用裸异常表达正常数据不足。

### 8.3 Ordering constraints

调用者没有 Task 顺序负担。Implementation 内部固定执行：

```text
resolve target + lock as_of
  → build ResearchPlan and method requirements
  → collect evidence concurrently
  → normalize + provenance validation
  → evaluate capability gates
  → deterministic models and scenarios
  → optional evidence-constrained agent synthesis
  → policy / consistency validation
  → build ReportViewModel
  → render + visual/data QA
  → persist immutable ResearchRun
```

`resume(run_id)` 从 journal 的第一个未完成步骤继续；只有 `refresh=True` 才创建新数据快照。

### 8.4 Error modes

| Error mode | Interface 结果 | 禁止行为 |
|---|---|---|
| ticker 有多个候选 | `needs_input` + candidates；不产生错误股票报告 | 猜 Top 1 |
| 某 provider 超时/限流 | 尝试下一 adapter，记录失败；相关 capability 可 `limited` | 静默吞掉实际 source |
| 非关键字段缺失 | `partial` 或仍 `complete`，报告显式 gap | 全局阻断 |
| DCF 必需输入缺失/方法禁用 | `capabilities["dcf"] = disabled`，其他研究继续 | 用市值反推 FCF 或输出假目标价 |
| 可比公司不足 | comps disabled/limited + 原因 | 用 1-2 家或错误币种硬算 |
| agent schema/citation 不合格 | 丢弃 agent narrative，保留确定性研究并记 issue | 让 agent 修改数值文件 |
| report QA 失败 | `failed` 或保留 snapshot、无 full report path | 打印错误后 exit 0 |
| 所有数据源均不可用 | 最小 identity/gap memo；若连标的都无法确认则 `failed` | 默认 safe/neutral 分 |

### 8.5 Implementation 隐藏在 seam 后的复杂性

根 Module 应隐藏：ticker/证券类型路由、运行计划、并发与超时、cache freshness、official-source precedence、field ledger、source manifest、capability graph、method registry、DCF/comps/SOTP/residual-income/NAV engines、scenario engine、agent prompt versioning、policy validator、report view-model、HTML/PDF renderer 和 artifact journal。

删除该 Module 后，这些复杂性会重新散落到每个 skill/CLI/report builder；因此它能通过 deletion test，是一个真正的深 Module。

### 8.6 依赖分类与 adapters

| 依赖 | 类别 | seam / adapters | 测试方式 |
|---|---|---|---|
| 方法路由、估值、情景、policy、view-model | in-process | 不增加外部 seam | 直接通过根 Interface 场景测试 |
| run store / artifact store | local-substitutable | filesystem adapter + in-memory adapter | 临时目录或内存实现 |
| 官方披露 | true external | CNINFO/SSE/SZSE/BSE、HKEX、SEC/company IR adapters + fixture adapter | 固定官方文件 fixture |
| 行情/结构化市场数据 | true external | AkShare/direct HTTP/Yahoo/iFind adapters + fixture adapter | provider contract tests |
| 搜索/浏览器 | true external | search/browser adapters + recorded fixture adapter | replay evidence bundle |
| LLM narrative | true external | OpenAI/local model adapter + deterministic no-op/fake adapter | schema、evidence ID 和 policy assertions |
| PDF/截图浏览器 | local-substitutable | Playwright adapter + HTML-only test adapter | DOM/visual snapshots |

这些都是内部 seams，不应出现在普通 `analyze()` 参数中。composition root `build_default_research_system(config)` 负责注入；调用者只学习根 Interface。

### 8.7 Interface 是测试面

优先建立以下根 Interface 场景，而不是继续给每个小脚本叠测试：

1. 意华股份 21/23 字段时：基础研究和 HTML 仍完成；缺 D&A/lease debt 只限制相关 DCF/EV bridge，结果为 `partial`，不是 Task 1 总失败。
2. 负 FCF 公司：不会用 market cap proxy 生成 DCF；capability 明确 disabled/caution。
3. 银行：普通 FCFF/WACC DCF 永远不出现，路由到 residual income/PB-ROE。
4. provider failover：最终 evidence 记录真实成功 adapter，且 cache freshness 生效。
5. agent 输出虚构数字：validator 拒绝 narrative，但 deterministic snapshot 保持可用。
6. 同一 snapshot 的 HTML、JSON、Excel 关键数字和 evidence IDs 一致。
7. report DOM、移动端、dark mode、打印/PDF、缺失态和禁用方法态都有视觉快照。

当这些测试稳定后，删除被根 Interface 覆盖的旧 shallow-module 单测，遵循 replace-don't-layer，避免测试锁死 implementation。

### 8.8 Trade-offs

- **高 leverage**：用户只学一条命令；同一 implementation 同时服务 skill、CLI、Web 和回归测试。
- **高 locality**：来源、方法、政策和报告一致性集中在一个 Module，不再跨四份 SKILL 和公司专用 builder 修复。
- **代价**：Implementation 会比单个 skill 复杂，需要先定义 `ResearchRun`、capability graph 和 adapters。
- **部分结果的风险**：不再全局阻断会提高可用性，也可能让用户误读；必须在 report hero、每个 method card 和机器结果中显著显示 `available/limited/disabled` 与原因。
- **叙事可重复性**：限制 agent 只能写 evidence-constrained narrative 会降低 persona 娱乐性，但提高可审计性和跨模型稳定性。
- **默认简单不等于默认粗糙**：一条命令隐藏顺序，不取消来源和方法规则；深度来自小 Interface 后的大 Implementation。

## 9. 借鉴清单

### 建议吸收

1. 一条命令的根入口和 `quick/standard/deep` profile。
2. `DimResult` 的 `full/partial/missing/error`、显式 gap 和真实 latency/cache 元信息。
3. 多 provider failover，但改成依赖注入并保留字段级真实 provenance。
4. 波次并发、resume 和局部错误继续运行。
5. 数据 gap banner、能力卡和缺失态 renderer。
6. HTML 产品化：摘要 hero、sticky TOC、暗色、响应式、术语 tooltip、可折叠证据、内联 SVG、分享卡。
7. bug 对应回归测试和报告前机械 QA。

### 明确不照搬

1. 用 prompt/skill 文档充当工作流状态机和数据迁移器。
2. catch-all 后静默切 legacy，且不在结果中暴露实际路径。
3. 缺数据给中性分、行业成长分或 trap “安全”分。
4. 所有公司默认 DCF、负 FCF 改用 proxy、市场价反推内在价值。
5. 不使用当前 EV 的 Quick LBO 作为“按今天价格”的估值验证。
6. 不合格 peer pool 仍计算 comps。
7. persona 投票作为核心研究证据或总分。
8. 按当前价百分比生成买入区间、50% 仓位、止损和目标位。
9. import-time/运行时自动安装依赖。
10. 单体 HTML 字符串替换、未统一 escape、报告与模型使用不同事实源。

## 10. 最关键的五条结论

1. **UZI 的真正优势是可用性架构，不是估值质量**：一键入口、profile、局部降级和 HTML 产品化值得借鉴。
2. **它仍是 hybrid migration**：fetcher adapter 与 synthesize 都依赖 legacy；不能把“有 pipeline 目录”误判为职责已完全迁移。
3. **估值不能照搬**：DCF proxy、无方法 gate、简化三表和不取当前 EV 的 LBO 会制造虚假精确度。
4. **缺失数据处理有正反两面**：结构化 gap 很好，但 missing→neutral/safe score 和无限 resume cache 会掩盖不确定性。
5. **本地重构的最佳根 Interface 是 `analyze(target)` + `resume(run_id)`**：把 Task、门禁、adapters、agent 和报告都隐藏在深 Module 内，以 capability-level gating 取代 Task 1 全局阻断。
