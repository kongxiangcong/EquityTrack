# 07 — 构建 MarketSnapshot 并执行 PlanEvaluation

**What to build:** 让平台从确切 DataSnapshot 构建透明、可解释的 A 股 MarketSnapshot，并对一个确切 active TradePlanVersion 执行只读、确定性的 PlanEvaluation。用户看到每条规则的输入、结果、原因、限制和证据，而不是黑箱总分或系统交易动作。

**Blocked by:** 03 — 授权同步并冻结 PIT DataSnapshot; 06 — 确认并启用不可变 TradePlanVersion.

**Status:** resolved

- [x] MarketSnapshot 只消费指定 DataSnapshot，并用 Security、market scope、requested/effective date、模型、freshness policy、有序组件和 code identity 形成可重算身份。
- [x] trend、breadth、liquidity、volatility 和 security price context 按 Spec 的固定窗口、样本门、分位阈值和 exact 输入确定性计算；不输出黑箱总分。
- [x] PIT universe membership 100% 可解释；Provider 缺失、quarantine、成交额缺行或不可证明排除使相关组件 blocked，并保存 expected、eligible、excluded、missing 计数。（AC-042）
- [x] 不支持的宏观、资金、新闻、情绪、拥挤度和行业轮动明确标记 unsupported，不填成中性或伪事实。
- [x] evaluation 精确引用 active plan version、MarketSnapshot、evaluator version 和 policy version，并以这四项形成幂等键。（AC-013）
- [x] 每条规则保存多值结果、reason code、actual operands、单位、观测时点、effect、applies_to 和 evidence refs；missing、conflict、stale 和 not-applicable 不被当作 false。
- [x] 停牌、涨跌停、market gate、exit、invalidation 和 risk 结果并列呈现；触发只产生复核、限制或失效候选，不改变计划生命周期或生成交易 payload。（AC-014、AC-025）
- [x] offline valid/stale/missing、MarketSnapshot limited/blocked 和 PlanEvaluation partial/blocked 按能力边界传播，历史读取仍可用。（AC-018 评估部分）
- [x] 相同输入复用 MarketSnapshot 和 PlanEvaluation；数据修订、新计划版本、新 evaluator 或 policy 生成并列结果，旧结果不覆盖。（AC-021、AC-049 评估部分）
- [x] v2 草稿未确认时 daily 仍评估 v1；v2 启用后新评估引用 v2，而旧评估继续引用 v1。（AC-022 评估部分）

## Implementation Evidence

- `0006_market_snapshot_evaluation.sql` 增加冻结 DataSnapshot→PIT universe 引用、全 universe 市场约束、不可变 MarketSnapshot/components、PlanEvaluation/rule operands/evidence 与防 late-insert triggers。
- `cn-a-share-market@1` 以 exact Decimal 输入确定性计算 benchmark trend、breadth、全市场 liquidity、20 日年化 log-return volatility 与 security price context；最多使用 252 个前置样本且明确 unsupported 组件。
- universe identity 对有序 member/source refs、membership hash 与 source-policy 重算并进入 fingerprint；上市/退市/上市不足/已证明停牌形成结构性 exclusion，缺约束、缺成交额或未知缺行形成 missing/blocked，不冒充排除。
- `PlanEvaluation` 只接受确切 active TradePlanVersion；四元键幂等，保存五值规则结果、reason/operands/unit/time/evidence/effect/applies_to；任一 blocked 规则不会被 triggered 覆盖，评估无计划状态或交易副作用。
- `python -m pytest tests/platform/test_market_evaluation.py tests/platform/test_data_sync_pit.py tests/platform/test_trade_plans.py -q` -> `23 passed`；覆盖 idempotency、修订并列、code/policy identity、v1/v2、stale/missing、横截面覆盖、停牌/涨跌停/公司行动冲突和不可变历史。
- 完整验证：`python -m pytest -q` -> `100 passed`；`npm test --prefix web` -> `4 passed`；`npm run build --prefix web`；`python -m compileall -q src`；`git diff --check`。
- `code-review` 修复全部有效发现后最终复审：Standards PASS；Spec PASS；无剩余 actionable finding。
