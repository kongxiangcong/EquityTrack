# 04 — 持久化不可变 Forecast 与 Valuation 产物

**What to build:** 让用户能够在平台重启后回看某次研究所引用的原始 DataSnapshot、ResearchRun、Forecast、情景和 Valuation，并能分辨创建、复用、模型版本变化和输入修订。

**Blocked by:** 02 — 建立类型化 Forecast 故事图; 03 — 交付多方法确定性情景估值.

**Status:** ready-for-agent

- [ ] Forecast、Valuation 和后续 Simulation 使用版本化、内容寻址、不可变的兄弟 artifacts，并引用确切 ResearchRun、DataSnapshot、公式、代码和 policy identity。
- [ ] 工作流以可恢复节点构建/复用这些产物；相同输入和版本幂等复用，数据、假设或模型变化产生并列新版本。
- [ ] SQLite 迁移新增 typed identity、关系、摘要和状态，历史 payload 保存在 artifact store；不破坏现有 research_run_record 插入合同。
- [ ] artifact manifest 从通用节点产物集合生成，不再硬编码只有 projection、JSON 和 HTML。
- [ ] 进程失败、恢复、对象损坏和并发重放测试证明不会改写旧研究或产生半提交结果。

