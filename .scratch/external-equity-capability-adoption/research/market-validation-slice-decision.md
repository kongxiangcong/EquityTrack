# A股、美股、港股隔离纵向验证切片

Date: 2026-07-24
Scope: Wayfinder ticket 08；不修改生产代码，不授权 production adoption。

## 结论

三个市场都完成了从已资格化 observation 到 typed frozen metadata evidence、研究质量候选、估值候选和策略验证候选的最小纵向切片。隔离 verifier 本身通过，但三个 production replacement gate 均按预期失败：

| 市场 | Frozen evidence | ResearchEvaluation | Valuation | StrategyValidation | Production replacement |
|---|---|---|---|---|---|
| A 股 `CN:SZSE:UNRESOLVED-QUALIFICATION-SUBJECT` | `metadata_only` | `blocked` / `data_insufficient_memo` | `not_comparable` | `blocked` / no result | `failed` |
| 美股 `US:XNAS:AAPL` / CIK 0000320193 | `metadata_only` | `blocked` / `data_insufficient_memo` | `not_comparable` | `blocked` / no result | `failed` |
| 港股 `HK:XHKG:00700` | `metadata_only` | `blocked` / `data_insufficient_memo` | `not_comparable` | `blocked` / no result | `failed` |

这不是“验证失败后退回旧路径”。它证明当前证据只能支持明确 blocked 结果，不能支持 production 替换；没有旧 provider fallback、外部报告旁路或伪造的 ready result。

## 可复现资产

- [typed validation plan](market-validation-slices.json)
- [single offline verifier](verify_market_validation_slices.py)
- [verifier-authored evidence](market-validation-slice-evidence.json)

固定 SHA-256：

| Artifact | SHA-256 |
|---|---|
| `market-validation-slices.json` | `9c99f971dda19e5e5ae37773d340389225ef5893ecb18bbd6d87208279900ddc` |
| `verify_market_validation_slices.py` | `caf3b4b3b67903c146d45fe6dbb74ee2230c8e56b97265b2233b08a06b2df48b` |
| `market-validation-slice-evidence.json` | `6a5679cc7e6c98bd7a7310f9fb4a2eab1f1a8135f4f0483a6b88ea985ecebd57` |
| semantic artifact manifest | `c9867b798c56d3ebf786d6e543f1a7c96190195566b6b8509c99428cee2ccc39` |

`market-validation-slices.json` 只选择 subject 与 pinned evidence，不声明 pass。verifier 拒绝 unknown fields、错误市场覆盖、重复 identity、evidence hash mismatch、upstream HEAD mismatch/dirty checkout，并从已绑定 observation 自己推导所有 outcome。

## Pinned upstream 与输入证据

verifier 重新检查了三个外部 checkout 的 HEAD 与 clean state：

| Candidate | Commit | Worktree |
|---|---|---|
| `a-stock-data` | `06791b5a3159401524c10bd0e28aaebe415ce604` | clean |
| `global-stock-data` | `d52a8a0013363577bceb28ca876c88fe6c1a5aeb` | clean |
| `Vibe-Trading` | `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6` | clean |

输入只绑定既有资格化 metadata evidence：

| Evidence | SHA-256 |
|---|---|
| `a-stock-data-live-probe-evidence.json` | `70d6e7d4b8a2c5bd328d4eed4338446e3ad593e6a02eeb98a06dcc519ab45e32` |
| `a-stock-data-official-live-probe-evidence.json` | `0a39d4c1f9a72b4ca4157729fba15fcf2a7bae37e55be53dd2f453edb887d1ec` |
| `global-stock-data-live-probe-evidence.json` | `0b6ee4940eb023b1ff5aeeba3e6565e439f7770e5cbf3acb0b5578c564b95b1c` |
| `global-stock-data-official-cross-validation-evidence.json` | `2831b2904d998da4a28ba44e825f865d984dce1d720699fd04ba7d8acb95165c` |
| `vibe-trading-runtime-evidence.json` | `8b824b690b4914760e40f6eddb711b2d591cf32056581417d53c7f2684833c55` |

