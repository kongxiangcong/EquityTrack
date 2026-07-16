from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import math
from typing import Any, Literal


DistributionFamily = Literal[
    "uniform",
    "triangular",
    "calibrated_normal",
    "empirical",
    "bernoulli",
]
SimulationStatus = Literal["ready", "partial"]


class SimulationInvariantError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _decimal(value: float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if not math.isfinite(value):
        raise SimulationInvariantError(
            "SIMULATION_NON_FINITE_RESULT",
            "Simulation calculations must remain finite.",
        )
    return Decimal(repr(value))


def _text(value: Decimal, places: str = "0.000000000001") -> str:
    try:
        quantized = value.quantize(Decimal(places))
    except InvalidOperation:
        quantized = value
    rendered = format(quantized, "f").rstrip("0").rstrip(".")
    return rendered or "0"


@dataclass(frozen=True)
class CalibrationEvidence:
    sample_id: str
    observations: tuple[Decimal, ...]
    window_start: str
    window_end: str
    as_of: str
    published_at: str
    available_at: str
    retrieved_at: str
    basis: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "observations": [_text(item) for item in self.observations],
            "window_start": self.window_start,
            "window_end": self.window_end,
            "as_of": self.as_of,
            "published_at": self.published_at,
            "available_at": self.available_at,
            "retrieved_at": self.retrieved_at,
            "basis": self.basis,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class CalibratedDistribution:
    assumption_id: str
    family: DistributionFamily
    parameters: tuple[tuple[str, Decimal], ...]
    reference_value: Decimal
    unit: str
    scale: Decimal
    currency: str | None
    hard_min: Decimal
    hard_max: Decimal
    calibration: CalibrationEvidence
    user_override_identity: str | None

    @property
    def parameter_map(self) -> dict[str, Decimal]:
        return dict(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "family": self.family,
            "parameters": [
                {"name": name, "value": _text(value)}
                for name, value in self.parameters
            ],
            "reference_value": _text(self.reference_value),
            "unit": self.unit,
            "scale": _text(self.scale),
            "currency": self.currency,
            "hard_bounds": {
                "minimum": _text(self.hard_min),
                "maximum": _text(self.hard_max),
            },
            "calibration": self.calibration.to_dict(),
            "user_override_identity": self.user_override_identity,
        }


@dataclass(frozen=True)
class DependencyModel:
    model_identity: str
    assumption_ids: tuple[str, ...]
    correlation_matrix: tuple[tuple[Decimal, ...], ...]
    calibration: DependencyCalibrationEvidence
    calibration_tolerance: Decimal
    user_override_identity: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_identity": self.model_identity,
            "assumption_ids": list(self.assumption_ids),
            "correlation_matrix": [
                [_text(value) for value in row]
                for row in self.correlation_matrix
            ],
            "calibration": self.calibration.to_dict(),
            "calibration_tolerance": _text(self.calibration_tolerance),
            "user_override_identity": self.user_override_identity,
        }


@dataclass(frozen=True)
class DependencyCalibrationEvidence:
    sample_id: str
    observation_vectors: tuple[tuple[Decimal, ...], ...]
    window_start: str
    window_end: str
    as_of: str
    published_at: str
    available_at: str
    retrieved_at: str
    basis: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "observation_vectors": [
                [_text(value) for value in row]
                for row in self.observation_vectors
            ],
            "window_start": self.window_start,
            "window_end": self.window_end,
            "as_of": self.as_of,
            "published_at": self.published_at,
            "available_at": self.available_at,
            "retrieved_at": self.retrieved_at,
            "basis": self.basis,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class SimulationTerm:
    assumption_id: str
    coefficient: Decimal
    coefficient_unit: str

    def to_dict(self) -> dict[str, str]:
        return {
            "assumption_id": self.assumption_id,
            "coefficient": _text(self.coefficient),
            "coefficient_unit": self.coefficient_unit,
        }


@dataclass(frozen=True)
class AffineSimulationModel:
    formula_id: str
    intercept: Decimal
    terms: tuple[SimulationTerm, ...]
    output_unit: str
    currency: str
    period: str
    minimum_output: Decimal | None
    maximum_output: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "intercept": _text(self.intercept),
            "terms": [item.to_dict() for item in self.terms],
            "output_unit": self.output_unit,
            "currency": self.currency,
            "period": self.period,
            "minimum_output": (
                _text(self.minimum_output)
                if self.minimum_output is not None
                else None
            ),
            "maximum_output": (
                _text(self.maximum_output)
                if self.maximum_output is not None
                else None
            ),
        }


