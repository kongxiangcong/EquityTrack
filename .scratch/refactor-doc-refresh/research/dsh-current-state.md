# DeepSeek Harness 当前能力审计与 EquityTrack Phase 2 适配建议

> 审计日期：2026-08-23
>
> DSH 仓库：`D:\dsh-proj\deepseek-harness`
>
> 审计方式：只读本地仓库、源码与随仓文档核验；未把用户原文或营销性描述当作事实。
> 本文中的相对路径均相对于上述 DSH 仓库根目录。

## 1. 快照与结论

### 1.1 被审计快照

- 分支状态：`master...origin/master`，审计开始与结束时工作树均无本地改动。
- HEAD：`b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`。
- HEAD 时间与主题：`2026-08-21T20:03:37+08:00`，`Merge pull request #2908 from deepseek-harness/release/dsh-0.1.1-rc.2`。
- 最近标签与 `git describe`：`dsh-v0.1.1-rc.2`；前序标签包括 `dsh-v0.1.1-rc.1`、`dsh-v0.1.0-rc.8`、`dsh-v0.1.0-rc.7`。
- 根包和 CLI 包都声明 `0.1.1-rc.2`（`package.json:2-9`；`apps/cli/package.json:2-15`）。
- 本机实测：Node `v25.8.1`，pnpm `11.7.0`；`pnpm dsh --version` 返回 `0.1.1-rc.2`，`pnpm dsh --help` 可正常列出 `web`、`profile` 和 `plugin` 入口。根清单要求 Node `^22.19.0 || >=24.0.0` 和 pnpm `11.7.0`（`package.json:7-9`）。

### 1.2 总结性判断

DSH 当前是一个**真实可运行、可通过 Cordis 插件组合的 Agent Harness**，具备模型适配、工具、Agent loop、会话事件日志、CLI/headless runner、浏览器聊天 UI、宿主/浏览器插件加载、通用 RPC、进程管理和 Python 驱动 SDK。用户原文中“插件化 Agent 运行时”这一判断成立：DSH 明确把模型适配器、工具注册、会话日志和 Agent loop 都做成插件（`README.md:5-11`；`docs/architecture.md:9-13`）。

但下面四个边界必须写进 Phase 2 文档，而不能继续作为隐含假设：

1. **DSH 不是金融评测系统。** 当前 `BENCHMARK.md` 只有一条操作提示：独立任务使用不同 workspace 和 session ID（`BENCHMARK.md:1-3`）。仓库虽有单测、真实 API e2e、传输/展示 snapshot 和 Web snapshot，却没有金融案例合同、硬约束、软评分、grader、汇总或校准系统（`package.json:35-51`；`docs/testing.md:7-15,47-49`）。
2. **DSH session log 不是 EquityTrack event store。** 它是 Agent 交互历史的追加式真值，模型上下文由其派生，包含用户消息、模型输出、工具参数和结果（`docs/subsystems/session.md:5-11,21-25,49-92`；`docs/architecture.md:92-96`）。账户、证据、风险政策和计划生命周期不能以此作为规范真值。
3. **官方 Python SDK 不能作为当前 Windows 本机的默认 Phase 2 桥。** 发布 SDK 的前置平台只有 Linux x64/arm64 和 macOS 14 arm64（`docs/user/guide/python-sdk.md:7-13`）；随 wheel 发布的生产运行时也只有 linux/macos，Node carrier 只是仓库开发用途且不会自动选择或发布（`python/sdk-runtime/README.md:7-20`）。此外，该 SDK 的方向是“Python 客户端启动 DSH Agent runtime”，不是“DSH 调用 EquityTrack Python Core”（`python/sdk/README.md:5-8,23-27`）。
4. **DSH 仍处在明确的 developer preview。** README 承诺会有兼容性破坏（`README.md:9-11`）；仓库规则进一步说明当前可自由重命名/重打包，旧磁盘格式会被拒绝，且 session format 没有兼容承诺（`AGENTS.md:5-7`）。Phase 2 必须精确锁版本，并确保退出 DSH 时不丢业务数据。

