from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.identity import canonical_hash


class AccountStateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExecutionProjectionRecord:
    execution_record_id: str
    account_id: str
    security_id: str
    effective_at: str
    effective_session: str
    intent_type: str
    quantity: str
    price_state: str
    price_value: str | None
    fee_state: str
    fee_value: str | None
    currency: str
    verification_status: str
    corrects_execution_record_id: str | None
    content_hash: str


class ExecutionRecordReader(Protocol):
    def read_confirmed(
        self,
        account_id: str,
        *,
        after_snapshot: AccountSnapshotVersion,
        through_snapshot: AccountSnapshotVersion | None = None,
    ) -> tuple[ExecutionProjectionRecord, ...]: ...


@dataclass(frozen=True)
class EstimatedPosition:
    security_id: str
    total_quantity: str
    available_quantity_state: str
    available_quantity_value: str | None
    cost_state: str
    cost_value: str | None
    market_value_state: str
    market_value_value: str | None


@dataclass(frozen=True)
class EstimatedAccountState:
    schema_version: str
    estimated_account_state_id: str
    account_id: str
    derived_from_snapshot_id: str
    derived_from_snapshot_as_of: str
    derived_from_snapshot_as_of_precision: str
    derived_from_snapshot_session_semantics: str
    snapshot_graph_seal_hash: str
    execution_record_ids: tuple[str, ...]
    positions: tuple[EstimatedPosition, ...]
    cash_state: str
    cash_value: str | None
    currency: str
    nav_state: str
    nav_value: str | None
    fees_state: str
    fees_value: str | None
    status: str
    blocking_reasons: tuple[str, ...]
    unverified_evidence: tuple[str, ...]
    content_hash: str


@dataclass(frozen=True)
class AccountStateDrift:
    schema_version: str
    drift_assessment_id: str
    expected_state_hash: str
    confirmed_snapshot_id: str
    position_differences: tuple[tuple[str, str, str, str], ...]
    cash_difference_state: str
    cash_difference_value: str | None
    explained_by_execution_ids: tuple[str, ...]
    unexplained_drift: tuple[str, ...]
    status: str
    content_hash: str


