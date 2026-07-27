# Tushare 与 Kimi Datasource：项目适配与实测比较

研究日期：2026-07-11  
适用范围：`E:\workspace\tradingSystem` 第一条 A 股纵向切片，以及后续本地优先、可审计、可复现的数据 Provider 设计。

## 结论

**Kimi Datasource 不能完整替代 Tushare。** 两者处于不同层：

- **Tushare：`adapt, optional production DataProvider`**。适合证券主数据、交易日历、未复权日线、复权因子、全市场横截面、财务结构化候选和披露日索引。它可以由普通代码确定性调用，适合增量同步、缓存和回测输入。
- **Kimi Datasource：`adapt, Codex/Skill control-plane acquisition bridge`**。适合用户明确触发的低频查询、非结构化信息发现、候选值补充和跨数据源语义检索；不应成为业务运行时 Provider。
- **官方披露：`adopt as authority`**。CNINFO、SSE、SZSE、BSE 和公司 IR 仍是公告原文、公司行动和关键财务事实的权威来源。Tushare 与 Kimi 都不能单独把聚合财务值升级为正式 Evidence。

Kimi 只能替代 Tushare 的一小部分人工、单标的、低频查询；不能替代批量同步、市场宽度、稳定字段契约、复权因子、全市场横截面和可重复回测数据。反过来，Tushare 也不能替代 Kimi 的自然语言路由、非结构化原文阅读和跨领域数据发现。

对第一条纵向切片，推荐的数据链为：

```text
官方披露 adapter（权威事实）
  + Tushare adapter（可选的结构化市场/财务索引）
  + AKShare/fixture adapter（无凭据回退与测试）
  + Kimi Datasource（运行时之外的人工触发候选采集）
```

## 重要访问边界

本轮按用户提供的说明，通过 `tx.xiaodefa.top` 完成 HTTP、Python SDK 和 MCP 实测。该主机不是 `tushare.pro` 官方域名；虽然响应兼容 Tushare Pro 协议，**其运营者、上游授权链、数据许可、日志策略、SLA 和长期稳定性尚未核实**。

因此本轮只能证明“这个兼容网关当前可用”，不能把它等同于“Tushare 官方服务已完成生产验收”。生产 adapter 应优先使用 Tushare 官方 endpoint；若继续使用该网关，必须先完成供应商与安全治理。

项目通过环境托管的批准 adapter seam 使用该兼容网关。凭据与 endpoint 边界见 [`tushare_usage.md`](tushare_usage.md)；调用方不接收 endpoint，不要求用户粘贴凭据，也不在源码、Git、报告、artifact 或日志中保存连接参数。

## 本轮实测

### 测试对象

- 标的：意华股份 `002897.SZ`
- 行情窗口：2026-07-01 至 2026-07-07，共 5 个交易日
- 财务期间：2026-03-31
- 公告窗口：2026-04-01 至 2026-05-15
- 本机 Tushare Python SDK：1.4.24，BSD 客户端许可证
- Kimi 对照：Kimi Code CLI 0.23.5 + Kimi Datasource 3.2.0 的既有 live 产物

### 接口结果

| 调用面 | 接口 | 结果 | 关键观察 |
|---|---|---|---|
| HTTP | `trade_cal` | 成功，11 行 | 有 `exchange/cal_date/is_open/pretrade_date` |
| HTTP | `daily` | 成功，5 行 | 有 OHLC、昨收、涨跌额、涨跌幅、成交量与成交额 |
| HTTP | `adj_factor` | 成功，5 行 | 每日因子为 `1.6642`；可与未复权行情分开保存 |
| HTTP | `stock_basic` | 成功，1 行 | 返回交易所、币种、上市状态、上市日等主数据 |
| HTTP | `balancesheet` | 成功，2 行 | 两行分别为 `update_flag=1/0`，导入时不能无版本去重 |
| HTTP | `disclosure_date` | 成功，1 行 | 返回计划/实际披露日期，但仍只有日期精度 |
| HTTP | `anns_d` | 失败，HTTP 业务码 403 | 当前凭据没有公告独立权限 |
| Python SDK | `index_basic` | 成功，5 行 | SDK 通过自定义网关返回指数主数据 |
| Python SDK | `pro_bar(adj=None)` | 成功，5 行 | 与 HTTP 未复权日线一致 |
| MCP | `initialize` | 成功 | server=`tushare-mcp-static/1.0.0`，协商到协议 `2024-11-05` |
| MCP | `tools/list` | 成功，273 个工具 | 接口覆盖很广，但数量本身不代表权限全部可用 |
| MCP | `tools/call daily` | 成功 | schema 声明 `symbol`，实际传 `ts_code` 也成功，存在 schema/实现漂移 |

