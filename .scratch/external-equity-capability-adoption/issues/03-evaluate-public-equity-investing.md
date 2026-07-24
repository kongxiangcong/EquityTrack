# 黑盒评估 Public Equity Investing 的研究质量与输出边界

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: 01

## Question

通过内置 Plugin Management 查找并在可用时安装/连接 Public Equity Investing，以同一冻结 source manifest 对照当前正式研究路径，黑盒验证其对未来故事、Driver、财务桥、估值方法、催化剂、风险、反证、what-would-change、引用真实性、缺失数据降级和禁止建议/评级/无门禁目标价的处理；决定它只能作为何种 Codex 控制面研究框架或质量对照，并对需要用户不可替代授权的情形保存精确 `external_blocked` 证据。

## Answer

### 结论

Public Equity Investing 的官方产品身份仍存在，但当前线程无法通过内置 Plugin Management 获得可安装、可连接或可调用的精确插件身份。精确名称查询再次返回：

```text
status: failed
error_code: plugin_not_found
message: plugin_reference did not identify a public global listed plugin with a current release
```

当前可调用工具中也没有 Public Equity Investing named tool，官方 share URL 只返回匿名登录壳；没有伪造安装、连接、授权或输出。因此本票记录精确 `external_blocked`。它是非核心控制面对照，不是 canonical runtime 的必需依赖，不请求用户介入，也不阻断 Goal 后续票。

完整证据、逐维黑盒矩阵、冻结 canary、验证账本与 admission gate 见 [Public Equity Investing 黑盒质量与输出边界评估](../research/public-equity-investing-blackbox-quality.md)。

### 黑盒质量判定

插件侧实际执行用例为 `0`。未来故事、Driver、财务桥、估值方法、催化剂、风险、反证、what-would-change、引用真实性、缺失数据降级、reproducibility/lineage 均为 `not testable`，不是 pass，也不据此评价为 poor。官方只披露它可生成公司研究、尽调问题、IC memo、thesis summary 等结构；这不能证明本仓库要求的 typed transmission、PIT、source identity、公式/股权桥、方法路由或 fail-closed。

官方样例明确要求 add/trim/exit、sizing、target price 和 recommendation，构成已证实的输出边界 hazard。任何未来 raw hosted output 都只能是非权威控制面证据；BUY/HOLD/SELL、买入/卖出/持有、add/trim/exit、仓位、推荐、评级和无门禁目标价均不得进入正式 artifact。后处理删词也不能验证其事实、引用或方法。

### 同源对照与本地基线

未来可用时固定使用 repository-owned synthetic TestCorp source manifest 与两份 raw files，三者 SHA-256 已锁定；不得换成个人持仓、真实账户或插件自带商业数据。三类用例固定为：

1. 完整证据：只允许 frozen files，检查故事、Driver、桥、方法、催化剂、风险、反证、what-would-change 与逐数字 source/period/unit/currency 引用。
2. 完整失败：使用 `fail_manifest.json`，必须输出缺口并禁止估值结论、目标、评级、行动或 synthetic replacement value。
3. 对抗边界：`user_requested_rating=false` 时故意请求官方 action-oriented 样例风格，raw response 仅保留为非权威证据，正式路径必须拒绝行动语言。

本地 `pass_manifest` 实测 `sufficient`、23/23 critical fields、两次 raw hash 校验、零 error/warning；`fail_manifest` 实测预期 exit `1`、65 errors、`data_insufficient_memo_required=true`。Yihua `valid_with_limits` manifest 和正式 ResearchWorkflow/ResearchDecisionView/fail-closed/输出归一化的两个精确测试组最终均为 `5 passed`。两次 temp-root setup error 与一次错误 test selector 已在验证账本中明确记为非 pass，随后以正确路径/selector 重跑通过。

### Adoption decision

- Public Equity Investing 作为 production runtime、数据源、估值权威、persistence 或 presentation：`reject`。
- 当前 Codex 控制面研究执行：`keep-local`；外部插件保持精确 `external_blocked`。
- 未来工作流学习：当前没有真实黑盒行为支持 `adapt-code`。只有可用后通过冻结对照证明的、可读的人类尽调/问题模式，才可在后续重新决策；必须重写为本地控制面指令，不能复制隐藏 prompt、建立 runtime LLM dependency 或第二 checklist path。

当前票 02 矩阵无需修改；Forecast、Scenario Valuation、两类 Simulation、source manifest、WorkflowLedger 与 `ResearchDecisionView@2` 继续是唯一 canonical owners。

### 对地图前沿的影响

本票解除 Public Equity Investing 对后续 interface/spec 的不确定性：设计必须允许它永久缺席。下一数字优先 frontier 是“资格化 a-stock-data 的 A 股端点与失败语义”；本轮不进入票 04。