def derive_estimated_account_state(
    snapshot: AccountSnapshotVersion,
    executions: tuple[ExecutionProjectionRecord, ...],
    *,
    execution_reader_available: bool = True,
    through_snapshot: AccountSnapshotVersion | None = None,
) -> EstimatedAccountState:
    """Fold immutable authority records into one deterministic working state."""
    active, duplicate_failures = _active_executions(
        snapshot, executions, through_snapshot
    )
    positions = {
        item.security_id: {
            "quantity": _required_decimal(
                item.total_quantity, "BASE_QUANTITY_INVALID"
            ),
            "available_state": item.available_quantity_state,
            "available": item.available_quantity_value,
            "cost_state": item.cost_state,
            "cost": item.cost_value,
            "market_value_state": item.market_value_state,
            "market_value": item.market_value_value,
        }
        for item in snapshot.positions
    }
    blocking = list(duplicate_failures)
    unverified: list[str] = []
    cash = (
        _optional_decimal(snapshot.cash_value)
        if snapshot.cash_state == "known"
        else None
    )
    cash_known = snapshot.cash_state == "known" and cash is not None
    any_execution = False
    for execution in active:
        any_execution = True
        quantity = _optional_decimal(execution.quantity)
        if (
            execution.account_id != snapshot.account_id
            or execution.intent_type not in {"increase", "decrease"}
            or quantity is None
            or quantity <= 0
        ):
            blocking.append(
                f"EXECUTION_INVALID:{execution.execution_record_id}"
            )
            continue
        position = positions.setdefault(
            execution.security_id,
            {
                "quantity": Decimal(0),
                "available_state": "unknown",
                "available": None,
                "cost_state": "unknown",
                "cost": None,
                "market_value_state": "unknown",
                "market_value": None,
            },
        )
        signed = quantity if execution.intent_type == "increase" else -quantity
        next_quantity = position["quantity"] + signed
        if next_quantity < 0:
            blocking.append(
                f"POSITION_QUANTITY_NEGATIVE:{execution.execution_record_id}"
            )
            continue
        position["quantity"] = next_quantity
        position["available_state"] = "unknown"
        position["available"] = None
        position["cost_state"] = "unknown"
        position["cost"] = None
        position["market_value_state"] = "unknown"
        position["market_value"] = None
        if execution.verification_status != "broker_matched":
            unverified.append(execution.execution_record_id)
        price = (
            _optional_decimal(execution.price_value)
            if execution.price_state == "known"
            else None
        )
        fee = (
            _optional_decimal(execution.fee_value)
            if execution.fee_state == "known"
            else None
        )
        if (
            not cash_known
            or price is None
            or fee is None
            or execution.currency != snapshot.currency
        ):
            cash_known = False
            cash = None
        else:
            gross = quantity * price
            cash = (
                cash - gross - fee
                if execution.intent_type == "increase"
                else cash + gross - fee
            )
            if cash < 0:
                blocking.append(
                    f"CASH_NEGATIVE:{execution.execution_record_id}"
                )
                cash_known = False
                cash = None
    if not execution_reader_available:
        unverified.append("EXECUTION_RECORD_READER_UNAVAILABLE")
    rendered_positions = tuple(
        EstimatedPosition(
            security_id=security_id,
            total_quantity=_render(values["quantity"]),
            available_quantity_state=str(values["available_state"]),
            available_quantity_value=(
                str(values["available"])
                if values["available_state"] == "known"
                else None
            ),
            cost_state=str(values["cost_state"]),
            cost_value=(
                str(values["cost"])
                if values["cost_state"] == "known"
                else None
            ),
            market_value_state=str(values["market_value_state"]),
            market_value_value=(
                str(values["market_value"])
                if values["market_value_state"] == "known"
                else None
            ),
        )
        for security_id, values in sorted(positions.items())
        if values["quantity"] != 0
    )
    status = (
        "blocked"
        if blocking
        else (
            "partial"
            if unverified
            or not cash_known
            or any(
                position.available_quantity_state != "known"
                for position in rendered_positions
            )
            else "ready"
        )
    )
    identity = {
        "schema_version": "EstimatedAccountState@1",
        "account_id": snapshot.account_id,
        "derived_from_snapshot_id": snapshot.account_snapshot_version_id,
        "derived_from_snapshot_as_of": snapshot.as_of_at,
        "derived_from_snapshot_as_of_precision": snapshot.as_of_precision,
        "derived_from_snapshot_session_semantics": (
            snapshot.session_semantics
        ),
        "snapshot_graph_seal_hash": snapshot.graph_seal_hash,
        "execution_record_ids": tuple(
            execution.execution_record_id for execution in active
        ),
        "positions": rendered_positions,
        "cash_state": "known" if cash_known else "unknown",
        "cash_value": _render(cash) if cash_known and cash is not None else None,
        "currency": snapshot.currency,
        "nav_state": "unknown" if any_execution else snapshot.nav_state,
        "nav_value": None if any_execution else snapshot.nav_value,
        "fees_state": "unknown" if any_execution else snapshot.fees_state,
        "fees_value": None if any_execution else snapshot.fees_value,
        "status": status,
        "blocking_reasons": tuple(sorted(set(blocking))),
        "unverified_evidence": tuple(sorted(set(unverified))),
    }
    content_hash = canonical_hash(identity)
    return EstimatedAccountState(
        estimated_account_state_id=f"estimated_account_state_{content_hash[:24]}",
        content_hash=content_hash,
        **identity,
    )


def reconcile_account_state(
    expected: EstimatedAccountState,
    confirmed: AccountSnapshotVersion,
) -> AccountStateDrift:
    """Compare a pre-confirmation estimate with a new immutable observation."""
    expected_positions = {
        item.security_id: item.total_quantity for item in expected.positions
    }
    confirmed_positions = {
        item.security_id: item.total_quantity for item in confirmed.positions
    }
    differences: list[tuple[str, str, str, str]] = []
    for security_id in sorted(expected_positions.keys() | confirmed_positions.keys()):
        left = expected_positions.get(security_id, "0")
        right = confirmed_positions.get(security_id, "0")
        difference = _render(
            _required_decimal(right, "CONFIRMED_QUANTITY_INVALID")
            - _required_decimal(left, "EXPECTED_QUANTITY_INVALID")
        )
        if difference != "0":
            differences.append((security_id, left, right, difference))
    if expected.cash_state == "known" and confirmed.cash_state == "known":
        cash_state = "known"
        cash_difference = _render(
            _required_decimal(confirmed.cash_value, "CONFIRMED_CASH_INVALID")
            - _required_decimal(expected.cash_value, "EXPECTED_CASH_INVALID")
        )
    else:
        cash_state = "unknown"
        cash_difference = None
    unexplained = tuple(
        [f"POSITION_DRIFT:{item[0]}" for item in differences]
        + (
            ["CASH_DRIFT"]
            if cash_state == "known" and cash_difference != "0"
            else []
        )
    )
    status = (
        "unable"
        if expected.status == "blocked"
        or (cash_state == "unknown" and not differences)
        else ("drift_detected" if unexplained else "reconciled")
    )
    identity = {
        "schema_version": "DriftAssessment@1",
        "expected_state_hash": expected.content_hash,
        "confirmed_snapshot_id": confirmed.account_snapshot_version_id,
        "position_differences": tuple(differences),
        "cash_difference_state": cash_state,
        "cash_difference_value": cash_difference,
        "explained_by_execution_ids": expected.execution_record_ids,
        "unexplained_drift": unexplained,
        "status": status,
    }
    content_hash = canonical_hash(identity)
    return AccountStateDrift(
        drift_assessment_id=f"account_state_drift_{content_hash[:24]}",
        content_hash=content_hash,
        **identity,
    )


