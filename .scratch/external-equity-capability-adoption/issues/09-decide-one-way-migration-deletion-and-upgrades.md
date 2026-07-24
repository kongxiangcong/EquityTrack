# 决定单向迁移、旧实现删除和第三方升级政策

Type: `task`
Mode: `AFK`
Status: `resolved`
Blocked by: 02, 07, 08

## Question

基于已验证的 adopt/adapt/keep/reject 行，锁定 blocker-first 的原子迁移顺序：每个 slice 的目标深模块 interface、caller/test/docs/persistence/presentation/schema 切换、一次性 migration、旧 symbols/exports/commands/fixtures/tests/dependencies/generated assets 删除、NOTICE/归属、固定版本/hash 和未来升级 qualification gate；证明序列中不存在 temporary-both、legacy fallback、dual read/write、兼容 reader、平行 Web/report/persistence 或无法在同票删除的 adopted 结论。
## Answer

决定见 [外部股票能力单向迁移、删除与升级决定](../research/one-way-migration-deletion-and-upgrade-decision.md)。当前最终集合没有任何 `adopt-external`：Public Equity production、两个自由 Skill/聚合器、HKEX scraper、Vibe MCP/backtest/report 全部拒绝或保持 non-runtime；只有 CNINFO/SZSE statutory disclosure 与 SEC submissions/companyfacts/Archives 的 protocol knowledge 作为 clean-room `adapt-code` 进入唯一 DataProvider/frozen-evidence path。StrategyValidation 当前为 typed unavailable，不预留 port/table/kind/route/adapter。

Blocker-first 总序锁定为 M01 typed provider/source-policy cutover → M02 `0013_source_policy_official_evidence.sql` → M03 A股 official adapters → M04 SEC adapter → M05 `ResearchWorkflowRequest@2` + `ResearchEvaluationPlan@1` + `0014_research_evaluation_cutover.sql` → M06 cleanup/release proof。每个 slice 都有 caller、tests、current docs/examples、persistence/schema、presentation 与 same-slice cleanup ledger；任一切换需要 temporary-both 时必须扩大 owning slice，不能留 compatibility follow-up。

M01 删除 `provider_type`、generic `HttpJsonProvider`、class lookup、orchestration wire params 与 provider-order fallback。M02 删除 hard-coded `query@1`/`source@1`、direct SQL/caller official facts，并对不可唯一迁移的旧 identity 整体失败。M05 原子删除 Request@1、ResearchProjection/free ResearchInputs、caller artifacts、`ImmutableArtifactDraft.from_serialized`、ResearchRunner fake variation point和整个 research-view runtime cutover/materializer seam；历史 bytes 仅作为 immutable audit object，不存在 active decoder/replay/fallback。

当前 runtime dependencies 为空，三个 upstream 不 vendor/submodule/copy，因此不新增 NOTICE payload；research evidence 保留 commit/license/file-hash attribution。任何未来代码复制或 upstream/endpoint/schema/terms 升级都必须重新 qualification、pin/hash、license/NOTICE、rights、fixture/live/tamper/public-interface/release gates，并在同票删除旧版本，禁止双版本 runtime。

本票只形成 Wayfinder migration decision，未修改生产代码，也未进入票 10。