因此，用户原来提出的“先由 EquityTrack 定义金融任务与判定标准，DSH 后接入为可替换运行器/工作台”的顺序是正确的。需要修正的是：**不要把 DSH Python SDK、session、workspace、权限预设或内置 Web UI描述成现成的 EquityTrack 产品层。**

## 2. 能力逐项核验

| 主题 | 当前真实能力 | 证据 | 对 Phase 2 的含义 |
|---|---|---|---|
| Cordis / 插件 | 所有运行时核心部件均可作为 Cordis 插件组合；插件通过服务、类型事件和可逆 effect 注册/卸载。 | `docs/architecture.md:9-13` | 可做外置适配器，不必 fork 或修改 DSH 内核。 |
| Profile / Bundle | profile 是 `$DSH_HOME` 下的可运行组合；bundle 是 npm 包形式的配置层。内置 `web`、`headless` 模板，可安装 out-of-tree bundle。 | `docs/architecture.md:15-27`；`docs/user/develop/basic/publish.md:9-16,66-83` | EquityTrack 应发布一个薄 bundle/adapter；profile 是部署组合，不应等同于领域 Skill。 |
| CLI | 支持命名 profile、一次性 headless session、Web alias 和 pnpm 插件管理；调用目录默认 workspace。 | `apps/cli/README.md:5-16,30-43` | 可用于 DSH 运行与适配器验收；不能代替 EquityTrack 的产品应用接口。 |
| TypeScript 插件 | 最小插件是导出 `apply(ctx)` 的 TS 模块；配置可用 Schemastery 校验，非法配置在加载时失败。 | `docs/user/develop/basic/index.md:15-29`；`docs/user/develop/basic/config.md:9-45,63-74` | 适配器应在加载时验证 Python 可执行位置、合同版本、超时和 telemetry 等部署配置。 |
| Cordis 来源 | Cordis 源码被 vendored、改到 `@deepseek-ai` scope，并由 DSH 仓库自己锁定和修改。 | `vendor/README.md:1-5,13-23`；`vendor/cordis/package.json:2-4` | 不要独立追随上游 Cordis 版本；应锁整个 DSH commit/lockfile。 |
| Skill | DSH Skill 是可发现的说明文本；filesystem provider 读取 `SKILL.md`，model-facing tool 把目录和选中的正文放进模型历史。 | `docs/subsystems/skills.md:5-15`；`packages/skill/skill-filesystem/README.md:53-59`；`packages/skill/tool-skill/README.md:5-31` | 可承载适配层提示，但不是可执行、版本化、可独立评分的金融领域合同。 |
| Skill 稳定性 | Skill body 无版本协议，正文修改不会更新 catalog digest；读取为一次性整段文本且没有大小上限。 | `packages/skill/tool-skill/README.md:162-169`；`packages/skill/skill-filesystem/README.md:69-75` | 五个内部 Skill 的版本、schema 和 Bench 必须由 EquityTrack 自己拥有。 |
| Session | 追加式类型事件日志，是 Agent 全部交互历史的真值；LLM 历史由日志派生。 | `docs/subsystems/session.md:5-11,21-25` | 仅记录 DSH 会话/工具轨迹；不得成为金融业务记录。 |
| Model 可见性 | 任何进入模型请求的内容都必须可从 session log 重建，即“model-visible means logged”。 | `docs/architecture.md:92-96` | 若把持仓、研究或交易计划送入 DSH Agent，敏感内容会落到 DSH session log；必须明确隐私边界。 |
| Persistence | JSONL 与 SQLite 后端可替换；SQLite 当前 schema 17，遇旧 schema 拒绝而非迁移。 | `docs/subsystems/persistence.md:231-236`；`packages/session/session-persistence-sqlite/src/schema.ts:17-20` | DSH 日志只能是辅助证据；不能让 DSH 升级可读性决定业务可恢复性。 |
| Session 格式 | format 固定为 0，无兼容保证、无迁移；未知必需事件或外来版本会拒绝加载。 | `packages/core/session/src/types.ts:33-56`；`docs/subsystems/persistence.md:53-55,92-94` | 每次升级使用独立 DSH_HOME，并把“无法重放旧 DSH 会话”视为允许发生的非业务损失。 |
| Workspace | workspace 是一个已存在目录的规范化注册记录及 session 分组；删除注册不会删除目录或 session 日志。 | `packages/workspace/workspace/README.md:5-21`；`docs/subsystems/workspace.md:116-122` | 它不是自动复制或隔离环境。Bench 必须自己创建物理独立目录、session root 和唯一 ID。 |
| Python SDK | Python 通过 stdio JSON-RPC 启动/驱动 DSH 子进程；可指定 cwd、session root、session id，并返回事件。 | `python/sdk/README.md:5-8,23-27,41-51`；`docs/user/guide/python-sdk.md:40-50,65-81` | 可作为 Linux CI 中的 DSH runner；不是当前 Windows 产品桥。 |
| Python SDK 平台 | 发行运行时仅 Linux/macOS；示例 PTY composition 也明确不支持 Windows agent。 | `docs/user/guide/python-sdk.md:7-13,98-102`；`python/sdk-runtime/README.md:9-20` | Windows Phase 2 应由 Node/DSH Host 通过进程协议调用 Python Core。 |
| 子进程 seam | `ctx.subprocess` 支持显式 argv/cwd/env/stdio、pipe/collect、AbortSignal、进程树终止；argv 不经 shell 解释。 | `docs/subsystems/subprocess.md:39-41,89-129,132-173` | 这是当前最合适的 DSH→Python 外部 seam，可实现长驻 NDJSON/JSON-RPC 或受控单次调用。 |
| Web UI | 有可运行的本地浏览器应用；`dsh web` 默认启动 `127.0.0.1:3080`。 | `README.md:19-23`；`apps/web/package.json:2-25` | 是聊天 UI 基座，不是现成的投资工作台。 |
| Web 插件 | Host 会扫描声明 `dsh.client` 的包，发布并加载浏览器 bundle；UI 通过 typed slot 注册组件。 | `docs/subsystems/client-modules.md:5-11,53-71`；`packages/client/ui-slots/README.md:5-22` | 可做受控的 EquityTrack client half，但必须开发并承担 DSH UI API churn。 |
| Chat 扩展 | 可用 durable Session event family + `ConversationNodeDefinition` + keyed renderer 插入业务行。 | `docs/cookbook/adding-a-conversation-node.md:5-23,185-200` | 适合展示 DSH 任务轨迹；不应把业务对象复制为 DSH durable events。 |
| Host/Client RPC | 通用 Connection RPC 可注册独立 channel，支持 `loopback`/`trusted-host` authority、取消信号和统一结果封装；浏览器通过 POST 调用。 | `packages/client/connection/src/rpc.ts:5-19,24-76`；`packages/client/connection/src/client/rpc.ts:18-53` | 可建立 `/equitytrack` 的独立 unary 通道，不必侵入 DSH 中央 API assembly。 |
| Typert Remote | 能生成严格 unary RPC，但 client assembly 必须显式纳入 package，合同变更要重新生成 Host/Client artifacts；不覆盖流式/分页协议。 | `docs/api-gateway.md:5-15,56-78,119-129,150-160` | 对最初的 out-of-tree 适配器偏重；先用独立 Connection channel + EquityTrack 自有 JSON schema。 |
| Human command | 插件可注册直接执行的命令，不创建 model message；handler 结果直接给 UI。 | `docs/subsystems/commands.md:1-5,29-55` | 在不允许产品运行时 LLM 的前提下，可作为受限入口；复杂工作台仍优先自有 client RPC。 |
| 权限预设 | 只是 sandbox mode 与 approval policy 的组合选择，本身不执行权限。默认有 `workspace-write+ask` 与 `danger-full-access+never`。 | `docs/subsystems/permission-presets.md:5-11,44-48` | 不能映射成 TradePlan 的 `confirmation_state`，也不能证明金融动作获授权。 |
| Approval | 对“一次具体工具动作”做一次性、fail-closed 决策；只在开放 turn 中发生并写 DSH audit event。 | `docs/subsystems/approval.md:5-33,84-88` | 可保护 DSH 工具执行，但不是 EquityTrack 的业务确认、版本并发或状态机。 |
| Sandbox | 只治理文件效果；网络和进程可见性不在其语义内。Windows ACL backend 对 ambient ACL gaps 报告 partial。 | `docs/subsystems/sandbox.md:5-30` | 不得宣称它提供完整数据隔离或网络隔离；Python Core 权限仍须最小化。 |
| Web 边界 | `/api` 有 Host/Origin trust fence，但文档明确这是 reachability policy，不是 authentication，且不支持 `0.0.0.0` 暴露。 | `packages/client/connection/README.md:5-13` | Phase 2 默认只允许 loopback；远程访问必须等待独立认证层。 |
| 动态插件 | 模型可临时定义/运行 Cordis 包，但 VM sandbox 不是安全边界，应像 bash 一样对待。 | `packages/extensions/tool-cordis/README.md:5-23` | 金融产品中必须关闭；不能让模型动态生成 EquityTrack adapter 或权限逻辑。 |
| Telemetry | 默认 `DISABLED`；上传模式会带出完整 event data，包括消息、工具参数/结果、文件内容、system prompt 和 cwd，且无内置脱敏规则。 | `packages/session/session-telemetry-otel/README.md:7-38`；`packages/bundle/base/cordis.patch.yml:129-161` | EquityTrack profile 必须显式锁 `DISABLED` 并做启动断言，不能只依赖默认值。 |

