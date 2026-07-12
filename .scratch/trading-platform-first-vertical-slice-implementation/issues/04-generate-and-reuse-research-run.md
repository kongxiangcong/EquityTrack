# 04 — 生成并复用不可变 ResearchRun

**What to build:** 让公开工作流在 2026-07-07 cutoff 上真实生成 ResearchRun，并在 2026-07-11 更新中根据冻结输入和版本化政策判断复用或新建。用户能够看到原始 cutoff、陈旧度、候选新数据、排除理由和产物身份，而不会得到一个被改写日期或复制内容的伪研究运行。

**Blocked by:** 03 — 授权同步并冻结 PIT DataSnapshot.

**Status:** resolved

- [x] 版本化 workflow registry、node contract、journal、transition、attempt、typed ref 和 checkpoint manifest 通过同一个 ApplicationFacade 运行。
- [x] 2026-07-07 ResearchRun 由公开 workflow 和真实 ResearchEngine seam 生成，不直接 seed 结果或绕过研究门禁。（AC-003）
- [x] snapshot-to-request assembler 只翻译冻结 research projection，并完整保留来源权威、期间、scope、单位、币种、scale、重述、稀释股本和净债务桥身份。
- [x] adapter 对相同 canonical request 的 schema、hash、capability 和 valuation permission 与既有 CLI/core 等价；异常单位、币种、期间、来源或桥接输入 fail closed，权限只能保持或降低。（AC-034、AC-039）
- [x] canonical ResearchRun JSON 与 HTML 作为独立、不可变 artifacts 发布；失败 attempt 只登记诊断，不能产生空壳 ResearchRun。
- [x] 2026-07-11 工作流保留 2026-07-07 research snapshot，并另建 2026-07-10 workflow/market snapshot；两者 purpose、cutoff 和 membership 不被合并。（AC-040）
- [x] routine market-only 数据不改变 research fingerprint 时复用原 ResearchRun identity、request、snapshot 和 artifact hashes，记录三日陈旧度与 reason，且不调用研究引擎或伪造 7 月 10 日 ResearchRequest。（AC-008）
- [x] 研究相关输入或政策真实变化时生成新的 research snapshot、request 和 ResearchRun，旧记录和旧 artifacts 保持可回放。
- [x] 同一 invocation 重放返回原 WorkflowRun；新 invocation 新建 run/attempt，但可复用相同 snapshot、ResearchRun 和 manifests。（AC-017 工作流部分）
- [x] 公共查询可遍历 WorkflowRun、两个 DataSnapshot、ResearchRun、attempts 和 ArtifactManifest，并区分 created 与 reused。（AC-015 部分）

## Implementation Evidence

- `tests/platform/test_research_workflow.py`: 17 passed；覆盖公开 ResearchEngine seam、完整 canonical core 等价、PIT/语义 mutation matrix、market-only 复用、research-relevant 新建、失败诊断、公开 history/manifest 查询与质量传播。
- 完整回归：`python -m pytest -q` => 76 passed。
- 静态卫生：`python -m compileall -q src` 与 `git diff --check` 通过。
- code-review Standards 与 Spec 双轴最终复审均 PASS；成功发布由单个 SQLite finalize transaction 提交 ResearchRun、manifests、refs、reuse decision、node/workflow terminal state。
- `git check-ignore -v docs/data docs/data/private-example.csv` 命中 `.gitignore:11:docs/data/`；未暂存个人同花顺数据。
