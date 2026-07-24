# 外部股票能力单向迁移、删除与升级决定

Date: 2026-07-24
Scope: Wayfinder ticket 09；锁定后续 implementation Spec 的迁移顺序，不授权本票修改生产代码。

## 最终采用集合

票 03–08 已推翻票 02 中尚待资格化的 provisional `adopt-external` 假设。当前最终集合为：

| Candidate / capability | Final decision | Production consequence |
|---|---|---|
| Public Equity Investing production runtime/data/valuation/presentation | `reject` | 不安装、不建 runtime contract、不建数据源或报告 |
| Public Equity Investing control-plane comparison | `keep-local` | 当前 `external_blocked`；未来只能对同一 frozen evidence 做非权威 canary |
| `a-stock-data` Skill、依赖、parser、fallback、cache/file/report | `reject` | 不执行、不 vendor、不复制、不添加依赖 |
| CNINFO HTTPS statutory disclosure protocol | `adapt-code` | 只允许 target-owned typed protocol/parser，进入唯一 DataProvider/frozen-evidence path |
| SZSE HTTPS statutory disclosure protocol | `adapt-code` | 同上；显式 source role，不作为 CNINFO 失败后的隐藏 fallback |
| SSE/SZSE public trading/supervision records | `keep-local` qualification evidence | 当前没有 named product caller，不建 adapter/placeholder |
| `global-stock-data` Skill、aggregator endpoints/parsers | `reject` | 不执行、不 vendor、不添加依赖 |
| SEC submissions/companyfacts/Archives protocol | `adapt-code` | clean-room target-owned SEC adapter，进入唯一 DataProvider/frozen-evidence path |
| SEC ticker discovery | `keep-local` qualification evidence | 不建立第二 security master；当前无必要 runtime caller |
| HKEX website scraper | `reject` | 无自动化许可，不建 adapter |
| licensed HKEX IIS/feed | `external_blocked` | 没有 entitlement/spec，不建占位符 |
| issuer IR | `keep-local` source-policy category | 必须逐发行人资格化；不是全市场 adapter |
| Vibe-Trading entire MCP/backtest/WF/bootstrap/MC/report | `reject` | production allowlist `[]`，无 subprocess/MCP/report/runtime dependency |
| Vibe signal/PIT/A-share execution/hash ideas | `adapt-code` design evidence only | 不复制实现；未来只有完整 target-owned StrategyValidation 能原子进入 |
| StrategyValidation production capability | `unavailable` | 当前不进入实现队列；selection 返回 typed unavailable，无 result/artifact |

因此当前没有任何 `adopt-external` conclusion，也没有外部 package/runtime 进入主项目。后续实现只能采用两个官方披露协议族的 clean-room `adapt-code`，并深化本地 ResearchEvaluation path。

## 当前代码基线与删除压力

当前 checkout 的真实 runtime 泄漏：

- `DataSyncService` 以 provider tuple 顺序嵌套尝试，并直接构造 `ts_code`、`exchange`、`list_status` 等 Tushare wire params。
- `FetchRequest.canonical_params` 把 provider wire shape 暴露给 orchestration。
- `provider_config.load_sync_job` 通过字符串 `provider_type` 和 dict class lookup 选择 `HttpJsonProvider` / `TushareCompatibleProvider`。
- generic `HttpJsonProvider` 同时假设 JSON POST、token/body shape 和错误折叠，不拥有具体 source protocol。
- `DataRepository.build_snapshot` 硬编码 `query@1`、`source@1`、`freshness@1`。
- `ResearchWorkflowRequest@1` 允许 caller 提交 `ResearchProjection.manifest`、`estimates`、free-mapping `ResearchInputs`、member classification 和 `analysis_artifacts`。
- `research_request_codec` 是唯一 `ImmutableArtifactDraft.from_serialized` caller。
- `ResearchRunner` Protocol 只有本地 engine 与测试 counting/decorator 变化点，没有真实 production adapter variation。
- `application/research_view_cutover.py`、`ResearchDecisionViewMaterializerPort` 和 persistence cutover 仍解码 Request@1，为 runtime 保留 migration-only seam。
- 当前最大数据库 migration 为 `0012_research_artifact_bundle.sql`。
- project runtime dependencies 为空；没有 project NOTICE/third-party runtime inventory。

