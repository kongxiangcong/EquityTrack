# Kimi Datasource 作为数据 Provider 的可行性研究

研究截至：2026-07-11（升级后 live 复验：Kimi Code CLI 0.23.5；Kimi Datasource 3.2.0）
适用范围：`E:\workspace\tradingSystem` 的个人、本地优先投研平台；本结论不授权商业使用、数据再分发、自动交易或无人值守高频采集。

## 升级后复验（2026-07-11）

### 复验结论

**CLI 与 Datasource 均已升级并通过 live 调用验证。升级使调用更容易诊断，但没有补齐数据来源身份、许可、PIT 时间、修订版本或复权因子版本。最终决策不变：Kimi Datasource 可作为 Codex/Skill 控制面的低频二级采集桥，不能作为本项目业务运行时的正式 `DataProvider`，不能单独支持关键财务事实、PIT 回测或可审计复权行情。**

插件升级在本轮研究过程中于 2026-07-11 21:59（Asia/Shanghai）写入托管副本。早一轮 3.1.0 现场检查因此只能作为升级前基线；以下以升级后的 managed manifest、源码 hash 和 live trace 为准：

| 项目 | 升级后现场事实 | 判断 |
|---|---|---|
| 实际命令 | `C:\Users\72449\.kimi-code\bin\kimi.exe` | PATH 首项正确；另有旧 npm shim，采集仍应记录绝对路径 |
| Kimi Code CLI | `0.23.5`；exe SHA-256 `ED1EF9E58B714927D63F7120A945F8A4A6B1CCAF303286A3256FF3AC5DE2D868` | 已从 0.19.1 升级成功 |
| 实际托管插件 manifest | `3.2.0`；manifest SHA-256 `3BF76FCB873F58105BDF3F26216D31A7643D4AD756073F55BD4F123182F4AD53` | 已升级并落盘 |
| 实际 MCP 源码 | 3.2.0；SHA-256 `1B0DFF6FD68A54C500F041AAF33C6653151E80C7EAE62B1131320F6EE80B669D` | 与官方 3.2.0 包内源码一致；live 结果出现 trace 行 |
| 官方最新 zip | 3.2.0；zip SHA-256 `0DAB1F77D1312F077306D54BB9D03DB0600A8AEB8572C736C288D52E37FD6173` | 本机托管源码与固定官方包一致 |
| Node | `v25.8.1`；exe SHA-256 `8CCFC9B16942FD1F4154E160A249805DD88EB0D253B789AA669B91CF0ADE6E57` | 可启动当前 MCP；不是数据正确性证明 |
| `kimi doctor` | 通过 | 只验证配置文件，不验证插件版本、Datasource entitlement 或数据质量 |

