from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from trading_platform.identity import canonical_hash


@dataclass(frozen=True)
class TradePlanMasterId:
    account_id: str
    security_id: str
    value: str

    @classmethod
    def derive(
        cls, account_id: str, security_id: str
    ) -> "TradePlanMasterId":
        if not account_id or not security_id:
            raise PlanValidationError("PLAN_OWNERSHIP_REQUIRED")
        digest = canonical_hash(
            {
                "schema_version": "TradePlanMasterId@1",
                "account_id": account_id,
                "security_id": security_id,
            }
        )
        return cls(
            account_id=account_id,
            security_id=security_id,
            value=f"trade_plan_master_{digest[:24]}",
        )


@dataclass(frozen=True)
class TradePlanMaster:
    plan_id: TradePlanMasterId
    strategy_version_id: str
    lifecycle_status: str
    transition_seq: int
    created_at: str
    schema_version: str = "TradePlanMaster@1"

    def validate(self) -> None:
        expected = TradePlanMasterId.derive(
            self.plan_id.account_id, self.plan_id.security_id
        )
        if (
            self.schema_version != "TradePlanMaster@1"
            or self.plan_id != expected
            or not self.strategy_version_id
            or self.lifecycle_status
            not in {"inactive", "active", "ended", "legacy_read_only"}
            or self.transition_seq < 0
            or not self.created_at
        ):
            raise PlanValidationError("PLAN_MASTER_INVALID")


@dataclass(frozen=True)
class PlanReference:
    ref_type: str
    ref_id: str
    resolution_status: str = "resolved"


@dataclass(frozen=True)
class AdjustedPriceEvidence:
    rule_id: str
    condition_path: tuple[int, ...]
    data_snapshot_id: str
    factor_set_id: str
    adjusted_price_decimal: str
    canonical_unadjusted_price_decimal: str
    factor_decimal: str
    algorithm_version: str


@dataclass(frozen=True)
class PlanConstant:
    constant_type: str
    value: str
    unit: str | None = None
    currency: str | None = None
    secondary_value: str | None = None


@dataclass(frozen=True)
class PlanCondition:
    node_kind: str
    metric_ref: str | None = None
    operator: str | None = None
    constant: PlanConstant | None = None
    observation: str | None = None
    children: tuple["PlanCondition", ...] = ()
    ast_version: str = "plan-condition-ast@1"


@dataclass(frozen=True)
class PlanRule:
    rule_id: str
    rule_kind: str
    effect: str
    applies_to: str
    condition: PlanCondition
    input_applicability: str = "applicable"


@dataclass(frozen=True)
class PlanDraftContent:
    security_id: str
    based_on_version_id: str | None
    references: tuple[PlanReference, ...]
    data_snapshot_id: str
    horizon_start: str
    horizon_end: str
    review_by: str
    rules: tuple[PlanRule, ...]
    max_planned_notional: str
    max_planned_loss: str
    currency: str
    market_gate_policy_version: str
    metric_catalog_version: str
    evaluator_policy_version: str
    user_input_source: str
    rationale: str
    adjusted_price_evidence: tuple[AdjustedPriceEvidence, ...] = ()
    account_snapshot_id: str | None = None


@dataclass(frozen=True)
class CreatePlanDraftCommand:
    invocation_id: str
    content: PlanDraftContent
    plan_id: str | None = None


@dataclass(frozen=True)
class UpdatePlanDraftCommand:
    invocation_id: str
    draft_id: str
    plan_id: str | None
    expected_revision: int
    content: PlanDraftContent


@dataclass(frozen=True)
class DiscardPlanDraftCommand:
    invocation_id: str
    draft_id: str
    expected_revision: int


@dataclass(frozen=True)
class ConfirmPlanDraftCommand:
    invocation_id: str
    draft_id: str
    expected_revision: int
    activation_mode: str


