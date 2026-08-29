from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from trading_platform.identifiers import identity
from trading_platform.result import FrozenFields, FrozenValue, freeze_value, thaw_value


@dataclass(frozen=True)
class AccountSnapshot:
    snapshot_id: str
    account_id: str
    as_of: str
    confirmed_by: str
    cash: FrozenFields | None
    positions: tuple[FrozenFields, ...]
    change_kind: str
    replaces_snapshot_id: str | None
    correction_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "account_id": self.account_id,
            "as_of": self.as_of,
            "confirmed_by": self.confirmed_by,
            "cash": self.cash.as_dict() if self.cash is not None else None,
            "positions": [position.as_dict() for position in self.positions],
            "change_kind": self.change_kind,
            "replaces_snapshot_id": self.replaces_snapshot_id,
            "correction_reason": self.correction_reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AccountSnapshot":
        if not value.get("confirmed_by"):
            raise ValueError("AccountSnapshot requires a named confirming user")
        positions_value = value.get("positions")
        if not isinstance(positions_value, list) or any(
            not isinstance(position, Mapping)
            or not position.get("security_id")
            or position.get("quantity") is None
            or _decimal(position["quantity"]) < 0
            for position in positions_value
        ):
            raise ValueError("AccountSnapshot positions are invalid")
        cash = value.get("cash")
        if cash is not None and not isinstance(cash, Mapping):
            raise ValueError("AccountSnapshot cash is invalid")
        if isinstance(cash, Mapping) and (
            cash.get("amount") is None or not cash.get("currency")
        ):
            raise ValueError("AccountSnapshot cash requires amount and currency")
        if isinstance(cash, Mapping):
            _decimal(cash["amount"])
        return cls(
            snapshot_id=str(value["snapshot_id"]), account_id=str(value["account_id"]), as_of=str(value["as_of"]),
            confirmed_by=str(value["confirmed_by"]),
            cash=FrozenFields.from_mapping(cash) if isinstance(cash, Mapping) else None,
            positions=tuple(FrozenFields.from_mapping(position) for position in positions_value),
            change_kind=str(value.get("change_kind", "new")),
            replaces_snapshot_id=str(value["replaces_snapshot_id"]) if value.get("replaces_snapshot_id") is not None else None,
            correction_reason=str(value["correction_reason"]) if value.get("correction_reason") is not None else None,
        )


@dataclass(frozen=True)
class ExecutionRecord:
    execution_id: str
    account_id: str
    base_snapshot_id: str
    security_id: str
    quantity_delta: str
    verification_status: str
    declared_by: str
    declared_at: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionRecord":
        if value.get("verification_status") != "user_declared" or not value.get("declared_by"):
            raise ValueError("ExecutionRecord requires an explicit user declaration")
        if not value.get("declared_at"):
            raise ValueError("ExecutionRecord declaration time is required")
        return cls(
            execution_id=str(value["execution_id"]),
            account_id=str(value["account_id"]),
            base_snapshot_id=str(value["base_snapshot_id"]),
            security_id=str(value["security_id"]),
            quantity_delta=_text(_decimal(value["quantity_delta"])),
            verification_status="user_declared",
            declared_by=str(value["declared_by"]),
            declared_at=str(value["declared_at"]),
        )