def _active_executions(
    snapshot: AccountSnapshotVersion,
    executions: tuple[ExecutionProjectionRecord, ...],
    through_snapshot: AccountSnapshotVersion | None,
) -> tuple[tuple[ExecutionProjectionRecord, ...], tuple[str, ...]]:
    by_id: dict[str, ExecutionProjectionRecord] = {}
    failures: list[str] = []
    for execution in executions:
        existing = by_id.get(execution.execution_record_id)
        if existing is not None and existing.content_hash != execution.content_hash:
            failures.append(
                f"EXECUTION_ID_CONFLICT:{execution.execution_record_id}"
            )
        else:
            by_id[execution.execution_record_id] = execution
    in_window = {
        execution.execution_record_id: execution
        for execution in by_id.values()
        if _after_snapshot(snapshot, execution)
        and (
            through_snapshot is None
            or _at_or_before_snapshot(through_snapshot, execution)
        )
    }
    corrections: dict[str, list[str]] = {}
    invalid_corrections: set[str] = set()
    for execution in in_window.values():
        target = execution.corrects_execution_record_id
        if target is None:
            continue
        if target not in in_window:
            failures.append(
                f"CORRECTION_TARGET_OUTSIDE_WINDOW:{execution.execution_record_id}"
            )
            invalid_corrections.add(execution.execution_record_id)
        else:
            corrections.setdefault(target, []).append(
                execution.execution_record_id
            )
    for target, correction_ids in corrections.items():
        if len(correction_ids) > 1:
            failures.append(f"CORRECTION_TARGET_AMBIGUOUS:{target}")
            invalid_corrections.update(correction_ids)
    corrected = {
        target
        for target, correction_ids in corrections.items()
        if len(correction_ids) == 1
    }
    active = [
        execution
        for execution in in_window.values()
        if execution.execution_record_id not in corrected
        and execution.execution_record_id not in invalid_corrections
    ]
    active.sort(
        key=lambda item: (
            item.effective_at,
            item.effective_session,
            item.execution_record_id,
        )
    )
    return tuple(active), tuple(failures)


def _after_snapshot(
    snapshot: AccountSnapshotVersion, execution: ExecutionProjectionRecord
) -> bool:
    try:
        effective = datetime.fromisoformat(execution.effective_at)
    except ValueError:
        return True
    if snapshot.as_of_precision == "instant":
        try:
            cutoff = datetime.fromisoformat(snapshot.as_of_at)
        except ValueError:
            return True
        return effective > cutoff
    return execution.effective_session > snapshot.as_of_at


def _at_or_before_snapshot(
    snapshot: AccountSnapshotVersion, execution: ExecutionProjectionRecord
) -> bool:
    if snapshot.as_of_precision == "instant":
        try:
            return datetime.fromisoformat(execution.effective_at) <= datetime.fromisoformat(
                snapshot.as_of_at
            )
        except ValueError:
            return False
    return execution.effective_session <= snapshot.as_of_at


def _optional_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _required_decimal(value: str | None, code: str) -> Decimal:
    result = _optional_decimal(value)
    if result is None:
        raise ValueError(code)
    return result


def _render(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return "0" if rendered == "-0" else rendered


__all__ = [
    "AccountStateDrift",
    "AccountStateError",
    "EstimatedAccountState",
    "EstimatedPosition",
    "ExecutionProjectionRecord",
    "ExecutionRecordReader",
    "derive_estimated_account_state",
    "reconcile_account_state",
]