@dataclass(frozen=True)
class ActivatePlanVersionCommand:
    invocation_id: str
    plan_id: str
    plan_version_id: str
    expected_transition_seq: int


@dataclass(frozen=True)
class ChangePlanLifecycleCommand:
    invocation_id: str
    plan_id: str
    expected_transition_seq: int
    reason: str


@dataclass(frozen=True)
class TradePlanDraftView:
    draft_id: str
    plan_id: str | None
    revision: int
    status: str
    content: PlanDraftContent
    content_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TradePlanVersionView:
    plan_id: str
    plan_version_id: str
    version_no: int
    supersedes_version_id: str | None
    lifecycle_status: str
    content: PlanDraftContent
    content_hash: str
    confirmed_at: str
    confirmation_invocation_id: str


@dataclass(frozen=True)
class PlanDiffItem:
    field: str
    before: object
    after: object


@dataclass(frozen=True)
class PlanConfirmationView:
    draft_id: str
    content: PlanDraftContent
    content_hash: str
    sections: tuple["PlanConfirmationSection", ...]
    diff: tuple[PlanDiffItem, ...]
    user_input_source: str
    execution_boundary: str
    portfolio_feasibility: str


@dataclass(frozen=True)
class ActivePlanView:
    plan_id: str
    lifecycle_status: str
    active_version: TradePlanVersionView | None


@dataclass(frozen=True)
class PlanConfirmationSection:
    name: str
    fields: tuple[tuple[str, object], ...]


class PlanValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_RULE_KINDS = {
    "entry_review",
    "adjustment_review",
    "exit_review",
    "invalidation",
    "risk_limit",
    "market_gate",
    "observation",
}
_EFFECTS = {
    "prompt_review",
    "mark_invalidation_candidate",
    "mark_risk_limit_breach",
    "block_user_intent",
    "observe",
}
_APPLIES = {"entry", "increase", "decrease", "exit", "plan"}
_OPERATORS = {
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "between",
    "crosses_above",
    "crosses_below",
    "changed_to",
}
_METRICS = {
    "security.close_unadjusted",
    "security.close_adjusted",
    "security.suspended",
    "security.limit_state",
    "market.trend",
    "market.breadth",
    "market.liquidity",
    "market.volatility",
    "position.quantity",
    "portfolio.net_asset_value",
}
_OBSERVATIONS = {"current_complete_session", "previous_complete_session"}
_METRIC_TYPES = {
    "security.close_unadjusted": ("decimal", "CNY_per_share", {"CNY"}),
    "security.close_adjusted": ("decimal", "CNY_per_share", {"CNY"}),
    "security.suspended": ("bool", "market_status", {"true", "false"}),
    "security.limit_state": ("enum", "security_limit_state", {"up", "down", "none"}),
    "market.trend": ("enum", "market_trend", {"up", "down", "mixed"}),
    "market.breadth": ("enum", "market_breadth", {"broad", "narrow", "mixed"}),
    "market.liquidity": ("enum", "market_liquidity", {"ample", "normal", "thin"}),
    "market.volatility": ("enum", "market_volatility", {"high", "normal", "low"}),
    "position.quantity": ("decimal", "share", set()),
    "portfolio.net_asset_value": ("decimal", "CNY", {"CNY"}),
}


