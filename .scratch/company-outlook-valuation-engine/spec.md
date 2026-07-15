# 公司未来推演与估值引擎

## Goal

把当前“证据门禁 + 手工研究叙事 + 少量估值计算”演进为可审计、可复现的公司未来推演与估值能力。系统必须从 Fact 和 Assumption 出发，以结构化因果链把事件、业务驱动、财务预测和 Valuation 连起来，并在数据与模型门禁允许时输出条件每股价值区间或分布。

## Authoritative boundaries

- 保留 `ResearchEngine.run(ResearchRequest) -> ResearchRun` 作为现有调用者的稳定研究 seam；通过兼容 adapter 演进，不复制研究内核或大爆炸重写。
- 确定性计算、公式、单位、场景、估值、模拟和复盘全部由普通代码完成；业务运行时不调用 LLM。
- Fact、Assumption、Forecast 与 Valuation 保持不同身份。Assumption 不得升级为 Fact，Forecast 不得冒充 Valuation。
- 每个数值必须携带 exact decimal、单位、倍率、币种、期间、截至时点和来源或假设引用。
- 估值方法按证券的经济结构路由。金融企业、创新药、周期和资源企业不得回退到不适用的普通 FCFF。
- Monte Carlo 只在不确定性、分布、相关性、校准和收敛规则可审计时启用；确定性情景先于概率模拟。
- 基本面每股价值分布与市场价格路径模拟是两个独立结果，不能混称“目标价”。
- 默认输出用于研究判断，不包含个性化买卖、持仓、仓位或收益承诺。

## Target execution shape

```text
DataSnapshot + ResearchRun evidence anchor
  -> typed Fact / Assumption
  -> event-driver-financial Forecast graph
  -> deterministic Scenario set
  -> valuation method registry
  -> optional calibrated simulation
  -> immutable Forecast / Valuation / Simulation artifacts
  -> decision-first report
  -> append-only Forecast review and calibration
```

Forecast、Valuation、Simulation 和 Review 作为同一 WorkflowRun / ArtifactManifest 下的兄弟不可变产物，引用既有 ResearchRun 与 DataSnapshot；不得把全部模型 payload 继续堆进自由 `context` 或无限膨胀 ResearchRun。

## Locked implementation frontier

实施队列固定为 `issues/01` 到 `issues/13`。只按 `Blocked by` 前沿顺序领取；每票测试驱动、代码复审并独立提交。除非新证据证明规格错误，否则不插入绕过当前前沿的实现。

## Completion evidence

- 类型化单位、期间、币种、倍率、股权桥和公式 lineage 有接口级 worked examples 与失败反例。
- 普通多分部 A 股可沿 `Event -> Driver -> FinancialForecast -> Valuation` 得到确定性情景结果。
- 适用的方法族可执行，未实现或不适用的方法局部降级，不伪造结果。
- Monte Carlo 保存算法、seed、样本数、相关性、校准、收敛、分位数和贡献度；不能收敛时不发布正式分布。
- ForecastReview 保留原始预测并计算概率与数值误差。
- 报告默认展示故事、驱动、场景、价值分布和改变观点的证据；来源与诊断渐进披露。
- 意华股份和多氟多真实样例、平台持久化、浏览器展示、全量 Python/Web 测试与金融边界全部验收通过。

