from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Mapping

from trading_platform.identity import canonical_hash


BUILTIN_STRATEGY_KEYS = (
    "trend_hold_break_exit",
    "core_plus_grid",
)
_BUILTIN_CREATED_AT = "2026-07-27T00:00:00+08:00"


class StrategyContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class InvestmentThesisVersion:
    thesis_id: str
    thesis_version_id: str
    version_no: int
    security_id: str
    as_of_at: str
    timezone: str
    status: str
    horizon: Mapping[str, object]
    claims: tuple[Mapping[str, object], ...]
    drivers: tuple[Mapping[str, object], ...]
    risks: tuple[Mapping[str, object], ...]
    invalidation_tests: tuple[Mapping[str, object], ...]
    evidence_manifest_id: str
    research_run_ids: tuple[str, ...]
    authoring_actor: str
    model_identity: str
    policy_identity: str
    content_hash: str
    created_at: str
    schema_version: str = "InvestmentThesisVersion@1"

    def validate(self) -> None:
        if (
            self.schema_version != "InvestmentThesisVersion@1"
            or not self.thesis_id
            or not self.thesis_version_id
            or self.version_no < 1
            or not self.security_id
            or not self.as_of_at
            or self.timezone != "Asia/Shanghai"
            or self.status not in {"draft", "published", "superseded"}
            or not self.evidence_manifest_id
            or not self.authoring_actor
            or not self.model_identity
            or not self.policy_identity
        ):
            raise StrategyContractError("INVESTMENT_THESIS_INVALID")
        expected = canonical_hash(self.identity_payload())
        if self.content_hash != expected:
            raise StrategyContractError("INVESTMENT_THESIS_HASH_MISMATCH")

    def identity_payload(self) -> Mapping[str, object]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key not in {"content_hash", "created_at"}
        }


@dataclass(frozen=True)
class StrategyParameterContract:
    parameter_key: str
    value_type: str
    required: bool = True
    enum_values: tuple[str, ...] = ()
    minimum: str | None = None
    maximum: str | None = None
    item_type: str | None = None
    unknown_policy: str = "forbidden"

    def validate(self, value: object) -> None:
        if value is None:
            if self.unknown_policy == "manual_review_required":
                return
            raise StrategyContractError(
                f"STRATEGY_PARAMETER_UNKNOWN:{self.parameter_key}"
            )
        if self.value_type == "enum":
            valid = isinstance(value, str) and value in self.enum_values
        elif self.value_type == "string":
            valid = isinstance(value, str) and bool(value.strip())
        elif self.value_type == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif self.value_type in {"decimal", "quantity"}:
            valid = _decimal(value) is not None
        elif self.value_type == "date":
            valid = _date(value)
        elif self.value_type == "string_list":
            valid = (
                isinstance(value, (tuple, list))
                and all(isinstance(item, str) and item for item in value)
            )
        elif self.value_type == "ast_condition":
            valid = (
                isinstance(value, Mapping)
                and value.get("ast_version") == "plan-rule-ast@2"
            )
        elif self.value_type == "typed_quantity":
            valid = _typed_quantity(value)
        elif self.value_type == "review_rule_ids":
            valid = _review_rule_ids(value)
        else:
            raise StrategyContractError(
                f"STRATEGY_PARAMETER_CONTRACT_INVALID:{self.parameter_key}"
            )
        if not valid:
            raise StrategyContractError(
                f"STRATEGY_PARAMETER_INVALID:{self.parameter_key}"
            )
        number = (
            Decimal(value)
            if self.value_type in {"integer", "decimal", "quantity"}
            else None
        )
        if (
            number is not None
            and self.minimum is not None
            and number < Decimal(self.minimum)
        ):
            raise StrategyContractError(
                f"STRATEGY_PARAMETER_BELOW_MINIMUM:{self.parameter_key}"
            )
        if (
            number is not None
            and self.maximum is not None
            and number > Decimal(self.maximum)
        ):
            raise StrategyContractError(
                f"STRATEGY_PARAMETER_ABOVE_MAXIMUM:{self.parameter_key}"
            )