## 3. DSH 不等于金融 Bench

### 3.1 已经具备的通用验证设施

DSH 自身工程验证很强：

- Vitest 单测及 package-level 100% line coverage gate；
- 真实模型 API e2e；
- 录制会话的 keyless transport/presentation snapshot；
- Web browser snapshot；
- built-artifact smoke 与 CLI acceptance。

这些设施验证的是 DSH 自己的运行时、协议、持久化和展示行为（`docs/testing.md:7-15,31-49`），可以帮助证明 adapter 没把 DSH 接坏。

### 3.2 缺失的金融评测能力

本地代码树没有可识别的独立 benchmark/eval 子系统；根清单也没有 bench/eval script（`package.json:35-51`）。`BENCHMARK.md:1-3` 只要求为独立任务使用不同 workspace 和 session ID。没有发现以下现成能力：

- `case_id / as_of / frozen_evidence / portfolio_snapshot / risk_policy` 案例合同；
- PIT 泄漏检测、来源完整性、估值复算、风险门等 hard invariant；
- 投资用途 rubric 或 grader；
- 禁止输出规则；
- 多模型差异、重试幂等、概率校准和组合风险指标聚合；
- 金融案例的版本、基线、报告和人工复核工作流。

所以 Phase 2 文档应明确：

> EquityTrack Bench 是 Phase 1 的一等产品资产。DSH 最多是一个可替换执行载体和轨迹来源，不拥有案例、判定规则、评分或发布门。

