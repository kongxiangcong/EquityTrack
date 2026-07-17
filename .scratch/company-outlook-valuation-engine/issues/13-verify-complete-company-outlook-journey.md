# 13 — 验证完整公司未来推演旅程

**What to build:** 让用户对意华股份和多氟多执行完整、可重复的公司未来推演，看到适配的故事、Driver、情景、多方法估值、可选模拟、复盘入口和决策优先报告，并能在平台历史中重启回看全部证据与版本。

**Blocked by:** 05 — 发布决策优先的研究视图; 06 — 增加校准后的 Valuation 模拟; 07 — 独立建模市场价格路径; 08 — 复盘 Forecast 并校准模型; 09 — 支持周期与资源证券估值; 10 — 支持金融企业 Valuation; 11 — 支持创新药 rNPV 与 SOTP; 12 — 收缩遗留研究与模型路径.

**Status:** in-progress — executable verification complete; real 多氟多 typed valuation chain awaits official inputs

- [ ] 两个真实样例经公开 facade 从 PIT DataSnapshot 建立/复用 ResearchRun、Forecast、Valuation、Simulation 和 ArtifactManifest，重启后完整回看。（意华股份完整通过；多氟多仅建立/复用 ResearchRun、snapshot 与 manifest，正式 typed chain 因官方摊薄股本桥及所选方法输入缺失而禁用。）
- [ ] 意华股份验证普通多分部驱动、FCFF/SOTP/reverse DCF 与数据不足降级；多氟多验证周期中枢、业务期权、重复计价防护和资本约束。（真实多氟多叙事和降级边界通过；周期估值方法由独立合成 golden 验证，未冒充多氟多证据。）
- [x] 报告与工作区默认展示故事、关键 Driver、情景与价值/价格路径差异，审计信息渐进披露，金融输出边界通过禁止语言扫描。
- [x] 浏览器完成真实 Chromium 旅程、响应式和可访问性复核；发现问题后修复并再次验证。
- [x] 全量 Python、Web、迁移、恢复、幂等、PIT、随机可复现、模型 golden cases、许可证和跨平台入口测试通过。
- [x] 完成清单逐项引用当前代码、运行、artifact hash 和测试证据；未通过的长期能力不得被完成状态掩盖。见 `docs/acceptance/company-outlook-ticket13.md`。

### Remaining external unlock package

1. 最新官方直接披露的稀释加权平均股数或完全摊薄股数。
2. 股权激励、期权、限制性股票、员工持股、库存股、可转债及其他工具到增量稀释股数的完整官方桥；不存在时也需有可审计的官方口径。
3. 所选周期估值方法所需的同口径分部经营输入、版本化商品价格曲线，以及通过来源、币种和会计口径检查的至少三家同源可比公司或可用历史区间分母。
