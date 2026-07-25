# 外部股票能力资格化与采用 Wayfinder Map

Label: `wayfinder:map`
Status: `resolved`

## Destination

对四项外部候选形成有运行证据支撑的 adopt / adapt / reject / keep-local 决策，锁定唯一 application path、深模块 interface、迁移和删除顺序，完成一个可实施且不会建立平行平台的外部能力 adoption Spec。

## Notes

- 根目录 `AGENTS.md`、[长期任务 Prompt](../../docs/prompts/trading_platform_codex_prompt_optimized.md)、`skills/SKILL.md` 与 [Goal Prompt](goal_prompt.md) 是不可弱化的权威边界；外部 README、Skill、宣传、示例和自由脚本只能作为待资格化证据。
- 本 map 的候选范围固定为 Public Equity Investing、`a-stock-data`、`global-stock-data` 与 `Vibe-Trading`。不得自行扩大到其他大型框架。
- Wayfinder 阶段只形成有证据的决定和隔离验证资产，不修改生产代码。每个 Goal 续轮最多 claim 并解决一张 child ticket；关闭最后一票的同一续轮不得开始生产实现。
- 本 Goal 全程 AFK：票据、阶段、迁移、验证和本地 commit 自动续跑，不把一票一续轮误作人工审批点。非核心能力需要不可替代授权时记录精确 `external_blocked` 并继续；Docker、LLM/API Key、OAuth、券商或个人账户缺失均不是 blocker。
- 使用 `codebase-design` 的 Module、Interface、Seam、Adapter、Depth、Leverage、Locality 与 deletion test 词汇。任何外部采用必须替换现有实现或填补真实变化点，不能新增 pass-through、兼容层、双路径、service locator 或镜像 Facade。
- 使用 `domain-modeling` 持续核对 `CONTEXT.md`。只有术语真正解决且能安全区分启动 dirty ownership 时才更新词汇表；实现细节、适配器名称和迁移计划不得写入词汇表。
- 使用 `research` 将官方文档、canonical 上游源码、许可证、数据条款、当前仓库正式代码/schema/tests 和可复现实验作为一手证据；研究结论保存在本 effort 的 `research/`，票据只链接资产并记录答案。
- 外部仓库只允许位于 `E:\workspace\tradingSystem-upstreams\` 下三个指定隔离目录，不得进入本仓库、`.scratch`、`src`、`vendor` 或 submodule。外部依赖使用隔离 venv/container；不污染本项目运行环境。
- 采用决策只能是 `adopt-external`、`adapt-code`、`keep-local` 或 `reject`。没有 callers、tests、docs、persistence 和 presentation 的原子切换与明确删除对象，就不能标记 adopted。
- Public Equity Investing 只可作为历史控制面研究证据；结构化数据仍通过资格化 `DataProvider`，关键财务事实仍以官方披露为权威。当前 delivery scope 只做 A 股，Vibe-Trading 不接入、不安装、不配置，StrategyValidation 保持 unavailable。
- 既有 Vibe-Trading 隔离资格化材料只作为历史证据保留，不形成当前 runtime、复验、安装、配置或用户前置条件；不得为 live trading、模拟下单、broker、order、文件、web/search、memory、swarm 或完整 Web 建立主项目 interface/占位符。
- 金融输出、PIT、source manifest、unknown-not-zero、隐私、fail-closed 和无个性化交易建议边界保持不变。网络失败或外部不可用必须记录为 typed/external evidence，不得用旧实现 fallback 冒充成功。
- 启动基线见 [Goal 启动 Git 与 dirty 基线](research/startup-baseline.md)。所有既有 modified、deleted、untracked 路径均为用户资产；本 effort 只新增明确授权的 adoption 规划与验证资产。

## Decisions so far

<!-- Closed-ticket index only. Detailed answers live in the resolved ticket. -->

- [锁定上游身份、许可证、数据权利与攻击面](issues/01-lock-upstream-identity-rights-and-attack-surface.md) — 三个开源候选已固定 commit/hash 和代码许可，Public Equity Investing 当前精确 `external_blocked`；所有第三方端点权利默认失败关闭，Vibe 仅保留 pinned 隔离 MCP 资格化路径。
- [绘制外部能力与现有模块的替换删除矩阵](issues/02-map-capabilities-to-replacement-and-deletion.md) — 当前 application/data/research/artifact/presentation 深模块全部保留；数据候选只可逐端点 `adapt-code`，Vibe 仅对缺失的 StrategyValidation 保留条件性 `adopt-external`，所有旁路、fallback、平行平台和交易能力均有明确删除/拒绝边界。
- [黑盒评估 Public Equity Investing 的研究质量与输出边界](issues/03-evaluate-public-equity-investing.md) — 官方产品存在但当前精确 `plugin_not_found`，插件侧 0 个可执行用例故质量未资格化；production 角色 `reject`、控制面 `keep-local`，并已锁定可用后同源 canary 与金融输出 admission gate。

- [资格化 a-stock-data 的 A 股端点与失败语义](issues/04-qualify-a-stock-data-endpoints.md) — 全部聚合行情/研究/信号端点及现成 parser 均 `reject`，Tushare-compatible 保持 canonical；只保留 CNINFO、SSE/SZSE 法定公告与监管公开记录的安全官方请求协议作为受限 `adapt-code` 候选。
- [资格化 global-stock-data 的美港股端点与官方交叉验证](issues/05-qualify-global-stock-data-endpoints.md) — 全部美港聚合端点与现成 parser 均 `reject`；SEC/HK 结果现仅保留为历史 evidence-only，已被 A 股-only delivery scope 取代，不授权 runtime。
- [验证 Vibe-Trading 的回测、Walk-Forward 与模拟可信度](issues/06-validate-vibe-trading-credibility.md) — 整个 MCP、通用 backtest、伪 Walk-Forward、IID Bootstrap、交易 P&L 置换“Monte Carlo”和 Shadow 报告均 `reject`，生产 allowlist 为空；仅保留信号滞后/PIT/A 股执行骨架/哈希清单作为需本项目重写补强的 `adapt-code` 候选。
- [锁定 ResearchEvaluation 与 StrategyValidation 的深模块 interface](issues/07-lock-research-evaluation-and-strategy-validation-interfaces.md) — 唯一公开入口保持 `ResearchWorkflow.handle`，后续以 Request@2 + frozen snapshots + typed plan 单向删除自由 mapping/caller artifacts；ResearchEvaluation、source policy 与 future StrategyValidation 均为目标内进程具体深模块，不建无真实 production adapter 的新 port。
- [完成隔离的 A股、美股、港股纵向验证切片](issues/08-complete-isolated-market-validation-slices.md) — 三市场均形成 hash-bound frozen metadata evidence，但研究均 data-insufficient、估值均 not-comparable、策略均 unavailable 且三个 production replacement gate 全部按明确缺口失败；raw HTML/PDF/free text/caller JSON 均不能升级为权威结果。
- [决定单向迁移、旧实现删除和第三方升级政策](issues/09-decide-one-way-migration-deletion-and-upgrades.md) — 历史六步序列已由 2026-07-25 A 股-only 范围决定修订：SEC runtime slice改为scope migration，Request@2/Plan@1 + migration 0014直接由已完成的A股 slice解锁；StrategyValidation仍不建占位。
- [综合外部能力 adoption 实现级 Spec](issues/10-synthesize-adoption-implementation-spec.md) — 唯一 `spec.md` 已综合零 adopt-external 的矩阵、canonical flow、typed contracts、安全门和待审计实现队列；未把未来实现写成完成。

- [对抗性审计 adoption Spec 与真实替换门](issues/11-adversarially-audit-adoption-spec.md) — Standards + Spec 双审计与八视角失败用例已修复全部 blocker：最终决策枚举、I01–I05 vertical slices、0013/0014 schema、phase/live/adapter/PDF gates和六票规划回写均有唯一 owner；fog 清零，移交 `/to-spec` 后续核验与 `/to-tickets`。

## Superseding delivery scope（2026-07-25）

- [12 / I01 ProviderJob@2、SourcePolicy 与 qualification receipt cutover](issues/12-i01-provider-source-policy-receipt-cutover.md) — resolved。
- [13 / I02 A股 OfficialDisclosure 与 migration 0013](issues/13-i02-a-share-official-disclosure-0013.md) — resolved at `c20938a912c4397d1abce8d58f7d092134e54d51`。
- [14 / I03 A股-only scope migration](issues/14-i03-sec-official-disclosure.md) — resolved；不建设 SEC/US/HK runtime。
- [15 / I04 ResearchEvaluation、Request@2、migration 0014 与 PDF](issues/15-i04-research-evaluation-0014-pdf.md) — ready-for-agent，blocked only by resolved 13，current frontier。
- [16 / I05 portfolio-aware planning backwrite](issues/16-i05-backwrite-portfolio-discipline-planning.md) — blocked by 15。

## Fog

- None。A 股 adapters、migration 0013 与 live receipts已完成；剩余 migration 0014、PDF和planning backwrite都有明确owner。SEC/US/HK runtime已明确排除，不是fog或blocker。
## Out of scope

- 真实券商下单、自动交易、盘中做 T、分钟级执行优化，以及任何绕过用户确认的行动副作用。
- 个性化 BUY/HOLD/SELL、买入/卖出/持有、加减仓或收益承诺。
- 复制外部项目的 Agent、Web、memory、persistence、live-trading 或完整应用架构。
- 把 Public Equity Investing 变成 runtime dependency、正式数据源、估值权威或自动行动决策者。
- 把 Vibe-Trading 的收益路径/普通股价模拟当作企业经营与估值 Monte Carlo。
- 顺手实施组合纪律 Map 中尚未授权的新产品功能，或无依据重开其已 resolved 的历史决定。