这些不是保留兼容层的理由，而是后续切片的明确删除对象。

## Blocker-first 原子序列

序列是总序；每票只允许其声明的 single path。后一票不得提前加入 field、table、adapter、feature flag、reader 或 placeholder。

```text
M01 typed provider/source-policy cutover
  -> M02 official evidence persistence migration 0013
  -> M03 A-share official-disclosure adapters
  -> M04 SEC official-disclosure adapter
  -> M05 ResearchWorkflowRequest@2 + ResearchEvaluation migration 0014
  -> M06 cleanup and release proof
```

StrategyValidation 不在当前序列中。它不是 M05 的空壳，也不预留 `0015`、port、table、kind、route 或 view field。

## M01 — typed provider/source-policy cutover

### Target interface

公开 application task 仍为 `DataSynchronization`。内部唯一外部 seam 仍为 `DataProvider`，但深化为：

```text
DataProvider.fetch(TypedDatasetQuery) -> FetchBatch
```

`TypedDatasetQuery` 是 closed union；provider adapter 自己拥有 endpoint、wire params、credential use、response schema 和 protocol failure translation。`FetchBatch` 绑定 raw envelope 与 typed normalized candidates/typed failure；orchestration 不再解析 provider wire JSON。

`SourcePolicy@1` 是具体、versioned、in-process policy，不是 port。它按 dataset/source role 静态声明 required providers、authority、rights、failure disposition 和 completeness。required source 失败产生 blocked/partial，不尝试“下一个旧源”制造成功。

### Caller/config cutover

- `sync`、`daily`、`provider-qualify` CLI command names不变。
- provider job 一次性升级为 `ProviderJob@2`；当前 Tushare-compatible gateway 是唯一 production structured-market provider，因此 job 不再携带 provider implementation selector。
- composition root 静态构造 `TushareCompatibleProvider` 和 `SourcePolicy@1`；未来 official providers 由同一 composition root 按显式 source role 加入。
- old job 被新 codec 拒绝 `PROVIDER_JOB_SCHEMA_UNSUPPORTED`；不 default、不 alias、不 dual decode。

### Same-ticket deletion

必须删除：

- `provider_type` field、default、readiness output 与所有 docs/examples/tests；
- provider-class dict dispatch；
- generic `HttpJsonProvider` class 与 `data.__init__` export；
- `FetchRequest.endpoint`、`canonical_params` 和 caller-built credential/provider identities；
- `DataSyncService` 的 Tushare-shaped params 与 provider-order nested fallback；
- `"http_json"` / `"tushare_compatible"` string implementation selection；
- tests 中“第二 provider 成功掩盖第一 provider 失败”的 fixture；
- old provider job fixtures、backup/restore assertions 和 `skills/SKILL.md` 的旧 config instructions。

保留具体 `TushareCompatibleProvider`、deterministic `FixtureProvider` 和 `DataProvider` port；前两者继续证明 production/test real variation。

### Schema/persistence/presentation

无 database migration。provider attempts/raw objects/snapshots 仍由 `DataRepository` 单一路径写；Web 仍只读 canonical persistence。`ProviderJob@2` 是唯一 config schema。

### Acceptance

- public `sync`/`daily`/`provider-qualify` task tests；
- Tushare wire/query/typed error fixtures；
- FixtureProvider deterministic rights tests；
- explicit required-source failure，不发生 fallback；
- targeted absence search for all deleted symbols/strings；
- doctor、backup/restore、CLI help/docs 同步更新。

## M02 — official evidence persistence migration `0013`

### Target deep module

`DataSynchronization` 后的 owning persistence 仍为 `DataRepository`。增加 typed official evidence records，而不是第二 repository：

