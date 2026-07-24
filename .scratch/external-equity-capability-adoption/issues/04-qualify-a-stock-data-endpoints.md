# 资格化 a-stock-data 的 A 股端点与失败语义

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

在指定仓库外隔离目录与独立环境中固定 `a-stock-data` commit，逐端点验证协议、字段/单位/证券身份、交易日历、复权、公司行动、停牌/涨跌停、published/available/retrieved 时间、正常/空/部分/过期/限流/鉴权/timeout/字段漂移失败语义、条款与缓存/再分发边界；通过 deterministic fixture replay 和真实 connectivity probe 判断哪些完整协议/解析行为可 `adapt-code` 进入唯一 DataProvider path，哪些只能辅助交叉验证或必须拒绝。
## Answer

### 结论

`a-stock-data` 已固定为 `06791b5a3159401524c10bd0e28aaebe415ce604` / `v3.5.0`。它是 Apache-2.0 的单文件 Skill/端点笔记，不是稳定 Python 包；代码许可证不覆盖第三方返回数据。其当前所有可执行实现均为 production `reject`：不得直接执行 Skill，不引入 `mootdx` 或其他依赖，不复制其 provider 优先级/fallback、home cache、任意文件写入、自由估值或空值降级。

完整条款、协议、端点族、字段/单位/身份/时间和失败审计见 [端点条款与协议资格研究](../research/a-stock-data-endpoint-terms-and-protocols.md)；隔离环境、真实连接、两套 deterministic replay、逐端点最终矩阵与删除边界见 [运行资格与最终决策](../research/a-stock-data-runtime-qualification-and-decision.md)。

没有任何现成上游 parser 可直接采用。只保留三类官方请求协议作为后续 owned `adapt-code` 输入：

1. CNINFO 法定公告的 HTTPS 证券映射与公告查询；
2. SZSE 法定公告查询；
3. SSE/SZSE 公开交易/监管记录查询。

它们只允许本地非商业、不得再分发，并且必须在唯一 `DataProvider`/OfficialDisclosure application path 内重新实现安全 transport、typed parser、不可变 raw hash、source-policy identity、完整 PIT/失败语义；不能复制当前明文 HTTP、`CERT_NONE`、猜测 `orgId`、SSE raw text 或官方失败后切 Eastmoney 的实现。CNINFO 互动问答最多是非权威 auxiliary；当前没有真实产品 task，不创建 adapter 或占位符。

通达信、腾讯、百度、东财、同花顺/Hexin、iwencai、新浪、CLS 的全部行情、K 线、研报、一致预期、资金流、龙虎榜、解禁、融资融券、大宗、股东、分红、新闻、财务、期权、热榜和打板端点均为 `reject`。Tushare-compatible 继续是结构化 A 股 market-data 的 canonical provider；关键财务事实继续以官方披露为权威。不存在 `adopt-external`、临时双轨、旧实现 fallback 或第二 persistence path。

### 运行与失败证据

上游目录内使用 CPython `3.11.15` 创建 `.venv-qualification`，解析到 `mootdx 0.11.7`、`requests 2.34.2`、`pandas 3.0.5`、`stockstats 0.6.8`、`httpx 0.25.2`；`uv pip check` 通过，但这只证明隔离环境内部依赖自洽，不构成采用。

代表性真实探测覆盖 Tencent、Baidu、Eastmoney、Tonghuashun、Sina、CNINFO、SSE、SZSE。CNINFO 精确公告查询返回 3 条且 3 条证券身份匹配；SZSE 公告查询返回 3 条且 3 条匹配；SZSE 公开交易记录返回 10 条；SSE 返回 510 条字符串记录。所有官方探测使用默认 certificate/hostname verification。只保存 schema/count/timing/hash，不保存响应正文或财务值。

两套全合成 replay 共 `17/17` assertions 通过，稳定复现 missing numeric 变零、truncated/schema drift 与合法空结果碰撞、错证券身份未拒绝、不同 transport/protocol failure 被折叠为空，以及官方 parser 丢 document/security/time/hash/date/unit 或把 SSE 记录降为 untyped text。原始 Skill 没有官方 calendar、requested/effective session、freshness、adjustment factor、corporate-action lineage、停牌/无成交/涨跌停规则，因此 stale、非交易日、停牌和 outage 无法可靠区分；这些项目判为不通过，未用合成数据伪造通过。

证据文件：

- [通用 live probe](../research/a-stock-data-live-probe-evidence.json)
- [官方 verified-TLS live probe](../research/a-stock-data-official-live-probe-evidence.json)
- [通用 synthetic replay](../research/a-stock-data-fixture-replay.mjs)
- [官方 synthetic replay](../research/a-stock-data-official-fixture-replay.mjs)

### 对地图前沿的影响

本票把票 02 对 A 股市场端点的乐观 `adapt-code` 候选收窄为“市场数据全部拒绝、只保留三类官方披露/监管请求协议”。后续 interface/spec 不得建立 `qualified AStockData-derived` 行情 adapter 占位符；只有上述官方协议在完整实现票通过 admission suite 后才能进入现有 OfficialDisclosure/DataProvider seam。

下一数字优先 frontier 是“资格化 global-stock-data 的美港股端点与官方交叉验证”；本轮不进入票 05。
