# 13 — 验证完整公司未来推演旅程

**What to build:** 让用户对意华股份和多氟多执行完整、可重复的公司未来推演，看到适配的故事、Driver、情景、多方法估值、可选模拟、复盘入口和决策优先报告，并能在平台历史中重启回看全部证据与版本。

**Blocked by:** 05 — 发布决策优先的研究视图; 06 — 增加校准后的 Valuation 模拟; 07 — 独立建模市场价格路径; 08 — 复盘 Forecast 并校准模型; 09 — 支持周期与资源证券估值; 10 — 支持金融企业 Valuation; 11 — 支持创新药 rNPV 与 SOTP; 12 — 收缩遗留研究与模型路径.

**Status:** done — complete public journey, replay and evidence gates verified

- [x] 两个真实样例经公开 facade 从 PIT DataSnapshot 建立/复用完整的六类 artifact：`DataSnapshot`、`Forecast`、`Valuation`、`Simulation`、`MarketDataSnapshot`、`MarketPathSimulation`。
- [x] 意华股份验证普通多分部驱动、FCFF/SOTP/reverse DCF 与数据不足降级；多氟多内部模型契约验证周期制造中枢、业务期权、重复计价防护、资本约束和经历史经营样本校准的企业价值 Monte Carlo 分布，但不冒充正式可发布旅程。
- [x] 多氟多缺少官方养老金调整和完整摊薄股本桥时，中周期方法只保留企业价值；权益价值与每股价值均明确为空。公开 facade 额外拒绝无股本 identity 的每股 artifact 注入。
- [x] 正式故事由 Forecast 的类型化 narrative statements 生成，不再读取 legacy `analysis`/`synthesis` 魔法键。
- [x] 报告与工作区默认展示故事、关键 Driver、情景及价值/市场路径差异。多氟多明确区分研究 `as_of=2026-07-18` 与有效行情 session `2026-07-17`，并保留独立的 available/retrieved 时间。
- [x] 已在最终行为上重新完成真实 Chromium、全量测试与双轴复审；旧的通过记录未作为本轮证据复用。
- [x] 多氟多 source manifest 以 v2 `valid_with_limits` 通过：11 个原始资产完成 hash 验证、零完整性错误；公开六类 artifact 在重启后复用相同 record ID 与 content hash。错误归属其他公司的二级 IR 文件已移除，关键事实改绑官方年报。

### Remaining per-share and cross-check unlock package

1. 最新官方直接披露的稀释加权平均股数或完全摊薄股数。
2. 股权激励、期权、限制性股票、员工持股、库存股、可转债及其他工具到增量稀释股数的完整官方桥；不存在时也需有可审计的官方口径。
3. 通过来源、币种和会计口径检查的至少三家同源可比公司、可用 PIT 历史区间分母，以及仅在资源储量业务存在时才需要的有限寿命 NAV 输入。

养老金和摊薄桥缺口仅阻断权益/每股换算，不再错误压制不依赖这些字段的企业价值能力。公开 workflow 可发布 `valid_with_limits` 的企业价值推演；价值模拟为 `CNY`，市场路径为 `CNY/share`，工作区将二者标为 `not_comparable`，不计算伪造的数值背离。

### Verification evidence

- 公开 facade 完整旅程、关闭数据库后的 restart/replay、六类 artifact lineage/hash 一致性均有自动化验收。
- 平台使用固定校准证据容差重新计算 observation vectors；artifact 自报的大容差不能掩盖篡改。
- 冻结市场数据快照的 `effective_session_date` 约束起始价格 session，不再用周末启发式猜测交易日历；价格 tick size 是显式 policy 数据。
- 官方 Q1、年报、资产转让和异常波动披露均保存 published/available/retrieved 三类 PIT 时间；非官方结构化行情不升级为官方财务权威。
- 最终测试与双轴复审结果记录在 `docs/acceptance/company-outlook-ticket13.md`。
