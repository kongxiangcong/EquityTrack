# 资格化 global-stock-data 的美港股端点与官方交叉验证

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

在指定仓库外隔离目录与独立环境中固定 `global-stock-data` commit，分别以 SEC EDGAR/XBRL、HKEXnews 和公司 IR 为关键披露权威，资格化其美股/港股端点的来源身份、PIT 时间、字段/单位/币种/证券身份、公司行动、正常及失败语义、条款与缓存/再分发边界；通过 deterministic fixture replay、官方交叉验证和真实 connectivity probe 判断哪些行为可进入唯一 DataProvider path，哪些只能辅助或必须拒绝。

## Answer

完整证据与逐端点矩阵见：

- [端点、数据权利与官方协议审计](../research/global-stock-data-endpoint-terms-and-protocols.md)
- [运行资格化与采用决定](../research/global-stock-data-runtime-qualification-and-decision.md)
- [确定性 parser fixture replay](../research/global-stock-data-fixture-replay.mjs)
- [真实 connectivity probe 证据](../research/global-stock-data-live-probe-evidence.json)
- [HKEXnews / 公司 IR 官方交叉验证](../research/global-stock-data-official-cross-validation-evidence.json)

`global-stock-data` 整体、全部 Yahoo/东方财富/新浪/腾讯端点和所有现成 parser 均
`reject`；真实 200 不能证明数据权、schema、PIT 或生产资格。唯一保留的 `adapt-code`
候选是 SEC submissions、companyfacts、Archives 与 ticker discovery 的官方协议知识，且必须在
唯一 `OfficialDisclosure` / `DataProvider` path 中重写，完整保留 CIK/listing identity、
acceptance/availability/retrieval time、accession、taxonomy/unit/context/revision、coverage、
raw hash 和 typed failure；上游 parser 不得复制。

上游没有 HKEXnews、HKEX IIS 或发行人 IR adapter。HKEXnews 网页抓取因条款 `reject`；获许可的
IIS/feed 只能未来独立资格化，不能建立占位符；发行人 IR 仅保留为逐站点条款资格化的
`keep-local` source-policy 类别。腾讯 2025 年报的 HKEXnews 与公司 IR PDF byte-identical，
只证明文档身份，不授予自动抓取权。纯技术指标保持本地唯一计算路径。

隔离 CPython 3.11.15 / requests 2.34.2 环境通过 dependency check；fixture replay 为
12 passed / 0 failed；真实 probe 覆盖 US/HK aggregator 和 SEC。SEC submissions/companyfacts
以规范化 CIK 和 accession 完成交叉验证，ticker convenience map 本轮 403 被保留为显式 external
failure，没有解释为空数据或触发 fallback。当前仓库未发现既有 SEC/HKEX runtime adapter，故
SEC 官方协议仍是后续 Spec 的新增 `adapt-code` 候选。Wayfinder 阶段未修改生产代码。
