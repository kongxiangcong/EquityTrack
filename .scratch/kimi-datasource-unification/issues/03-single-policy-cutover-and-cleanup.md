# 03 task: 单一切换为 kimi-agentgw 策略并删除旁路/过时代码

Type: task
Status: claimed
Blocked by: 02

## Question / Scope

把数据获取收敛为唯一流程并同单元删除被取代的路径：

1. `provider_config.py`：删除 `TushareCompatibleProvider` 绑定、`_TUSHARE_*` 常量、`layered-auto` 策略与 layered bind 选择逻辑；sync job 模板与 `decode_sync_job` 只接受 kimi-agentgw 策略（数据集全集：trade_cal/market_universe/daily/income/balancesheet/cashflow/forecast_actual）。
2. `data/providers.py`：删除 `TushareCompatibleProvider`（FixtureProvider 保留，测试 seam）；credentials 移除 `TUSHARE_TOKEN` scope。
3. 文档同单元更新：AGENTS.md 数据规则（Tushare 主源条款 → Kimi iFind/Wind 分类条款）、README、skills/tasks/account-status.md、skills/references/platform-control-plane.md；`.scratch/trading-platform-first-vertical-slice-spec/research/kimi-experiments/tushare_usage.md` 与 `tushare-vs-kimi-datasource.md` 标记 superseded 并指向本 spec。
4. 测试：替换/删除 Tushare 与 layered 相关 fixture、用例、job 模板引用；不得 layered 新旧测试并存。
5. 全局 grep 确认无残留引用（tushare、layered-auto、8.136.22.187、TUSHARE_TOKEN），git status/diff 复核。

Boundaries: 不动 kong 数据根历史数据（不可变证据，来源身份保留）；不新增 schema 迁移。