@dataclass(frozen=True)
class TrendHoldBreakExitParameters:
    price_basis: str
    trend_metric_ref: str
    break_condition: Mapping[str, object]
    break_confirmation_sessions: int
    core_floor_quantity: Decimal
    invalidation_review_rule_ids: object
    candidate_decrease_quantity: Mapping[str, object]
    review_by: str

    @classmethod
    def from_mapping(
        cls, parameters: Mapping[str, object]
    ) -> "TrendHoldBreakExitParameters":
        floor = _required_decimal(
            parameters.get("core_floor_quantity"),
            "CORE_FLOOR_INVALID",
        )
        condition = parameters.get("break_condition")
        if (
            not isinstance(condition, Mapping)
            or condition.get("ast_version") != "plan-rule-ast@2"
            or condition.get("session_scope") != "complete_session"
        ):
            raise StrategyContractError(
                "TREND_BREAK_SESSION_SCOPE_INVALID"
            )
        return cls(
            price_basis=str(parameters.get("price_basis", "")),
            trend_metric_ref=str(
                parameters.get("trend_metric_ref", "")
            ),
            break_condition=condition,
            break_confirmation_sessions=int(
                parameters.get("break_confirmation_sessions", 0)
            ),
            core_floor_quantity=floor,
            invalidation_review_rule_ids=parameters.get(
                "invalidation_review_rule_ids"
            ),
            candidate_decrease_quantity=parameters.get(
                "candidate_decrease_quantity", {}
            ),
            review_by=str(parameters.get("review_by", "")),
        )


@dataclass(frozen=True)
class CorePlusGridParameters:
    core_floor_quantity: Decimal
    grid_lower_price: Decimal
    grid_upper_price: Decimal
    grid_level_count: int
    grid_quantity_per_level: Decimal
    grid_total_quantity_budget: Decimal
    grid_price_basis: str
    grid_trigger_mode: str
    cooldown_trading_sessions: int
    cash_operand_policy: str
    quantity_operand_policy: str

    @classmethod
    def from_mapping(
        cls, parameters: Mapping[str, object]
    ) -> "CorePlusGridParameters":
        floor = _required_decimal(
            parameters.get("core_floor_quantity"),
            "CORE_FLOOR_INVALID",
        )
        lower = _required_decimal(
            parameters.get("grid_lower_price"),
            "GRID_PRICE_BOUNDS_INVALID",
        )
        upper = _required_decimal(
            parameters.get("grid_upper_price"),
            "GRID_PRICE_BOUNDS_INVALID",
        )
        if lower <= 0 or upper <= lower:
            raise StrategyContractError("GRID_PRICE_BOUNDS_INVALID")
        per_level = _required_decimal(
            parameters.get("grid_quantity_per_level"),
            "GRID_LOT_SIZE_INVALID",
        )
        total_budget = _required_decimal(
            parameters.get("grid_total_quantity_budget"),
            "GRID_QUANTITY_BUDGET_INVALID",
        )
        if (
            per_level <= 0
            or per_level != per_level.to_integral_value()
            or per_level % Decimal("100") != 0
        ):
            raise StrategyContractError("GRID_LOT_SIZE_INVALID")
        if (
            floor != floor.to_integral_value()
            or total_budget != total_budget.to_integral_value()
        ):
            raise StrategyContractError("GRID_QUANTITY_BUDGET_INVALID")
        return cls(
            core_floor_quantity=floor,
            grid_lower_price=lower,
            grid_upper_price=upper,
            grid_level_count=int(
                parameters.get("grid_level_count", 0)
            ),
            grid_quantity_per_level=per_level,
            grid_total_quantity_budget=total_budget,
            grid_price_basis=str(
                parameters.get("grid_price_basis", "")
            ),
            grid_trigger_mode=str(
                parameters.get("grid_trigger_mode", "")
            ),
            cooldown_trading_sessions=int(
                parameters.get("cooldown_trading_sessions", -1)
            ),
            cash_operand_policy=str(
                parameters.get("cash_operand_policy", "")
            ),
            quantity_operand_policy=str(
                parameters.get("quantity_operand_policy", "")
            ),
        )


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    strategy_key: str
    display_name: str
    purpose: str
    market_scope: str = "CN_A_SHARE"
    authoring_mode: str = "built_in"