官方插件文档说明插件不会自动更新；必须在 TUI 的 `/plugins` 中重新安装/更新，再执行 `/reload` 或开启新会话。CLI 没有 `kimi plugin ...` shell 子命令；`kimi plugin list` 在 0.23.5 返回 `unknown command`，插件管理是 TUI 斜杠命令。[官方插件安装与激活说明](https://moonshotai.github.io/kimi-code/en/customization/plugins.html#installation)

### 新 CLI 与 live probes

本轮在独占 staging、`KIMI_DISABLE_TELEMETRY=1`、公开标的和短 prompt 下，用一个精确 session 串行执行 4 个 3.2.0 live probes；没有把账户、持仓、成本或凭据写入 prompt/产物：

1. 描述接口并获取 `002897.SZ` 在 2026-07-07 的一行未复权日线；
2. 请求 1990-01-01 至 1990-01-02 的公告空窗口；
3. 获取 2025-12-31 资产负债表；
4. 获取 2026-04-01 至 2026-05-15 公告索引。
5. 显式传入 `format=json` 并把目标命名为 `.json`，验证实际落盘格式。

可复现实测结果：

- 每次都严格出现 `get_data_source_desc -> call_data_source_tool`，未观察到额外 `Read/Write/Bash/Web/Yahoo`；显式 `--session` 连续恢复成功；这是本组短 prompt 的观察结果，不是 CLI 工具权限保证；
- live desc 有 9 个股票接口；`get_price` 仍限制最多 3 个 ticker、最多 3 年，而 3.2.0 静态 `SKILL.md` 仍写“历史接口最多 10 个”，静态 skill 与动态合约漂移没有被升级解决；
- 3.2.0 的每个 desc/data Tool result 都出现 `[kimi-datasource] request-id: ... · tool-call-id: ...`；`tool-call-id` 是本地生成的调用 UUID，`request-id` 是可选后端关联 ID，二者不能替代数据 provenance/PIT 字段；
- 单次端到端耗时分别约 25.06 秒（行情）、24.77 秒（空公告）、21.66 秒（财务表）、22.86 秒（38 行公告），平均约 23.59 秒；这适合人工按需补数，不适合低延迟或批量运行时同步；
- 行情 CSV 为 1 行、144 bytes、SHA-256 `7291F6CB4CCEBB2276123A968AB173D74A94D861A62318EB1E16DB4F4AE51E4B`；
- CSV header 仍只有 `open,high,low,close,volume,thscode,time,thsname_cn,thsname_en,currency`，没有上游发布者、来源 URL、请求参数、`adjust=none`、数据版本、`published_at`、`available_at`、`retrieved_at`、时区或复权因子版本；
- 财务表 CSV 为 1 行宽表，Tool result 有 backend endpoint 和抓取 timestamp，但 CSV 的 `time` 为空，仍无正式报告 URL、公告可用时间、币种/单位契约和修订版本；
- 非空公告 CSV 为 38 行，包含 `reportDate/ctime/reportTitle/pdfURL/seq`，但 PDF host 是 `ft.10jqka.com.cn`，不是 CNINFO/交易所官方域名；可用于公告发现，不能直接升级为官方 Evidence；
- 空公告 Tool result 为 `EMPTY_DATA`，Agent遵守本次 prompt 没有创建文件，但 CLI 仍退出 0。故 0.23.2 的“turn 失败返回非零”修复不覆盖“工具业务错误被 Agent 正常解释后完成”的情形。
- 显式 `format=json`、目标扩展名 `.json` 的行情调用仍写出相同的 CSV bytes（144 bytes，hash 与 `price.csv` 相同）；因此 `format` 和扩展名都不能作为内容类型证据，导入器必须 sniff bytes 并按实测 schema 解析。

Kimi Code 0.23.5 的官方变更仅改善 LLM Provider 的 429/过载重试可靠性，并在 `stream-json` 中展示重试事件；0.23.2 修复 prompt turn 真实失败仍退出 0 的问题。这些是 Agent/模型调用层的可靠性改进，不会给 Datasource MCP 增加业务错误枚举、数据 provenance 或 PIT 字段。[Kimi Code 变更记录](https://moonshotai.github.io/kimi-code/en/release-notes/changelog.html)

### 官方 3.2.0 能改变什么、不能改变什么

本轮固定官方 3.2.0 zip并逐行检查 MCP 源码，再用安装后的同 hash 源码完成 live probes。3.2.0 相对 3.1.0 的实质变化是：

- 补入 3.1.2 的环境匹配：Datasource endpoint 和 OAuth credential key 跟随当前 Kimi Code OAuth/base URL 环境；
- 新增 `yuandian_law`，与本项目股票数据无关；
- 每次后端请求生成 UUID 作为 `X-Msh-Tool-Call-Id`，从响应 header 尝试提取可选 `request-id`，并把 trace 行追加到成功或已捕获的失败文本中；
- `tool-call-id` 是调用诊断 ID，`request-id` 是可选后端关联 ID；二者都不是数据发布者、官方公告 ID、来源 URL、内容版本、`published_at` 或 `available_at`，不能替代 `source_manifest`；
- MCP 仍是固定 30 秒 timeout，源码未实现重试、退避、`Retry-After`、速率状态或熔断；CLI 0.23.5 的模型 Provider 重试不能推定为 Datasource 请求重试。

因此，**升级到 3.2.0 已被证实会改善故障关联和环境兼容性，但不会把 Kimi Datasource 升级为确定性、来源完备、PIT 合格的数据 API。** 当前分类保持：`adapt as llm_mediated_acquisition_bridge; reject runtime DataProvider`。

## 结论

**决策（经 CLI 0.23.5 + Datasource 3.2.0 源码和 live 调用复核后不变）：adapt，但只能作为 Codex/Skill 控制面的低频、用户触发“采集桥”（`llm_mediated_acquisition_bridge`）；拒绝把它实现为业务运行时 `DataProvider`，拒绝把其输出直接当作官方事实或 PIT 数据。可批准一个受控的 transcript-verifier 试点，但不能把它列为第一条纵向切片的必需依赖。**

Kimi Datasource 确实能用短 prompt 调用，能在 Windows 上连续恢复同一个 session，并能把完整结果写为 CSV。本机实测已经成功完成“读取动态接口说明 → 恢复 session → 获取一小段 A 股日线 → 让模型返回短 JSON”这一链路。因此它可以补充：

- 行情、公司资料、财务表、业务分部、股东、财务指标的结构化候选数据；
- A 股公告标题、发布时间、PDF URL 的来源发现；
- 现有正式 Provider 暂时缺失时的人工/控制面交叉核验。

但它不能直接成为平台的确定性 Provider，原因是：

1. Kimi Code 先由 LLM 解释 prompt、选择工具和参数，再调用 Datasource MCP；同一句 prompt 不能保证只调用指定工具。
2. `stream-json` 是 Agent 消息与工具事件的 JSONL，不是业务数据契约；最终 Assistant JSON 仍是概率生成结果。
3. 实测 CSV 没有上游发布者身份、来源 URL、`published_at`、`available_at`、Provider 数据版本或复权因子版本，无法单独满足当前仓库的证据与 PIT 门禁。
4. 负面实测中，Datasource 返回 `EMPTY_DATA` 后 CLI 仍以退出码 0 完成，Agent 随后使用通用 `Write` 工具创建了只有表头的 CSV；另一次受限 prompt 仍多读取了 `stock_finance_data` 与 `yahoo_finance` 两份描述。prompt 不是工具 allowlist，也不是数据真实性边界。
5. 官方条款与自动化边界存在未解冲突：CLI 文档明确支持 `-p` 用于脚本/CI，但 Kimi 通用服务条款禁止未经书面授权、以脚本或计划任务模拟人工使用，并禁止高频相似请求。[CLI 非交互模式](https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html#non-interactive-execution)；[Kimi 服务条款，第 2 节](https://www.kimi.com/user/agreement/modelUse?version=v2)
6. 本仓库的权威任务声明禁止业务运行时代码调用 Kimi 等 LLM API 或硬编码分析 prompt；只有 Codex/Skill 控制面可持有操作说明与编排模板。

推荐链路是：

```text
用户明确发起 / Codex 控制面
  -> 隔离目录中调用 Kimi Code CLI
  -> 保存完整 JSONL transcript + Datasource CSV
  -> 确定性导入器验证工具序列、路径、hash、schema 和数据质量
  -> 标记为 unknown_secondary / provenance_incomplete
  -> 必要时回到官方披露验证
  -> 才能进入 normalized store / DataSnapshot
```

业务运行时、每日后台任务、Web 服务、规则引擎、估值、回测和计划评估均不得直接启动 Kimi CLI 或 Kimi Agent SDK。

## 一、第一手证据基线

### 1. 本机安装状态

2026-07-11 的只读检查结果：

| 项目 | 本机事实 | 影响 |
|---|---|---|
| 实际解析的命令 | `C:\Users\72449\.kimi-code\bin\kimi.exe` | 必须记录绝对路径，不能假设 PATH 只有一个 Kimi |
| `kimi --version` | `0.23.5` | 已升级；每次采集仍需记录，不能只记录 npm 包版本 |
| 另一套安装 | 全局 npm `@moonshot-ai/kimi-code@0.6.0` 及 npm shims | Windows PATH 改变可能切换实际实现 |
| 实际加载的 Datasource 插件 | `3.2.0`，enabled；MCP SHA-256 `1B0D...669D` | 已与官方 3.2.0 包内源码一致，并完成 live trace 验证 |
| 最新官方插件 | `3.2.0` | 新增 backend `request-id` / `tool-call-id` 跟踪、环境匹配和法律数据源；不补金融数据 provenance/PIT |
| Node | `C:\Program Files\nodejs\node.exe`，`v25.8.1` | 插件 manifest 用 `node` 启动 MCP；原生 CLI 可运行不代表插件无需 Node |
| 配置检查 | `kimi doctor` 通过 | 只证明 TOML 有效，不证明 Datasource entitlement、余额或数据质量 |
| 本机模型上下文 | `max_context_size = 262144` | 这是模型上下文配置，不是已发布的 prompt 长度 SLA |

本机已安装插件由 Kimi 官方 zip URL 安装；manifest 位于 `...\managed\kimi-datasource\kimi.plugin.json:1-17`，声明开发者为 Moonshot AI、版本 `3.2.0`、通过 `node ./bin/kimi-datasource.mjs` 提供 MCP。`installed.json.updatedAt` 可能滞后，本轮以 CLI 实际使用的 managed manifest、MCP hash 和 live trace 三者共同判断生效版本。

官方文档当前标注最新版本为 `3.2.0`，且说明插件不会自动更新。[Kimi Code 插件文档](https://moonshotai.github.io/kimi-code/en/customization/plugins.html#kimi-datasource)

为避免研究过程再次修改用户级插件状态，本轮重新下载并解包了最新官方 zip，只用于源码与哈希比较，没有替用户安装。下载 URL 与快照：

- URL：`https://code.kimi.com/kimi-code/plugins/official/kimi-datasource.zip`
- SHA-256：`0DAB1F77D1312F077306D54BB9D03DB0600A8AEB8572C736C288D52E37FD6173`
- manifest 版本：`3.2.0`
- `CHANGELOG.md`：3.2.0 新增 `yuandian_law`，并给工具结果增加 `request-id` / `tool-call-id`；3.1.2 让 OAuth 凭据与 Datasource endpoint 跟随当前 Kimi Code 环境
- zip 内未发现独立 `LICENSE` 文件

Kimi Code CLI 本体以 MIT 发布，但这只覆盖 CLI 软件，不自动授予 Datasource 服务或上游金融数据的使用、缓存和再分发许可。[Kimi Code 仓库与许可证](https://github.com/MoonshotAI/kimi-code)

### 2. 插件真实调用协议

已安装 `SKILL.md:10-19,36-49` 与当前官方 3.2.0 包都要求固定两步：

1. `get_data_source_desc(name)`：现场获取当前接口、参数和限制；
2. `call_data_source_tool(data_source_name, api_name, params)`：按动态说明调用。

插件明确说后端 API 会调整，故意不把具体 API/参数静态写死。它不是一个稳定、版本化的普通 Python/HTTP SDK 契约。

3.2.0 MCP 源码显示：

- MCP 自身只有 `get_data_source_desc` 与 `call_data_source_tool` 两个工具；
- 通过 OAuth token 向 `${KIMI_CODE_BASE_URL}/tools` 发送请求；
- 每次请求超时固定 30 秒；
- 没有内置重试、退避、`Retry-After` 或熔断；
- 非 2xx 响应变成工具错误文本；
- 返回文件只有在等于请求的 `file_path`，或位于同目录且使用同扩展名/预期前缀时才会落盘；
- 3.2.0 会给工具结果追加 `request-id`（若后端返回）和本地生成的 `tool-call-id`。

这些事实来自上述 SHA-256 固定的 3.2.0 官方 zip 中 `bin/kimi-datasource.mjs`，其 SHA-256 为 `1B0DFF6FD68A54C500F041AAF33C6653151E80C7EAE62B1131320F6EE80B669D`；当前实际安装源码 hash 与之相同。升级前 3.1.0 源码 SHA-256 `11C4645A39CDECFC06F26984C3302530D8456DB85EA51736A9E4D3E58E3AB500` 仅保留为历史对比。

**不要绕过 Kimi Agent 直接把内部 MCP 脚本或 `/coding/v1/tools` 当公开 API。** 插件自身明确要求由 Kimi Code 托管调用；该网关没有独立的公开稳定性、许可、配额和兼容性承诺，直连属于内部接口依赖。

## 二、可用数据与接口约束

官方文档声称 Datasource 覆盖 A 股、港股、美股及主要全球市场的实时/历史行情、技术指标、财务表和选股，并按调用消耗 Kimi Code 账户 credits；插件只读，不提供写入或交易能力。[官方覆盖与计费说明](https://moonshotai.github.io/kimi-code/en/customization/plugins.html#coverage)

本机 2026-07-11 live `get_data_source_desc("stock_finance_data")` 返回九个接口：

| API | 能力 | live 主要限制 | 作为本平台数据的评级 |
|---|---|---|---|
| `get_price` | 历史股票/指数/商品 OHLCV | 最多 3 个 ticker、单次最多 3 年，`D/W/M/Q/Y`，`forward/backward/none` | 补充行情/交叉核验；无因子版本时不具 PIT 资格 |
| `get_stock_realtime_price` | 开/收盘摘要、实时价、实时技术指标 | 最多 3 个；实时技术指标仅部分 A 股，港/美/ETF/科创板受限 | 仅当时市场观察；指标应由本地代码重算 |
| `get_financial_statements` | 资产负债、利润、现金流 | 最多 3 个 ticker，以报告期末参数查询 | 结构化候选；不能代替官方报告 |
| `get_stock_financial_index` | 六类财务指标 | 指定报告期和类别 | 交叉核验；正式指标应本地确定性计算 |
| `get_stock_business_segmentation` | 行业/产品/地区收入、成本、毛利 | 指定报告期 | 结构化候选；回到官方附注验证 |
| `get_stock_info` | 公司/股本/控制人/业务等 | 最多 3 个；`request_time` 默认今天 | 主数据候选；稳定身份和历史状态不能只靠它 |
| `get_holder_info` | 股东与持股变化 | 最多 3 个；`request_time` 默认今天 | 候选/交叉核验 |
| `get_stock_announcement` | A 股公告索引、发布时间、标题、PDF URL、序号 | 指定日期范围 | 适合作为官方 PDF 的发现索引，不是官方原文自身 |
| `get_forecast` | A 股预测数据 | 强制使用今天作为 `request_time` | 只能作为外部估计，禁止标成 Fact 或历史 PIT |

存在已证实的契约漂移：实际安装的 3.1.0 与重新下载的官方 3.2.0 `SKILL.md` 都声称历史接口最多 10 个 ticker，而升级后 live `get_price` 描述限制最多 3 个。因此，升级并没有修复静态说明漂移；静态 prompt/代码不能信任 skill 中的旧上限，每个 session 或每个被缓存的 desc 版本必须先执行并保存动态接口说明。

### 数据来源身份仍不合格

live 描述只说 `stock_finance_data is a financial data platform provided by stock_finance_data Inc.`，没有提供可核验的法律主体、产品页面、数据授权链、字段来源或 SLA。实测字段常有 `ths...` 前缀，**可以推断**其部分数据可能来自同花顺/iFind 体系，但当前一手证据不足，不能把该推断写成 `publisher=iFind` 或 `source_authority=official`。

在获得明确上游身份和许可前，统一标记：

```text
source_authority = unknown_secondary
provenance_status = incomplete
pit_eligible = false
redistribution_allowed = unknown
```

## 三、本机调用与连续短 prompt 实测

### 1. 命令模式

官方 CLI 支持：

- `-p/--prompt`：单次非交互 prompt；不会打开 TUI；
- `--output-format stream-json`：stdout 按行输出 Agent/Tool/Meta JSON 对象；
- `--session <id>` / `-r <id>`：恢复精确 session；
- `--continue`：恢复当前工作目录最近 session。

prompt 模式本身采用 auto permission，不能与 `--yolo`、`--auto` 或 `--plan` 组合；stderr 仍可能包含工具进度和恢复提示。[`kimi` 命令参考](https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html)

初次研究在隔离的 Windows 临时目录中用三个短 prompt 连续成功：

1. 只调用 `get_data_source_desc(stock_finance_data)`，要求最终仅列 API 名；
2. 用返回的 session id 恢复会话，只调用 `get_price` 获取 `600519.SH` 三个交易日、不复权日线并写临时 CSV；
3. 再次恢复会话，不调用工具，要求把上一步状态压成一行 JSON。

观察结果：

- `stream-json` 按顺序给出 Assistant `tool_calls`、Tool `content`、Assistant 最终回答和 Meta `session_id`；
- session id 能被 `-r` 连续复用；
- CSV 成功写入 Windows 绝对路径，3 行，SHA-256 为 `4673C4DBE02EFC6D617BF18D8D5B932B748C1E49C3528532CA0A25F2F186268C`；
- CSV 头只有 `open, high, low, close, volume, thscode, time, thsname_cn, thsname_en, currency`；
- CSV 没有请求参数、`adjust=none`、上游来源、数据版本、`published_at`、`available_at`、`retrieved_at`、时区或交易日历版本；
- 第三步的短 JSON 格式服从了 prompt，但这不使它成为可信业务结果。

其他隔离实测进一步发现：

- 另一段价格 CSV 同样缺失来源与 PIT 元数据；
- 财务表的 Tool 事件包含 endpoint/timestamp 一类文字，但落盘 CSV 未携带，最终 Assistant JSON还错误判断了 provider timestamp 是否存在；
- 公告查询返回 `EMPTY_DATA` 时，CLI 进程仍退出 0，随后 Agent 使用 `Write` 创建了表头 CSV；
- 即使 prompt 限制工具，Agent仍可能额外查询另一个 Datasource 描述。

CLI 0.23.5 复验时，Agent对相同 `EMPTY_DATA` 服从了“禁止创建文件”的短 prompt，因此没有再次生成表头文件；但进程仍退出 0。单次服从不能建立工具权限保证，也不能推翻此前已观察到的 `Write` 偏航。0.23.5 没有新增“只允许某个 Datasource Tool”的命令行 allowlist。

因此：**退出码 0、最终 JSON、目标文件存在、甚至 CSV schema 正确，都不能单独证明数据来自 Datasource。完整 Tool transcript 才是最小审计对象。**

### 2. Session 语义与并发约束

Kimi Code 会把每次会话的完整通信记录保存到 `$KIMI_CODE_HOME/sessions/<workDirKey>/<sessionId>/agents/main/wire.jsonl`；`--continue` 以工作目录查找最近会话，`--session` 恢复指定会话。[Session 文档](https://moonshotai.github.io/kimi-code/en/guides/sessions.html)；[数据目录](https://moonshotai.github.io/kimi-code/en/configuration/data-locations.html#session-data)

推荐：

- 一个采集 job 一个隔离 staging 工作目录与一个 session；
- 后续调用只用精确 `--session <id>`，不用 `--continue`，避免并发任务争用“最近 session”；
- 同一 session 严格串行，不并行 resume；
- session 只覆盖一个标的和一个数据族，完成后关闭；不要长期累积上下文；
- 保存 JSONL transcript 的脱敏副本及 SHA-256，但不得复制 OAuth token 或全局日志；
- 失败重跑创建新的 attempt 记录，不篡改原 session 证据。

没有找到官方发布的 Datasource 专属 prompt 长度上限。`262144` 是当前本机模型上下文配置，不是服务 SLA。真正需要控制的是动态 desc 体积、credits、延迟和模型偏航。把长 JSON schema 放进 prompt 没有价值；schema 应由本地确定性导入器维护。

## 四、推荐的短 prompt 协议

以下命令只允许由 Codex/Skill 控制面在用户明确发起时调用，不得复制进业务运行时代码。

### 1. 启动与描述阶段

PowerShell 调用骨架：

```powershell
$kimi = (Get-Command kimi.exe).Source
$env:KIMI_DISABLE_TELEMETRY = '1'
& $kimi -p $describePrompt --output-format stream-json
```

短 prompt：

```text
只调用 kimi-datasource 的 get_data_source_desc 查询 stock_finance_data；不要查数据，不要写文件。最终只返回 API 名。
```

控制面从 Meta 行读取 `session_id`，从 Tool 行保存完整 desc；不要从最终 Assistant 文本恢复接口定义。

### 2. 一次只取一个数据集

```powershell
& $kimi --session $sessionId -p $queryPrompt --output-format stream-json
```

历史行情示例：

```text
继续上一步。仅用 get_price 查 {ticker} 在 {start} 至 {end} 的日线，adjust=none；写入 {absolute_csv_path}。不要分析，最终只回状态和路径。
```

财务表示例：

```text
继续上一步。仅查 {ticker} 的 {period_end} {statement}；写入 {absolute_csv_path}。不要计算或补缺，最终只回状态和路径。
```

公告索引示例：

```text
继续上一步。仅查 {ticker} 在 {start} 至 {end} 的公告索引；写入 {absolute_csv_path}。空数据就报 EMPTY_DATA，禁止创建文件。
```

拆分规则：

- 每个 prompt 只包含一个 `data_source_name`、一个 API、一个数据集和一个输出路径；
- 使用已核验的完整 ticker，不在同一调用里让模型猜代码；
- 当前 live 合约最多 3 个 ticker，保守按 1 个 ticker 调用；
- 历史行情每次不超过 3 年，第一条切片按月/年小窗口分段；
- 财务表按一个报告期、一个 statement 拆分；
- 不让 Kimi 做估值、指标计算、数据合并、缺失填充或事实判断；
- 不在 prompt 中放持仓数量、成本、现金、账户、交易计划、风险预算或标注；
- 不使用插件的 `watchlist.json` 持仓成本/数量能力。

短 prompt 能降低偏航，但**不能防止**偏航。工具序列审计才是强制边界。

### 3. 结构化输出不要交给模型

`--output-format stream-json` 只保证 CLI 事件是 JSONL。业务 envelope 应由本地 importer 从 Tool event 与文件生成：

本项目若做控制面试点，入口不应接受任意自然语言，而应接受一个窄的结构化请求，再由版本化模板生成短 prompt：

```json
{
  "job_id": "uuid",
  "dataset": "daily_price|financial_statement|announcement_index",
  "ticker": "002897.SZ",
  "start_date": "2026-07-07",
  "end_date": "2026-07-07",
  "period_end": null,
  "statement": null,
  "adjust": "none",
  "output_path": "<absolute allowlisted staging path>",
  "expected_schema_version": "kimi-stock-finance-price-v1"
}
```

控制面用静态映射把 `dataset` 转成唯一允许的 `api_name` 和 params；ticker、日期、枚举、最大窗口和绝对路径在启动 Kimi 前先本地校验。Kimi 只能负责执行动态 desc + 指定工具调用，不能决定业务数据集、补默认值、改日期范围或生成 schema。`format=json` 当前没有足够稳定证据，试点以 Tool event + 实际 CSV bytes 为准，不依赖模型声称的格式。

建议的项目接口边界是：

```text
KimiAcquisitionRequest
  -> versioned short-prompt renderer
  -> kimi.exe stream-json runner (isolated staging, exact session)
  -> transcript verifier (tool allowlist + exact params + error semantics)
  -> CSV schema/quality verifier
  -> KimiAcquisitionResult + immutable RawArtifact
  -> unknown_secondary candidate importer
  -> official-source binder / deterministic Provider cross-check
  -> normalized store / DataSnapshot
```

`KimiAcquisitionResult` 必须把 `complete / empty / failed / rejected_agent_deviation` 分开；任何 `EMPTY_DATA`、非预期工具、参数漂移、文件缺失或 schema drift 都不得转成 `complete`。该接口属于 Codex/Skill 控制面研究工具，不进入平台业务 runtime contract。

导入器生成的 envelope 示例：

```json
{
  "provider_kind": "llm_mediated_acquisition_bridge",
  "provider": "kimi-datasource",
  "data_source_name": "stock_finance_data",
  "api_name": "stock_finance_data_get_price",
  "cli_path": "...",
  "cli_version": "...",
  "plugin_version": "...",
  "session_id": "...",
  "tool_call_id": "...",
  "backend_request_id": null,
  "params": {},
  "prompt_template_version": "...",
  "prompt_sha256": "...",
  "retrieved_at": "...",
  "output_path": "...",
  "output_sha256": "...",
  "row_count": 0,
  "source_authority": "unknown_secondary",
  "provenance_status": "incomplete",
  "pit_eligible": false,
  "status": "complete|empty|failed|rejected",
  "errors": []
}
```

这个 envelope 的值不得从最终 Assistant 自述复制；版本、时间、路径、hash、行数和工具序列全部由本地代码读取或计算。

## 五、强制验证门禁

只有全部通过时，Kimi 产物才可作为 `unknown_secondary` 候选导入；任一项失败就保留 transcript 并拒绝数据文件。

### Gate 0：架构边界

- 调用发生在 Codex/Skill 控制面，而非应用、Web server、worker、每日任务、策略、估值或回测代码；
- 仓库业务依赖中不存在 Kimi CLI/Agent SDK/LLM client；
- prompt 模板不进入业务运行时代码。

### Gate 1：环境与版本

- 记录 `Get-Command kimi.exe` 的绝对路径与 `kimi --version`；
- 记录插件 manifest 版本和 MCP 源文件 hash；
- `kimi doctor` 通过，OAuth 有效，Node 可解析；
- 每个采集 job 都记录 managed manifest 版本与 MCP 源码 hash；当前已验证 3.2.0，未来升级后仍须重新固定版本并跑 contract probes；
- 设置 `KIMI_DISABLE_TELEMETRY=1`，但不得误称这会阻止服务端处理 prompt、文件内容或设备头。

### Gate 2：调用序列 allowlist

对 JSONL transcript 做确定性检查：

1. 正好一个 `get_data_source_desc(stock_finance_data)`；
2. 正好一个预期的 `call_data_source_tool`；
3. `data_source_name`、`api_name` 与每个 params 精确匹配请求；
4. 没有 `Write`、`Bash`、`WebSearch`、其他 Datasource、其他文件读取或子 Agent 调用；
5. Tool event 没有 `isError`、`EMPTY_DATA`、HTTP error、timeout、auth/credits 错误；
6. 3.2.0 下记录 `tool-call-id`，能取得时同时记录 backend `request-id`。

不能满足精确序列时，即使文件存在也标记 `rejected_agent_deviation`。

### Gate 3：文件真实性与幂等

- 输出只能位于 job 独占 staging 目录的 allowlist 路径；
- 调用前路径必须不存在；调用后必须由预期 MCP Tool event 声明返回；
- 禁止接受由通用 `Write`/shell 创建的文件；
- 文件非空、可解析、编码明确、header 与契约匹配；
- 计算 bytes SHA-256、row count、创建时间和本地 `retrieved_at`；
- raw 以 hash 只追加保存，不覆盖；相同 hash 幂等复用；
- CSV 与 JSONL transcript 必须在同一 `ArtifactManifest` 中关联。

### Gate 4：数据质量

- ticker、交易所、币种、日期、行数与请求一致；
- natural key 唯一、日期递增、目标区间没有意外越界；
- OHLC 满足 `low <= open/close <= high`，volume 非负；
- 空数据不是 0，不创建伪 fixture；
- provider 间冲突输出 conflict，不自动择一；
- 技术指标、财务比率和估值结果由本地代码重算，不信任 Datasource 派生值。

### Gate 5：证据与 PIT

- 缺少上游 URL/发布者/版本时保持 `source_authority=unknown_secondary`；
- 缺少 `published_at`/`available_at` 时 `pit_eligible=false`，不得进入历史回测或历史计划评估；
- 前/后复权序列缺少因子版本时不得充当 canonical PIT 行情；优先请求 `adjust=none`，公司行动和因子走确定性 Provider；
- 财务表只有 `period_end` 不等于可用时间；没有官方公告校验就不能进入关键事实 source manifest；
- 公告索引只有在下载并 hash 官方 PDF、核验官方发布页后，相关事实才可升级为官方证据；
- `forecast` 始终为外部估计/预测，不得提升为 Fact。

### Gate 6：失败、限流与重试

插件内部只有 30 秒 timeout，没有可靠重试。控制面最多对 timeout、明确 429 或 5xx 做低频、有限重试，并为每次尝试保留独立记录；不得对以下错误自动重试：

- 鉴权过期、余额/entitlement 不足；
- 参数错误、`API_NOT_FOUND`、schema drift；
- `EMPTY_DATA`；
- 来源身份或许可不明；
- 工具序列偏航；
- 数据冲突或质量检查失败。

CLI 退出码 0 不能代表数据成功。最终状态必须来自 Tool event + 文件 + schema 三方共同判定。

## 六、隐私、许可与自动化约束

### 1. 数据会离开本机

Datasource 是 OAuth 托管的远程服务，不是本地数据库。Kimi 隐私政策把 prompts、files 和生成内容列为 User Content，并说明可用于提供、改进和训练服务；还会收集设备、会话和使用信息。[Kimi 隐私政策](https://www.kimi.com/user/agreement/userprivacy?version=v2)

Kimi Code 本地还会保存完整 session `wire.jsonl`、输入历史和诊断日志；关闭 telemetry 不会清理这些文件。[数据目录文档](https://moonshotai.github.io/kimi-code/en/configuration/data-locations.html)

因此：

- 只能发送公开证券代码和完成查询必需的公开时间参数；
- 禁止发送个人账户、现金、持仓成本/数量、交易流水、交易计划、风险配置、标注和未公开研究；
- 不导出包含全局日志的 session debug zip；
- session/transcript 的留存、清理和脱敏需要单独策略；
- 用户若希望禁止 Content 用于模型改进，需要按官方条款提供的渠道确认 opt-out，不能由本项目猜测账户状态。

### 2. 数据许可没有被 CLI 的 MIT 许可证解决

官方 plugin zip 没有独立数据许可证，动态 desc 没有上游条款。Kimi 服务条款要求用户自行遵守第三方服务条款，并保留服务及相关数据的权利，未经授权不得复制、分发或用于未授权目的。[第三方服务与知识产权条款](https://www.kimi.com/user/agreement/modelUse?version=v2)

在明确许可前：

- 仅限个人、低频、非再分发研究；
- raw CSV 和 transcript 只保存在本机，不进入公开仓库或报告附件；
- fixture 是否可长期提交 Git 仍属阻塞项；优先使用自行构造的 schema fixture，而不是复制远程真实数据；
- 若平台变为多人、商业或对外服务，Kimi Datasource 路线必须重新取得书面许可。

### 3. 自动化条款阻塞生产 Provider

Kimi Code 文档公开支持 `-p` 用于 script/CI，但 Kimi 通用服务条款同时禁止未经书面授权的 bot/script/scheduled task 模拟人工访问，并限制高频相似请求。没有找到 Datasource 专属条款来消除这一冲突。

所以当前允许的是：

- 用户明确发起、Codex 控制、低频、单次有界的研究采集；
- 产物经过本地确定性验证后人工/控制面导入。

当前禁止的是：

- 平台每日任务、后台 worker、cron、Web 请求自动调用；
- 批量全市场抓取；
- 自动重试风暴；
- 把 Kimi credits 当作正式 Provider SLA；
- 在没有书面授权时对外提供基于该服务的自动数据产品。

## 七、与现有 Provider 组合的最终定位

| 能力 | Kimi Datasource 决策 | 正式首选仍是 |
|---|---|---|
| 证券主数据 | adapt：候选/交叉核验 | 交易所列表、Tushare（有权限） |
| 未复权日线 | adapt：控制面补充或交叉核验 | Tushare / 固定版本 AKShare adapter |
| 复权行情 | reference only：缺因子版本 | 未复权价 + 公司行动 + 可版本化因子 |
| 财务表与分部 | reference only：结构化候选 | CNINFO/交易所/公司正式报告 |
| 公告 | adapt：来源发现索引 | 官方公告页与 PDF raw |
| 财务指标/技术指标 | reference only | 本地确定性代码计算 |
| 外部预测 | reference only，明确 estimate | 有来源与可用时间的共识数据；否则 missing |
| 历史回测/PIT | reject | 带 `available_at` 和版本的确定性 Provider |
| 每日自动同步 | reject | 普通代码 Provider adapter |
| 个人账户/持仓/计划 | reject transmitting | 仅本地数据库 |

Kimi 的存在不改变原 Provider 研究的主结论：官方披露保权威，Tushare/AKShare 等确定性 adapter 提供结构化市场数据，Kimi 只能在控制面补充来源发现或候选值。

## 八、最小试点建议

如果后续决定试点，应把范围限制为一个可删除的研究工具，而不是纵向切片的必需依赖：

1. 以当前已验证的 0.23.5 + 3.2.0 固定版本，只实现 transcript verifier + staging importer，不实现业务运行时 Kimi subprocess；
2. 先覆盖一个标的、一个月 `adjust=none` 日线和一个公告索引窗口；
3. 对同一窗口用正式 Provider/官方披露做逐字段对账；
4. 验证 Agent 偏航、`EMPTY_DATA + exit 0`、伪造文件、timeout、auth expired、schema drift；
5. 将 `request-id/tool-call-id` 只用于 attempt 诊断，不能作为 source/version key；
6. 未取得自动化与数据留存许可前，不接 daily sync、不进入正式 cache chain；
7. 任何 provenance/PIT 门禁失败都降级为 `data_insufficient_memo` 或辅助候选，不恢复估值权限。

该试点可以验证“控制面采集桥”是否节省人工整理时间；它不能证明 Kimi 是生产数据 API。

## 九、未解决证据缺口

以下缺口在补齐前阻止 Kimi 成为正式 Provider：

- `stock_finance_data` 的真实法律主体、上游数据源、许可、缓存与再分发条款；
- Datasource 专属的自动化授权，是否允许 Codex/CLI 连续调用、计划任务或产品集成；
- 每个 API 的 credits 价格、账户额度查询、速率限制、并发限制和 SLA；
- 数据修订、历史回放、删除、更正和 schema 版本政策；
- 财务表的正式公告 URL、`published_at`、`available_at` 与更正关系；
- 未复权/前复权/后复权的因子来源、版本和公司行动处理；
- 实时价的市场时间、延迟等级、快照时间与交易所状态；
- CSV 字段类型、单位、精度、缺失值和编码的稳定契约；
- Kimi Datasource 专属 prompt 长度/上下文/响应大小限制；
- 429/credits exhausted/overload 的机器可读错误枚举和重试指引；
- `format=json` 的稳定语义，以及完整结果是否始终以 CSV 落盘；
- 用户账户是否已选择不把 Content 用于模型改进；
- 真实数据 fixture 能否合法提交 Git 或长期保存。

## 主要第一手来源

- [Kimi Code Plugins / Kimi Datasource](https://moonshotai.github.io/kimi-code/en/customization/plugins.html#kimi-datasource)
- [Kimi Code 变更记录](https://moonshotai.github.io/kimi-code/en/release-notes/changelog.html)
- [`kimi` 命令与非交互 JSONL](https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html)
- [Kimi Code Sessions](https://moonshotai.github.io/kimi-code/en/guides/sessions.html)
- [Kimi Code 数据目录](https://moonshotai.github.io/kimi-code/en/configuration/data-locations.html)
- [Kimi Code 环境变量与 telemetry 开关](https://moonshotai.github.io/kimi-code/en/configuration/env-vars.html)
- [Kimi Code 官方源代码与 MIT 许可证](https://github.com/MoonshotAI/kimi-code)
- [Kimi 服务条款，2026-01-21 生效](https://www.kimi.com/user/agreement/modelUse?version=v2)
- [Kimi 隐私政策，2025-07-07 更新](https://www.kimi.com/user/agreement/userprivacy?version=v2)
- [Kimi Datasource 官方 zip](https://code.kimi.com/kimi-code/plugins/official/kimi-datasource.zip)
- 本机官方插件安装记录、manifest、skill 与 MCP 源码：`C:\Users\72449\.kimi-code\plugins\installed.json`、`C:\Users\72449\.kimi-code\plugins\managed\kimi-datasource\`
