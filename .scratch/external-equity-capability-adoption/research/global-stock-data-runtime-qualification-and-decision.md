# `global-stock-data` 运行资格化与采用决定

## 决定

固定对象：

- canonical repository：`https://github.com/simonlin1212/global-stock-data`
- commit：`d52a8a0013363577bceb28ca876c88fe6c1a5aeb`
- upstream tag/version：`v1.0.1` / `1.0.1`
- license：Apache-2.0（只覆盖上游代码，不覆盖第三方数据权利）
- 资格化日期：2026-07-24

最终结论：

1. `global-stock-data` 整体 `reject`。它是一个 1,437 行 Markdown Skill 与内嵌自由 Python，
   没有 package、lock、tests、CI、fixture 或 typed failure contract，不能成为 production
   dependency，也不得由 CLI、Web 或 research workflow 直接执行。
2. 上游全部 Yahoo、东方财富、新浪、腾讯美股/港股行情、K 线、财务、筛选、期权、新闻、
   机构持仓和资金流端点及现成 parser 均 `reject`。真实 probe 的 200 只证明可达；平台条款、
   数据 entitlement、缓存/再分发权、PIT、证券身份、字段版本与失败语义仍不合格。
3. SEC submissions、companyfacts、Archives 和 ticker discovery 的**官方协议知识**
   `adapt-code`；上游现成 SEC parser `reject`。后续只能在本仓库唯一
   `OfficialDisclosure` / `DataProvider` path 中重写，不能复制 Skill 函数或保留双路径。
4. `company_tickers.json` 只可做有 snapshot identity 的 current discovery，不得成为第二个
   security master，也不得用 ticker 单独证明历史证券身份。
5. 上游没有 HKEXnews、HKEX IIS 或公司 IR 实现，因而没有可采用的港股官方 adapter。
   HKEXnews 网页抓取 `reject`；获许可的 IIS/feed 是未来独立资格项，本票不建占位符。
   公司 IR 保留为逐发行人资格化的 `keep-local` source-policy 类别。
6. MA/EMA/MACD/RSI/KDJ/Bollinger 纯计算 `keep-local`。它们不代表外部数据变化点，复制会建立
   第二套指标路径。
7. 当前仓库 targeted runtime search 没有发现已有 SEC/HKEX adapter，只发现
   `skills/references` 和 validator 中的 source-policy 名称。因此 SEC 官方协议仍是新增
   `adapt-code` 候选，而不是把现有 production 实现重新命名为 adopted。

本决定收紧票 02 的早期候选：美股/港股日频 OHLCV 不再保留从本上游 `adapt-code` 的可能性；
Yahoo chart 与全部聚合行情 parser 现在均为 `reject`。票 02 只是调查前 frontier，不构成 adoption。

## 隔离环境与依赖

上游 checkout 位于仓库外：

`E:\workspace\tradingSystem-upstreams\global-stock-data`

资格化环境位于该 checkout 内：

`E:\workspace\tradingSystem-upstreams\global-stock-data\.venv-qualification`

执行结果：

| 项目 | 结果 |
|---|---|
| checkout | clean tracked tree；HEAD 与 pinned commit 一致 |
| Python | CPython `3.11.15` |
| installer | `uv 0.11.17` |
| declared dependency | 上游只声明 `requests`，无版本范围与 lock |
| resolved dependency | `requests 2.34.2`、`urllib3 2.7.0`、`certifi 2026.7.22`、`charset-normalizer 3.4.9`、`idna 3.18` |
| dependency check | `uv pip check`：5 packages compatible |
| project environment | 未安装或修改任何依赖 |

隔离环境只用于审计。决定为 `reject` 的 Skill 不会把这个 venv 带入 production，也不会提交外部
checkout。

## 运行证据

### Deterministic fixture replay

证据脚本：

- [`global-stock-data-fixture-replay.mjs`](global-stock-data-fixture-replay.mjs)

命令：

```powershell
node .scratch/external-equity-capability-adoption/research/global-stock-data-fixture-replay.mjs
```

结果：12 passed、0 failed，约 1.1 秒。覆盖：

