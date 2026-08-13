# Evidence-bound semantic model-input compiler

Status: needs-triage

## Blocking edge

当前确定性模型能严格消费 frozen `research_model_input`，但 production 数据链
尚没有从 official/structured facts 到这些字段的唯一语义编译器。直接添加
隐式字段映射会绕过 lineage、PIT 和 origin contract。

## Required migration

- 定义版本化目标 schema 及每个 path 的维度、期间、单位、币种和语义；
- 每个 derived/estimated 字段绑定 parent evidence refs、计算或估算 policy、
  PIT 选择规则和 source authority；
- 从 SourcePolicy、provider rights 与 dataset schema 派生字段 allowlist；denied
  字段不得出现在 diagnostics、lineage、artifact 或 reuse metadata；
- 以一次性向前迁移替换现有直接注入数据，不保留 legacy reader；
- 缺少 segment、scenario、bridge 或估算依据时保持 missing，不生成默认值；
- 通过 ProviderJob -> snapshot -> ResearchWorkflow -> restart 黑盒验收。

## Removal target

迁移完成后删除所有 fixture/local 路径中绕过语义编译器直接构造 production
model input 的做法；fixture-only 测试数据仍必须声明为 fixture origin。


## Comments
