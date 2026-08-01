from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
import math
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .simulation import _SplitMix64


PathStatus = Literal["ready", "partial"]


def _market_timezone(name: str) -> tzinfo:
    if name == "Asia/Shanghai":
        return timezone(timedelta(hours=8), name)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise ValueError("MARKET_TIMEZONE_UNSUPPORTED") from error


class MarketPathInvariantError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _text(value: Decimal | float, places: str = "0.000000000001") -> str:
    decimal = value if isinstance(value, Decimal) else Decimal(repr(value))
    try:
        decimal = decimal.quantize(Decimal(places))
    except InvalidOperation:
        pass
    rendered = format(decimal, "f").rstrip("0").rstrip(".")
    return rendered or "0"


@dataclass(frozen=True)
class MarketPathObservation:
    session_date: str
    unadjusted_close: Decimal
    adjustment_factor: Decimal
    market_state: str
    close_available_at: str
    factor_available_at: str
    state_available_at: str
    retrieved_at: str
    suspended: bool
    limit_state: Literal["none", "up", "down"]
    corporate_action_identity: str | None
    evidence_refs: tuple[str, ...]

    @property
    def adjusted_close(self) -> Decimal:
        return self.unadjusted_close * self.adjustment_factor

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date,
            "unadjusted_close": _text(self.unadjusted_close),
            "adjustment_factor": _text(self.adjustment_factor),
            "adjusted_close": _text(self.adjusted_close),
            "market_state": self.market_state,
            "close_available_at": self.close_available_at,
            "factor_available_at": self.factor_available_at,
            "state_available_at": self.state_available_at,
            "retrieved_at": self.retrieved_at,
            "suspended": self.suspended,
            "limit_state": self.limit_state,
            "corporate_action_identity": self.corporate_action_identity,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class MarketPathCalibration:
    snapshot_id: str
    platform_snapshot_id: str
    market: str
    market_timezone: str
    series_identity: str
    series_evidence_refs: tuple[str, ...]
    adjustment_mode: Literal["backward_adjusted_return"]
    trading_calendar_identity: str
    calendar_evidence_refs: tuple[str, ...]
    calendar_member_ids: tuple[str, ...]
    trading_sessions: tuple[str, ...]
    next_session_date: str
    next_session_calendar_member_id: str
    series_member_ids: tuple[str, ...]
    adjustment_member_ids: tuple[str, ...]
    corporate_action_member_ids: tuple[str, ...]
    state_model_identity: str
    observations: tuple[MarketPathObservation, ...]
    window_start: str
    window_end: str
    as_of: str
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "platform_snapshot_id": self.platform_snapshot_id,
            "market": self.market,
            "market_timezone": self.market_timezone,
            "series_identity": self.series_identity,
            "series_evidence_refs": list(self.series_evidence_refs),
            "adjustment_mode": self.adjustment_mode,
            "trading_calendar_identity": self.trading_calendar_identity,
            "calendar_evidence_refs": list(self.calendar_evidence_refs),
            "calendar_member_ids": list(self.calendar_member_ids),
            "trading_sessions": list(self.trading_sessions),
            "next_session_date": self.next_session_date,
            "next_session_calendar_member_id": (self.next_session_calendar_member_id),
            "series_member_ids": list(self.series_member_ids),
            "adjustment_member_ids": list(self.adjustment_member_ids),
            "corporate_action_member_ids": list(self.corporate_action_member_ids),
            "state_model_identity": self.state_model_identity,
            "observations": [item.to_dict() for item in self.observations],
            "window_start": self.window_start,
            "window_end": self.window_end,
            "as_of": self.as_of,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class MarketConstraintPolicy:
    policy_identity: str
    one_way_transaction_cost_bps: Decimal
    minimum_execution_lag_sessions: int
    price_limit_fraction: Decimal
    price_tick_size: Decimal | None
    preserve_observed_suspensions: bool
    preserve_observed_limit_states: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_identity": self.policy_identity,
            "one_way_transaction_cost_bps": _text(self.one_way_transaction_cost_bps),
            "minimum_execution_lag_sessions": self.minimum_execution_lag_sessions,
            "price_limit_fraction": _text(self.price_limit_fraction),
            "price_tick_size": (
                _text(self.price_tick_size)
                if self.price_tick_size is not None
                else None
            ),
            "preserve_observed_suspensions": self.preserve_observed_suspensions,
            "preserve_observed_limit_states": self.preserve_observed_limit_states,
        }


