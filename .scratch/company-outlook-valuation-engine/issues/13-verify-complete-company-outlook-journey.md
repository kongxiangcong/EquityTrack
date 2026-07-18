# 13 — 验证完整公司未来推演旅程

**What to build:** 让用户对意华股份和多氟多执行完整、可重复的公司未来推演，看到适配的故事、Driver、情景、多方法估值、可选模拟、复盘入口和决策优先报告，并能在平台历史中重启回看全部证据与版本。

**Blocked by:** 05 — 发布决策优先的研究视图; 06 — 增加校准后的 Valuation 模拟; 07 — 独立建模市场价格路径; 08 — 复盘 Forecast 并校准模型; 09 — 支持周期与资源证券估值; 10 — 支持金融企业 Valuation; 11 — 支持创新药 rNPV 与 SOTP; 12 — 收缩遗留研究与模型路径.

**Status:** in-progress — valuation foundation hardened; complete journey still blocked

- [ ] 两个真实样例经公开 facade 从 PIT DataSnapshot 建立/复用完整的六类 artifact。意华股份已覆盖；多氟多的 source manifest 仍无效，因此公开 workflow fail closed，不发布模型候选 artifact；独立 MarketDataSnapshot/MarketPathSimulation 也尚缺。
- [x] 意华股份验证普通多分部驱动、FCFF/SOTP/reverse DCF 与数据不足降级；多氟多内部模型契约验证周期制造中枢、业务期权、重复计价防护、资本约束和经历史经营样本校准的企业价值 Monte Carlo 分布，但不冒充正式可发布旅程。
- [x] 多氟多缺少官方养老金调整和完整摊薄股本桥时，中周期方法只保留企业价值；权益价值与每股价值均明确为空。公开 facade 额外拒绝无股本 identity 的每股 artifact 注入。
- [x] 正式故事由 Forecast 的类型化 narrative statements 生成，不再读取 legacy `analysis`/`synthesis` 魔法键。
- [ ] 报告与工作区默认展示故事、关键 Driver、情景及价值/市场路径差异。多氟多市场路径必须使用检索时间不晚于研究 as-of 的冻结行情快照；不得将 2026-07-17 新取数据反向声明为 2026-07-03 PIT 数据。
- [x] 已在最终行为上重新完成真实 Chromium、全量测试与双轴复审；旧的通过记录未作为本轮证据复用。
- [ ] 当前仓库内候选校准资产已完成 hash 验证，但多氟多七个公开原始来源文件仍缺失，无法完成公开六类 artifact 的最终 hash 验收。

### Remaining per-share and cross-check unlock package

1. 最新官方直接披露的稀释加权平均股数或完全摊薄股数。
2. 股权激励、期权、限制性股票、员工持股、库存股、可转债及其他工具到增量稀释股数的完整官方桥；不存在时也需有可审计的官方口径。
3. 通过来源、币种和会计口径检查的至少三家同源可比公司、可用 PIT 历史区间分母，以及仅在资源储量业务存在时才需要的有限寿命 NAV 输入。

养老金和摊薄桥缺口阻断权益/每股换算；缺失原始文件导致 source manifest 整体无效，因此在补齐并重新通过 validator 前，公开 workflow 不发布正式估值或模拟 artifact。内部企业价值模型只能作为待验证候选。