### 与 Kimi 的逐值对照

行情对照结果：

- 5 个交易日的 open/high/low/close **全部一致**。
- Tushare `vol` 的官方单位是“手”，保留两位小数；换算为股后，Kimi 每日分别少 22、37、72、90、93 股。Kimi CSV 把成交量表示为“股”但丢失了不足一手的尾数。
- Tushare 还提供 `pre_close/change/pct_chg/amount`；本次 Kimi CSV 没有这些字段。
- Kimi CSV 有股票中英文名和币种；Tushare 将这类字段放在 `stock_basic` 等主数据接口，不在日线中重复。

财务对照结果：

| 字段 | Tushare | Kimi | 判断 |
|---|---:|---:|---|
| 总资产 | 6,855,000,420.80 | 6,855,000,420.80 | 一致 |
| 总负债 | 3,963,710,136.38 | 3,963,710,136.38 | 一致 |
| 归母权益 | 2,842,639,753.42 | 2,842,639,753.42 | 一致 |
| 报告期/公告日 | `end_date/ann_date/f_ann_date` 可用 | `time` 为空 | Tushare 更适合 PIT 前置治理 |
| 更新版本 | `update_flag=1/0` 两行 | 无显式版本字段 | Tushare 更好，但必须保留版本并确定性选取 |

这组样本说明 Kimi 的数值并非明显错误，但也说明“数值相同”不能弥补单位、精度、时间和版本字段缺失。

### 调用耗时观察

- Tushare HTTP 5 个顺序请求总计约 16 秒，约 3.2 秒/次。
- Python SDK 的 2 个顺序请求总计约 11.4 秒。
- 既有 Kimi Datasource 4 次短请求平均约 23.59 秒/次。

这些只是同一工作站、不同时间的观察，不是 SLA 或严格性能基准。结构差异比速度数字更重要：Tushare 是一次确定性 API 请求；Kimi 还包含模型推理、动态描述读取、工具选择和最终回复。

## 项目能力矩阵

| 项目需要 | Tushare | Kimi Datasource | 能否由 Kimi 替代 |
|---|---|---|---|
| `Security` 主数据 | 强：代码、交易所、币种、上市/退市状态、上市日 | 可查询候选，但接口动态且批量受限 | **不建议** |
| 交易日历 | 强：结构化、可批量、含前一交易日 | 当前股票接口未形成稳定日历契约 | **不能稳定替代** |
| 未复权日 OHLCV | 强：字段、单位、更新时间、批量限制明确 | 单标的可用，实测 OHLC 一致；来源/PIT 元数据不足 | **仅可低频补充** |
| 复权因子 | 强：独立 `adj_factor`，可本地确定性派生 | 只能请求复权结果，缺少因子版本 | **不能替代** |
| 全市场横截面/市场宽度 | 强：按交易日批量抓取，适合 breadth 与状态计算 | 历史接口实测最多 3 个 ticker、3 年 | **不能替代** |
| 财务表结构化 | 强：公告日、实际公告日、更新标志、报告类型 | 宽表候选值丰富，但时间、单位、版本不足 | **仅可交叉核验** |
| 公告发现 | `anns_d` 能力明确，但当前凭据无权限 | 实测能返回公告标题、发布时间、PDF URL | **当前凭据下 Kimi 更可用** |
| 公告/财报原文权威性 | 仍是聚合/索引，不是官方原文 authority | 返回过同花顺域名 PDF，不是官方 authority | **两者都不能替代官方源** |
| 非结构化语义阅读 | 不负责 | 强：可路由、搜索、归纳候选信息 | **Kimi 优势** |
| 确定性增量同步 | 强：普通 HTTP/SDK，可固定 method/params/schema | 弱：LLM 可能额外调用、解释错误或业务失败仍 exit 0 | **不能替代** |
| 回测/PIT 输入 | 可作为较好基础，但仍需本地版本与官方可用时间校准 | 缺来源、版本、因子和 `available_at` | **不能替代** |
| 业务运行时合规 | 可以封装为普通代码 adapter | 项目基线禁止业务运行时代码调用 Kimi/LLM | **禁止替代** |