“每个案例使用独立 workspace/session”仍然有用，但必须由 EquityTrack Bench runner 真正创建独立物理目录、独立 session root、唯一 session id，且最好使用隔离的 `$DSH_HOME`。仅把两个 session 关联到不同的 DSH Workspace 注册记录，并不创建副本或 sandbox；Workspace 只是目录记录（`packages/workspace/workspace/README.md:11-21`）。

## 4. 日志、事件和业务真值的边界

### 4.1 DSH 可以拥有的状态

DSH 可以拥有：

- DSH profile、bundle 和 plugin 配置；
- Agent session id、消息、工具调用、运行原因和模型用量；
- DSH UI 的临时状态和可重建投影缓存；
- DSH workspace 注册和 session 分组；
- 用于诊断的 adapter correlation id、contract version、redacted error code；
- Bench 运行时的 DSH transcript（仅作为诊断附件）。

### 4.2 DSH 禁止拥有的规范真值

下列信息必须只由 EquityTrack Python Core 的合同、持久化端口与业务事件存储拥有：

- 账户、现金、持仓、成交、成本和 `PortfolioSnapshot`；
- `EvidenceSnapshot`、source manifest、PIT/available-at、来源冲突和数据质量；
- `InvestmentCase`、`ValuationCase`、`DecisionCard`；
- 风险政策、风险预算、仓位上限和任何确定性计算结果；
- `TradePlan` 的版本、确认、激活、触发、替代、过期和关闭状态；
- `DecisionReview`、错误分类、lesson candidate、playbook rule；
- Bench case、fixture、hard invariant、rubric、评分、基线和放行决策；
- 规范业务审计与幂等键。

