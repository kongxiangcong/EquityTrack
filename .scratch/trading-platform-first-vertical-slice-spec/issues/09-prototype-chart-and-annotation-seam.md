# 原型化 K 线与持久化标注 seam

Type: `prototype`
Mode: `HITL`
Status: resolved
Blocked by: 04, 06, 07

## Question

在选定图表库、数据/时间契约和示例标的后，用最低成本的可交互原型确认第一条纵向切片的 K 线页面应如何加载版本化 OHLCV、明确显示复权/数据截至时间、创建至少一条标注、刷新或重启后恢复相同时间与价格坐标，并关联研究 run、计划版本或事件证据。原型应专注最高风险交互和序列化契约，验证标注类型、坐标、版本、作者/创建时间、删除/修改语义和缺失数据状态，不作为正式 UI 实现。

## Comments

- 已建立可丢弃的[三变体 K 线与版本化标注原型](../prototypes/chart-annotation-prototype/README.md)，并记录[Windows Chromium 手工 E2E 与设计发现](../prototypes/chart-annotation-prototype/VALIDATION.md)。
- 当前原型锁定 `klinecharts@10.0.0`，使用真实且脱敏的 29 日未复权意华股份 fixture；完成 v1 创建、v2 修改、v3 tombstone、v4 恢复、页面刷新、服务重启、跨周期 fail-closed、stale/missing 和本地资源检查，浏览器无 warning/error。
- 本票为 HITL，等待用户在 A“证据优先控制台”、B“画布优先驾驶舱”、C“版本账本工作台”中选择整体方向或组合要素。在用户真实反馈前保持 `Status: claimed`，不写 `## Answer`、不关闭票据、不更新 map 的 Decisions-so-far。
- 2026-07-12 用户将本票的 UI 取舍提升为项目长期设计基线：设计驱动、用户友好、默认只展示判断相关信息、过程数据渐进披露、尽可能帮助用户理解和判断，并采用 Apple 启发的清晰/克制/层级/一致性风格；完整规则写入[总任务 Prompt](../../../docs/prompts/trading_platform_codex_prompt_optimized.md#product-and-interaction-design-principles--产品与交互设计原则)。

## Answer

用户在实际查看三个可交互变体后明确裁决：**不采用 A；以 B“画布优先驾驶舱”为默认视图，吸收 C 的不可变版本账本作为可收起版本侧栏，并让同一个 B 视图同时承担全屏模式。** 原型问题已经得到真实 HITL 回答。

### 1. 正式 UI 的信息层级

- 默认 K 线工作台以 B 为骨架：K 线、成交量和标注工具占据主视觉与最大空间；默认视图和全屏视图复用同一个 chart component、adapter、selection 和 annotation state，不维护第二套图表实现。
- C 不再作为独立默认页面。其 v1/v2、`supersedes`、tombstone、恢复和领域关联成为 B 的“版本侧栏”：桌面端可收起 dock，窄屏为 drawer；进入全屏时默认收起，用户需要时可覆盖打开。
- A 不进入正式主视图。数据来源、抓取状态、DataSnapshot identity、完整序列化状态等过程/provenance 数据不得持续铺在图表旁、占用画布或主导视觉。
- 正常状态下，主视图只保留用户理解图表所需的最小语义，例如 `Security`、周期、复权模式和有效截止日；完整来源、snapshot/factor identity、provider attempt 和质量明细放入按需“数据详情”、历史或审计入口。
- 美化不能隐藏会改变当前能力的异常。`missing`、阻断级 `stale`、数据冲突、复权或跨周期坐标无法安全迁移必须在图表附近显示紧凑且明确的 warning/blocking banner；正常 `pass` 状态不常驻展示。

### 2. 标注与版本化 seam

- `ChartAnnotation` 保持稳定逻辑身份；创建产生 v1，修改追加新版本并引用 `supersedes_version_id`，删除追加 `status=deleted` tombstone，恢复再追加 active 版本，旧版本不可覆盖或删除。
- 持久化 DTO 只保存证券、interval、adjustment mode、`data_snapshot_id`、适用时的 `factor_snapshot_id`、市场 timestamp、十进制 price string、白名单 style、作者/创建时间和领域 links。禁止保存 pixel、dataIndex、KLineChart overlay/runtime id、回调或 Canvas 对象。
- 图表 adapter 承担 `DTO -> overlay` 与图库事件到领域 command 的投影。`onDrawEnd`、`onPressedMoveEnd` 和显式删除操作不能直接修改历史记录。
- ResearchRun、Evidence、TradePlanVersion 或事件只作为 typed links 关联；图表库不解释这些领域对象。

### 3. KLineChart 与交互裁决

- `klinecharts@10.0.0` 维持 **`adapt`**，不是无条件 `adopt`。本原型已在 Windows Chromium 手工通过 K 线/VOL、画线、版本修改、tombstone、恢复、刷新、服务重启、离线静态资源和 missing/stale 门禁，浏览器无 warning/error。
- 内置 `segment` 的实际操作需要起点、终点和最终确认三步；正式 B 工具栏必须清楚呈现绘制状态和提交反馈，避免用户把第二个锚点误认成已经持久化。
- 正式实现必须重写原型代码并补自动化 browser E2E、生命周期/性能和许可证归属检查；原型的 `localStorage` 只证明 DTO round-trip，不证明 SQLite 事务、迁移或并发合同。

### 4. 复权、跨周期与缺失数据边界

- 只有存在目标 interval/adjustment mode 对应的不可变 derived DataSnapshot、factor snapshot 和受测确定性映射时，才允许生成新标注版本或显式迁移版本。
- 无交易日 anchor、日到周/月 bucket、除权日、factor revision 或目标 bar 不唯一时返回 `unresolved_requires_confirmation`，保持旧版本原坐标，禁止按最近 bar、数组索引或像素静默吸附。
- `missing` 不渲染假 K 线、不允许新标注；历史版本仍可审计。`stale` 是否允许历史查看或阻断当日能力由消费能力决定，并以异常 banner 表达，不把完整状态矩阵常驻主视图。

原型和验证证据见[三变体原型说明](../prototypes/chart-annotation-prototype/README.md)与[验证记录](../prototypes/chart-annotation-prototype/VALIDATION.md)。完整原型 primary source 已保存在分支 `codex/prototype-chart-annotation-seam`、commit `4519e92709895c1c656101972108e36889c1a924`；它不应直接合并为生产 UI。

本票已把 map 中关于复权坐标、公司行动、跨周期重采样和标注迁移的 fog 收敛成以上确定性门禁与强制失败用例，无需新增 Wayfinder 决策票；这些用例由后续验收 seam 与 Spec 继承。