@dataclass(frozen=True)
class MarketPathBudget:
    rng_algorithm: str
    seed: int
    path_count: int
    horizon_sessions: int
    block_length: int
    minimum_candidate_blocks: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rng_algorithm": self.rng_algorithm,
            "seed": self.seed,
            "path_count": self.path_count,
            "horizon_sessions": self.horizon_sessions,
            "block_length": self.block_length,
            "minimum_candidate_blocks": self.minimum_candidate_blocks,
        }


@dataclass(frozen=True)
class MarketPathRequest:
    simulation_id: str
    security_id: str
    as_of: str
    as_of_at: str
    valuation_simulation_source_identity: str
    model_identity: str
    policy_identity: str
    price_unit: str
    currency: str
    starting_price: Decimal
    starting_price_session: str
    starting_price_member_id: str
    starting_price_available_at: str
    starting_price_evidence_refs: tuple[str, ...]
    current_market_state: str
    current_state_available_at: str
    current_state_evidence_refs: tuple[str, ...]
    calibration: MarketPathCalibration
    constraints: MarketConstraintPolicy
    budget: MarketPathBudget
    price_thresholds: tuple[Decimal, ...]
    tail_return_threshold: Decimal


@dataclass(frozen=True)
class MarketPathResult:
    simulation_id: str
    security_id: str
    as_of: str
    as_of_at: str
    valuation_simulation_source_identity: str
    model_identity: str
    policy_identity: str
    price_unit: str
    currency: str
    status: PathStatus
    interpretation: str
    calibration: MarketPathCalibration
    constraints: MarketConstraintPolicy
    budget: MarketPathBudget
    starting_price: str
    starting_price_session: str
    starting_price_member_id: str
    starting_price_available_at: str
    starting_price_evidence_refs: tuple[str, ...]
    current_market_state: str
    current_state_available_at: str
    current_state_evidence_refs: tuple[str, ...]
    price_thresholds: tuple[str, ...]
    tail_return_threshold: str
    horizon_return_basis: str
    execution_period: str
    terminal_period: str
    risk_horizon_period: str
    completed_paths: int
    terminal_price_quantiles: dict[str, str] | None
    horizon_return_quantiles: dict[str, str] | None
    maximum_drawdown_quantiles: dict[str, str] | None
    threshold_trigger_probabilities: tuple[dict[str, str], ...]
    tail_results: dict[str, str] | None
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "security_id": self.security_id,
            "as_of": self.as_of,
            "as_of_at": self.as_of_at,
            "valuation_simulation_source_identity": (
                self.valuation_simulation_source_identity
            ),
            "model_identity": self.model_identity,
            "policy_identity": self.policy_identity,
            "price_unit": self.price_unit,
            "currency": self.currency,
            "status": self.status,
            "interpretation": self.interpretation,
            "calibration": self.calibration.to_dict(),
            "constraints": self.constraints.to_dict(),
            "budget": self.budget.to_dict(),
            "starting_price": self.starting_price,
            "starting_price_session": self.starting_price_session,
            "starting_price_member_id": self.starting_price_member_id,
            "starting_price_available_at": self.starting_price_available_at,
            "starting_price_evidence_refs": list(self.starting_price_evidence_refs),
            "current_market_state": self.current_market_state,
            "current_state_available_at": self.current_state_available_at,
            "current_state_evidence_refs": list(self.current_state_evidence_refs),
            "price_thresholds": list(self.price_thresholds),
            "tail_return_threshold": self.tail_return_threshold,
            "horizon_return_basis": self.horizon_return_basis,
            "execution_period": self.execution_period,
            "terminal_period": self.terminal_period,
            "risk_horizon_period": self.risk_horizon_period,
            "completed_paths": self.completed_paths,
            "terminal_price_quantiles": self.terminal_price_quantiles,
            "horizon_return_quantiles": self.horizon_return_quantiles,
            "maximum_drawdown_quantiles": self.maximum_drawdown_quantiles,
            "threshold_trigger_probabilities": list(
                self.threshold_trigger_probabilities
            ),
            "tail_results": self.tail_results,
            "diagnostics": list(self.diagnostics),
        }


