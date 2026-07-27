# 决定 Codex 控制面、确定性运行时与 run journal 边界

Type: `grilling`
Mode: `HITL`
Status: resolved
Blocked by: 02, 05, 07

## Question

在“Codex 是控制面、业务运行时无 LLM API/分析 prompt、用户不手工执行零散 CLI”的硬约束下，第一条纵向切片应如何划分统一维护入口、应用 facade、现有 `ResearchEngine`、Provider adapters、确定性计划规则、Web UI、workflow registry、run journal 与 artifact store？需要确定 `bootstrap / doctor / migrate / sync / daily / serve / test / backup / restore` 中本切片必须真实支持的最小集合、节点 typed I/O/版本/缓存键/失败恢复语义、`ResearchRun` 与 `WorkflowRun` 的关系，以及重复执行和中断恢复的验收方式。

## Comments

- 第一个 grilling 问题直接采用推荐答案：Codex 只作为进程外控制面，负责读取 Skill/结构化结果、选择并调用稳定维护入口，不进入业务进程、不被 Web 回调，也不把自然语言 prompt/API 注入运行时。根维护入口 `scripts/platform.py` 与本地 Web 都只是 driving adapters，共同调用进程内 `ApplicationFacade`；facade 是唯一应用命令/查询边界，内部才可调用 workflow registry、Provider ports、snapshot assembler、`ResearchEngine` adapter、确定性市场/计划服务、repositories 与 artifact publisher。CLI/Web 禁止绕过 facade 直接访问 `ResearchEngine`、Provider 或 SQLite；Web 也禁止以 subprocess 拼接 CLI。
- 第二个 grilling 问题直接采用推荐答案：第一切片运行时是一个纯 Python 模块化单体，单进程协调 SQLite 单 writer 与内容寻址 object store；不引入 Celery/Redis、消息队列、微服务、Notebook 生产路径或 Agent/LLM workflow framework。模块边界按 application facade、workflow、data/provider、research adapter、market/plan、persistence/artifacts、web adapters 划分。现有 `ResearchEngine.run(ResearchRequest) -> ResearchRun` 保持无网络/数据库 I/O 的深模块；平台只通过 snapshot-to-request adapter 组装不可变 `ResearchRequest`，调用一次后通过 repository/publisher 持久化结果，任何模块不得调用其内部 evidence/valuation/renderer 函数。
- 第三个 grilling 问题直接采用推荐答案：总任务 Prompt 已把 `bootstrap / doctor / migrate / sync / daily / serve / test / backup / restore` 设为统一入口最低能力，因此第一切片九项全部必须真实支持，不能留 no-op/TODO；只缩小作用域。`bootstrap` 创建本地 data root/非秘密配置并调用迁移、可重复执行；`doctor` 只读检查 Python/SQLite WAL 修复门、路径/权限、schema/hash/FK/object 完整性、配置与 Provider readiness；`migrate` 执行不可变 SQL ledger 和 backup-first 升级；`sync` 对明确 Security/dataset/cutoff 做增量或 offline 同步；`daily` 执行一次版本化日常复合工作流；`serve` 在 loopback 启动本地 Web 且不隐式联网；`test` 从稳定入口运行分层测试并原样传播退出码；`backup` 生成并验证一致性 bundle；`restore` 先恢复到新 data root、全量校验后才允许显式切换。每项 stdout 返回带 `operation/workflow_run_id/status/error_code/artifacts` 的结构化摘要，stderr 只用于脱敏诊断，失败非零退出。
- 第四个 grilling 问题直接采用推荐答案：workflow registry 是代码内、带稳定 ID/definition version 的确定性注册表，不是用户可编辑 YAML、prompt 或运行时插件下载器。第一切片注册 `sync_security_snapshot@1` 与 `watchlist_update@1`；Web“更新至今天”和 `daily` 复用后者，只以 trigger/source、目标 Security、请求日、online/offline、force-refresh 和是否存在可评估计划为 typed 输入差异。最小节点序列为 `resolve_effective_session -> sync_required_datasets -> build_data_snapshot -> decide_research_reuse -> run_or_link_research -> build_market_snapshot -> evaluate_confirmed_plans -> publish_run_manifest`，registry 可按 typed precondition 跳过不适用节点并记录原因。图表读取、标注编辑、计划草稿/确认是短 application commands，使用各自不可变版本/audit 表；不把一个 `WorkflowRun` 长时间挂起等待人操作。计划确认或 daily 可另起短评估 workflow，并通过引用把先前 annotation/plan/data/research 串联回看；完整用户旅程不等于一个长寿命 `WorkflowRun`。
- 第五个 grilling 问题直接采用推荐答案：每个 node definition 必须声明稳定 `node_id`、`node_version`、typed input/output DTO schema version、preconditions、cache policy、retry policy、failure codes 与是否为当前 capability 的 required node；跨节点只传小型不可变值和已持久化 identity/ref，不传隐含进程全局状态或可变大对象。node fingerprint/cache key 对 `workflow_definition_version + node_id/version + canonical typed input + DataSnapshot membership hash + provider/normalizer/source/freshness/query-policy versions + relevant config hash + deterministic code identity` 做 SHA-256；排除 wall-clock、run/attempt ID、绝对路径、明文秘密和展示选项。缓存命中必须重新校验 referenced object hashes/schema/policy，并在新 node attempt 中记录 `outcome=reused`、来源 run/node/output refs；它跳过计算但不跳过 journal。
- 第六个 grilling 问题直接采用推荐答案：`WorkflowRun` 使用每次明确执行唯一、非内容寻址的 ID，并另存 canonical `request_fingerprint`；同输入的有意重跑创建新 run，不能把历史合并。Web/CLI 每次用户动作生成 `invocation_id` 作为命令幂等键：响应丢失、双击或客户端重试携带同一 ID 时返回原 run；用户再次点击生成新 ID 与新 run。run 状态最小为 `queued / running / succeeded / succeeded_with_limits / failed / cancelled`；中断不是伪成功终态，恢复前仍是 running 并带 stale lease，恢复失败才转 failed。node 状态为 `pending / running / succeeded / skipped / blocked / failed`，attempt 结果为 `succeeded / reused / failed / abandoned`。`skipped` 必须有 typed precondition reason；required node 的 blocked/failed 使 run failed，只有明确 optional capability 的受限结果才允许 `succeeded_with_limits`。
- 第七个 grilling 问题直接采用推荐答案：run journal 是 SQLite 中用于审计与恢复的结构化 append-oriented 状态账本，不是 console log、JSONL 日志、产物目录，也不把整个业务域改造成 event sourcing。第一切片新增 `workflow_run`（invocation/request/workflow/version/trigger/cutoff/code-config-policy versions/status/lease/timestamps）、`workflow_node_run`（run/ordinal/node/version/required/input schema+hash/fingerprint/state/outcome/reason/output manifest）、`workflow_node_attempt`（attempt no/lease/start-heartbeat-finish/result/error code/retryable/diagnostic artifact）、`workflow_transition`（单调 sequence、entity、from/to、reason、at、attempt）和 `workflow_run_ref`（typed role、entity type/id、created-or-reused disposition）。状态字段可原位推进但每次推进必须同事务追加 transition，禁止删除/改写历史 attempt/transition。`doctor/test/serve` 不冒充 `WorkflowRun`；migration 由 `schema_migration` ledger 审计，backup/restore 由不可变 backup/restore manifest 审计，bootstrap 返回组合操作结果。人类可读/JSONL 诊断只作脱敏 artifact，不能决定恢复状态。
- 第八个 grilling 问题直接采用推荐答案：`ResearchRun` 不是 `WorkflowRun` 的子实体或别名，而是可被零到多个工作流创建/复用的不可变研究结果。现有核心的内容派生 `rr_*` identity 保留；平台新增薄 `research_run_record`，唯一登记 engine run ID、ResearchRequest fingerprint/schema、确切 `data_snapshot_id`、research engine/schema/code identity、原始 research cutoff/status、canonical JSON artifact、HTML artifact 与 created_at。组装后的 ResearchRequest 也以脱敏 canonical artifact/hash 保存。`run_or_link_research` 命中相同确定性输入时不调用引擎，只在本次 `workflow_run_ref(role=research_run, disposition=reused)` 和 node attempt 中记录复用理由；输入变化时调用一次并登记新记录/artifacts。工作流请求日或有效交易日不得覆盖 `ResearchRun.as_of_date`；失败且没有合法 `ResearchRun` 时只记录 failed attempt/diagnostic，不生成空研究结果。
- 第九个 grilling 问题直接采用推荐答案：`ArtifactManifest` 既是成功节点的恢复 checkpoint，也是 run 终态的完整目录；不是可变“当前文件列表”。在 issue 07 的 `artifact`/`artifact_relation` 上新增 `artifact_manifest`（manifest kind、schema version、canonical membership hash、workflow/node/attempt/checkpoint sequence、created_at）和 `artifact_manifest_member`（ordered role、artifact id、input/output/diagnostic direction、producer、media/schema/hash）。产物严格按同卷 temp -> flush/fsync/hash -> `os.replace` -> 短 SQLite 事务顺序发布；同一事务登记 object/artifact、不可变 manifest/members、typed output refs、node succeeded/reused 和 transition。终态 run manifest 只汇总已提交 checkpoint 与必要诊断；manifest 成员 hash/顺序决定 identity。失败 attempt 可发布脱敏诊断 artifact，但不能冒充成功 checkpoint；orphan object 可回收，committed manifest 的 missing/hash mismatch 必须让 doctor/resume fail closed。
- 第十个 grilling 问题直接采用推荐答案：增加稳定 `resume --run-id` application/maintenance command（Web 历史页可触发，用户无需手拼命令）。每个 running run/attempt 持有单 owner token、lease expiry 与 heartbeat；进程死亡后，resume 先以短事务取得新 lease并将过期 attempt 标为 `abandoned`，再按 journal 顺序验证 checkpoint 的 workflow/node/schema/fingerprint 与全部 object hashes。验证通过的 succeeded/reused node 不重跑；无 committed checkpoint 的节点创建递增 attempt。恢复必须能加载原 workflow definition 与 node versions；版本不可用或输入/checkpoint 损坏时原 run fail closed，用户/Codex只能创建显式关联的新 run，禁止半程换代码。网络超时、rate limit、SQLite busy 等仅按代码内有界策略重试并尊重 Retry-After；schema drift、PIT/质量 blocking、hash mismatch、未知版本和领域不变量错误不可重试。cancel 只在节点事务边界生效，不回滚已提交节点；Provider cursor、artifact refs 与 node success 必须同事务提交，确保重试不会重复推进或产生重复业务版本。
- 第十一个 grilling 问题直接采用推荐答案：区分 execution failure 与 governed degraded result。Provider partial/missing、无 cutoff 合法缓存、数据陈旧或计划规则输入缺失时，节点若能持久化 typed freshness/gap/result（例如 MarketSnapshot capability blocked、PlanEvaluation `blocked`/`unable_to_determine` 及逐条原因），则节点执行成功但 outcome 带 limits，run 为 `succeeded_with_limits`；不得伪装为当日完整快照或已完成交易判断。只有 contract/schema/hash/PIT/identity 不变量破坏、required definition/version 不存在、数据库事务或 artifact publish 无法完成，才是 node/run `failed`。旧 ResearchRun 的历史回看和明确陈旧复用可继续；陈旧 OHLCV 不允许生成“当日正常”MarketSnapshot。fallback/降级决策、被排除来源和 capability permission 必须进入 run refs/manifest，不能只写日志。
- 第十二个 grilling 问题直接采用推荐答案：结构化 journal、诊断日志和用户历史视图严格分离。journal 只保存受控状态、版本、fingerprints、时间、稳定 error/reason codes 和 typed refs；append-only JSONL/文本诊断经脱敏后作为 artifact，可删除展示副本但不能替代 journal；历史页通过只读 query facade 从 journal、domain version tables 与 manifests 拼装，不直接扫文件夹。明文 token/cookie/header、credential scope 内容、个人绝对路径、未脱敏请求参数和持仓隐私不得进入 DB、stdout/stderr、artifact 或 Web 错误；只保存不可逆 `credential_scope_id` 与安全摘要。日志时间统一 UTC，同时按需展示市场时区；所有用户可见错误必须能从稳定 code 追溯到确切 run/node/attempt，而不暴露秘密。
- 第十三个 grilling 问题直接采用推荐答案并清除 map 的备份 fog：第一切片真实 backup 是用户/Codex 指定目标目录中的 timestamped immutable bundle，包含 SQLite online backup、由冻结副本枚举出的全部 referenced objects、版本化 `backup_manifest.json`、schema/app/config-safe versions 和逐项 SHA-256；目标在 live data root 内直接拒绝，同卷仅警告灾难隔离不足。restore 永不覆盖活跃 root：解包到新 root，执行 hash、SQLite integrity/FK/schema/domain、最小查询与 journal/artifact referential checks，生成不可变 restore report 后才允许显式切换配置。第一切片不自动上传云端、不自动轮换/删除备份、不自建加密密钥管理；默认永不自动删除，敏感备份依赖用户控制的受限目录/BitLocker 或等价加密卷，并在 doctor 中提示。恢复演练由 fixture E2E 强制覆盖；介质生命周期和异地灾备是后续运维范围，无需新增 Wayfinder ticket。
- 第十四个 grilling 问题直接采用推荐答案：重跑验收必须证明同一 `invocation_id` 的重试只返回同一 WorkflowRun；新 invocation 在相同 cutoff/input 下创建不同 WorkflowRun/node attempts，但复用相同 raw objects、normalized versions、DataSnapshot、ResearchRun 和同一 `plan_version + market_snapshot + evaluator_version` 的 PlanEvaluation，不重复推进 cursor或生成领域版本；freshness 命中仍记录 `cache_hit/reused`。恢复测试在 temp write、object rename 前后、DB commit 前后、cursor commit、node success、final manifest 前后注入进程崩溃，随后 resume，断言只有 temp/orphan或完整引用、attempt 单调增加、已完成节点不重算、最终 manifest 完整。另测 stale lease 双 owner 排斥、不可用旧 node version、corrupt/missing object、retryable/nonretryable 分类、offline stale/missing、backup->new-root restore->history replay、Windows rollback-journal 单 writer、九项入口退出码/JSON contract、现有 35 项回归，以及静态/运行测试证明业务包无 LLM SDK/API/prompt 与券商执行路径。
- 第十五个 grilling 问题直接采用推荐答案：第一切片明确单 data-root 单 mutating workflow/maintenance writer。Web 进程用串行 application command queue；跨进程用 data-root scoped OS lock 加 DB lease/owner token 排斥，网络等待期间不保持 SQLite transaction，但仍保持可心跳的 workflow ownership。只读 Web/query/doctor 的非锁检查可并行；第二个 mutation 返回结构化 `RUNTIME_BUSY` 与当前 run ref，不等待到未知超时，也不偷偷并发。`migrate`、restore 验证后的切换和会改变 schema/root 的 bootstrap 步骤取得独占 maintenance lock，并要求没有 live server/workflow；`serve` 启动只绑定 `127.0.0.1` 的配置端口、默认不联网，重复启动返回已有健康地址或 `RUNTIME_BUSY`。SQLite 写事务保持短小，避免把全工作流锁误写成数据库长事务。

