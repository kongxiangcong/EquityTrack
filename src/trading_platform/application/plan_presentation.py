from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping


_LIFECYCLE_LABELS = {
    "active": "已确认并启用",
    "confirmed": "已确认，尚未启用",
    "draft": "未确认草稿",
    "inactive": "已停用",
}
_RULE_LABELS = {
    "trend_break_candidate": "趋势跌破条件",
    "thesis_invalidation_review": "投资论点失效复核",
    "core_floor_precedence": "核心数量下限",
}
_EFFECT_LABELS = {
    "open_decision_task": "创建待用户处理的决策任务；不会自动执行",
    "open_plan_review": "发起计划复核；不会自动修改计划",
    "block_candidate_below_core_floor": "阻止候选数量低于核心数量下限",
}
_STATE_LABELS = {
    "triggered": "条件已满足",
    "not_triggered": "条件未满足",
    "not_selected": "本次未选中",
    "unable_to_determine": "暂时无法判断",
    "blocked": "评估受阻",
    "not_applicable": "当前不适用",
    "unassessed": "尚未评估",
}
_EVIDENCE_LABELS = {
    "market_data_snapshot": "行情数据",
    "account_snapshot": "账户快照",
    "risk_policy": "风险约束",
    "ResearchDecisionView": "研究结论",
    "RecentTrendAssessment": "近期走势",
    "AccountSnapshotVersion": "账户快照",
    "PortfolioRiskPolicyVersion": "风险约束",
    "StrategyVersion": "计划策略",
}
_RISK_LABELS = {
    "single_security_exposure": "单一证券敞口上限",
    "industry_exposure": "行业敞口上限",
    "gross_exposure": "总敞口上限",
    "minimum_cash": "最低现金比例",
    "single_plan_loss": "单计划损失上限",
    "aggregate_active_plan_loss": "启用计划合计损失上限",
    "drawdown_review": "回撤复核阈值",
    "drawdown_freeze": "回撤冻结阈值",
    "plan_daily_liquidity": "计划日流动性上限",
    "position_daily_liquidity": "持仓日流动性上限",
}


def build_plan_decision_summary(
    projection: Mapping[str, object],
) -> Mapping[str, object]:
    """Translate frozen plan authority into one decision-first product view."""
    identity = _mapping(projection.get("plan_identity"))
    versions = _mappings(projection.get("version_history"))
    confirmed = versions[-1] if versions else {}
    confirmation = _mapping(projection.get("confirmation_state"))
    draft = _mapping(confirmation.get("open_draft"))
    if draft.get("status") == "open":
        draft_horizon = _mapping(draft.get("horizon"))
        latest = {
            "horizon_start": draft_horizon.get("start"),
            "horizon_end": draft_horizon.get("end"),
            "review_by": draft_horizon.get("review_by"),
        }
        content = _mapping(draft.get("content"))
        sleeves = _mappings(draft.get("sleeves"))
        rules = _mappings(draft.get("rules"))
        states: dict[str, Mapping[str, object]] = {}
        freshness = _mappings(draft.get("evidence"))
        evaluations: tuple[Mapping[str, object], ...] = ()
        lifecycle = "draft"
    else:
        latest = confirmed
        content = _mapping(latest.get("content"))
        sleeves = _mappings(projection.get("sleeve_summary"))
        rules = _mappings(projection.get("rules"))
        states = {
            str(item.get("rule_id")): item
            for item in _mappings(projection.get("rule_states"))
        }
        freshness = _mappings(projection.get("evidence_freshness"))
        evaluations = _mappings(
            projection.get("latest_frozen_evaluations")
        )
        lifecycle = str(identity.get("lifecycle_status", "draft"))
    parameters = _mapping(content.get("strategy_parameters"))
    return {
        "lifecycle_label": _LIFECYCLE_LABELS.get(
            lifecycle, "状态待确认"
        ),
        "user_control_boundary": _boundary(lifecycle),
        "horizon": {
            "start": latest.get("horizon_start"),
            "end": latest.get("horizon_end"),
            "review_by": latest.get("review_by"),
        },
        "quantities": _quantities(parameters, sleeves),
        "trigger_conditions": tuple(
            _rule_summary(rule, states.get(str(rule.get("rule_id"))))
            for rule in rules
        ),
        "risk_constraints": _risk_constraints(content, sleeves),
        "evidence_status": _evidence_status(freshness),
        "evaluation": _evaluation_summary(evaluations),
    }


def _boundary(lifecycle: str) -> str:
    if lifecycle == "active":
        return (
            "这是已确认并启用的纪律计划；系统只生成复核与待办，"
            "不会自动执行。"
        )
    if lifecycle == "confirmed":
        return "这是已确认但未启用的计划；不会参与日常评估或自动执行。"
    return "这是未确认草稿；确认前不会参与日常评估或自动执行。"


