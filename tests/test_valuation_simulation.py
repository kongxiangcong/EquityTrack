from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json

import pytest

from equity_research import (
    AffineSimulationModel,
    CalibrationEvidence,
    CalibratedDistribution,
    DependencyCalibrationEvidence,
    DependencyModel,
    DeterministicValueFallback,
    SimulationBudget,
    SimulationInvariantError,
    SimulationTerm,
    ValuationSimulationEngine,
    ValuationSimulationRequest,
)


def calibration(
    sample: tuple[str, ...] = tuple(str(index) for index in range(30)),
) -> CalibrationEvidence:
    return CalibrationEvidence(
        sample_id="sample_fixture",
        observations=tuple(Decimal(value) for value in sample),
        window_start="2021-01-01",
        window_end="2025-12-31",
        as_of="2026-07-07",
        published_at="2026-01-01T00:00:00Z",
        available_at="2026-01-02T00:00:00Z",
        retrieved_at="2026-07-07T00:00:00Z",
        basis="PIT fixture calibrated from disclosed operating history.",
        evidence_refs=("Evidence:fixture",),
    )


def distribution(
    assumption_id: str,
    *,
    family: str = "uniform",
    parameters: tuple[tuple[str, str], ...] = (("low", "0"), ("high", "1")),
    hard_bounds: tuple[str, str] = ("0", "1"),
    evidence: CalibrationEvidence | None = None,
    reference_value: str | None = None,
    unit: str = "decimal",
    currency: str | None = None,
    user_override_identity: str | None = None,
) -> CalibratedDistribution:
    minimum = Decimal(hard_bounds[0])
    maximum = Decimal(hard_bounds[1])
    if evidence is None:
        step = (maximum - minimum) / Decimal("29")
        evidence = calibration(
            tuple(
                _decimal_text(
                    maximum
                    if index == 29
                    else minimum + step * index
                )
                for index in range(30)
            )
        )
    parameter_map = dict(parameters)
    if reference_value is None:
        if family == "triangular":
            reference_value = parameter_map["mode"]
        elif family == "calibrated_normal":
            reference_value = parameter_map["mean"]
        elif family == "bernoulli":
            reference_value = parameter_map["probability"]
        elif family == "empirical":
            ordered = sorted(evidence.observations)
            middle = len(ordered) // 2
            reference_value = _decimal_text(
                ordered[middle]
                if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / Decimal("2")
            )
        else:
            reference_value = _decimal_text((minimum + maximum) / Decimal("2"))
    return CalibratedDistribution(
        assumption_id=assumption_id,
        family=family,
        parameters=tuple((name, Decimal(value)) for name, value in parameters),
        reference_value=Decimal(reference_value),
        unit=unit,
        scale=Decimal("1"),
        currency=currency,
        hard_min=minimum,
        hard_max=maximum,
        calibration=evidence,
        user_override_identity=user_override_identity,
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def request(
    assumptions: tuple[CalibratedDistribution, ...],
    *,
    matrix: tuple[tuple[str, ...], ...] | None = None,
    intercept: str = "10",
    coefficients: tuple[str, ...] | None = None,
    minimum_output: str = "0",
    sample_budget: int = 20_000,
    tolerance: str = "0.03",
    dependency_override_identity: str | None = "fixture-dependency-override@1",
    tail_threshold: str = "9",
) -> ValuationSimulationRequest:
    coefficients = coefficients or tuple("1" for _ in assumptions)
    if matrix is None:
        matrix = tuple(
            tuple("1" if row == column else "0" for column in range(len(assumptions)))
            for row in range(len(assumptions))
        )
    coefficients_decimal = tuple(Decimal(value) for value in coefficients)
    base = Decimal(intercept) + sum(
        coefficient * assumption.reference_value
        * assumption.scale
        for assumption, coefficient in zip(
            assumptions,
            coefficients_decimal,
            strict=True,
        )
    )
    vectors = tuple(
        tuple(
            Decimal(index if column == 0 else ((index * (column + 2)) % 31))
            for column in range(len(assumptions))
        )
        for index in range(30)
    )
    return ValuationSimulationRequest(
        simulation_id="simulation_fixture",
        security_id="002897.SZ",
        as_of="2026-07-07",
        valuation_source_identity="valuation_fixture",
        model_identity="valuation-simulation@1",
        policy_identity="simulation-policy@1",
        assumptions=assumptions,
        dependency_model=DependencyModel(
            model_identity="gaussian-copula-fixture@1",
            assumption_ids=tuple(item.assumption_id for item in assumptions),
            correlation_matrix=tuple(
                tuple(Decimal(value) for value in row) for row in matrix
            ),
            calibration=DependencyCalibrationEvidence(
                sample_id="dependency_fixture",
                observation_vectors=vectors,
                window_start="2021-01-01",
                window_end="2025-12-31",
                as_of="2026-07-07",
                published_at="2026-01-01T00:00:00Z",
                available_at="2026-01-02T00:00:00Z",
                retrieved_at="2026-07-07T00:00:00Z",
                basis="PIT fixture multivariate calibration.",
                evidence_refs=("Evidence:dependency-fixture",),
            ),
            calibration_tolerance=Decimal("0.000001"),
            user_override_identity=dependency_override_identity,
        ),
        valuation_model=AffineSimulationModel(
            formula_id="affine-per-share-fixture@1",
            intercept=Decimal(intercept),
            terms=tuple(
                SimulationTerm(
                    item.assumption_id,
                    Decimal(coefficient),
                    (
                        "CNY/share"
                        if item.unit == "decimal"
                        else f"CNY/share per {item.unit}"
                    ),
                )
                for item, coefficient in zip(assumptions, coefficients, strict=True)
            ),
            output_unit="CNY/share",
            currency="CNY",
            period="2026-07-07",
            output_level="per_share_value",
            minimum_output=Decimal(minimum_output),
            maximum_output=None,
        ),
        deterministic_fallback=DeterministicValueFallback(
            scenario_id="scenario_fixture",
            method_id="fcff_dcf",
            formula_version="formula_fixture@1",
            low=base - Decimal("2"),
            base=base,
            high=base + Decimal("2"),
            unit="CNY/share",
            currency="CNY",
            period="2026-07-07",
            output_level="per_share_value",
        ),
        tail_threshold=Decimal(tail_threshold),
        budget=SimulationBudget(
            rng_algorithm="splitmix64_box_muller@1",
            seed=20260707,
            sample_budget=sample_budget,
            batch_size=1000,
            convergence_tolerance=Decimal(tolerance),
            stable_batches_required=2,
            maximum_invalid_path_rate=Decimal("0.05"),
            minimum_tail_observations=10,
        ),
    )


def test_linear_uniform_model_has_known_quantiles_and_byte_reproducibility() -> None:
    engine = ValuationSimulationEngine()
    simulation_request = request(
        (distribution("volume_growth"),),
        coefficients=("2",),
    )

    first = engine.run(simulation_request)
    second = engine.run(simulation_request)

    assert first.status == "ready"
    assert first.converged is True
    assert Decimal(first.quantiles["p50"]) == pytest.approx(Decimal("11"), abs=Decimal("0.04"))
    assert Decimal(first.quantiles["p5"]) == pytest.approx(Decimal("10.1"), abs=Decimal("0.04"))
    assert Decimal(first.quantiles["p95"]) == pytest.approx(Decimal("11.9"), abs=Decimal("0.04"))
    assert first.contributions[0]["assumption_id"] == "volume_growth"
    assert first.contributions[0]["share"] == "1"
    assert json.dumps(first.to_dict(), sort_keys=True, separators=(",", ":")) == json.dumps(
        second.to_dict(), sort_keys=True, separators=(",", ":")
    )


def test_correlated_calibrated_inputs_preserve_declared_dependency() -> None:
    observations = tuple("-1" if index % 2 == 0 else "1" for index in range(60))
    assumptions = (
        distribution(
            "volume",
            family="calibrated_normal",
            parameters=(("mean", "0"), ("stdev", "1")),
            hard_bounds=("-5", "5"),
            evidence=calibration(observations),
        ),
        distribution(
            "margin",
            family="calibrated_normal",
            parameters=(("mean", "0"), ("stdev", "1")),
            hard_bounds=("-5", "5"),
            evidence=calibration(observations),
        ),
    )
    result = ValuationSimulationEngine().run(
        request(
            assumptions,
            matrix=(("1", "0.7"), ("0.7", "1")),
            coefficients=("1", "1"),
            dependency_override_identity="fixture-correlation-override@1",
        )
    )

    observed = Decimal(result.observed_dependency_matrix[0][1])
    assert Decimal("0.64") <= observed <= Decimal("0.76")
    assert {item["assumption_id"] for item in result.contributions} == {
        "volume",
        "margin",
    }
    assert sum(Decimal(item["share"]) for item in result.contributions) == pytest.approx(
        Decimal("1"), abs=Decimal("0.000001")
    )


@pytest.mark.parametrize(
    "matrix,code",
    [
        ((("1", "0.4"), ("0.3", "1")), "SIMULATION_DEPENDENCY_NOT_SYMMETRIC"),
        ((("0.9", "0"), ("0", "1")), "SIMULATION_DEPENDENCY_DIAGONAL_INVALID"),
        ((("1", "1.1"), ("1.1", "1")), "SIMULATION_DEPENDENCY_NOT_PSD"),
        ((("1", "1.0000000000001"), ("1.0000000000001", "1")), "SIMULATION_DEPENDENCY_NOT_PSD"),
    ],
)
def test_illegal_dependency_structures_fail_closed(
    matrix: tuple[tuple[str, ...], ...],
    code: str,
) -> None:
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(
            request(
                (distribution("a"), distribution("b")),
                matrix=matrix,
            )
        )
    assert error.value.code == code


def test_empirical_heavy_tail_requires_sufficient_calibration_sample() -> None:
    insufficient = distribution(
        "commodity_price",
        family="empirical",
        parameters=(),
        hard_bounds=("-10", "20"),
        evidence=calibration(("-5", "-1", "0", "1", "10")),
    )
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(request((insufficient,)))
    assert error.value.code == "SIMULATION_CALIBRATION_SAMPLE_INSUFFICIENT"

    heavy_tail = distribution(
        "commodity_price",
        family="empirical",
        parameters=(),
        hard_bounds=("-10", "20"),
        evidence=calibration(
            tuple(["-2", "-1", "0", "1", "2"] * 8 + ["-8", "12"])
        ),
    )
    result = ValuationSimulationEngine().run(
        request((heavy_tail,), intercept="20", tolerance="0.08")
    )
    assert result.status == "ready"
    assert (
        Decimal(result.quantiles["p50"]) - Decimal(result.quantiles["p5"])
        > Decimal(result.quantiles["p50"]) - Decimal(result.quantiles["p25"])
    )


def test_unqualified_default_normal_family_is_not_available() -> None:
    unsupported = replace(
        distribution("unsupported"),
        family="normal",  # type: ignore[arg-type]
    )
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(request((unsupported,)))
    assert error.value.code == "SIMULATION_DISTRIBUTION_FAMILY_UNSUPPORTED"


def test_calibrated_binary_event_can_drive_a_discrete_value_branch() -> None:
    event = distribution(
        "capacity_release_event",
        family="bernoulli",  # type: ignore[arg-type]
        parameters=(("probability", "0.25"),),
        hard_bounds=("0", "1"),
        evidence=calibration(tuple(["0"] * 30 + ["1"] * 10)),
    )
    result = ValuationSimulationEngine().run(
        request(
            (event,),
            intercept="10",
            coefficients=("8",),
            tolerance="0.08",
        )
    )
    assert result.status == "ready"
    assert Decimal(result.quantiles["p50"]) == Decimal("10")
    assert Decimal(result.quantiles["p95"]) == Decimal("18")


def test_invalid_operating_paths_limit_simulation_and_keep_deterministic_fallback() -> None:
    destructive = distribution(
        "invalid_margin_path",
        parameters=(("low", "-2"), ("high", "-1")),
        hard_bounds=("-2", "-1"),
    )
    result = ValuationSimulationEngine().run(
        request(
            (destructive,),
            intercept="0",
            coefficients=("1",),
            minimum_output="0",
            sample_budget=4000,
        )
    )

    assert result.status == "partial"
    assert result.converged is False
    assert result.quantiles is None
    assert result.invalid_path_rate == "1"
    assert result.deterministic_fallback["base"] == "-1.5"
    assert "model_output>=0" in result.constraint_path


def test_parameters_and_pit_timestamps_fail_closed_without_named_override() -> None:
    mismatched = distribution(
        "mismatch",
        parameters=(("low", "0.1"), ("high", "0.9")),
    )
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(request((mismatched,)))
    assert error.value.code == "SIMULATION_PARAMETERS_NOT_CALIBRATED"

    overridden = replace(
        mismatched,
        reference_value=Decimal("0.5"),
        user_override_identity="researcher-override@1",
    )
    assert ValuationSimulationEngine().run(request((overridden,))).status == "ready"

    future = replace(
        distribution("future"),
        calibration=replace(
            calibration(("0", "1") * 15),
            window_end="2026-08-01",
        ),
    )
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(request((future,)))
    assert error.value.code == "SIMULATION_CALIBRATION_EVIDENCE_INVALID"


def test_dependency_matrix_requires_multivariate_calibration_or_named_override() -> None:
    base = request(
        (distribution("left"), distribution("right")),
        matrix=(("1", "1"), ("1", "1")),
        dependency_override_identity=None,
    )
    vectors = tuple(
        (Decimal(index), Decimal(index))
        for index in range(30)
    )
    calibrated = replace(
        base,
        dependency_model=replace(
            base.dependency_model,
            calibration=replace(
                base.dependency_model.calibration,
                observation_vectors=vectors,
            ),
        ),
    )
    assert ValuationSimulationEngine().run(calibrated).status == "ready"

    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(
            replace(
                calibrated,
                dependency_model=replace(
                    calibrated.dependency_model,
                    correlation_matrix=(
                        (Decimal("1"), Decimal("0")),
                        (Decimal("0"), Decimal("1")),
                    ),
                ),
            )
        )
    assert error.value.code == "SIMULATION_DEPENDENCY_NOT_CALIBRATED"


def test_empty_tail_is_unknown_and_rare_tail_cannot_converge_early() -> None:
    no_tail = ValuationSimulationEngine().run(
        request((distribution("bounded"),), tail_threshold="9")
    )
    assert no_tail.status == "ready"
    assert no_tail.tail_results["conditional_tail_mean"] is None

    event = distribution(
        "rare_loss",
        family="bernoulli",
        parameters=(("probability", "0.01"),),
        hard_bounds=("0", "1"),
        evidence=calibration(tuple(["0"] * 99 + ["1"])),
    )
    rare = request(
        (event,),
        intercept="10",
        coefficients=("-10",),
        tail_threshold="5",
        sample_budget=3000,
        tolerance="0.9",
    )
    rare = replace(
        rare,
        budget=replace(rare.budget, minimum_tail_observations=100),
    )
    result = ValuationSimulationEngine().run(rare)
    assert result.status == "partial"
    assert result.quantiles is None


def test_units_and_deterministic_reference_anchor_are_invariants() -> None:
    base = request((distribution("volume", unit="units"),))
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(
            replace(
                base,
                valuation_model=replace(
                    base.valuation_model,
                    terms=(
                        replace(
                            base.valuation_model.terms[0],
                            coefficient_unit="CNY/share",
                        ),
                    ),
                ),
            )
        )
    assert error.value.code == "SIMULATION_TERM_UNIT_INVALID"

    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(
            replace(
                base,
                deterministic_fallback=replace(
                    base.deterministic_fallback,
                    base=base.deterministic_fallback.base + Decimal("1"),
                    high=base.deterministic_fallback.high + Decimal("1"),
                ),
            )
        )
    assert error.value.code == "SIMULATION_DETERMINISTIC_ANCHOR_INVALID"


def test_pit_dependency_tail_and_scale_gates_cannot_be_disabled() -> None:
    invalid_time = replace(
        distribution("invalid_time"),
        calibration=replace(
            calibration(("0", "1") * 15),
            retrieved_at="not-a-timestamp",
        ),
    )
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(request((invalid_time,)))
    assert error.value.code == "SIMULATION_CALIBRATION_EVIDENCE_INVALID"

    late_availability = replace(
        distribution("late_availability"),
        calibration=replace(
            calibration(("0", "1") * 15),
            as_of="2025-12-31",
            available_at="2026-01-02T00:00:00Z",
        ),
    )
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(request((late_availability,)))
    assert error.value.code == "SIMULATION_CALIBRATION_EVIDENCE_INVALID"

    base = request(
        (distribution("left"), distribution("right")),
        matrix=(("1", "0"), ("0", "1")),
    )
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(
            replace(
                base,
                dependency_model=replace(
                    base.dependency_model,
                    user_override_identity=None,
                    calibration_tolerance=Decimal("2"),
                ),
            )
        )
    assert error.value.code == "SIMULATION_DEPENDENCY_CALIBRATION_INVALID"

    constants = tuple((Decimal("1"), Decimal("1")) for _ in range(30))
    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(
            replace(
                base,
                dependency_model=replace(
                    base.dependency_model,
                    user_override_identity=None,
                    calibration=replace(
                        base.dependency_model.calibration,
                        observation_vectors=constants,
                    ),
                ),
            )
        )
    assert error.value.code == "SIMULATION_DEPENDENCY_CALIBRATION_DEGENERATE"

    with pytest.raises(SimulationInvariantError) as error:
        ValuationSimulationEngine().run(
            replace(
                request((distribution("tail_gate"),)),
                budget=replace(
                    request((distribution("tail_gate"),)).budget,
                    minimum_tail_observations=0,
                ),
            )
        )
    assert error.value.code == "SIMULATION_BUDGET_INVALID"

    scaled = replace(distribution("scaled"), scale=Decimal("1000"))
    scaled_result = ValuationSimulationEngine().run(
        request((scaled,), intercept="10")
    )
    assert Decimal(scaled_result.quantiles["p50"]) > Decimal("400")

    tiny = ValuationSimulationEngine().run(
        request(
            (distribution("tiny_driver"),),
            coefficients=("0.0000000001",),
            tolerance="0.08",
        )
    )
    assert tiny.status == "ready"
    assert tiny.contributions[0]["share"] == "1"

    scaled_tail = request(
        (scaled,),
        intercept="1000",
        coefficients=("-1",),
        tail_threshold="500",
        sample_budget=3000,
        tolerance="0.9",
    )
    scaled_tail = replace(
        scaled_tail,
        budget=replace(
            scaled_tail.budget,
            minimum_tail_observations=2000,
        ),
    )
    assert ValuationSimulationEngine().run(scaled_tail).status == "partial"


def test_empirical_sampling_stays_on_the_observed_support() -> None:
    empirical = distribution(
        "observed_support",
        family="empirical",
        parameters=(),
        hard_bounds=("0", "100"),
        evidence=calibration(tuple(["0"] * 19 + ["100"])),
    )
    engine = ValuationSimulationEngine()
    assert engine._sample(empirical, 0.975) in {0.0, 100.0}
    assert engine._sample(empirical, 0.975) == 100.0
