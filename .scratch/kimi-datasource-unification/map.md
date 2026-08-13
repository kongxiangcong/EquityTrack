# kimi-datasource-unification map

## Notes

- Owner directive 2026-08-02: 数据更新统一走 Kimi 内置库（iFind/Wind），按数据类型分类选库，CLI 为唯一入口，skills 约束结构化返回，禁止迁移/兼容代码，清除旁路与过时代码。
- 既有实现 `src/trading_platform/data/kimi_agentgw.py` 已是该方向的第一层（iFind 结构化 API），但只覆盖 {daily, income, balancesheet, cashflow, forecast_actual}，且 daily 缺 amount。
- normalizer 对 `{"rows": [...]}` 负载按数据集做共享校验（trade_cal / market_universe / daily 必填键已确认），Kimi 层新数据集只需产出符合校验的行。
- 实网验证（2026-08-02）：Wind get_stock_kline 含 amt；Wind get_index_kline(000001.SH) 交易日序列正确；iFind get_stock_info 无上市日期字段。

## Decisions-so-far

- 数据分类映射定案：daily/trade_cal/market_universe→Wind，income/balancesheet/cashflow/forecast_actual→iFind（见 issues/01 Answer 与 spec.md）。
- trade_cal 以 Wind 指数交易日推导（`wind_get_index_price` 000001.SH）。
- SDK 直连已验证（2026-08-02）：`agent_gw` SDK 的 Wind 数据源 API 为 `wind_` 前缀；`wind_get_price`（price_adj=N）直连返回 OHLCV+amt；`wind_get_index_price`/`wind_get_stock_info` 存在。Fog 项"SDK data_source_name 与入参映射"已清除。
- Wind `file_path` 入参用正斜杠绝对路径（反斜杠+t 会被上游转义为 Tab）。
- 02 resolved：Wind/iFind 数据集路由 + trade_cal/market_universe/daily(amount) 落地；ipo_date 字段实网确认；market_session 只查 is_open=1 故纯开市日日历可行（见 issues/02 Answer）。

## Fog

- ~~`wind_get_stock_info` 默认字段组未含上市日期~~ → 已清除：`wind_search_fields` 确认字段名 `ipo_date`（返回列头中文「首发上市日期」），兜底 wind_get_price 长区间首行（02 已实现）。
- ~~market_session 完整性逻辑对"只有开市日"日历行的接受度~~ → 已清除：repository 只查 is_open=1（repository.py:628），02 repository 级测试通过。

## Frontier

- 03（task，未认领，Blocked by 02 → 已解除）
