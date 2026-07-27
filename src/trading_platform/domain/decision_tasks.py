from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum
from typing import Mapping

from trading_platform.identity import canonical_hash

from .manual_review import (
    ManualPortfolioReviewItem,
    ManualPortfolioReviewRun,
    ReviewOutcome,
)


class DecisionTaskError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DecisionTaskState(str, Enum):
    OPEN = "open"
    DEFERRED = "deferred"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class UserDisposition(str, Enum):
    EXECUTED = "executed"
    DEFERRED = "deferred"
    SKIPPED = "skipped"
    OVERRIDDEN = "overridden"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class DeferralCondition:
    target_type: str
    target_value: str | None

    def validate(self) -> None:
        if self.target_type not in {
            "specific_date_or_session",
            "next_manual_review",
            "evidence_trigger",
        }:
            raise DecisionTaskError("DEFERRAL_CONDITION_INVALID")
        if self.target_type == "specific_date_or_session":
            try:
                date.fromisoformat(str(self.target_value))
            except ValueError as error:
                raise DecisionTaskError(
                    "DEFERRAL_TARGET_INVALID"
                ) from error
        elif self.target_type == "next_manual_review":
            if self.target_value is not None:
                raise DecisionTaskError("DEFERRAL_TARGET_INVALID")
        elif not self.target_value:
            raise DecisionTaskError("DEFERRAL_TARGET_INVALID")


@dataclass(frozen=True)
class DecisionTask:
    decision_task_id: str
    account_id: str
    security_id: str
    review_run_id: str
    review_item_id: str
    plan_version_id: str | None
    plan_evaluation_id: str | None
    task_kind: str
    reason_code: str
    priority: str
    condition_identity: str
    evidence_manifest_id: str
    created_at: str
    content_hash: str
    state: DecisionTaskState = DecisionTaskState.OPEN
    transition_seq: int = 0
    latest_transition_id: str | None = None
    disposition: UserDisposition | None = None
    deferral_condition: DeferralCondition | None = None
    schema_version: str = "DecisionTask@1"

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key
            not in {
                "content_hash",
                "state",
                "transition_seq",
                "latest_transition_id",
                "disposition",
                "deferral_condition",
            }
        }
        try:
            created = datetime.fromisoformat(self.created_at)
        except ValueError as error:
            raise DecisionTaskError("DECISION_TASK_TIME_INVALID") from error
        if (
            self.schema_version != "DecisionTask@1"
            or not self.decision_task_id
            or not self.account_id
            or not self.security_id
            or not self.review_run_id
            or not self.review_item_id
            or not self.task_kind
            or not self.reason_code
            or self.priority not in {"low", "normal", "high", "critical"}
            or not self.condition_identity
            or not self.evidence_manifest_id
            or created.tzinfo is None
            or self.transition_seq < 0
            or self.content_hash != canonical_hash(identity)
            or (
                (self.transition_seq == 0)
                != (self.latest_transition_id is None)
            )
            or (
                self.state is DecisionTaskState.DEFERRED
                and (
                    self.deferral_condition is None
                    or self.disposition is not UserDisposition.DEFERRED
                )
            )
            or (
                self.state is DecisionTaskState.RESOLVED
                and (
                    self.deferral_condition is not None
                    or self.disposition
                    not in {
                        UserDisposition.EXECUTED,
                        UserDisposition.SKIPPED,
                        UserDisposition.OVERRIDDEN,
                        UserDisposition.NOT_APPLICABLE,
                    }
                )
            )
            or (
                self.state
                in {DecisionTaskState.OPEN, DecisionTaskState.SUPERSEDED}
                and (
                    self.deferral_condition is not None
                    or self.disposition is not None
                )
            )
        ):
            raise DecisionTaskError("DECISION_TASK_INVALID")