class MarketPathEngine:
    RNG_ALGORITHM = "splitmix64_state_block_bootstrap@1"
    QUANTILES = (
        ("p5", 0.05),
        ("p25", 0.25),
        ("p50", 0.50),
        ("p75", 0.75),
        ("p95", 0.95),
    )
    INTERPRETATION = (
        "MarketPathSimulation models state-conditional traded-price paths; "
        "it is not intrinsic value, a target price, or a trading instruction."
    )

    def run(self, request: MarketPathRequest) -> MarketPathResult:
        blocks = self._validate(request)
        if len(blocks) < request.budget.minimum_candidate_blocks:
            return self._partial(
                request,
                "State-conditioned calibration has too few eligible contiguous blocks.",
            )
        generator = _SplitMix64(request.budget.seed)
        terminal_prices: list[float] = []
        horizon_returns: list[float] = []
        drawdowns: list[float] = []
        triggers = {threshold: 0 for threshold in request.price_thresholds}
        tail_count = 0
        round_trip_cost = (
            float(request.constraints.one_way_transaction_cost_bps) * 2.0 / 10_000.0
        )
        execution_lag = request.constraints.minimum_execution_lag_sessions
        for _ in range(request.budget.path_count):
            returns: list[float] = []
            required_returns = request.budget.horizon_sessions + execution_lag
            while len(returns) < required_returns:
                block = blocks[
                    min(
                        len(blocks) - 1,
                        math.floor(generator.uniform() * len(blocks)),
                    )
                ]
                returns.extend(block)
            price = float(request.starting_price)
            for path_return in returns[:execution_lag]:
                price *= math.exp(path_return)
            execution_price = price
            peak = execution_price
            maximum_drawdown = 0.0
            triggered: set[Decimal] = set()
            for threshold in request.price_thresholds:
                if (
                    threshold >= request.starting_price
                    and execution_price >= float(threshold)
                ) or (
                    threshold < request.starting_price
                    and execution_price <= float(threshold)
                ):
                    triggered.add(threshold)
            for path_return in returns[
                execution_lag : execution_lag + request.budget.horizon_sessions
            ]:
                price *= math.exp(path_return)
                peak = max(peak, price)
                maximum_drawdown = min(
                    maximum_drawdown,
                    (price / peak) - 1.0,
                )
                for threshold in request.price_thresholds:
                    if (
                        threshold >= request.starting_price
                        and price >= float(threshold)
                    ) or (
                        threshold < request.starting_price and price <= float(threshold)
                    ):
                        triggered.add(threshold)
            gross_return = price / execution_price - 1.0
            net_return = gross_return - round_trip_cost
            terminal_prices.append(price)
            horizon_returns.append(net_return)
            drawdowns.append(maximum_drawdown)
            for threshold in triggered:
                triggers[threshold] += 1
            if net_return < float(request.tail_return_threshold):
                tail_count += 1
        return MarketPathResult(
            simulation_id=request.simulation_id,
            security_id=request.security_id,
            as_of=request.as_of,
            as_of_at=request.as_of_at,
            valuation_simulation_source_identity=(
                request.valuation_simulation_source_identity
            ),
            model_identity=request.model_identity,
            policy_identity=request.policy_identity,
            price_unit=request.price_unit,
            currency=request.currency,
            status="ready",
            interpretation=self.INTERPRETATION,
            calibration=request.calibration,
            constraints=request.constraints,
            budget=request.budget,
            starting_price=_text(request.starting_price),
            starting_price_session=request.starting_price_session,
            starting_price_member_id=request.starting_price_member_id,
            starting_price_available_at=request.starting_price_available_at,
            starting_price_evidence_refs=request.starting_price_evidence_refs,
            current_market_state=request.current_market_state,
            current_state_available_at=request.current_state_available_at,
            current_state_evidence_refs=request.current_state_evidence_refs,
            price_thresholds=tuple(_text(item) for item in request.price_thresholds),
            tail_return_threshold=_text(request.tail_return_threshold),
            horizon_return_basis=("net_of_declared_round_trip_transaction_costs"),
            execution_period=f"T+{execution_lag} trading sessions",
            terminal_period=(
                f"T+{execution_lag + request.budget.horizon_sessions} "
                "trading sessions"
            ),
            risk_horizon_period=(
                f"T+{execution_lag} through "
                f"T+{execution_lag + request.budget.horizon_sessions} "
                "trading sessions"
            ),
            completed_paths=request.budget.path_count,
            terminal_price_quantiles=self._quantiles(terminal_prices),
            horizon_return_quantiles=self._quantiles(horizon_returns),
            maximum_drawdown_quantiles=self._quantiles(drawdowns),
            threshold_trigger_probabilities=tuple(
                {
                    "threshold": _text(threshold),
                    "probability": _text(
                        Decimal(count) / Decimal(request.budget.path_count)
                    ),
                }
                for threshold, count in sorted(triggers.items())
            ),
            tail_results={
                "return_threshold": _text(request.tail_return_threshold),
                "probability_below_threshold": _text(
                    Decimal(tail_count) / Decimal(request.budget.path_count)
                ),
            },
            diagnostics=(),
        )

    def _validate(
        self,
        request: MarketPathRequest,
    ) -> tuple[tuple[float, ...], ...]:
        if (
            not request.simulation_id
            or not request.security_id
            or not request.valuation_simulation_source_identity
            or not request.model_identity
            or not request.policy_identity
            or not request.price_unit
            or not request.currency
            or request.price_unit != f"{request.currency}/share"
            or request.starting_price <= 0
            or not request.starting_price_member_id
            or request.starting_price_member_id
            not in request.starting_price_evidence_refs
            or not request.current_market_state
            or not request.starting_price_evidence_refs
            or not request.current_state_evidence_refs
        ):
            raise MarketPathInvariantError(
                "MARKET_PATH_IDENTITY_INVALID",
                "Market path identity, parent Simulation, state, and price are required.",
            )
        try:
            as_of = date.fromisoformat(request.as_of)
            as_of_at = self._timestamp(request.as_of_at)
            market_timezone = _market_timezone(request.calibration.market_timezone)
            as_of_local_date = self._local_date(
                request.as_of_at,
                market_timezone,
            )
            starting_session = date.fromisoformat(request.starting_price_session)
            window_start = date.fromisoformat(request.calibration.window_start)
            window_end = date.fromisoformat(request.calibration.window_end)
            calibration_as_of = date.fromisoformat(request.calibration.as_of)
            starting_price_available = self._timestamp(
                request.starting_price_available_at
            )
            current_state_available = self._timestamp(
                request.current_state_available_at
            )
        except ValueError:
            raise MarketPathInvariantError(
                "MARKET_PATH_DATE_INVALID",
                "Market path dates must use ISO calendar dates.",
            ) from None
        if (
            starting_session > as_of
            or as_of_local_date != as_of
            or self._local_date(
                request.starting_price_available_at,
                market_timezone,
            )
            > as_of
            or self._local_date(
                request.current_state_available_at,
                market_timezone,
            )
            > as_of
            or starting_price_available > as_of_at
            or current_state_available > as_of_at
            or not window_start <= window_end <= calibration_as_of <= as_of
            or request.calibration.adjustment_mode != "backward_adjusted_return"
            or not request.calibration.snapshot_id
            or not request.calibration.platform_snapshot_id
            or not request.calibration.market
            or not request.calibration.market_timezone
            or not request.calibration.trading_calendar_identity
            or not request.calibration.calendar_evidence_refs
            or not request.calibration.calendar_member_ids
            or not request.calibration.next_session_date
            or not request.calibration.next_session_calendar_member_id
            or request.calibration.next_session_date != request.starting_price_session
            or request.calibration.next_session_calendar_member_id
            not in request.calibration.calendar_evidence_refs
            or not request.calibration.series_identity
            or not request.calibration.series_evidence_refs
            or len(request.calibration.series_member_ids)
            != len(request.calibration.observations)
            or not set(request.calibration.calendar_member_ids).issubset(
                request.calibration.calendar_evidence_refs
            )
            or not set(request.calibration.series_member_ids).issubset(
                {
                    ref
                    for observation in request.calibration.observations
                    for ref in observation.evidence_refs
                }
            )
            or not request.calibration.state_model_identity
            or request.calibration.state_model_identity != "one_session_return_sign@1"
            or not request.calibration.basis
            or request.budget.rng_algorithm != self.RNG_ALGORITHM
            or request.budget.path_count < 1000
            or request.budget.horizon_sessions <= 0
            or request.budget.block_length < 2
            or request.budget.minimum_candidate_blocks <= 0
            or request.constraints.minimum_execution_lag_sessions != 1
            or not request.constraints.policy_identity
            or not Decimal("0")
            <= request.constraints.one_way_transaction_cost_bps
            <= Decimal("1000")
            or not Decimal("0")
            < request.constraints.price_limit_fraction
            < Decimal("1")
            or (
                request.constraints.price_tick_size is not None
                and (
                    not request.constraints.price_tick_size.is_finite()
                    or request.constraints.price_tick_size <= 0
                )
            )
            or any(threshold <= 0 for threshold in request.price_thresholds)
        ):
            raise MarketPathInvariantError(
                "MARKET_PATH_POLICY_INVALID",
                "PIT, adjustment, block-bootstrap, cost, and execution policies "
                "must be explicit and valid.",
            )
        observations = request.calibration.observations
        if len(observations) < request.budget.block_length + 1:
            raise MarketPathInvariantError(
                "MARKET_PATH_SAMPLE_INSUFFICIENT",
                "A block bootstrap requires enough ordered observations.",
            )
        if (
            observations[0].session_date != request.calibration.window_start
            or observations[-1].session_date != request.calibration.window_end
            or tuple(item.session_date for item in observations)
            != request.calibration.trading_sessions
        ):
            raise MarketPathInvariantError(
                "MARKET_PATH_WINDOW_INVALID",
                "Calibration window boundaries must match the frozen series.",
            )
        previous_date: date | None = None
        for index, observation in enumerate(observations):
            try:
                session = date.fromisoformat(observation.session_date)
                if (
                    self._local_date(
                        observation.close_available_at,
                        market_timezone,
                    )
                    > session
                ):
                    raise ValueError(observation.close_available_at)
                if (
                    self._local_date(
                        observation.factor_available_at,
                        market_timezone,
                    )
                    > session
                ):
                    raise ValueError(observation.factor_available_at)
                if (
                    self._local_date(
                        observation.state_available_at,
                        market_timezone,
                    )
                    > session
                ):
                    raise ValueError(observation.state_available_at)
                close_available = self._timestamp(observation.close_available_at)
                factor_available = self._timestamp(observation.factor_available_at)
                state_available = self._timestamp(observation.state_available_at)
                retrieved = self._timestamp(observation.retrieved_at)
            except ValueError:
                raise MarketPathInvariantError(
                    "MARKET_PATH_PIT_INVALID",
                    "Observation timestamps must be valid timezone-aware ISO values.",
                ) from None
            if (
                session > as_of
                or session < window_start
                or session > window_end
                or previous_date is not None
                and session <= previous_date
                or self._local_date(
                    observation.retrieved_at,
                    market_timezone,
                )
                > as_of
                or retrieved > as_of_at
                or close_available > retrieved
                or factor_available > retrieved
                or state_available > retrieved
                or observation.unadjusted_close <= 0
                or observation.adjustment_factor <= 0
                or not observation.market_state
                or observation.limit_state not in {"none", "up", "down"}
                or not observation.evidence_refs
            ):
                raise MarketPathInvariantError(
                    "MARKET_PATH_PIT_INVALID",
                    "Forward data, future state labels, leaked factors, and "
                    "unidentified corporate actions are not admissible.",
                )
            previous_date = session
        returns: list[float] = []
        for previous, current in zip(observations, observations[1:]):
            if (
                current.adjustment_factor != previous.adjustment_factor
                and not current.corporate_action_identity
            ):
                raise MarketPathInvariantError(
                    "MARKET_PATH_CORPORATE_ACTION_INVALID",
                    "Every adjustment-factor change requires a corporate-action identity.",
                )
            simple_return = float(
                current.adjusted_close / previous.adjusted_close - Decimal("1")
            )
            limit = float(request.constraints.price_limit_fraction)
            # Price limits are applied to a tick-rounded reference price. The
            # observed close-to-close return can therefore differ slightly
            # from the nominal percentage. Tick semantics are data, not a
            # policy-name convention.
            limit_rounding_tolerance = (
                float(
                    request.constraints.price_tick_size
                    / Decimal("2")
                    / previous.adjusted_close
                )
                if request.constraints.price_tick_size is not None
                else 1e-12
            )
            if current.suspended:
                if not request.constraints.preserve_observed_suspensions:
                    raise MarketPathInvariantError(
                        "MARKET_PATH_SUSPENSION_POLICY_INVALID",
                        "Observed suspensions cannot be silently discarded.",
                    )
                if current.adjusted_close != previous.adjusted_close:
                    raise MarketPathInvariantError(
                        "MARKET_PATH_SUSPENSION_CONTRADICTION",
                        "A suspended session cannot carry a changed adjusted close.",
                    )
                simple_return = 0.0
            if abs(simple_return) > limit + limit_rounding_tolerance:
                raise MarketPathInvariantError(
                    "MARKET_PATH_LIMIT_SEMANTICS_INVALID",
                    "Observed returns must respect the declared market price limit.",
                )
            if (
                current.limit_state != "none"
                and not request.constraints.preserve_observed_limit_states
            ):
                raise MarketPathInvariantError(
                    "MARKET_PATH_LIMIT_POLICY_INVALID",
                    "Observed limit states cannot be silently discarded.",
                )
            if (
                current.limit_state == "up"
                and abs(simple_return - limit) > limit_rounding_tolerance
                or current.limit_state == "down"
                and abs(simple_return + limit) > limit_rounding_tolerance
                or current.limit_state == "none"
                and abs(simple_return) >= limit - limit_rounding_tolerance
            ):
                raise MarketPathInvariantError(
                    "MARKET_PATH_LIMIT_STATE_CONTRADICTION",
                    "Limit-state labels must agree with the observed adjusted return.",
                )
            returns.append(math.log1p(simple_return))
        for index, observation in enumerate(observations):
            expected_state = (
                "warmup"
                if index == 0
                else self._return_state(
                    observation.adjusted_close,
                    observations[index - 1].adjusted_close,
                )
            )
            required_state_refs = {request.calibration.series_member_ids[index]}
            if index:
                required_state_refs.add(
                    request.calibration.series_member_ids[index - 1]
                )
            required_state_available = max(
                self._timestamp(observation.close_available_at),
                self._timestamp(observation.factor_available_at),
            )
            if index:
                required_state_available = max(
                    required_state_available,
                    self._timestamp(observations[index - 1].close_available_at),
                    self._timestamp(observations[index - 1].factor_available_at),
                )
            if (
                observation.market_state != expected_state
                or not required_state_refs.issubset(observation.evidence_refs)
                or self._timestamp(observation.state_available_at)
                < required_state_available
            ):
                raise MarketPathInvariantError(
                    "MARKET_PATH_STATE_LINEAGE_INVALID",
                    "Historical market states must be reproducible from "
                    "the frozen adjacent-session series.",
                )
        expected_current_state = self._return_state(
            request.starting_price,
            observations[-1].adjusted_close,
        )
        if (
            request.current_market_state != expected_current_state
            or not {
                request.starting_price_member_id,
                request.calibration.series_member_ids[-1],
                request.calibration.state_model_identity,
            }.issubset(request.current_state_evidence_refs)
            or current_state_available
            < max(
                starting_price_available,
                self._timestamp(observations[-1].close_available_at),
                self._timestamp(observations[-1].factor_available_at),
            )
        ):
            raise MarketPathInvariantError(
                "MARKET_PATH_STATE_LINEAGE_INVALID",
                "Current market state must be reproducible from the frozen "
                "starting close and latest calibration session.",
            )
        block_length = request.budget.block_length
        return tuple(
            tuple(returns[index : index + block_length])
            for index in range(len(returns) - block_length + 1)
            if observations[index].market_state == request.current_market_state
        )

    @staticmethod
    def _timestamp(value: str) -> datetime:
        if "T" not in value:
            raise ValueError(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(value)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _local_date(value: str, market_timezone: tzinfo) -> date:
        if "T" not in value:
            raise ValueError(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(value)
        return parsed.astimezone(market_timezone).date()

    @staticmethod
    def _return_state(current: Decimal, previous: Decimal) -> str:
        if current > previous:
            return "risk_on"
        if current < previous:
            return "risk_off"
        return "flat"

    def _quantiles(self, values: list[float]) -> dict[str, str]:
        ordered = sorted(values)
        return {
            label: _text(self._quantile(ordered, probability))
            for label, probability in self.QUANTILES
        }

    @staticmethod
    def _quantile(ordered: list[float], probability: float) -> float:
        position = probability * (len(ordered) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction

    def _partial(
        self,
        request: MarketPathRequest,
        diagnostic: str,
    ) -> MarketPathResult:
        return MarketPathResult(
            simulation_id=request.simulation_id,
            security_id=request.security_id,
            as_of=request.as_of,
            as_of_at=request.as_of_at,
            valuation_simulation_source_identity=(
                request.valuation_simulation_source_identity
            ),
            model_identity=request.model_identity,
            policy_identity=request.policy_identity,
            price_unit=request.price_unit,
            currency=request.currency,
            status="partial",
            interpretation=self.INTERPRETATION,
            calibration=request.calibration,
            constraints=request.constraints,
            budget=request.budget,
            starting_price=_text(request.starting_price),
            starting_price_session=request.starting_price_session,
            starting_price_member_id=request.starting_price_member_id,
            starting_price_available_at=request.starting_price_available_at,
            starting_price_evidence_refs=request.starting_price_evidence_refs,
            current_market_state=request.current_market_state,
            current_state_available_at=request.current_state_available_at,
            current_state_evidence_refs=request.current_state_evidence_refs,
            price_thresholds=tuple(_text(item) for item in request.price_thresholds),
            tail_return_threshold=_text(request.tail_return_threshold),
            horizon_return_basis=("net_of_declared_round_trip_transaction_costs"),
            execution_period=(
                f"T+{request.constraints.minimum_execution_lag_sessions} "
                "trading sessions"
            ),
            terminal_period=(
                "T+"
                f"{request.constraints.minimum_execution_lag_sessions + request.budget.horizon_sessions} "
                "trading sessions"
            ),
            risk_horizon_period=(
                f"T+{request.constraints.minimum_execution_lag_sessions} through "
                "T+"
                f"{request.constraints.minimum_execution_lag_sessions + request.budget.horizon_sessions} "
                "trading sessions"
            ),
            completed_paths=0,
            terminal_price_quantiles=None,
            horizon_return_quantiles=None,
            maximum_drawdown_quantiles=None,
            threshold_trigger_probabilities=(),
            tail_results=None,
            diagnostics=(diagnostic,),
        )