- Yahoo `None`/缺项被静默提升为零；
- Yahoo 丢弃 `adjclose`、split/dividend events 与 exchange timezone；
- magic-array 空字段变零，短响应、拦截页与真正无数据都变 `{}`；
- 东财错误响应、空结果和身份失败都变 `{}`，`f59` 可无版本地改变价格缩放；
- SEC recent 被静默截断至 50，历史分片不读，多 ticker 只取第一个；
- SEC filing 丢失 `acceptanceDateTime` 与 `reportDate`；
- companyfacts 任意选单位、丢失 `start` / `accn` / `frame`、只取最后 20 项；
- 非 `us-gaap`、unknown metric 与真正无事实都变 `[]`；
- 所有结果缺少 `retrieved_at`、raw hash 与 adapter identity。

这些是当前 parser 行为的最小可重复证明，不是未来 adapter 的 fixture。未来 adapter 必须建立新的
official-schema fixtures，不能把这些宽松输出 shape 当兼容合同。

### Live connectivity

证据：

- [`global-stock-data-live-probe.py`](global-stock-data-live-probe.py)
- [`global-stock-data-live-probe-evidence.json`](global-stock-data-live-probe-evidence.json)

最终命令：

```powershell
E:\workspace\tradingSystem-upstreams\global-stock-data\.venv-qualification\Scripts\python.exe `
  .scratch/external-equity-capability-adoption/research/global-stock-data-live-probe.py
```

结果：命令 exit 0，13.1 秒；没有保存响应 body，只保存 status、content type、size、SHA-256、
schema 摘要、duration 和官方交叉验证字段。

| Probe | 结果 | 资格解释 |
|---|---|---|
| Yahoo chart `AAPL` | 200 JSON，1,599 bytes | 可达，不证明自动访问、持久化、schema 或数据权 |
| Yahoo chart `0700.HK` | 200 JSON，1,555 bytes | 同上；不能填补港股官方 disclosure/corporate-action contract |
| Eastmoney US quote | 502 HTML | 不能与 valid empty 区分；上游会在 JSON decode 或空值语义处失败 |
| Eastmoney HK quote | 502 HTML | 同上 |
| Sina US/HK quote | 200 JavaScript | magic-array 成功不构成正式 API/schema/rights |
| Tencent US/HK quote | 200 text/html | magic-array 成功不构成正式 API/schema/rights |
| SEC company tickers | 403 HTML | discovery endpoint 外部失败；不得解释为空映射或做 fallback |
| SEC submissions AAPL | 200 JSON，164,394 bytes | 官方协议可达，保留完整 PIT/coverage 后可适配 |
| SEC companyfacts AAPL | 200 JSON，3,748,682 bytes | 官方协议可达，保留 context/unit/accession 后可适配 |

本次 audit User-Agent 故意标注为 non-production 且没有伪造联系地址，证据明确记录
`production_user_agent_compliant=false`。因此 SEC 403 不是“偶发成功也算通过”，而是 future
adapter 必须由 deployment 配置真实可联系身份、执行全局不超过 10 requests/second、处理
`Retry-After` 和使用 nightly bulk policy 的 admission gate。

### SEC official cross-validation

submissions 与 companyfacts 规范化后的 CIK 都是 `0000320193`，匹配为 true。submissions 同时
给出 `AAPL` / `Nasdaq` identity、1,000 条 recent rows 和历史分片指针。

最新 10-K identity：

| 字段 | 值 |
|---|---|
| form | `10-K` |
| filing date | `2025-10-31` |
| report date | `2025-09-27` |
| acceptance / availability candidate | `2025-10-31T10:01:26.000Z` |
| accession | `0000320193-25-000079` |
| primary document | `aapl-20250927.htm` |

companyfacts 包含 `dei` 与 `us-gaap`、505 concepts、6 种单位；427 个 fact entries 通过 accession
连接到该 10-K。它证明官方 payload 具有上游 parser 丢弃的 PIT、context、unit 和 filing lineage。

本轮 `company_tickers.json` 为 403，所以 `ticker_map_normalized_cik_match=null`，没有伪造成
pass。ticker map 不是关键事实 authority；submissions 与 companyfacts 的 CIK/filing lineage
仍完成交叉验证。未来 discovery adapter 必须把 403 作为 typed external failure。

### HKEXnews 与公司 IR

证据：

- [`global-stock-data-official-cross-validation-evidence.json`](global-stock-data-official-cross-validation-evidence.json)

对腾讯 2025 年报做了单文档、只读人工资格化：

| 来源 | identity | bytes | SHA-256 |
|---|---|---:|---|
| HKEXnews | `00700` / `80700`，2026-04-09 17:21，Annual Report | 3,999,857 | `2a7547168077c3d9994af673125e77612e8656bc0f17ad189371d7e4088f4e98` |
| Tencent IR | 同一 2025 annual report | 3,999,857 | `2a7547168077c3d9994af673125e77612e8656bc0f17ad189371d7e4088f4e98` |

两份 PDF byte-identical，证明发行人 IR 可作为该监管文档的第一方镜像交叉验证。它不授权
HKEXnews 网页 scraper，也不证明所有发行人 IR 有统一自动访问、缓存或再分发权。

## 字段、身份、PIT 与公司行动门禁

### SEC future adapter

唯一允许进入后续 Spec 的路径：

```text
EvidenceSnapshot / DataSynchronization
  -> OfficialDisclosure DataProvider
      -> SecEdgarAdapter
          submissions + companyfacts + Archives