DSH session event 即使允许插件扩展，也不应复制上述对象作为第二业务账本。DSH 的 durable event 机制为会话重放服务，并且未知必需事件或格式变化可能让旧日志拒绝加载（`docs/subsystems/session.md:198-234`；`docs/subsystems/persistence.md:92-94`）。

### 4.3 隐私含义

DSH 的模型历史来自 session log，模型可见内容必须持久化（`docs/architecture.md:92-96`）。因此：

- 如果 Phase 2 把真实持仓、研究证据或计划传给 DSH Agent/LLM，它们既会送往所选模型 endpoint，也会写入本地 DSH 会话日志；
- 若启用 FULL/FEEDBACK_ONLY telemetry，完整消息、工具参数/结果、文件内容和 cwd 还可能发送到 OTLP endpoint（`packages/session/session-telemetry-otel/README.md:22-38`）；
- `DISABLED` 虽是默认值，但金融 profile 应显式配置并在启动时断言为 disabled，避免环境变量或上层 patch 改写；
- UI/adapter 响应默认应传只读、最少字段的 presentation DTO；详细来源和过程按需加载。

EquityTrack 当前权威基线要求产品业务运行时不自行调用 LLM，而 Codex/Skill 是控制面（`D:\dsh-proj\EquityTrack\docs\prompts\trading_platform_codex_prompt_optimized.md:40-44`）。让 DSH 的 Agent loop 执行五个金融 Skill 会改变这一边界，不能作为“产品封装”被悄悄引入。除非以后明确修订并评审该政策，Phase 2 应把 DSH 用作本地 UI/transport/可选 Bench runner，而不是金融推理真值或常驻 LLM runtime。

## 5. 推荐的最薄适配 seam

### 5.1 推荐结构

```text
DSH Web client plugin (read-only projection / explicit confirmation UI)
                 │
                 │  /equitytrack, loopback-only unary RPC
                 │  EquityTrackTaskRequest@1 / EquityTrackTaskResult@1
                 ▼
@equitytrack/dsh-adapter (Host Cordis plugin)
                 │
                 │  ctx.subprocess, argv never shell-interpreted
                 │  framed JSON over stdio, timeout + cancellation
                 ▼
EquityTrack Python application task interface
                 │
                 ▼
EquityTrack contracts + deterministic services + event store
```

建议初版只做一个 out-of-tree bundle，例如 `@equitytrack/dsh-adapter`，包含：

1. **Host plugin**：注入 `ctx.connection` 与 `ctx.subprocess`；注册独立 `/equitytrack` channel，authority 固定为 `loopback`；严格解析 `EquityTrackTaskRequest@1`，调用 Python application task，严格解析 `EquityTrackTaskResult@1`。
2. **Python protocol endpoint**：只暴露已经存在的任务级 application interface；使用定界 JSON/NDJSON 或 JSON-RPC，含 `contract_version`、`request_id`、幂等键、超时、取消、typed failure code。它是一个真实外部协议翻译 seam，可以拥有进程生命周期、重试边界和错误映射，但不能复制业务决策。
3. **Client plugin**：声明 `dsh.client`，调用 `ctx.connection.rpc.call('/equitytrack', ...)`，只渲染 Python Core 返回的 presentation model；活动计划变更必须提交 core 发出的确认挑战及当前版本，不能由 UI 本地切状态。
4. **配置门**：Python executable/core version、协议版本、数据根、超时、最大响应体、telemetry-disabled 断言和 loopback-only 都在插件 schema 中显式校验，失败则插件不加载。