def _quantities(
    parameters: Mapping[str, object],
    sleeves: tuple[Mapping[str, object], ...],
) -> Mapping[str, object]:
    core = next(
        (item for item in sleeves if item.get("sleeve_kind") == "core"),
        {},
    )
    candidate = _mapping(parameters.get("candidate_decrease_quantity"))
    core_value = parameters.get("core_floor_quantity")
    return {
        "core_floor": {
            "state": (
                "known" if core_value is not None else core.get(
                    "core_floor_state", "unknown"
                )
            ),
            "value": (
                str(core_value)
                if core_value is not None
                else core.get("core_floor_value")
            ),
            "unit": "股",
        },
        "candidate_adjustment": {
            "state": candidate.get("state", "unknown"),
            "value": candidate.get("value"),
            "unit": "股",
        },
    }


def _rule_summary(
    rule: Mapping[str, object],
    state: Mapping[str, object] | None,
) -> Mapping[str, object]:
    rule_kind = str(rule.get("rule_kind", ""))
    return {
        "name": _RULE_LABELS.get(rule_kind, "计划条件"),
        "condition": _condition_text(rule_kind, rule),
        "current_state": _STATE_LABELS.get(
            str(state.get("state")) if state else "unassessed",
            "状态待解释",
        ),
        "on_trigger": _EFFECT_LABELS.get(
            str(rule.get("effect")), "生成复核事项；不会自动执行"
        ),
    }


def _condition_text(
    rule_kind: str, rule: Mapping[str, object]
) -> str:
    condition = _mapping(rule.get("condition"))
    if rule_kind == "trend_break_candidate":
        children = _mappings(condition.get("children"))
        comparison = next(
            (item for item in children if item.get("node") == "comparison"),
            {},
        )
        elapsed = next(
            (
                item
                for item in children
                if item.get("node") == "elapsed_trading_sessions"
            ),
            {},
        )
        expected = comparison.get("expected", "明确阈值")
        sessions = int(elapsed.get("threshold_sessions", 0)) + 1
        return f"收盘价低于 {expected}，并连续 {sessions} 个完整交易日确认"
    if rule_kind == "thesis_invalidation_review":
        return "投资论点失效事件进入当前复核窗口"
    if rule_kind == "core_floor_precedence":
        expected = condition.get("expected", "核心数量下限")
        return f"候选调整后的剩余数量不得低于 {expected} 股"
    return "按已确认计划条件评估"


def _risk_constraints(
    content: Mapping[str, object],
    sleeves: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    limits = _mapping(content.get("risk_policy_limits"))
    result = [
        {"label": label, "value": _percent(value)}
        for key, label in _RISK_LABELS.items()
        if (value := limits.get(key)) is not None
    ]
    core = next(
        (item for item in sleeves if item.get("sleeve_kind") == "core"),
        None,
    )
    if core is not None:
        for key, label in (
            ("max_notional_value", "核心袖套最大名义金额"),
            ("max_loss_value", "核心袖套最大损失金额"),
        ):
            if core.get(key) is not None:
                result.append({"label": label, "value": str(core[key])})
    return tuple(result)


def _percent(value: object) -> str:
    try:
        return f"{(Decimal(str(value)) * 100).normalize()}%"
    except (InvalidOperation, ValueError):
        return "未知"


def _evidence_status(
    freshness: tuple[Mapping[str, object], ...],
) -> Mapping[str, object]:
    seen: set[tuple[object, object, object]] = set()
    items: list[Mapping[str, object]] = []
    for item in freshness:
        label = _EVIDENCE_LABELS.get(
            str(item.get("evidence_kind")), "计划证据"
        )
        state = str(item.get("freshness_state", "unknown"))
        state_label = (
            "已冻结" if state in {"frozen", "resolved"} else "需要复核"
        )
        key = (label, state_label, item.get("as_of"))
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "label": label,
                "state": state_label,
                "as_of": item.get("as_of"),
            }
        )
    needs_review = any(item["state"] != "已冻结" for item in items)
    return {
        "summary": "存在需要复核的证据" if needs_review else "证据均已冻结",
        "items": tuple(items),
    }


def _evaluation_summary(
    evaluations: tuple[Mapping[str, object], ...],
) -> Mapping[str, object]:
    if not evaluations:
        return {
            "state": "尚未评估",
            "reason": "尚未对最新完整交易日执行计划评估。",
            "next_step": "使用最新完整交易日运行一次计划评估。",
        }
    outcome = str(evaluations[0].get("resolution_outcome", ""))
    if outcome == "decision_task":
        return {
            "state": "需要用户处理",
            "reason": "一个候选条件已满足，并已形成待办。",
            "next_step": "查看待办并记录决定；系统不会自动执行。",
        }
    if outcome == "no_action":
        return {
            "state": "当前无需处理",
            "reason": "本次没有计划条件满足触发要求。",
            "next_step": "等待新的完整交易日或关键证据后再次评估。",
        }
    if outcome == "blocked":
        return {
            "state": "评估受阻",
            "reason": "必要输入或约束未通过，当前不能安全判断。",
            "next_step": "补齐受阻输入后重新评估。",
        }
    return {
        "state": "暂时无法判断",
        "reason": "当前证据不足以确定计划条件是否成立。",
        "next_step": "补充缺失证据并重新评估。",
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


__all__ = ["build_plan_decision_summary"]