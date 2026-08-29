# 将工作流编排与六个领域模块分离

决策核心重构采用 `evidence`、`portfolio`、`research`、`valuation`、`planning`、`review` 六个领域模块；每个模块拥有自己的不变量和公开类型，跨模块流程由 application task 编排，`monitor` 只是应用工作流而不是第七个领域模块。模块不得访问彼此的 repository、表或私有函数，只能交换不可变类型化记录；Provider、SQLite、CLI 和 Markdown 都是外部适配器，持久化共用一个 SQLite、一个事务管理器和一条迁移路径。