## Answer

第一条纵向切片采用“**Codex 外部控制面 + 统一 application facade + 纯 Python 确定性模块化单体 + SQLite run journal + 内容寻址 artifact store**”。这是一份实现阶段必须遵守的边界决策，不代表平台代码已经存在。

### 1. 调用与模块边界

```text
Codex / local Web
        |
scripts/platform.py or Web adapter
        |
ApplicationFacade  <- only command/query boundary
        |
WorkflowRegistry + WorkflowRunner
  | Provider ports / snapshot assembler
  | Research adapter -> ResearchEngine.run(ResearchRequest) -> ResearchRun
  | deterministic market / plan services
  | repositories + artifact publisher
        |
SQLite authority + SHA-256 immutable object store
```

- Codex 负责在业务进程外选择并调用入口、读取 Skill 和结构化结果；业务运行时不得调用 Codex/LLM API，也不得保存分析 prompt。
- `scripts/platform.py` 和 Web 是同级 driving adapters，均调用 `ApplicationFacade`；Web 不以 subprocess 拼 CLI，CLI/Web 不绕过 facade 直接访问 Provider、数据库或研究内核。
- 现有 `ResearchEngine` 保持无 I/O 深模块。平台只通过 snapshot-to-request adapter 输入冻结数据，通过 repository/artifact publisher 接收结果；不复制或穿透 evidence、valuation、narrative、renderer 内部实现。
- 第一切片保持单进程模块化单体，不引入微服务、队列、Celery/Redis、Notebook 生产路径或 Agent workflow runtime。