通用 Connection RPC 支持独立 channel 和 `loopback` authority（`packages/client/connection/src/rpc.ts:5-19,24-37`），浏览器端已有统一 correlation 与结果 envelope（`packages/client/connection/src/client/rpc.ts:18-53`）。与把新 endpoint 加进 DSH 中央 Typert `api-remotes` assembly 相比，这个方式对 out-of-tree adapter 更薄、退出更容易，也不要求修改 DSH 仓库。

`ctx.subprocess` 是比直接依赖 Python SDK 更合适的 Windows 边界：它明确管理 argv、cwd、环境、pipe/collect、取消与进程树终止，且 argv 不会经 shell 解释（`docs/subsystems/subprocess.md:39-41,89-134`）。若使用长驻 Python 进程，adapter 必须拥有 frame decoder、stderr 上限、请求关联、崩溃恢复和退出；若使用一次性进程，必须评估启动成本并保证同一任务不会双写。两者只能选一条规范路径，不能长期双轨。

### 5.2 为什么不首选另外几种 seam

- **不首选 Python SDK**：方向相反且当前无 Windows 发布运行时；它适合 Linux CI 中“Python 驱动 DSH Agent”，不适合 Windows 上“DSH 调用 Python 投资核心”。
- **不首选 model-facing tool**：会把输入/输出纳入模型上下文与 DSH 日志，并触发 LLM runtime；与当前 EquityTrack 权威边界冲突。
- **不首选动态 Cordis tool**：其 VM 明确不是安全边界（`packages/extensions/tool-cordis/README.md:21-23`）。
- **不首选裸 WebServer route**：Connection 已提供统一 envelope、取消与 Host trust fence；裸 route 会形成第二套传输和安全路径。
- **不首选 Typert Remote 初版**：它适合 DSH monorepo 内严格生成的 unary API，但要求显式 client assembly 和 Host/Client artifact 生成（`docs/api-gateway.md:76-78,150-160`）。adapter 自有版本化 JSON 合同更易独立发布和退出。稳定后若 DSH 提供成熟的 out-of-tree Remote 扩展流程，再重新评估。
- **不把 human command 当完整工作台**：它确实能绕过 model turn（`docs/subsystems/commands.md:29-55`），适合少量诊断或显式操作；但领域展示、确认版本和渐进披露更适合 client plugin + RPC。若使用 command，敏感输入应设置 `recordInput: false`，仍不能把其审计事件当业务确认。

### 5.3 最小交付顺序

Phase 2 不应一开始创建 `equity-research`、`equity-plan`、`equity-monitor`、`equity-review`、`equity-workbench` 五个 profile。Profile 是运行时插件组合，不是领域 Skill；过早一一映射会制造重复配置和升级面。

建议顺序：

1. `P2.0 — Compatibility spike`：在固定 DSH commit 上证明 out-of-tree bundle 能加载、`/equitytrack` loopback RPC 能调用一个无业务副作用的 Core health/contract endpoint，并证明卸载后无残留。
2. `P2.1 — Read-only workbench`：仅账户/计划状态的只读投影和研究产物查看；不得创建或激活计划。
3. `P2.2 — Explicit draft/confirmation`：允许 Core 创建草稿；确认必须由 Core 签发挑战并校验版本，DSH 只是呈现与转发。
4. `P2.3 — Optional DSH runner`：Phase 1 Bench 已稳定后，在支持的平台用 DSH headless/Python SDK 执行可选模型实验；案例、验证和评分仍在 EquityTrack。
5. `P2.4 — Additional profiles`：只有配置差异确有运行时意义时再拆 profile；不要因五个领域 Skill 而机械地创建五个 profile。

