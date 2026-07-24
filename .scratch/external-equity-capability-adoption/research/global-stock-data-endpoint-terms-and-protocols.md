# `global-stock-data` 端点、数据权利与官方交叉验证审计

## 结论

审计对象固定为：

- 仓库：`https://github.com/simonlin1212/global-stock-data`
- commit：`d52a8a0013363577bceb28ca876c88fe6c1a5aeb`
- 上游声明版本：`1.0.1`
- 审计日期：`2026-07-24`
- 执行边界：只读源码与官方资料；没有运行上游自由 Skill，没有把任何第三方响应或代码带入生产路径。

资格结论：

1. `global-stock-data` 整体是单文件端点知识库，不是可采用的 production package；整体决策为
   `reject`，不得 `adopt-external` 或作为运行时 Skill 执行。
2. 唯一可进入后续 `adapt-code` 评估的是 SEC 官方公开协议：
   `data.sec.gov/submissions`、`data.sec.gov/api/xbrl/companyfacts`、
   `www.sec.gov/files/company_tickers.json` 和由 accession 构造的 EDGAR Archives 文件身份。
   可以适配的是协议知识，不是上游现成 parser；现成 parser 丢失关键 PIT、单位、context 和
   accession lineage，必须重写并接入唯一 `OfficialDisclosure` / `DataProvider` path。
3. 上游没有任何 HKEXnews、HKEX IIS 或公司 IR 实现。因此它没有可资格化的港股官方披露路径。
   HKEX 网页条款明确禁止未经书面许可的程序化访问、系统性提取、缓存数据库和再发布；若未来需要
   自动化港股公告，必须使用获得许可的 HKEX IIS/feed 或逐发行人取得允许自动访问的 IR 协议，
   不能从网页抓取开始。
4. Yahoo、东方财富、新浪、腾讯的全部可执行端点均 `reject` 进入 production：
   它们是未文档化的面向网页内部接口，官方条款没有授权本项目的自动抓取、持久化和再分发，
   且来源、交易所授权、字段版本、时区、复权、公司行动和失败语义不足。
5. 纯计算 MA/EMA/MACD/RSI/KDJ/Bollinger 不是外部数据能力。它们与本仓库已有 deterministic
   calculation 职责重叠，结论为 `keep-local`；不得为了复用几段公式引入第二套指标路径。
6. 公司 IR 是公司自愿披露的第一方来源；对于港股，HKEX Listing Rule 2.07C 还要求发行人网站
   镜像交易所发布的监管文件。但每个 IR 网站的自动访问、缓存与转载条款各异，上游也没有 IR
   协议。它只能保留为本仓库 source policy 中逐发行人资格化的权威/交叉验证类别，不构成这次
   上游代码的 `adapt-code`。

## 审计方法与证据等级

优先级依次为：

1. 固定 commit 的可执行源码；
2. SEC、HKEX/HKEXnews 的官方开发者文档、规则与条款；
3. Yahoo、东方财富、新浪、腾讯自己发布的服务条款；
4. 上游 README/注释只用于发现端点和理解作者意图，不作为数据权利、字段稳定性或正确性的证明。

Apache-2.0 只覆盖上游作者提供的代码文本，不授予 Yahoo、交易所或其他第三方数据的访问、缓存、
衍生、再分发或商业使用权。上游 LICENSE 本身也没有第三方数据授权清单或 NOTICE。

## 可执行端点全清单

