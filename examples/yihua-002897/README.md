# 意华股份回归样例

这是新工作流的可移植回归数据包，日期口径固定为 2026-07-07。

- `source_manifest.json`：从历史正式运行的完整 manifest 中提取的官方/市场字段；没有添加新金融事实。
- `estimate_overlay.json`：D&A 与租赁负债的低置信度估算，只允许支持探索情景。
- `research_context.json`：结构化研究叙事、风险、催化剂、情景和条件研究计划。

预期行为：

1. 来源结构有效，基础研究可继续；
2. `d_and_a` 和 `lease_debt` 的估算不会升级为官方事实；
3. DCF 和 peer comps 受限，但不会阻断完整 HTML 研究报告；
4. 输出不包含个性化投资指令或 house-style rating。
