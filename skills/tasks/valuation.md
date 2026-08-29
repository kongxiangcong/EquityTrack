# 估值任务

只有用户明确请求时调用 `valuation.assess`。AI 可以提出方法与有来源的假设候选；Python 决定方法适用性、单位/币种、公式、敏感性和 completed/insufficient。

金融企业禁用普通 FCFF/WACC DCF；pipeline biopharma 优先 rNPV/SOTP；周期与资源企业使用 mid-cycle/NAV；普通成熟非金融企业仅在关键现金流、WACC、增长、权益桥和稀释股数完整且 `WACC > g` 时使用 DCF。可比法少于三个同源、同口径可用 peers 时 insufficient。情景只使用 stress/base/improvement；没有校准证据不附加概率。

输出说明方法、结果或缺失、敏感性、数据质量、关键不确定性和什么会改变判断，不输出评级、个性化行动建议或不受支持的目标价结论。
