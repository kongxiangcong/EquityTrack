# 13 — I02 A股 OfficialDisclosure vertical slice 与 migration 0013

**What to build:** 让平台运营者通过现有 public sync 与 provider-qualify tasks 为明确 Security 获取 CNINFO/SZSE 法定披露，保存权利允许的原始文件、不可变 filing identity 与 PIT metadata，并把合格成员冻结进唯一 DataSnapshot。0013 在同一票把旧 placeholder policy/fixture-rights schema 单向迁移为唯一 QueryPolicy、SourcePolicy、SourceRights、OfficialFiling 与 FinancialFact persistence contract；任何无法证明的rights或identity使整次迁移失败并可从完整backup恢复。A股PDF本票只形成document evidence，不猜测critical financial facts。

**Blocked by:** 12 — I01 ProviderJob@2、SourcePolicy 与 qualification receipt cutover.

**Status:** resolved

## Target interface and vertical slice

- [x] 先在public sync/provider-qualify seam写失败测试，证明caller只提交typed official-filing query与network authorization，不提交CNINFO/SZSE wire参数、provider class、raw facts或fallback。
- [x] CNINFO与SZSE clean-room production adapters各自拥有TLS、request/response protocol、Security/issuer/document identity、pagination、MIME/size/hash、published/available/retrieved、correction/completeness、rights和typed failure translation。
- [x] existing DataProvider port同时由production adapters与deterministic FixtureProvider覆盖；不创建OfficialDisclosure mirror port、registry或第二sync path。
- [x] 0013精确实现Spec定义的 query policy、source policy、generic source rights、rebuilt provider attempt/data snapshot、official filing与financial fact tables、FK/unique/check/immutability/no-delete gates。
- [x] `fixture_rights_profile`逐项迁入唯一SourceRights contract并删除旧表；旧attempt只在snapshot policy identity与fixture rights均可证明时迁移，不能证明则整次以`SOURCE_POLICY_IDENTITY_UNMIGRATABLE`失败。
- [x] official raw object先durable publish，再在一个transaction写attempt、normalized/filing records、quality、cursor和snapshot membership。
- [x] A股PDF无独立qualified semantic extractor时只保存filing identity/metadata/raw hash；不得由文件名、free text或caller mapping生成FinancialFactVersion。

## Migration, caller migration and deletion

- [x] migration preflight覆盖fresh、0012 empty/populated、mixed policy、missing member、hash conflict、unprovable rights与fault injection；失败码与Spec一致且不会留下active dual schema。
- [x] backup包含database与全部object blobs，并验证hash、size、count、SQLite integrity/FK；restore只到new root并验证domain invariants。
- [x] public sync/qualify、normalization、persistence、doctor/backup/restore、Skill/runbook、fixtures与tests全部迁入0013 contract。
- [x] 删除hard-coded `query@1`/`source@1`、old rights table、placeholder/default identities、direct SQL/caller official-fact fixtures、cleartext/guessed identity、disabled TLS、raw-text result和aggregator fallback。
- [x] 不引入whole Skill、mootdx、CNINFO Q&A、SSE/SZSE public-record placeholder、HKEX或StrategyValidation surface。

## Acceptance and verification

- [x] CNINFO与SZSE分别覆盖normal、legal empty、partial、stale、rate-limit、401/403、timeout、schema drift、wrong Security identity、published/available/retrieved、correction和malicious/oversize/wrong-MIME document。
- [x] 对filing dataset，calendar、price adjustment、T+1、suspension/price-limit格必须返回typed `not_applicable` reason，不可伪装pass；rights/authority仍required。
- [x] deterministic fixture replay通过；每个production source至少生成一次identity-bound live receipt。
- [x] narrow command通过：`python -m pytest -q tests/platform/test_data_sync_pit.py tests/platform/test_provider_qualification.py tests/platform/test_external_official_disclosure.py tests/platform/test_operations_backup_restore.py`。
- [x] 首个新DataProvider进入production后full phase gate通过：`python -m trading_platform.cli test --repo-root .`。
- [x] migration-0013 fresh/prior/populated/fault/rollback/restore、absence gates、`git diff --check`和code review全部通过。

## Commit scope

- [x] 一个local commit包含0013 schema/migration、CNINFO/SZSE adapters、public callers、persistence、fixtures/tests/docs、旧schema/path删除和本票evidence；实现仅使用标准库，依赖/NOTICE范围不变。
- [x] 精确stage本票owning paths；不提交live payload、external checkout、personal/provider data、secrets、gateway参数、`docs/data/**`或unrelated dirty；不push/PR。

## Evidence

- Narrow gate: `82 passed`（新增provable populated migration案例后最终重跑）。
- Full gate: `python -m trading_platform.cli test --repo-root .`；core `189 passed`，platform-1 `68 passed / 1 deselected`，platform-2 `100 passed / 3 skipped`，platform-3 `81 passed`，platform-4 `56 passed`，web `18 passed`；typed verifier总状态`passed`，duration `250.514s`。
- Production live receipts（2026-07-25，临时data roots，不进入仓库）：SZSE `artifact_ca81f3f93817a3e48d88214c`，CNINFO `artifact_415998f7fae3d9860998435d`；均为`qualified`、official authority、identity-bound snapshot。
- Code review关闭了迁移伪造rights、policy/member不一致、PIT排序、分页/批量边界、correction/freshness、混合数据集绕过、原子提交故障边界、错误时间戳与CNINFO/SZSE失败矩阵；未引入SEC/HK/Vibe/StrategyValidation runtime。
- `git diff --check`通过；最终absence audit不含hard-coded `query@1`/`source@1`、`legacy_identity`、SEC/HK/Vibe/StrategyValidation runtime symbol。