## Tushare 的具体优越性

### 1. 确定性调用

Tushare 直接以 `api_name + params + fields` 调用。相同输入可以缓存、重放和做 contract test，不需要模型决定调用哪个接口。Kimi Datasource 则要求先动态读取描述，再由 Agent 选工具和参数；prompt 不是稳定的工具 allowlist。

### 2. 更适合批量与横截面

Tushare 日线接口可按交易日获取全市场，股票基础信息可一次覆盖全市场，官方文档给出每次行数和每分钟频次。它更适合：

- 日终增量同步；
- 全市场涨跌家数、成交额与宽度计算；
- 同业横截面对比；
- 可重复的策略研究与回测数据集。

Kimi 当前更适合少量 ticker 的人工查询，而非构建长历史面板。

### 3. 单位、更新时间和权限更透明

Tushare 官方接口文档明确指出 A 股日线 `vol` 是手、`amount` 是千元，并说明日线入库时段；复权因子、主数据、交易日历和财务表分别列出积分、频次或独立权限。Kimi 动态接口虽然给出部分参数限制，但落盘 CSV 未携带上游身份、更新规则、数据版本或权限 profile。

### 4. 复权数据可审计

项目可以保存未复权 OHLCV 和独立复权因子，由本地代码生成前/后复权视图。Tushare 官方说明 `pro_bar` 的前复权以请求 `end_date` 为锚；因此只保存一份前复权 CSV 无法长期复现，保存原始日线、因子、请求参数与抓取时间才符合本项目要求。

### 5. 财务时间和修订字段更接近 PIT 需要

`ann_date`、`f_ann_date`、`update_flag` 和披露日索引比 Kimi 本次空 `time` 字段更适合作为财务可用时间治理的起点。它仍不是完整 PIT：日期不是精确 `available_at`，Tushare 也没有对完整历史修订快照作出保证。

## Tushare 不能被高估的地方

1. **不是官方披露 authority**：关键财务事实仍须回链 CNINFO、交易所或公司 IR。
2. **不天然满足 PIT**：没有完整的历史可见版本、统一 `available_at` 时间戳和不可变 revision snapshot。
3. **权限碎片化**：常规接口依赖积分；公告、分钟、港美股等可能需要独立权限。本轮 `anns_d` 已实际返回 403。
4. **软件许可证不等于数据许可**：Python SDK 是 BSD，但数据服务协议限定个人、不可转让、非商业、可撤销和有期限使用；多人或商业化需要重新授权。
5. **当前兼容网关风险高于官方接入**：网关域名、运营者、授权链和 SLA 未核实；SDK 通过私有属性 `_DataApi__http_url` 改写 endpoint，也不是稳定公共接口。
6. **MCP schema 仍需 contract test**：本轮已观察到 `daily` 工具声明 `symbol`、实际接受 `ts_code` 的漂移，不能仅凭 tools/list 自动生成生产调用。

## 能否由 Kimi 替代：精确回答

### 可以替代的部分

- 用户临时问一只股票的近期价格或一个财务候选值；
- Tushare 某个接口未开权限时，做公告发现或二级交叉核验；
- 需要自然语言理解后跨股票、宏观、企业、学术或法律数据源路由；
- 阅读公告标题、原文或非结构化材料并组织待验证线索。

替代后的数据必须标成 `unknown_secondary / provenance_incomplete / pit_eligible=false`，不能直接进入关键官方 Evidence。

### 不能替代的部分

- 定时 `sync/daily` 业务运行时；
- 全市场日线、市场宽度和长历史面板；
- 独立复权因子、公司行动与可复现复权视图；
- 幂等增量游标、精确缓存键、重试/限流和可回放 raw；
- 回测、估值和计划评估所需的确定性输入；
- 官方财务事实或正式公告证据。

