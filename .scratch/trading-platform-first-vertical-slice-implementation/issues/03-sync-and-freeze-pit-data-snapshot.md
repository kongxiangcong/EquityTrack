# 03 — 授权同步并冻结 PIT DataSnapshot

**What to build:** 让用户从观察项明确授权一次数据更新，将真实可追溯 fixture 经与生产相同的 Provider、raw、normalization、质量、cursor 和 point-in-time 路径冻结为不可变 DataSnapshot。界面和查询应解释请求日、有效交易日、新增或复用内容、陈旧度和限制。

**Blocked by:** 02 — 持久化并恢复观察项.

**Status:** resolved

- [x] 启动、打开和 serve 默认零外连；只有用户明确执行“更新至今天”才允许配置范围内的在线同步。（AC-004）
- [x] 固定旅程同时保存请求日 2026-07-11、有效完整交易日 2026-07-10、Asia/Shanghai 语义和交易日历版本。（AC-005）
- [x] fixture Provider 与生产 Provider 实现同一 typed contract，fixture 强制禁止联网，且二者走同一 raw、normalizer、质量、PIT 和 cursor 路径。
- [x] 每次同步保存全部 Provider attempts、真实来源身份、脱敏参数、terms profile、cache disposition、raw hash、质量结果和 cursor 处置，fallback 不覆盖早先失败。（AC-006、AC-020）
- [x] raw object 不可变；normalized 修订追加版本；OHLCV 保留未复权 exact decimal，单位、币种、来源时间精度和四类时间明确。
- [x] `available_at` 是唯一 PIT admission gate；未来 sentinel、缺 availability basis、身份冲突、quarantine 和 blocking 数据不能进入快照。（AC-007、AC-019）
- [x] purpose-scoped DataSnapshot 固化 cutoff、策略版本、有序成员、membership hash、freshness 和质量；相同合法输入可复用，修订产生并列新版本。（AC-017、AC-021）
- [x] PIT market universe 保留上市、退市、ST 和成员来源的有效区间，后来上市证券不会提前出现，后来退市证券不会从历史消失。（AC-041）
- [x] breadth/liquidity 所需横截面能区分结构性排除与 Provider 缺失，并保存 expected、eligible、excluded、missing 计数；非结构性缺口 fail closed。（AC-042 数据门部分）
- [x] offline valid、stale、missing 分别返回准确能力、freshness 和下一步；空响应、rate limit、schema drift 或缺 object 不写零值、不删旧数据、不错误推进 cursor。（AC-018）
- [x] fixture member 逐项记录本地保存、确定性回放、仓库再分发和打包分发权；未授权 raw 不进入版本库或发布包。（AC-051 数据部分）

## Implementation Evidence

- `0002_provider_normalized_snapshot.sql` 增加 Provider attempt/cursor、append-only normalized/OHLCV、calendar、PIT universe、quality、purpose-scoped DataSnapshot 与逐 member fixture rights schema。
- `DataProvider` typed contract 包含 endpoint、Security/market/range/cursor、credential scope；`RawEnvelope` 包含真实 source URL/identity/authority、headers、时间精度、raw SHA-256、status 与 cursor。
- Fixture 与 `TushareCompatibleProvider` 经同一 `DataSyncService -> object store -> normalizer -> quality/PIT -> cursor -> snapshot` 路径；启动和未授权请求的 network spy 为零。
- 固定旅程保存 requested `2026-07-11`、effective `2026-07-10`、`Asia/Shanghai` 与 calendar version；未复权 OHLCV 以 exact decimal、显式单位/币种和 event/published/available/retrieved 四类时间持久化。
- `available_at` 是唯一准入门；future、缺 basis、schema/identity conflict、quarantine/blocking 均 fail closed。同级/较低 authority 冲突不推进 cursor。
- cursor before/after/disposition 逐 attempt 保留；相同 cursor 重放不重写 `advanced_at`。公共 `SyncDisposition` 解释 raw/normalized/snapshot 的 created/reused。
- PIT universe 保存 listing/delisting/ST/source intervals；synthetic later-listing/later-delisting sentinel 验证历史成员不被当前 master 回填，coverage 只计算 cutoff-legal admitted OHLCV/amount。
- offline valid/stale/missing 返回 coverage、stale days、freshness basis、last success 与 next step；empty/rate-limit/schema drift/rights failure 不写零值或推进 cursor。
- `tests/fixtures/platform_data/manifest.json` 对每个 fixture member 绑定 payload hash、来源请求/证据、availability policy、real/synthetic 分类及四项 rights；原始兼容网关响应未提交且 distribution 为 `external_blocked`。
- 真实网关资格检查：3 个 Provider attempts/raw objects、14 个 normalized versions；因采集晚于 cutoff，14 个成员全部 `PIT_FUTURE_EXCLUDED`，正确返回 `missing`，未伪造历史成功。
- 验证：`python -m pytest tests/platform/test_data_sync_pit.py -q` -> `11 passed`；`python -m pytest -q` -> `59 passed`；`python -m compileall -q src`；`git diff --check`。
- `code-review` 最终复审：Standards PASS；Spec PASS；全部有效发现均修复并重新验证。