@dataclass(frozen=True)
class DecisionTaskTransition:
    transition_id: str
    decision_task_id: str
    transition_seq: int
    from_status: DecisionTaskState
    to_status: DecisionTaskState
    trigger_kind: str
    disposition: UserDisposition | None
    deferral_condition: DeferralCondition | None
    evidence_ref: str | None
    action_log_entry_id: str | None
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    occurred_at: str
    content_hash: str
    schema_version: str = "DecisionTaskTransition@1"

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key != "content_hash"
        }
        try:
            occurred = datetime.fromisoformat(self.occurred_at)
        except ValueError as error:
            raise DecisionTaskError(
                "DECISION_TASK_TRANSITION_TIME_INVALID"
            ) from error
        if self.deferral_condition is not None:
            self.deferral_condition.validate()
        valid_shape = (
            (
                self.from_status is DecisionTaskState.OPEN
                and self.to_status is DecisionTaskState.DEFERRED
                and self.trigger_kind == "user_disposition"
                and self.disposition is UserDisposition.DEFERRED
                and self.deferral_condition is not None
            )
            or (
                self.from_status is DecisionTaskState.OPEN
                and self.to_status is DecisionTaskState.RESOLVED
                and self.trigger_kind == "user_disposition"
                and self.disposition
                in {
                    UserDisposition.EXECUTED,
                    UserDisposition.SKIPPED,
                    UserDisposition.OVERRIDDEN,
                    UserDisposition.NOT_APPLICABLE,
                }
                and self.deferral_condition is None
            )
            or (
                self.from_status is DecisionTaskState.DEFERRED
                and self.to_status is DecisionTaskState.OPEN
                and self.trigger_kind
                in {"date_or_session", "next_review", "evidence_trigger"}
                and self.disposition is None
                and self.deferral_condition is None
            )
            or (
                self.from_status
                in {DecisionTaskState.OPEN, DecisionTaskState.DEFERRED}
                and self.to_status is DecisionTaskState.SUPERSEDED
                and self.trigger_kind
                in {"plan_superseded", "condition_invalidated"}
                and self.disposition is None
                and self.deferral_condition is None
            )
        )
        if (
            self.schema_version != "DecisionTaskTransition@1"
            or not self.transition_id
            or not self.decision_task_id
            or self.transition_seq < 1
            or self.trigger_kind
            not in {
                "user_disposition",
                "date_or_session",
                "next_review",
                "evidence_trigger",
                "plan_superseded",
                "condition_invalidated",
            }
            or not self.decision_actor
            or not self.interaction_channel
            or not self.transport_actor
            or occurred.tzinfo is None
            or not valid_shape
            or (
                self.to_status is DecisionTaskState.DEFERRED
                and self.deferral_condition is None
            )
            or (
                self.to_status is not DecisionTaskState.DEFERRED
                and self.deferral_condition is not None
            )
            or self.content_hash != canonical_hash(identity)
        ):
            raise DecisionTaskError("DECISION_TASK_TRANSITION_INVALID")


@dataclass(frozen=True)
class DecisionTaskSeed:
    decision_task_id: str
    account_id: str
    security_id: str
    review_run_id: str
    review_item_id: str
    plan_version_id: str | None
    plan_evaluation_id: str | None
    task_kind: str
    reason_code: str
    priority: str
    condition_identity: str
    created_at: str


def derive_task_identity(
    *,
    account_id: str,
    security_id: str,
    plan_version_id: str | None,
    rule_id: str,
    candidate_intent: str,
    review_window: str,
    evidence_identity: str,
) -> tuple[str, str]:
    condition_identity = canonical_hash(
        {
            "plan_version_id": plan_version_id,
            "rule_id": rule_id,
            "candidate_intent": candidate_intent,
            "review_window": review_window,
            "evidence_identity": evidence_identity,
        }
    )
    return (
        "decision_task_"
        + canonical_hash(
            {
                "account_id": account_id,
                "security_id": security_id,
                "condition_identity": condition_identity,
            }
        )[:24],
        condition_identity,
    )


