# K 线与版本化标注原型验证记录

状态：`PROTOTYPE ONLY`，HITL 已裁决；不是正式验收或平台实现。

## HITL 裁决

2026-07-12，用户明确排除 A 作为默认视图，并锁定：

1. B“画布优先驾驶舱”是默认 K 线工作台；
2. C 的不可变版本账本成为 B 的可收起版本侧栏；
3. 同一个 B 视图也承担全屏模式，避免维护两套图表与标注状态；
4. 数据来源、数据状态等过程信息不持续占据主视图，只在用户主动打开审计详情，或异常实际阻断/降级当前能力时显示。

## 验证环境

- Windows / PowerShell
- Node.js `25.8.1`，npm `11.11.0`
- `klinecharts@10.0.0`，lockfile integrity：`sha512-njopc5Wwff83l9R750Yrj+EcmQUe7JUwN4xgmmwhUPX30jd7ZLabBQT5s2+yTaAk98MMqglCE6vqrSnek/ppbg==`
- Codex in-app Chromium browser
- 本地静态服务：`127.0.0.1:4173`

## 冻结输入

- `Security`：意华股份 `002897.SZ`
- 用户请求日：`2026-07-11`
- 交易日历解析：回退至 `2026-07-10`
- 真实未复权日线：`2026-06-01` 至 `2026-07-10`，29 bars
- 来源：预配置 `tx.xiaodefa.top` Tushare-compatible gateway；明确不是官方披露 authority
- 浏览器运行时资源全部为相对本地路径：KLineChart bundle、`app.js`、`styles.css`、`fixture.json`；无 CDN 或图片资源

## 已通过的手工 E2E

| 用例 | 结果 |
|---|---|
| K 线 + VOL 加载 | 29 bars 正常显示，KLineChart 10.0.0 无浏览器 warning/error |
| 创建趋势线 | 实际交互需要起点、终点、最终确认；生成 `cav_proto_002897_001` |
| 序列化边界 | 只保存 UTC timestamp、decimal price、interval、adjustment mode、snapshot refs、白名单 style、domain links；不保存 pixel/dataIndex/overlay object |
| 页面刷新恢复 | v1 的两个锚点与 snapshot 引用完全一致 |
| 修改语义 | 第二锚点 `+0.50` 追加 v2，v1 保留且 `supersedes` 链正确 |
| 删除语义 | 删除追加 v3 `status=deleted` tombstone，不移除旧版本 |
| 恢复语义 | 从 tombstone 追加 v4 active，不复写 v3 |
| 服务重启恢复 | 停止并重启本地 HTTP 服务后，v1-v4 账本、v4 坐标与图表 overlay 恢复 |
| 跨周期门禁 | 从 1d 请求 1w 返回 `unresolved_requires_confirmation`；原坐标保持 1d/none，不吸附 |
| 复权门禁 | forward/backward 只形成 proposed view；没有派生 DataSnapshot 时不改坐标 |
| missing 状态 | `DATA_SNAPSHOT_MISSING`，0 canvas，不渲染假行情；历史版本仍可审计 |
| stale 状态 | 明确显示“当日评估阻断”，历史图表仍可回看 |
| 三变体切换 | `?variant=A/B/C` 可分享、刷新稳定，四个标注版本在三种布局间一致 |

## 设计发现

1. KLineChart 10 的内置 `segment` 确实减少了绘图胶水，但“最终确认”是额外一步；正式 UI 需要明确提示或用 adapter 包装，否则用户容易以为第二个锚点已经保存。
2. `onDrawEnd` 与 `onPressedMoveEnd` 足以投影为领域命令，但图库 `Overlay` 混有运行时 identity、callbacks、points 与样式，不能直接序列化。
3. 版本账本与图表投影分离后，刷新/重启恢复、tombstone 和跨视图 fail-closed 都能表达；`ChartAnnotation` 应保持稳定 identity，版本才是不可变记录。
4. 浏览器 `localStorage` 只证明 adapter/DTO round-trip，不证明 SQLite schema、事务、迁移或并发语义；正式实现仍须重写 persistence adapter 和自动化 E2E。
5. 本原型尚未证明真实公司行动导致的 factor 修订、无交易日 anchor、日到周/月 bucket 映射或大数据量性能；这些必须进入 Spec 的强制失败用例，不得由本原型的成功推断为已解决。

## 方案取舍记录

- A — 不作为正式主视图；它持续显示过程/provenance 信息，影响图表焦点和美化。
- B — 采用为默认和全屏模式；保留大画布、集中工具栏和最短绘图路径。
- C — 不作为独立默认页面；吸收其版本链、tombstone 和恢复历史为 B 的可收起侧栏。
