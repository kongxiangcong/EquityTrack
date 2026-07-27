# 调研数据 Provider、point-in-time 与增量缓存

Type: `research`
Mode: `AFK`
Status: resolved
Blocked by: 01

## Question

针对第一条 A 股纵向切片，哪些官方与第三方 Provider 组合能够满足证券主数据、交易日历、OHLCV/复权、公司行动、财务披露和市场状态的增量同步、可用时间语义、离线缓存与数据许可要求？研究必须检查候选项目/服务的许可证和使用条款、固定版本核心源码/接口、字段与时间语义、限流重试、失败恢复、Windows 支持、测试与维护状态，不得只看 README；比较当前输出资产、AkShare、Tushare、Baostock、交易所/监管/公司披露渠道及必要替代路线，明确 `adopt / adapt / reference only / reject`、生产与 fixture adapter、缓存键/TTL/强刷/内容哈希/幂等与质量检查建议，并形成独立 Markdown 研究资产供后续决策引用。

## Answer

已完成独立研究资产：[A 股数据 Provider、point-in-time 与增量缓存研究](../research/data-providers-pit-cache.md)。研究以 2026-07-11 为证据截至日，核验了固定版本客户端/源码、官方文档、服务条款、字段和更新时间、维护状态、Windows 路线及当前 checkout 资产。

第一条切片采用按权威性分工的 Provider 组合，不采用单一“万能数据源”：

- **官方披露 adapter family — `adopt authority, adapt access`**：CNINFO、SSE、SZSE、BSE 与公司 IR 承担公告、定期报告、公司行动和关键财务事实的 raw Evidence；交易所/监管披露优先。公开浏览不代表批量 API、SLA 或再分发授权已经核实，具体 adapter 必须可替换、低频增量、保存条款 profile，并在明确禁止自动访问时停用。
- **Tushare Pro — `adapt, optional production`**：在用户已有 Token、积分/独立权限且接受个人非商业条款时，优先承担结构化 `Security` 主数据、交易日历、日 OHLCV、复权因子和财务披露索引；BSD 客户端许可证不等于数据服务许可，且 Tushare 不替代官方财务原文。它不是第一条切片的凭据前置条件。
- **AKShare 1.18.64 — `adapt as fallback/cross-check`**：用于无凭据行情、日历、市场宽度、来源发现和交叉核验；固定源码证实核心日线接口直接依赖东方财富端点，项目也明确学术研究用途与接口移除风险，因此必须由本地 adapter 补重试、熔断、schema/version 和真实上游 provenance，不能把聚合财务值升级为官方事实。
- **BaoStock 0.9.2 — `reference only`**：仅用于 OHLCV、交易日历和复权结果的独立核验或 Provider fixture 候选；Alpha 状态、PIT 财务字段、服务端修订语义和 SLA 证据不足，不作为唯一生产依赖。
- **当前 CNINFO/Yahoo manifest — `regression fixture only; reject production`**：继续验证 `ResearchEngine`，但不构成 Provider/cache。多氟多 manifest 声明的 raw path/hash 文件不在当前 checkout，Provider contract fixtures 必须另建合法、最小、版本化、可回放的 raw 样本；Yahoo 不进入生产 provider chain。

point-in-time 最低语义已收敛为 `event_at/period_end`、`published_at`、`available_at`、`retrieved_at` 四类时间，另带 `time_precision` 与 `availability_basis`；日期精度公告不得伪造时刻，同日使用必须走保守门禁。财务期间不等于可用时间，修订/更正形成新 raw hash 和 normalized version。canonical 行情保留未复权 OHLCV 与公司行动/因子，前后复权只是带因子版本的派生视图；今天下载的前复权历史不能冒充历史时点当时可得的数据。

缓存建议不使用一个全局 TTL：raw request key 包含 provider、adapter version、dataset/endpoint、canonical params 与非敏感 credential scope；raw bytes 用 SHA-256 内容寻址，normalized/derived 分别带 schema、normalization、算法与输入 snapshot 版本。主数据、交易日历、日线、公告索引和不可变 raw 使用各自 freshness 边界；`force_refresh` 只绕过 freshness，不覆盖 raw。相同 hash 记录 revalidation 并幂等复用，hash 变化创建新版本。cursor 按 dataset 定义，失败/空结果只做短 negative cache 并遵守 `Retry-After`。

生产与 fixture adapter 使用同一 typed contract；fixture 禁止联网。同步结果至少区分 `complete / partial / missing / failed / rate_limited`，保留每次 provider attempt、cache hit、重试、错误和 next cursor。质量检查覆盖 natural-key 重复、OHLC 合法性、交易日历、停牌/零成交、证券/交易所/币种/时区、复权与公司行动、provider 冲突、财务口径/单位/修订，以及 `available_at <= as_of`。关键官方证据缺失继续能力级降级或 `data_insufficient_memo`，第三方 fallback 不恢复正式估值权限。

未核实的官方批量端点 SLA/自动化与再利用条款、用户实际 Tushare entitlement、BaoStock 服务端 PIT/SLA、AKShare 各上游站点条款均已列为 adapter capability/实施前证据缺口；它们不阻塞 Spec，也不能被描述为真实同步已获授权。

无需新增 Wayfinder ticket：样例与新 raw fixture 由[固定纵向切片用户故事与示例标的](06-fix-slice-user-story-and-security-fixture.md)收敛；四类时间、date-only 门禁、未复权 canonical、append-only raw、dataset cursor、freshness/staleness 和强刷语义由[决定分层存储、时间语义与同步契约](07-decide-data-storage-and-pit-contracts.md)最终决定。只有后续明确依赖 Tushare 独占字段时，才需要新增凭据/entitlement task。

### 后续证据补充：Kimi Datasource

用户提出本机 Kimi Code CLI 的内置 Datasource 后，已完成独立研究与 live probes：[Kimi Datasource 作为数据 Provider 的可行性研究](../research/kimi-datasources-provider.md)。结论为 **`adapt as low-frequency Codex/Skill acquisition bridge`，同时 `reject as business-runtime Provider`**。

Kimi Code CLI 0.23.5 + Datasource 3.2.0 已完成 live 复验。短 prompt 分拆和精确 session id 可连续获取行情、财务表和公告索引 CSV；3.2.0 的 `request-id/tool-call-id` 改善了调用诊断，但不是来源、版本或 PIT 标识。实测仍有 `EMPTY_DATA + exit 0`，公告 PDF 指向同花顺聚合域名，财务 CSV 的时间字段为空；历史 probes 还出现模型创建表头文件、额外查询未请求 Datasource、最终 JSON 丢失 Tool metadata 等偏航。因此只有完整 `stream-json` transcript 通过确定性工具序列/参数/path/hash/schema 门禁后，产物才可作为 `unknown_secondary` 候选；正式 Fact、财务关键数字和 PIT 数据仍需官方披露或确定性 Provider 支撑。

该路线只能由用户明确发起并由 Codex/Skill 在隔离 staging 低频调用；业务运行时、`daily/sync`、Web worker、估值、回测和计划评估不得启动 Kimi CLI，也不得包含 Kimi prompt。未获得 Datasource 专属自动化与数据留存许可前，不把它加入无人值守缓存链。