### 2. 统一入口的真实最低能力

总任务 Prompt 点名的九项全部是第一切片验收范围，不能是 no-op：

| command | 第一切片真实语义 |
|---|---|
| `bootstrap` | 幂等创建 data root 和非秘密配置，调用 migration，拒绝覆盖不兼容现有数据 |
| `doctor` | 只读检查 Python/SQLite WAL 修复门、路径/权限、schema ledger/hash、FK/integrity、object refs、配置与 Provider readiness |
| `migrate` | 在独占维护锁和已验证 backup 后执行不可变 SQL migrations，失败保留旧库并 fail closed |
| `sync` | 对明确 Security/datasets/cutoff 执行增量或 offline 同步，形成受版本/质量约束的 DataSnapshot |
| `daily` | 执行 `watchlist_update@1`，记录请求日/有效交易日、同步、研究复用、市场状态和可用计划评估 |
| `serve` | 只绑定 loopback，启动本地 Web；启动本身不联网、不自动同步 |
| `test` | 通过稳定入口运行分层测试，保留真实退出码和结构化摘要 |
| `backup` | 生成并校验 SQLite frozen copy + referenced objects + hash manifest 的一致性 bundle |
| `restore` | 恢复到新 data root，完整校验并生成 restore report，只有显式动作才切换活跃 root |

