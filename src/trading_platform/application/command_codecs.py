from __future__ import annotations

import json
from typing import Any

from trading_platform.application.contracts import SecurityIdentity
from trading_platform.application.market_contracts import (
    BuildMarketSnapshotCommand,
    EvaluatePlanCommand,
)
from trading_platform.identity.code import CodeIdentity
from trading_platform.domain.rules import EventWindow, operand_from_dict


class CommandCodecError(ValueError):
    def __init__(self, code: str, substep: str, cause_type: str) -> None:
        super().__init__(code)
        self.code = code
        self.substep = substep
        self.cause_type = cause_type


def decode_watchlist_identity_value(value: Any) -> SecurityIdentity:
    try:
        if not isinstance(value, dict):
            raise TypeError("identity must be an object")
        return SecurityIdentity(**value)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CommandCodecError(
            "WATCHLIST_IDENTITY_INVALID",
            "watchlist_identity.decode",
            type(error).__name__,
        ) from None


def decode_watchlist_identity(payload: bytes) -> SecurityIdentity:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise CommandCodecError(
            "WATCHLIST_IDENTITY_INVALID",
            "watchlist_identity.decode",
            type(error).__name__,
        ) from None
    return decode_watchlist_identity_value(value)


def decode_provider_security_identity_value(value: Any) -> SecurityIdentity:
    """Translate the provider-job identity protocol into the domain contract."""
    try:
        if not isinstance(value, dict) or set(value) - {
            "security_id", "venue", "code", "currency", "listed_from"
        }:
            raise TypeError("provider security identity fields are invalid")
        fields = (
            value["security_id"], value["venue"], value["code"],
            value["currency"], value["listed_from"],
        )
        if not all(isinstance(item, str) and item for item in fields):
            raise TypeError("provider security identity fields must be strings")
        return SecurityIdentity(
            security_id=fields[0],
            market=fields[1],
            code=fields[2],
            currency=fields[3],
            identifier_valid_from=fields[4],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CommandCodecError(
            "WATCHLIST_IDENTITY_INVALID",
            "provider_job.security_identity.decode",
            type(error).__name__,
        ) from None


def decode_market_snapshot_command_value(value: Any) -> BuildMarketSnapshotCommand:
    try:
        if not isinstance(value, dict) or not isinstance(value.get("code_identity"), dict):
            raise TypeError("market command must contain a code identity object")
        value["code_identity"] = CodeIdentity(**value["code_identity"])
        return BuildMarketSnapshotCommand(**value)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CommandCodecError(
            "MARKET_SNAPSHOT_COMMAND_INVALID",
            "market_snapshot_command.decode",
            type(error).__name__,
        ) from None


def decode_market_snapshot_command(payload: bytes) -> BuildMarketSnapshotCommand:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise CommandCodecError(
            "MARKET_SNAPSHOT_COMMAND_INVALID",
            "market_snapshot_command.decode",
            type(error).__name__,
        ) from None
    return decode_market_snapshot_command_value(value)


def decode_plan_evaluation_command_value(value: Any) -> EvaluatePlanCommand:
    try:
        if not isinstance(value, dict):
            raise TypeError("evaluation command must be an object")
        allowed = {
            "invocation_id",
            "plan_version_id",
            "market_snapshot_id",
            "operands",
            "complete_sessions",
            "event_windows",
            "resource_conflict",
        }
        if set(value) - allowed:
            raise TypeError("unknown evaluation command field")
        resource_conflict = value.get("resource_conflict", False)
        if not isinstance(resource_conflict, bool):
            raise TypeError("resource_conflict must be boolean")
        operand_fields = {
            "operand_id",
            "value_state",
            "value",
            "unit",
            "currency",
            "as_of_identity",
            "evidence_refs",
            "reason_code",
        }
        event_fields = {
            "event_type",
            "start_session",
            "end_session",
            "event_ids",
        }
        raw_operands = value.get("operands", ())
        raw_windows = value.get("event_windows", ())
        if (
            not isinstance(raw_operands, (list, tuple))
            or not isinstance(raw_windows, (list, tuple))
            or any(
                not isinstance(item, dict)
                or set(item) - operand_fields
                for item in raw_operands
            )
            or any(
                not isinstance(item, dict)
                or set(item) - event_fields
                for item in raw_windows
            )
        ):
            raise ValueError("invalid typed evaluation input")
        return EvaluatePlanCommand(
            invocation_id=str(value["invocation_id"]),
            plan_version_id=str(value["plan_version_id"]),
            market_snapshot_id=str(value["market_snapshot_id"]),
            operands=tuple(
                operand_from_dict(item)
                for item in raw_operands
            ),
            complete_sessions=tuple(
                str(item)
                for item in value.get("complete_sessions", ())
            ),
            event_windows=tuple(
                EventWindow(
                    event_type=str(item["event_type"]),
                    start_session=str(item["start_session"]),
                    end_session=str(item["end_session"]),
                    event_ids=tuple(item.get("event_ids", ())),
                )
                for item in raw_windows
            ),
            resource_conflict=resource_conflict,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CommandCodecError(
            "PLAN_EVALUATION_COMMAND_INVALID",
            "plan_evaluation_command.decode",
            type(error).__name__,
        ) from None


def decode_plan_evaluation_command(payload: bytes) -> EvaluatePlanCommand:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise CommandCodecError(
            "PLAN_EVALUATION_COMMAND_INVALID",
            "plan_evaluation_command.decode",
            type(error).__name__,
        ) from None
    return decode_plan_evaluation_command_value(value)



__all__ = [
    "CommandCodecError",
    "decode_market_snapshot_command",
    "decode_market_snapshot_command_value",
    "decode_plan_evaluation_command",
    "decode_plan_evaluation_command_value",
    "decode_provider_security_identity_value",
    "decode_watchlist_identity",
    "decode_watchlist_identity_value",
]
