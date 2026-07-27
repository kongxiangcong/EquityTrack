from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Mapping

from trading_platform.identity import canonical_hash


class PlanValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PositionSleeveKind(str, Enum):
    CORE = "core"
    GRID = "grid"
    LEGACY_UNSLEEVED = "legacy_unsleeved"

    @classmethod
    def parse(cls, value: str) -> "PositionSleeveKind":
        try:
            return cls(value)
        except ValueError as error:
            raise PlanValidationError("SLEEVE_KIND_INVALID") from error


@dataclass(frozen=True)
class CoreFloor:
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.quantity is None:
            raise PlanValidationError("CORE_FLOOR_REQUIRED")
        if not _whole_share(self.quantity, allow_zero=True):
            raise PlanValidationError("CORE_FLOOR_INVALID")


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

    def __post_init__(self) -> None:
        if (
            not self.grid_constraint_id
            or not _exact_decimal(self.lower_price, positive=True)
            or not _exact_decimal(self.upper_price, positive=True)
            or self.upper_price <= self.lower_price
        ):
            raise PlanValidationError("GRID_PRICE_BOUNDS_INVALID")
        if (
            isinstance(self.level_count, bool)
            or not 2 <= self.level_count <= 100
        ):
            raise PlanValidationError("GRID_LEVEL_COUNT_INVALID")
        if (
            not _whole_share(self.quantity_per_level, allow_zero=False)
            or self.quantity_per_level % Decimal("100") != 0
        ):
            raise PlanValidationError("GRID_LOT_SIZE_INVALID")
        if not _whole_share(
            self.total_quantity_budget, allow_zero=True
        ):
            raise PlanValidationError("GRID_QUANTITY_BUDGET_INVALID")
        if self.price_basis not in {"unadjusted", "adjusted"}:
            raise PlanValidationError("GRID_PRICE_BASIS_INVALID")
        if self.trigger_mode not in {
            "crosses_level",
            "closes_at_or_beyond_level",
        }:
            raise PlanValidationError("GRID_TRIGGER_MODE_INVALID")
        if (
            isinstance(self.cooldown_trading_sessions, bool)
            or self.cooldown_trading_sessions < 0
        ):
            raise PlanValidationError("GRID_COOLDOWN_INVALID")

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
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.canonical_content)


@dataclass(frozen=True, kw_only=True)
class PositionSleeve:
    sleeve_id: str
    quantity_budget: Decimal | None
    core_floor: CoreFloor
    max_notional: Decimal | None = None
    max_loss: Decimal | None = None

    @property
    def kind(self) -> PositionSleeveKind:
        raise NotImplementedError

    def __post_init__(self) -> None:
        if not self.sleeve_id:
            raise PlanValidationError("SLEEVE_ID_REQUIRED")
        if self.quantity_budget is not None and not _whole_share(
            self.quantity_budget, allow_zero=True
        ):
            raise PlanValidationError("SLEEVE_QUANTITY_BUDGET_INVALID")
        for value in (self.max_notional, self.max_loss):
            if value is not None and not _exact_decimal(
                value, positive=False
            ):
                raise PlanValidationError("SLEEVE_FINANCIAL_LIMIT_INVALID")

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "sleeve_id": self.sleeve_id,
            "sleeve_kind": self.kind.value,
            "quantity_budget_state": (
                "known" if self.quantity_budget is not None else "unknown"
            ),
            "quantity_budget_value": (
                str(self.quantity_budget)
                if self.quantity_budget is not None
                else None
            ),
            "core_floor_state": "known",
            "core_floor_value": str(self.core_floor.quantity),
            "max_notional_state": (
                "known" if self.max_notional is not None else "unknown"
            ),
            "max_notional_value": (
                str(self.max_notional)
                if self.max_notional is not None
                else None
            ),
            "max_loss_state": (
                "known" if self.max_loss is not None else "unknown"
            ),
            "max_loss_value": (
                str(self.max_loss) if self.max_loss is not None else None
            ),
            "grid_constraint_id": None,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.canonical_content)


