# 04 task: kong 数据根实网验证与死代码清除

Type: task
Status: open
Blocked by: 03

## Question / Scope

1. 全量回归：`tests/platform`（含 test_data_sync_pit.py）通过；报告通过/失败计数与跳过项。
2. kong 数据根实网同步：4 只持仓证券（002407/002897/002155/002241）经 kimi-agentgw 单策略 sync 至最新完整交易日；预期 freshness valid、coverage missing=0、snapshot_created=true。
3. 人工组合复核（manual_portfolio_review.run@2）走通并产出三类中性表述之一。
4. account-show 最终状态确认，输出符合 skills 默认合同。
5. 死代码清除终查：grep superseded 符号/导入/命令/文档；删除 `outputs/diag/` 诊断副本等临时产物；git status 最终 diff 复核，保留无关用户改动。