另增 `resume --run-id` 作为恢复入口。所有入口 stdout 输出稳定 JSON envelope，至少含 `operation`、适用时的 `workflow_run_id`、`status`、`error_code` 与 artifact refs；失败返回非零。用户不需要记忆或手动拼这些命令，由 Codex 或 Web 触发。

### 3. Registry、节点与 typed contract

workflow registry 是代码内、版本化、可测试的确定性定义，不是 prompt、用户 YAML 或在线插件系统。第一切片至少注册：

- `sync_security_snapshot@1`：解析有效交易日、增量同步、质量校验、冻结 DataSnapshot；
- `watchlist_update@1`：`resolve_effective_session -> sync_required_datasets -> build_data_snapshot -> decide_research_reuse -> run_or_link_research -> build_market_snapshot -> evaluate_confirmed_plans -> publish_run_manifest`。

Web“更新至今天”和 `daily` 共享 `watchlist_update@1`。标注编辑、计划草稿和确认是短 application commands，以各自不可变版本/audit 记录持久化；不让一个 WorkflowRun 跨越用户思考时间长期等待。一次完整用户旅程可以链接多个短 workflow/command，不能把它误称为一个长寿命 WorkflowRun。

每个节点必须声明稳定 node/version、typed input/output schema、precondition、required/optional capability、cache/retry policy 和稳定 failure codes。跨节点只传小型不可变值或持久化 identity/ref。缓存 fingerprint 对 workflow/node version、canonical typed input、DataSnapshot membership hash、Provider/normalizer/source/freshness/query-policy versions、相关配置 hash 与确定性代码身份做 SHA-256；不得包含 wall clock、run/attempt ID、绝对路径、明文秘密或纯展示选项。缓存命中仍创建本次 node attempt，并记录 `reused` 来源和理由。

