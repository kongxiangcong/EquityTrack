# K 线库、标注模型与许可证调研

## 结论

截至 **2026-07-11（Asia/Shanghai）**，第一条 Windows 本地优先纵向切片应把 **`klinecharts@10.0.0` 精确锁定后作为 `adapt` 候选进入受控原型**，而不是把任何图库直接作为领域模型或持久化格式。选择它的原因是：基础包内置 K 线、`VOL` 成交量指标、交互式 overlay、事件回调、时间/价格与像素互转，完成“画一条线并持久化”所需的 UI 胶水最少；npm `gitHead` 与固定 tag 源码 commit 一致，能建立可复现依赖基线。

这不是成熟的 `adopt`：10.0.0 在本调研日刚发布，是从 9.x 到 10.x 的破坏性升级，而且固定 tag 没有 `tests/` 目录或自动测试脚本。采用条件是用本仓库自己的契约测试、Windows 浏览器 E2E、刷新/重启持久化测试和离线打包测试补齐证据。`9.8.12` 仅保留为应急 fallback，不能称为严格的“已验证基线”：其 npm `gitHead` 与 v9.8.12 tag peeled commit 不同，且上游只有手工 HTML 样例、没有自动测试脚本。

`TradingView Lightweight Charts 5.2.0` 对本切片为 **`reference only`**：维护与测试证据最强，坐标和 primitive seam 清晰，但交互绘图工具只是示例，需要自行实现状态机、命中测试与编辑手柄。`Apache ECharts 6.1.0` 对本 K 线交互面为 **`reference only`**：通用可视化、candlestick、mark/graphic 与测试体系很强，但不是金融绘图工具，交互式趋势线编辑仍需自建；它可以在后续报告/分析图表票中重新评估。三者都不负责行情数据、跨周期聚合或前/后/不复权计算。

## 范围与证据口径

- 只检查三个基础开源包，不把 TradingView Widgets、Advanced Charts、Trading Platform 或 KLineChart Pro 混入结论。
- 版本以 npm registry 的固定版本元数据、官方 tag/release、固定 commit 源码互证；源码路径全部固定到 commit，避免 `main` 漂移。
- 本票只形成设计决策，不实现 UI。当前仓库没有 `package.json` 或前端工程，因此“新建本地 Web 壳、构建链和框架生命周期”是三个候选共有的前置成本。
- 第一切片的 canonical 行情是**未复权 OHLCV**；前复权/后复权是带 factor snapshot 与 data snapshot 版本的派生视图。图表库只渲染已物化的视图。

## 固定版本与维护状态

