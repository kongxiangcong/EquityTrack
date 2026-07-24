# 14 — I03 SEC OfficialDisclosure vertical slice

**What to build:** 让平台运营者通过同一个 public sync 与 provider-qualify path，为具有canonical Security/issuer/CIK identity的美股获取 SEC submissions、companyfacts 与 Archives documents；adapter按照SEC访问政策、truthful operator identity、rate/Retry-After、PIT、amendment/context/unit与raw hash规则，把合格filing/facts写入0013唯一schema和DataSnapshot。任何ticker-only、caller-authored、raw-JSON-to-research或aggregator fallback路径在同一票删除。

**Blocked by:** 13 — I02 A股 OfficialDisclosure vertical slice 与 migration 0013.

**Status:** ready-for-agent

## Target interface and vertical slice

- [ ] 先在public sync/provider-qualify seam写失败测试，证明caller只提交typed SEC official query、canonical identity与network authorization。
- [ ] cohesive SEC production adapter完整拥有submissions/companyfacts/Archives protocol、truthful User-Agent/operator contact、rate/Retry-After、CIK/accession/document/context/unit/scale/period/amendment/coverage/PIT/hash与typed failure。
- [ ] DataProvider保持唯一port；SEC production adapter与deterministic FixtureProvider是两个合理adapters，不新建SEC service/registry/port。
- [ ] 使用0013的唯一QueryPolicy/SourcePolicy/SourceRights/OfficialFilingVersion/FinancialFactVersion/DataSnapshot schema；本票不新增database schema或parallel persistence。
- [ ] companyfacts只在taxonomy/concept/context/period/unit/value/source fact identity完整且与filing/security/PIT一致时进入snapshot；unknown不等于zero。
- [ ] raw submissions/companyfacts/document objects先durable publish，accepted typed records与snapshot membership在single transaction提交。

## Caller migration and deletion

- [ ] public sync/qualify、normalization/persistence、doctor/backup/archive、Skill/runbook、fixtures、NOTICE与tests完成SEC role迁移。
- [ ] 删除generic/ticker-only/caller SEC facts、raw SEC JSON直达research、upstream Skill parser、Yahoo/aggregator fallback和任何第二security master。
- [ ] HKEX website、issuer-IR registry、licensed-feed placeholder与Vibe/StrategyValidation surface保持不存在。
- [ ] SEC operator contact只来自本地approved config/env identity；不得把个人信息、secret或完整URL params写入logs/artifacts。

## Acceptance and verification

- [ ] fixtures覆盖normal、legal empty、partial、stale、rate-limit、401/403、timeout、schema drift、wrong ticker/CIK/listing/accession、published/available/retrieved、amendment/restatement、context/unit/scale和coverage。
- [ ] filing dataset的calendar/price-adjustment/T+1/suspension/price-limit格返回typed not-applicable；amendment/correction semantics必须通过。
- [ ] deterministic replay字节/identity稳定；真实connectivity probe生成CIK/accession、command receipt、attempt/raw/snapshot hash绑定的qualification artifact。
- [ ] narrow command通过：`python -m pytest -q tests/platform/test_data_sync_pit.py tests/platform/test_provider_qualification.py tests/platform/test_external_official_disclosure.py`。
- [ ] slice verifier通过：`python .scratch/external-equity-capability-adoption/research/verify_market_validation_slices.py`。
- [ ] full phase gate通过：`python -m trading_platform.cli test --repo-root .`；absence gates、`git diff --check`和code review无未处理finding。

## Commit scope

- [ ] 一个local commit包含SEC adapter、public callers、0013 persistence usage、fixtures/tests/docs/NOTICE、旧SEC/aggregator paths删除和本票evidence。
- [ ] 精确stage本票owning paths；不提交live raw filings、operator secret/contact value、external checkout、personal/provider data、gateway参数或unrelated dirty；不push/PR。