- `OfficialFilingVersion`：security/issuer/source/document/accession-or-document-id/filing type/period/document object hash；
- `FinancialFactVersion`：filing parent、taxonomy/concept/context/period/unit/currency/scale/Decimal value/statement scope/source fact identity；
- base `NormalizedVersion` 继续拥有 published/available/retrieved/supersedes/quality；
- `DataSnapshot` 继续是 ResearchEvaluation 唯一 frozen input owner。

### Exact database migration

新增且只新增 `migrations/0013_source_policy_official_evidence.sql`。不得修改 `0001`–`0012`。

`0013` 必须：

1. 建立 immutable typed source-policy identity record；
2. 让每个 provider attempt 绑定 non-null `query_policy_version` 与 `source_policy_version`；
3. 新建 official-filing 与 financial-fact typed extension tables，均引用现有 normalized/object/security identity；
4. 以现有 provider attempt、adapter/source identity 和 snapshot membership 推导旧 `query@1` / `source@1` 行的 canonical policy identity；
5. 任一旧 snapshot 无法唯一推导时以 `SOURCE_POLICY_IDENTITY_UNMIGRATABLE` 整个 transaction 失败；
6. 重建受影响表并删除 generic placeholder value；不保留 default/legacy reader；
7. 保留 immutable raw/object/artifact history及原始 source identity，不重写事实值；
8. 安装 immutability、FK、unique content/lineage 和 new-write schema gates。

迁移前由 canonical `migrate` 生成并验证 backup；migration、backfill、FK/integrity、fail-injection rollback 与 restore 都经现有 MigrationRunner path。

### Same-ticket deletion

- repository 与 fixture 中所有 hard-coded `query@1`、`source@1`；
- direct SQL official-filing/financial-fact fixture；
- caller-authored fake official filing/fact object；
- free dict official fact persistence；
- duplicate/raw report tables或文件写入（若实现中出现则本票失败）。

### Presentation

不改变 `ResearchDecisionView@2`。没有 complete typed facts 的 snapshot 只能阻塞 downstream；Web 不获得直接 disclosure endpoint。

## M03 — A股 official-disclosure adapters

### Target adapters

在既有 `DataProvider` seam 后实现两个具体 production adapters：

- `CninfoStatutoryDisclosureProvider`
- `SzseStatutoryDisclosureProvider`

它们拥有 HTTPS allowlist、exact security/org identity、bounded response/document、MIME/hash、published/available/retrieved semantics、correction/supersession、typed empty/partial/rate/auth/timeout/schema/identity failures和 clean-room parser。

`SourcePolicy@1` 为二者分配显式不同 role。一个 source 失败不能把另一个标记为其 fallback success；required cross-check 缺失产生 partial/blocked attempt evidence。

### Rights/deployment

只允许已资格化的本地非商业使用，不再分发 raw 或 derived provider payload。rights profile 是 source policy admission gate；不满足 deployment policy 时 adapter 不发起网络请求。

### Same-ticket deletion

- 所有 direct SQL official-disclosure fixtures；
- caller-authored filing/member classification；
- 当前 public tests 中替代真实 adapter path 的 official filing injection；
- 任何 cleartext CNINFO mapping、guessed org ID、disabled TLS、Eastmoney fallback、raw SSE text forwarding 或 direct PDF path（这些若被误引入，必须同票删除）。

### Explicit non-adoption

不实现 CNINFO Q&A、SSE/SZSE public trading records、aggregator reports或整个 `a-stock-data` Skill。它们没有当前 named caller；不得以 future registry/placeholder 存在。

### Acceptance

target-owned synthetic official-schema fixtures + controlled live canary；覆盖 exact identity、document hash/PIT、empty vs drift、wrong security、partial pages、correction、403/429/timeout、oversize/MIME、rights denied。验收必须从 public `DataSynchronization` 进入 `DataSnapshot`，不能直接调用 parser 作为最终证明。

## M04 — SEC official-disclosure adapter

### Target adapter