def prepare_decision_tasks(
    run: ManualPortfolioReviewRun,
    items: tuple[ManualPortfolioReviewItem, ...],
) -> tuple[
    tuple[ManualPortfolioReviewItem, ...],
    tuple[DecisionTaskSeed, ...],
]:
    prepared_items: list[ManualPortfolioReviewItem] = []
    seeds: list[DecisionTaskSeed] = []
    review_window = (
        f"{run.window_start_exclusive}..{run.window_end_inclusive}"
    )
    for item in items:
        if item.outcome is not ReviewOutcome.REVIEW_REQUIRED:
            prepared_items.append(item)
            continue
        winner = item.conflict_resolution.get("winner", {})
        if not isinstance(winner, Mapping):
            winner = {}
        rule_id = str(winner.get("rule_id", "manual_review"))
        candidate_intent = str(
            winner.get("intent_type", "manual_disposition")
        )
        evidence_identity = str(
            item.conflict_resolution.get(
                "evidence_identity",
                canonical_hash(
                    {
                        "data_snapshot_ids": item.data_snapshot_ids,
                        "research_run_ids": item.research_run_ids,
                        "evidence_ids": item.evidence_ids,
                        "market_snapshot_ids": item.market_snapshot_ids,
                    }
                ),
            )
        )
        task_id, condition_identity = derive_task_identity(
            account_id=item.account_id,
            security_id=item.security_id,
            plan_version_id=item.plan_version_id,
            rule_id=rule_id,
            candidate_intent=candidate_intent,
            review_window=review_window,
            evidence_identity=evidence_identity,
        )
        reason_code = (
            item.evaluation_reason_code
            or next(iter(item.blocked_reasons), None)
            or next(iter(item.unable_reasons), None)
            or "MANUAL_REVIEW_REQUIRED"
        )
        task_kind = (
            "grid_trigger"
            if "grid" in rule_id.lower()
            else "manual_review"
        )
        seed = DecisionTaskSeed(
            decision_task_id=task_id,
            account_id=item.account_id,
            security_id=item.security_id,
            review_run_id=item.review_run_id,
            review_item_id=item.review_item_id,
            plan_version_id=item.plan_version_id,
            plan_evaluation_id=item.plan_evaluation_id,
            task_kind=task_kind,
            reason_code=reason_code,
            priority=(
                "high" if item.blocked_reasons else "normal"
            ),
            condition_identity=condition_identity,
            created_at=item.created_at,
        )
        revised = replace(item, decision_task_ids=(task_id,))
        revised = replace(
            revised,
            content_hash=canonical_hash(
                {
                    key: value
                    for key, value in revised.__dict__.items()
                    if key != "content_hash"
                }
            ),
        )
        revised.validate()
        prepared_items.append(revised)
        seeds.append(seed)
    return tuple(prepared_items), tuple(seeds)


def finalize_decision_tasks(
    seeds: tuple[DecisionTaskSeed, ...],
    evidence_manifest_id: str,
) -> tuple[DecisionTask, ...]:
    tasks: list[DecisionTask] = []
    for seed in seeds:
        base = DecisionTask(
            **seed.__dict__,
            evidence_manifest_id=evidence_manifest_id,
            content_hash="",
        )
        identity = {
            key: value
            for key, value in base.__dict__.items()
            if key
            not in {
                "content_hash",
                "state",
                "transition_seq",
                "latest_transition_id",
                "disposition",
                "deferral_condition",
            }
        }
        task = replace(base, content_hash=canonical_hash(identity))
        task.validate()
        tasks.append(task)
    return tuple(tasks)


def build_transition(
    *,
    task: DecisionTask,
    to_status: DecisionTaskState,
    trigger_kind: str,
    disposition: UserDisposition | None,
    deferral_condition: DeferralCondition | None,
    evidence_ref: str | None,
    action_log_entry_id: str | None,
    decision_actor: str,
    interaction_channel: str,
    transport_actor: str,
    occurred_at: str,
) -> DecisionTaskTransition:
    base = DecisionTaskTransition(
        transition_id="",
        decision_task_id=task.decision_task_id,
        transition_seq=task.transition_seq + 1,
        from_status=task.state,
        to_status=to_status,
        trigger_kind=trigger_kind,
        disposition=disposition,
        deferral_condition=deferral_condition,
        evidence_ref=evidence_ref,
        action_log_entry_id=action_log_entry_id,
        decision_actor=decision_actor,
        interaction_channel=interaction_channel,
        transport_actor=transport_actor,
        occurred_at=occurred_at,
        content_hash="",
    )
    transition_id = (
        "decision_transition_"
        + canonical_hash(
            {
                "decision_task_id": task.decision_task_id,
                "transition_seq": base.transition_seq,
                "from_status": task.state,
                "to_status": to_status,
                "trigger_kind": trigger_kind,
                "disposition": disposition,
                "deferral_condition": deferral_condition,
                "evidence_ref": evidence_ref,
            }
        )[:24]
    )
    prepared = replace(base, transition_id=transition_id)
    identity = {
        key: value
        for key, value in prepared.__dict__.items()
        if key != "content_hash"
    }
    transition = replace(
        prepared, content_hash=canonical_hash(identity)
    )
    transition.validate()
    return transition


__all__ = [
    "DecisionTask",
    "DecisionTaskError",
    "DecisionTaskState",
    "DecisionTaskTransition",
    "DeferralCondition",
    "UserDisposition",
    "derive_task_identity",
]
