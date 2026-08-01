# 内部控制面与应用边界

本文件只供 Codex 执行和故障诊断；不得逐字转呈普通用户。主入口和默认呈现合同只在 `../SKILL.md`。

## 安全生命周期

用户任务打开数据根时先验证当前迁移集合。版本落后由应用生命周期自动执行：不可覆盖的完整备份 -> 写锁和运行时存在检查 -> 只向前迁移 -> doctor -> 重试原任务。任何一步失败都返回用户语言限制并保留内部类型化诊断；不得删除数据库、绕过迁移或直接修表。

初始化、显式诊断、同步、研究、备份和恢复仍通过唯一确定性维护适配器：

```powershell
python -m trading_platform.cli bootstrap --data-root <root>
python -m trading_platform.cli health --data-root <root>
python -m trading_platform.cli doctor --data-root <root>
python -m trading_platform.cli sync --data-root <root> --job-file <job.json>
python -m trading_platform.cli research --data-root <root> --request-file <request.json>
python -m trading_platform.cli backup --data-root <root> --archive <outside-root.zip>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <new-root>
```

这些命令由 Codex 调用，不是用户界面。不要让用户手动执行，也不要在默认结果中展示。

## 正式变更

所有正式业务变更只经过：

```powershell
python -m trading_platform.cli application-command --data-root <root> --envelope-file <command.json>
```

临时文件严格使用 `ApplicationCommandEnvelope@1`。应用校验版本、能力、actor、批准边界、规范请求 hash 和幂等回执。Skill 是 interaction channel，不是 decision actor；Codex 传输使用 agent actor，只有用户明确确认最终内容时才使用 user decision actor。

当前唯一命令注册表包括账户快照与风险政策确认、`trade_plan.prepare_draft@1`、计划挑战与确认、`manual_portfolio_review.run@2`、待处理事项处置、执行事实声明与修正、周期复盘草稿/确认、计划影响判断与修改提案。未注册命令失败关闭。不得直接 SQL 或文件写入，也不得把 Shell、路径、凭据、provider 目标、研究运行身份、趋势评估身份、策略版本或调用方构造的计划图放入正式 payload。

## 读取与呈现

读取只通过 `open_read_models(...)`、账户状态查询和单一 codec。Skill 可读取组合、持仓、计划、复核、研究索引、图表和账户编辑器的不可变内部投影，但默认只呈现主入口定义的用户字段。内部 schema 名、projection/source ID、hash、诊断和完整 provenance 只在用户要求“技术详情/来源/审计”时展开。

Web 复用相同读取与变更边界，只是可选查看器。Web 不得成为 Skill 任务前置条件，也不得拥有平行工作流。

## 数据源与凭据

仅接受 `ProviderJob@2`。生产组合固定 provider 目的地和 credential scope；进程环境是显式覆盖，否则从 Windows Credential Manager 的 `tradingSystem/TUSHARE_TOKEN` 读取。不得把凭据值写入文件、命令、日志、数据库、备份或产物。

Tushare-compatible 数据保留 `structured_aggregator` 身份，不视为官方披露。同步和资格检查共享 raw -> normalize -> quality/PIT -> persist 路径。真实源不可用时可以使用合格缓存或隔离 fixture 验证，但不能把 fixture、跳过或 timeout 报成真实同步通过。

## 研究和计划

正式研究只有：

```python
ResearchWorkflow.handle(StartResearchWorkflow(request)) -> ResearchWorkflowResult
```

检查持久化 manifest 后再报告产物，并通过 `open_research_publication(...)` 发布可打开的报告与图表。报告到计划只有 `trade_plan.prepare_draft@1`；调用方只提供用户可读的账户别名、证券代码、计划类型和请求时点，应用选择最新完整研究、绑定趋势、已确认账户、风险政策和活动内置策略，并保守地编译完整图。任何候选数量都保持待用户复核，不由应用推断。最终确认要求未过期、未消费且绑定精确修订的 challenge；确认不产生订单。