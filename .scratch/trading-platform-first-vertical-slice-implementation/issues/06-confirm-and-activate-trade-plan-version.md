# 06 — 确认并启用不可变 TradePlanVersion

**What to build:** 让用户基于冻结研究和数据创建交易计划草稿、查看完整内容与版本差异，并通过显式“确认并启用”形成不可变 TradePlanVersion。平台保存的是用户决策规则而非建议或订单，未确认草稿不会影响当前 active 版本。

**Blocked by:** 04 — 生成并复用不可变 ResearchRun.

**Status:** resolved

- [x] 公共命令支持创建、更新和丢弃单一 open draft，并使用 expected revision 防止静默覆盖并发修改。
- [x] 草稿和确认页按依据与期限、规则、风险预算、市场门控组织，并显示完整内容、引用、diff、canonical hash、`user_fixture_input` 和“不会执行交易”的边界。（AC-011、AC-037）
- [x] 首次确认原子创建 TradePlan、不可变 v1、activation 和 transition；任一步失败都不留下半版本或半激活。（AC-012）
- [x] TradePlanVersion 固化 Security、baseline、ResearchRun/Evidence/DataSnapshot refs、期限、review date、完整规则、风险约束、政策版本、确认记录和内容 hash。
- [x] 规则使用受控 typed AST、metric catalog、单位和时间语义；接口拒绝自由执行公式、Python、SQL、JavaScript、prompt、订单或 broker payload。
- [x] 所有金额为有限、非负 exact decimal，币种匹配，最大计划损失不超过最大计划名义金额，期限有序；无 Position/account 时组合可行性和相关规则为 not_applicable/unknown。（AC-043）
- [x] active v1 上的 v2 草稿不改变 daily 评估版本；只有 v2 确认并启用成功后才原子切换，v1 内容、hash、activation 和既有引用保持不变。（AC-022 计划部分）
- [x] ended 是不可复活终态；继续相同内容必须经新草稿确认创建新的 TradePlan identity。（AC-023）
- [x] 从复权图产生的价格阈值只有在能保存 canonical 未复权 CNY exact value 和 factor 反算证据时才允许确认。（AC-026 计划部分）
- [x] 任何 rule 命中都不会自动 activate、deactivate、end 或产生交易副作用。

## Implementation Evidence

- `0005_market_trade_plan.sql` 持久化 TradePlan/Draft/Version、typed rule/condition、风险约束、冻结 refs、不可变 factor-set 反算证据、activation 与单调 transition；不可变历史由 trigger 和 FK/唯一约束保护。
- `PlanService` 经窄 `PlanRepository` port 编排草稿、确认投影和生命周期；SQLite adapter 只在 composition root 注入，公开 facade 提供逐命令 DTO、active/lifecycle 查询与 `get_plan_version_diff`。
- `plan-condition-ast@1` 支持 leaf/all/any/not、受控 metric/operator、typed constant、单位/币种/完整 session；账户依赖输入强制 `not_applicable/unknown`，复权阈值逐 condition path 绑定 immutable factor provenance。
- `python -m pytest tests/platform/test_trade_plans.py -q` -> `8 passed`，覆盖事务失败回滚、幂等、revision 冲突、v2 原子切换、ended 终态、重启恢复、AST/ref/risk/factor 反例。
- 完整验证：`python -m pytest -q` -> `96 passed`；`npm test --prefix web` -> `4 passed`；`npm run build --prefix web`；`python -m compileall -q src`；`git diff --check`。
- `code-review` 三轮修复后最终复审：Standards PASS；Spec PASS；无剩余 actionable finding。