@dataclass(frozen=True, kw_only=True)
class CoreSleeve(PositionSleeve):
    @property
    def kind(self) -> PositionSleeveKind:
        return PositionSleeveKind.CORE


@dataclass(frozen=True, kw_only=True)
class GridSleeve(PositionSleeve):
    constraint: GridConstraint

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.quantity_budget != self.constraint.total_quantity_budget:
            raise PlanValidationError("GRID_QUANTITY_BUDGET_MISMATCH")

    @property
    def kind(self) -> PositionSleeveKind:
        return PositionSleeveKind.GRID

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            **super().canonical_content,
            "grid_constraint_id": self.constraint.grid_constraint_id,
        }


def validate_sleeve_contract(
    strategy_version_id: str,
    sleeves: tuple[PositionSleeve, ...],
) -> None:
    core_count = sum(
        sleeve.kind is PositionSleeveKind.CORE for sleeve in sleeves
    )
    grid_count = sum(
        sleeve.kind is PositionSleeveKind.GRID for sleeve in sleeves
    )
    if core_count == 0:
        raise PlanValidationError("SLEEVE_CORE_REQUIRED")
    if core_count > 1:
        raise PlanValidationError("SLEEVE_CORE_DUPLICATE")
    if grid_count > 1:
        raise PlanValidationError("SLEEVE_GRID_DUPLICATE")
    if len({sleeve.sleeve_id for sleeve in sleeves}) != len(sleeves):
        raise PlanValidationError("SLEEVE_ID_DUPLICATE")
    if any(
        sleeve.kind is PositionSleeveKind.LEGACY_UNSLEEVED
        for sleeve in sleeves
    ):
        raise PlanValidationError("LEGACY_SLEEVE_READ_ONLY")
    expected = {
        "strategy_version_trend_hold_break_exit_1": {PositionSleeveKind.CORE},
        "strategy_version_core_plus_grid_1": {
            PositionSleeveKind.CORE,
            PositionSleeveKind.GRID,
        },
    }.get(strategy_version_id)
    if expected is None:
        raise PlanValidationError("SLEEVE_STRATEGY_UNKNOWN")
    actual = {sleeve.kind for sleeve in sleeves}
    if not actual <= expected:
        raise PlanValidationError("SLEEVE_STRATEGY_MISMATCH")


def validate_sleeve_quantities(
    sleeves: tuple[PositionSleeve, ...],
    *,
    total_quantity: Decimal | None,
    remaining_quantity: Decimal | None = None,
    candidate_grid_decrease: Decimal | None = None,
) -> None:
    floors = {sleeve.core_floor.quantity for sleeve in sleeves}
    if len(floors) != 1:
        raise PlanValidationError("CORE_FLOOR_MISMATCH")
    floor = next(iter(floors))
    known_budgets = tuple(
        sleeve.quantity_budget
        for sleeve in sleeves
        if sleeve.quantity_budget is not None
    )
    if total_quantity is not None:
        if not _whole_share(total_quantity, allow_zero=True):
            raise PlanValidationError("TOTAL_QUANTITY_INVALID")
        if len(known_budgets) == len(sleeves) and sum(
            known_budgets, Decimal("0")
        ) > total_quantity:
            raise PlanValidationError("SLEEVE_ALLOCATION_EXCEEDS_POSITION")
        if floor > total_quantity:
            raise PlanValidationError("CORE_FLOOR_EXCEEDS_POSITION")
    if candidate_grid_decrease is None:
        return
    if remaining_quantity is None:
        raise PlanValidationError("GRID_REMAINING_QUANTITY_REQUIRED")
    if (
        not _whole_share(remaining_quantity, allow_zero=True)
        or not _whole_share(candidate_grid_decrease, allow_zero=False)
    ):
        raise PlanValidationError("GRID_DECREASE_QUANTITY_INVALID")
    if remaining_quantity - candidate_grid_decrease < floor:
        raise PlanValidationError("GRID_DECREASE_CROSSES_CORE_FLOOR")


