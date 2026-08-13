# 02 task: Kimi 层 Wind 数据源路由与 daily/trade_cal/market_universe 处理器

Type: task
Status: resolved

## Answer

已落地（2026-08-03/06）：

1. 路由表 `_DATASET_DATASOURCE`：daily/trade_cal/market_universe→Wind，income/balancesheet/cashflow/forecast_actual→iFind；`_call_rows(dataset, api_name, params)` 按数据集选 `data_source_name`，CSV 解析与失败码 taxonomy 共用。
2. `daily` 改走 `wind_get_price`（price_adj=N, frequency=D），行含 open/high/low/close/volume(share)/amount(amt，元)/amount_unit=yuan/currency，availability_basis 沿用 conservative_end_of_session_date。
3. 新增 `_trade_cal_rows`：`wind_get_index_price`(000001.SH) → {market, session_date, is_open:true, calendar_version:"wind-index-sessions@1", published_at=session_date, available_at=当日开盘(Asia/Shanghai), availability_basis=publisher_timestamp}。KIMI_AGENTGW_DATASETS 已加 trade_cal。
4. 新增 `_market_universe_rows`：首选 `wind_get_stock_info`+fields=ipo_date（实网验证字段名为 `ipo_date`，返回列头为中文「首发上市日期」，两者都解析）；取不到则兜底 `wind_get_price` 1990-12-19 起长区间首行。source_ref 分别为 `wind:wind_get_stock_info:ipo_date:<code>` / `wind:wind_get_price:first_session:<code>`；market_scope_id 固定 CN_A_SHARE。KIMI_AGENTGW_DATASETS 已加 market_universe。
5. capabilities 同步：TRADING_CALENDAR=SUPPORTED(WIND_INDEX_SESSIONS)，DAILY_UNADJUSTED=SUPPORTED(WIND_GET_PRICE_UNADJUSTED)；provider_config 的 canonical_kimi_agentgw_source_policy 加入 trade_cal/market_universe REQUIRED/BLOCK 路由。
6. Fog 清除：① ipo_date 字段名经 `wind_search_fields`+`wind_get_stock_info` 实网确认（002407.SZ→2010-05-18）；② market_session 完整性逻辑只查 is_open=1 行（repository.py:628），"只有开市日"日历行被接受——repository 级测试实测通过。③ `file_path` 统一走 `_agentgw_file_path`（tempfile 正斜杠绝对路径）。
7. 顺带的强制清理（0025 前置迁移遗留的同单元修复）：版本断言 24→25（test_migration_0015_0017 / test_open_draft_upsert_receipt_migration / test_trade_plan_evidence_payload_migration / test_research_evaluation_migration）、application_task_fixture 两处 normalized_version INSERT 补 source_policy_identity 列、test_runtime_skeleton 的 owning-SQL 名单登记 test_kimi_agentgw_provider.py、回归账本子进程改 sys.executable、vendor-token 检查对 agentgw seam 符号开豁免、`_KIMI_*`→`_AGENTGW_*` 常量重命名。

验证：`PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/platform -q`（跳过 6 个缺 pypdf 的文件：test_research_bundle_decision_projection / test_research_decision_pdf / test_research_bundle_integrity / test_research_raw_valuation_audit_boundary / test_valuation_workbook_adapter / test_valuation_workbook_decision_reconciliation）分组全绿；test_kimi_agentgw_provider.py 28 passed（含 fixture 级三新处理器行形态/路由/失败码 + repository 级覆盖度门禁与快照成员测试）。

## Question / Scope

在 `src/trading_platform/data/kimi_agentgw.py` 内把单数据源（ifind）扩展为按数据集分类的双数据源路由，并新增三个数据集处理器。传输统一为 `agent_gw` SDK `call_data_source_tool`；SDK 实测事实（2026-08-02）：

- Wind 数据源 API 名为 `wind_` 前缀：`wind_get_price`（个股日线，ticker/start_date/end_date/price_adj=N，返回 trade_date,wind_code,open,high,low,close,volume,amt）、`wind_get_index_price`（指数日线，交易日历推导）、`wind_get_stock_info`（证券参考数据）。
- Wind `file_path` 入参必须正斜杠绝对路径（反斜杠+t 会被上游转义成 Tab）；平台只消费响应 `files[].content`。

1. 数据源路由：模块级常量路由表，`daily`/`trade_cal`/`market_universe` → Wind；`income`/`balancesheet`/`cashflow`/`forecast_actual` → iFind（既有）。数据集分类即 spec.md 映射。
2. `_call_rows` 泛化：按数据源选择 data_source_name（"wind"/"ifind"），CSV 解析逻辑共用；失败码沿用既有 taxonomy。
3. `_daily_rows` 改走 Wind `wind_get_price`（price_adj=N）：行带 open/high/low/close/volume(share)/amount(元)/amount_unit/currency，availability_basis 沿用 conservative_end_of_session_date。
4. 新增 `_trade_cal_rows`：Wind `wind_get_index_price`(000001.SH) 交易日 → {market（按查询市场）, session_date, is_open:true, calendar_version:"wind-index-sessions@1", published_at=session_date(date), available_at=当日开盘, availability_basis="publisher_timestamp"}。KIMI_AGENTGW_DATASETS 加入 trade_cal。验证 market_session 完整性逻辑接受"只有开市日"的日历行（Fog 项）。
5. 新增 `_market_universe_rows`：先用 `wind_get_stock_info` + fields/wind_search_fields 确认上市日期字段；取不到则兜底 `wind_get_price` 长区间首行交易日作 listed_from。行 {market_scope_id:"CN_A_SHARE", security_id, listed_from, source_ref:"wind:<api>:<field或first_session>:<code>", availability_basis:"publisher_timestamp"}。KIMI_AGENTGW_DATASETS 加入 market_universe。
6. capabilities 声明同步更新（TRADING_CALENDAR: SUPPORTED via WIND_INDEX_SESSIONS 等），SourceAuthority 保持 STRUCTURED_AGGREGATOR，provenance 如实标注 Wind/iFinD 身份。
7. 单测：fixture 级覆盖三个新处理器的行形态、路由表与失败码；repository 级验证 daily 含 amount 可通过覆盖度门禁、trade_cal/market_universe 行被接受并产生合格快照成员。

Boundaries: 不改 normalizer/repository；不引入 NL 工具；不动 provider_config 的 Tushare/layered 删除（ticket 03）。
