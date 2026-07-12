# 08 — 从故障检查点安全恢复 WorkflowRun

**What to build:** 让平台在 object、数据库、cursor、node 或 final manifest 边界发生崩溃后，能够验证已有记录并从最后一个合法检查点恢复。恢复必须复用已提交结果、递增 attempt、拒绝损坏或版本不兼容状态，并且永远不制造半 cursor、重复领域版本或缺失对象引用。

**Blocked by:** 07 — 构建 MarketSnapshot 并执行 PlanEvaluation.

**Status:** resolved

- [x] WorkflowRun、node 和 attempt 使用 owner token、lease expiry、heartbeat 和单调 transition history；历史 attempt/transition 不被覆盖或删除。
- [x] resume 取得合法 lease，将过期 running attempt 标记 abandoned，并逐节点校验 workflow/node/schema/fingerprint、checkpoint manifest 和 object hashes。
- [x] 已成功或复用且 checkpoint 完整的 node 不重算；未提交 node 创建递增 attempt 后继续。
- [x] temp write、object rename、数据库登记、cursor 推进、node success 和 final manifest commit 各边界都有 crash injection，恢复后只留下 temp/orphan 或完整 committed 引用。（AC-027）
- [x] cursor 只与数据、质量、object 和成功状态在同一事务安全推进；恢复不会产生半 cursor、重复 normalized/version/snapshot/market/evaluation。
- [x] stale lease 的第二 owner 返回稳定 busy 错误和当前 run ref；同一 data root 不允许并行 mutation/maintenance writer。（AC-028）
- [x] 旧 node version 不可用、artifact 缺失或损坏、hash mismatch、schema drift、PIT/质量 blocking 和领域不变量错误均 fail closed，不能在原 run 中半程换代码。（AC-028）
- [x] 可重试网络、rate limit 和 SQLite busy 使用有界策略并保留每次 attempt；不可重试错误不被掩盖为 limits success。
- [x] cancellation 只在节点事务边界生效，不回滚已经提交的不可变历史。
- [x] invocation 重放、响应丢失和 resume 组合测试证明不会重复推进 cursor、调用研究引擎或生成重复领域版本。（AC-017 恢复部分）

## Implementation Evidence

- `migrations/0007_workflow_recovery.sql` adds durable owner/lease/heartbeat metadata, immutable request and recovery journals, monotonic history guards, and sealed manifest/object history.
- `WorkflowRepository` and `ResearchWorkflowService` implement writer-locked lease acquisition, periodic heartbeat renewal, expired-attempt abandonment, persisted-request verification, checkpoint/object/domain revalidation, cancellation boundaries, and bounded transient retries with monotonic attempts.
- Object, cursor, node-success, research-response, and final-manifest crash hooks are exercised by `tests/platform/test_workflow_recovery.py`, including live-owner contention, slow-call heartbeat, request mismatch, schema/version/fingerprint drift, missing/corrupt objects, quality/domain blocking, and response-loss replay.
- Targeted recovery and workflow tests passed: 44 tests. Full Python suite passed: 127 tests. Frontend tests passed: 4 tests; production build passed. Python compilation and `git diff --check` passed.
- Independent code review from fixed point `5ba57e6`: Standards PASS and Spec PASS after all valid findings were fixed and reverified.
