from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills"


def _read(relative: str) -> str:
    return (SKILL_ROOT / relative).read_text(encoding="utf-8")


def test_skill_exposes_exactly_six_natural_language_user_tasks() -> None:
    skill = _read("SKILL.md")
    assert [
        line for line in skill.splitlines() if line.startswith("### ")
    ] == [
        "### A. 查看当前账户",
        "### B. 更新今天状态",
        "### C. 本周或指定周期复盘",
        "### D. 研究一只股票并生成图表报告",
        "### E. 创建交易计划",
        "### F. 更新交易计划",
    ]
    for phrase in (
        "用户只需用自然语言",
        "headline",
        "少量关键指标",
        "变化、偏离、限制",
        "一个明确问题",
        "技术细节、来源、版本与审计只在用户要求时展开",
        "未触发复核条件 / 符合已确认计划",
        "触发复核，需要用户判断",
        "证据不足，暂时无法判断",
    ):
        assert phrase in skill


def test_skill_default_surface_hides_internal_transport_and_web_burden() -> None:
    skill = _read("SKILL.md")
    for leaked in (
        "python -m trading_platform.cli",
        "ApplicationCommandEnvelope@1",
        "PortfolioWorkspaceView@1",
        "TradePlanDetailView@1",
        "projection_id",
        "PLAN_NOT_EVALUATED",
        "P5_LIVE_DATA_ROOT",
    ):
        assert leaked not in skill
    assert "Web 是可选的产物查看器，不是完成六类任务的前置条件" in skill
    assert "普通任务不要求用户启动 Web 或手动运行 CLI" in skill


def test_task_modules_own_the_six_workflows_and_confirmation_boundary() -> None:
    account = _read("tasks/account-status.md")
    cycle = _read("tasks/cycle-review.md")
    research = _read("tasks/equity-research.md")
    plan = _read("tasks/trade-plan.md")

    for phrase in (
        "安全备份",
        "最新完整 A 股交易日",
        "更新市值、收益、仓位与集中度",
        "没有新的券商或成交事实",
        "未触发复核条件 / 符合已确认计划",
    ):
        assert phrase in account
    assert "本周" in cycle and "持仓贡献" in cycle
    assert "不要求用户确认" in cycle
    for phrase in (
        "ResearchWorkflow",
        "stress/base/improvement",
        "Monte Carlo",
        "可以打开的真实产物",
        "data_insufficient_memo",
    ):
        assert phrase in research
    for phrase in (
        "创建计划",
        "更新计划",
        "新增、修改、删除、保持不变",
        "只询问一次",
        "拒绝、未回答、确认过期",
    ):
        assert phrase in plan


def test_internal_reference_preserves_one_application_and_persistence_path() -> None:
    internal = _read("references/platform-control-plane.md")
    for phrase in (
        "python -m trading_platform.cli application-command",
        "ApplicationCommandEnvelope@1",
        "trade_plan.prepare_draft@1",
        "manual_portfolio_review.run@2",
        "open_read_models(...)",
        "ResearchWorkflow.handle(StartResearchWorkflow(request))",
        "不得直接 SQL",
    ):
        assert phrase in internal

    active_docs = "\n".join(
        _read(path)
        for path in (
            "SKILL.md",
            "references/platform-control-plane.md",
            "tasks/account-status.md",
            "tasks/cycle-review.md",
            "tasks/equity-research.md",
            "tasks/trade-plan.md",
            "output/report-layout.md",
            "references/financial-model-spec.md",
            "references/output-schema.md",
            "valuation/valuation-method-router.md",
        )
    )
    for stale in (
        "trade_plan.create_draft@1",
        "trade_plan.revise_draft@1",
        "RECENT_TREND_SEAM_UNWIRED",
        "APPLICATION_TRADE_PLAN_AUTHORING_UNWIRED",
        "manual_portfolio_review.run@1",
        "RunManualPortfolioReview@1",
    ):
        assert stale not in active_docs