这些 evidence 没有保存 provider raw bodies 或关键财务值。verifier 因而只能冻结 source/document/security/time/hash metadata，`authoritative_financial_fact_count` 必须为零；它不能把 observation JSON 自己声明的布尔值升级成正式事实。

## A 股切片

输入证据：

- CNINFO HTTPS security map 记录“请求 identity 已找到”，但 evidence 没有保存该 identity 的具体值；
- CNINFO exact announcement 为 HTTP 200、3 rows、3 identity matches，带 publication time 和 response hash；
- SZSE announcement 为 HTTP 200、3 rows、3 identity matches，带 publication time 和 response hash；
- raw response/document bytes 未保留，`available_at` 未建立。

冻结记录绑定 CNINFO/SZSE authority、security/issuer、as-of、observation、response hash、publication state 和 verifier-side retrieval observation。它不包含财务值。

失败原因：

- `OFFICIAL_FACTS_NOT_NORMALIZED`
- `CRITICAL_FINANCIAL_FACTS_MISSING`
- `AVAILABLE_AT_UNPROVEN`
- `A_SHARE_SECURITY_IDENTITY_NOT_PERSISTED`
- `A_SHARE_CALENDAR_IDENTITY_MISSING`
- `A_SHARE_ADJUSTMENT_LINEAGE_MISSING`
- `A_SHARE_CORPORATE_ACTION_LINEAGE_MISSING`
- `A_SHARE_EXECUTION_RULES_UNQUALIFIED`

因此 CNINFO/SZSE 仍只是目标系统安全重写的 `adapt-code` protocol candidate；现成 parser、明文/disabled TLS、fallback 和 raw text path 仍拒绝。

## 美股切片

输入证据：

- SEC submissions AAPL 为 HTTP 200 JSON，绑定 response hash；
- SEC companyfacts AAPL 为 HTTP 200 JSON，绑定 response hash；
- raw bodies 未保留；当前仓库没有 target-owned SEC typed parser。

SEC 是 critical disclosure authority，但 raw JSON 本身不是 `ResearchEvaluationResult` 或估值输入。没有对 filing/accession/context/unit/amendment/coverage/availability 的完整 typed normalization，就不能产生关键事实。

失败原因：

- `OFFICIAL_FACTS_NOT_NORMALIZED`
- `CRITICAL_FINANCIAL_FACTS_MISSING`
- `AVAILABLE_AT_UNPROVEN`
- `SEC_TYPED_PARSER_NOT_IMPLEMENTED`
- `SEC_FILING_COVERAGE_NOT_FROZEN`
- `US_SECURITY_MASTER_HISTORY_MISSING`
- `US_CORPORATE_ACTION_LINEAGE_MISSING`
- `US_EXECUTION_RULES_UNQUALIFIED`

因此只保留 SEC official protocol knowledge 的 `adapt-code` 结论；`global-stock-data` parser、aggregator 行情/报告和 ticker-only security identity 仍拒绝。

## 港股切片

输入证据：

- HKEXnews 与 Tencent investor relations 的 2025 annual report 都是 HTTP 200 PDF；
- 两份文档均为 3,999,857 bytes；
- byte-identical SHA-256 为 `2a7547168077c3d9994af673125e77612e8656bc0f17ad189371d7e4088f4e98`；
- raw PDF 未保留，交叉验证只证明 document identity，不授予网页 scraper 自动访问权。

失败原因：

- `OFFICIAL_FACTS_NOT_NORMALIZED`
- `CRITICAL_FINANCIAL_FACTS_MISSING`
- `AVAILABLE_AT_UNPROVEN`
- `HKEX_AUTOMATION_RIGHTS_NOT_QUALIFIED`
- `HKEX_TYPED_ADAPTER_NOT_IMPLEMENTED`
- `HK_SECURITY_MASTER_HISTORY_MISSING`
- `HK_CORPORATE_ACTION_LINEAGE_MISSING`
- `HK_EXECUTION_RULES_UNQUALIFIED`

