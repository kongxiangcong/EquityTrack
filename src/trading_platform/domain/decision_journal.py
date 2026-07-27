from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from trading_platform.identity import canonical_hash

from .decision_tasks import UserDisposition


class DecisionJournalError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


ExecutionVerificationState = Enum(
    "ExecutionVerificationState",
    {
        "USER_DECLARED_UNVERIFIED": "user_declared_unverified",
        "BROKER_MATCHED": "broker_matched",
        "CONFLICTED": "conflicted",
    },
    type=str,
)


@dataclass(frozen=True)
class ActionLogEntry:
    action_log_entry_id: str
    decision_task_id: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    disposition: UserDisposition
    reason: str
    occurred_at: str
    recorded_at: str
    corrects_entry_id: str | None
    content_hash: str
    schema_version: str = "ActionLogEntry@1"

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key != "content_hash"
        }
        try:
            occurred = datetime.fromisoformat(self.occurred_at)
            recorded = datetime.fromisoformat(self.recorded_at)
        except ValueError as error:
            raise DecisionJournalError(
                "ACTION_LOG_TIME_INVALID"
            ) from error
        if (
            self.schema_version != "ActionLogEntry@1"
            or not self.action_log_entry_id
            or not self.decision_task_id
            or not self.decision_actor.startswith("user:")
            or self.interaction_channel not in {"skill", "cli"}
            or not self.transport_actor
            or not self.reason.strip()
            or occurred.tzinfo is None
            or recorded.tzinfo is None
            or recorded < occurred
            or self.content_hash != canonical_hash(identity)
        ):
            raise DecisionJournalError("ACTION_LOG_INVALID")


@dataclass(frozen=True)
class ExecutionRecord:
    execution_record_id: str
    action_log_entry_id: str
    account_id: str
    security_id: str
    plan_version_id: str | None
    decision_task_id: str
    effective_at: str
    effective_session: str
    intent_type: str
    quantity: str
    price_state: str
    price_value: str | None
    fee_state: str
    fee_value: str | None
    currency: str
    verification_status: ExecutionVerificationState
    corrects_execution_record_id: str | None
    content_hash: str
    confirmed_at: str
    schema_version: str = "ExecutionRecord@1"

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key != "content_hash"
        }
        try:
            effective = datetime.fromisoformat(self.effective_at)
            confirmed = datetime.fromisoformat(self.confirmed_at)
            session = date.fromisoformat(self.effective_session)
        except ValueError as error:
            raise DecisionJournalError(
                "EXECUTION_TIME_INVALID"
            ) from error
        quantity = _positive_decimal(
            self.quantity, "EXECUTION_QUANTITY_INVALID"
        )
        _state_value(
            self.price_state,
            self.price_value,
            "EXECUTION_PRICE_INVALID",
        )
        _state_value(
            self.fee_state,
            self.fee_value,
            "EXECUTION_FEE_INVALID",
        )
        if (
            self.schema_version != "ExecutionRecord@1"
            or not self.execution_record_id
            or not self.action_log_entry_id
            or not self.account_id
            or not self.security_id
            or not self.decision_task_id
            or self.intent_type not in {"increase", "decrease"}
            or quantity <= 0
            or len(self.currency) != 3
            or self.currency != self.currency.upper()
            or effective.tzinfo is None
            or confirmed.tzinfo is None
            or confirmed < effective
            or effective.date() != session
            or self.content_hash != canonical_hash(identity)
        ):
            raise DecisionJournalError("EXECUTION_RECORD_INVALID")


@dataclass(frozen=True)
class ExecutionCorrection:
    original_execution_record_id: str
    original_action_log_entry_id: str
    corrected_execution_record_id: str
    corrected_action_log_entry_id: str
    reason: str

    def validate(self) -> None:
        if (
            not self.original_execution_record_id
            or not self.original_action_log_entry_id
            or not self.corrected_execution_record_id
            or not self.corrected_action_log_entry_id
            or not self.reason.strip()
            or self.original_execution_record_id
            == self.corrected_execution_record_id
            or self.original_action_log_entry_id
            == self.corrected_action_log_entry_id
        ):
            raise DecisionJournalError("EXECUTION_CORRECTION_INVALID")