def validate_plan_content(
    content: PlanDraftContent,
    *,
    security_currency: str | None,
    snapshot_scope: str | None,
    resolved_research_ids: set[str],
    factor_sets: dict[str, tuple[str, str, str, str]],
    account_metrics_supported: bool = False,
) -> None:
    if security_currency is None or snapshot_scope != content.security_id:
        raise PlanValidationError("PLAN_REFERENCE_INVALID")
    if content.currency != security_currency or content.currency != "CNY":
        raise PlanValidationError("PLAN_CURRENCY_INVALID")
    notional, loss = _decimal(content.max_planned_notional), _decimal(
        content.max_planned_loss
    )
    if loss > notional:
        raise PlanValidationError("PLAN_RISK_LIMIT_INVALID")
    try:
        start, review, end = map(
            date.fromisoformat,
            (content.horizon_start, content.review_by, content.horizon_end),
        )
    except ValueError as error:
        raise PlanValidationError("PLAN_HORIZON_INVALID") from error
    if not start <= review <= end:
        raise PlanValidationError("PLAN_HORIZON_INVALID")
    if (
        content.user_input_source != "user_fixture_input"
        or not content.rationale
        or len(content.rationale) > 2000
    ):
        raise PlanValidationError("PLAN_USER_INPUT_INVALID")
    if (
        not content.rules
        or len(content.rules) > 64
        or len({rule.rule_id for rule in content.rules}) != len(content.rules)
    ):
        raise PlanValidationError("PLAN_RULE_INVALID")
    research_refs = [
        item for item in content.references if item.ref_type == "ResearchRun"
    ]
    if (
        len(research_refs) != 1
        or research_refs[0].resolution_status != "resolved"
        or research_refs[0].ref_id not in resolved_research_ids
    ):
        raise PlanValidationError("PLAN_RESEARCH_REFERENCE_INVALID")
    if any(
        item.ref_type not in {"ResearchRun", "Evidence"}
        or item.resolution_status not in {"resolved", "unresolved_external"}
        for item in content.references
    ):
        raise PlanValidationError("PLAN_REFERENCE_INVALID")
    if not any(item.ref_type == "Evidence" for item in content.references):
        raise PlanValidationError("PLAN_EVIDENCE_REFERENCE_REQUIRED")
    adjusted_paths: set[tuple[str, tuple[int, ...]]] = set()
    for rule in content.rules:
        if (
            rule.rule_kind not in _RULE_KINDS
            or rule.effect not in _EFFECTS
            or rule.applies_to not in _APPLIES
        ):
            raise PlanValidationError("PLAN_RULE_INVALID")
        metrics = _validate_condition(rule.condition, content.currency)
        if (
            metrics & {"position.quantity", "portfolio.net_asset_value"}
            and rule.input_applicability == "applicable"
            and not account_metrics_supported
        ):
            raise PlanValidationError("PLAN_ACCOUNT_INPUT_APPLICABILITY_REQUIRED")
        if (
            metrics & {"position.quantity", "portfolio.net_asset_value"}
            and rule.input_applicability != "applicable"
            and account_metrics_supported
        ):
            raise PlanValidationError("PLAN_ACCOUNT_INPUT_APPLICABILITY_INVALID")
        if (
            not metrics & {"position.quantity", "portfolio.net_asset_value"}
            and rule.input_applicability != "applicable"
        ):
            raise PlanValidationError("PLAN_RULE_APPLICABILITY_INVALID")
        adjusted_paths.update(
            (rule.rule_id, path)
            for path, leaf in _leaves(rule.condition)
            if leaf.metric_ref == "security.close_adjusted"
        )
    evidence_by_path = {
        (item.rule_id, item.condition_path): item
        for item in content.adjusted_price_evidence
    }
    if adjusted_paths and not evidence_by_path:
        raise PlanValidationError("PLAN_ADJUSTED_PRICE_EVIDENCE_REQUIRED")
    if set(evidence_by_path) != adjusted_paths:
        raise PlanValidationError("PLAN_ADJUSTED_PRICE_EVIDENCE_INVALID")
    for evidence in content.adjusted_price_evidence:
        adjusted, unadjusted, factor = (
            _decimal(evidence.adjusted_price_decimal, True),
            _decimal(evidence.canonical_unadjusted_price_decimal, True),
            _decimal(evidence.factor_decimal, True),
        )
        rule = next(item for item in content.rules if item.rule_id == evidence.rule_id)
        leaf = dict(_leaves(rule.condition))[evidence.condition_path]
        threshold = leaf.constant
        factor_provenance = factor_sets.get(evidence.factor_set_id)
        if (
            factor_provenance is None
            or factor_provenance[0] != content.data_snapshot_id
            or factor_provenance[1] != "unique_deterministic"
            or not factor_provenance[2]
            or factor_provenance[3] != evidence.algorithm_version
            or evidence.data_snapshot_id != content.data_snapshot_id
            or threshold is None
            or threshold.value != evidence.adjusted_price_decimal
            or evidence.algorithm_version != "deterministic_reverse@1"
            or adjusted * factor != unadjusted
        ):
            raise PlanValidationError("PLAN_ADJUSTED_PRICE_EVIDENCE_INVALID")