因此 HKEX website scraper 仍 `reject`，licensed IIS/feed 仍需独立授权资格化，issuer IR 仍是逐发行人的 `keep-local` source-policy 类别；不建立无许可 adapter 占位符。

## Research、valuation 与 strategy 语义

三个切片都满足以下 invariant：

1. 未得到 typed official facts 时，ResearchEvaluation 只能产生 `blocked` 与 `data_insufficient_memo`。
2. critical facts 与 selected-method inputs 缺失时，Valuation 为 `not_comparable`，`formal_value=null`。
3. Vibe runtime decision 必须仍为 entire MCP/backtest/Walk-Forward/bootstrap/Monte Carlo reject，production allowlist 必须为 `[]`。
4. 当前没有目标实现的 StrategyValidation engine，结果只能是 `blocked + STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`，`result=null`，不生成 strategy artifact。
5. 市场规则、calendar、adjustment、corporate actions、universe history 或 execution semantics 不完整时，不得用 synthetic fixture 宣称策略可信。

## Raw/caller authority 攻击

verifier 运行四个独立 negative admission case：

| Input kind | Result | Stable reason |
|---|---|---|
| `raw_html` | rejected | `TYPED_OFFICIAL_FACT_REQUIRED` |
| `raw_pdf` | rejected | `TYPED_OFFICIAL_FACT_REQUIRED` |
| `free_text` | rejected | `TYPED_OFFICIAL_FACT_REQUIRED` |
| `caller_authored_json` | rejected | `TYPED_OFFICIAL_FACT_REQUIRED` |

原始内容可成为 hash-bound source artifact，但在经过 target-owned typed parser、identity/PIT/source-policy/lineage gates 前不能成为权威结果。caller 不能提交 pass boolean、自由 financial facts、artifact draft 或 hash 来授权自己。

## 精确命令与结果

主验收：

```powershell
python .scratch/external-equity-capability-adoption/research/verify_market_validation_slices.py `
  --write-evidence .scratch/external-equity-capability-adoption/research/market-validation-slice-evidence.json
```

结果：

```text
market-validation-slices: 3 slices verified; 3 expected production gates failed; 4 raw-authority attacks rejected
artifact_manifest_sha256=c9867b798c56d3ebf786d6e543f1a7c96190195566b6b8509c99428cee2ccc39
exit code: 0
```

无写入重放产生相同 semantic manifest hash。verifier 内部按固定 script hash 执行：

- `node a-stock-data-fixture-replay.mjs`：12/12；
- `node a-stock-data-official-fixture-replay.mjs`：5/5；
- `node global-stock-data-fixture-replay.mjs`：12 passed / 0 failed。

这些 synthetic replays 证明上游 parser 的 unknown-to-zero、empty/error/schema collision、identity/PIT/adjustment/context/accession/coverage 丢失，不能成为成功的目标 adapter fixtures。

篡改测试把首个 evidence hash 改为错误值后运行同一 verifier：

```text
market-validation-slices: verification failed: VerificationFailure:
a-stock-data-live-probe-evidence.json: evidence hash mismatch ...
tamper_exit_code=1
```

## Production replacement gate

票 08 不提升任何候选为 adopted。三个市场共同仍缺：

- target-owned typed raw-artifact/frozen-evidence builder；
- Request@2 与 typed ResearchEvaluationPlan 的 production codec；
- 合格的 official disclosure parser、PIT availability 与 source-policy identity；
- typed critical facts 和估值方法输入；
- market calendar、security/universe history、adjustment/corporate-action lineage；
- StrategyValidation engine、artifact kind/lineage、ledger transaction 和真实 public caller；
- caller/test/docs/persistence/presentation 的原子切换及旧路径删除。

这些具体缺口进入票 09 的 blocker-first 单向迁移排序；本票没有修改生产代码，也没有进入票 09。
