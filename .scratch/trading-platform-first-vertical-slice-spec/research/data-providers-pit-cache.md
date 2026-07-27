# A 股数据 Provider、point-in-time 与增量缓存研究

研究截至：2026-07-11
适用范围：个人、本地优先的第一条 A 股纵向切片；不覆盖商业再分发、全市场高频数据或完整回测数据采购。

## 结论

第一条切片不应寻找一个“万能 Provider”，而应采用按权威性分工的组合：

1. **官方披露 adapter family（adopt）**：CNINFO、SSE、SZSE、BSE 与上市公司 IR 用于公告、定期报告、公司行动和关键财务事实的原始证据；交易所/监管披露优先于公司 IR 镜像。
2. **Tushare Pro（adapt，optional）**：适合作为有 Token 且服务权限匹配时的结构化证券主数据、交易日历、日线、复权因子和财务索引 adapter；它不能替代官方披露，也不能成为第一条切片的必备凭据。
3. **AKShare（adapt，fallback/cross-check）**：适合作为无凭据行情、日历、市场宽度和来源发现的回退 adapter；不得将 MIT 客户端许可证误读为其上游数据的再分发许可，也不得把聚合财务值升级为官方事实。
4. **BaoStock（reference only）**：可作为日线、交易日历和复权结果的独立交叉核验或 fixture 来源；其 Alpha 状态、服务端协议、PIT 字段不足和公开 SLA 缺失，使其不适合作为切片的唯一生产依赖。
5. **Kimi Datasource（adapt，Codex-control-plane only）**：可由用户明确触发、经 Codex/Skill 用短 prompt 分步调用，补充行情、财务候选字段和公告发现；它是 LLM mediated acquisition bridge，不是业务运行时 Provider，也不能直接产生官方 Fact 或 PIT 数据。详见[Kimi Datasource Provider 可行性研究](kimi-datasources-provider.md)。
6. **当前 checkout 资产（adopt as regression fixtures only）**：现有 CNINFO/Yahoo manifest 能继续验证 `ResearchEngine`，但不是 Provider 缓存；Yahoo 不进入本切片的生产 provider chain。

推荐的业务运行时基线仍为“官方披露 + Tushare（可选）/AKShare + 本地 fixture adapter”；Kimi 只能位于运行时之外，由 Codex 低频按需采集到隔离 staging，再经确定性 transcript/file verifier 导入为 `unknown_secondary` 候选。Provider fallback 必须逐次记录真实成功来源，不能把最终值统一标成“official”。

## 当前仓库事实

- `pyproject.toml` 没有 Provider、HTTP、重试或数据库依赖；产品代码没有网络同步路径。
- `examples/yihua-002897` 与 `examples/duofuduo-002407` 是人工整理的研究输入。它们包含 CNINFO、SZSE、Yahoo 和本地计算来源，但不会自动刷新或归一化。
- 多氟多 manifest 声明的 `raw_file_path` 与 SHA-256 对应文件并不在当前 checkout；因此这些声明不能充当可回放 raw-cache fixture。
- 现有核心已经校验 `available_at <= as_of_date`，但只接受组装后的 manifest；Provider 的抓取时间、内容哈希、限流、增量 cursor、修订与离线 staleness 必须在 `ResearchEngine` 外解决。

## 候选矩阵