以下清单来自固定 commit 的
[`SKILL.md`](https://github.com/simonlin1212/global-stock-data/blob/d52a8a0013363577bceb28ca876c88fe6c1a5aeb/SKILL.md)。

| 家族 | 上游函数 / 协议 | 内容 | 权威级别 | 结论 |
|---|---|---|---|---|
| Yahoo session | `get_yahoo_session`; `fc.yahoo.com`; `/v1/test/getcrumb` | cookie/crumb 获取与进程内缓存 | 非数据权威；访问机制未获授权 | `reject` |
| Yahoo quoteSummary | `yahoo_quote_summary`; `/v10/finance/quoteSummary/{symbol}` | 估值、财务、预期、评级、持仓 | 聚合/二手；部分内容可能来自第三方 | `reject` |
| Yahoo chart | `stock_kline_yahoo`; `/v8/finance/chart/{symbol}` | 美港 K 线 | 聚合行情 | `reject` |
| Yahoo options | `options_chain`; `/v7/finance/options/{symbol}` | 美股期权链 | 聚合行情 | `reject` |
| Yahoo search/news | `stock_news`; `/v1/finance/search` | 新闻索引 | 聚合/出版商内容 | `reject` |
| Eastmoney datacenter | `eastmoney_datacenter`, `financial_statements_eastmoney`, `key_indicators_eastmoney`; `/api/data/v1/get` | 美港财报三表与指标 | 聚合/二手 | `reject` |
| Eastmoney push2 quote | `stock_quote_eastmoney`; `/api/qt/stock/get` | 美港报价 | 聚合行情 | `reject` |
| Eastmoney push2his flow | `fund_flow_daily`; `/api/qt/stock/fflow/daykline/get` | 资金流分类 | 不透明派生数据 | `reject` |
| Eastmoney search | `stock_search`; `/api/suggest/get` | 名称、市场代码映射 | 聚合证券主数据 | `reject` |
| Eastmoney clist | `market_stock_list`; `/api/qt/clist/get` | 全市场列表与排序 | 聚合行情/证券主数据 | `reject` |
| Sina quote | `us_stock_quote_sina`, `hk_stock_quote_sina`; `hq.sinajs.cn/list=...` | 美港报价 | 合作方聚合行情 | `reject` |
| Sina US K-line | `us_stock_kline_sina`; `US_MinKService.getDailyK` JSONP | 美股日 K | 聚合行情 | `reject` |
| Tencent quote | `us_stock_quote_tencent`, `hk_stock_quote_tencent`; `qt.gtimg.cn/q=...` | 美港报价 | 聚合行情 | `reject` |
| SEC submissions | `sec_filings`; `data.sec.gov/submissions/CIK##########.json` | 法定 filing 列表与身份 | 美国官方披露 | 协议 `adapt-code`；现成 parser `reject` |
| SEC companyfacts | `sec_xbrl_facts`; `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | 结构化法定事实 | 美国官方披露 | 协议 `adapt-code`；现成 parser `reject` |
| SEC Archives | `sec_filings` 构造 `www.sec.gov/Archives/edgar/data/...` | 原始 filing 文档 | 美国官方披露 | 协议 `adapt-code` |
| SEC ticker mapping | `ticker_to_cik`; `www.sec.gov/files/company_tickers.json` | ticker 到 CIK 候选映射 | SEC 发布的便利映射 | 协议 `adapt-code`，但不能单独证明 listing identity |
| 纯计算 | `_ema`, `calc_ma`, `calc_macd`, `calc_rsi`, `calc_kdj`, `calc_boll` | 技术指标 | 无外部来源 | `keep-local` |

上游没有 HKEXnews、HKEX IIS、发行人 IR、NYSE/Nasdaq 官方行情、港股公司行动或交易日历端点。
因此“美港股全栈”不能被理解为具有完整官方 source lineage 的数据产品。

## 官方来源与数据权利

### SEC EDGAR / XBRL

SEC 明确提供：

- 无需鉴权/API key 的 JSON REST API，包括 submissions 与 XBRL companyfacts；
- 数据随 filing disseminate 实时更新，submissions 典型延迟低于一秒、XBRL API 典型延迟低于
  一分钟，但高峰期可能更长；
- nightly bulk ZIP，适合大量获取，避免逐实体高频抓取；
- companyfacts 按 taxonomy concept 和单位保留多个 fact context；
- SEC.gov 政府创建内容和 EDGAR 公开 filing 内容可免费访问和复用。

对应官方证据：

- [EDGAR Application Programming Interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC Webmaster FAQ：EDGAR 内容可访问和复用](https://www.sec.gov/about/webmaster-frequently-asked-questions)
- [SEC Website Dissemination](https://www.sec.gov/about/privacy-information#dissemination)

自动访问必须：

- 使用能识别调用方并包含联系地址的 declared `User-Agent`；
- 总速率不超过每秒 10 次，并高效、按需下载；
- 对 429/403、短暂限流与服务异常实施显式退避，而不是把它们解释为空数据；
- 批量任务优先使用官方 nightly bulk archive。

上游写死的
`SimonLin global-stock-data/1.0 (contact@example.com)` 不是本项目真实身份，也不能满足可联系要求；
必须替换为由 canonical adapter 配置且非秘密的真实应用标识。

### HKEXnews、HKEX IIS 与发行人 IR

HKEX Listing Rule 2.07C 证明：

- 必须发布的公告由发行人提交给交易所网站；
- 发行人必须在自己的网站发布同一公告，并持续至少五年免费提供；
- 发行人对提交内容的准确性负责。

这使 HKEX 发布文档成为港股监管披露的 canonical authority，发行人 IR 上的同一监管文档可做
第一方镜像交叉验证。证据：

- [HKEX Listing Rule 2.07C](https://en-rules.hkex.com.hk/rulebook/207c)
- [HKEX Issuer Information feed Service](https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/Issuer-Information-feed-Service-%28IIS%29?sc_lang=en)

但公开网页“可浏览”不等于“可自动抓取”。HKEX Terms of Use 第 5 节只允许个人临时下载、显示和
有限本地存储，未经书面许可禁止：

- 程序化、脚本或机械访问；
- 系统性提取形成数据库；
- 复制、发布或向第三方提供；
- text/data mining 和 web scraping。

证据：[HKEX Terms of Use](https://www.hkex.com.hk/global/exchange/terms-of-use?sc_lang=en)。

HKEX 另有明确的 market-data 与 issuer-news feed 许可体系；IIS News 列在 vendor licence 的
数据 feed 内，市场数据的内部使用、非展示和再分发也分别受许可与费用约束：

- [HKEX Market Data Vendor Licence Agreement](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Market-Data-Services/Real-Time-Data-Services/Data-Licensing_/Agreement/Market-Data-Vendor-Licence-Agreement-v202403m.pdf)
- [HKEX Getting Market Data FAQ](https://www.hkex.com.hk/Global/Exchange/FAQ/Market-Data/Getting-Market-Data?sc_lang=en)

因此：

- `HKEX website scraper`：`reject`；
- `HKEX IIS/获许可 feed adapter`：未来可独立资格化，但不是本上游能力；
- `issuer IR`：逐发行人条款资格化后可作为第一方交叉验证，不能假定全市场统一授权；
- 当前 ticket 不得创建空 HKEX adapter 或“先抓网页、以后换 feed”的兼容路径。

### Yahoo

上游调用的是 Yahoo Finance 网页内部 JSON URL，不是凭 Yahoo API credentials 使用的正式 API。
Yahoo 通用条款禁止未经事先明确许可，以机器人、scraper、data-mining 或其他自动方式访问或收集
服务数据，也禁止用内容建立替代性数据库、archive、feed 或聚合数据源。正式 Yahoo API 条款又
要求使用获授权的 API credentials，并限制 API Data 的使用与转移。

证据：

- [Yahoo Terms of Service](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)
- [Yahoo Application Programming Interface Terms](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apitnc/index.html)

上游通过 `fc.yahoo.com` 获取 cookie/crumb 来调用内部端点，并不产生授权。无公开字段契约、
来源许可、缓存/再分发许可或稳定限流政策，所以 chart、quoteSummary、options、search/news
全部 `reject`。即使某次 connectivity probe 返回 200，也只证明网络可达，不证明可合法稳定使用。

### 东方财富

东方财富 2025-07-18 生效的用户协议适用于 WEB 服务和行情信息。其知识产权条款规定，服务内容
知识产权属于东方财富或相关权利人；未经事先书面许可不得使用或创作衍生作品；特别提醒未经
交易所书面同意不得复制行情数据、向机构或个人提供全部或部分行情数据，也不得将其用于衍生品。
协议还明确不保证信息的真实性、完整性、准确性、及时性和连续性。

证据：

- [东方财富用户服务协议](https://about.eastmoney.com/home/protocol)
- [东方财富网法律声明](https://about.eastmoney.com/home/legal)

上游没有书面许可、交易所 entitlement、正式 API 文档或字段版本。因此 datacenter、push2、
push2his、search 和 clist 均 `reject`。硬编码的 search token 只是网页参数，不是数据许可。

### 新浪财经

新浪财经用户协议未经书面许可禁止：

- 复制、读取或采用服务信息用于商业用途；
- 整理后在原页面以外展示；
- 通过机器人、蜘蛛等程序监视、复制、传播、镜像、上传或下载内容。

新浪财经首页还说明免费行情来自合作方，其他行情可能至少延迟 15 分钟，并且不保证错误、残缺或
延迟；这不能为具体字段提供交易所授权、实时性或再分发权。

证据：

- [新浪财经用户协议](https://finance.sina.com.cn/roll/2021-05-12/doc-ikmxzfmm2033220.shtml)
- [新浪财经行情来源与延迟声明](https://finance.sina.com.cn/)

因此 `hq.sinajs.cn` 报价和 JSONP K 线均 `reject`。设置浏览器 Referer 和 User-Agent 不构成
API 授权。

### 腾讯

腾讯服务协议规定服务仅供个人非商业使用，用户应通过腾讯提供或认可的方式访问；未经授权不得
使用第三方软件、插件、系统等查看或获取腾讯、合作伙伴或用户的数据，且必须遵守 robots 规则。
服务按现状提供，可能中断或丢失数据。证据：

- [腾讯服务协议](https://edu.tencent.com/agreement.html)
- [Tencent.com 服务协议](https://www.tencent.com/index.php/zh-cn/service-agreement.html)

`qt.gtimg.cn` 没有随上游提供的正式 API、字段版本、市场数据 entitlement、缓存或再分发授权，
所以美股和港股报价均 `reject`。

## 字段、身份、单位和 PIT 审计

### SEC submissions

官方结构本身可支持可靠身份和时间，但上游 `sec_filings` 只保留 `filingDate`、form、
accession 和 primary document，并存在以下缺口：

- 只读取 `filings.recent`，忽略 `filings.files` 指向的较老历史分片；
- 只返回前 50 项，截断规则没有反映为 coverage；
- 丢失 `acceptanceDateTime`、`reportDate`、`fileNumber`、film number、items、size 和 amendment
  关系；
- ticker 只取数组第一个，无法表达同一实体多 ticker/交易所；
- 没有把 accession、primary document、CIK 与取得时间绑定成不可变 artifact identity；
- 没有 `published_at` / `available_at` / `retrieved_at` 区分。

后续适配必须将 SEC `acceptanceDateTime` 作为官方可得时间候选，把 `filingDate` 当披露日期而非
精确可得时刻；保存 accession、CIK、form、period/report date、amendment、primary document URL、
原始响应 hash 和 `retrieved_at`。对历史分片进行完整覆盖或明确 coverage boundary。

### SEC companyfacts

官方 companyfacts 为每个 taxonomy concept 按单位保存事实，事实可能包含 `start`、`end`、
`val`、`accn`、`fy`、`fp`、`form`、`filed`、`frame` 等。上游 parser：

- 只读取 `us-gaap`，忽略 `ifrs-full` 和发行人自定义 taxonomy；
- 自动优先选 `USD`，否则任取第一个单位，可能把错误单位静默提升；
- 丢弃 `start`、`accn`、`frame` 和事实 context；
- 用数组最后 20 项代替显式 revision/amendment policy；
- 仅凭 form 为 10-K/10-Q 过滤，无法区分重复、修订、期间和 instant/duration fact；
- 未把事实链接回原 filing；
- 缺少 currency、scale、shares/per-share 单位的 typed gate。

因此现成 `sec_xbrl_facts` 不可采用。后续 adapter 必须保留官方单位和完整 context，以 accession
连接 submissions；同一 fact 多 context、amendment、不同 currency/units 或 taxonomy 时不得
“任选一个”，而应按 typed policy 解析或 fail closed。

### SEC ticker mapping

`company_tickers.json` 是便利映射，不是带历史有效区间的 security master。ticker 可变更、复用，
同一 CIK 可有多个证券。上游的 process-global cache 没有 fetched time/hash/version，也仅做
当前大写字符串匹配。后续可用于 discovery，但 canonical identity 必须是 CIK + listing/security
identity，并保存映射快照与 `as_of/retrieved_at`；不能用 ticker 单独证明历史身份。

### Yahoo / 新浪 / 腾讯 / 东方财富

共同缺口：

- 没有正式 schema/version；
- 没有 `published_at`、`available_at`、`retrieved_at`；
- 股票代码前缀由 caller 手工选择，错误市场身份可返回空或另一证券；
- 没有 exchange MIC、share class、listing currency 和 corporate-action identity；
- 没有 trading calendar；
- 没有停牌、退市、半日市、盘前/盘后状态的可靠 contract；
- 没有公司行动或复权 policy。

特有缺口：

- Yahoo chart 使用本机 `datetime.fromtimestamp`，没有使用响应里的 exchange timezone；
  省略 `adjclose` 和 `events`，并把 `None`/零值都转换为 `0`。
- 新浪/腾讯按魔法数组位置解析，字段变化可能静默错位；大量空字段被转成数值零。
- 东财报价依赖 `f59` 和手写 `fNN` 字段，clist 又未使用同一缩放规则；单位在函数间不一致。
- 东财财报缺少原始 filing、会计期间、发布日期/可得时间和修订 lineage，不能替代 SEC/HKEX/IR。
- “资金流”大/中/小单分类没有定义版本、算法或交易所级原始来源，不能作为可审计事实。
- Yahoo `options_chain` 声称含 Greeks，实际只返回 implied volatility，并未返回 delta/gamma/theta/
  vega/rho；也没有 OPRA entitlement、quote timestamp、multiplier 或 corporate-action lineage。
- Yahoo 分析师目标价与 `buy/hold/sell` 评级直接违反本仓库默认 Financial Output Boundary。
- Yahoo 机构持仓缺少对应 13F filing/accession、报告日到公开日的 PIT lineage，不能作为正式持仓事实。

## 失败与安全语义

上游没有 typed failure contract，具体表现为：

| 端点家族 | 当前行为 | 不可接受的歧义 |
|---|---|---|
| Yahoo | 多数 `raise_for_status`，但直接索引 `[0]` 或把缺项变 `{}`/`[]` | 401/403/429、真实空集、无覆盖、schema drift 混杂；crumb 失效无专门语义 |
| Eastmoney | 多数不 `raise_for_status`，`result/data` 缺失直接返回空 | 限流、封禁、错误证券、服务错误、合法空集无法区分 |
| Sina/Tencent | regex 不匹配或字段少返回空，字段转换可抛裸异常 | HTML 拦截页、编码变化、退市、错误代码、schema drift 混杂 |
| SEC | HTTP 错误抛通用 requests 异常；缺 metric 返回空 | 404 无实体、403/429 fair-access、暂时服务错误、taxonomy 缺失、真实无披露无法区分 |
| 纯计算 | 对空序列、零分母和不足窗口缺少统一前置 contract | 无数据、不足窗口、无涨跌、算法定义变化可能变成崩溃或错误数值 |

所有网络调用都缺少：

- 限速与 `Retry-After` 处理；
- 有界重试、退避和 total deadline；
- 最大响应体限制与 content-type 验证；
- response identity/schema hash；
- TLS/redirect 目标 allowlist；
- redacted typed diagnostics；
- retrieval timestamp 和 raw artifact hash；
- normal / empty / partial / stale / 401 / 403 / 429 / timeout / malformed / schema drift 的可区分结果。

Yahoo cookie/crumb 以进程全局 session 保存且无过期/刷新 contract；SEC ticker mapping 也以全局变量
缓存。这些都不是本仓库允许的持久化或 source-policy seam。

## Adopt / adapt / keep / reject 矩阵

| 能力 | 决策 | 采用条件 | 删除/禁止对象 | 原因 |
|---|---|---|---|---|
| 整个 Skill 与端点 fallback 编排 | `reject` | 无 | 禁止自由执行、动态复制代码、caller 选 provider、prefer-new-else-old | 建立平行入口和未声明 fallback |
| SEC submissions 协议 | `adapt-code` | 唯一 OfficialDisclosure/DataProvider adapter；真实 UA；≤10 rps；完整历史/identity/PIT/typed failures/fixture+live probe | 不保留上游 `sec_filings` parser | 官方、可自动访问、可复用，但上游 parser 不合格 |
| SEC companyfacts 协议 | `adapt-code` | 保留 taxonomy/unit/context/accession/revision；连接原 filing；unknown fail closed | 不保留任意单位选择和 last-20 逻辑 | 官方结构化事实，但必须避免 context 丢失 |
| SEC ticker mapping 协议 | `adapt-code`（discovery only） | snapshot identity、retrieved time、CIK + listing identity；不得作为历史 security master | 删除 ticker-only identity 假设 | 官方便利映射但缺少历史有效区间 |
| SEC Archives filing identity | `adapt-code` | accession-derived canonical URI、hash、content-type/size gates | 禁止 caller 拼 URL 后直接消费 | 官方原始披露与不可变 lineage |
| HKEXnews 网页抓取 | `reject` | 无书面许可时无 | 禁止 scraper/HTML parser/本地公告库 | 官方条款明确禁止程序化访问和系统提取 |
| HKEX IIS / licensed issuer-news feed | `keep-local` 的未来资格项，不是本上游 adoption | 获得明确许可、schema/identity/PIT/rights 后另行 qualification | 不创建占位 adapter | 上游未实现；需许可和正式协议 |
| 公司 IR | `keep-local` source-policy 类别 | 逐发行人条款、内容 hash、官方 filing cross-link、PIT 通过 | 不假定全市场统一爬取权 | 第一方内容，但访问权逐站点 |
| Yahoo 全家族 | `reject` | 无 | cookie/crumb、quoteSummary、chart、options、search/news | 未获自动访问许可、内部 schema、不明数据权 |
| Eastmoney 全家族 | `reject` | 无 | datacenter/push2/push2his/search/clist | 未获交易所与平台书面许可、字段/权利不稳定 |
| Sina 报价/K 线 | `reject` | 无 | Referer 模拟、magic-array/JSONP parser | 条款禁止自动复制，合作方数据与延迟不透明 |
| Tencent 报价 | `reject` | 无 | magic-array parser | 非认可访问方式、个人非商业边界、无数据许可 |
| 分析师评级/目标价 | `reject` | 无 | `recommendation`, target high/low/mean 正式输出 | 来源/PIT 不足且违反 Financial Output Boundary |
| Yahoo 机构持仓 | `reject` | 无 | top-holder 聚合结果 | 无 accession/13F lineage 与可得时间 |
| “资金流”分类 | `reject` | 无 | Eastmoney order-size 派生数据 | 定义和算法不可审计 |
| 纯技术指标公式 | `keep-local` | 只走本仓库唯一 deterministic calculation interface 与测试 | 不复制第二套函数或建立外部 adapter | 无外部变化点，复用会制造双路径 |

## 后续唯一可实施协议

若票 05 的运行/fixture 验证不推翻上述结论，后续 Spec 应只携带以下一条外部适配候选：

```text
EvidenceSnapshot / DataSynchronization
  -> OfficialDisclosure DataProvider
      -> SecEdgarAdapter
          submissions + companyfacts + Archives
```

必须满足：

- source policy 固定 SEC endpoint family 和 adapter version，不由 caller 选择；
- 输入使用 typed US issuer/security identity，CIK 是 issuer identity，ticker 仅为映射线索；
- 保存 `requested_date`、`effective_session_date`、`as_of_at`、`published_at`、
  `available_at`、`retrieved_at`；
- 保存 accession、form、amendment、period、taxonomy、concept、unit、context、raw hash 和 adapter
  code/config hash；
- 处理 submissions 历史分片、companyfacts 多 context/多单位/修订；
- 对 unknown、缺失、空响应、限流、错误身份和 schema drift fail closed；
- 使用真实 SEC declared User-Agent、全局限速和 bulk-data policy；
- 不把 SEC 便利 ticker mapping 变成第二个 security master；
- 不增加 HKEX/Yahoo/东财/新浪/腾讯 fallback，不保留双读或 shadow comparison runtime；
- critical US financial facts 可用 SEC/发行人 IR 交叉验证；港股 critical facts 继续以
  HKEXnews/发行人 IR 的既有或未来合格 canonical path 为准。

若当前仓库已经拥有同等或更严格的 SEC official-disclosure 实现，则决策应从 `adapt-code`
收敛为 `keep-local`，仅将本审计作为 qualification regression criteria；不得为了宣称采用上游而
复制等价实现。

## 反证与重新资格条件

以下证据可改变当前 `reject`，但一次 connectivity 200、README 声称“免费零 Key”或字段样例不能：

- Yahoo、东方财富、新浪或腾讯出具覆盖具体端点、自动访问、内部持久化、衍生使用和项目所需
  再分发范围的书面许可，以及稳定 API/schema/rate-limit 文档；
- HKEX 授予适用的 IIS/market-data license 并提供可固定版本的 transmission specification；
- 某发行人 IR 明确允许本项目的自动访问与存储，并能稳定绑定其 HKEX/SEC filing identity；
- official protocol fixture 和真实 probe 同时证明身份、时间、单位、修订和失败语义，而不是只证明
  HTTP 可达。

在这些证据出现前，production 资格必须保持上述 fail-closed 结论。