## 6. 权限与确认模型

必须区分三种完全不同的权限：

| 层 | 负责什么 | 不负责什么 |
|---|---|---|
| DSH sandbox | 子进程文件写入范围；可报告 full/partial | 网络隔离、业务授权、账户写入权限 |
| DSH approval | 一次具体工具动作是否允许，`allowed-once` 或 fail-closed | TradePlan 版本、确认状态、用户投资决策 |
| EquityTrack authority | 账户真值、计划状态机、风险政策、确认挑战、幂等和审计 | DSH 进程/UI 生命周期 |

Windows sandbox 文档明确指出 ambient ACL gaps 时只报告 partial，且 SandboxMode 不覆盖网络与进程可见性（`docs/subsystems/sandbox.md:9-30`）。所以即使 DSH UI 显示 `workspace-write + ask`，也不能据此宣称“Python Core 只可读”或“交易计划已被用户确认”。

推荐权限合同：

- 研究/估值/监控查询端点默认只读；
- draft 创建端点只能写入 `DRAFT`，不接受客户端直接传 `ACTIVE`；
- 激活/替代/关闭由 Core 验证 `confirmation_challenge + expected_version + user_intent`；
- 风险上限、仓位计算和状态转换全部在 Core 复算；客户端传来的结果只作建议输入；
- DSH adapter 进程凭据不包含券商下单权限；Phase 2 不接自动订单；
- Web 仅监听 loopback。DSH 自己说明 trust fence 不是认证层，且 `0.0.0.0` 当前不受支持（`packages/client/connection/README.md:7-13`）。

## 7. 版本锁定、升级和退出策略

### 7.1 锁定基线

Phase 2 首个 spike 应锁定：

- DSH git commit：`b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`；
- DSH tag/package：`dsh-v0.1.1-rc.2` / `@deepseek-ai/dsh@0.1.1-rc.2`；
- Node 范围：遵循 DSH 清单 `^22.19.0 || >=24.0.0`，生产选择一个精确 patch；
- pnpm：`11.7.0`；
- DSH lockfile 与 adapter 的 package tarball/hash；
- adapter↔Core 协议：`EquityTrackTaskRequest@1` / `EquityTrackTaskResult@1`；
- 独立 DSH_HOME 和 telemetry `DISABLED` 的有效配置快照（可用 `dsh --profile ... --dump-config` 核验；`apps/cli/README.md:30-43`）。

不要单独锁一个外部 Cordis semver来拼装。DSH vendored 并重命名了 Cordis，而且自己维护本地修改（`vendor/README.md:1-5,29-31`）；可审计单位应是完整 DSH commit 和 lockfile。

### 7.2 升级门

每次 DSH 升级必须在独立分支和独立 DSH_HOME 完成：

1. adapter 编译、插件加载/卸载和配置 fail-loud 测试；
2. Host↔Python contract conformance、超时、取消、崩溃和幂等测试；
3. client bundle 与 loopback RPC 浏览器验收；
4. telemetry-disabled 和无敏感日志断言；
5. Phase 1 全量金融 Bench；
6. 确认业务数据库字节/业务事件未被 DSH 升级或回滚修改；
7. 人工确认后才切换生产 profile。

DSH 当前明确拒绝旧格式且不提供迁移（`AGENTS.md:5-7`；`packages/core/session/src/types.ts:33-56`）。因此不要让升级流程原地修改唯一 `$DSH_HOME`；旧 DSH 日志可以保留为只读诊断附件，但不能把“新版本能继续旧会话”写成验收前提。

### 7.3 退出与回滚

退出条件必须在接入前可验证：

