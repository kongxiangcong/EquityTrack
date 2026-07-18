# 多氟多 002407.SZ V3 示例

该目录使用研究时点 2026-07-18、最近有效交易日 2026-07-17 的已锁定本地证据包；证据中分别保留可用时间与检索时间，演示可审计的公司未来推演旅程。

```powershell
python scripts\research.py run `
  --manifest examples\duofuduo-002407\source_manifest.json `
  --context examples\duofuduo-002407\research_context.json `
  --as-of-date 2026-07-18 `
  --output-dir outputs\dfd_002407_20260718\v3
```
