# 01 — 建立受保护的平台运行骨架

**What to build:** 让平台能够通过一个稳定的应用边界启动和接受健康检查，同时把既有研究内核保留为不可复制、不可绕过的深模块。这个切片建立后，后续能力可以沿同一个 composition root、命令/查询合同和确定性身份机制增量加入，而现有研究结果与金融门禁保持不变。

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] 生产 composition root 能创建唯一的 ApplicationFacade，并通过稳定、类型化的命令、查询、结果和错误合同被本地适配器调用。
- [x] 既有研究行为测试和估值 worked examples 原样通过，并被记录为后续每票都必须保持的回归基线。
- [x] 平台只通过公开 `ResearchEngine.run(ResearchRequest) -> ResearchRun` seam 访问研究能力，不复制研究、证据、估值、叙事或报告渲染逻辑。
- [x] 架构门禁拒绝平台导入研究内部模块，也拒绝业务依赖、资源和公共 surface 出现 Skill、分析 prompt、LLM SDK、券商、订单或交易执行能力。
- [x] 版本化 canonicalization 对 UTC 时间、日期精度、exact decimal、枚举、显式 null 和稳定成员顺序生成可重算身份，不受 locale 或字段顺序影响。
- [x] code identity 能区分 commit、dirty source/diff、锁文件、迁移集、工作流、前端和确定性配置变化；无随机节点明确记录 deterministic 与空 seed。
- [x] 平台运行骨架保持 Python 3.10 兼容，并能在尚未实现业务能力时以明确的 unavailable 状态响应，而不是伪造成功。

## Implementation Evidence

- `ProductionCompositionRoot` 缓存唯一 `ApplicationFacade`；`application-contract@1` 使用枚举化 command/query/result/error 合同，未实现能力返回 `CAPABILITY_UNAVAILABLE`。
- `ResearchAdapter` 只从 `equity_research` 包根导入并调用 `ResearchEngine.run`；architecture test 同时检查两类私有 import、依赖、资源与公共 surface denylist。
- `canonical-json@1` 覆盖 UTC instant、date precision、typed exact decimal、enum、null、稳定 mapping/set 成员，并拒绝 binary float、无时区 datetime 和非字符串 mapping key。
- `CodeIdentity` 记录 commit、source、lock、migration、workflow、frontend、config、package/build、model/policy 与 dependency/license hashes，以及 `random_seed=null`/deterministic basis。
- `tests/platform/regression_baseline.json` 固化 35 项 legacy suite 与显式 DCF worked example，并由测试校验 collection。
- 验证：`python -m pytest -q` -> `40 passed`；`python -m compileall -q src`；`git diff --check`；`git check-ignore -v docs/data docs/data/**`。
- `code-review` 最终复审：Standards PASS；Spec PASS；所有有效发现已修复并重新验证。