def build_action_log_entry(
    *,
    decision_task_id: str,
    disposition: UserDisposition,
    reason: str,
    occurred_at: str,
    recorded_at: str,
    decision_actor: str,
    interaction_channel: str,
    transport_actor: str,
    corrects_entry_id: str | None = None,
) -> ActionLogEntry:
    base = ActionLogEntry(
        action_log_entry_id="",
        decision_task_id=decision_task_id,
        decision_actor=decision_actor,
        interaction_channel=interaction_channel,
        transport_actor=transport_actor,
        disposition=disposition,
        reason=reason,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        corrects_entry_id=corrects_entry_id,
        content_hash="",
    )
    entry_id = (
        "action_log_"
        + canonical_hash(
            {
                "decision_task_id": decision_task_id,
                "disposition": disposition,
                "occurred_at": occurred_at,
                "corrects_entry_id": corrects_entry_id,
            }
        )[:24]
    )
    prepared = replace(base, action_log_entry_id=entry_id)
    entry = replace(
        prepared,
        content_hash=canonical_hash(
            {
                key: value
                for key, value in prepared.__dict__.items()
                if key != "content_hash"
            }
        ),
    )
    entry.validate()
    return entry


def build_execution_record(
    *,
    action: ActionLogEntry,
    account_id: str,
    security_id: str,
    plan_version_id: str | None,
    effective_at: str,
    effective_session: str,
    intent_type: str,
    quantity: str,
    price_state: str,
    price_value: str | None,
    fee_state: str,
    fee_value: str | None,
    currency: str,
    confirmed_at: str,
    corrects_execution_record_id: str | None = None,
) -> ExecutionRecord:
    base = ExecutionRecord(
        execution_record_id="",
        action_log_entry_id=action.action_log_entry_id,
        account_id=account_id,
        security_id=security_id,
        plan_version_id=plan_version_id,
        decision_task_id=action.decision_task_id,
        effective_at=effective_at,
        effective_session=effective_session,
        intent_type=intent_type,
        quantity=_decimal_text(
            quantity, "EXECUTION_QUANTITY_INVALID", positive=True
        ),
        price_state=price_state,
        price_value=_normalized_state_value(
            price_state, price_value, "EXECUTION_PRICE_INVALID"
        ),
        fee_state=fee_state,
        fee_value=_normalized_state_value(
            fee_state, fee_value, "EXECUTION_FEE_INVALID"
        ),
        currency=currency,
        verification_status=(
            ExecutionVerificationState.USER_DECLARED_UNVERIFIED
        ),
        corrects_execution_record_id=corrects_execution_record_id,
        content_hash="",
        confirmed_at=confirmed_at,
    )
    record_id = (
        "execution_"
        + canonical_hash(
            {
                "action_log_entry_id": action.action_log_entry_id,
                "decision_task_id": action.decision_task_id,
                "effective_at": effective_at,
                "corrects_execution_record_id": (
                    corrects_execution_record_id
                ),
            }
        )[:24]
    )
    prepared = replace(base, execution_record_id=record_id)
    record = replace(
        prepared,
        content_hash=canonical_hash(
            {
                key: value
                for key, value in prepared.__dict__.items()
                if key != "content_hash"
            }
        ),
    )
    record.validate()
    return record


def _positive_decimal(value: str, code: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise DecisionJournalError(code) from error
    if not result.is_finite() or result <= 0:
        raise DecisionJournalError(code)
    return result


def _decimal_text(
    value: str,
    code: str,
    *,
    positive: bool,
) -> str:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise DecisionJournalError(code) from error
    if (
        not result.is_finite()
        or (positive and result <= 0)
        or (not positive and result < 0)
    ):
        raise DecisionJournalError(code)
    rendered = format(result.normalize(), "f")
    return "0" if rendered == "-0" else rendered


def _state_value(
    state: str, value: str | None, code: str
) -> Decimal | None:
    if state not in {"known", "unknown", "not_applicable"}:
        raise DecisionJournalError(code)
    if state == "known":
        if value is None:
            raise DecisionJournalError(code)
        return Decimal(_decimal_text(value, code, positive=False))
    if value is not None:
        raise DecisionJournalError(code)
    return None


def _normalized_state_value(
    state: str, value: str | None, code: str
) -> str | None:
    result = _state_value(state, value, code)
    if result is None:
        return None
    rendered = format(result.normalize(), "f")
    return "0" if rendered == "-0" else rendered


__all__ = [
    "ActionLogEntry",
    "DecisionJournalError",
    "ExecutionCorrection",
    "ExecutionRecord",
    "ExecutionVerificationState",
]
