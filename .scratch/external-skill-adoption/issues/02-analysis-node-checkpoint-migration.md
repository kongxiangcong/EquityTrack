# Analysis-node checkpoint and invalidation migration

Status: needs-triage

## Blocking edge

`ResearchAnalysisPlan@1` 已给出直接能力摘要、依赖哈希和 node hash，但现有
workflow ledger 仍以正式 workflow node 为 checkpoint 单位。把 hash 当成已
实现缓存会产生无法证明的 reused claim。

## Required migration

- 版本化 ledger/checkpoint schema，绑定 compiler、node、dependency 与 output
  identity；
- 定义成功、受限、阻断、取消、超时和损坏条目的重放规则；
- 当直接能力或任何祖先改变时，使所有后代失效；
- 同一身份只允许一个 canonical output，不新增第二 cache 或 run ledger；
- 用篡改、部分失败、restart、concurrent claim 和 descendant invalidation 黑盒
  测试证明 reuse 语义。

## Removal target

迁移完成后，节点 hash 的文档从“审计与失效边界”升级为已验证 reuse 合同；
在此之前不得显示 node-level cache hit。


## Comments