@dataclass(frozen=True)
class DeterministicValueFallback:
    scenario_id: str
    method_id: str
    formula_version: str
    low: Decimal
    base: Decimal
    high: Decimal
    unit: str
    currency: str
    period: str

    def to_dict(self) -> dict[str, str]:
        return {
            "scenario_id": self.scenario_id,
            "method_id": self.method_id,
            "formula_version": self.formula_version,
            "low": _text(self.low),
            "base": _text(self.base),
            "high": _text(self.high),
            "unit": self.unit,
            "currency": self.currency,
            "period": self.period,
        }


@dataclass(frozen=True)
class SimulationBudget:
    rng_algorithm: str
    seed: int
    sample_budget: int
    batch_size: int
    convergence_tolerance: Decimal
    stable_batches_required: int
    maximum_invalid_path_rate: Decimal
    minimum_tail_observations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rng_algorithm": self.rng_algorithm,
            "seed": self.seed,
            "sample_budget": self.sample_budget,
            "batch_size": self.batch_size,
            "convergence_tolerance": _text(self.convergence_tolerance),
            "stable_batches_required": self.stable_batches_required,
            "maximum_invalid_path_rate": _text(self.maximum_invalid_path_rate),
            "minimum_tail_observations": self.minimum_tail_observations,
        }


@dataclass(frozen=True)
class ValuationSimulationRequest:
    simulation_id: str
    security_id: str
    as_of: str
    valuation_source_identity: str
    model_identity: str
    policy_identity: str
    assumptions: tuple[CalibratedDistribution, ...]
    dependency_model: DependencyModel
    valuation_model: AffineSimulationModel
    deterministic_fallback: DeterministicValueFallback
    tail_threshold: Decimal
    budget: SimulationBudget


@dataclass(frozen=True)
class ValuationSimulationResult:
    simulation_id: str
    security_id: str
    as_of: str
    valuation_source_identity: str
    model_identity: str
    policy_identity: str
    status: SimulationStatus
    converged: bool
    assumptions: tuple[CalibratedDistribution, ...]
    dependency_model: DependencyModel
    valuation_model: AffineSimulationModel
    budget: SimulationBudget
    completed_samples: int
    valid_paths: int
    invalid_paths: int
    invalid_path_rate: str
    convergence_batches: int
    stable_batches: int
    constraint_path: tuple[str, ...]
    tail_threshold: str
    quantiles: dict[str, str] | None
    tail_results: dict[str, str | None] | None
    contributions: tuple[dict[str, str], ...]
    observed_dependency_matrix: tuple[tuple[str, ...], ...]
    deterministic_fallback: dict[str, str]
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "security_id": self.security_id,
            "as_of": self.as_of,
            "valuation_source_identity": self.valuation_source_identity,
            "model_identity": self.model_identity,
            "policy_identity": self.policy_identity,
            "status": self.status,
            "converged": self.converged,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "dependency_model": self.dependency_model.to_dict(),
            "valuation_model": self.valuation_model.to_dict(),
            "budget": self.budget.to_dict(),
            "completed_samples": self.completed_samples,
            "valid_paths": self.valid_paths,
            "invalid_paths": self.invalid_paths,
            "invalid_path_rate": self.invalid_path_rate,
            "convergence_batches": self.convergence_batches,
            "stable_batches": self.stable_batches,
            "constraint_path": list(self.constraint_path),
            "tail_threshold": self.tail_threshold,
            "quantiles": self.quantiles,
            "tail_results": self.tail_results,
            "contributions": list(self.contributions),
            "observed_dependency_matrix": [
                list(row) for row in self.observed_dependency_matrix
            ],
            "deterministic_fallback": self.deterministic_fallback,
            "diagnostics": list(self.diagnostics),
        }


class _SplitMix64:
    MASK = (1 << 64) - 1

    def __init__(self, seed: int) -> None:
        self.state = seed & self.MASK
        self._spare_normal: float | None = None

    def _next_uint64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & self.MASK
        return value ^ (value >> 31)

    def uniform(self) -> float:
        return ((self._next_uint64() >> 11) + 0.5) / (1 << 53)

    def normal(self) -> float:
        if self._spare_normal is not None:
            value = self._spare_normal
            self._spare_normal = None
            return value
        radius = math.sqrt(-2.0 * math.log(self.uniform()))
        angle = 2.0 * math.pi * self.uniform()
        self._spare_normal = radius * math.sin(angle)
        return radius * math.cos(angle)


