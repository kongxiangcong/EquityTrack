# 数据源映射 Lookup Table（数据类型 → Kimi 路由数据源）

本表是项目取数的唯一查询入口：更新数据或获取数据时先查本表确定去哪个数据源、用哪个结构化 API。决策记录与切换进度见 `.scratch/kimi-datasource-unification/`。

## 硬规则

- 业务运行时（平台持久化流程）取数**只经 Kimi agent-gw 路由**：`agent_gw` SDK `call_data_source_tool`；凭证在网关侧（`KIMI_API_KEY` 或 `~/.kimi/agent-gw.json`），平台不持有、不打印、不转发任何数据源凭证。
- **禁止**任何直连供应商 endpoint、Python 直连/脚本旁路、Web 搜索兜底进入业务运行时；自然语言（question 入参）工具不进业务运行时——每次调用必须确定性、可缓存、可重放。
- 平台取数唯一入口是 CLI `sync`（job 文件固定数据源策略）；provider 层内部按下表路由 Wind/iFind。会话内回答用户即席问题时可使用 wind / ifind 插件 skill 的 CLI，但结果不得写入平台数据根。
- 数据源身份如实标注为 `structured_aggregator`（Wind/iFinD），不是官方披露权威。官方披露（CNINFO / HKEXnews / SEC EDGAR）走独立路径，不经过聚合源。
- 任一 API 不可用或返回为空：按降级规则产出"证据不足"，不得伪造数据。

## Lookup Table

| 数据类型（数据集） | 用途 | 数据源 | 结构化 API（SDK 名） | 参数要点 | 约束与备注 |
|---|---|---|---|---|---|
| 交易日历 `trade_cal` | 冻结最新完整交易日 | **Wind** | `wind_get_index_price` | ticker=000001.SH，start/end_date=YYYY-MM-DD | 以指数交易日推导 is_open=true 行；calendar_version=`wind-index-sessions@1` |
| 证券宇宙 `market_universe` | 快照成员资格、listed_from | **Wind** | `wind_get_stock_info`（首选）/ `wind_get_price` 长区间首行（兜底） | ticker=<code>.<SZ\|SH\|BJ> | market_scope_id 固定 `CN_A_SHARE`；上市日期字段名待 fields/wind_search_fields 确认，兜底取最早日线交易日 |
| 日线行情 `daily` | 市值/收益估算 | **Wind** | `wind_get_price` | price_adj=N（不复权），frequency=D | 返回含 amt（成交额，元）——覆盖度门禁必需；iFind 日线无成交额，不能用于本数据集 |
| 财务报表 `income`/`balancesheet`/`cashflow` | 财务建模输入 | **iFind** | `ifind_get_financial_statements` | statement=income_statement/balance_sheet/cash_flow，financial_parameter=季末 yyyyMMdd | 无公告时间戳 → availability_basis=`retrieved_only`；字段映射已实测 |
| 一致预期 `forecast_actual` | 分析师一致预期 | **iFind** | `ifind_get_forecast` | ticker 单只 | 聚合一致预期，comparability_status=aggregator_consensus_unverified |
| 实时/快照行情（辅助展示） | 会话内即席回答 | Wind / iFind | `wind_get_stock_price_indicators` / `ifind_get_stock_realtime_price` | 单标的 | 仅辅助，不作业务运行时门禁输入 |
| 公告/新闻（辅助发现） | 线索与交叉核对 | Wind / iFind | `wind_get_company_announcements` / `ifind_get_stock_announcement` | — | 辅助来源，不作官方披露权威 |
| 官方披露 | 关键财务数据权威 | CNINFO / 交易所 / SEC EDGAR | 独立披露路径 | — | 不经过 Wind/iFind；缺失则不出估值结论 |

## 调用约束（两库通用）

- 单标的调用；多标的拆多次后合并（iFind `ifind_get_price` 允许逗号最多 3 只为例外）。
- 日期格式以各 API 描述为准（SDK 层 Wind 为 YYYY-MM-DD；node CLI 层为 yyyyMMdd）。
- Wind API 的 `file_path` 入参：正斜杠绝对路径（反斜杠+t 会被上游转义为 Tab）；平台只消费响应 `files[].content`，不读服务器落盘文件。
- 凭证只在网关侧解析；客户端不配置 `WIND_API_KEY` / `IFIND` 凭据。

## 状态

本表为目标路由（2026-08-02 经实网验证定案）。运行时切换由 `.scratch/kimi-datasource-unification/` tickets 02–04 落地；落地前运行时仍存在 Tushare 兼容网关层（切换时同单元删除，不留兼容代码）。