### 4. WorkflowRun 身份与 run journal

- `WorkflowRun` 每次明确执行生成唯一、非内容寻址 ID，并另存 `request_fingerprint`。
- 同一 `invocation_id` 的双击、断线重试或响应重放返回原 run；新的明确执行使用新 invocation/run，即使业务输入相同。
- run 状态：`queued / running / succeeded / succeeded_with_limits / failed / cancelled`。
- node 状态：`pending / running / succeeded / skipped / blocked / failed`；attempt 结果：`succeeded / reused / failed / abandoned`。
- `skipped` 必须有 typed precondition reason。数据缺失等受控结果与执行失败分开：能产出结构化 staleness/gap/blocked evaluation 的运行是 `succeeded_with_limits`；契约、hash、PIT、schema、持久化或版本不变量破坏才是 `failed`。

在 issue 07 的数据表基础上，第一切片新增：

| table | 责任 |
|---|---|
| `workflow_run` | invocation、request fingerprint、workflow/version、trigger/cutoff、code/config/policy versions、状态、lease、时间 |
| `workflow_node_run` | 顺序、node/version、required flag、input schema/hash、fingerprint、状态/outcome/reason、output manifest |
| `workflow_node_attempt` | attempt no、owner/lease、start/heartbeat/finish、result、stable error code、retryability、diagnostic artifact |
| `workflow_transition` | 单调 sequence 的 from/to/reason/at/attempt 历史 |
| `workflow_run_ref` | 以 typed role 链接 DataSnapshot、ResearchRun、MarketSnapshot、PlanEvaluation、annotation/plan refs，标记 created/reused |
| `artifact_manifest`, `artifact_manifest_member` | 不可变 node checkpoint 与 final run 产物目录、成员顺序/角色/schema/hash/producer |
| `research_run_record` | engine run identity、request fingerprint/schema、DataSnapshot、engine/code version、原始 cutoff/status、canonical JSON/HTML artifacts |

