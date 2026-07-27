# 审计当前投研 MVP 与可复用边界

Type: `task`
Mode: `AFK`
Status: `resolved`

## Question

以当前 Git checkout 和未提交修改为事实源，完整审计现有股票投研报告 MVP 的真实架构、入口、数据流、输入输出、缓存/产物、失败路径、测试 seam、脚本和遗留 validator，回答：哪些能力可直接复用，哪些需要 adapter，哪些不得带入平台运行时，第一条纵向切片能在何处最小接入而不复制或破坏 `ResearchEngine.run(ResearchRequest) -> ResearchRun`？审计必须用代码位置、行为测试或可复现运行支撑，并产出唯一当前事实审计 `current-product-state-audit.md`；不得只复述 README，也不得把未来设计写成已实现事实。

## Answer

已完成审计资产：[当前股票投研 MVP 实现审计](../../../current-product-state-audit.md)。

结论是当前 checkout 已形成一个可直接复用的确定性研究深模块，唯一外部 seam 为：

```python
ResearchEngine.run(ResearchRequest) -> ResearchRun
```

第一条纵向切片必须在该 seam 外新增 snapshot-to-request adapter：平台负责标的解析、Provider 增量同步、raw/normalized snapshot 和 request 组装；研究引擎保持无 I/O，并在一次调用中返回 canonical `ResearchRun`；平台随后原样持久化 JSON，把 HTML 登记为同一运行的派生 artifact。不得复制 evidence、capability、method、narrative 或 renderer implementation，也不得让数据库、Web 或计划模块直接调用内部函数。

直接复用范围：公共 request/run contract、evidence identity/time/estimate 分离、能力级降级、已实现的 observed/peer/history/DCF 计算、证据约束叙事、输出权限、HTML renderer，以及 35 项行为回归测试。需要 adapter 的范围：security master、Provider/raw ingestion、point-in-time snapshot、request assembler、research run repository、artifact publisher、统一平台 control plane 和 Web read adapter。

不得带入平台运行时的内容：Skill/LLM prompt、固定 23 字段的遗留全局 source gate、Excel/旧 HTML validator 作为状态机、`outputs/*/work` 公司专用生成脚本和目录协议、未验证的 Kimi/estimate 数据、把 `conditional_plan` 冒充 `trade plan`、把静态 stock chart 冒充 K 线标注、把当前 `run_id` 冒充 workflow journal，以及任何真实自动下单。

关键缺口已确认：当前没有 Provider、增量缓存、数据库/迁移、workflow journal、artifact manifest、K 线交互/标注、版本化交易计划、市场状态规则评估或统一平台维护入口。历史 `outputs/` 被 Git 忽略且没有 schema/索引，不是产品存储层。

最高风险是双重 manifest 权威：活跃 `source-manifest.md` 仍要求固定 23 字段 legacy validator 先行，而当前核心采用 capability-level degradation；同一输入可能在外层 total fail、在核心 `completed_with_limits`。遗留 validator 的 raw path/hash 检查应迁入 ingest integrity 或核心 implementation，但其全局字段门禁不得保留。当前 `build_evidence()` 本身不读取 raw 文件、不校验 SHA-256、也不鉴别声明为 official 的发布者，这必须由后续数据契约解决。

可复现证据：

- `python -B -m unittest discover -s tests -v`：35/35 通过；
- 意华 `assess`：`rr_24636f6a962f2242`、`completed_with_limits`、`report_mode=professional`、0 integrity errors、正式每股估值权限关闭；
- legacy source validator：pass fixture 23/23、退出 0；fail fixture 65 errors、退出 1；
- legacy model validator：valid workbook 通过；`WACC=2% <= g=3%` 以 `DCF_WACC_NOT_GREATER_THAN_G` 失败；
- legacy report validator：data-insufficient fixture 6/6 结构检查通过；
- 当前 `src/tests/scripts/pyproject` 对所有 legacy validator/chart 脚本均无运行时引用。

新暴露事项均已被现有后续票据覆盖，无需新增 ticket：Provider/raw/hash/缓存由[调研数据 Provider、point-in-time 与增量缓存](03-research-data-providers-pit-and-cache.md)和[决定分层存储、时间语义与同步契约](07-decide-data-storage-and-pit-contracts.md)处理；`ResearchRun`、`WorkflowRun` 与 artifact store 关系由[决定 Codex 控制面、确定性运行时与 run journal 边界](08-decide-control-plane-runtime-and-run-journal.md)处理；最高层回归 seam 由[决定纵向切片最高层验收 seam](11-decide-vertical-slice-acceptance-seam.md)处理。
