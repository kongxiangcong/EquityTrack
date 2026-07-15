# 10 — 支持金融企业 Valuation

**What to build:** 让银行、保险和券商围绕监管资本、ROE/COE、信用成本、净息差、承保与可分配现金流推演，并明确禁止普通工业企业 FCFF/WACC DCF。

**Blocked by:** 03 — 交付多方法确定性情景估值; 04 — 持久化不可变 Forecast 与 Valuation 产物.

**Status:** ready-for-agent

- [ ] 金融企业路由自动禁用普通 FCFF/WACC，并选择适用的 P/B-ROE/COE、DDM、剩余收益或 excess-return 方法。
- [ ] 方法执行处理 clean-surplus、监管资本、信用成本、资产质量和稀释，并保存公式、期间、单位与 lineage。
- [ ] DDM 与剩余收益在一致 fixture 上可交叉解释；方法差异不会被无依据平均。
- [ ] 银行、保险和券商缺少专属输入时局部受限，不回退工业企业模板或伪造结果。
- [ ] 报告以条件价值与资本约束表达，不生成 house-style rating 或交易建议。