状态行可以推进，但每次推进必须同事务追加 transition；attempt/transition 不得删除或改写。console/JSONL 诊断不是 journal 权威，只能是脱敏 artifact。`doctor/test/serve` 不冒充 WorkflowRun；migration、backup 和 restore 分别由 schema ledger、backup manifest、restore report 审计。

### 5. ResearchRun 与 artifact transaction

`ResearchRun` 是可被多个 WorkflowRun 创建或复用的不可变研究结果，不是工作流子实体。平台保持核心 `rr_*` identity，并额外登记它引用的 DataSnapshot、ResearchRequest artifact/fingerprint、研究引擎/代码版本、canonical JSON 与派生 HTML。工作流只通过 `workflow_run_ref(role=research_run, disposition=created|reused)` 引用；工作流请求日不得改写研究运行自己的 `as_of_date`。

每个成功/复用节点都有不可变 checkpoint manifest，终态另有完整 run manifest。提交顺序固定为：同卷 temp 写入 -> flush/fsync/hash -> `os.replace` 到内容地址 -> 短 SQLite 事务登记 object/artifact/manifest/output refs/node success/transition。失败 attempt 可以发布诊断 artifact，但没有成功 checkpoint。由此崩溃只可能留下 temp、可回收 orphan 或完整 committed 引用，不能留下“节点成功但产物缺失”。