在同一 `DataProvider` seam 后实现一个 cohesive `SecOfficialDisclosureProvider`，拥有 submissions、companyfacts 与 Archives 三个协同协议。输入使用 typed CIK + canonical listing/security identity；ticker 不作为历史 identity 或第二 security master。

adapter 拥有 truthful contact User-Agent、host allowlist、rate/Retry-After、bounded body、CIK/accession/form/report/filing/acceptance/context/unit/taxonomy/amendment/coverage、raw hash和 typed failure。

### Same-ticket deletion

- 任何 generic SEC JSON dict parser；
- ticker-only cache/mapping假设；
- caller-authored SEC filings/facts；
- current test fixture 中绕过 public DataSynchronization/persistence 的 SEC facts；
- raw HTML/XBRL/JSON 到 ResearchEvaluation/Valuation 的直通；
- 若出现 Yahoo/Eastmoney/Sina/Tencent fallback 或 `global-stock-data` Skill/runtime dependency，本票失败并删除。

### Explicit non-adoption

不实现 HKEX scraper、licensed feed placeholder、issuer-global registry、aggregator行情/报告、recommendation或 target-price parser。

### Acceptance

official-schema fixtures覆盖 historical submissions shards、amendments、多 unit/context、unknown taxonomy、missing fact、wrong CIK、403/429/timeout/schema drift和 coverage；controlled SEC live canary使用 truthful User-Agent。public acceptance 必须证明 typed facts进入 migration-0013 schema及 frozen snapshot，原始 JSON 不能成为正式结果。

## M05 — `ResearchWorkflowRequest@2` 与 ResearchEvaluation 原子切换

这是一个 cohesive、不可拆成 temporary-both 的切片。拆开会迫使旧 free mappings 或 caller artifacts 继续成为 active seam。

### Target application path

唯一入口：

```text
ResearchWorkflow.handle(
  StartResearchWorkflow(
    ResearchWorkflowRequest@2(
      invocation/security/requested/effective dates,
      data_snapshot_id,
      workflow_snapshot_id?,
      market_data_snapshot_id?,
      ResearchEvaluationPlan@1
    )
  )
) -> ResearchWorkflowResult
```

具体 `ResearchEvaluation.evaluate(...)` 从 ledger/repository 加载 frozen typed evidence，内部拥有 source/PIT/quality admission、Forecast、method router、ScenarioValuation、ValuationSimulation、反证与 publication permission，并由 workflow 建 typed artifact drafts。

### Exact database migration

新增 `migrations/0014_research_evaluation_cutover.sql`，配套只在 canonical migration path 运行的 typed one-way migration step。

`0014` 必须：

1. preflight 所有旧 research workflows 已 terminal，且每个已完成 run 已有 hash-valid `ResearchDecisionView@2` / HTML / manifest；
2. 将旧 projection identity 转为 typed historical evaluation-plan record，绑定原 snapshot、old projection artifact hash和 `historical_migrated_read_only` disposition；不得把旧 free mapping 解释成新正式事实；
3. 新建 immutable evaluation-plan identity/record与 research-run reference；
4. 重建 `research_run_record`，切换到 evaluation-plan/snapshot identity；
5. 删除 `research_input_projection` active schema；
6. 安装 new-write gate：research workflow 只接受 `ResearchWorkflowRequest@2`；
7. 保留旧 request/object bytes作为 immutable audit blobs，但 production runtime 没有 Request@1 decoder/reader；
8. 任一旧 run 无法安全 materialize/migrate 时以 stable code 整体失败并从 backup 恢复；不创建兼容 reader。

历史 Request@1 bytes 的保留不是 dual-read：它们只作为 content-addressed audit evidence存在，没有 application decoder、resume 或 replay path。新的 start/resume/replay 全部使用 Request@2。

### Caller cutover

同票更新：

