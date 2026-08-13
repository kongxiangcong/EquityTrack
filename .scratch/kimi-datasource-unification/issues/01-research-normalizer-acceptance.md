# 01 research: normalizer/repository 对 Kimi 层新数据集行的接受性

Type: research
Status: resolved

## Question

Kimi agent-gw 层若以 `{"rows": [...]}` 负载产出 `trade_cal`、`market_universe`、含 amount 的 `daily` 行，normalizer 与 repository 的现有校验是否接受？需要哪些改动点？

## Answer

接受，无需改 normalizer。已读码确认（normalizer.py / repository.py / domain/data.py）：

1. `normalize()` 对 `{"rows": [...]}` 负载直接进入共享行校验，Tushare 的 `data.fields/items` 映射只在 rows 缺失时触发。Kimi 层新数据集只需产出合规行。
2. `trade_cal` 行必填 {market, session_date, is_open, calendar_version}，natural_key=`market:session_date:calendar_version`。以 Wind 指数交易日推导时发行 `calendar_version="wind-index-sessions@1"`、is_open=true 的行即可；0025 后版本身份按策略作用域，不会与历史 Tushare 日历行冲突。
3. `market_universe` 行必填 {market_scope_id, security_id, listed_from, source_ref}；market_scope_id 必须 `CN_A_SHARE`（0025 已纠正 kong 根旧行；复核查询硬过滤此值）。
4. `daily` 行 normalizer 必填集不含 amount，但 repository 快照覆盖度门禁要求 amount_decimal 非空——所以 daily 必须路由 Wind（有 amt），行内带 `amount`/`amount_unit`；volume_unit=share（Wind volume 为股，与 iFind 一致，实测 002407 volume 158513601≈158513600）。
5. 快照成员单策略不变量：新快照全部成员来自 kimi-agentgw 单策略即可满足，无需跨策略采用逻辑。
6. iFind 财报表无公告时间戳 → `availability_basis="retrieved_only"`（在 ALLOWED_AVAILABILITY_BASES 内，既有实现已用）。

改动点全部收敛在 `kimi_agentgw.py`（新数据集处理器 + Wind 数据源路由）与 `provider_config.py`（策略声明），normalizer/repository 不动。