@dataclass(frozen=True)
class RiskPolicy:
    policy_id: str
    max_concentration: str
    max_position_value: str
    confirmed_by: str

    @classmethod
    def from_candidate(cls, value: Mapping[str, Any]) -> "RiskPolicy":
        if value.get("confirmed") is not True or not value.get("confirmed_by"):
            raise ValueError("RiskPolicy requires explicit user confirmation")
        concentration = _decimal(value["max_concentration"])
        position_value = _decimal(value["max_position_value"])
        if concentration < 0 or concentration > 1 or position_value < 0:
            raise ValueError("RiskPolicy limits are outside their valid range")
        return cls(
            policy_id=str(value["policy_id"]),
            max_concentration=_text(concentration),
            max_position_value=_text(position_value),
            confirmed_by=str(value["confirmed_by"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "max_concentration": self.max_concentration,
            "max_position_value": self.max_position_value,
            "confirmed": True,
            "confirmed_by": self.confirmed_by,
        }


@dataclass(frozen=True)
class PortfolioState:
    account_snapshot_id: str
    as_of: str
    currency: str | None
    cash: str | None
    positions: tuple[FrozenFields, ...]
    total_value: str | None
    execution_refs: tuple[str, ...]
    price_inputs: tuple[FrozenFields, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_snapshot_id": self.account_snapshot_id,
            "as_of": self.as_of,
            "currency": self.currency,
            "cash": self.cash,
            "positions": [position.as_dict() for position in self.positions],
            "total_value": self.total_value,
            "execution_refs": list(self.execution_refs),
            "price_inputs": [price.as_dict() for price in self.price_inputs],
        }

    @property
    def portfolio_state_ref(self) -> str:
        return identity("portfolio-state", self.as_dict())


@dataclass(frozen=True)
class RiskLimitResult:
    risk_limit_result_id: str
    status: str
    policy_id: str
    portfolio_state: PortfolioState
    input_refs: FrozenFields
    limits: FrozenFields

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_limit_result_id": self.risk_limit_result_id,
            "status": self.status,
            "policy_id": self.policy_id,
            "portfolio_state_ref": self.portfolio_state.portfolio_state_ref,
            "portfolio_state": self.portfolio_state.as_dict(),
            "input_refs": self.input_refs.as_dict(),
            "limits": self.limits.as_dict(),
        }


def confirm_account(
    candidate: Mapping[str, Any], prior: Mapping[str, Any] | None = None
) -> AccountSnapshot:
    required = ("account_id", "as_of", "confirmed", "confirmed_by", "positions")
    if (
        any(key not in candidate for key in required)
        or candidate.get("confirmed") is not True
        or not candidate.get("confirmed_by")
    ):
        raise ValueError("explicit account confirmation is required")
    positions = candidate["positions"]
    if not isinstance(positions, list) or any(
        not isinstance(position, Mapping)
        or not position.get("security_id")
        or position.get("quantity") is None
        for position in positions
    ):
        raise ValueError("every position needs an identity and quantity")
    for position in positions:
        if _decimal(position["quantity"]) < 0:
            raise ValueError("position quantity cannot be negative")
    change_kind = str(candidate.get("change_kind", "new"))
    if change_kind not in {"new", "revision", "correction"}:
        raise ValueError("change_kind must be new, revision, or correction")
    replaces = candidate.get("replaces_snapshot_id")
    if change_kind in {"revision", "correction"}:
        if prior is None:
            raise LookupError("the snapshot being changed does not exist")
        if prior["account_id"] != candidate["account_id"] or prior["as_of"] != candidate["as_of"]:
            raise StaleAccount("a revision or correction must preserve account and as_of")
        if change_kind == "correction" and not candidate.get("correction_reason"):
            raise ValueError("a correction reason is required")
    elif replaces is not None:
        raise ValueError("a new observation cannot replace a snapshot")
    account_id = str(candidate["account_id"])
    as_of = str(candidate["as_of"])
    confirmed_by = str(candidate["confirmed_by"])
    cash_value = candidate.get("cash")
    if cash_value is not None and not isinstance(cash_value, Mapping):
        raise ValueError("cash must be money or unknown")
    if isinstance(cash_value, Mapping) and (
        cash_value.get("amount") is None or not cash_value.get("currency")
    ):
        raise ValueError("known cash requires amount and currency")
    if isinstance(cash_value, Mapping):
        _decimal(cash_value["amount"])
    cash = FrozenFields.from_mapping(cash_value) if isinstance(cash_value, Mapping) else None
    position_records = tuple(FrozenFields.from_mapping(position) for position in positions)
    replaces_id = str(replaces) if replaces is not None else None
    correction_reason = (
        str(candidate["correction_reason"])
        if candidate.get("correction_reason") is not None
        else None
    )
    payload: dict[str, Any] = {
        "account_id": account_id,
        "as_of": as_of,
        "confirmed_by": confirmed_by,
        "cash": cash.as_dict() if cash is not None else None,
        "positions": [position.as_dict() for position in position_records],
        "change_kind": change_kind,
        "replaces_snapshot_id": replaces_id,
        "correction_reason": correction_reason,
    }
    return AccountSnapshot(
        snapshot_id=identity("snapshot", payload),
        account_id=account_id,
        as_of=as_of,
        confirmed_by=confirmed_by,
        cash=cash,
        positions=position_records,
        change_kind=change_kind,
        replaces_snapshot_id=replaces_id,
        correction_reason=correction_reason,
    )


class StaleAccount(ValueError):
    pass


def build_portfolio(
    snapshot: AccountSnapshot,
    prices: Mapping[str, Mapping[str, Any]],
    *,
    executions: Iterable[ExecutionRecord] = (),
) -> PortfolioState:
    """Derive account exposure without mutating or persisting account truth."""
    quantities = {
        str(position["security_id"]): _decimal(position["quantity"])
        for position in snapshot.positions
    }
    execution_refs: list[str] = []
    for execution in executions:
        if execution.account_id != snapshot.account_id or execution.base_snapshot_id != snapshot.snapshot_id:
            raise ValueError("ExecutionRecord does not belong to the confirmed account snapshot")
        security_id = execution.security_id
        quantities[security_id] = quantities.get(security_id, Decimal("0")) + _decimal(
            execution.quantity_delta
        )
        execution_refs.append(execution.execution_id)

    cash_record = snapshot.cash
    cash = _decimal(cash_record["amount"]) if cash_record is not None else None
    currency = str(cash_record["currency"]) if cash_record is not None else None
    positions: list[dict[str, Any]] = []
    price_inputs: list[dict[str, Any]] = []
    known_position_total = Decimal("0")
    all_prices_known = True
    for security_id, quantity in quantities.items():
        price = prices.get(security_id)
        if price is None:
            market_value = None
            all_prices_known = False
        else:
            if not price.get("source_id"):
                raise ValueError("every known price requires source_id")
            price_currency = str(price["currency"])
            if currency is None:
                currency = price_currency
            elif currency != price_currency:
                raise ValueError("portfolio currencies must match")
            market_value_number = quantity * _decimal(price["amount"])
            known_position_total += market_value_number
            market_value = _text(market_value_number)
            price_inputs.append(
                {
                    "security_id": security_id,
                    "amount": str(price["amount"]),
                    "currency": price_currency,
                    "source_id": str(price["source_id"]),
                }
            )
        positions.append({"security_id": security_id, "quantity": _text(quantity), "market_value": market_value})
    total = cash + known_position_total if cash is not None and all_prices_known else None
    return PortfolioState(
        account_snapshot_id=snapshot.snapshot_id,
        as_of=snapshot.as_of,
        currency=currency,
        cash=_text(cash) if cash is not None else None,
        positions=tuple(FrozenFields.from_mapping(position) for position in positions),
        total_value=_text(total) if total is not None else None,
        execution_refs=tuple(execution_refs),
        price_inputs=tuple(FrozenFields.from_mapping(price) for price in price_inputs),
    )


def evaluate_risk(state: PortfolioState, policy: RiskPolicy) -> RiskLimitResult:
    limits: dict[str, dict[str, Any]] = {}
    max_position = _decimal(policy.max_position_value)
    position_values = [
        _decimal(position["market_value"])
        for position in state.positions
        if position["market_value"] is not None
    ]
    largest = max(position_values, default=Decimal("0"))
    limits["max_position_value"] = {
        "status": "within_limit" if largest <= max_position else "breached",
        "observed": _text(largest),
        "limit": _text(max_position),
    }
    if state.total_value is None:
        limits["max_concentration"] = {"status": "insufficient", "missing": ["cash"]}
    else:
        concentration = largest / _decimal(state.total_value) if _decimal(state.total_value) else Decimal("0")
        maximum = _decimal(policy.max_concentration)
        limits["max_concentration"] = {
            "status": "within_limit" if concentration <= maximum else "breached",
            "observed": _text(concentration),
            "limit": _text(maximum),
        }
    statuses = {entry["status"] for entry in limits.values()}
    status = "insufficient" if "insufficient" in statuses else "breached" if "breached" in statuses else "within_limits"
    input_refs = FrozenFields.from_mapping({
        "account_snapshot_id": state.account_snapshot_id,
        "execution_record_ids": list(state.execution_refs),
        "price_source_ids": [item["source_id"] for item in state.price_inputs],
    })
    payload = {
        "status": status,
        "policy_id": policy.policy_id,
        "portfolio_state_ref": state.portfolio_state_ref,
        "portfolio_state": state.as_dict(),
        "input_refs": input_refs.as_dict(),
        "limits": limits,
    }
    return RiskLimitResult(
        risk_limit_result_id=identity("risk", payload),
        status=status,
        policy_id=policy.policy_id,
        portfolio_state=state,
        input_refs=input_refs,
        limits=FrozenFields.from_mapping(limits),
    )


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("invalid decimal") from error
    if not result.is_finite():
        raise ValueError("decimal must be finite")
    return result


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")