- CLI research request codec/fixtures/examples；
- `DailyResearchCycle` serialized job contract；
- browser acceptance fixture；
- research workflow、recovery、operations、secure workspace、plan/market、forecast review、valuation/workbook public callers；
- tests 中所有 `ResearchWorkflowRequest(...)` construction；
- `examples/*/research_context.json` 删除或替换为完整 typed Request@2 example；
- `skills/SKILL.md`、architecture、source-manifest docs 和 CLI help；
- JSON/HTML/workbook/Web 继续消费唯一 `ResearchDecisionView@2`。

### Same-ticket deletion

必须删除：

- `ResearchWorkflowRequest@1`、`ResearchProjection` 及其 decoder；
- public/free-mapping `ResearchInputs@1`、`from_mapping` 和映射 fixtures；
- caller-supplied manifest/estimates/member classifications；
- caller-authored `analysis_artifacts`；
- `ImmutableArtifactDraft.from_serialized`（当前唯一 caller随旧 decoder消失）；
- `ResearchRunner` Protocol、CountingEngine/decorator-only test seam；
- `application/research_view_cutover.py`；
- `ResearchDecisionViewMaterializerPort`；
- `persistence/research_view_cutover.py` 和 `cutover_research_decision_views`；
- operations/bootstrap/runtime cutover gates、legacy cutover faults/tests/docs；
- old projection table及所有 active reader/writer；
- raw external narrative/report到 research artifact 的映射。

若上述任一对象仍被 active code/tests/docs引用，M05 不得关闭。

### Presentation

`ResearchDecisionView@2` 保持唯一 schema；plan/source-policy identity 与 disabled reason 进入既有 audit/policy identity。M05 不增加 parallel view 或 `@3`。只有未来真实 StrategyValidation 产生 decision-relevant typed result 时，才另行资格化一次 atomic view migration。

### Strategy semantics

`ResearchEvaluationPlan@1.strategy_validation` 允许 `not_requested` 或 typed selection。selection 在当前 capability state 下返回：

```text
blocked + STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE
result = null
artifact = none
```

M05 不创建 `StrategyValidationPort`、engine、table、artifact kind、CLI/Web route、fake adapter或 Vibe wrapper。

## M06 — mandatory cleanup 与 release proof

M06 不增加功能，只证明 M01–M05 已形成唯一当前系统。

### Mandatory absence searches

至少搜索并要求零 active hit：

- `provider_type`、`HttpJsonProvider`、provider-class lookup；
- caller-built Tushare wire params in `DataSyncService`；
- hard-coded `query@1` / `source@1`；
- `ResearchWorkflowRequest@1`、`ResearchProjection`、`ResearchInputs@1`；
- `analysis_artifacts` on application request；
- `ImmutableArtifactDraft.from_serialized`；
- `ResearchRunner`；
- research-view cutover/materializer/legacy fault symbols；
- Vibe/MCP/backtest/report runtime dependency；
- HKEX scraper、aggregator fallback、Skill runner；
- compatibility/legacy/fallback/dual feature flags introduced by this effort。

Migration files and ticket/research evidence may retain historical symbol text; runtime, active tests, current docs/examples不得保留。

### Required verification

- fresh database migrations `0001`–`0014`；
- supported old database one-way upgrade through `0013`/`0014`，backup/hash/integrity/FK/fail-injection/restore；
- full public provider/research/workflow/recovery/presentation suite；
- exact A-share/SEC live qualification gates, with skipped external state reported rather than passed；
- real browser acceptance through production verifier and canonical DecisionView；
- backup/restore/doctor/acceptance manifest；
- fresh checkout/generated Web assets if affected；
- dependency/lock/licence inventory；
- final diff/status and superseded-symbol search。

M06 不能以 caller-authored JSON、boolean 或窄单元测试证明 broad release。

## Slice surface ledger

每个 implementation slice 都必须在同一 local commit 覆盖下表声明的 surface；“不变”是显式验收项，不代表可忽略。