class ValuationSimulationEngine:
    RNG_ALGORITHM = "splitmix64_box_muller@1"
    CONTRIBUTION_METHOD = "variance_euler_linear@1"
    QUANTILES = (
        ("p5", 0.05),
        ("p25", 0.25),
        ("p50", 0.50),
        ("p75", 0.75),
        ("p95", 0.95),
    )

    def run(self, request: ValuationSimulationRequest) -> ValuationSimulationResult:
        cholesky = self._validate(request)
        generator = _SplitMix64(request.budget.seed)
        values: list[float] = []
        sampled_inputs: list[list[float]] = [
            [] for _ in request.assumptions
        ]
        invalid_paths = 0
        stable_batches = 0
        completed_batches = 0
        previous: tuple[float, ...] | None = None
        converged = False
        total_batches = (
            request.budget.sample_budget + request.budget.batch_size - 1
        ) // request.budget.batch_size
        for batch_index in range(total_batches):
            remaining = request.budget.sample_budget - (
                batch_index * request.budget.batch_size
            )
            count = min(request.budget.batch_size, remaining)
            for _ in range(count):
                independent = [generator.normal() for _ in request.assumptions]
                correlated = [
                    sum(
                        cholesky[row][column] * independent[column]
                        for column in range(row + 1)
                    )
                    for row in range(len(request.assumptions))
                ]
                inputs = [
                    self._sample(distribution, self._normal_cdf(normal))
                    * float(distribution.scale)
                    for distribution, normal in zip(
                        request.assumptions, correlated, strict=True
                    )
                ]
                output = float(request.valuation_model.intercept) + sum(
                    float(term.coefficient) * inputs[index]
                    for index, term in enumerate(request.valuation_model.terms)
                )
                if not self._valid_output(request.valuation_model, output):
                    invalid_paths += 1
                    continue
                values.append(output)
                for index, value in enumerate(inputs):
                    sampled_inputs[index].append(value)
            completed_batches += 1
            if len(values) < max(100, request.budget.batch_size):
                continue
            quantile_state = tuple(
                self._quantile(values, probability)
                for _, probability in self.QUANTILES
            )
            tail_count = sum(
                value < float(request.tail_threshold) for value in values
            )
            tail_probability = tail_count / len(values)
            tail_mean = self._tail_mean(values, float(request.tail_threshold))
            contribution_state = tuple(
                float(item["share"])
                for item in self._contributions(request, sampled_inputs, values)
            )
            current = (
                *quantile_state,
                tail_probability,
                tail_mean if tail_mean is not None else 0.0,
                *contribution_state,
            )
            tail_gate_satisfied = (
                self._tail_is_structurally_impossible(request)
                or tail_count >= request.budget.minimum_tail_observations
            )
            if previous is not None and self._stable(
                previous,
                current,
                float(request.budget.convergence_tolerance),
            ) and tail_gate_satisfied:
                stable_batches += 1
            else:
                stable_batches = 0
            previous = current
            if (
                completed_batches >= 3
                and stable_batches >= request.budget.stable_batches_required
            ):
                converged = True
                break

        completed_samples = (
            len(values) + invalid_paths
        )
        invalid_rate = (
            Decimal(invalid_paths) / Decimal(completed_samples)
            if completed_samples
            else Decimal("1")
        )
        if invalid_rate > request.budget.maximum_invalid_path_rate:
            converged = False
        diagnostics: list[str] = []
        if invalid_rate > request.budget.maximum_invalid_path_rate:
            diagnostics.append(
                "Invalid path rate exceeded the declared maximum; stochastic "
                "quantiles are withheld."
            )
        elif not converged:
            diagnostics.append(
                "Quantile stability did not satisfy the declared convergence gate."
            )
        quantiles = (
            {
                name: _text(_decimal(self._quantile(values, probability)))
                for name, probability in self.QUANTILES
            }
            if converged
            else None
        )
        tail = (
            {
                "threshold": _text(request.tail_threshold),
                "probability_below_threshold": _text(
                    Decimal(
                        sum(value < float(request.tail_threshold) for value in values)
                    )
                    / Decimal(len(values))
                ),
                "conditional_tail_mean": self._tail_mean_text(
                    values,
                    float(request.tail_threshold),
                ),
            }
            if converged
            else None
        )
        contributions = (
            self._contributions(request, sampled_inputs, values)
            if converged
            else ()
        )
        observed = self._observed_dependency(sampled_inputs)
        constraint_path = ["all_assumptions_within_hard_bounds"]
        if request.valuation_model.minimum_output is not None:
            constraint_path.append(
                f"per_share_value>={_text(request.valuation_model.minimum_output)}"
            )
        if request.valuation_model.maximum_output is not None:
            constraint_path.append(
                f"per_share_value<={_text(request.valuation_model.maximum_output)}"
            )
        return ValuationSimulationResult(
            simulation_id=request.simulation_id,
            security_id=request.security_id,
            as_of=request.as_of,
            valuation_source_identity=request.valuation_source_identity,
            model_identity=request.model_identity,
            policy_identity=request.policy_identity,
            status="ready" if converged else "partial",
            converged=converged,
            assumptions=request.assumptions,
            dependency_model=request.dependency_model,
            valuation_model=request.valuation_model,
            budget=request.budget,
            completed_samples=completed_samples,
            valid_paths=len(values),
            invalid_paths=invalid_paths,
            invalid_path_rate=_text(invalid_rate),
            convergence_batches=completed_batches,
            stable_batches=stable_batches,
            constraint_path=tuple(constraint_path),
            tail_threshold=_text(request.tail_threshold),
            quantiles=quantiles,
            tail_results=tail,
            contributions=contributions,
            observed_dependency_matrix=observed,
            deterministic_fallback=request.deterministic_fallback.to_dict(),
            diagnostics=tuple(diagnostics),
        )

    def _validate(
        self,
        request: ValuationSimulationRequest,
    ) -> tuple[tuple[float, ...], ...]:
        if (
            not request.simulation_id
            or not request.security_id
            or not request.as_of
            or not request.valuation_source_identity
            or not request.model_identity
            or not request.policy_identity
            or not request.assumptions
        ):
            raise SimulationInvariantError(
                "SIMULATION_IDENTITY_INVALID",
                "Simulation identity and inputs are required.",
            )
        if request.budget.rng_algorithm != self.RNG_ALGORITHM:
            raise SimulationInvariantError(
                "SIMULATION_RNG_UNSUPPORTED",
                "The RNG algorithm must be explicit and supported.",
            )
        if (
            request.budget.sample_budget <= 0
            or request.budget.batch_size <= 0
            or request.budget.batch_size > request.budget.sample_budget
            or request.budget.stable_batches_required <= 0
            or request.budget.minimum_tail_observations <= 0
            or not Decimal("0") < request.budget.convergence_tolerance < Decimal("1")
            or not Decimal("0")
            <= request.budget.maximum_invalid_path_rate
            < Decimal("1")
        ):
            raise SimulationInvariantError(
                "SIMULATION_BUDGET_INVALID",
                "Sample, batch, convergence, and invalid-path gates must be valid.",
            )
        fallback = request.deterministic_fallback
        model = request.valuation_model
        if (
            not fallback.scenario_id
            or not fallback.method_id
            or not fallback.formula_version
            or fallback.low > fallback.base
            or fallback.base > fallback.high
            or fallback.unit != model.output_unit
            or fallback.currency != model.currency
            or fallback.period != model.period
            or not model.formula_id.strip()
            or not model.output_unit.strip()
            or not model.currency.strip()
            or not model.period.strip()
        ):
            raise SimulationInvariantError(
                "SIMULATION_DETERMINISTIC_FALLBACK_INVALID",
                "The deterministic fallback must identify an ordered parent "
                "valuation range with matching dimensions.",
            )
        assumption_ids = tuple(item.assumption_id for item in request.assumptions)
        if (
            len(assumption_ids) != len(set(assumption_ids))
            or request.dependency_model.assumption_ids != assumption_ids
            or tuple(item.assumption_id for item in request.valuation_model.terms)
            != assumption_ids
        ):
            raise SimulationInvariantError(
                "SIMULATION_ASSUMPTION_BINDING_INVALID",
                "Assumptions, dependency rows, and valuation terms must align.",
            )
        for item in request.assumptions:
            self._validate_distribution(item, request.as_of)
        for item, term in zip(
            request.assumptions,
            request.valuation_model.terms,
            strict=True,
        ):
            expected_unit = (
                model.output_unit
                if item.unit == "decimal"
                else f"{model.output_unit} per {item.unit}"
            )
            if term.coefficient_unit != expected_unit:
                raise SimulationInvariantError(
                    "SIMULATION_TERM_UNIT_INVALID",
                    "Each affine coefficient must declare the dimensional "
                    "conversion from its assumption to the model output.",
                )
        with localcontext() as context:
            context.prec = 80
            reference_anchor = model.intercept + sum(
                (
                    term.coefficient
                    * assumption.reference_value
                    * assumption.scale
                    for assumption, term in zip(
                        request.assumptions,
                        model.terms,
                        strict=True,
                    )
                ),
                Decimal("0"),
            )
        if reference_anchor != fallback.base:
            raise SimulationInvariantError(
                "SIMULATION_DETERMINISTIC_ANCHOR_INVALID",
                "The affine model evaluated at calibrated reference values must "
                "equal the parent deterministic base value.",
            )
        if not request.dependency_model.model_identity.strip():
            raise SimulationInvariantError(
                "SIMULATION_DEPENDENCY_IDENTITY_INVALID",
                "The dependency model must carry a versioned identity.",
            )
        self._validate_dependency(request.dependency_model, request.as_of)
        return self._cholesky(request.dependency_model.correlation_matrix)

    def _validate_distribution(
        self,
        distribution: CalibratedDistribution,
        as_of: str,
    ) -> None:
        if (
            not distribution.assumption_id
            or distribution.hard_min >= distribution.hard_max
            or not distribution.unit.strip()
            or distribution.scale <= 0
            or distribution.reference_value < distribution.hard_min
            or distribution.reference_value > distribution.hard_max
            or (
                distribution.currency is not None
                and not distribution.currency.strip()
            )
            or len(distribution.parameters)
            != len({name for name, _ in distribution.parameters})
        ):
            raise SimulationInvariantError(
                "SIMULATION_DISTRIBUTION_INVALID",
                "Each stochastic assumption requires identity and ordered hard bounds.",
            )
        self._validate_calibration(distribution.calibration, as_of)
        if distribution.user_override_identity is not None and not (
            distribution.user_override_identity.strip()
        ):
            raise SimulationInvariantError(
                "SIMULATION_USER_OVERRIDE_IDENTITY_INVALID",
                "A declared user override requires a non-empty identity.",
            )
        parameters = distribution.parameter_map
        if distribution.family == "uniform":
            if set(parameters) != {"low", "high"} or not (
                distribution.hard_min
                <= parameters["low"]
                < parameters["high"]
                <= distribution.hard_max
            ):
                raise SimulationInvariantError(
                    "SIMULATION_DISTRIBUTION_INVALID",
                    "Uniform parameters must be explicitly bounded.",
                )
            self._require_calibrated(
                distribution,
                {
                    "low": min(distribution.calibration.observations),
                    "high": max(distribution.calibration.observations),
                },
            )
            expected_reference = (
                parameters["low"] + parameters["high"]
            ) / Decimal("2")
        elif distribution.family == "triangular":
            if set(parameters) != {"low", "mode", "high"} or not (
                distribution.hard_min
                <= parameters["low"]
                <= parameters["mode"]
                <= parameters["high"]
                <= distribution.hard_max
            ):
                raise SimulationInvariantError(
                    "SIMULATION_DISTRIBUTION_INVALID",
                    "Triangular parameters must be explicitly bounded.",
                )
            ordered = sorted(distribution.calibration.observations)
            middle = len(ordered) // 2
            median = (
                ordered[middle]
                if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / Decimal("2")
            )
            self._require_calibrated(
                distribution,
                {
                    "low": min(ordered),
                    "mode": median,
                    "high": max(ordered),
                },
            )
            expected_reference = parameters["mode"]
        elif distribution.family == "calibrated_normal":
            if (
                set(parameters) != {"mean", "stdev"}
                or parameters["stdev"] <= 0
                or len(distribution.calibration.observations) < 30
            ):
                raise SimulationInvariantError(
                    "SIMULATION_CALIBRATION_SAMPLE_INSUFFICIENT",
                    "A normal family is allowed only with an explicit calibration sample.",
                )
            observations = distribution.calibration.observations
            mean = sum(observations, Decimal("0")) / Decimal(len(observations))
            variance = sum(
                (item - mean) ** 2 for item in observations
            ) / Decimal(len(observations))
            self._require_calibrated(
                distribution,
                {"mean": mean, "stdev": variance.sqrt()},
                tolerance=Decimal("0.000000001"),
            )
            expected_reference = parameters["mean"]
        elif distribution.family == "empirical":
            if parameters or len(distribution.calibration.observations) < 20:
                raise SimulationInvariantError(
                    "SIMULATION_CALIBRATION_SAMPLE_INSUFFICIENT",
                    "Empirical distributions require at least twenty observations.",
                )
            ordered = sorted(distribution.calibration.observations)
            middle = len(ordered) // 2
            expected_reference = (
                ordered[middle]
                if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / Decimal("2")
            )
        elif distribution.family == "bernoulli":
            if (
                set(parameters) != {"probability"}
                or not Decimal("0") <= parameters["probability"] <= Decimal("1")
                or distribution.hard_min != Decimal("0")
                or distribution.hard_max != Decimal("1")
                or len(distribution.calibration.observations) < 20
                or any(
                    value not in {Decimal("0"), Decimal("1")}
                    for value in distribution.calibration.observations
                )
            ):
                raise SimulationInvariantError(
                    "SIMULATION_CALIBRATION_SAMPLE_INSUFFICIENT",
                    "Bernoulli events require binary calibration observations and "
                    "an explicit probability.",
                )
            probability = (
                sum(distribution.calibration.observations, Decimal("0"))
                / Decimal(len(distribution.calibration.observations))
            )
            self._require_calibrated(
                distribution,
                {"probability": probability},
            )
            expected_reference = parameters["probability"]
        else:
            raise SimulationInvariantError(
                "SIMULATION_DISTRIBUTION_FAMILY_UNSUPPORTED",
                "No implicit or default distribution family is permitted.",
            )
        if (
            distribution.user_override_identity is None
            and distribution.reference_value != expected_reference
        ):
            raise SimulationInvariantError(
                "SIMULATION_REFERENCE_NOT_CALIBRATED",
                "The reference value must match the calibrated distribution "
                "center unless a user override identity is declared.",
            )
        if any(
            value < distribution.hard_min or value > distribution.hard_max
            for value in distribution.calibration.observations
        ):
            raise SimulationInvariantError(
                "SIMULATION_CALIBRATION_OUTSIDE_HARD_BOUNDS",
                "Calibration observations must respect declared hard bounds.",
            )

    @staticmethod
    def _require_calibrated(
        distribution: CalibratedDistribution,
        expected: dict[str, Decimal],
        *,
        tolerance: Decimal = Decimal("0"),
    ) -> None:
        if distribution.user_override_identity is not None:
            return
        parameters = distribution.parameter_map
        if any(
            name not in parameters or abs(parameters[name] - value) > tolerance
            for name, value in expected.items()
        ):
            raise SimulationInvariantError(
                "SIMULATION_PARAMETERS_NOT_CALIBRATED",
                "Distribution parameters must match the frozen calibration "
                "sample unless a user override identity is declared.",
            )

    @staticmethod
    def _validate_calibration(
        calibration: CalibrationEvidence,
        as_of: str,
    ) -> None:
        try:
            request_date = ValuationSimulationEngine._parse_date(as_of)
            window_start = ValuationSimulationEngine._parse_date(
                calibration.window_start
            )
            window_end = ValuationSimulationEngine._parse_date(
                calibration.window_end
            )
            calibration_date = ValuationSimulationEngine._parse_date(
                calibration.as_of
            )
            published_at = ValuationSimulationEngine._parse_timestamp(
                calibration.published_at
            )
            available_at = ValuationSimulationEngine._parse_timestamp(
                calibration.available_at
            )
            retrieved_at = ValuationSimulationEngine._parse_timestamp(
                calibration.retrieved_at
            )
        except (TypeError, ValueError):
            raise SimulationInvariantError(
                "SIMULATION_CALIBRATION_EVIDENCE_INVALID",
                "Calibration dates and timestamps must be valid ISO values.",
            ) from None
        if (
            not calibration.sample_id
            or not calibration.observations
            or window_start > window_end
            or not window_end <= calibration_date <= request_date
            or not published_at <= available_at <= retrieved_at
            or available_at.date() > calibration_date
            or not calibration.basis
            or not calibration.evidence_refs
        ):
            raise SimulationInvariantError(
                "SIMULATION_CALIBRATION_EVIDENCE_INVALID",
                "Calibration requires a PIT-valid sample, window, basis, and evidence.",
            )

    @classmethod
    def _validate_dependency(
        cls,
        dependency: DependencyModel,
        as_of: str,
    ) -> None:
        calibration = dependency.calibration
        dimension = len(dependency.assumption_ids)
        if dependency.user_override_identity is not None and not (
            dependency.user_override_identity.strip()
        ):
            raise SimulationInvariantError(
                "SIMULATION_DEPENDENCY_OVERRIDE_IDENTITY_INVALID",
                "A dependency override requires a non-empty identity.",
            )
        try:
            request_date = cls._parse_date(as_of)
            window_start = cls._parse_date(calibration.window_start)
            window_end = cls._parse_date(calibration.window_end)
            calibration_date = cls._parse_date(calibration.as_of)
            published_at = cls._parse_timestamp(calibration.published_at)
            available_at = cls._parse_timestamp(calibration.available_at)
            retrieved_at = cls._parse_timestamp(calibration.retrieved_at)
        except (TypeError, ValueError):
            raise SimulationInvariantError(
                "SIMULATION_DEPENDENCY_CALIBRATION_INVALID",
                "Dependency dates and timestamps must be valid ISO values.",
            ) from None
        if (
            dimension == 0
            or len(calibration.observation_vectors) < 20
            or any(len(row) != dimension for row in calibration.observation_vectors)
            or not Decimal("0")
            <= dependency.calibration_tolerance
            <= Decimal("0.25")
            or not calibration.sample_id
            or window_start > window_end
            or not window_end <= calibration_date <= request_date
            or not published_at <= available_at <= retrieved_at
            or available_at.date() > calibration_date
            or not calibration.basis
            or not calibration.evidence_refs
        ):
            raise SimulationInvariantError(
                "SIMULATION_DEPENDENCY_CALIBRATION_INVALID",
                "Dependency calibration requires a PIT-valid multivariate sample.",
            )
        if dependency.user_override_identity is None:
            observed = cls._decimal_correlation(calibration.observation_vectors)
            if any(
                abs(
                    dependency.correlation_matrix[row][column]
                    - observed[row][column]
                )
                > dependency.calibration_tolerance
                for row in range(dimension)
                for column in range(dimension)
            ):
                raise SimulationInvariantError(
                    "SIMULATION_DEPENDENCY_NOT_CALIBRATED",
                    "The dependency matrix must match its frozen multivariate "
                    "calibration sample unless an override identity is declared.",
                )

    @staticmethod
    def _decimal_correlation(
        observations: tuple[tuple[Decimal, ...], ...],
    ) -> tuple[tuple[Decimal, ...], ...]:
        columns = tuple(zip(*observations, strict=True))
        means = tuple(
            sum(column, Decimal("0")) / Decimal(len(column))
            for column in columns
        )
        centered = tuple(
            tuple(value - means[index] for value in column)
            for index, column in enumerate(columns)
        )
        if any(
            sum((value * value for value in column), Decimal("0")) == 0
            for column in centered
        ):
            raise SimulationInvariantError(
                "SIMULATION_DEPENDENCY_CALIBRATION_DEGENERATE",
                "Every dependency calibration dimension must have positive variance.",
            )
        matrix: list[tuple[Decimal, ...]] = []
        for left in centered:
            row: list[Decimal] = []
            left_ss = sum((value * value for value in left), Decimal("0"))
            for right in centered:
                right_ss = sum((value * value for value in right), Decimal("0"))
                numerator = sum(
                    (a * b for a, b in zip(left, right, strict=True)),
                    Decimal("0"),
                )
                correlation = numerator / (left_ss * right_ss).sqrt()
                row.append(correlation)
            matrix.append(tuple(row))
        return tuple(matrix)

    @staticmethod
    def _parse_date(value: str) -> date:
        if not isinstance(value, str):
            raise TypeError(value)
        return date.fromisoformat(value)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        if not isinstance(value, str) or "T" not in value:
            raise ValueError(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(value)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _cholesky(
        matrix: tuple[tuple[Decimal, ...], ...],
    ) -> tuple[tuple[float, ...], ...]:
        size = len(matrix)
        if size == 0 or any(len(row) != size for row in matrix):
            raise SimulationInvariantError(
                "SIMULATION_DEPENDENCY_DIMENSION_INVALID",
                "The dependency matrix must be square and non-empty.",
            )
        for row in range(size):
            if matrix[row][row] != Decimal("1"):
                raise SimulationInvariantError(
                    "SIMULATION_DEPENDENCY_DIAGONAL_INVALID",
                    "A correlation matrix requires an exact unit diagonal.",
                )
            for column in range(row):
                if (
                    matrix[row][column] < Decimal("-1")
                    or matrix[row][column] > Decimal("1")
                ):
                    raise SimulationInvariantError(
                        "SIMULATION_DEPENDENCY_NOT_PSD",
                        "Correlation entries must remain within [-1, 1].",
                    )
                if matrix[row][column] != matrix[column][row]:
                    raise SimulationInvariantError(
                        "SIMULATION_DEPENDENCY_NOT_SYMMETRIC",
                        "The dependency matrix must be exactly symmetric.",
                    )
        lower = [[Decimal("0")] * size for _ in range(size)]
        for row in range(size):
            for column in range(row + 1):
                product_sum = sum(
                    (
                        lower[row][index] * lower[column][index]
                        for index in range(column)
                    ),
                    Decimal("0"),
                )
                value = matrix[row][column] - product_sum
                if row == column:
                    if value < 0:
                        raise SimulationInvariantError(
                            "SIMULATION_DEPENDENCY_NOT_PSD",
                            "The dependency matrix must be positive semidefinite.",
                        )
                    lower[row][column] = value.sqrt()
                elif lower[column][column] != 0:
                    lower[row][column] = value / lower[column][column]
                elif value != 0:
                    raise SimulationInvariantError(
                        "SIMULATION_DEPENDENCY_NOT_PSD",
                        "The dependency matrix must be positive semidefinite.",
                    )
        return tuple(tuple(float(value) for value in row) for row in lower)

    def _sample(self, distribution: CalibratedDistribution, uniform: float) -> float:
        parameters = distribution.parameter_map
        if distribution.family == "uniform":
            low, high = float(parameters["low"]), float(parameters["high"])
            value = low + (high - low) * uniform
        elif distribution.family == "triangular":
            low = float(parameters["low"])
            mode = float(parameters["mode"])
            high = float(parameters["high"])
            split = (mode - low) / (high - low)
            if uniform < split:
                value = low + math.sqrt(uniform * (high - low) * (mode - low))
            else:
                value = high - math.sqrt(
                    (1 - uniform) * (high - low) * (high - mode)
                )
        elif distribution.family == "calibrated_normal":
            value = float(parameters["mean"]) + float(
                parameters["stdev"]
            ) * self._normal_inverse(uniform)
        elif distribution.family == "bernoulli":
            value = 1.0 if uniform < float(parameters["probability"]) else 0.0
        else:
            ordered = sorted(float(item) for item in distribution.calibration.observations)
            index = min(len(ordered) - 1, math.floor(uniform * len(ordered)))
            value = ordered[index]
        return min(float(distribution.hard_max), max(float(distribution.hard_min), value))

    @staticmethod
    def _valid_output(model: AffineSimulationModel, output: float) -> bool:
        if not math.isfinite(output):
            return False
        if model.minimum_output is not None and output < float(model.minimum_output):
            return False
        if model.maximum_output is not None and output > float(model.maximum_output):
            return False
        return True

    @staticmethod
    def _quantile(values: list[float], probability: float) -> float:
        ordered = sorted(values)
        position = probability * (len(ordered) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction

    @staticmethod
    def _stable(
        previous: tuple[float, ...],
        current: tuple[float, ...],
        tolerance: float,
    ) -> bool:
        return len(previous) == len(current) and all(
            abs(now - before) <= tolerance * max(abs(before), 0.01)
            for before, now in zip(previous, current, strict=True)
        )

    @staticmethod
    def _tail_is_structurally_impossible(
        request: ValuationSimulationRequest,
    ) -> bool:
        minimum = request.valuation_model.intercept
        for distribution, term in zip(
            request.assumptions,
            request.valuation_model.terms,
            strict=True,
        ):
            bound = (
                distribution.hard_min
                if term.coefficient >= 0
                else distribution.hard_max
            )
            minimum += term.coefficient * bound * distribution.scale
        return request.tail_threshold <= minimum

    @staticmethod
    def _tail_mean(values: list[float], threshold: float) -> float | None:
        tail = [value for value in values if value < threshold]
        return sum(tail) / len(tail) if tail else None

    @classmethod
    def _tail_mean_text(
        cls,
        values: list[float],
        threshold: float,
    ) -> str | None:
        mean = cls._tail_mean(values, threshold)
        return _text(_decimal(mean)) if mean is not None else None

    def _contributions(
        self,
        request: ValuationSimulationRequest,
        inputs: list[list[float]],
        outputs: list[float],
    ) -> tuple[dict[str, str], ...]:
        output_variance = self._covariance(outputs, outputs)
        if output_variance <= 0:
            return ()
        raw = [
            float(term.coefficient)
            * self._covariance(inputs[index], outputs)
            / output_variance
            for index, term in enumerate(request.valuation_model.terms)
        ]
        total = sum(raw)
        if total == 0:
            return ()
        shares = [_decimal(value / total) for value in raw]
        rendered: list[dict[str, str]] = []
        running = Decimal("0")
        for index, (term, share) in enumerate(
            zip(request.valuation_model.terms, shares, strict=True)
        ):
            normalized = (
                Decimal("1") - running
                if index == len(shares) - 1
                else share.quantize(Decimal("0.000000000001"))
            )
            running += normalized
            rendered.append(
                {
                    "assumption_id": term.assumption_id,
                    "share": _text(normalized),
                    "method": self.CONTRIBUTION_METHOD,
                }
            )
        return tuple(rendered)

    def _observed_dependency(
        self,
        inputs: list[list[float]],
    ) -> tuple[tuple[str, ...], ...]:
        matrix: list[tuple[str, ...]] = []
        for left in inputs:
            row: list[str] = []
            for right in inputs:
                covariance = self._covariance(left, right)
                denominator = math.sqrt(
                    max(0.0, self._covariance(left, left))
                    * max(0.0, self._covariance(right, right))
                )
                correlation = covariance / denominator if denominator else 0.0
                row.append(_text(_decimal(correlation)))
            matrix.append(tuple(row))
        return tuple(matrix)

    @staticmethod
    def _covariance(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or len(left) < 2:
            return 0.0
        left_mean = sum(left) / len(left)
        right_mean = sum(right) / len(right)
        return sum(
            (a - left_mean) * (b - right_mean)
            for a, b in zip(left, right, strict=True)
        ) / (len(left) - 1)

    @staticmethod
    def _normal_cdf(value: float) -> float:
        return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))

    @staticmethod
    def _normal_inverse(probability: float) -> float:
        # Peter J. Acklam's inverse-normal approximation.
        probability = min(1.0 - 1e-15, max(1e-15, probability))
        a = (
            -3.969683028665376e01,
            2.209460984245205e02,
            -2.759285104469687e02,
            1.383577518672690e02,
            -3.066479806614716e01,
            2.506628277459239e00,
        )
        b = (
            -5.447609879822406e01,
            1.615858368580409e02,
            -1.556989798598866e02,
            6.680131188771972e01,
            -1.328068155288572e01,
        )
        c = (
            -7.784894002430293e-03,
            -3.223964580411365e-01,
            -2.400758277161838e00,
            -2.549732539343734e00,
            4.374664141464968e00,
            2.938163982698783e00,
        )
        d = (
            7.784695709041462e-03,
            3.224671290700398e-01,
            2.445134137142996e00,
            3.754408661907416e00,
        )
        low = 0.02425
        high = 1 - low
        if probability < low:
            q = math.sqrt(-2 * math.log(probability))
            return (
                (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
                / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
            )
        if probability > high:
            q = math.sqrt(-2 * math.log(1 - probability))
            return -(
                (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
                / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
            )
        q = probability - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