@dataclass(frozen=True)
class TradePlanMasterId:
    account_id: str
    security_id: str
    value: str

    @classmethod
    def derive(
        cls,
        account_id: str,
        security_id: str,
        identity_seed: str = "initial",
    ) -> "TradePlanMasterId":
        if not account_id or not security_id or not identity_seed:
            raise PlanValidationError("PLAN_OWNERSHIP_REQUIRED")
        digest = canonical_hash(
            {
                "schema_version": "TradePlanMasterId@1",
                "account_id": account_id,
                "security_id": security_id,
                "identity_seed": identity_seed,
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
        if (
            self.schema_version != "TradePlanMaster@1"
            or not self.plan_id.account_id
            or not self.plan_id.security_id
            or not self.plan_id.value
            or not self.strategy_version_id
            or self.lifecycle_status not in {"inactive", "active", "ended"}
            or self.transition_seq < 0
            or not self.created_at
        ):
            raise PlanValidationError("PLAN_MASTER_INVALID")


@dataclass(frozen=True)
class TradePlanDraft:
    draft_id: str
    plan_id: str | None
    account_id: str
    security_id: str
    strategy_version_id: str
    based_on_version_id: str | None
    revision: int
    status: str
    parameters: Mapping[str, object]
    content: Mapping[str, object]
    content_hash: str
    created_at: str
    updated_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "TradePlanDraft@1"

    def validate(self) -> None:
        if (
            self.schema_version != "TradePlanDraft@1"
            or not self.draft_id
            or not self.account_id
            or not self.security_id
            or not self.strategy_version_id
            or self.revision < 1
            or self.status not in {"open", "rejected", "confirmed"}
            or not self.decision_actor
            or not self.interaction_channel
            or not self.transport_actor
            or self.content_hash
            != canonical_hash(
                {
                    "account_id": self.account_id,
                    "security_id": self.security_id,
                    "strategy_version_id": self.strategy_version_id,
                    "based_on_version_id": self.based_on_version_id,
                    "parameters": self.parameters,
                    "content": self.content,
                }
            )
        ):
            raise PlanValidationError("PLAN_DRAFT_INVALID")


@dataclass(frozen=True)
class PlanGraphSeal:
    graph_seal_hash: str
    version_content_hash: str
    sleeve_hashes: tuple[str, ...]
    rule_hashes: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    schema_version: str = "PlanGraphSeal@1"

    @classmethod
    def build(
        cls,
        *,
        version_content_hash: str,
        sleeve_hashes: tuple[str, ...],
        rule_hashes: tuple[str, ...],
        evidence_hashes: tuple[str, ...],
    ) -> "PlanGraphSeal":
        canonical_sleeves = tuple(sorted(sleeve_hashes))
        canonical_rules = tuple(rule_hashes)
        canonical_evidence = tuple(evidence_hashes)
        identity = {
            "schema_version": "PlanGraphSeal@1",
            "version_content_hash": version_content_hash,
            "sleeve_hashes": canonical_sleeves,
            "rule_hashes": canonical_rules,
            "evidence_hashes": canonical_evidence,
        }
        return cls(
            graph_seal_hash=canonical_hash(identity),
            version_content_hash=version_content_hash,
            sleeve_hashes=canonical_sleeves,
            rule_hashes=canonical_rules,
            evidence_hashes=canonical_evidence,
        )


@dataclass(frozen=True)
class TradePlanVersion:
    plan_version_id: str
    plan_id: str
    version_no: int
    supersedes_version_id: str | None
    strategy_version_id: str
    investment_thesis_version_id: str | None
    account_snapshot_version_id: str
    data_snapshot_id: str
    horizon_start: str
    horizon_end: str
    review_by: str
    risk_policy_version_id: str | None
    metric_catalog_version: str
    evaluator_policy_version: str
    conflict_policy_version: str
    ast_version: str
    content: Mapping[str, object]
    content_hash: str
    graph_seal_hash: str
    confirmed_at: str
    user_approval_receipt_id: str
    legacy_read_only: bool = False
    schema_version: str = "TradePlanVersion@1"

    def validate(self) -> None:
        try:
            start = date.fromisoformat(self.horizon_start)
            review = date.fromisoformat(self.review_by)
            end = date.fromisoformat(self.horizon_end)
        except ValueError as error:
            raise PlanValidationError("PLAN_HORIZON_INVALID") from error
        if (
            self.schema_version != "TradePlanVersion@1"
            or not self.plan_version_id
            or not self.plan_id
            or self.version_no < 1
            or not self.strategy_version_id
            or not self.account_snapshot_version_id
            or not self.data_snapshot_id
            or not start <= review <= end
            or self.conflict_policy_version != "trade-plan-conflict@1"
            or self.ast_version != "plan-rule-ast@2"
            or self.content_hash != canonical_hash(self.content)
            or not self.graph_seal_hash
            or not self.confirmed_at
            or not self.user_approval_receipt_id
            or self.legacy_read_only
        ):
            raise PlanValidationError("PLAN_VERSION_INVALID")


@dataclass(frozen=True)
class TradePlanGraph:
    version: TradePlanVersion
    sleeves: tuple[PositionSleeve, ...]
    rules: tuple[Mapping[str, object], ...]
    evidence_references: tuple[Mapping[str, object], ...]
    adjusted_price_evidence: tuple[Mapping[str, object], ...] = ()
    schema_version: str = "TradePlanGraph@1"

    def validate(self) -> None:
        self.version.validate()
        if self.schema_version != "TradePlanGraph@1":
            raise PlanValidationError("PLAN_GRAPH_INVALID")
        validate_sleeve_contract(
            self.version.strategy_version_id, self.sleeves
        )
        validate_sleeve_quantities(self.sleeves, total_quantity=None)
        sleeve_hashes = _sleeve_hashes(self.sleeves)
        rule_hashes = _child_hashes(
            self.rules, "rule_id", sequence_sensitive=True
        )
        evidence_hashes = _child_hashes(
            self.evidence_references,
            "ref_id",
            sequence_sensitive=True,
        ) + _child_hashes(
            self.adjusted_price_evidence,
            "content_hash",
            sequence_sensitive=True,
        )
        expected = PlanGraphSeal.build(
            version_content_hash=self.version.content_hash,
            sleeve_hashes=sleeve_hashes,
            rule_hashes=rule_hashes,
            evidence_hashes=evidence_hashes,
        )
        if self.version.graph_seal_hash != expected.graph_seal_hash:
            raise PlanValidationError("PLAN_GRAPH_SEAL_MISMATCH")


@dataclass(frozen=True)
class PlanActivation:
    activation_id: str
    plan_id: str
    plan_version_id: str
    activated_event_id: str
    activated_at: str
    user_approval_receipt_id: str
    command_invocation_id: str
    ended_event_id: str | None = None
    ended_at: str | None = None
    end_reason: str | None = None
    schema_version: str = "PlanActivation@1"


@dataclass(frozen=True)
class ActiveTradePlan:
    master: TradePlanMaster
    activation: PlanActivation | None
    version: TradePlanVersion | None


def build_plan_version(
    *,
    plan_version_id: str,
    plan_id: str,
    version_no: int,
    supersedes_version_id: str | None,
    strategy_version_id: str,
    investment_thesis_version_id: str | None,
    account_snapshot_version_id: str,
    data_snapshot_id: str,
    horizon_start: str,
    horizon_end: str,
    review_by: str,
    risk_policy_version_id: str | None,
    metric_catalog_version: str,
    evaluator_policy_version: str,
    content: Mapping[str, object],
    sleeves: tuple[PositionSleeve, ...],
    rules: tuple[Mapping[str, object], ...],
    evidence_references: tuple[Mapping[str, object], ...],
    adjusted_price_evidence: tuple[Mapping[str, object], ...],
    confirmed_at: str,
    user_approval_receipt_id: str,
) -> TradePlanGraph:
    content_hash = canonical_hash(content)
    seal = PlanGraphSeal.build(
        version_content_hash=content_hash,
        sleeve_hashes=_sleeve_hashes(sleeves),
        rule_hashes=_child_hashes(
            rules, "rule_id", sequence_sensitive=True
        ),
        evidence_hashes=_child_hashes(
            evidence_references, "ref_id", sequence_sensitive=True
        )
        + _child_hashes(
            adjusted_price_evidence,
            "content_hash",
            sequence_sensitive=True,
        ),
    )
    version = TradePlanVersion(
        plan_version_id=plan_version_id,
        plan_id=plan_id,
        version_no=version_no,
        supersedes_version_id=supersedes_version_id,
        strategy_version_id=strategy_version_id,
        investment_thesis_version_id=investment_thesis_version_id,
        account_snapshot_version_id=account_snapshot_version_id,
        data_snapshot_id=data_snapshot_id,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        review_by=review_by,
        risk_policy_version_id=risk_policy_version_id,
        metric_catalog_version=metric_catalog_version,
        evaluator_policy_version=evaluator_policy_version,
        conflict_policy_version="trade-plan-conflict@1",
        ast_version="plan-rule-ast@2",
        content=content,
        content_hash=content_hash,
        graph_seal_hash=seal.graph_seal_hash,
        confirmed_at=confirmed_at,
        user_approval_receipt_id=user_approval_receipt_id,
    )
    graph = TradePlanGraph(
        version=version,
        sleeves=sleeves,
        rules=rules,
        evidence_references=evidence_references,
        adjusted_price_evidence=adjusted_price_evidence,
    )
    graph.validate()
    return graph


def _child_hashes(
    children: tuple[Mapping[str, object], ...],
    identity_key: str,
    *,
    sequence_sensitive: bool = False,
) -> tuple[str, ...]:
    identities: set[str] = set()
    hashes: list[str] = []
    for child in children:
        identity = child.get(identity_key)
        content_hash = child.get("content_hash")
        if (
            not isinstance(identity, str)
            or not identity
            or identity in identities
            or not isinstance(content_hash, str)
            or content_hash != canonical_hash(
                {
                    key: value
                    for key, value in child.items()
                    if key != "content_hash"
                }
            )
        ):
            raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")
        identities.add(identity)
        hashes.append(content_hash)
    return tuple(hashes if sequence_sensitive else sorted(hashes))


def _sleeve_hashes(
    sleeves: tuple[PositionSleeve, ...],
) -> tuple[str, ...]:
    identities = [sleeve.sleeve_id for sleeve in sleeves]
    if (
        any(not identity for identity in identities)
        or len(set(identities)) != len(identities)
    ):
        raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")
    return tuple(sorted(sleeve.content_hash for sleeve in sleeves))


def _exact_decimal(value: object, *, positive: bool) -> bool:
    if not isinstance(value, Decimal) or not value.is_finite():
        return False
    return value > 0 if positive else value >= 0


def _whole_share(value: object, *, allow_zero: bool) -> bool:
    if not _exact_decimal(value, positive=not allow_zero):
        return False
    assert isinstance(value, Decimal)
    return value == value.to_integral_value()


__all__ = [
    "ActiveTradePlan",
    "CoreFloor",
    "CoreSleeve",
    "GridConstraint",
    "GridSleeve",
    "PlanActivation",
    "PlanGraphSeal",
    "PlanValidationError",
    "PositionSleeve",
    "PositionSleeveKind",
    "TradePlanDraft",
    "TradePlanGraph",
    "TradePlanMaster",
    "TradePlanMasterId",
    "TradePlanVersion",
    "build_plan_version",
    "validate_sleeve_contract",
    "validate_sleeve_quantities",
]
