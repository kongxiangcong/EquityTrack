# 08 — 复盘 Forecast 并校准模型

**What to build:** 让用户在后续公告或财报到来后，把实际结果与原始 Forecast 对照，看到事件判断、数值区间和 Driver 偏差来自哪里，并据此创建新的校准版本而不改写历史。

**Blocked by:** 04 — 持久化不可变 Forecast 与 Valuation 产物; 06 — 增加校准后的 Valuation 模拟.

**Status:** done

- [x] ForecastReview 追加保存实际结果 Evidence、原 Forecast/Scenario/Simulation 引用、复核时点和 reviewer/policy identity，原预测不可更新或删除。
- [x] 概率事件计算 Brier Score；数值预测计算绝对误差、相对误差、方向、区间覆盖率和按 Driver 的误差分解。
- [x] 缺失、重述、口径变化和延迟披露不会被静默当作预测失败，review 明确说明可比性状态。
- [x] 任何校准变化形成新 Assumption/model version，旧 Simulation 与报告保持可回放。
- [x] 工作区提供预测登记、到期复核和误差历史视图，默认不把单次命中包装成模型有效性证明。