| 候选 | 固定证据 | 能力与时间语义 | 许可/运行风险 | 决策 |
|---|---|---|---|---|
| CNINFO / SSE / SZSE / BSE / 公司 IR | CNINFO 自述为深交所法定信息披露平台；各站公开公告/PDF | 公告与报告原文、披露日期/时间、公司行动；适合作为 `available_at` 权威来源 | 未核实到统一、公开承诺的批量 API、限流 SLA 或再分发许可；网页端点可能变化 | **adopt authority, adapt access** |
| Tushare Pro + Python 1.4.29 | [PyPI 1.4.29](https://pypi.org/project/tushare/)、[权限与频次](https://tushare.pro/document/1?doc_id=290)、[服务协议](https://tushare.pro/document/1?doc_id=405) | `stock_basic`、`trade_cal`、`daily`、`adj_factor`、财务表/披露日索引等；接口文档给出更新时间、积分与频次 | BSD 只覆盖客户端；数据服务需 Token/积分或独立权限，许可为个人、非商业、不可转让且可撤销 | **adapt, optional production** |
| AKShare 1.18.64 / commit `fcdbf25` | [固定 release](https://github.com/akfamily/akshare/releases/tag/release-v1.18.64)、[固定源码 `stock_zh_a_hist`](https://github.com/akfamily/akshare/blob/fcdbf25aa864a218c54864c3f6ab6a2ed19cce28/akshare/stock_feature/stock_hist_em.py#L952-L1003)、[项目说明](https://akshare.akfamily.xyz/introduction.html) | 覆盖 A 股日线、复权、主数据、公告和市场指标；固定源码显示该日线接口直接请求东方财富端点并暴露 timeout | MIT 只覆盖代码；官方说明数据仅用于学术研究且接口会因上游变化移除；单次 HTTP 调用本身没有平台需要的统一重试/熔断/来源许可模型 | **adapt as fallback/cross-check** |
| BaoStock 0.9.2 | [PyPI 0.9.2](https://pypi.org/project/baostock/)；[官方复权说明](https://www.baostock.com/helpdocs/pdf/BaoStock%E5%A4%8D%E6%9D%83%E5%9B%A0%E5%AD%90%E7%AE%80%E4%BB%8B.pdf) | 日/周/月和分钟 K 线、交易日、证券信息、复权因子及部分财务查询；客户端声明 OS independent | BSD 客户端、免费服务，但 PyPI 仍标 Alpha；未核实公开服务 SLA、批量使用条款、财务 `available_at` 或历史修订语义 | **reference only** |
| Kimi Code CLI 0.23.5 + Kimi Datasource 3.2.0（本机 live 已验证） | [独立研究与实测](kimi-datasources-provider.md)、[官方插件文档](https://moonshotai.github.io/kimi-code/en/customization/plugins.html#kimi-datasource) | 自然语言经 Kimi Agent 调用动态 Datasource MCP，可写行情、财务、公告等 CSV；session 可连续恢复；3.2.0 提供 request/tool-call trace | LLM 选择工具/参数；CSV 缺上游身份与 PIT 元数据；trace 不是来源/版本；退出码/最终 JSON/文件存在均不足以证明成功；通用条款限制未授权自动化/批量使用；违反业务运行时无 LLM 约束 | **adapt as low-frequency Codex acquisition bridge; reject runtime provider** |
| 当前 Yahoo 静态资产 | checkout 中两份 manifest | 只证明当时人工运行使用过 Yahoo chart 数据 | 没有 SDK、adapter、缓存、服务条款快照或可回放 raw；A 股关键数据不具官方权威性 | **regression fixture only; reject production** |

维护活跃不等于接口稳定：AKShare 与 BaoStock 在 2026 年均有新 release，Tushare 也在 2026-03 发布 1.4.29；但三者都需要本项目自己的 contract tests、超时、重试、限流和 schema 版本，不能依赖上游测试替代本地契约。

## 能力分工

| 数据能力 | 首选 | 回退/交叉核验 | 不允许的降级 |
|---|---|---|---|
| `Security` 主数据 | Tushare（若有权限）或交易所上市列表 | AKShare、BaoStock | 仅用当前简称/代码当稳定证券身份 |
| 交易日历 | 交易所日历；Tushare 结构化 | AKShare、BaoStock | 以“周一至周五”推断交易日 |
| 未复权日 OHLCV | Tushare 或固定版本 AKShare adapter | BaoStock、第二 provider 对账 | 混合不同 provider/复权模式后不留来源 |
| 复权因子/公司行动 | 官方公告为事件权威；Tushare 因子结构化 | AKShare/BaoStock 因子交叉核验 | 把今天下载的前复权历史当历史时点当时已知数据 |
| 财务披露与关键财务事实 | CNINFO/交易所/公司正式报告原文 | Tushare/AKShare 仅用于索引、结构化候选和交叉检查 | 第三方聚合值单独支持正式估值结论 |
| 市场状态输入 | 结构化指数、个股、宽度、成交额数据 | AKShare/Tushare 相互核验 | 把 provider 自带“热度/信号”直接当 `MarketSnapshot` |

CSRC 更适合作为监管规则和监管公告来源，不是第一条切片的证券行情或公司财务结构化 Provider。公司 IR 可补充公告发布时间和演示材料，但交易所/CNINFO 已披露版本仍是关键事实的首要来源。

## Point-in-time 约束

每个 raw 获取和 normalized record 至少保留四类时间，且不得互相代替：

- `event_at` / `period_end`：交易或财务事实描述的经济时点；
- `published_at`：发布者标注的公告时间；
- `available_at`：该版本最早可被本系统用户公开获得的时间，是历史 `as_of` 门禁；
- `retrieved_at`：本机实际抓取时间，只用于采集审计，不能证明历史可用性。

实施时还需记录 `time_precision` 与 `availability_basis`。若官方页面只有日期而没有时间，不得虚构 `00:00`；应标为 date-only，并在同日回测/评估中使用保守门禁（例如下一交易时段才可用），具体规则交给“决定分层存储、时间语义与同步契约”。

财务表的 `report_date/end_date` 不是 `available_at`。Tushare 的公告日期、实际公告日期和更新标志应原样保留，随后用官方原文校准。修订/更正公告必须形成新 raw hash 和新 normalized version，不能覆盖旧值。

未复权 OHLCV 与公司行动应作为 canonical 输入分开保存。前复权/后复权序列是某个因子版本下的派生视图；未来公司行动会改变历史前复权值，因此当前下载的整段前复权序列不可直接用于历史 PIT 回测。第一条切片可冻结当前图表用复权视图，但必须连同 adjustment mode、因子版本和 `DataSnapshot` 一起保存。

## 增量缓存建议（供后续契约票据决定）

### 键与版本

- raw request key：`provider + adapter_version + dataset/endpoint + canonical_params + credential_scope_id`；只存不可逆 scope id，绝不把 Token 写入键、日志或数据库。
- raw content identity：响应 bytes 的 SHA-256；另存 HTTP status、响应头、请求时间、来源 URL、条款/许可 profile 和错误类型。
- normalized identity：`schema_version + security_id + dataset + natural_key + source_raw_hash + normalization_version`。
- derived identity：所有输入 snapshot hashes、参数、复权模式、时区和算法版本。

### Freshness 而非单一 TTL

| 数据集 | 建议刷新边界 | 离线行为 |
|---|---|---|
| 主数据 | 每日任务最多刷新一次；代码/上市状态变化强刷 | 允许旧值并显示 `stale_by`，身份冲突时阻塞 |
| 交易日历 | 缓存当前与下一年度；周级刷新、年末或官方变更强刷 | 可用已冻结日历；未知日期不得猜测 |
| 日 OHLCV | 从最后完整交易日增量；下一交易日收盘加 provider 延迟后到期 | 可读旧 snapshot；当日 `MarketSnapshot` 因不新鲜而受限/阻塞 |
| 公告索引/公司行动 | 每次 daily run 增量查询，发现新公告或更正即强刷 raw | 可读旧报告，但明确“截至上次成功同步” |
| 已下载官方 PDF/原始响应 | 内容寻址后永不过期；只追加新抓取/修订 | 始终可回放并校验 hash |
| 失败/空结果 | 短 negative cache，尊重 `Retry-After`；不得长时间缓存为“无数据” | 返回 `missing/error`，不写 0 或空事实 |

`force_refresh` 只绕过 freshness 判断，不得原地覆盖 raw。若新响应 hash 相同，记录一次新的 sync attempt/cache revalidation，但 normalized 内容可以幂等复用；若 hash 变化，则创建新版本并保留差异。

增量 cursor 必须是 provider/dataset 专属且可审计，例如交易日、公告 ID/发布时间与分页位置的组合；不得用“最后一次运行时间”作为所有数据集的通用 cursor。写入以 natural key + source version 做幂等 upsert，同一工作流重跑不得增加重复 OHLCV、公告、公司行动或 Evidence。

## Adapter 与失败语义

生产 adapter 与 fixture adapter 必须实现同一 typed contract，但 fixture 只回放版本化 raw bytes/JSON 和预期元数据，禁止访问网络。现有研究 manifest 可以继续做 `ResearchEngine` fixture；Provider contract fixture 要另建真实响应的最小、脱敏、可合法保留样本，并校验 SHA-256。

一次同步结果至少区分 `complete / partial / missing / failed / rate_limited`，并保留所有 attempt：provider、版本、开始/结束、cache hit、重试次数、HTTP/业务错误、next cursor 和成功产物。回退成功不能抹去前序失败，也不能把回退数据冒充首选来源。

重试只适用于 timeout、连接失败、429 和明确的 5xx；采用指数退避、jitter、最大尝试数并尊重 `Retry-After`。鉴权、权限不足、schema drift、许可禁止和质量冲突不得盲重试。进程重启后从已提交 raw artifact/cursor 恢复，不从头重复抓取。

## 最低质量检查

- natural key 重复、日期顺序、交易日历覆盖、停牌/零成交语义；
- `low <= open/close <= high`、非负 volume/amount、价格与单位类型；
- 证券代码、交易所、币种、时区和上市状态一致；
- 未复权价、复权因子、除权除息日与官方公司行动相互解释；
- provider 间异常跳变、缺口和修订必须输出 conflict，不自动择一；
- 财务期间、合并/母公司口径、币种、单位、公告版本与更正关系；
- `available_at > as_of` 的记录不得进入 `DataSnapshot`；date-only 可用时间不得通过同日精细回测门禁。

任何关键官方来源缺失都沿用当前 `data_insufficient_memo`/能力级降级边界；第三方 fallback 只能恢复相应的非关键市场能力，不能恢复正式估值权限。

## 许可、凭据与 Windows

- Tushare Token 只从本地 secret/config 注入并在日志中屏蔽。用户未提供 Token 时 adapter 报 `not_configured`，随后走无凭据路线；不需要为第一条切片新增前置凭据 task。
- Kimi 使用本机 OAuth 凭据和远程 Datasource 网关；只发送公开证券代码和必要日期，禁止传持仓、成本、现金、交易流水、计划、风险配置或未公开研究。设置 `KIMI_DISABLE_TELEMETRY=1` 不能把远程服务变成本地数据库。
- Kimi prompt 模式默认自动处理工具权限，实测可调用 `Read/Write/Bash`；必须在隔离 staging 运行，并从 `stream-json` 精确拒绝非预期 MCP 工具、额外数据源、参数漂移、`EMPTY_DATA` 和模型创建的伪文件。业务运行时、daily sync、Web worker、估值和回测代码不得启动 Kimi CLI。
- 本地缓存不得再分发 Tushare 或聚合站 raw 数据；导出的 `ArtifactManifest` 只登记本机路径、hash、来源和许可 profile。若未来产品转为多人/商业使用，必须重新取得数据许可。
- AKShare 与 BaoStock 均为纯 Python/OS-independent 路线，适合 Windows；但第三方网络端点、编码和证书问题仍须在 Windows contract test 覆盖。
- 官方披露站点的公开浏览不等于已获得批量抓取、镜像或再分发授权。实现前应保存当时条款快照、使用低频增量请求并提供人工下载/fixture 导入回退；若站点明确禁止自动访问，立即停用该 adapter。

## 尚未获得的证据

以下不是“已通过”，而是后续实现前必须重新核验的外部边界：

- CNINFO/SSE/SZSE/BSE 对具体批量端点的公开 API 稳定性、限流和长期存档 SLA；
- 各官方站点对自动化下载、本地长期 raw 保留和派生字段使用的具体条款；
- Tushare 用户当前实际积分/接口权限，以及第一条样例所需字段的 entitlement；
- BaoStock 0.9.2 服务端协议、历史修订、公告可用时间和明确服务 SLA；
- AKShare 每个选定函数背后的上游站点条款，而非仅 AKShare MIT 许可证。
- Kimi `stock_finance_data` 的真实上游身份、数据许可、credits/速率/SLA、修订策略、PIT/复权版本，以及 Datasource 专属自动化授权。

这些缺口不阻塞 Spec：第一条切片可以用官方公开披露、无凭据市场 adapter 与合法版本化 fixture 完成；但它们会限制 adapter 的能力状态和可宣称的真实同步范围。

## 对后续 Wayfinder 票据的输入

- “固定纵向切片用户故事与示例标的”可以在意华股份/多氟多现有研究 fixture 中选一个，但必须新增独立的 Provider raw/contract fixture，不能假设当前 raw 路径可回放。
- “决定分层存储、时间语义与同步契约”应锁定上述四类时间、date-only 保守规则、未复权 canonical + 因子派生、append-only raw、dataset-specific cursor、freshness/staleness 和强刷不覆盖语义。
- Tushare 维持 optional；只有后续明确选择依赖其独占字段时，才需创建凭据/entitlement 前置 task。
- Kimi 不进入正式 Provider runtime contract；若后续试点，只实现 Codex 控制面的 transcript verifier + staging importer，并以正式 Provider/官方披露逐字段对账。
