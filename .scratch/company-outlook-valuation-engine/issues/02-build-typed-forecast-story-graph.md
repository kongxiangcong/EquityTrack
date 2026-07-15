# 02 — 建立类型化 Forecast 故事图

**What to build:** 让一只普通非金融 A 股的研究从冻结 Fact 与显式 Assumption 出发，形成可证伪的事件、业务驱动、财务预测和复核条件，而不是由调用者预写最终故事文本。

**Blocked by:** 01 — 保护金融量纲与统一股权桥.

**Status:** ready-for-agent

- [ ] Forecast 图只允许可验证的事件、Driver、FinancialForecast 和 Valuation 依赖，图无环且每条数值边通过单位、期间和币种检查。
- [ ] 普通制造/多分部证券至少支持销量或需求、ASP、产能、利用率、成本、利润率、资本开支和营运资本驱动到三表/FCFF 的确定性传播。
- [ ] 每条 Forecast 保存期限、里程碑、领先指标、触发条件、失效条件、复核日期和 Fact/Assumption lineage。
- [ ] 调用者只需指定 Security、截至时点、DataSnapshot 和有限的 typed assumption overrides；公司类型与模板路由可解释但不成为自由 Mapping。
- [ ] 旧 analyses/debate/synthesis 输入暂由兼容 adapter 接受，新计算路径不直接读取 magic keys。

