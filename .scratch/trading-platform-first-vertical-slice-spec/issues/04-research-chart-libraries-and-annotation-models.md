# 调研 K 线库、标注能力与许可证

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

`TradingView Lightweight Charts`、`KLineChart` 与 `Apache ECharts` 中，哪种方案最适合 Windows 本地优先的第一条纵向切片，并能在明确的前/后/不复权语义下展示 K 线、成交量和至少一条可持久化标注？研究必须核验各候选的准确产品边界、固定版本许可证、NOTICE/归属要求、维护状态、核心源码与测试、绘图/事件 API、序列化能力、时间与价格坐标、跨周期/复权行为、离线打包和框架集成成本；不得把 TradingView 所有产品笼统视为开源，也不得只看 README。输出独立 Markdown 研究资产和 `adopt / adapt / reference only / reject` 结论所需证据，不在本 ticket 实现正式 UI。

## Answer

已完成独立研究资产：[K 线库、标注模型与许可证调研](../research/chart-libraries-and-annotation-models.md)。

- **`klinecharts@10.0.0` — `adapt`**：精确锁定 npm integrity 与 commit `0474602cc0f8ff6db4629eaae255052e640a5c93` 后进入受控原型。它内置 K 线、VOL、交互 overlay、绘制/移动/删除回调和时间/价格坐标转换，完成第一条可持久化标注所需 UI 胶水最少；但它是本调研日刚发布的 major，固定 tag 没有自动测试，因此不能写成成熟 `adopt`。
- **`lightweight-charts@5.2.0` — `reference only`**：上游维护和测试证据最强，坐标、primitive、hit-test 与 lifecycle seam 值得借鉴；但交互绘图工具仅为示例，首切片需自建状态机、编辑手柄和持久化 adapter。它只是开源 Lightweight Charts，不代表 TradingView Advanced Charts、Trading Platform 或 Widgets，且页面归属和链接要求必须保留。
- **`echarts@6.1.0` — `reference only`**：candlestick、bar、dataZoom、marker/graphic、坐标转换与测试体系成熟，但属于通用可视化库，没有现成金融趋势线编辑器；后续非 K 线分析图可另行评估。
- 三库均只渲染调用方提供的数据，不负责交易日历、跨周期聚合、公司行动或前/后/不复权。平台继续保存未复权 canonical OHLCV；派生视图必须引用固定 `data_snapshot_id`、`factor_snapshot_id` 与 adjustment mode。
- 标注持久化采用库无关、不可变版本 DTO：稳定 `annotation_id`，版本身份与 supersedes 链，市场 timestamp + decimal price 锚点、interval、复权模式、数据/因子快照、受控 style 与领域 links。禁止保存 pixel/dataIndex、KLineChart `Overlay`、Lightweight Charts primitive 或 ECharts `getOption()`/函数对象。
- 采用门槛由[原型化 K 线与持久化标注 seam](09-prototype-chart-and-annotation-seam.md)验证：本仓库 contract、Windows 浏览器 E2E、画/移/删/刷新/重启 round-trip、跨周期/复权 unresolved 行为、离线 bundle/network、生命周期和性能。门槛失败时停止采用 KLineChart，并把 Lightweight Charts 升为 `adapt` 候选。

本票没有实现正式 UI，也没有新增 Wayfinder ticket；公司行动、无交易日、周/月 bucket 与因子修订等已明确反例继续由既有原型票验证。
