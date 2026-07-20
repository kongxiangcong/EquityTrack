# 11 — 让 WorkflowLedger 成为唯一 Workflow persistence owner

**What to build:** 在不改变当前用户可见 WorkflowRun 行为和数据库 schema 的前提下，让纯领域 `ArtifactLineage.validate` 统一验证 frozen evidence 与 artifact graph，让 `WorkflowLedger` 原子拥有 workflow state、lease、checkpoint、object、artifact、manifest、reference 与恢复事务。现有研究工作流和 workspace 通过 typed Ledger contract 继续完成 create、replay、resume 与 inspection；旧 repository、跨 seam SQL、connection escape 和对应私有测试在本票内删除。

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] `ArtifactLineage.validate` 在无 SQLite 环境下验证 typed frozen evidence、artifact roles、identity edges、manifest completeness、tamper 与 exact replay invariants。
- [x] `WorkflowLedger` 是 WorkflowRun aggregate 的唯一 persistence owner，完整拥有 create/load、transition、lease、heartbeat、checkpoint、object registration、artifact edges、manifest、references、replay 与 recovery。
- [x] durable object 流程固定为 temporary write、flush、hash、atomic rename，再由单一 immediate transaction 提交 object、artifact、edge、manifest、reference 与 state transition。
- [x] crash 或 injected object/database failure 最多留下可审计的 unreferenced object；不得留下 committed dangling reference、partial manifest 或跨 aggregate 半提交状态。
- [x] 当前 Research Workflow 与 workspace caller 已完整迁移到 typed Ledger contract；除 owning persistence/migration/corruption tests 外，application、CLI、Web 和 domain 不再访问 workflow tables、raw connection 或 object store。
- [x] 旧多方法 repository、独立 object registration、重复 artifact-role mapping、nonrecoverable lifecycle、root repository exposure 与 forwarding API 已删除并搜索清零。
- [x] 旧 direct-SQL application tests 被 public workflow journey tests 或 owning Ledger adapter tests替换；未为了测试新增 public storage seam。
- [x] failure matrix覆盖 busy、lease、fingerprint、definition、checkpoint、object、collision、integrity、concurrent writer、transaction rollback、restart、corruption 与 doctor audit，并保留稳定 typed code 和 redacted substep evidence。
- [x] existing schema、WorkflowRun identity、ResearchRun identity、artifact bytes 与 manifest identity 保持不变；不得新增 shadow schema、dual write、repository adapter 或 connection fallback。
- [x] lineage、ledger、workflow create/replay/recovery、outlook artifacts、forecast review 与 backup/restore suites 全部通过，且静态依赖 guard 证明 storage ownership 唯一；本票以一个 commit 完成替换与删除。

## Implementation Evidence

- Canonical interfaces: pure `ArtifactLineage.validate` owns typed frozen-evidence and graph validation; application-owned `WorkflowLedgerPort` associates typed commands/queries with typed results; `WorkflowLedger` alone owns workflow, object, artifact, manifest, reference, replay and recovery persistence.
- Atomicity: Windows publication uses `MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH)`; POSIX publication fsyncs the renamed file and parent directory. Start, projection, research checkpoint, forecast review, failure and finalization publish before an explicit `BEGIN IMMEDIATE`, then commit each aggregate once.
- Failure evidence: injected projection, research artifact, forecast review and finalization failures prove rollback of database rows, manifests, refs, reuse decisions and terminal state; lease, busy writer, fingerprint/definition, collision, integrity, restart, corruption and doctor paths remain covered.
- Cleanup: deleted `workflows/repository.py`, `persistence/objects.py` and the application-side raw-SQL workspace module; retired repository/object-store symbols, compatibility payload reader, tuple-shaped research rows and cross-owner `object_blob` reads search clean. Static AST guard scans all non-owner modules, including persistence modules other than the ledger and migrations.
- Static verification: `python -m compileall -q src tests`; focused `pyflakes`; `python -m mypy src/trading_platform/application/workflow_ledger.py src/trading_platform/workflows/research.py src/trading_platform/data/repository.py src/trading_platform/persistence/workspace.py --follow-imports=skip --ignore-missing-imports` -> `Success: no issues found in 4 source files`; `git diff --check` clean apart from line-ending notices.
- Full verification: `python -m trading_platform.cli test --repo-root .` -> passed in 136.917s: core 192 passed; platform-1 41 passed and 3 skipped; platform-2 46 passed; platform-3 52 passed and 1 deselected; platform-4 79 passed; Web passed with 0 skipped. The 3 skips are workbook adapter cases explicitly gated because the bundled artifact runtime is not configured; Ticket 11 does not require workbook generation or zero skips.
- Review: final Spec review reported no actionable P1/P2 finding. Final Standards review confirmed the Ticket 11 durability, typing, ownership, compatibility and workspace fixes; its sole remaining note concerns the pre-existing dirty `AGENTS.md` cleanup-priority edit, which is outside this ticket and is explicitly excluded from staging and commit.
