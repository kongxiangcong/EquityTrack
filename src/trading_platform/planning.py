from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from trading_platform.identifiers import digest, identity, parse_time
from trading_platform.evidence import EvidenceSet
from trading_platform.portfolio import AccountSnapshot, RiskLimitResult
from trading_platform.research.core import InvestmentCase
from trading_platform.result import FrozenFields
from trading_platform.valuation import ValuationAssessment


RULE_TYPES = {"price_above", "price_below", "evidence_equals", "review_on_or_after"}


@dataclass(frozen=True)
class DecisionCard:
    decision_card_id: str
    investment_case_id: str
    valuation_assessment_id: str | None
    risk_limit_result_id: str
    account_snapshot_id: str
    as_of: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class TradePlanDraft:
    draft_id: str
    content_hash: str
    decision_card_id: str
    account_id: str
    security_id: str
    expires_at: str | None
    review_window_end: str | None
    rules: tuple[FrozenFields, ...]
    plan_family_id: str
    revision: int
    supersedes_plan_id: str | None
    close_plan_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "rules": [rule.as_dict() for rule in self.rules]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TradePlanDraft":
        return cls(
            draft_id=str(value["draft_id"]), content_hash=str(value["content_hash"]),
            decision_card_id=str(value["decision_card_id"]), account_id=str(value["account_id"]),
            security_id=str(value["security_id"]), expires_at=str(value["expires_at"]) if value.get("expires_at") is not None else None,
            review_window_end=str(value["review_window_end"]) if value.get("review_window_end") is not None else None,
            rules=tuple(FrozenFields.from_mapping(rule) for rule in value["rules"]),
            plan_family_id=str(value["plan_family_id"]), revision=int(value["revision"]),
            supersedes_plan_id=str(value["supersedes_plan_id"]) if value.get("supersedes_plan_id") is not None else None,
            close_plan_id=str(value["close_plan_id"]) if value.get("close_plan_id") is not None else None,
        )


