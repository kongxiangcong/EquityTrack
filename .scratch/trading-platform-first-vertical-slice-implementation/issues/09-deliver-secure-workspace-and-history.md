# 09 — 交付安全可访问的完整工作区与历史回看

**What to build:** 让用户在一个克制、任务优先的本地工作区完成更新授权、研究复用理解、K 线标注、计划确认、市场评估和历史跳转。正常 provenance 渐进披露，真正影响能力的异常就近解释；完整历史从冻结 refs 和当时 artifacts 渲染，而不是用当前政策重算过去。

**Blocked by:** 04 — 生成并复用不可变 ResearchRun; 05 — 展示版本化 K 线并持久化 ChartAnnotation; 07 — 构建 MarketSnapshot 并执行 PlanEvaluation.

**Status:** resolved

- [x] 本地服务只绑定 loopback，启动生成不进入 URL、日志或 artifact 的高熵会话凭据，并拒绝非法 Host、DNS rebinding、跨源 mutation、缺 CSRF、GET mutation 和错误 content type。（AC-045）
- [x] CSP、同源策略、本地静态资源、请求大小限制和文本转义阻止外部资源、遥测、脚本型 annotation/source/error 和路径型输入；主动报告内容在非特权隔离环境中查看。（AC-045）
- [x] 完整 browser E2E 覆盖观察项、更新授权、requested/effective date、研究复用说明、K 线与标注、计划 diff/确认、评估、历史跳转、reload 和 server restart。（AC-031）
- [x] 默认工作区优先显示当前任务、发生的变化、比较、影响、规则结果和不确定性；正常 Provider、hash、节点和 provenance 仅在数据详情、证据或历史中展开。
- [x] blocking/partial 状态用用户语言说明发生了什么、仍可做什么和缺少什么；正常 pass 状态不形成流水线墙。
- [x] 版本侧栏、blocking banner、键盘、焦点、对比度、文字缩放、目标窗口宽度、reduced motion 和非颜色单一编码通过真实页面验证。（AC-032）
- [x] 历史 timeline 可从 WorkflowRun 遍历两个 DataSnapshot、ResearchRun、ChartAnnotationVersion、TradePlanVersion、MarketSnapshot、PlanEvaluation 和 ArtifactManifest，并明确 created/reused。（AC-015）
- [x] 迟到公告、官方更正、用户 rationale 或 evaluator/policy 升级生成并列新版本；旧历史继续按冻结 refs、当时 operands/reasons/policy 和 artifacts 展示。（AC-049）
- [x] 离线 browser journey 的 network spy 为零外连；live 模式只允许配置的服务端 Provider destinations，secret 和个人绝对路径不会到达 DOM、日志或 artifacts。（AC-036）
- [x] 所有 fixture 计划阈值、金额和规则持续标记 `user_fixture_input`，页面不使用个性化建议、买卖评级、目标价或收益承诺语言。（AC-037）

## Implementation Evidence

- `WorkspaceService` exposes replay-safe update authorization and frozen history only through `ApplicationFacade`; workspace history reads persisted refs, snapshots, research artifacts, plan/evaluation operands and policies without invoking current engines.
- `LocalChartWorkspaceServer` binds loopback and enforces Host, Origin, CSRF, method, content type and body-size gates plus restrictive CSP/COOP/CORP/Permissions headers. Script-shaped annotations, traversal, arbitrary provider destinations, secret/path leakage, and sandbox isolation have targeted tests.
- The task-first UI supports update authorization, versioned chart annotations, plan diff/confirmation, frozen evaluation/history expansion and an unprivileged report iframe. Fixture inputs remain labelled `user_fixture_input` and prohibited financial-language checks pass.
- A real in-app browser journey covered authorization, requested/effective dates, K-line annotation, plan diff/confirmation, evaluation detail, frozen refs, reload, and a stop/start server restart on the same data root. Browser checks also proved zero external resources/log errors, no secret/path leakage, keyboard focus with visible 2.4px outline, 16.27:1 button contrast, textual status encoding, 800px and zoomed layouts without overflow, and computed reduced-motion `transition: 0s` / `animation: none`.
- Targeted secure-workspace tests passed: 10. Full Python suite passed: 137. Frontend tests passed: 8 and production build passed. Python compilation and `git diff --check` passed.
- Independent review from fixed point `0f76a2d`: Standards PASS and Spec PASS after all findings were fixed and reverified.
