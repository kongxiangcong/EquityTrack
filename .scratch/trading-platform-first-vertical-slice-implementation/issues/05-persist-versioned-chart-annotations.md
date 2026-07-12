# 05 — 展示版本化 K 线并持久化 ChartAnnotation

**What to build:** 让用户在本地工作区查看确切 DataSnapshot 对应的版本化 K 线，并创建、修改、删除、恢复至少一条语义标注。浏览器刷新、应用重建和服务重启后，标注身份、坐标、引用及其不可变版本历史保持一致。

**Blocked by:** 03 — 授权同步并冻结 PIT DataSnapshot.

**Status:** resolved

- [x] 图表查询返回截至 2026-07-10 的版本化日 K 线，并明确 adjustment mode、snapshot/factor refs、effective session 和 freshness。（AC-009）
- [x] 图表库固定版本和 integrity，资源完全本地打包且无 CDN、遥测或隐式安装；薄 adapter 只转换 DTO、overlay 和经校验的领域命令。
- [x] 图表与持久化层不保存像素、数组下标、runtime overlay id、回调、Canvas 或图库私有序列化对象。
- [x] 公共 annotation commands 使用 invocation id 和并发控制创建 v1、追加修订、追加 tombstone 和追加恢复版本；历史不可覆盖或删除。
- [x] 每个版本保存稳定 identity、Security、interval、adjustment、snapshot/factor refs、市场时间、exact price、受控 kind/style、作者和 typed links。
- [x] 完全关闭并重建 facade 后，标注 identity、timestamp、exact price、interval、adjustment 和 refs 与写入时一致。（AC-010）
- [x] browser reload 和 server restart 后，图表与标注恢复一致；默认和全屏视图复用相同领域状态、选择和 chart adapter。（AC-031 图表部分）
- [x] 跨周期、复权或公司行动坐标只有在唯一确定映射时才追加新版本；无交易日 anchor、bucket 不唯一、因子修订或无法反算时 fail closed 并保留旧坐标。（AC-024、AC-026）
- [x] 绘制流程提供清楚的起点、终点、确认、持久化反馈和键盘焦点，且不只用颜色表达状态。（AC-032 图表部分）

## Implementation Evidence

- `tests/platform/test_chart_annotations.py`: 12 passed；覆盖公开 Issue 03 PIT snapshot 图表查询、exact decimal/市场时间、v1→v2→tombstone→restore、invocation replay、并发冲突、不可变 identity/version/anchor/link、重建 facade/server、跨周期/复权/非交易日 fail closed。
- `web/tests/*.test.js`: 4 passed；薄 adapter 不持久化 pixel/dataIndex/runtime object，并验证成功响应丢失时复用同一 invocation、不同命令阻断及已知失败释放。
- `python scripts/verify_issue05_browser.py`: 真实临时-profile Chromium PASS；实际渲染 10 个 canvas、零外部资源，完成 v1 创建/v2 修订/v3 删除/v4 恢复，reload 与 server restart 四版本一致，并通过焦点推进、共享全屏、800px 响应式、reduced motion、校验失败恢复和 `201` body 丢失安全重放（`ambiguous_replay=true`）。
- `npm run build`: `klinecharts@10.0.0` 本地 production bundle 成功；package lock 固定 integrity，构建复制完整 upstream Apache-2.0 `LICENSE`/`NOTICE`，运行时无 CDN/遥测/隐式安装。
- 完整回归：`python -m pytest -q` => 88 passed；`python -m compileall -q src scripts` 与 `git diff --check` 通过。
- `python -m pip install --dry-run --require-hashes -r requirements-browser-test.lock` 通过；Chromium verifier 的唯一 Python 测试依赖有精确版本和 wheel SHA-256。
- code-review Standards 与 Spec 双轴最终复审均 PASS；所有有效问题已修复并重新验证。
- `git check-ignore -v docs/data docs/data/private-example.csv` 命中 `.gitignore:11:docs/data/`；未暂存个人同花顺数据。
