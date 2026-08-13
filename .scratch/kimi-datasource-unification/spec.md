# Kimi 数据源统一（iFind/Wind 分类获取）Spec

Status: active
Owner directive: 2026-08-02 会话指令（"数据更新使用 kimi 的 Wind 和 iFind 数据库获取，对数据类型分类选择 iFind 或 Wind；由 skills 约束结构化返回，通过 cli 接口更新本地数据库；不允许迁移或兼容代码，统一流程，清除旁路/过时代码"；补充确认：数据接口只经 Kimi 路由，不允许 Python 直连/CLI 旁路，映射 lookup table 落在项目 skills）。

**Canonical lookup table：`skills/references/data-source-map.md`**（数据类型 → 数据源/API 的唯一查询入口）。本 spec 保留决策历史与切换范围；日常取数查 skills 表。

## 目标

平台数据获取收敛为**唯一流程**：

```
skills 任务文档（结构化返回约束）
  → CLI `python -m trading_platform.cli sync --job-file <job>`
  → Kimi agent-gw 数据路由层（按数据集分类选择 Wind 或 iFind 结构化 API）
  → normalizer（共享 {"rows": [...]} 校验）
  → repository（版本化持久化 + 快照）
  → account-show / 人工组合复核
```

运行时只存在这一条获取路径：无 Tushare 网关、无 layered-auto 环境选择、无双读/回退/兼容分支。历史 Tushare 时代数据作为不可变证据保留其来源身份，不做运行时兼容。

## 系统需要的数据类型（盘点结论）

| 数据集 | 用途 | 关键约束 |
|---|---|---|
| `trade_cal` | 冻结最新完整交易日 | normalizer 需要 market/session_date/is_open/calendar_version |
| `market_universe` | 快照成员资格（CN_A_SHARE 成员 + listed_from） | normalizer 需要 market_scope_id/security_id/listed_from/source_ref；复核查询硬过滤 CN_A_SHARE |
| `daily` | 市值/收益估算 | OHLCV + **amount 必须非空**（repository 覆盖度门禁）；adjustment_mode=none |
| `income` / `balancesheet` / `cashflow` | 财务建模输入 | iFind 结构化 API 无公告时间戳 → availability_basis=retrieved_only |
| `forecast_actual` | 一致预期 | iFind 结构化 API |
| 官方披露（official filing） | 关键财务数据权威来源 | 独立路径（CNINFO/交易所/SEC），不属于聚合数据更新范围 |

NL（自然语言 question 入参）工具不进入业务运行时——确定性、可缓存、可重放要求（kimi_agentgw 模块既有硬规则，本次保留）。

## 数据类型 → 数据源分类（2026-08-02 实网验证）

传输统一为 `agent_gw` Python SDK `call_data_source_tool`；Wind 数据源的 SDK API 名为 `wind_` 前缀（已实测，`get_stock_kline` 这类 node CLI 名在 SDK 层不存在）。

| 数据集 | 数据源 | SDK 结构化 API | 验证结论 |
|---|---|---|---|
| `daily` | **Wind** | `wind_get_price`（price_adj=N） | SDK 直连实测 002407.SZ 2026-07-31：OHLCV+amt（元）齐全，与 iFind 价格一致；iFind `ifind_get_price` 无 amount，不满足覆盖度门禁 |
| `trade_cal` | **Wind** | `wind_get_index_price`（000001.SH） | node CLI 实测 2026-07-20~08-02：交易日序列正确（周末缺失）；以指数交易日推导 is_open=true 行，calendar_version=wind-index-sessions@1 |
| `market_universe` | **Wind** | `wind_get_stock_info`（上市日期字段）或 `wind_get_price` 长区间首行 | `wind_get_stock_info` 描述含 listing date（默认字段组未直接给出，需用 fields/wind_search_fields 确认字段名）；兜底：个股最早日线交易日作 listed_from，source_ref=wind:wind_get_price:first_session:<code> |
| `income`/`balancesheet`/`cashflow` | **iFind** | `ifind_get_financial_statements` | 字段映射已对 2025 年报实测（kimi_agentgw 既有实现） |
| `forecast_actual` | **iFind** | `ifind_get_forecast` | 既有实测实现 |

实现注意：Wind API 的 `file_path` 入参必须绝对路径且用正斜杠（反斜杠+t 会被上游转义成 Tab，已实测）。平台只消费响应 `files[].content`，不读服务器落盘文件。

## 删除清单（旁路/过时代码，随 ticket 03 同单元删除）

- `TushareCompatibleProvider` 及 `_TUSHARE_*` 常量、`TUSHARE_TOKEN` credential seam、`http://8.136.22.187:8010/` endpoint
- `layered-auto` 策略与 layer 选择逻辑（provider_config 的 layered bind）
- sync job 模板：`layered-auto` → `kimi-agentgw` 单一策略
- 文档同步：AGENTS.md 数据规则、README、skills 任务文档、`.scratch/trading-platform-first-vertical-slice-spec/research/kimi-experiments/` 两份 tushare 文档标记为历史研究
- 测试：Tushare/layered 相关 fixture 与用例替换为 kimi 层等价覆盖后删除

## 不兼容政策

- 不新增 schema 迁移（0025 已落地，是本次切换的前置修复，不属于兼容代码）。
- 同一自然键跨来源身份：0025 已使 normalized_version 身份按 source policy 作用域；新快照成员全部来自 kimi 层单策略即满足"快照成员单策略"不变量，无需运行时采用/双读逻辑。
- 工具/API 不可用 → 按降级规则产出 data_insufficient_memo，不得伪造数据。

## Tickets

- `issues/01-research-normalizer-acceptance.md`（research，已 resolved）
- `issues/02-wind-routing-and-new-datasets.md`（task）
- `issues/03-single-policy-cutover-and-cleanup.md`（task，Blocked by: 02）
- `issues/04-live-verification-and-purge.md`（task，Blocked by: 03）