```

它必须拥有完整协议翻译而不是 pass-through：

- typed issuer + security identity；CIK 是 issuer identity，listing/ticker 另有有效期和 snapshot；
- `requested_date`、`effective_session_date`、`as_of_at`、`published_at`、
  `available_at`、`retrieved_at` 分离；
- accession、form、amendment、report period、acceptance time、primary document、
  raw content hash 与 adapter code/config hash；
- submissions recent + historical shards 的 coverage；
- taxonomy、concept、unit、currency、scale、instant/duration context、frame、revision；
- companyfacts fact 必须通过 accession 连接 filing；冲突、多 context、多单位不“任选一个”；
- normal、valid empty、no coverage、partial、stale、401/403/429、timeout、malformed、
  schema drift、wrong identity 为不同 typed outcome；
- content-type、size、redirect host allowlist、bounded retry/backoff、rate limit、total deadline；
- raw disclosure artifact immutable；caller 不得拼 Archives URL 后绕过 adapter；
- critical fact 缺失或无法消歧继续 fail closed。

SEC 只解决美国官方 disclosure，不提供完整 daily market OHLCV、交易日历、adjustment/corporate
action 或 market microstructure contract。这些能力不得从已拒绝的 aggregator fallback 补齐。

### HK future source policy

当前票不产生 HK production adapter：

- HKEXnews browser page：programmatic scrape `reject`；
- HKEX IIS / licensed issuer-news feed：未来另行 qualification，必须有许可、固定 schema、
  PIT、identity、cache/redistribution rights；
- issuer IR：逐发行人 qualification 的 `keep-local` authority/cross-check 类别；
- 无许可或无逐站条款时，只能控制面人工发现/验证，不能写进 runtime；
- 不能创建空 `HkexAdapter`、临时 scraper 或 “以后换 feed” compatibility seam。

## Adopt / adapt / keep / reject 删除矩阵

| 能力 | 当前 canonical implementation | 外部候选 | 决策 | 采用条件 | 删除/禁止对象 | 拒绝原因 |
|---|---|---|---|---|---|---|
| 整个 Global Skill | `skills/SKILL.md` + application tasks | 自由 Markdown/Python | `reject` | 无 | 禁止复制、直接执行、第二 CLI/Skill | 无 package/tests/typed contract；平行入口 |
| US official filings | 仅 source-policy 文档，无 runtime adapter | SEC submissions + Archives protocol | `adapt-code` | 唯一 OfficialDisclosure/DataProvider；PIT/coverage/hash/typed failures | 不复制 `sec_filings`；无 caller URL 拼接 | 官方协议合格，当前 parser 丢字段 |
| US official facts | 仅 source-policy 文档，无 runtime adapter | SEC companyfacts protocol | `adapt-code` | unit/context/accession/revision 完整保留 | 删除任意单位、last-20、空数组歧义 | 官方协议合格，当前 parser 不合格 |
| US ticker discovery | 现有 security identity contract | SEC company_tickers | `adapt-code`（discovery only） | snapshot/hash/retrieved_at；CIK+listing identity | 禁止 ticker-only cache/security master | 无历史有效区间；本轮 403 |
| US/HK OHLCV | 当前 DataProvider source policy | Yahoo chart | `reject` | 无 | 禁止 chart parser 和 fallback | rights、adjustment、events、PIT 不合格 |
| US/HK quote/list/search | 当前 DataProvider source policy | Eastmoney/Sina/Tencent/Yahoo | `reject` | 无 | 禁止 magic-array、push2、crumb/session | 无许可/schema/identity；失败歧义 |
| US/HK financial aggregation | official-disclosure-first policy | Yahoo/Eastmoney | `reject` | 无 | 禁止作为 critical facts 或 ready gate | 非官方、无 filing lineage/PIT |
| Options/news/ratings/holders/flow | 当前研究与金融输出门禁 | Yahoo/Eastmoney | `reject` | 无 | 禁止 ratings/target、无 accession holder、资金流 | rights/lineage 不足；评级违反输出边界 |
| HK official disclosures | HKEXnews/IR policy，无本票 runtime | 上游没有实现 | `keep-local` policy；上游 `reject` | licensed feed 或逐 IR 条款后另票 | 禁止 scraper/占位 adapter | 上游无实现；网页条款禁止抓取 |
| Technical indicators | 本仓库 deterministic calculation | 上游公式 | `keep-local` | 无新 adapter | 不复制第二套指标函数 | 没有真实外部变化点 |

不存在 `temporary-both`、fallback、shadow read/write、caller adapter selection 或 compatibility
reader。`adapt-code` 只表示后续 Spec 可使用官方协议知识；在 callers、tests、persistence、
presentation 和旧对象原子切换前，不表示 production 已采用。

## Failure semantics qualification

必须拒绝的当前行为：

| 输入/外部状态 | 当前上游行为 | 必需正式语义 |
|---|---|---|
| 401/403/429 | 通用 exception、HTML decode failure 或 `{}` | typed unauthorized / forbidden / rate-limited，含 retry evidence |
| timeout / 5xx | 裸 requests exception 或 JSON decode error | typed transient external failure，bounded retry 后 fail closed |
| valid empty | `{}` / `[]` | typed empty，必须有完整 identity、coverage 与 source response |
| partial arrays | 缺失值变 0 或 IndexError | typed partial/schema drift；unknown 不等于 zero |
| wrong symbol/prefix | `{}` 或另一 listing | identity mismatch；绝不当无数据 |
| stale data | 无 retrieval/PIT | freshness/available/retrieved gate |
| schema drift | magic index 错位或空 | version/hash diagnostic，阻止 admission |
| multiple units/context | 自动选 USD/第一单位 | typed policy 或 ambiguity failure |
| amendment/revision | 最后 20 项覆盖 | accession/form/amendment/revision lineage |

## Data rights and retention

- Apache-2.0 允许审计/修改上游作者代码，但不授予第三方数据权利。
- SEC official public data 可按官方 developer/fair-access policy 访问和复用；production 仍必须
  识别调用方、限速、记录 provenance 并避免低效抓取。
- Yahoo、东方财富、新浪、腾讯没有证据授予本项目所需的自动访问、内部持久化、衍生和再分发
  权利；所以不因 200 connectivity 改变 `reject`。
- HKEX website terms 禁止未经书面许可的 programmatic access、systematic extraction、database
  creation 和再发布；licensed IIS/feed 是不同产品与许可边界。
- issuer IR 不能全市场概括授权，逐发行人记录 authority、terms、cache、redistribution 和
  provenance。

## 反证与升级政策

以下证据才允许重新开资格化：

- 第三方平台提供覆盖具体 endpoint、automation、storage、derived use 与 redistribution 的书面
  许可，以及稳定 schema/rate-limit/version；
- HKEX 提供适用 IIS/feed licence 与可固定 transmission specification；
- 发行人 IR 明确允许自动访问，并稳定绑定 SEC/HKEX filing identity；
- SEC future adapter 同时通过 official-schema fixtures、wrong identity、历史分片、多单位、
  amendment、403/429/timeout/schema drift 和真实 probe。

一次 200、README 的“免费无 Key”、浏览器能打开或 parser 有字段示例都不是反证。

## 票 05 完成判断

Question 已回答：

- pinned identity、license、dependency 与隔离环境已验证；
- 美股/港股全部端点逐族完成 authority、terms、PIT、identity、units/currency、corporate
  actions、failure、cache/redistribution 判断；
- deterministic fixture replay 为 12/12 pass；
- live connectivity 已覆盖 US/HK aggregator 与 SEC official protocols；
- SEC submissions/companyfacts 的 CIK、ticker/exchange、filing、accession 与 fact lineage 已交叉；
- HKEXnews 与 Tencent IR 的年度报告 byte-identical；
- 每项能力都有 `adapt-code` / `keep-local` / `reject`，没有 provisional 双路径；
- 未修改 production code，未污染项目环境，未保存第三方 raw bodies。

因此票 05 可以 `resolved`。下一票只能在下一 Goal 续轮领取。