@dataclass(frozen=True)
class TradePlan:
    trade_plan_id: str
    draft_id: str
    content_hash: str
    decision_card_id: str
    account_id: str
    security_id: str
    rules: tuple[FrozenFields, ...]
    review_window_end: str
    plan_family_id: str
    revision: int
    supersedes_plan_id: str | None
    confirmed_at: str
    confirmed_by: str
    confirmation_channel: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TradePlan":
        return cls(
            trade_plan_id=str(value["trade_plan_id"]), draft_id=str(value["draft_id"]), content_hash=str(value["content_hash"]),
            decision_card_id=str(value["decision_card_id"]), account_id=str(value["account_id"]), security_id=str(value["security_id"]),
            rules=tuple(FrozenFields.from_mapping(rule) for rule in value["rules"]), review_window_end=str(value["review_window_end"]),
            plan_family_id=str(value["plan_family_id"]), revision=int(value["revision"]),
            supersedes_plan_id=str(value["supersedes_plan_id"]) if value.get("supersedes_plan_id") is not None else None,
            confirmed_at=str(value["confirmed_at"]), confirmed_by=str(value["confirmed_by"]), confirmation_channel=str(value["confirmation_channel"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "rules": [rule.as_dict() for rule in self.rules]}


@dataclass(frozen=True)
class PlanClosed:
    plan_closed_id: str
    draft_id: str
    closed_plan_id: str
    plan_family_id: str
    closed_at: str
    closed_by: str
    channel: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlanClosed":
        return cls(
            plan_closed_id=str(value["plan_closed_id"]), draft_id=str(value["draft_id"]),
            closed_plan_id=str(value["closed_plan_id"]), plan_family_id=str(value["plan_family_id"]),
            closed_at=str(value["closed_at"]), closed_by=str(value["closed_by"]), channel=str(value["channel"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class PreparedPlan:
    risk_limit_result: RiskLimitResult
    decision_card: DecisionCard
    trade_plan_draft: TradePlanDraft

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_limit_result": self.risk_limit_result.as_dict(),
            "decision_card": self.decision_card.as_dict(),
            "trade_plan_draft": self.trade_plan_draft.as_dict(),
        }


@dataclass(frozen=True)
class PlanConfirmation:
    kind: str
    record: TradePlan | PlanClosed

    def as_dict(self) -> dict[str, Any]:
        return self.record.as_dict()


@dataclass(frozen=True)
class PlanEvaluation:
    plan_evaluation_id: str
    trade_plan_id: str
    evidence_set_id: str
    as_of: str
    status: str
    rule_results: tuple[FrozenFields, ...]
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "plan_evaluation_id": self.plan_evaluation_id,
            "trade_plan_id": self.trade_plan_id,
            "evidence_set_id": self.evidence_set_id,
            "as_of": self.as_of,
            "status": self.status,
            "rule_results": [rule.as_dict() for rule in self.rule_results],
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


def is_active_plan(
    plan: TradePlan,
    plans: Sequence[TradePlan],
    closings: Sequence[PlanClosed],
) -> bool:
    plan_id = plan.trade_plan_id
    superseded = any(candidate.supersedes_plan_id == plan_id for candidate in plans)
    closed = any(candidate.closed_plan_id == plan_id for candidate in closings)
    return not superseded and not closed


def prepare(
    investment_case: InvestmentCase,
    valuation: ValuationAssessment | None,
    account: AccountSnapshot,
    risk: RiskLimitResult,
    plan: Mapping[str, Any],
    *,
    superseded_plan: TradePlan | None = None,
    closed_plan: TradePlan | None = None,
    existing_plans: Sequence[TradePlan] = (),
    existing_closings: Sequence[PlanClosed] = (),
) -> PreparedPlan:
    if valuation is not None and valuation.investment_case_id != investment_case.investment_case_id:
        raise ValueError("ValuationAssessment does not reference the InvestmentCase")
    if plan.get("supersedes_plan_id") and superseded_plan is None:
        raise ValueError("superseded TradePlan does not exist")
    if plan.get("close_plan_id") and closed_plan is None:
        raise ValueError("TradePlan to close does not exist")
    if plan.get("supersedes_plan_id") and plan.get("close_plan_id"):
        raise ValueError("a draft cannot revise and close at the same time")
    lifecycle_target = superseded_plan or closed_plan
    if lifecycle_target is not None and not is_active_plan(
        lifecycle_target, existing_plans, existing_closings
    ):
        raise ValueError("only the active TradePlan can be revised or closed")
    rules = plan.get("rules", [])
    if not isinstance(rules, list) or any(
        not isinstance(rule, Mapping) or rule.get("type") not in RULE_TYPES or not rule.get("rule_id")
        for rule in rules
    ):
        raise ValueError("PlanRule must use a finite supported type")
    forbidden = {"order", "broker_order", "automatic_execution", "monitor_only"}
    if forbidden.intersection(plan):
        raise ValueError("the requested plan capability is outside the finite planning Interface")

    card = {
        "investment_case_id": investment_case.investment_case_id,
        "valuation_assessment_id": valuation.valuation_assessment_id if valuation else None,
        "risk_limit_result_id": risk.risk_limit_result_id,
        "account_snapshot_id": account.snapshot_id,
        "as_of": investment_case.as_of,
    }
    card["decision_card_id"] = identity("card", card)
    if superseded_plan:
        family_id = superseded_plan.plan_family_id
        revision = superseded_plan.revision + 1
        if any(
            candidate.plan_family_id == family_id
            and candidate.revision == revision
            for candidate in existing_plans
        ):
            raise ValueError("the next plan revision already exists")
    elif closed_plan:
        family_id = closed_plan.plan_family_id
        revision = closed_plan.revision
    else:
        family_id = identity("plan-family", {"card": card["decision_card_id"]})
        revision = 1
    content = {
        "decision_card_id": card["decision_card_id"],
        "account_id": account.account_id,
        "security_id": investment_case.security_id,
        "expires_at": plan.get("expires_at"),
        "review_window_end": plan.get("review_window_end"),
        "rules": rules,
        "plan_family_id": family_id,
        "revision": revision,
        "supersedes_plan_id": plan.get("supersedes_plan_id"),
        "close_plan_id": plan.get("close_plan_id"),
    }
    content_hash = digest(content)
    draft = {**content, "content_hash": content_hash}
    draft["draft_id"] = identity("draft", draft)
    card_record = DecisionCard(
        decision_card_id=str(card["decision_card_id"]),
        investment_case_id=investment_case.investment_case_id,
        valuation_assessment_id=valuation.valuation_assessment_id if valuation else None,
        risk_limit_result_id=risk.risk_limit_result_id,
        account_snapshot_id=account.snapshot_id,
        as_of=investment_case.as_of,
    )
    rule_records = tuple(FrozenFields.from_mapping(rule) for rule in rules)
    draft_record = TradePlanDraft(
        draft_id=str(draft["draft_id"]), content_hash=content_hash,
        decision_card_id=card_record.decision_card_id, account_id=account.account_id,
        security_id=investment_case.security_id,
        expires_at=str(plan["expires_at"]) if plan.get("expires_at") is not None else None,
        review_window_end=str(plan["review_window_end"]) if plan.get("review_window_end") is not None else None,
        rules=rule_records, plan_family_id=str(family_id), revision=revision,
        supersedes_plan_id=str(plan["supersedes_plan_id"]) if plan.get("supersedes_plan_id") is not None else None,
        close_plan_id=str(plan["close_plan_id"]) if plan.get("close_plan_id") is not None else None,
    )
    return PreparedPlan(
        risk_limit_result=risk,
        decision_card=card_record,
        trade_plan_draft=draft_record,
    )


def confirm(
    draft: TradePlanDraft,
    confirmation: Mapping[str, Any],
    *,
    existing_plans: Sequence[TradePlan] = (),
    existing_closings: Sequence[PlanClosed] = (),
) -> PlanConfirmation:
    if any(candidate.draft_id == draft.draft_id for candidate in existing_plans) or any(
        candidate.draft_id == draft.draft_id for candidate in existing_closings
    ):
        raise StalePlan("the TradePlanDraft has already been confirmed")
    if confirmation.get("explicit_confirmation") is not True:
        raise ValueError("explicit confirmation is required")
    if confirmation.get("content_hash") != draft.content_hash:
        raise StalePlan("content hash does not match the final draft")
    confirmed_at = str(confirmation.get("confirmed_at", ""))
    if not confirmed_at or not confirmation.get("confirmed_by") or not confirmation.get("channel"):
        raise ValueError("confirmation time, actor, and channel are required")
    if draft.expires_at and parse_time(confirmed_at) > parse_time(draft.expires_at):
        raise StalePlan("the TradePlanDraft has expired")
    metadata = {
        "confirmed_at": confirmed_at,
        "confirmed_by": str(confirmation["confirmed_by"]),
        "confirmation_channel": str(confirmation["channel"]),
    }
    if draft.close_plan_id:
        closed = {
            "draft_id": draft.draft_id,
            "closed_plan_id": draft.close_plan_id,
            "plan_family_id": draft.plan_family_id,
            "closed_at": confirmed_at,
            "closed_by": metadata["confirmed_by"],
            "channel": metadata["confirmation_channel"],
        }
        closed["plan_closed_id"] = identity("plan-closed", closed)
        return PlanConfirmation("PlanClosed", PlanClosed.from_dict(closed))
    plan = {
        "draft_id": draft.draft_id,
        "content_hash": draft.content_hash,
        "decision_card_id": draft.decision_card_id,
        "account_id": draft.account_id,
        "security_id": draft.security_id,
        "rules": [rule.as_dict() for rule in draft.rules],
        "review_window_end": draft.review_window_end,
        "plan_family_id": draft.plan_family_id,
        "revision": draft.revision,
        "supersedes_plan_id": draft.supersedes_plan_id,
        **metadata,
    }
    plan["trade_plan_id"] = identity("plan", plan)
    return PlanConfirmation("TradePlan", TradePlan.from_dict(plan))


class StalePlan(ValueError):
    pass


def evaluate(plan: TradePlan, evidence: EvidenceSet) -> PlanEvaluation:
    items = {item.name: item for item in evidence.items}
    results: list[dict[str, Any]] = []
    for rule in plan.rules:
        rule_type = rule["type"]
        evidence_name = str(rule.get("evidence_name", ""))
        item = items.get(evidence_name) if evidence_name else None
        if rule_type == "review_on_or_after":
            triggered = parse_time(evidence.as_of) >= parse_time(str(rule["threshold"]))
            results.append({"rule_id": rule["rule_id"], "status": "triggered" if triggered else "not_triggered", "basis": evidence.as_of})
        elif item is None or item.missing_reason is not None:
            results.append({"rule_id": rule["rule_id"], "status": "insufficient", "missing": [evidence_name]})
        elif rule_type in {"price_above", "price_below"}:
            observed = float(str(item.value))
            threshold = float(str(rule["threshold"]))
            triggered = observed > threshold if rule_type == "price_above" else observed < threshold
            results.append({"rule_id": rule["rule_id"], "status": "triggered" if triggered else "not_triggered", "observed": str(item.value), "threshold": str(rule["threshold"]), "source_id": item.source_id})
        else:
            triggered = item.value == rule.get("expected")
            results.append({"rule_id": rule["rule_id"], "status": "triggered" if triggered else "not_triggered", "observed": item.value, "source_id": item.source_id})
    statuses = {result["status"] for result in results}
    status = "triggered" if "triggered" in statuses else "insufficient" if "insufficient" in statuses else "not_triggered"
    evaluation = {
        "trade_plan_id": plan.trade_plan_id,
        "evidence_set_id": evidence.evidence_set_id,
        "as_of": evidence.as_of,
        "status": status,
        "rule_results": results,
    }
    return PlanEvaluation(
        plan_evaluation_id=identity("evaluation", evaluation),
        trade_plan_id=plan.trade_plan_id,
        evidence_set_id=evidence.evidence_set_id,
        as_of=evidence.as_of,
        status=status,
        rule_results=tuple(FrozenFields.from_mapping(result) for result in results),
    )


def blocked_evaluation(plan: TradePlan, evidence: EvidenceSet, reason: str) -> PlanEvaluation:
    evaluation = {
        "trade_plan_id": plan.trade_plan_id,
        "evidence_set_id": evidence.evidence_set_id,
        "as_of": evidence.as_of,
        "status": "blocked",
        "reason": reason,
        "rule_results": [],
    }
    return PlanEvaluation(
        plan_evaluation_id=identity("evaluation", evaluation),
        trade_plan_id=plan.trade_plan_id,
        evidence_set_id=evidence.evidence_set_id,
        as_of=evidence.as_of,
        status="blocked",
        rule_results=(),
        reason=reason,
    )
