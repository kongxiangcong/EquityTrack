# 完成隔离的 A股、美股、港股纵向验证切片

Type: `task`
Mode: `AFK`
Status: `resolved`
Blocked by: 03, 04, 05, 06, 07

## Question

不修改生产代码，在隔离验证资产中分别完成 A 股、美股、港股从资格化输入到 frozen evidence、公司研究/估值语义与策略验证候选结果的最小纵向切片；绑定 pinned upstream、source authority、PIT/identity、typed schema、artifact hashes 和精确命令结果，验证外部原始 HTML/PDF/自由文本/caller-authored JSON 不能成为权威结果，并暴露跨市场端点、接口或报告能力仍不满足 production 替换门的具体失败。
## Answer

决定与精确验收结果见 [A股、美股、港股隔离纵向验证切片](../research/market-validation-slice-decision.md)，输入 plan、单一离线 verifier 和 verifier-authored evidence 分别见 [market-validation-slices.json](../research/market-validation-slices.json)、[verify_market_validation_slices.py](../research/verify_market_validation_slices.py) 与 [market-validation-slice-evidence.json](../research/market-validation-slice-evidence.json)。

三个 pinned upstream checkout 的 HEAD/clean state、五份既有 qualification evidence 的 SHA-256、三套 deterministic parser replay（12/12、5/5、12/12）以及 Vibe production allowlist `[]` 均由 verifier 重新绑定。A 股、美股、港股各形成一个 `FrozenExternalEvidence@1` metadata-only artifact identity；三个 `authoritative_financial_fact_count` 均为 0，ResearchEvaluation 均为 `blocked + data_insufficient_memo`，Valuation 均为 `not_comparable`，StrategyValidation 均为 `blocked + STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE` 且 `result=null`。三个 production replacement gate 因各市场明确 PIT/identity/parser/rights/calendar/action/execution 缺口按预期全部失败，没有触发旧 provider fallback 或伪造 ready。

`raw_html`、`raw_pdf`、`free_text` 和 `caller_authored_json` 四类 authority injection 均以 `TYPED_OFFICIAL_FACT_REQUIRED` 拒绝；篡改任一输入 evidence hash 时 verifier 退出 1。最终主命令退出 0，semantic artifact manifest SHA-256 为 `c9867b798c56d3ebf786d6e543f1a7c96190195566b6b8509c99428cee2ccc39`。A 股证据仅保存 identity-match 布尔而没有具体证券 identity，因此切片明确冻结为 `CN:SZSE:UNRESOLVED-QUALIFICATION-SUBJECT` 并记录 `A_SHARE_SECURITY_IDENTITY_NOT_PERSISTED`，未凭上下文冒认证券。

本票只新增隔离研究/验收资产，没有修改生产代码，没有提升任何候选为 adopted，也没有进入票 09。
