from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from trading_platform.identifiers import identity, parse_time
from trading_platform.planning import PlanEvaluation, TradePlan


@dataclass(frozen=True)
class DecisionTask:
    task_id: str
    trade_plan_id: str
    plan_evaluation_id: str
    triggered_rule_ids: tuple[str, ...]
    created_at: str
    status: str = "open"

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "triggered_rule_ids": list(self.triggered_rule_ids)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DecisionTask":
        return cls(
            task_id=str(value["task_id"]), trade_plan_id=str(value["trade_plan_id"]),
            plan_evaluation_id=str(value["plan_evaluation_id"]),
            triggered_rule_ids=tuple(str(item) for item in value["triggered_rule_ids"]),
            created_at=str(value["created_at"]), status=str(value["status"]),
        )


@dataclass(frozen=True)
class DecisionReview:
    decision_review_id: str
    review_type: str
    trade_plan_id: str
    task_id: str
    as_of: str
    frozen_refs: tuple[str, ...]
    assessment: str
    process_review_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "frozen_refs": list(self.frozen_refs)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DecisionReview":
        return cls(
            decision_review_id=str(value["decision_review_id"]), review_type=str(value["review_type"]),
            trade_plan_id=str(value["trade_plan_id"]), task_id=str(value["task_id"]), as_of=str(value["as_of"]),
            frozen_refs=tuple(str(item) for item in value["frozen_refs"]), assessment=str(value["assessment"]),
            process_review_id=str(value["process_review_id"]) if value.get("process_review_id") is not None else None,
        )


def create_task(plan: TradePlan, evaluation: PlanEvaluation) -> DecisionTask:
    triggered_rules = [str(result["rule_id"]) for result in evaluation.rule_results if result["status"] == "triggered"]
    if not triggered_rules:
        raise ValueError("DecisionTask requires a triggered PlanEvaluation")
    task = {
        "trade_plan_id": plan.trade_plan_id,
        "plan_evaluation_id": evaluation.plan_evaluation_id,
        "triggered_rule_ids": triggered_rules,
        "created_at": evaluation.as_of,
        "status": "open",
    }
    return DecisionTask(
        task_id=identity("task", task),
        trade_plan_id=plan.trade_plan_id,
        plan_evaluation_id=evaluation.plan_evaluation_id,
        triggered_rule_ids=tuple(triggered_rules),
        created_at=evaluation.as_of,
    )


def commit_review(
    candidate: Mapping[str, Any],
    plan: TradePlan,
    *,
    task: DecisionTask | None = None,
    process: DecisionReview | None = None,
    frozen_ref_times: Mapping[str, str | None] | None = None,
) -> DecisionReview:
    review_type = candidate.get("review_type")
    if review_type == "PROCESS":
        if task is None or task.trade_plan_id != plan.trade_plan_id:
            raise ValueError("PROCESS review requires the plan's DecisionTask")
        if not candidate.get("frozen_refs") or not candidate.get("assessment"):
            raise ValueError("PROCESS review requires frozen references and assessment")
        refs = [str(item) for item in candidate["frozen_refs"]]
        resolved = frozen_ref_times or {}
        unknown = [ref for ref in refs if ref not in resolved]
        if unknown:
            raise ValueError("PROCESS review contains an unrelated frozen reference")
        process_time = parse_time(str(candidate["as_of"]))
        if any(
            reference_time is not None and parse_time(reference_time) > process_time
            for reference_time in (resolved[ref] for ref in refs)
        ):
            raise StaleReview("PROCESS review cannot use information from after its as_of")
        payload = {
            "review_type": "PROCESS",
            "trade_plan_id": plan.trade_plan_id,
            "task_id": task.task_id,
            "as_of": str(candidate["as_of"]),
            "frozen_refs": refs,
            "assessment": str(candidate["assessment"]),
            "process_review_id": None,
        }
    elif review_type == "OUTCOME":
        if process is None or process.review_type != "PROCESS" or process.trade_plan_id != plan.trade_plan_id:
            raise ValueError("OUTCOME review requires the corresponding PROCESS review")
        if parse_time(str(candidate["as_of"])) <= parse_time(plan.review_window_end):
            raise StaleReview("the outcome window has not ended")
        payload = {
            "review_type": "OUTCOME",
            "trade_plan_id": plan.trade_plan_id,
            "task_id": process.task_id,
            "as_of": str(candidate["as_of"]),
            "frozen_refs": [],
            "assessment": str(candidate.get("assessment", "")),
            "process_review_id": process.decision_review_id,
        }
        if not payload["assessment"]:
            raise ValueError("OUTCOME review requires an assessment")
    else:
        raise ValueError("review_type must be PROCESS or OUTCOME")
    frozen_refs_value = payload["frozen_refs"]
    frozen_refs = frozen_refs_value if isinstance(frozen_refs_value, list) else []
    return DecisionReview(
        decision_review_id=identity("review", payload),
        review_type=str(payload["review_type"]),
        trade_plan_id=str(payload["trade_plan_id"]),
        task_id=str(payload["task_id"]),
        as_of=str(payload["as_of"]),
        frozen_refs=tuple(str(item) for item in frozen_refs),
        assessment=str(payload["assessment"]),
        process_review_id=(
            str(payload["process_review_id"])
            if payload["process_review_id"] is not None
            else None
        ),
    )


class StaleReview(ValueError):
    pass