### 6. 中断恢复、重试与并发

- 每个 running run/attempt 使用 owner token、lease expiry 与 heartbeat。`resume` 取得新 lease 后把过期 attempt 标记为 `abandoned`，逐节点验证 definition/version/fingerprint/schema 与 object hashes。
- 合法 checkpoint 的 succeeded/reused 节点不重算；未提交节点创建递增 attempt。原 workflow/node version 已不可用或 checkpoint 损坏时，原 run fail closed，只能创建显式关联的新 run，禁止半程换代码。
- 网络超时、rate limit、SQLite busy 等按代码内有界策略重试并尊重 `Retry-After`；schema drift、PIT/质量 blocking、hash mismatch、未知版本和领域不变量错误不可重试。
- cancel 只在节点事务边界生效，不回滚已提交历史。Provider cursor、artifact refs 与 node success 同事务提交。
- 第一切片采用单 data-root 单 mutating writer：Web 串行 mutation queue，跨进程使用 OS lock + DB lease；只读查询可并行。第二个写者返回 `RUNTIME_BUSY` 和当前 run ref。migrate/restore switch 等取得独占 maintenance lock；网络等待不保持 SQLite 长事务。

### 7. 备份、隐私与展示边界

backup 是用户/Codex 指定目录下的 timestamped immutable bundle。目标位于 live root 内直接拒绝，同卷告警隔离不足；restore 永不原地覆盖。第一切片不自动上传云端、不自动删除/轮换、不自建加密密钥管理；默认永不自动删除，敏感副本依赖受限目录和 BitLocker/等价加密卷，doctor 明确提示。

journal 只保存受控状态、版本、fingerprint、稳定 code 与 typed refs。明文 token/cookie/header、credential 内容、个人绝对路径和未脱敏请求参数不得进入 DB、stdout/stderr、artifact 或 Web 错误。历史页从 query facade 读取结构化 journal、领域版本表和 manifests，不扫描文件夹拼历史。

### 8. 强制验收

实现阶段至少必须证明：

1. 同 invocation 重试只返回同一 run；新 invocation 创建新 WorkflowRun，但相同输入复用 raw/normalized/snapshot/ResearchRun/确定性 PlanEvaluation，不重复推进 cursor 或创建领域版本。
2. 在 temp write、object rename、DB/cursor/node/final-manifest commit 前后注入崩溃；resume 后 attempt 单调增加、已完成节点不重算、无 missing object/半 cursor/重复业务记录。
3. stale lease 的第二 owner 被排斥；旧 node version 不可用、artifact 损坏、不可重试错误均 fail closed。
4. offline stale/missing 形成明确受限结果；不伪装当日完整 MarketSnapshot 或计划判断。
5. backup -> 新 data root restore -> history replay 全链路通过 hash、SQLite/FK/schema/domain 和 artifact referential checks。
6. Windows rollback-journal 单 writer、九项入口 JSON/退出码 contract、本地 Web loopback/不隐式联网均通过。
7. 现有 35 项研究回归继续通过，并以静态和运行测试证明业务包没有 LLM SDK/API/分析 prompt、券商连接或交易执行路径。

本票没有改变业务领域词义：`WorkflowRun`、`ResearchRun` 与 `ArtifactManifest` 的 glossary 边界保持不变；run journal、lease、facade 和 checkpoint 属于架构实现词汇，因此不修改 `CONTEXT.md`。控制面与运行时分离来自总任务硬约束而非新的可选权衡，本阶段也不单独创建 ADR。
