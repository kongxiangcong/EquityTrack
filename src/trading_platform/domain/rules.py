from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Mapping

from trading_platform.identity import canonical_hash


class RuleContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RuleClass(str, Enum):
    HARD = "hard"
    REVIEW = "review"


class RulePriority(str, Enum):
    ORDINARY = "ordinary"
    INVALIDATION = "invalidation"
    RISK = "risk"
    CORE_FLOOR = "core_floor"


class RuleScope(str, Enum):
    MASTER = "master"
    CORE = "core"
    GRID = "grid"


class OperandState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class RuleTruth(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED = "blocked"


class RuleResult(str, Enum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    UNABLE = "unable_to_determine"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED = "blocked"


_OPERAND_IDENTITIES = {
    "security.close_unadjusted",
    "security.previous_close_unadjusted",
    "security.status",
    "market.trend",
    "account.total_quantity",
    "account.remaining_quantity",
    "account.available_quantity",
    "account.cash",
    "account.nav",
    "candidate.quantity",
    "candidate.remaining_quantity",
    "candidate.notional",
    "calendar.complete_session",
    "event.session",
}
_EVENT_TYPES = {
    "thesis_invalidated",
    "risk_limit_breached",
    "review_due",
    "grid_level_observed",
}


@dataclass(frozen=True)
class OperandValue:
    operand_id: str
    value_state: OperandState
    value: Decimal | str | bool | int | None
    unit: str
    currency: str | None
    as_of_identity: str
    evidence_refs: tuple[str, ...]
    reason_code: str | None = None

    def validate(self) -> None:
        if (
            self.operand_id not in _OPERAND_IDENTITIES
            or not self.unit
            or not self.as_of_identity
            or (
                self.value_state is OperandState.KNOWN
                and self.value is None
            )
            or (
                self.value_state is not OperandState.KNOWN
                and self.value is not None
            )
            or (
                self.value_state is not OperandState.KNOWN
                and not self.reason_code
            )
            or (
                isinstance(self.value, Decimal)
                and not self.value.is_finite()
            )
        ):
            raise RuleContractError("OPERAND_VALUE_INVALID")


@dataclass(frozen=True)
class EventWindow:
    event_type: str
    start_session: str
    end_session: str
    event_ids: tuple[str, ...]

    def validate(self) -> None:
        try:
            start = date.fromisoformat(self.start_session)
            end = date.fromisoformat(self.end_session)
        except ValueError as error:
            raise RuleContractError("EVENT_WINDOW_INVALID") from error
        if (
            self.event_type not in _EVENT_TYPES
            or start > end
            or len(set(self.event_ids)) != len(self.event_ids)
        ):
            raise RuleContractError("EVENT_WINDOW_INVALID")


@dataclass(frozen=True, kw_only=True)
class GridConstraint:
    grid_constraint_id: str
    lower_price: Decimal
    upper_price: Decimal
    level_count: int
    quantity_per_level: Decimal
    total_quantity_budget: Decimal
    price_basis: str
    trigger_mode: str
    cooldown_trading_sessions: int
    lot_size: Decimal = Decimal("100")

    def __post_init__(self) -> None:
        decimals = (
            self.lower_price,
            self.upper_price,
            self.quantity_per_level,
            self.total_quantity_budget,
            self.lot_size,
        )
        if (
            not self.grid_constraint_id
            or any(not value.is_finite() for value in decimals)
            or self.lower_price <= 0
            or self.upper_price <= self.lower_price
        ):
            raise RuleContractError("GRID_PRICE_BOUNDS_INVALID")
        if (
            isinstance(self.level_count, bool)
            or not 2 <= self.level_count <= 100
        ):
            raise RuleContractError("GRID_LEVEL_COUNT_INVALID")
        if (
            self.lot_size <= 0
            or self.lot_size != self.lot_size.to_integral_value()
            or self.quantity_per_level <= 0
            or self.quantity_per_level % self.lot_size != 0
        ):
            raise RuleContractError("GRID_LOT_SIZE_INVALID")
        if (
            self.total_quantity_budget < 0
            or self.total_quantity_budget
            != self.total_quantity_budget.to_integral_value()
        ):
            raise RuleContractError("GRID_QUANTITY_BUDGET_INVALID")
        if self.price_basis not in {"unadjusted", "adjusted"}:
            raise RuleContractError("GRID_PRICE_BASIS_INVALID")
        if self.trigger_mode not in {
            "crosses_level",
            "closes_at_or_beyond_level",
        }:
            raise RuleContractError("GRID_TRIGGER_MODE_INVALID")
        if (
            isinstance(self.cooldown_trading_sessions, bool)
            or self.cooldown_trading_sessions < 0
        ):
            raise RuleContractError("GRID_COOLDOWN_INVALID")

    @property
    def generated_levels(self) -> tuple[Decimal, ...]:
        step = (self.upper_price - self.lower_price) / (
            self.level_count - 1
        )
        return tuple(
            self.lower_price + step * index
            for index in range(self.level_count)
        )

    @property
    def generated_levels_hash(self) -> str:
        return canonical_hash(self.generated_levels)

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "grid_constraint_id": self.grid_constraint_id,
            "lower_price": str(self.lower_price),
            "upper_price": str(self.upper_price),
            "level_count": self.level_count,
            "quantity_per_level": str(self.quantity_per_level),
            "total_quantity_budget": str(self.total_quantity_budget),
            "price_basis": self.price_basis,
            "trigger_mode": self.trigger_mode,
            "cooldown_trading_sessions": self.cooldown_trading_sessions,
            "lot_size": str(self.lot_size),
            "generated_levels_hash": self.generated_levels_hash,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.canonical_content)


@dataclass(frozen=True)
class CandidateIntent:
    intent_id: str
    direction: str
    quantity: OperandValue
    remaining_quantity: OperandValue
    notional: OperandValue
    grid_level_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        for operand in (
            self.quantity,
            self.remaining_quantity,
            self.notional,
        ):
            operand.validate()
        known_values = (
            self.quantity.value,
            self.remaining_quantity.value,
            self.notional.value,
        )
        if (
            not self.intent_id
            or self.direction not in {"increase", "decrease", "exit"}
            or self.quantity.operand_id != "candidate.quantity"
            or self.remaining_quantity.operand_id
            != "candidate.remaining_quantity"
            or self.notional.operand_id != "candidate.notional"
            or self.quantity.unit != "share"
            or self.remaining_quantity.unit != "share"
            or self.notional.unit != "CNY"
            or self.notional.currency != "CNY"
            or any(
                value is not None and not isinstance(value, Decimal)
                for value in known_values
            )
            or (
                isinstance(self.quantity.value, Decimal)
                and self.quantity.value <= 0
            )
            or (
                isinstance(self.remaining_quantity.value, Decimal)
                and self.remaining_quantity.value < 0
            )
            or (
                isinstance(self.notional.value, Decimal)
                and self.notional.value < 0
            )
            or len(set(self.grid_level_ids)) != len(
                self.grid_level_ids
            )
        ):
            raise RuleContractError("CANDIDATE_INTENT_INVALID")


@dataclass(frozen=True)
class RuleAstV2:
    node: str
    children: tuple["RuleAstV2", ...] = ()
    operand_id: str | None = None
    operator: str | None = None
    expected: Decimal | str | bool | int | None = None
    threshold_sessions: int | None = None
    event_type: str | None = None
    grid_constraint: GridConstraint | None = None
    ast_version: str = "plan-rule-ast@2"

    def validate(self) -> None:
        if self.ast_version != "plan-rule-ast@2":
            raise RuleContractError("RULE_AST_VERSION_INVALID")
        if self.node in {"all", "any"}:
            valid = len(self.children) >= 1 and all(
                child is not self for child in self.children
            )
        elif self.node == "not":
            valid = len(self.children) == 1
        elif self.node == "comparison":
            valid = (
                not self.children
                and self.operand_id in _OPERAND_IDENTITIES
                and self.operator in {"eq", "ne", "lt", "lte", "gt", "gte"}
                and self.expected is not None
            )
        elif self.node == "elapsed_trading_sessions":
            valid = (
                not self.children
                and self.operand_id == "event.session"
                and isinstance(self.threshold_sessions, int)
                and not isinstance(self.threshold_sessions, bool)
                and self.threshold_sessions >= 0
            )
        elif self.node == "event_window":
            valid = (
                not self.children and self.event_type in _EVENT_TYPES
            )
        elif self.node == "grid_constraint":
            valid = (
                not self.children
                and self.grid_constraint is not None
            )
        else:
            valid = False
        if not valid:
            raise RuleContractError("RULE_AST_NODE_INVALID")
        for child in self.children:
            child.validate()


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: str
    result: RuleResult
    reason_code: str
    operands: tuple[OperandValue, ...]
    candidate_intent: CandidateIntent | None
    matched_grid_levels: tuple[str, ...]
    observed_at: str
    evidence_refs: tuple[str, ...]
    replay_hash: str


def evaluate_rule(
    *,
    rule_id: str,
    rule_class: RuleClass,
    condition: RuleAstV2,
    candidate_intent: CandidateIntent | None,
    operands: Mapping[str, OperandValue],
    complete_sessions: tuple[str, ...],
    event_windows: tuple[EventWindow, ...],
    observed_at: str,
) -> RuleEvaluation:
    condition.validate()
    try:
        date.fromisoformat(observed_at)
        parsed_sessions = tuple(
            date.fromisoformat(session) for session in complete_sessions
        )
    except ValueError as error:
        raise RuleContractError("TRADING_SESSION_SEQUENCE_INVALID") from error
    if (
        len(set(complete_sessions)) != len(complete_sessions)
        or tuple(sorted(parsed_sessions)) != parsed_sessions
    ):
        raise RuleContractError("TRADING_SESSION_SEQUENCE_INVALID")
    for operand in operands.values():
        operand.validate()
    for window in event_windows:
        window.validate()
    if candidate_intent is not None:
        candidate_intent.validate()
    if rule_class is RuleClass.REVIEW:
        truth = RuleTruth.NOT_APPLICABLE
        used: tuple[OperandValue, ...] = ()
        levels: tuple[str, ...] = ()
        reason = "REVIEW_RULE_REQUIRES_ASSESSMENT"
    else:
        truth, used, levels, reason = _evaluate_ast(
            condition,
            operands,
            complete_sessions,
            event_windows,
            observed_at,
        )
        if (
            truth is RuleTruth.TRUE
            and levels
            and (
                candidate_intent is None
                or candidate_intent.grid_level_ids != levels
            )
        ):
            truth = RuleTruth.BLOCKED
            reason = "CANDIDATE_GRID_LEVEL_MISMATCH"
    result = {
        RuleTruth.TRUE: RuleResult.TRIGGERED,
        RuleTruth.FALSE: RuleResult.NOT_TRIGGERED,
        RuleTruth.UNKNOWN: RuleResult.UNABLE,
        RuleTruth.NOT_APPLICABLE: RuleResult.NOT_APPLICABLE,
        RuleTruth.BLOCKED: RuleResult.BLOCKED,
    }[truth]
    evidence = tuple(
        sorted(
            {
                reference
                for operand in used
                for reference in operand.evidence_refs
            }
        )
    )
    payload = {
        "rule_id": rule_id,
        "result": result.value,
        "reason_code": reason,
        "operands": used,
        "candidate_intent": candidate_intent,
        "matched_grid_levels": levels,
        "observed_at": observed_at,
        "evidence_refs": evidence,
    }
    return RuleEvaluation(
        rule_id=rule_id,
        result=result,
        reason_code=reason,
        operands=used,
        candidate_intent=(
            candidate_intent
            if result is RuleResult.TRIGGERED
            else None
        ),
        matched_grid_levels=levels,
        observed_at=observed_at,
        evidence_refs=evidence,
        replay_hash=canonical_hash(payload),
    )


def _evaluate_ast(
    ast: RuleAstV2,
    operands: Mapping[str, OperandValue],
    sessions: tuple[str, ...],
    windows: tuple[EventWindow, ...],
    observed_at: str,
) -> tuple[
    RuleTruth,
    tuple[OperandValue, ...],
    tuple[str, ...],
    str,
]:
    if ast.node in {"all", "any", "not"}:
        evaluated = tuple(
            _evaluate_ast(child, operands, sessions, windows, observed_at)
            for child in ast.children
        )
        truths = tuple(item[0] for item in evaluated)
        if ast.node == "not":
            truth = {
                RuleTruth.TRUE: RuleTruth.FALSE,
                RuleTruth.FALSE: RuleTruth.TRUE,
            }.get(truths[0], truths[0])
        elif RuleTruth.BLOCKED in truths:
            truth = RuleTruth.BLOCKED
        elif ast.node == "all":
            truth = (
                RuleTruth.FALSE
                if RuleTruth.FALSE in truths
                else RuleTruth.UNKNOWN
                if RuleTruth.UNKNOWN in truths
                else RuleTruth.NOT_APPLICABLE
                if RuleTruth.NOT_APPLICABLE in truths
                else RuleTruth.TRUE
            )
        else:
            truth = (
                RuleTruth.TRUE
                if RuleTruth.TRUE in truths
                else RuleTruth.UNKNOWN
                if RuleTruth.UNKNOWN in truths
                else RuleTruth.NOT_APPLICABLE
                if RuleTruth.NOT_APPLICABLE in truths
                else RuleTruth.FALSE
            )
        return (
            truth,
            tuple(value for item in evaluated for value in item[1]),
            tuple(value for item in evaluated for value in item[2]),
            next(
                (
                    item[3]
                    for item in evaluated
                    if item[0]
                    in {
                        RuleTruth.BLOCKED,
                        RuleTruth.UNKNOWN,
                        RuleTruth.NOT_APPLICABLE,
                    }
                ),
                "CONDITION_TRUE"
                if truth is RuleTruth.TRUE
                else "CONDITION_FALSE",
            ),
        )
    if ast.node == "comparison":
        operand = operands.get(str(ast.operand_id))
        return _compare(operand, ast.operator, ast.expected)
    if ast.node == "elapsed_trading_sessions":
        operand = operands.get("event.session")
        if operand is None:
            return RuleTruth.UNKNOWN, (), (), "OPERAND_MISSING"
        if operand.value_state is not OperandState.KNOWN:
            return _unavailable(operand)
        if not isinstance(operand.value, str):
            return RuleTruth.BLOCKED, (operand,), (), "OPERAND_CORRUPT"
        elapsed = sum(
            operand.value < session <= observed_at for session in sessions
        )
        matched = elapsed >= int(ast.threshold_sessions or 0)
        return (
            RuleTruth.TRUE if matched else RuleTruth.FALSE,
            (operand,),
            (),
            "ELAPSED_SESSIONS_MATCHED"
            if matched
            else "ELAPSED_SESSIONS_NOT_MATCHED",
        )
    if ast.node == "event_window":
        matching = tuple(
            window
            for window in windows
            if window.event_type == ast.event_type
            and window.start_session <= observed_at <= window.end_session
        )
        return (
            RuleTruth.TRUE if matching else RuleTruth.FALSE,
            (),
            (),
            "EVENT_WINDOW_MATCHED"
            if matching
            else "EVENT_WINDOW_NOT_MATCHED",
        )
    assert ast.grid_constraint is not None
    current = operands.get("security.close_unadjusted")
    previous = operands.get("security.previous_close_unadjusted")
    if current is None or previous is None:
        return RuleTruth.UNKNOWN, (), (), "OPERAND_MISSING"
    if (
        current.value_state is not OperandState.KNOWN
        or previous.value_state is not OperandState.KNOWN
    ):
        return _unavailable(
            current
            if current.value_state is not OperandState.KNOWN
            else previous
        )
    if not isinstance(current.value, Decimal) or not isinstance(
        previous.value, Decimal
    ):
        return (
            RuleTruth.BLOCKED,
            (previous, current),
            (),
            "OPERAND_CORRUPT",
        )
    constraint = ast.grid_constraint
    levels = tuple(
        f"grid_level_{index}"
        for index, level in enumerate(constraint.generated_levels)
        if (
            previous.value < level <= current.value
            or previous.value > level >= current.value
        )
    )
    return (
        RuleTruth.TRUE if levels else RuleTruth.FALSE,
        (previous, current),
        levels,
        "GRID_LEVEL_MATCHED" if levels else "GRID_LEVEL_NOT_MATCHED",
    )


def _compare(
    operand: OperandValue | None,
    operator: str | None,
    expected: Decimal | str | bool | int | None,
) -> tuple[
    RuleTruth,
    tuple[OperandValue, ...],
    tuple[str, ...],
    str,
]:
    if operand is None:
        return RuleTruth.UNKNOWN, (), (), "OPERAND_MISSING"
    if operand.value_state is not OperandState.KNOWN:
        return _unavailable(operand)
    try:
        if operator == "eq":
            matched = operand.value == expected
        elif operator == "ne":
            matched = operand.value != expected
        elif operator == "lt":
            matched = operand.value < expected
        elif operator == "lte":
            matched = operand.value <= expected
        elif operator == "gt":
            matched = operand.value > expected
        else:
            matched = operand.value >= expected
    except TypeError:
        return RuleTruth.BLOCKED, (operand,), (), "OPERAND_TYPE_MISMATCH"
    return (
        RuleTruth.TRUE if matched else RuleTruth.FALSE,
        (operand,),
        (),
        "CONDITION_TRUE" if matched else "CONDITION_FALSE",
    )


def _unavailable(
    operand: OperandValue,
) -> tuple[
    RuleTruth,
    tuple[OperandValue, ...],
    tuple[str, ...],
    str,
]:
    return (
        (
            RuleTruth.UNKNOWN
            if operand.value_state is OperandState.UNKNOWN
            else RuleTruth.NOT_APPLICABLE
        ),
        (operand,),
        (),
        str(operand.reason_code),
    )


def operand_to_dict(operand: OperandValue) -> Mapping[str, object]:
    return {
        "operand_id": operand.operand_id,
        "value_state": operand.value_state.value,
        "value": _encode_scalar(operand.value),
        "unit": operand.unit,
        "currency": operand.currency,
        "as_of_identity": operand.as_of_identity,
        "evidence_refs": operand.evidence_refs,
        "reason_code": operand.reason_code,
    }


def operand_from_dict(payload: Mapping[str, object]) -> OperandValue:
    return OperandValue(
        operand_id=str(payload["operand_id"]),
        value_state=OperandState(str(payload["value_state"])),
        value=_decode_scalar(payload.get("value")),
        unit=str(payload["unit"]),
        currency=(
            str(payload["currency"])
            if payload.get("currency") is not None
            else None
        ),
        as_of_identity=str(payload["as_of_identity"]),
        evidence_refs=tuple(payload.get("evidence_refs", ())),
        reason_code=(
            str(payload["reason_code"])
            if payload.get("reason_code") is not None
            else None
        ),
    )


def candidate_to_dict(
    candidate: CandidateIntent | None,
) -> Mapping[str, object] | None:
    if candidate is None:
        return None
    return {
        "intent_id": candidate.intent_id,
        "direction": candidate.direction,
        "quantity": operand_to_dict(candidate.quantity),
        "remaining_quantity": operand_to_dict(
            candidate.remaining_quantity
        ),
        "notional": operand_to_dict(candidate.notional),
        "grid_level_ids": candidate.grid_level_ids,
    }


def candidate_from_dict(
    payload: Mapping[str, object] | None,
) -> CandidateIntent | None:
    if payload is None:
        return None
    return CandidateIntent(
        intent_id=str(payload["intent_id"]),
        direction=str(payload["direction"]),
        quantity=operand_from_dict(payload["quantity"]),
        remaining_quantity=operand_from_dict(
            payload["remaining_quantity"]
        ),
        notional=operand_from_dict(payload["notional"]),
        grid_level_ids=tuple(payload.get("grid_level_ids", ())),
    )


def ast_to_dict(ast: RuleAstV2) -> Mapping[str, object]:
    return {
        "ast_version": ast.ast_version,
        "node": ast.node,
        "children": tuple(ast_to_dict(child) for child in ast.children),
        "operand_id": ast.operand_id,
        "operator": ast.operator,
        "expected": _encode_scalar(ast.expected),
        "threshold_sessions": ast.threshold_sessions,
        "event_type": ast.event_type,
        "grid_constraint": (
            ast.grid_constraint.canonical_content
            if ast.grid_constraint is not None
            else None
        ),
    }


def ast_from_dict(payload: Mapping[str, object]) -> RuleAstV2:
    grid_payload = payload.get("grid_constraint")
    grid = (
        GridConstraint(
            grid_constraint_id=str(
                grid_payload["grid_constraint_id"]
            ),
            lower_price=Decimal(str(grid_payload["lower_price"])),
            upper_price=Decimal(str(grid_payload["upper_price"])),
            level_count=int(grid_payload["level_count"]),
            quantity_per_level=Decimal(
                str(grid_payload["quantity_per_level"])
            ),
            total_quantity_budget=Decimal(
                str(grid_payload["total_quantity_budget"])
            ),
            price_basis=str(grid_payload["price_basis"]),
            trigger_mode=str(grid_payload["trigger_mode"]),
            cooldown_trading_sessions=int(
                grid_payload["cooldown_trading_sessions"]
            ),
            lot_size=Decimal(str(grid_payload["lot_size"])),
        )
        if isinstance(grid_payload, Mapping)
        else None
    )
    return RuleAstV2(
        node=str(payload["node"]),
        children=tuple(
            ast_from_dict(child)
            for child in payload.get("children", ())
        ),
        operand_id=(
            str(payload["operand_id"])
            if payload.get("operand_id") is not None
            else None
        ),
        operator=(
            str(payload["operator"])
            if payload.get("operator") is not None
            else None
        ),
        expected=_decode_scalar(payload.get("expected")),
        threshold_sessions=(
            int(payload["threshold_sessions"])
            if payload.get("threshold_sessions") is not None
            else None
        ),
        event_type=(
            str(payload["event_type"])
            if payload.get("event_type") is not None
            else None
        ),
        grid_constraint=grid,
        ast_version=str(payload["ast_version"]),
    )


def _encode_scalar(
    value: Decimal | str | bool | int | None,
) -> Mapping[str, object] | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    return {"type": "string", "value": value}


def _decode_scalar(
    payload: object,
) -> Decimal | str | bool | int | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise RuleContractError("RULE_SCALAR_INVALID")
    kind = payload.get("type")
    value = payload.get("value")
    if kind == "decimal":
        return Decimal(str(value))
    if kind == "boolean" and isinstance(value, bool):
        return value
    if (
        kind == "integer"
        and isinstance(value, int)
        and not isinstance(value, bool)
    ):
        return value
    if kind == "string" and isinstance(value, str):
        return value
    raise RuleContractError("RULE_SCALAR_INVALID")


__all__ = [
    "CandidateIntent",
    "EventWindow",
    "GridConstraint",
    "OperandState",
    "OperandValue",
    "RuleAstV2",
    "RuleClass",
    "RuleContractError",
    "RuleEvaluation",
    "RulePriority",
    "RuleResult",
    "RuleScope",
    "ast_from_dict",
    "ast_to_dict",
    "candidate_from_dict",
    "candidate_to_dict",
    "evaluate_rule",
    "operand_from_dict",
    "operand_to_dict",
]
