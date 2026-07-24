# 12 — I01 ProviderJob@2、SourcePolicy 与 qualification receipt cutover

**What to build:** 让平台运营者继续通过唯一的 sync、daily、provider-qualify 与 acceptance application tasks 使用 Tushare-compatible market data，但所有 query、source selection、rights、failure disposition 与 live qualification identity 都由 typed ProviderJob@2 和 SourcePolicy 拥有。production qualification 必须形成 data-root 内可回查 command、attempt、object 与 snapshot lineage 的 receipt artifact；caller-authored live JSON 不再具有证明力。所有 caller、tests、Skill/operations docs 与配置示例原子迁移，旧字符串 dispatch、generic HTTP path、wire 参数泄漏和隐式 provider-order fallback 在本票删除。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

## Target interface and vertical slice

- [ ] 先在最高 public seam 写失败测试：sync、daily、provider-qualify 与 acceptance 只接受 ProviderJob@2；old job、caller live file、undeclared fallback 和 runtime provider class lookup 被拒绝。
- [ ] `DataProvider.fetch(TypedDatasetQuery)` 保持唯一 provider seam；Tushare-compatible 是 production adapter，FixtureProvider 是 deterministic test adapter。
- [ ] QueryPolicy@1 与 SourcePolicy@1 是 immutable typed values，拥有 canonical identity、source routes、authority、rights、freshness、completeness、retry/fallback mode 和 typed disposition；caller不能提交 endpoint、class、module或wire mapping。
- [ ] SourcePolicy 仅允许 `no_fallback` 或经过独立资格化的 `qualified_equivalent`；critical official role不得降级到 aggregator/secondary，未声明或退休实现永不参与 fallback。
- [ ] provider-qualify 通过现有 command receipt、artifact/object 与 Workflow/Data persistence owner 持久化 `ProviderQualificationReceipt@1`，绑定 request/query/source-policy、provider/adapter/code、attempt/raw/snapshot hashes与时间边界。
- [ ] acceptance 只接收 receipt artifact identity并从data root回查全部权威对象；伪造字段、孤立hash、JSON/boolean或非production command identity必须失败。
- [ ] 本票 database schema 明确不变；不得为policy routing或qualification另建registry/table/persistence path。

## Caller migration and deletion

- [ ] CLI、operations readiness、sync/daily tasks、provider qualification、acceptance、Skill instructions、examples与tests全部迁入ProviderJob@2和receipt artifact contract。
- [ ] 删除 `provider_type`、class lookup、generic `HttpJsonProvider`、orchestration-owned Tushare wire params、implicit tuple-order fallback、old codecs/defaults/aliases以及 `--live-qualification-file`。
- [ ] 删除只保护退休private seams的tests、fixtures、docs和exports；搜索证明active runtime/current docs无旧symbol或旧命令命中。
- [ ] 不修改个人data root、`docs/data/**`、外部upstream checkout或startup dirty assets。

## Acceptance and verification

- [ ] deterministic cases覆盖normal、legal empty、partial、stale、rate limit、401/403、timeout、schema drift、wrong Security identity、published/available/retrieved、calendar/adjustment/corporate-action/suspension-limit的supported或typed-unavailable disposition。
- [ ] sync/daily/provider-qualify幂等；每个fallback attempt持久化且substitution不冒充primary complete。
- [ ] narrow command通过：`python -m pytest -q tests/platform/test_data_sync_pit.py tests/platform/test_provider_qualification.py tests/platform/test_cli_application_tasks.py tests/platform/test_acceptance_evidence.py`。
- [ ] full phase gate通过：`python -m trading_platform.cli test --repo-root .`；报告每个named suite、duration、passed/failed/skipped/deselected/timeout和artifact。
- [ ] `git diff --check`、forbidden-symbol search、完整status/diff/staged diff均通过；有效code-review findings在关闭前修复。

## Commit scope

- [ ] 一个local commit同时包含ProviderJob@2/SourcePolicy/receipt实现、production/test caller迁移、tests、Skill/operations docs、旧路径删除与本票状态/evidence。
- [ ] 只精确stage本票owning paths；禁止`git add .`、`git add -A`，禁止夹带其他`.scratch`、用户dirty、secrets、gateway参数或provider data；不push/PR。