def _validate_condition(condition: PlanCondition, currency: str) -> set[str]:
    if condition.ast_version != "plan-condition-ast@1" or condition.node_kind not in {
        "leaf",
        "all",
        "any",
        "not",
    }:
        raise PlanValidationError("PLAN_AST_INVALID")
    if condition.node_kind != "leaf":
        if (
            any(
                value is not None
                for value in (
                    condition.metric_ref,
                    condition.operator,
                    condition.constant,
                    condition.observation,
                )
            )
            or not condition.children
            or (condition.node_kind == "not" and len(condition.children) != 1)
        ):
            raise PlanValidationError("PLAN_AST_INVALID")
        metrics: set[str] = set()
        for child in condition.children:
            metrics.update(_validate_condition(child, currency))
        return metrics
    if condition.children or condition.operator not in _OPERATORS:
        raise PlanValidationError("PLAN_OPERATOR_INVALID")
    if condition.metric_ref not in _METRICS:
        raise PlanValidationError("PLAN_METRIC_INVALID")
    if condition.observation not in _OBSERVATIONS or condition.constant is None:
        raise PlanValidationError("PLAN_CONDITION_INVALID")
    constant = condition.constant
    expected_type, expected_unit, allowed = _METRIC_TYPES[condition.metric_ref]
    if (
        constant.constant_type != expected_type
        or constant.unit != expected_unit
        or constant.currency not in {None, currency}
    ):
        raise PlanValidationError("PLAN_CONDITION_INVALID")
    allowed_operators = (
        {
            "eq",
            "ne",
            "lt",
            "lte",
            "gt",
            "gte",
            "between",
            "crosses_above",
            "crosses_below",
        }
        if expected_type == "decimal"
        else {"eq", "ne", "changed_to"}
    )
    if condition.operator not in allowed_operators:
        raise PlanValidationError("PLAN_OPERATOR_INVALID")
    if expected_type == "decimal":
        _decimal(constant.value, condition.metric_ref.startswith("security.close"))
        if condition.operator == "between":
            if constant.secondary_value is None or _decimal(
                constant.secondary_value
            ) < _decimal(constant.value):
                raise PlanValidationError("PLAN_CONDITION_INVALID")
        elif constant.secondary_value is not None:
            raise PlanValidationError("PLAN_CONDITION_INVALID")
    elif expected_type in {"enum", "bool"}:
        if constant.value not in allowed or constant.secondary_value is not None:
            raise PlanValidationError("PLAN_CONDITION_INVALID")
    return {condition.metric_ref}


def _decimal(value: str, positive: bool = False) -> Decimal:
    if not re.fullmatch(r"(?:0|[1-9]\d{0,19})(?:\.\d{1,12})?", value):
        raise PlanValidationError("PLAN_AMOUNT_INVALID")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise PlanValidationError("PLAN_AMOUNT_INVALID") from error
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise PlanValidationError("PLAN_AMOUNT_INVALID")
    return number


def _leaves(
    condition: PlanCondition, path: tuple[int, ...] = ()
) -> tuple[tuple[tuple[int, ...], PlanCondition], ...]:
    if condition.node_kind == "leaf":
        return ((path, condition),)
    return tuple(
        item
        for index, child in enumerate(condition.children)
        for item in _leaves(child, path + (index,))
    )