@dataclass(frozen=True)
class StrategyVersion:
    strategy_definition: StrategyDefinition
    strategy_version_id: str
    version_no: int
    status: str
    sleeve_contract: tuple[str, ...]
    parameter_contracts: tuple[StrategyParameterContract, ...]
    rule_templates: tuple[str, ...]
    content_hash: str
    created_at: str
    conflict_policy_version: str = "trade-plan-conflict@1"
    ast_version: str = "plan-rule-ast@2"
    schema_version: str = "StrategyVersion@1"
    publicly_selectable: bool = True

    @property
    def strategy_key(self) -> str:
        return self.strategy_definition.strategy_key

    @property
    def public_identity(self) -> str:
        return f"{self.strategy_key}@{self.version_no}"

    def identity_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_definition.strategy_id,
            "strategy_version_id": self.strategy_version_id,
            "strategy_key": self.strategy_key,
            "version_no": self.version_no,
            "market_scope": self.strategy_definition.market_scope,
            "authoring_mode": self.strategy_definition.authoring_mode,
            "status": self.status,
            "sleeve_contract": self.sleeve_contract,
            "parameter_contracts": self.parameter_contracts,
            "rule_templates": self.rule_templates,
            "conflict_policy_version": self.conflict_policy_version,
            "ast_version": self.ast_version,
            "publicly_selectable": self.publicly_selectable,
        }

    def validate_integrity(self) -> None:
        if (
            self.schema_version != "StrategyVersion@1"
            or self.strategy_definition.market_scope != "CN_A_SHARE"
            or self.strategy_definition.authoring_mode != "built_in"
            or self.version_no < 1
            or self.status not in {"active", "retired"}
            or self.ast_version != "plan-rule-ast@2"
            or self.conflict_policy_version != "trade-plan-conflict@1"
            or not self.strategy_version_id
            or len({item.parameter_key for item in self.parameter_contracts})
            != len(self.parameter_contracts)
            or self.content_hash != canonical_hash(self.identity_payload())
        ):
            raise StrategyContractError("STRATEGY_VERSION_CORRUPT")

    def validate_parameters(self, parameters: Mapping[str, object]) -> None:
        self.validate_integrity()
        contracts = {
            item.parameter_key: item for item in self.parameter_contracts
        }
        unknown = sorted(set(parameters) - set(contracts))
        if unknown:
            raise StrategyContractError(
                f"STRATEGY_PARAMETER_UNKNOWN:{unknown[0]}"
            )
        missing = sorted(
            key
            for key, contract in contracts.items()
            if contract.required and key not in parameters
        )
        if missing:
            raise StrategyContractError(
                f"STRATEGY_PARAMETER_REQUIRED:{missing[0]}"
            )
        for key, value in parameters.items():
            contracts[key].validate(value)
        if self.strategy_key == "trend_hold_break_exit":
            TrendHoldBreakExitParameters.from_mapping(parameters)
        elif self.strategy_key == "core_plus_grid":
            CorePlusGridParameters.from_mapping(parameters)


class StrategyCatalog:
    """Owns the closed public registry and finite parameter validation."""

    def __init__(self, versions: tuple[StrategyVersion, ...]) -> None:
        for version in versions:
            version.validate_integrity()
        public = tuple(
            version
            for version in versions
            if version.publicly_selectable and version.status == "active"
        )
        identities = tuple(sorted(item.public_identity for item in public))
        if identities != ("core_plus_grid@1", "trend_hold_break_exit@1"):
            raise StrategyContractError("STRATEGY_PUBLIC_CATALOG_INVALID")
        self._public = tuple(
            sorted(public, key=lambda item: item.public_identity)
        )
        self._by_id = {
            version.strategy_version_id: version for version in versions
        }

    def list_public(self) -> tuple[StrategyVersion, ...]:
        return self._public

    def get(self, strategy_version_id: str) -> StrategyVersion:
        version = self._by_id.get(strategy_version_id)
        if version is None or not version.publicly_selectable:
            raise StrategyContractError("STRATEGY_VERSION_NOT_FOUND")
        return version


