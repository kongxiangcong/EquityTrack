# 05 — 发布决策优先的研究视图

**What to build:** 让用户打开报告或本地工作区时先看到核心故事、市场隐含预期、关键 Driver、情景财务和条件价值区间；完整来源、公式、参数、版本和诊断仍可按需展开。

**Blocked by:** 03 — 交付多方法确定性情景估值; 04 — 持久化不可变 Forecast 与 Valuation 产物.

**Status:** done

- [x] 首屏按“发生什么、为什么重要、如何传导、有哪些反例、什么会改变判断”组织，不显示默认展开的来源表、能力矩阵或运行日志。
- [x] 基准/改善/压力情景展示 Driver、关键财务结果和方法级 low/base/high 价值区间；reverse DCF 明确解释当前价格隐含假设。
- [x] 每股价值只以条件研究区间/分布呈现，不使用评级、建议式目标价或买卖语言。
- [x] 平台提供安全的研究 view-model / artifact 读取路径并真正加载 sandbox 报告视图，历史版本可选择且不会从 HTML 反解析权威数字。
- [x] 浏览器验收覆盖响应式、原生键盘焦点语义、焦点、等效缩放、减少动态和渐进披露，并执行修复后复验。

## Implementation evidence

- 正式 JSON、HTML、Web workspace 和 XLSX 均读取同一 `ResearchDecisionView@2`；HTML 内嵌 canonical view 只用于精确审计，不从 HTML 反解析权威数字。
- 正式 HTML 展示市场隐含预期、估值分布、市场价格/回撤路径与价值-市场差异；模拟或市场路径缺失时局部省略，不伪造结果。
- 审计附录默认关闭，展开后包含 artifact、事实证据、公式身份、模型参数、来源、版本/权限及诊断/缺口；补充公司叙事也独立渐进披露。
- 最终聚焦回归 29 passed；Ruff passed；Standards 与 Spec 双轴复审均 PASS。
- 真实 in-app Chromium 在 390×844 下文档 `scrollWidth == clientWidth == 375`，首屏标题严格按五问排序；240px 等效二倍缩放下文档 `scrollWidth == clientWidth == 225`，宽表只在自身容器滚动。
- 所有 8 个 `summary` 在真实 DOM 中 `tabIndex == 0`；补充叙事与审计默认关闭，交互后焦点保持在 `SUMMARY`，审计显示 3 个 artifact 和 6 个追溯分组；`prefers-reduced-motion` 规则由真实页面样式表确认存在。
