# PROTOTYPE ONLY — K 线与版本化标注 seam

> 三种意华股份 K 线工作台变体，使用同一份版本化 OHLCV 与 `ChartAnnotation` DTO，通过 `?variant=A|B|C` 切换。

这是一份可丢弃的 Wayfinder HITL 原型，不是平台正式 UI、数据库或生产 Provider。它只用于确认高风险交互与序列化合同：数据截至/复权可见性、画线、版本化修改、tombstone 删除、刷新/服务重启恢复，以及跨周期/复权无法精确映射时 fail closed。

## HITL 裁决（2026-07-12）

用户选择 **B“画布优先驾驶舱”作为默认视图，并让同一 B 视图同时承担全屏模式；吸收 C 的不可变版本账本作为可收起版本侧栏**。A“证据优先控制台”不进入正式主视图，因为持续展示数据来源、数据状态等过程信息会削弱看图焦点与视觉质量。

正式实现只继承这一信息层级和下方的领域/序列化决策，不直接复制原型代码：

- 默认页以 K 线、成交量和标注操作为主，过程/provenance 数据收进按需“数据详情”或历史审计入口。
- 数据缺失、陈旧、复权/跨周期无法安全迁移等会改变当前能力的异常，仍须在图表附近以紧凑阻断/警告显示，不能被美化需求隐藏。
- C 的版本链在桌面端作为可收起侧栏，在窄屏作为 drawer；全屏 B 默认收起侧栏，仅在用户要求时打开。
- 默认 B 与全屏 B 使用同一 chart/annotation adapter 和状态，不建立第二套图表实现。

## 启动

```powershell
npm run prototype
```

打开 `http://127.0.0.1:4173/?variant=A`。底部原型切换器支持按钮和左右方向键。

浏览器 `localStorage` 键 `PROTOTYPE_WIPE_ME_chart_annotation_v1` 是唯一 scratch 持久化；页面的“清空原型状态”会删除它。原型不会写平台数据库，也不会联网获取数据。

## 已回答的原型问题

第一条纵向切片的 K 线页采用 B 的画布优先信息层级，C 版本账本按需展开；正常状态不把 `DataSnapshot`、来源和同步状态持续铺在主视图，只有异常与无法安全迁移的状态必须显式打断。

## 数据与依赖

- 证券：意华股份 `002897.SZ`，`Asia/Shanghai`，CNY。
- 行情：2026-06-01 至 2026-07-10 的真实未复权日线，由预配置的 Tushare-compatible gateway 于 2026-07-11 获取；该网关不是官方披露 authority，原型内只保存脱敏 provenance 和冻结值。
- 图库：`klinecharts@10.0.0`，精确版本由 `package-lock.json` 固定；浏览器运行时只加载本地 `node_modules`，不访问 CDN。
- 许可证：Apache-2.0；完整 `LICENSE`、`NOTICE` 与补充许可证随安装包位于 `node_modules/klinecharts/`。

## 预期验证

1. 三个变体共享同一状态；切换变体不改变领域数据。
2. 按 KLineChart 10 的实际交互依次点击起点、终点和最终确认来创建趋势线；锚点只保存 UTC timestamp 与十进制价格字符串，不保存 pixel/dataIndex/图库对象。
3. 拖动/修改通过“保存为新版本”追加版本；删除产生 tombstone，历史仍可见。
4. 刷新页面或重启本地服务后，激活版本及锚点不变。
5. 切换到周线或前复权只产生 `unresolved / requires_confirmation`，不静默吸附坐标。