| 候选 | 固定版本与证据 | 固定源码 | 维护与发布风险 |
|---|---|---|---|
| TradingView Lightweight Charts | [`lightweight-charts@5.2.0`](https://registry.npmjs.org/lightweight-charts/5.2.0)，发布于 2026-04-24，npm `gitHead=868cae27…`；[官方 release](https://github.com/tradingview/lightweight-charts/releases/tag/v5.2.0) | [`868cae27bd1acafa0128d8d868ea740a59ae42ce`](https://github.com/tradingview/lightweight-charts/tree/868cae27bd1acafa0128d8d868ea740a59ae42ce) | 当前 5.2 稳定版，官方仓库有 unit/type/E2E/graphics 体系；低版本新鲜度风险。 |
| KLineChart | [`klinecharts@10.0.0`](https://registry.npmjs.org/klinecharts/10.0.0)，发布于 2026-07-10 16:46 UTC（上海时间 2026-07-11），npm `gitHead=0474602c…` | v10.0.0 peeled commit [`0474602cc0f8ff6db4629eaae255052e640a5c93`](https://github.com/klinecharts/KLineChart/tree/0474602cc0f8ff6db4629eaae255052e640a5c93) 与 npm 一致 | 发布日 major；[10.0 changelog](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/docs/en-US/guide/changelog.md) 明列数据加载、坐标轴、指标、overlay、格式与样式重组；固定 tag 无自动测试目录，风险高。 |
| KLineChart fallback | [`klinecharts@9.8.12`](https://registry.npmjs.org/klinecharts/9.8.12)，发布于 2024-12-22 | tag peeled commit [`03b2baf1…`](https://github.com/klinecharts/KLineChart/tree/03b2baf1e77af7ce82053a7a06038390d8c15921)，但 npm `gitHead=cf90ee01…`，两者不一致 | 年龄不等于严格验证；固定 tag 有 29 个 HTML/CSS/JS 手工样例但 package scripts 无 `test`，且未来必有 10.x 迁移成本。仅 fallback。 |
| Apache ECharts | [`echarts@6.1.0`](https://registry.npmjs.org/echarts/6.1.0)，发布于 2026-05-19，npm `gitHead=c5a48f5f…`；[官方 release](https://github.com/apache/echarts/releases/tag/6.1.0) | [`c5a48f5f97d23e5379720870b8444cd05b50ffb4`](https://github.com/apache/echarts/tree/c5a48f5f97d23e5379720870b8444cd05b50ffb4) | ASF 项目，6.1 固定源码包含 Jest unit、类型和大量 visual fixtures；低维护风险，但能力边界与本票不完全匹配。 |

## 产品边界、许可证与分发义务

| 候选 | 准确产品边界 | 许可证与 NOTICE | 本地分发动作 |
|---|---|---|---|
| Lightweight Charts 5.2.0 | TradingView 官方明确其为免费开源的 client-side library；不含市场数据，也不等于 Advanced Charts/Trading Platform。[官方产品比较](https://www.tradingview.com/charting-library-docs/latest/getting_started/product-comparison/)还明确其不内置指标。 | [Apache-2.0 LICENSE](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/LICENSE)；[NOTICE](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/NOTICE) 为 TradingView Lightweight Charts、Copyright 2025、TradingView URL。固定版 [README 许可段](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/README.md#license)要求在用户可见页面注明 TradingView 为产品创建者、放 NOTICE 文本并链接 TradingView；`attributionLogo` 可满足链接要求。还注明内含 0BSD tslib 部分。 | 包内保留 LICENSE/NOTICE；应用 About/Third-party notices 页面保留原文；图表页启用 attribution logo 或等价可见 NOTICE+链接；SBOM 记录直接依赖 `fancy-canvas@2.1.0`（MIT）。 |
| KLineChart 10.0.0 | 开源、零运行时依赖的 Canvas K 线基础库；不把 README 链接的 KLineChart Pro 或模拟交易环境算作基础包能力。 | [Apache-2.0 LICENSE](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/LICENSE)；[NOTICE](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/NOTICE) 同时列出 KLineChart Copyright 2019 lihu 与 TradingView Lightweight Charts Copyright 2019 + URL；仓库还分发 [`licenses/LICENSE-lightweight-charts`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/licenses/LICENSE-lightweight-charts)。不能只保留 KLineChart 自身名义。 | 离线安装包、应用 About/Third-party notices 与发布归档必须原样保留 LICENSE、NOTICE 和 `licenses/`；生成第三方许可证清单。 |
| Apache ECharts 6.1.0 | 通用数据可视化库；candlestick 只是一个 chart type，不含市场数据、金融周期/复权或交易绘图工作流。 | [Apache-2.0 LICENSE](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/LICENSE)；[NOTICE](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/NOTICE) 为 Apache ECharts Copyright 2017-2026 ASF；仓库还有 [`licenses/LICENSE-d3`](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/licenses/LICENSE-d3)。npm 直接依赖 `zrender@6.1.0`（BSD-3-Clause）与 `tslib@2.3.0`（0BSD）。 | 保留 LICENSE/NOTICE/补充 licenses；SBOM/Third-party notices 同时覆盖 ECharts、zrender、tslib。 |

以上是工程合规核验，不替代正式法律意见。

## 核心源码、测试与能力

| 维度 | Lightweight Charts 5.2.0 | KLineChart 10.0.0 | Apache ECharts 6.1.0 |
|---|---|---|---|
| K 线/成交量 | [`CandlestickSeries`](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/src/api/candlestick-series-api.ts)；成交量用独立 `HistogramSeries`/pane 组合，不是自动金融布局。 | [`KLineData`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/common/Data.ts) 原生含 timestamp/OHLC/volume/turnover；内置 [`VOL`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/extension/indicator/volume.ts) 指标。 | [`CandlestickSeries`](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/src/chart/candlestick/CandlestickSeries.ts) 加 Bar series 和多 grid 组合。 |
| 绘图/标记 | Series markers 支持 time、可选 exact price；任意趋势线/矩形需实现 [`ISeriesPrimitive`](https://tradingview.github.io/lightweight-charts/docs/api/interfaces/ISeriesPrimitiveBase)。官方仅提供 [`trend-line`](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/plugin-examples/src/plugins/trend-line/trend-line.ts)、[`rectangle-drawing-tool`](https://github.com/tradingview/lightweight-charts/tree/868cae27bd1acafa0128d8d868ea740a59ae42ce/plugin-examples/src/plugins/rectangle-drawing-tool) 等示例，不是稳定内置绘图 UI。 | [`createOverlay/getOverlays/overrideOverlay/removeOverlay`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/Chart.ts)，内置 straight/segment/ray/horizontal/vertical/price/channel/fibonacci/tag/annotation/brush 等 overlay；最接近本切片。 | series 内建 [`markPoint/markLine/markArea`](https://github.com/apache/echarts/tree/c5a48f5f97d23e5379720870b8444cd05b50ffb4/src/component/marker)，另有 [`graphic`](https://github.com/apache/echarts/tree/c5a48f5f97d23e5379720870b8444cd05b50ffb4/src/component/graphic) 与 brush；没有现成的金融趋势线编辑器。 |
| 事件 | [`subscribeClick`/`subscribeCrosshairMove`](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/src/api/ichart-api.ts)，primitive 提供 hit test seam。绘制开始/移动/结束状态机由应用实现。 | [`ActionType`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/common/Action.ts) 和 `subscribeAction`；[`Overlay`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/component/Overlay.ts) 有 draw、move、select、remove 等回调，适合在完成/移动/删除时投影领域命令。 | `ECharts` 实例事件 + zrender 事件，需应用自己组合 graphic drag 与数据坐标回写；[`core/echarts.ts`](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/src/core/echarts.ts) 是核心实例实现。 |
| 时间/价格坐标 | [`ITimeScaleApi.timeToCoordinate/coordinateToTime`](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/src/api/itime-scale-api.ts) 与 [`ISeriesApi.priceToCoordinate/coordinateToPrice`](https://github.com/tradingview/lightweight-charts/blob/868cae27bd1acafa0128d8d868ea740a59ae42ce/src/api/iseries-api.ts) 明确分离。 | [`Point={dataIndex,timestamp,value}`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/common/Point.ts)，`convertToPixel/convertFromPixel` 支持 pane/xAxis/yAxis filter。领域层只取 timestamp+value，不保存 dataIndex/pixel。 | [`convertToPixel/convertFromPixel/containPixel`](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/src/core/echarts.ts) 支持 Cartesian 数据坐标与像素转换。 |
| 标注序列化 | **无内置领域序列化**。markers 是可投影的 plain data，但 primitive 是带 renderer/lifecycle/hitTest 的运行时对象。 | **无内置持久化协议**。`getOverlays()` 返回的 `Overlay` 同时含 points/styles/extendData 与大量函数回调，不能直接 JSON；应用必须白名单投影。 | `getOption()` 是图表运行时 option 快照，不是标注审计协议；option/graphic/custom series 可包含 formatter、renderItem、事件函数，也不能直接作为领域 JSON。 |
| 核心测试证据 | 固定版 [`tests/unittests`](https://github.com/tradingview/lightweight-charts/tree/868cae27bd1acafa0128d8d868ea740a59ae42ce/tests/unittests)、[`tests/type-checks`](https://github.com/tradingview/lightweight-charts/tree/868cae27bd1acafa0128d8d868ea740a59ae42ce/tests/type-checks)、[`tests/e2e`](https://github.com/tradingview/lightweight-charts/tree/868cae27bd1acafa0128d8d868ea740a59ae42ce/tests/e2e)；`package.json` 的 `verify` 串联 build/lint/unit/type/size 门禁，E2E graphics/interactions/memleaks 另有独立脚本。三者最强。 | 固定 v10 tag 的 [`package.json`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/package.json) 只有 lint/type-check/build，没有 `test`，仓库也无 `tests/`。这是采用硬风险。 | 固定版 [`test/ut`](https://github.com/apache/echarts/tree/c5a48f5f97d23e5379720870b8444cd05b50ffb4/test/ut)、[`test/types`](https://github.com/apache/echarts/tree/c5a48f5f97d23e5379720870b8444cd05b50ffb4/test/types) 与大量 visual fixtures；[`package.json`](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/package.json) 提供 Jest/visual/type/lint/build 脚本。 |

## 跨周期、复权与时区职责

三套库都只消费调用方交付的数据，不能作为复权或 point-in-time 数据权威：

1. `ohlcv` canonical 永远存未复权值和公司行动事实；前复权/后复权由确定性数据层用固定 `factor_snapshot_id` 生成不可变派生 `data_snapshot_id`。
2. 日/周/月/分钟 bar 的交易日历、区间边界、时区、停牌与聚合由数据层处理。KLineChart 10 的 [`Period`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/common/Period.ts) 与 [`DataLoader`](https://github.com/klinecharts/KLineChart/blob/0474602cc0f8ff6db4629eaae255052e640a5c93/src/common/DataLoader.ts) 只是请求/回调契约，不执行可信重采样或复权。
3. 图表 adapter 每次接收完整的 `{security, interval, adjustment_mode, data_snapshot_id, factor_snapshot_id}` 视图；不得让图库在未知数据集上自动“修正”。Lightweight Charts 还明确[不原生处理时区](https://tradingview.github.io/lightweight-charts/docs/time-zones)，进一步说明时间语义应在数据层锁定。
4. 标注锚点保存市场 timestamp + 显示视图中的 price，并同时保存 interval、adjustment mode 与快照引用；不保存 pixel 或数组 index。
5. 跨周期或复权切换只允许：精确复现、通过同一固定 factor snapshot 做显式转换，或返回 `unresolved/requires_confirmation`。**禁止因最近 bar、dataIndex 或像素接近而静默重定位。** 具体公司行动、无交易日、周/月 bucket 与 factor 修订反例留给后续原型票。

## 库无关、可版本化的最小标注 DTO

```json
{
  "schema_version": 1,
  "annotation_id": "stable-logical-uuid",
  "annotation_version_id": "immutable-version-uuid",
  "version": 1,
  "supersedes_version_id": null,
  "status": "active",
  "security_id": "stable-security-id",
  "kind": "trend_line",
  "interval": "1d",
  "adjustment_mode": "none",
  "data_snapshot_id": "ohlcv-snapshot-id",
  "factor_snapshot_id": null,
  "price_basis": "display_view",
  "anchors": [
    { "timestamp": "2026-07-01T07:00:00Z", "price": "21.35" },
    { "timestamp": "2026-07-10T07:00:00Z", "price": "23.10" }
  ],
  "text": null,
  "style": { "color": "#2962ff", "line_width": 2 },
  "links": [],
  "created_at": "2026-07-11T12:00:00Z",
  "created_by": "local-user"
}
```

约束：

- `annotation_id` 是稳定逻辑身份；修改创建新的 `annotation_version_id/version` 并引用 `supersedes_version_id`。删除写入 `status="deleted"` 的 tombstone 新版本，不抹除历史。
- `anchors[].price` 用十进制定点字符串持久化，adapter 在图库边界才转成 JavaScript number；timestamp 必须是已规范化的市场 bar timestamp。
- 调整视图必须有 `factor_snapshot_id`；`none` 必须为空。`links` 可关联 research run、forecast、trade、trade plan version 或事件，但图库不解释这些领域引用。
- `style` 只允许产品定义的 JSON 白名单；不得把库名、KLine overlay name、ECharts option、Canvas 对象或任意函数藏入 DTO。
- KLineChart `Overlay`、Lightweight Charts primitive/回调、ECharts `getOption()`/formatter/renderItem/event handler 都是运行时对象，**禁止直接 `JSON.stringify` 后入库**。adapter 的职责是 `DTO -> library object` 与 `library event -> validated domain command`，不是保存图库内部状态。

## 离线打包与框架集成成本

| 候选 | 离线/Windows | 框架成本 |
|---|---|---|
| Lightweight Charts 5.2.0 | npm 固定包只发布 `dist/**`，提供 production/development ESM 和 standalone bundle；无 native addon，运行时不需要 TradingView 服务或市场数据服务。npm 解包约 3.07 MB、10 files；直接依赖 `fancy-canvas@2.1.0`。 | Vanilla DOM API；官方有 React 教程但没有必要引入第三方 wrapper。组合 K 线+成交量容易，交互趋势线编辑/恢复的 adapter 与状态机成本最高。 |
| KLineChart 10.0.0 | npm 固定包含 ESM/CJS/UMD、类型、LICENSE/NOTICE/licenses，零运行时依赖，解包约 2.86 MB、12 files；无 native addon，适合 Vite/本地静态资产。DataLoader 应接本地后端/缓存，不直接接第三方网络。 | Vanilla DOM API；内置 overlay 显著减少绘图 UI 成本。10.x major 的 API 变更和无上游自动测试使测试成本最高，但通过 adapter 可隔离。 |
| Apache ECharts 6.1.0 | npm 包解包约 60.30 MB、1347 files，含 ESM/CJS/预构建包；可从 `echarts/core`、charts/components/renderers 做模块化打包，无 native addon。 | Vanilla DOM API；K 线+bar+dataZoom 成熟，但拖拽趋势线、命中与数据坐标回写需自己实现；作为本切片主图不比 KLineChart 省成本。 |

所有方案都必须精确锁定版本与 integrity，离线构建不得依赖 CDN；浏览器运行时不得发出图库遥测或外部数据请求。框架若选 React/Vue，应由薄 lifecycle component 创建/销毁 chart，领域 DTO 与 adapter 保持框架无关。

## `adopt / adapt / reference only / reject` 决策矩阵

| 候选 | 决策 | 证据化理由 | 反向条件 |
|---|---|---|---|
| `klinecharts@10.0.0` | **adapt** | 内置 overlay + draw/move/remove 回调 + timestamp/value points + 像素互转，完成第一条持久化标注的胶水最少；零依赖；npm/tag commit 一致。必须隔离 DataLoader、领域 DTO、版本历史和复权语义。 | 若固定包不能通过下述 Windows E2E/重启/离线门禁，立即停止采用并把 Lightweight Charts primitive 原型升格，不在业务层打补丁绕过。 |
| `lightweight-charts@5.2.0` | **reference only**（本 K 线切片） | 产品边界清晰、维护和测试证据最强；坐标 API、primitive、hit test、React lifecycle 与插件示例值得借鉴。交互趋势线只是示例，完整编辑/持久化需自建，首切片成本高；另有显式 TradingView 页面归属要求。 | KLineChart 原型失败，或团队更重视长期上游测试质量并接受自建绘图工具时，转为 `adapt`。 |
| `echarts@6.1.0` | **reference only**（K 线交互面） | candlestick、bar、dataZoom、marker/graphic、坐标转换和测试体系成熟，但它是通用可视化库，金融交互绘图状态机仍由应用承担，主图适配成本高。 | 后续报告/横截面对比/研究 artifact 可单独评估为 `adopt/adapt`；本票不否定其非 K 线用途。 |
| TradingView Advanced Charts/Trading Platform、Widgets、KLineChart Pro | **reject**（本票范围） | 不是本次核验的同一开源基础包；许可证、托管、数据和分发边界不同，不能用基础库的 Apache-2.0 结论覆盖。 | 只有新建独立研究票并重新核验固定版本与许可后才能进入候选。 |

## KLineChart 10.0.0 受控原型的进入门槛

1. 精确锁定 `klinecharts@10.0.0`、npm integrity 与 commit `0474602c…`，生成第三方许可证清单并展示完整 NOTICE。
2. adapter contract：canonical 未复权 KLineData 映射、VOL pane、`DTO -> overlay -> event -> new DTO version` JSON round-trip；不允许图库 id/pixel/index 泄漏到持久化模型。
3. Windows Chromium E2E：显示 K 线与成交量，画/移动一条趋势线，刷新页面和重启本地服务后坐标一致；删除产生 tombstone，旧版本仍可回看。
4. 跨周期/复权高风险用例：无交易日锚点、日到周/月 bucket、前/后/不复权切换、除权日、factor snapshot 修订。无法精确映射时必须显示 unresolved/需确认，不得静默吸附。
5. 离线 E2E：断网且本地已有数据/静态 bundle 时可启动和回看，浏览器 network log 无图库 CDN、遥测或第三方数据请求。
6. 生命周期与性能：创建/销毁无重复订阅；resize/zoom 后锚点不漂移；至少用切片代表性 bar 数验证交互；任何上游异常由 adapter fail closed 并保留原 DTO。

在这些门槛通过前，结论保持 `adapt/prototype`，不得在 Spec 中写成“已采用并验证”。
