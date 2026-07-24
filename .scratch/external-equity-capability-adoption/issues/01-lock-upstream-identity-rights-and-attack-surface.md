# 锁定上游身份、许可证、数据权利与攻击面

Type: `research`
Mode: `AFK`
Status: `resolved`
Blocked by: none

## Question

以 canonical repository、官方插件目录/授权面、许可证与 NOTICE、依赖和数据源条款、固定 commit/release、运行时写入/文件/子进程/外联能力以及真实维护证据为一手来源，锁定 Public Equity Investing、`a-stock-data`、`global-stock-data` 与 `Vibe-Trading` 的可复现身份、法律/数据权利边界和攻击面；产出 upstream manifest 与逐端点 terms profile，并明确哪些未知会阻断后续 production 采用、哪些只会把候选限制为隔离研究对照。
## Answer

### 结论

四项候选的身份、代码许可证、数据权利边界和攻击面已经锁定；三个开源仓库均固定到完整 commit 与核心文件 hash，外部 checkout 保持 clean。代码许可不等于第三方数据权利：当前没有任何候选证明其全部数据端点具备缓存、持久化、派生、再分发或商业使用权，因此所有端点仍须在后续资格化票中按 primary terms 与运行证据逐项解锁，不能直接进入 production。

规范化证据：

- [上游 manifest](../research/upstream-manifest.md)
- [逐来源 terms/authority profile](../research/endpoint-terms-profile.md)
- [Public Equity Investing 审计](../research/public-equity-investing-upstream-audit.md)
- [`a-stock-data` 审计](../research/a-stock-data-upstream-audit.md)
- [`global-stock-data` 审计](../research/global-stock-data-upstream-audit.md)
- [Vibe-Trading 审计](../research/vibe-trading-upstream-audit.md)
- [当前 canonical seams](../research/current-canonical-seams.md)
- [Goal Prompt 更新记录](../research/authority-revision-log.md)

### 固定身份与许可

| 候选 | 固定身份 | 许可/NOTICE | 本票结论 |
|---|---|---|---|
| Public Equity Investing | OpenAI 官方 hosted catalog/share target；无可复制 source commit/hash | 未披露源代码许可证或 NOTICE | 官方产品存在，但当前 Plugin Management 对精确名称返回 `plugin_not_found`；状态为精确 `external_blocked`，不得伪造安装或可用性 |
| `a-stock-data` | `06791b5a3159401524c10bd0e28aaebe415ce604` / `v3.5.0` | Apache-2.0；无 NOTICE 文件 | 单一 `SKILL.md`/内嵌 Python 知识库，不是稳定包；只允许后续按端点考虑 `adapt-code` |
| `global-stock-data` | `d52a8a0013363577bceb28ca876c88fe6c1a5aeb` / `v1.0.1` | Apache-2.0；无 NOTICE 文件 | 单一 Skill，不是稳定包；无 shipped tests/CI，且当前公开 issue 指出腾讯字段索引/单位风险 |
| Vibe-Trading | `0aa45a9ff3df58fab1c50f5400d9b112d19cacc6`，即 `v0.1.12-78-g0aa45a9` | MIT；有 NOTICE 和因子归属 | 完整应用且攻击面宽；只能在后续票以 pinned、隔离、最小 allowlist 的 stdio MCP 引擎资格化 |

### 生产阻断与允许继续的未知

阻断相关能力进入 production：

1. 端点级 authority、terms、cache、redistribution、commercial-use、rate-limit、PIT 时间和 provenance 未由 primary evidence 证明。
2. `a-stock-data` 存在明文 CNINFO、关闭 SZSE TLS 校验、可改 iwencai 凭据目的地、用户目录/任意目标写入、empty-on-error 和 legacy fallback；这些行为直接拒绝，不能带入适配代码。
3. `global-stock-data` 存在 unknown→0、failure→empty、placeholder SEC User-Agent、无 typed PIT/provenance，并直接暴露 target/recommendation 字段；不能直连正式路径。
4. Public Equity Investing 的底层 app manifest、商业数据 entitlement、retention 与当前 workspace 可用性未知；不能成为数据源、runtime 或估值权威。
5. Vibe-Trading 的完整 MCP 暴露文件、web/search、broker/order、memory、scheduler、swarm、外部 MCP、Web/API 和生成代码子进程；完整应用/in-process/平行 Web 采用被排除。

不阻断 Goal 继续：

1. Public Equity Investing 是非核心控制面质量对照，可保留 `external_blocked` 并继续其余 canonical path。
2. Vibe 数据 loader 权利未知不阻断使用 repository-owned frozen fixture、禁用 egress 后资格化策略算法。
3. 轻量/未签名 tag 不阻断可复现性，因为完整 SHA 与文件 hash 已固定。
4. Apache 上游没有 NOTICE 文件不消除许可证义务，但也不产生缺失 NOTICE payload 的 blocker。
5. 某个端点被拒绝不阻断从同一仓库评估另一个独立、可完整测试的协议/解析行为。

### 安全边界

- Skill 自由 Python 不得由 CLI、Web、research 或 Codex 直接执行；任何合格数据能力只能进入唯一 `DataProvider` application path。
- Vibe-Trading 后续固定使用上游 checkout 内 `uv + CPython 3.11 + .venv`，自动验证 stdio MCP；Docker、LLM/API Key、OAuth、券商和个人账户缺失不是 blocker。
- Vibe 的 live trading、模拟下单、broker/order、文件、web/search、memory、swarm、上游 Web/persistence 永久排除，不创建主项目 interface、fixture 或兼容占位符。
- Public Equity Investing 官方示例包含 add/trim/exit、sizing、target price 和 recommendation，后续黑盒评估必须证明本仓库 `Financial Output Boundary` 能失败关闭。

### 对地图前沿的影响

本票解决后，“绘制外部能力与现有模块的替换删除矩阵”、“黑盒评估 Public Equity Investing 的研究质量与输出边界”、“资格化 a-stock-data 的 A 股端点与失败语义”、“资格化 global-stock-data 的美港股端点与官方交叉验证”和“验证 Vibe-Trading 的回测、Walk-Forward 与模拟可信度”均解除上游身份 blocker。按本地 tracker 数字优先规则，下一 frontier 是“绘制外部能力与现有模块的替换删除矩阵”。