| Slice | Caller/application | Tests | Current docs/examples | Persistence/schema | Presentation | Same-slice cleanup |
|---|---|---|---|---|---|---|
| M01 | `sync`/`daily`/`provider-qualify` names不变，全部改用 ProviderJob@2 + typed policy | public tasks、Tushare/fixture、failure/no-fallback、operations | Skill provider config、CLI help、job examples | DB 不变；attempt/snapshot仍唯一 owner | Web不变且不得直接 fetch | old codec/dispatch/generic provider/wire params/fallback fixtures 全删 |
| M02 | DataSynchronization仍唯一写入入口 | migration/backfill/fault/restore、public sync→snapshot | schema/architecture/source policy docs | migration 0013；旧 placeholder rows唯一迁移 | DecisionView@2不变；缺 facts 时 blocked | hard-coded policy ids、direct SQL/caller fact fixtures 全删 |
| M03 | 现有 sync/daily/provider-qualify 经 policy 调用 A股 official roles | target-owned fixtures、live canary、rights/PIT/identity/public path | A股 source/rights/runbook、job/policy examples | 使用 0013 tables，无第二 repository/schema | DecisionView@2不变；只消费 frozen snapshot | official direct SQL/injection、任何不安全/fallback path 全删 |
| M04 | 同一 application tasks 经 policy 调用 SEC role | SEC schema/failure/live/public snapshot tests | SEC User-Agent/rate/rights/runbook、policy examples | 使用 0013 tables，无 SEC side database | DecisionView@2不变；raw SEC不能直通 | generic/ticker-only/caller facts/aggregator fallback 全删 |
| M05 | CLI/daily/browser/workflow/recovery/operations 全部原子切 Request@2 | 所有 request callers、engine、artifact、ledger、recovery、renderers、browser | Skill、architecture、source-manifest、CLI help、examples 全部 Request@2 | migration 0014；old projection active schema删除；old bytes audit-only | DecisionView@2 唯一且全部 renderer/Web同步验证 | Request@1/free mappings/caller drafts/runner/cutover seam/tests/docs 全删 |
| M06 | 无新 caller | full verifier + release acceptance | 当前文档只描述新路径 | fresh/upgrade/restore全验 | real browser production verifier | stale symbols/fixtures/deps/generated assets/NOTICE inventory 清零或解释 |

任何 slice 若需要让旧、新 caller/codec/table/renderer 同时存活才能通过，就必须扩大该 slice 直到可以原子删除，不能拆出 compatibility follow-up。
## No-temporary-both proof

| Boundary | Before slice | After slice | Forbidden middle state eliminated in same slice |
|---|---|---|---|
| Provider config | old `provider_type` dispatch only | `ProviderJob@2` static Tushare + typed policy only | no dual codec/default/alias |
| Provider query | orchestration-built generic mapping | provider-owned typed query/protocol only | no generic helper/fallback |
| Source policy identity | hard-coded placeholders | migration-0013 derived typed identity only | no dual snapshot writes/readers |
| Official facts | caller/direct-SQL fixtures only | typed migration-0013 persistence via public sync only | direct SQL/caller objects deleted |
| A/US official source | no production adapter | explicit role adapter in same DataProvider path | no Skill runner/second persistence |
| Research request | Request@1 only | Request@2 only | decoder/callers/examples/tests atomically replaced |
| Research artifacts | caller-authored drafts | workflow-owned typed factories | serialized caller artifact path deleted |
| Historical research | runtime cutover reader | one-way migrated audit blobs + current views | Request@1/cutover runtime deleted |
| Presentation | DecisionView@2 | DecisionView@2 | no parallel external/strategy report |
| Strategy validation | unavailable | unavailable typed result | no placeholder/empty schema |

At no row do old and new runtime readers/writers coexist after the owning slice commit. Migration-only readers are reachable solely from canonical `migrate`, version-bound, transaction-tested and never imported by CLI/Web/application tasks after migration.

## Dependency、NOTICE 与归属

### Current implementation queue

