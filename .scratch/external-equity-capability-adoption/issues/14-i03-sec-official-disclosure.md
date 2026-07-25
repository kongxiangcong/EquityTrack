# 14 — I03 A股-only scope migration（不建设 SEC runtime）

**What to build:** 将用户最新且最高优先级的市场范围决定写入唯一 implementation Spec、Map 与 delivery frontier：本 Goal 只建设 A 股；不实现 SEC、美股或港股 runtime。既有 US/HK/SEC 资格化材料只保留为历史研究证据，不再形成 adapter、配置、凭据、schema、验收或 live-receipt 要求。Issue 15 直接由已完成的 Issue 13 解锁。

**Blocked by:** 13 — I02 A股 OfficialDisclosure vertical slice 与 migration 0013.

**Status:** resolved

## Scope decision

- [x] 当前 production market scope 固定为 A 股；Tushare-compatible market data 与 CNINFO/SZSE official disclosure 是唯一已授权数据角色。
- [x] SEC submissions/companyfacts/Archives、US Security/CIK、HKEX、issuer-IR registry 与 licensed HK feed 均不进入当前 runtime。
- [x] 不创建 SEC/HK provider、query、codec、normalizer、persistence、config/env、fixture、route、CLI/Web、NOTICE dependency 或 live receipt。
- [x] 已完成的 US/HK/SEC qualification research 保留为历史证据，明确不得解释为当前 implementation authorization。
- [x] Vibe-Trading 不接入、不安装、不配置；StrategyValidation 保持 unavailable，且不阻断 ResearchEvaluation、交易计划或后续组合纪律主流程。

## Dependency migration

- [x] `spec.md` 的 Solution、candidate matrix、canonical flow、vertical slices、phase gates、adapter matrix、release proof、acceptance criteria、preconditions 与 published frontier 全部迁为 A 股-only。
- [x] `map.md` 记录 superseding scope decision，并把当前 delivery frontier 从 Issue 14 scope migration推进到 Issue 15。
- [x] Issue 15 的 `Blocked by` 从 Issue 14 改为已完成的 Issue 13；Issue 14 不再是 ResearchEvaluation/Request@2/0014/PDF 的运行时前置条件。
- [x] Issue 16 仍只 blocked by Issue 15，依赖顺序保持真实。

## Evidence

- Runtime absence audit：`src/`、`examples/`、`migrations/` 与 current tests 中没有 SEC provider/query/config/route；现有 `HKEX` 字样仅是既有市场代码映射，不是本票新增 runtime。
- Issue 13 local commit：`c20938a912c4397d1abce8d58f7d092134e54d51`；A 股 CNINFO/SZSE production roles、migration 0013、两个 identity-bound live receipts 与完整 verifier 已通过。
- Scope migration 只修改四个 planning assets：本票、Issue 15、`map.md`、`spec.md`；不修改生产代码、schema、依赖、凭据或用户 dirty。
- `git diff --check` 与 exact-path diff/absence/dependency audit 通过；无 live payload、operator contact、personal/provider data、Token 或 gateway 参数进入提交。

## Commit scope

- [x] 一个 local commit 仅包含上述 scope/dependency planning migration。
- [x] 精确 stage 四个 owning paths；保护 `docs/prompts/trading_platform_codex_prompt_optimized.md` 的用户 dirty 与全部既有 untracked assets；不 push/PR。