- 移除/禁用 `@equitytrack/dsh-adapter` bundle 后，EquityTrack 的 Skill/application interface/CLI 仍可完整运行 Phase 1 闭环；
- DSH session id 只存为可空 correlation，不参与业务主键、版本或幂等；
- 删除整个 DSH_HOME 只损失 DSH UI 偏好和对话轨迹，不损失账户、研究、计划、复盘或 Bench；
- UI 无本地-only 业务状态，所有页面可从 Core read model 重建；
- 回滚使用被锁定的旧 DSH artifact + 旧独立 DSH_HOME，不添加 session 格式 shim、dual-read 或业务 dual-write；
- 若 DSH API churn 使 adapter 成本超阈值，恢复 Phase 1 唯一入口，而不是把 Core 重写进 DSH/Cordis。

## 8. 对 Phase 2 文档的具体改写建议

建议保留的原判断：

- DSH 是插件化 Agent Harness；
- Cordis 能组合模型、工具、会话和 Agent loop；
- DSH session log 与 EquityTrack event store 必须分开；
- 先建金融 Bench，再接 DSH，再做 UI；
- Python 投资核心不重写成 TypeScript/Cordis；
- DSH 只是可替换 adapter，不拥有金融真值；
- 当前处于 developer preview，必须锁版本。

建议修正或补充：

1. 把“Python SDK 可在独立 workspace/session 运行 Agent”限定为**支持平台上的 DSH runner 能力**；明确当前 Windows 发布 SDK 不支持，且它不是 DSH→Python Core seam。
2. 把最薄桥改为 **DSH Host Cordis plugin → `ctx.subprocess` → EquityTrack versioned stdio protocol**；浏览器端使用 loopback-only Connection RPC。
3. 明确 DSH Workspace 只是现有目录注册，不是隔离机制；Bench runner 自己供应物理隔离。
4. 明确 DSH Skill 是提示词/说明文本，body 没有版本协议；五个金融 Skill 的可执行合同和版本仍属于 EquityTrack。
5. 明确内置 Web 是聊天基座，不是投资工作台；工作台需要 out-of-tree client bundle、slot/RPC 和持续适配成本。
6. 明确 DSH approval 不能代替 `TradePlan.confirmation_state`，sandbox 不覆盖网络且 Windows 可能 partial。
7. 将 telemetry disabled、loopback-only、动态 Cordis tool 禁用列为硬门。
8. 把五个 DSH profile 从初始交付移到可选后续；先做一个 adapter bundle、一个 workbench profile，Bench profile 后置。
9. 加入“当前 EquityTrack 运行时禁止 LLM”的冲突说明：DSH Agent 执行金融 Skill 需要新的显式架构决策；在此之前只允许 UI/transport/可选外部实验 runner。
10. 加入独立 DSH_HOME、精确 commit/lockfile、升级矩阵和无业务数据退出测试。

## 9. 审计边界与未验证事项

本次完成了本地源码、文档、manifest、git 状态、版本与 CLI help 的核验，没有：

- 启动 Web UI 并做浏览器交互验收；
- 安装或发布 out-of-tree EquityTrack 插件；
- 在 DSH 内运行真实模型请求；
- 构建 Python SDK wheel，或在 Linux/macOS 上执行 SDK 示例；
- 对 DSH 全仓运行 `check:all` / e2e / Web snapshot；
- 修改 DSH 仓库任何文件。

这些未验证项不影响“平台限制、持久化边界、SDK 支持矩阵和 Bench 缺失”的源码级结论，但 Phase 2 spike 必须补上实际插件加载、RPC、卸载、Windows Python 子进程和 Web 交互证据后，才能声称适配链可运行。

## 10. 可复现审计命令

```powershell
Set-Location -LiteralPath D:\dsh-proj\deepseek-harness
git status --short --branch
git rev-parse HEAD
git log -1 --format='%H%n%ad%n%s' --date=iso-strict
git describe --tags --always --dirty
git tag --sort=-version:refname
node --version
pnpm --version
pnpm dsh --version
pnpm dsh --help
rg --files | rg -i 'bench|eval|sdk|workspace|session|plugin|cordis|permission|telemetry'
```
