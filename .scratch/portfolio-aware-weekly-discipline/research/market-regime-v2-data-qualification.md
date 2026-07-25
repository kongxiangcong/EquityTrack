# MarketRegime v2 数据资格与最小组件决定

研究日期：2026-07-25

范围：A 股、收盘后评估、下一交易日执行窗口

状态：研究结论完成；production 数据资格尚未完成

## 决定

MarketRegime v2 的**最小可解释目标包**应保留四个彼此不可替代的组件：

1. `market.trend`：固定 A 股-only benchmark `930903.CSI`（中证 A 股）的中短期方向；
2. `market.breadth`：每个 session 当时 `930903.CSI` PIT 成分横截面的上涨与站上中期均线比例；
3. `market.liquidity`：每个历史 session 当时同一 A 股 PIT 横截面的成交额总和相对历史的位置；
4. `market.volatility`：固定 benchmark `930903.CSI` 的已实现波动率及其历史位置。

`930903.CSI` 的 index identity、publisher、base metadata 与日线必须冻结；
index level 单位是 `index_point`，不是 CNY。它是 trend/volatility 的固定
基准，同时用其 per-session PIT constituent membership 作为
breadth/liquidity population。中证指数公司的 2026-06-30 factsheet 和
2022-12 V1.2 methodology 都明确：该指数覆盖 SSE、SZSE、BSE 符合条件的
A 股，样本空间不含存托凭证并排除 ST/*ST
（[official factsheet](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/930903factsheet.pdf)，
[official methodology](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/930903_Index_Methodology_cn.pdf)）。
runtime 仍必须以 typed `instrument_type=A_SHARE` 校验每个成员；任何 CDR
或无法确认的 instrument identity 都是 identity conflict/unknown，而不是
默默纳入。
成员资格必须按每个 session 的可得版本重建，不能用今天的成分回填历史。
停牌证券凭 session-specific constraint evidence 排除；breadth 另要求成员有
20 sessions 价格历史。liquidity 的 121-session 门槛属于**聚合后的市场总额
序列**：每个 session 都要先完成当时 eligible A 股横截面，新纳入成员只要
当日 `amount` 有效就立即贡献，不要求该成员自身拥有 121 日历史。

两份选定 benchmark 的可变官方文档已于
`2026-07-25T06:23:49.2568202Z` 至 `2026-07-25T06:24:05.9105763Z`
冻结到仓库外证据根
`E:\workspace\tradingSystem-runtime-evidence\market-regime-20260725-current\official-sources`：

- factsheet：454232 bytes，SHA-256
  `3034602167c40f555f64d872faa43798fd091c160b188e9ff1976cf2c1626f97`，
  文档内日期 `2026年6月30日`；
- methodology：997013 bytes，SHA-256
  `1c01eddac143261769819e02c9895901c1ae0bb20ab83dd859562f257838a5bf`，
  文档页眉标注 `2022年12月 /
  版本号 V1.2`。

仓库内只记录检索时间、字节数和 hash，不提交 PDF。
早先候选 `000985.CSI` 因官方 methodology 明确包含红筹存托凭证而被否决；
它不得作为本项目 trend/volatility 或 cross-section population。

行业轮动和资金流都不进入最小包。宏观、新闻、情绪、拥挤度也继续
禁用。当前领域实现已经把 `market.funds`、`market.industry_rotation`
以及后四项显式投影为 `unsupported`，而不是伪造分数
（[`domain/market.py:258-278`](../../../src/trading_platform/domain/market.py#L258-L278)）。

这个决定**不等于四组件已经具备 production 数据资格**。当前唯一
production market-data adapter 只声明交易日历和未复权个股日线为
supported；复权因子、公司行动、停牌与涨跌停 typed capability 仍为
unavailable（[`data/providers.py:177-186`](../../../src/trading_platform/data/providers.py#L177-L186)）。
当前 typed query union 只有 `trade_cal`、单一证券 `daily`、
`market_universe`、`official_filing` 和 `forecast_actual`
（[`domain/data.py:240-320`](../../../src/trading_platform/domain/data.py#L240-L320)），
没有宽基准指数序列、全市场日线横截面、行业成员/行业指数或资金流
query。已关闭 I01 的 production receipt 只证明 canonical sync 路径
完成了三个 dataset attempt，并没有证明 MarketRegime 所需的指数、
全市场横截面或历史窗口覆盖
（[`Issue 12:39-44`](../../external-equity-capability-adoption/issues/12-i01-provider-source-policy-receipt-cutover.md#L39-L44)）。

因此本票的 planning disposition 是
`blocked_data_qualification`；这不是已存在的 runtime enum。当前 runtime
只允许 `SnapshotStatus=blocked|limited|complete` 和 component reason
codes。后续实现必须先增加真正拥有语义的
typed query，并分别取得 identity-bound production qualification
receipt；在此之前，现有 deterministic fixture 只证明算法和失败关闭，
不能证明 production 数据可得。

### 2026-07-25 current production probe

在仓库外隔离 data root 上通过 canonical `provider-qualify` 运行
`ProviderJob@2`，没有把 credential、gateway 参数或 raw payload 写入本
研究资产。复现实验使用以下 redacted commands；`<configured-env>` 由本地
说明载入，未打印：

```text
python -m trading_platform.cli bootstrap --data-root <isolated-root>
$env:TUSHARE_TOKEN=<configured-env>
python -m trading_platform.cli provider-qualify --data-root <isolated-root> --job-file <ProviderJob@2>
```

首次根
`E:\workspace\tradingSystem-runtime-evidence\market-regime-20260725`
中 `market_universe` 与 `daily` complete，但 `trade_cal` 返回 typed
`PROVIDER_TRANSPORT_FAILED`，整次 qualification 正确失败。第二根
`...\market-regime-20260725-retry` 的三个 attempt complete，但旧
`as_of_at` 使成员全部被 `PIT_FUTURE_EXCLUDED`，没有生成 snapshot，
仍然失败。当前根
`...\market-regime-20260725-current` 首次也因 retrieval 晚于
13:55 cutoff 得到 `QUALIFICATION_RECEIPT_LINEAGE_INVALID`；使用新的
invocation 与 14:00 cutoff 后得到 `qualified` receipt
`artifact_61764aa1849a4401e8872dbb`：

- requested date `2026-07-25`，effective complete session
  `2026-07-24`；
- `trade_cal`、`market_universe`、`daily` 均为 complete；
- snapshot `snapshot_396d46c20615ab92c89797c0` 的 freshness `valid`、
  quality `pass`、coverage `1/1/0/0`；
- normalized evidence 只有 8 个日历记录、1 个 universe 成员与 5 个单证券
  daily 记录。

这份 current receipt 证明 canonical 单证券数据路径和 fail-closed/retry
语义当前可运行，反向证明它**没有**覆盖宽基准 65/141 日历史、全 A 股
20/120 日横截面或任何行业/资金流 dataset；不能把 `qualified` 这个
单证券 receipt 外推为 MarketRegime v2 ready。隔离证据保存在
`E:\workspace\tradingSystem-runtime-evidence\market-regime-20260725-current`
且不进入 Git。

### 2026-07-25 control-plane candidate probes

为回答“候选接口是否存在/有权限”，另以只读、redacted HTTP probe 调用
兼容协议；这不是 production authorization，也没有绕过未来 typed query
要求。实际复验从 `2026-07-25T06:17:13.4408954Z` 至
`2026-07-25T06:17:34.0658004Z`，每次只保留 api、redacted params、业务
code、row count、字段名和时间。等价 redacted 请求形状为：

```text
$env:TUSHARE_TOKEN=<configured-local-env>
Invoke-RestMethod -Method Post -Uri <configured-compatible-endpoint> `
  -ContentType application/json `
  -Body {"api_name":<api>,"token":"<configured-local-env>","params":<params>,"fields":""}
```

精确 requests 为：
`index_classify(src=SW2021,level=L1)`、
`index_member(index_code=801010.SI)`、
`sw_daily(ts_code=801010.SI,start_date=20260701,end_date=20260724)`、
`moneyflow(ts_code=002897.SZ,start_date=20260701,end_date=20260724)`、
`moneyflow_hsgt(start_date=20260701,end_date=20260724)`、
`margin_detail(ts_code=002897.SZ,start_date=20260701,end_date=20260724)`、
`index_basic(ts_code=000985.CSI)` 和
`index_daily(ts_code=000985.CSI,start_date=20260401,end_date=20260724)`。
全部返回业务 code `0`。redacted metadata 保存在仓库外
`E:\workspace\tradingSystem-runtime-evidence\market-regime-20260725-current\candidate-probe-evidence.json`
（SHA-256
`cd8e75446c8b090d6d008bed289da95ff00f3ec69d7c48b07b20dbb6593f6898`），
其中 transport identity SHA-256 为
`5ac73c2a6bda774e50c5c2fd0d7d468d38b792189fa1b44df09bd9007a8dea68`；
endpoint、credential 和 raw payload 均未保留。

Spec 复审识别到 `000985.CSI` 点位本身包含 CDR 后，又从
`2026-07-25T06:23:31.6776918Z` 至 `2026-07-25T06:23:38.6269895Z`
以同一 redacted 请求形状复验 A 股-only 候选：
`index_basic(ts_code=930903.CSI)` 返回 1 行，
`index_daily(ts_code=930903.CSI,start_date=20260401,end_date=20260724)`
返回 78 行，两者业务 code 均为 `0`；但
`index_member(index_code=930903.CSI)` 业务 code `0` 且返回 0 行。
这使 index identity/daily 仍只是 control-plane candidate，constituent
membership 明确保持 unknown/unavailable，不能把 legal-empty 解释为“指数
无成分”。补充 metadata 保存在仓库外
`E:\workspace\tradingSystem-runtime-evidence\market-regime-20260725-current\a-share-benchmark-probe-evidence.json`
（SHA-256
`09e7a6a5c6c3b7533fc7dc5df6987616b1fb42435eb93dbded34d84c448641ba`）。

| 候选 | probe 结果 | 仍缺的 production contract | 决定 |
|---|---|---|---|
| A 股-only 固定宽基准 | `index_basic(930903.CSI)` 返回 1 行，确认中证 A 股 identity/publisher；`index_daily` 返回 78 行，字段含 OHLC、`pre_close/change/pct_chg/vol/amount`。 | 无 typed index query、`index_point` normalizer、SourcePolicy route、PIT/history/identity receipt；production 必须保留 typed timeout/retry。 | 选为 trend/volatility target，当前 unavailable。 |
| A 股 PIT population | official methodology 明确 `930903` 只含 SSE/SZSE/BSE A 股并排除 ST/*ST；`index_member(930903.CSI)` 返回 legal-empty。 | legal-empty 不证明 constituent membership；缺 per-session version、typed instrument identity、SourcePolicy、PIT/coverage/rights/cache/failure contract 和 receipt。 | 选为 breadth/liquidity target population，当前 blocked/unknown。 |
| 被否决宽基准 | `index_basic/index_daily(000985.CSI)` 可调用，但 official methodology 明确其包含红筹存托凭证。 | 与 A-share-only scope 冲突；不能靠过滤横截面修正已发布指数点位。 | **拒绝用于所有四组件。** |
| 行业分类/行业行情 | `index_classify(SW2021,L1)` 31 行；`index_member(801010.SI)` 549 行，含 `in_date/out_date/is_new`；`sw_daily` 18 行，含 OHLC、amount、估值与市值字段。 | 未证明 taxonomy revision/`published_at`/`available_at`、成员修订历史、跨行业完整覆盖、rights/cache/failure contract；无 typed query/receipt。 | 第一版 disabled；probe 只证明候选端点与当前 entitlement。 |
| 个股成交方向标签 | `moneyflow` 18 行，含分档买卖量额与 `net_mf_*`。 | “主力”分档是 provider taxonomy；无 authority、单位 normalizer、publication/availability、全市场 coverage 或 receipt。 | 第一版 disabled。 |
| 跨境流 | `moneyflow_hsgt` 17 行，含沪/深/港与 north/south money。 | 不是全 A 股证券级资金方向；可用性/历史口径/发布时点与政策变更未资格化。 | 第一版 disabled。 |
| 融资融券 | `margin_detail` 17 行，含融资融券余额、买入、偿还、余量。 | 是杠杆余额而非通用“资金流”；缺 typed identity、单位/PIT/coverage/cache/receipt。 | 第一版 disabled。 |

因此行业与资金候选不是因“接口不存在”而 disabled，而是因为 endpoint
entitlement 不能替代完整、可审计的 production contract；成交额继续只
表达 liquidity，不能被重命名成资金净流入。

## 组件资格矩阵

| 候选 | 最小解释与现有算法证据 | 当前 canonical dataset / query / provider | 字段、单位、时间与 PIT | 覆盖、历史、freshness、cache 与失败语义 | 决定 |
|---|---|---|---|---|---|
| 趋势 | `930903.CSI` 收盘点位高于/低于 SMA20、SMA60，并用 5 个交易日前的 SMA20 判断斜率；至少需要 65 个收盘观测，输出 `close`、`sma20`、`sma60`、`sma20_5d_prior` 和 `up/down/mixed`（[`domain/market.py:296-328`](../../../src/trading_platform/domain/market.py#L296-L328)）。 | `daily` / `DailyOhlcvQuery` / Tushare-compatible 只接受一个证券代码与 venue；adapter 把它翻译成单证券日线请求（[`domain/data.py:248-264`](../../../src/trading_platform/domain/data.py#L248-L264)，[`data/providers.py:108-125`](../../../src/trading_platform/data/providers.py#L108-L125)）。当前没有宽基准指数 typed query；不能假设个股 `daily` 可代替指数日线。 | 必需字段：`930903.CSI` identity/publisher/base metadata、`session_date`、`close`（`index_point`）、`published_at`、`available_at`、`retrieved_at`。现有股票 normalizer 的 CNY/hand/thousand-CNY 合同不能复用于 index level。 | 覆盖固定为版本化 `930903.CSI` identity；历史至少 65 个完整交易日。freshness 必须来自该 dataset 的 `SourceRoute.freshness_max_stale_days`，不能写死（[`domain/data.py:130-168`](../../../src/trading_platform/domain/data.py#L130-L168)）。raw 以 SHA-256 内容寻址，attempt 保存 cache disposition 和时间（[`data/repository.py:192-225`](../../../src/trading_platform/data/repository.py#L192-L225)）。缺指数 query、少于 65 日、身份冲突、stale、schema drift 或 fetch failure 均为 blocked/unknown。 | **最小包保留；当前 unavailable，等待 index typed query + live receipt。** |
| 宽度 | 对每个 session 当时的 `930903.CSI` PIT 成分计算上涨比例和站上 SMA20 比例；两者同时不低于 0.6 为 `broad`，同时不高于 0.4 为 `narrow`，否则 `mixed`。runtime 再校验 `instrument_type=A_SHARE`；缺少 20 日价格历史明示 excluded；未解释 missing 为 `COVERAGE_INCOMPLETE`（[`domain/market.py:331-380`](../../../src/trading_platform/domain/market.py#L331-L380)）。 | 当前 `market_universe`/`daily` 都是单证券 query，normalizer 也把返回行绑定到请求中的同一个 `security_id`，不能表达 index membership、typed instrument identity 或全横截面（[`domain/data.py:266-280`](../../../src/trading_platform/domain/data.py#L266-L280)，[`data/normalizer.py:66-68`](../../../src/trading_platform/data/normalizer.py#L66-L68)）。control-plane member probe legal-empty。 | 必需字段：per-session constituent version、stable `security_id`/venue、typed `instrument_type`、member effective interval、official methodology/version、停牌 evidence、`close`（CNY/share）与四时间 lineage。ST/*ST 按 official index methodology excluded，不是缺失；非 A 股或 identity unknown 阻断；停牌与价格历史不足明示 excluded。当前 `UniverseMember`/静态 snapshot 不能表达完整 per-session constituent lineage（[`persistence/market.py:37-50`](../../../src/trading_platform/persistence/market.py#L37-L50)）。比例为 0–1。 | expected/eligible/excluded/missing 绑定每个 session 当时可得的 constituent version，禁止当前成员回填历史。legal-empty、任何未解释 missing 均 blocked；缓存、freshness 与失败语义同 SourcePolicy。 | **最小包保留；当前 unavailable，等待 index constituent + instrument identity + cross-section typed query + coverage receipt。** |
| 流动性 | 对每个历史 session 当时的 `930903.CSI` PIT 成分汇总当日有效 `amount`，再把当前 session 总额与此前 120–252 个完整 session 总额比较 percentile；不低于 0.7 为 `ample`，不高于 0.3 为 `thin`，否则 `normal`（[`domain/market.py:383-436`](../../../src/trading_platform/domain/market.py#L383-L436)）。 | 与宽度共用未来 constituent/instrument/cross-section query；当前只有单证券 `DailyOhlcvQuery`（[`domain/data.py:248-264`](../../../src/trading_platform/domain/data.py#L248-L264)）。Tushare-compatible test contract包含 `amount`，但只证明 adapter schema（[`test_provider_qualification.py:32`](../../../tests/platform/test_provider_qualification.py#L32)）。 | `amount` 为 `thousand_cny`；`total_amount` 仍为千元人民币，percentile 为 0–1（[`data/normalizer.py:59-63`](../../../src/trading_platform/data/normalizer.py#L59-L63)）。每个 historical total 绑定该 session 的 constituent version、member versions、A 股 identity 与 PIT cutoff。 | 每个 session 重建当时成分并形成完整 A 股横截面；ST/*ST 和不满足 official listing rule 的证券明示 excluded。新纳入 A 股只要当日 `amount` 有效就立即贡献，不要求其自身有 121 日历史。至少需要当前加此前 120 个、最多当前加此前 252 个完整 PIT 聚合横截面；legal-empty、任何未解释 amount/coverage 缺口、partial 或 stale 均 blocked，绝不补零。不能把当前静态 universe tuple 用于历史窗口，否则产生 survivorship/new-listing bias。 | **最小包保留；当前 unavailable，等待 per-session constituents + instrument identity + cross-section amount query + 121 个完整聚合 session receipt。** |
| 波动率 | 用 `930903.CSI` 最近 21 个 index-point close 形成 20 个对数收益，按 252 年化；当前值相对最多 252 个先前窗口求 percentile。现有最小门槛为 141 个观测（[`domain/market.py:439-469`](../../../src/trading_platform/domain/market.py#L439-L469)，[`domain/market.py:553-566`](../../../src/trading_platform/domain/market.py#L553-L566)）。 | 与趋势共用尚未实现的 index typed query；当前单证券 `daily` 不能证明指数数据角色。 | identity/time/unit 与趋势相同；`annualized_volatility` 和 percentile 为无量纲，冻结 252 年化常数、20 日窗口和样本 identity。 | 固定 `930903.CSI`，至少 141 个观测；完整 252 个 prior percentile 需 273 个。少历史、stale、identity mismatch、非正点位或 timeout 均 blocked。 | **最小包保留；当前 unavailable，等待 index typed query + 141/273 日 receipt。** |
| 行业轮动 | control-plane probe 证明 SW2021 L1 分类、带 `in_date/out_date` 成员和行业日线候选当前有 entitlement；当前实现仍只返回 `unsupported`（[`domain/market.py:258-278`](../../../src/trading_platform/domain/market.py#L258-L278)）。 | 无行业 typed query/SourcePolicy route；候选字段见上表。 | 缺 taxonomy revision、publisher availability、PIT 修订、单位 normalizer。 | 无 receipt、全行业 coverage/history/freshness/cache 和 legal-empty/partial/schema/timeout contract。 | **第一版 disabled；不得用板块热度、概念榜或静态当前分类替代。** |
| 资金流 | probe 证明 `moneyflow`、`moneyflow_hsgt`、`margin_detail` 当前有 entitlement，但三者是不同领域语义；当前 `market.funds` 为 `unsupported`（[`domain/market.py:258-278`](../../../src/trading_platform/domain/market.py#L258-L278)）。 | 无资金流 typed query/SourcePolicy route；候选字段见上表。 | 缺 canonical taxonomy/单位、publication/availability；成交额不能改名为净流入。 | 无 receipt、全市场覆盖、历史分布、freshness/cache 和 legal-empty/partial/schema/timeout contract。 | **第一版 disabled；流动性只回答交易活跃度，不冒充资金方向。** |

## 为什么四个组件缺一不可

- 趋势只回答基准价格方向，不能说明上涨是否由少数大权重证券驱动；宽度补足
  横截面参与度。现有算法也分别以一个 benchmark 与全 universe 为输入
  （[`domain/market.py:153-223`](../../../src/trading_platform/domain/market.py#L153-L223)）。
- 流动性回答当前市场成交是否相对充足，不回答价格方向；波动率回答价格路径
  的不稳定程度，不回答上涨参与度。两者使用不同输入聚合与不同历史分布
  （[`domain/market.py:383-469`](../../../src/trading_platform/domain/market.py#L383-L469)）。
- 四者只产生可审计的状态和原始量，不合成为黑箱“风险偏好分”。任何一个
  component blocked 时保留其 `reason_code`、coverage 和 evidence refs；
  snapshot 在 freshness/quality/series 缺失时整体 fail closed
  （[`domain/market.py:224-293`](../../../src/trading_platform/domain/market.py#L224-L293)）。

## 必须补齐的 production 资格证据

后续实现票在宣称 MarketRegime v2 ready 前，至少要通过以下同一 canonical
路径的资格检查：

1. 为 `930903.CSI` index identity、per-session constituents、A 股
   instrument identity 和横截面行情定义不可混淆的 typed query；caller
   不能提交 endpoint、provider class 或 wire params。`DataProvider.fetch`
   仍是唯一 provider seam
   （[`domain/data.py:397-405`](../../../src/trading_platform/domain/data.py#L397-L405)）。
2. 每个 dataset 都要进入 `SourcePolicy@1` route，明确 authority、rights、
   completeness、freshness、retry、fallback 和 failure disposition；
   undeclared route 必须失败
   （[`domain/data.py:171-230`](../../../src/trading_platform/domain/data.py#L171-L230)）。
   当前 preconfigured structured policy 仅覆盖 `trade_cal`、
   `market_universe`、`daily`，三者都是最多 stale 1 日、required、单次
   attempt、no fallback、failure block；未来指数/横截面 route 必须自行
   资格化，不能继承一个未声明的默认值
   （[`provider_config.py:79-95`](../../../src/trading_platform/provider_config.py#L79-L95)）。
3. production qualification receipt 必须绑定 provider/adapter/code/transport、
   query policy、source policy、attempt/raw hash、snapshot identity、coverage、
   quality 与时间；required dataset 不完整、quality 非 pass 或 coverage missing
   使 receipt failed
   （[`provider_qualification.py:157-225`](../../../src/trading_platform/provider_qualification.py#L157-L225)）。
4. PIT snapshot 只接纳 `available_at <= as_of_at` 的版本；repository 已将未来
   可用记录排除并记录 `PIT_FUTURE_EXCLUDED`
   （[`data/repository.py:330-364`](../../../src/trading_platform/data/repository.py#L330-L364)）。
5. 测试必须同时覆盖 legal empty、partial、stale、rate limit、401/403、
   timeout、schema drift、wrong Security identity、单位错误、历史不足和
   横截面缺口；I01 已把这些定义为 provider contract 的验收边界
   （[`Issue 12:26-32`](../../external-equity-capability-adoption/issues/12-i01-provider-source-policy-receipt-cutover.md#L26-L32)）。

## Official evidence 与研究工作流边界

MarketRegime 的四个最小组件是结构化市场数据，不会把公告“情绪”塞入状态分。
当前 production 范围仅为 A 股；Tushare-compatible market data 与
CNINFO/SZSE official disclosure 是已授权角色
（[`Issue 14:11`](../../external-equity-capability-adoption/issues/14-i03-sec-official-disclosure.md#L11)）。
CNINFO/SZSE adapters 已实现 Security/issuer/document identity、PIT 三时间、
correction/completeness、rights 和 typed failure translation，并有各自
identity-bound live receipt
（[`Issue 13:11-12`](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md#L11-L12)，
[`Issue 13:45-46`](../../external-equity-capability-adoption/issues/13-i02-a-share-official-disclosure-0013.md#L45-L46)）。
SSE、BSE 和公司正式 IR ingestion 没有对应 production 实现或 receipt，
继续是 future/unavailable；缺失不能解释为“无事件”。

未来 MarketRegime snapshot 只能以 frozen identity 进入
`ResearchEvaluationPlan@1` 或计划指标。研究请求仍由唯一
`ResearchWorkflow` 管理，artifacts 和 `ResearchDecisionView@2` 由
`WorkflowLedger` 原子持久化；I04 已验证 JSON/HTML/PDF/XLSX/Web/archive
只投影同一个 View@2
（[`Issue 15:3`](../../external-equity-capability-adoption/issues/15-i04-research-evaluation-0014-pdf.md#L3)）。
`WorkflowLedgerPort` 也是 qualification receipt 的 commit/load owner
（[`application/workflow_ledger.py:475-500`](../../../src/trading_platform/application/workflow_ledger.py#L475-L500)，
[`application/workflow_ledger.py:551-553`](../../../src/trading_platform/application/workflow_ledger.py#L551-L553)）。

`StrategyValidation` 保持 unavailable：显式请求只能得到
`requested_unavailable` 和
`STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE`
（[`domain/research_evaluation.py:26-28`](../../../src/trading_platform/domain/research_evaluation.py#L26-L28)，
[`domain/research_evaluation.py:98-105`](../../../src/trading_platform/domain/research_evaluation.py#L98-L105)）。
它不是 MarketRegime 数据资格的一部分，也不阻断研究、计划草稿或计划评估；
本决定不引入 Vibe-Trading、回测、broker、order、自动交易或盘中做 T。

## 对后续票据的可消费结论

- `07` 原型只能显示四个 component 的明确状态、值、coverage、freshness 和
  reason；当前没有 production receipt 时显示“数据资格未完成”，不能用
  mock 分数冒充真实市场状态。
- `08` 指标目录可预留四个 typed metric group，但只有绑定 frozen
  MarketRegime snapshot identity 的值才能参与规则；blocked/unknown 传播为
  `unable_to_determine` 或 blocked。现有 rule evaluator 已把 unknown 和
  blocked 分开传播
  （[`domain/market.py:650-674`](../../../src/trading_platform/domain/market.py#L650-L674)）。
- 行业轮动、资金流、宏观、新闻、情绪和拥挤度均不进入第一版 acceptance；
  未来若要加入，必须各自完成 typed query、SourcePolicy、PIT、coverage、
  history、cache、typed failure 和 production live receipt，不能复用
  “热度”字符串或 caller-authored JSON。