def builtin_strategy_versions() -> tuple[StrategyVersion, ...]:
    trend = _version(
        StrategyDefinition(
            strategy_id="strategy_definition_trend_hold_break_exit",
            strategy_key="trend_hold_break_exit",
            display_name="趋势持仓与破位复核",
            purpose="以 core sleeve 表达趋势破坏、失效复核与候选调整。",
        ),
        sleeve_contract=("core",),
        contracts=(
            _contract(
                "price_basis",
                "enum",
                enum_values=("unadjusted", "adjusted"),
            ),
            _contract("trend_metric_ref", "string"),
            _contract("break_condition", "ast_condition"),
            _contract("break_confirmation_sessions", "integer", minimum="1"),
            _contract("core_floor_quantity", "quantity", minimum="0"),
            _contract("invalidation_review_rule_ids", "review_rule_ids"),
            _contract(
                "candidate_decrease_quantity",
                "typed_quantity",
                unknown_policy="manual_review_required",
            ),
            _contract("review_by", "date"),
        ),
        rule_templates=(
            "trend_break_candidate",
            "thesis_invalidation_review",
            "core_floor_precedence",
        ),
    )
    grid = _version(
        StrategyDefinition(
            strategy_id="strategy_definition_core_plus_grid",
            strategy_key="core_plus_grid",
            display_name="核心仓位与有限网格",
            purpose="在一个 Master Plan 内约束 core 与可选 grid sleeves。",
        ),
        sleeve_contract=("core", "grid_optional"),
        contracts=(
            _contract("core_floor_quantity", "quantity", minimum="0"),
            _contract("grid_lower_price", "decimal", minimum="0"),
            _contract("grid_upper_price", "decimal", minimum="0"),
            _contract(
                "grid_level_count", "integer", minimum="2", maximum="100"
            ),
            _contract("grid_quantity_per_level", "quantity", minimum="0"),
            _contract("grid_total_quantity_budget", "quantity", minimum="0"),
            _contract(
                "grid_price_basis",
                "enum",
                enum_values=("unadjusted", "adjusted"),
            ),
            _contract(
                "grid_trigger_mode",
                "enum",
                enum_values=(
                    "crosses_level",
                    "closes_at_or_beyond_level",
                ),
            ),
            _contract(
                "cooldown_trading_sessions", "integer", minimum="0"
            ),
            _contract(
                "cash_operand_policy",
                "enum",
                enum_values=(
                    "known_required",
                    "unknown_manual_review_required",
                ),
            ),
            _contract(
                "quantity_operand_policy",
                "enum",
                enum_values=(
                    "known_required",
                    "unknown_manual_review_required",
                ),
            ),
        ),
        rule_templates=(
            "grid_level_candidate",
            "cash_quantity_guard",
            "core_floor_precedence",
        ),
    )
    return (trend, grid)


def _version(
    definition: StrategyDefinition,
    *,
    sleeve_contract: tuple[str, ...],
    contracts: tuple[StrategyParameterContract, ...],
    rule_templates: tuple[str, ...],
) -> StrategyVersion:
    version_id = f"strategy_version_{definition.strategy_key}_1"
    prototype = StrategyVersion(
        strategy_definition=definition,
        strategy_version_id=version_id,
        version_no=1,
        status="active",
        sleeve_contract=sleeve_contract,
        parameter_contracts=contracts,
        rule_templates=rule_templates,
        content_hash="",
        created_at=_BUILTIN_CREATED_AT,
    )
    return StrategyVersion(
        **{
            **asdict(prototype),
            "strategy_definition": definition,
            "parameter_contracts": contracts,
            "content_hash": canonical_hash(prototype.identity_payload()),
        }
    )


def _contract(
    parameter_key: str,
    value_type: str,
    *,
    enum_values: tuple[str, ...] = (),
    minimum: str | None = None,
    maximum: str | None = None,
    unknown_policy: str = "forbidden",
) -> StrategyParameterContract:
    return StrategyParameterContract(
        parameter_key=parameter_key,
        value_type=value_type,
        enum_values=enum_values,
        minimum=minimum,
        maximum=maximum,
        unknown_policy=unknown_policy,
    )


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _required_decimal(value: object, code: str) -> Decimal:
    result = _decimal(value)
    if result is None:
        raise StrategyContractError(code)
    return result


def _date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _typed_quantity(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    state = value.get("state")
    amount = value.get("value")
    return (
        state == "known"
        and _decimal(amount) is not None
        or state == "unknown"
        and amount is None
    )


def _review_rule_ids(value: object) -> bool:
    if isinstance(value, (tuple, list)):
        return bool(value) and all(
            isinstance(item, str) and item for item in value
        )
    return (
        isinstance(value, Mapping)
        and value.get("state") == "not_configured"
        and isinstance(value.get("reason"), str)
        and bool(str(value["reason"]).strip())
    )


__all__ = [
    "BUILTIN_STRATEGY_KEYS",
    "CorePlusGridParameters",
    "InvestmentThesisVersion",
    "StrategyCatalog",
    "StrategyContractError",
    "StrategyDefinition",
    "StrategyParameterContract",
    "StrategyVersion",
    "TrendHoldBreakExitParameters",
    "builtin_strategy_versions",
]