- `pyproject.toml` runtime dependencies must remain empty unless a specific protocol implementation proves stdlib insufficient and a separately qualified dependency ticket is added.
- 不 vendor、不 submodule、不复制三个 upstream source trees，不安装 Vibe runtime。
- clean-room adapter code由本项目拥有；上游 Apache/MIT code不复制，因此当前不新增 runtime NOTICE payload。
- research assets保留 upstream repository/commit/tag/license/file hashes和 protocol provenance，作为设计归属与审计证据。
- official provider data rights与代码 license分开记录；official authority不等于自动访问、缓存或再分发许可。

### If code copying is proposed later

任何逐行/结构性复制都会把该 slice 从 `adapt-code` 变成新的 external adoption qualification，必须在修改生产代码前：

1. 固定新 commit 与 copied-file hash；
2. 记录 license、NOTICE、transitive dependency和 source attribution；
3. 生成/更新 project third-party notices及分发边界；
4. 证明 copied behavior 是唯一实现并删除 clean-room/旧实现；
5. 重新执行 security、rights、failure、public-interface和release gates。

没有以上证据，不得复制。

## Pinned version 与未来升级 gate

当前 evidence pin：

| Upstream | Commit |
|---|---|
| `a-stock-data` | `06791b5a3159401524c10bd0e28aaebe415ce604` |
| `global-stock-data` | `d52a8a0013363577bceb28ca876c88fe6c1a5aeb` |
| `Vibe-Trading` | `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` |

生产 adapter 不依赖这些 repositories；pin 只标识 protocol qualification evidence。tag、branch、README 或“latest”不能升级 qualification。

任何 upstream、endpoint、官方 schema、terms、entitlement、User-Agent/rate policy 或 target parser 变化必须开新 qualification ticket，并在隔离目录：

1. 固定 canonical identity、full commit与相关文件 SHA-256；
2. diff endpoint/field/unit/time/identity/auth/network/files/process surface；
3. 重做 primary terms/cache/derived/redistribution/commercial-use review；
4. 重跑 synthetic normal/empty/partial/drift/wrong-identity/error fixtures；
5. 重跑 controlled live probe与官方交叉验证；
6. 重跑三市场 vertical-slice verifier及 tamper test；
7. 重做 source-policy、PIT、lineage、financial-output和privacy gates；
8. 给出 upgrade adoption/deletion matrix、schema impact与 rollback/restore；
9. 原子更新 adapter version/policy identity/fixtures/docs/NOTICE；
10. 删除旧 adapter/version fixture；不得双版本 runtime或 fallback。

未通过任一步时保持当前 pinned qualification/adapter；若旧 endpoint 已不可用则 typed blocked，不自动切新 upstream。

## Persisted-data upgrade policy

- migration files append-only；已发布 hash 不改写。
- 当前 queue 只锁定 `0013` 与 `0014`；不为 StrategyValidation 预留空 migration。
- schema migration 先 durable backup，单 transaction，失败恢复；不能 partial commit。
- old data必须被唯一、可验证地迁移；无法推导 identity/authority/PIT 时 upgrade失败并给 stable blocker，不填默认值。
- migration结束后 active writer/reader只有新 schema。保留的 immutable old bytes只是 audit object，不可被 application decode、resume或fallback。
- restore拒绝 future/unknown schema、hash mismatch和 missing migration。
- rollback不是 runtime dual-path；只能恢复整个 pre-migration backup并运行旧 binary，不能由新 binary读旧 schema。

## Closure criteria for ticket 09

本决定已经为每个当前 implementation slice 锁定：

- target deep module interface；
- callers、tests、docs、persistence、presentation切换；
- exact config/schema versions `ProviderJob@2`、`0013`、`ResearchWorkflowRequest@2`、`ResearchEvaluationPlan@1`、`0014`；
- same-ticket deletion对象；
- absence/public-interface/release acceptance；
- dependency/NOTICE/attribution和future upgrade qualification gate。

由于当前没有 `adopt-external`，不存在“无法同票删除旧实现却仍标记 adopted”的行。所有 rejected/blocked capabilities 都没有 placeholder、dependency、schema、route或report；所有 `adapt-code` 只进入唯一 DataProvider/frozen-evidence path。