最硬的限制不是“数据量”，而是仓库长期基线明确禁止业务运行时代码调用 Kimi 等 LLM API。即使 Kimi 数据数值正确，也不能把它放进正式 runtime Provider chain。

## 项目落地建议

### Provider 决策

保留现有结论，但根据本次实测提高证据强度：

```text
TushareProvider = adapt, optional production
KimiDatasourceBridge = adapt, control-plane only
OfficialDisclosureProvider = adopt as authority
FixtureProvider = adopt for offline tests
```

Tushare 不应成为第一条切片的强制凭据：无 Token 或权限不足时，切片仍应能通过合法 fixture 与无凭据 fallback 完成。它应是可插拔的 production adapter。

### 最小 adapter 表面

```text
resolve_security()
sync_trade_calendar()
sync_daily_unadjusted()
sync_adjustment_factors()
sync_financial_index()
sync_disclosure_dates()
```

公告原文仍交给官方披露 adapter。`anns_d` 只能作为可选发现接口。

### Raw 与 normalized 要求

每次请求至少保存：

- provider 与实际 gateway host；
- adapter、SDK 与 schema 版本；
- endpoint、脱敏后的 canonical params、fields；
- `retrieved_at`、HTTP/业务状态和 entitlement profile；
- 原始响应 bytes/hash；
- `trade_date/end_date/ann_date/f_ann_date/update_flag` 等原始时间/版本字段；
- normalized 单位与转换规则，例如 `vol_hand * 100 = volume_share`；
- `published_at/available_at` 的来源、精度和保守门禁；
- 未复权 raw、因子 raw 和派生复权视图的输入 snapshot。

### 必需 contract tests

1. `daily` 字段和单位固定，成交量从手转股不丢小数尾数。
2. OHLC 合法性、交易日历一致性、停牌/零成交语义。
3. `balancesheet` 的 `update_flag` 与重复 natural key 版本处理。
4. 未复权日线 + 因子派生的前/后复权结果可复现。
5. 403/无权限、空数据、限流和 transport failure 分开建模。
6. 同一请求第二次执行命中缓存，不重复 raw/normalized 入库。
7. 网关或 SDK schema 变化时 fail closed，而不是静默错列。
8. 官方披露缺失时，第三方值不能恢复正式估值/评级权限。

## 一手资料与本地证据

### Tushare 官方资料

- [A 股日线：字段、单位、更新时间、频次](https://tushare.pro/document/2?doc_id=27)
- [复权因子：更新时间、积分和字段](https://tushare.pro/document/2?doc_id=28)
- [A 股复权行情：`end_date` 锚点与计算语义](https://tushare.pro/document/2?doc_id=146)
- [股票基础信息：全市场行数、字段与频次](https://tushare.pro/document/2?doc_id=25)
- [交易日历](https://tushare.pro/document/2?doc_id=26)
- [资产负债表：公告日、实际公告日与报告类型](https://tushare.pro/document/2?doc_id=36)
- [上市公司全量公告：独立权限](https://tushare.pro/document/2?doc_id=176)
- [积分与频次权限对应表](https://tushare.pro/document/1?doc_id=290)
- [Tushare 数据服务协议](https://tushare.pro/document/1?doc_id=405)

### Kimi 官方与本地证据

- [Kimi Code Plugins / Kimi Datasource](https://moonshotai.github.io/kimi-code/en/customization/plugins.html#kimi-datasource)
- [`Kimi Datasource 作为数据 Provider 的可行性研究`](../kimi-datasources-provider.md)
- [`A 股数据 Provider、PIT 与增量缓存研究`](../data-providers-pit-cache.md)
- 本轮对照输入：`002897_price.csv`、`002897_bs_20260331.csv`、`002897_announcements.csv`

## 最终判断

对本项目，Tushare 的核心价值不是“它一定比 Kimi 的数字更准”，而是它提供了更适合普通代码消费的结构化、批量、单位明确、可缓存和可测试的接口。Kimi 的核心价值则是降低人工查找与非结构化理解成本。

所以正确答案不是二选一：

- **正式 runtime：官方披露 + Tushare/其他确定性 adapter；**
- **控制面补充：Kimi Datasource；**
- **关键财务 Evidence：最终仍回到官方原文。**
