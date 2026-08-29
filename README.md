# EquityTrack

EquityTrack 是面向单一用户、一个默认账户和单证券决策闭环的本地系统。当前公开路径只完成：账户确认与读取、宽松证据下的研究提交、确定性估值、风险约束的计划准备与用户确认、规则监控，以及 PROCESS/OUTCOME 两阶段复盘。它不自动下单，也不替用户给出证券行动建议。

当前事实状态是**合成通路已验证**；真实 Provider、真实来源和真实数据根未配置、未访问、未验证。

## 唯一路径

唯一控制面是 [`skills/SKILL.md`](skills/SKILL.md)。CLI、Skill 和测试都调用同一个 Application Interface：

- `account.confirm` / `account.show`
- `research.commit`
- `valuation.assess`
- `planning.prepare` / `planning.confirm`
- `monitor.evaluate`
- `review.commit`

CLI 适配器使用对应连字符命令，例如：

```powershell
python -m trading_platform.cli account-show --data-root <synthetic-root> --account-id account-orchid
python -m trading_platform.cli research-commit --data-root <synthetic-root> --input-file <request.json> --idempotency-key <key>
```

变更操作的输入文件由 Codex 在隔离临时目录中准备，用户不需要手工拼接内部请求。JSON 是即时标准响应；`--format markdown` 只生成不落地的只读投影。SQLite 文件 `decision-core.sqlite3` 是唯一持久化业务真值。

## 模块与权威

六个 deep Module 是 `evidence`、`portfolio`、`research`、`valuation`、`planning` 和 `review`；`monitor` 只是 application workflow。AI/Skill 负责研究含义、反方、证伪条件、不确定性和复盘判断；Python 负责确定性校验、计算、事务和持久化；用户确认账户事实和最终 TradePlan。

开发和当前验收只使用明确虚构的 Fixture Adapter 与临时数据根。没有配置真实 Provider，没有访问或迁移真实数据，也不能从合成结果推断真实通路已经验证。

## 验证

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
python -X utf8 -B -m pytest -q
```

产品、架构与验收基线见 [`docs/decision-core.md`](docs/decision-core.md)，领域词汇见 [`CONTEXT.md`](CONTEXT.md)，操作规则见 [`AGENTS.md`](AGENTS.md)。
