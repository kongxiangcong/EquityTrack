# Goal Prompt：完成代码结构深模块改造 Wayfinder

在 `E:\workspace\tradingSystem` 中持续推进
`.scratch/code-structure-deepening/map.md`，直到该 Wayfinder map 的全部现有 child
issues，以及推进过程中从 `Not yet specified` 毕业出的新增 child issues，全部得到有代码
证据支撑的决策并标记为 `resolved`。本 Goal 的终点是形成一份可以直接进入
`/to-spec` 的完整架构决策，不实施生产代码重构。

## 每次 Goal 续轮的固定流程

1. 从仓库根目录工作。先读取当前 `AGENTS.md`、
   `docs/prompts/trading_platform_codex_prompt_optimized.md`、
   `docs/agents/issue-tracker.md`、`CONTEXT.md`、
   `.scratch/code-structure-deepening/map.md`，以及 `wayfinder`、
   `codebase-design`、`domain-modeling` 技能的完整说明。只读取当前票据需要的相关
   ADR；不存在时静默继续。
2. 扫描 `.scratch/code-structure-deepening/issues/`，依据本地 tracker 的
   `Status` 和 `Blocked by` 计算 frontier。若有多个 frontier，按文件编号取第一张。
3. 在进行任何调查前，先把选中票据的 `Status` 改为 `claimed`。并发会话已经认领的
   票据必须跳过。
4. 每次续轮最多解决一张票。不得在同一轮顺手解决下一张票，也不得提前实施生产代码。
5. 以当前 checkout 为事实源，使用 `rg`、公开导出、调用者、schema、artifact identity、
   测试和运行时合同取得证据。能从代码查清的事实不得询问用户。
6. 每张票只作一个架构决策。用户已给出持续授权：直接采用 Agent 基于证据给出的推荐
   答案作为最终选择，不因普通设计选择等待人工确认。若缺少不可推断的业务事实、需要
   新权限、会改变金融边界或会扩大 Destination，才停止并请求用户。
7. 使用 `module`、`interface`、`seam`、`depth`、`leverage`、`locality` 的统一词汇。
   推荐答案必须说明：目标 module 拥有什么完整行为；interface 包含什么；依赖指向；
   状态、副作用和 typed failure 归属；旧实现、旧导出、旧调用者和旧测试何时删除；
   如何通过删除测试证明它不是转发层。
8. 把完整答案追加到所认领票据的 `## Answer`，将其 `Status` 改为 `resolved`；随后只在
   map 的 `Decisions so far` 追加一行“票据名称链接 + 一句话结论”，不得复制详细答案。
9. 根据答案更新地图：已经清晰的问题从 `Not yet specified` 删除并建立新 child issue；
   新票据先创建，第二遍再写 `Blocked by`；确认超出 Destination 的内容进入
   `Out of scope`，已有误建票据应关闭而不是留在 frontier。
10. 完成当前票据后结束本轮，让 Goal 自动续轮重新加载地图和 frontier。不得依赖上一轮
    未写入 tracker 的隐含上下文。

## 不可违反的结构约束

- `AGENTS.md` 只保存长期约束，不得把本 Goal 的任务计划、进度或票据清单写回其中。
- 禁止胶水代码、旁路代码、兼容代码、service locator、镜像 Facade、双读、双写、旧新
  双路径和大爆炸式重写。
- 不能以减少行数或增加文件数作为答案。目标是小 interface 后隐藏完整行为的深 module。
- 只保护正式平台路径的可观察行为、领域语义、历史 artifact 可追溯性和持久化数据。
  私有接口、旧 V3/file CLI、重复脚本和旧渲染器在调用者迁移后直接删除。
- 数据库 schema 和 artifact identity 默认保持不变。确需改变时，只允许版本化、
  backup-first 的一次性迁移；迁移完成后不保留旧结构 fallback。
- 不新增研究方法、估值方法、交易功能、UI 功能或 Provider 能力，不提供个性化投资建议。
- 不修改 `src/`、`tests/`、Web 代码、schema 或生产文档；Wayfinder 阶段只写 map、child
  issues，以及确有必要的决策资产。不得创建实现原型，除非地图新增并明确批准 prototype
  票据。
- 保留工作树中与本 effort 无关的用户修改，不清理、不暂存、不提交它们。

## 完成条件

只有同时满足以下条件，Goal 才算完成：

- `.scratch/code-structure-deepening/issues/` 中没有 `open` 或 `claimed` child issue；推进中
  新增的票据也全部 `resolved`。
- frontier 为空不是因为错误阻塞；所有 `Blocked by` 指向的票据均已解决。
- `Not yet specified` 已清空，或每一项都已明确移动为 child issue 或 `Out of scope`。
- `Decisions so far` 按名称链接每一张属于路线的 resolved ticket，详细决策只存在于对应
  ticket。
- 决策完整覆盖 workflow persistence/lineage、workflow execution、forecast、scenario
  valuation、research decision view、application task interfaces，以及替换/删除/验证顺序。
- 最终迁移图能直接交给 `/to-spec`：每个目标 module 的 interface、职责、依赖、迁移
  blocker、旧代码删除条件、公开回归和数据迁移规则都已明确，不再有必须先回答的架构问题。
- 将 map 的 `Status` 更新为 `resolved`，最后报告地图已完成，并把唯一下一步写为
  `/to-spec .scratch/code-structure-deepening/map.md`。不要继续执行 `/to-spec`、
  `/to-tickets` 或 `/implement`。

如果只是调查困难、代码量大或需要更多时间，不得把 Goal 标记为 blocked；继续在后续轮次
处理。只有真正缺少用户权限、不可获得的外部事实或与长期约束发生无法自行解决的冲突时，
才报告精确阻塞证据。
