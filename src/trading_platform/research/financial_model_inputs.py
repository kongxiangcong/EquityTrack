from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from equity_research import (
    AffineSimulationModel,
    CalibrationEvidence,
    CalibratedDistribution,
    DependencyCalibrationEvidence,
    DependencyModel,
    DeterministicValueFallback,
    FinancialQuantity,
    SimulationBudget,
    SimulationTerm,
    ValuationSimulationEngine,
    ValuationSimulationRequest,
)
from equity_research.forecast import (
    CompanyArchetype,
    CompanyOpeningBalanceSheet,
    DataSnapshot,
    ForecastQuantity,
    ForecastRequest,
    Security,
    SegmentBaseline,
    SegmentForecastOverride,
    SnapshotFact,
)
from equity_research.scenario_valuation import (
    DcfApplicability,
    DcfValuationSpec,
    DeterministicScenarioRequest,
    DeterministicScenarioResult,
    EquityBridgeSpec,
    EquityBridgeTiming,
    ReverseDcfSpec,
    ScenarioDefinition,
    ScenarioRole,
    SotpComponentSpec,
    SotpValuationSpec,
    ValuationPlan,
)

from trading_platform.application.workflow_ledger import (
    SnapshotEvidence,
    SnapshotMemberEvidence,
)
from trading_platform.domain.research_model_input import (
    exact_model_path,
    typed_model_field_failure,
)
from trading_platform.domain.research_evaluation import ResearchWorkflowRequest
from trading_platform.identity import canonical_hash


_BASELINE_METRICS = (
    "volume",
    "asp",
    "capacity",
    "utilization",
    "unit_cost",
    "operating_expense",
    "capex",
    "working_capital",
    "depreciation",
    "tax_rate",
)
_OPENING_METRICS = (
    "cash",
    "working_capital",
    "net_ppe",
    "other_assets",
    "debt",
    "other_liabilities",
    "equity",
)
_OVERRIDE_METRICS = SegmentForecastOverride.field_names()
_BRIDGE_FIELDS = (
    "diluted_shares",
    "lease_debt",
    "preferred_stock",
    "minority_interest",
    "pension_deficit",
    "associates_jv_value",
    "non_operating_assets",
)
_RESERVED_SEGMENT_IDS = frozenset({"company"})


@dataclass(frozen=True)
class FrozenModelCompilation:
    scenario_request: DeterministicScenarioRequest | None
    missing_gates: tuple[str, ...]
    source_member_ids: tuple[str, ...]


@dataclass(frozen=True)
class FrozenSimulationCompilation:
    request: ValuationSimulationRequest | None
    missing_gates: tuple[str, ...]
    source_member_ids: tuple[str, ...]


@dataclass(frozen=True)
class _Input:
    path: str
    value: Any
    period: str
    unit: str
    currency: str
    member: SnapshotMemberEvidence

    @property
    def fact_id(self) -> str:
        return "model_fact_" + canonical_hash(
            {
                "member": self.member.normalized_version_id,
                "path": self.path,
                "period": self.period,
                "value": str(self.value),
                "unit": self.unit,
                "currency": self.currency,
            }
        )[:24]

    @property
    def fact_ref(self) -> str:
        return f"Fact:{self.fact_id}"

    @property
    def assumption_ref(self) -> str:
        return "Assumption:model_input:" + canonical_hash(
            {
                "member": self.member.normalized_version_id,
                "path": self.path,
                "period": self.period,
                "value": str(self.value),
            }
        )[:24]


class FrozenFinancialModelCompiler:
    """Builds the existing typed engines only from exact frozen model inputs."""

    IDENTITY = "FrozenFinancialModelCompiler@2"

    def compile_scenarios(
        self,
        *,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> FrozenModelCompilation:
        inputs, duplicate, failure_code = _model_inputs(
            evidence,
            prefixes=("forecast.", "scenario.", "valuation."),
        )
        source_ids = _source_ids(inputs)
        if failure_code is not None:
            return FrozenModelCompilation(
                None,
                (failure_code,),
                source_ids,
            )
        if duplicate:
            return FrozenModelCompilation(
                None,
                ("RESEARCH_MODEL_INPUT_DUPLICATE",),
                source_ids,
            )
        structural = (
            "forecast.archetype",
            "forecast.company_name",
            "forecast.segment_ids",
            "forecast.opening_period",
        )
        missing = [path for path in structural if path not in inputs]
        if missing:
            return FrozenModelCompilation(
                None,
                ("FORECAST_TYPED_INPUTS_INSUFFICIENT",),
                source_ids,
            )
        try:
            segments = tuple(
                item.strip()
                for item in str(inputs["forecast.segment_ids"].value).split(",")
                if item.strip()
            )
            archetype = CompanyArchetype(
                str(inputs["forecast.archetype"].value)
            )
        except ValueError:
            return FrozenModelCompilation(
                None,
                ("FORECAST_TYPED_INPUTS_INVALID",),
                source_ids,
            )
        if any(segment in _RESERVED_SEGMENT_IDS for segment in segments):
            return FrozenModelCompilation(
                None,
                ("FORECAST_SEGMENT_ID_RESERVED",),
                source_ids,
            )
        periods = _forecast_periods(request)
        required = [
            *(
                f"forecast.baseline.{segment}.{metric}"
                for segment in segments
                for metric in _BASELINE_METRICS
            ),
            *(
                f"forecast.opening.{metric}"
                for metric in _OPENING_METRICS
            ),
            *(
                f"scenario.{role.value}.{period}.{segment}.{metric}"
                for role in ScenarioRole
                for period in periods
                for segment in segments
                for metric in _OVERRIDE_METRICS
            ),
            *(
                f"valuation.bridge.{timing}.{field}"
                for timing in ("opening", "terminal")
                for field in _BRIDGE_FIELDS
            ),
            "valuation.dcf.status",
            "valuation.dcf.reason",
            "valuation.dcf.discount_rate_low",
            "valuation.dcf.discount_rate_base",
            "valuation.dcf.discount_rate_high",
            "valuation.dcf.terminal_growth_low",
            "valuation.dcf.terminal_growth_base",
            "valuation.dcf.terminal_growth_high",
            "valuation.reverse.enterprise_value",
            "valuation.reverse.discount_rate",
            *(
                f"valuation.sotp.{segment}.{field}"
                for segment in segments
                for field in (
                    "metric",
                    "multiple_low",
                    "multiple_base",
                    "multiple_high",
                )
            ),
        ]
        absent = tuple(path for path in required if path not in inputs)
        if absent:
            gates = []
            if any(path.startswith("forecast.") for path in absent):
                gates.append("FORECAST_TYPED_INPUTS_INSUFFICIENT")
            if any(path.startswith("scenario.") for path in absent):
                gates.append("SCENARIO_DRIVER_INPUTS_INSUFFICIENT")
            if any(path.startswith("valuation.") for path in absent):
                gates.append("VALUATION_METHOD_INPUTS_INSUFFICIENT")
            return FrozenModelCompilation(
                None,
                tuple(gates),
                source_ids,
            )
        if any(
            inputs[path].member.source_authority != "official"
            for path in required
            if path.startswith(
                (
                    "forecast.baseline.",
                    "forecast.opening.",
                    "valuation.bridge.opening.",
                    "valuation.reverse.enterprise_value",
                )
            )
        ):
            return FrozenModelCompilation(
                None,
                ("RESEARCH_MODEL_OFFICIAL_FACTS_REQUIRED",),
                source_ids,
            )
        try:
            compiled = self._scenario_request(
                request,
                evidence,
                inputs,
                segments,
                archetype,
                periods,
            )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return FrozenModelCompilation(
                None,
                ("RESEARCH_MODEL_TYPED_INPUT_INVALID",),
                source_ids,
            )
        return FrozenModelCompilation(compiled, (), source_ids)

    def compile_simulation(
        self,
        *,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        scenario_result: DeterministicScenarioResult,
        scenario_artifact_id: str,
    ) -> FrozenSimulationCompilation:
        simulation_inputs, duplicate, failure_code = _model_inputs(
            evidence,
            prefixes=("simulation.",),
        )
        source_ids = _source_ids(simulation_inputs)
        if failure_code is not None:
            return FrozenSimulationCompilation(
                None,
                (failure_code,),
                source_ids,
            )
        if duplicate:
            return FrozenSimulationCompilation(
                None,
                ("VALUATION_SIMULATION_INPUT_DUPLICATE",),
                source_ids,
            )
        required = (
            "simulation.policy_identity",
            "simulation.hard_min",
            "simulation.hard_max",
            "simulation.tail_threshold",
            "simulation.sample_budget",
            "simulation.batch_size",
            "simulation.convergence_tolerance",
            "simulation.stable_batches_required",
            "simulation.maximum_invalid_path_rate",
            "simulation.minimum_tail_observations",
        )
        observations = tuple(
            item
            for path, item in sorted(simulation_inputs.items())
            if path.startswith("simulation.calibration.")
        )
        if (
            any(path not in simulation_inputs for path in required)
            or len(observations) < 20
        ):
            return FrozenSimulationCompilation(
                None,
                ("VALUATION_SIMULATION_CALIBRATION_UNAVAILABLE",),
                source_ids,
            )
        try:
            base_scenario = next(
                item
                for item in scenario_result.scenarios
                if item.role is ScenarioRole.BASE
            )
            method = next(
                item
                for item in base_scenario.methods
                if item.method_id == "fcff_dcf"
                and item.status == "ready"
                and item.conditional_value_range is not None
            )
            value_range = method.conditional_value_range
            if value_range is None:
                raise ValueError("VALUATION_SIMULATION_PARENT_MISSING")
            points = (
                value_range.low.per_share_value,
                value_range.base.per_share_value,
                value_range.high.per_share_value,
            )
            if any(item is None for item in points):
                raise ValueError("VALUATION_SIMULATION_PARENT_MISSING")
            low, base, high = points
            if low is None or base is None or high is None:
                raise ValueError("VALUATION_SIMULATION_PARENT_MISSING")
            compiled = self._simulation_request(
                request,
                scenario_artifact_id,
                method.formula_version,
                low,
                base,
                high,
                simulation_inputs,
                observations,
            )
        except (
            InvalidOperation,
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
        ):
            return FrozenSimulationCompilation(
                None,
                ("VALUATION_SIMULATION_INPUTS_INVALID",),
                source_ids,
            )
        return FrozenSimulationCompilation(compiled, (), source_ids)

    def _scenario_request(
        self,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        inputs: Mapping[str, _Input],
        segments: tuple[str, ...],
        archetype: CompanyArchetype,
        periods: tuple[str, ...],
    ) -> DeterministicScenarioRequest:
        as_of = request.evaluation_plan.horizon.as_of
        baselines: list[SegmentBaseline] = []
        facts: dict[str, SnapshotFact] = {}
        for segment in segments:
            quantities = {
                metric: _forecast_quantity(
                    inputs[f"forecast.baseline.{segment}.{metric}"],
                    as_of,
                    fact=True,
                )
                for metric in _BASELINE_METRICS
            }
            baselines.append(
                SegmentBaseline(segment_id=segment, **quantities)
            )
            for metric in _BASELINE_METRICS:
                item = inputs[f"forecast.baseline.{segment}.{metric}"]
                facts[item.fact_id] = _snapshot_fact(
                    item,
                    request.security_id,
                    scope="segment",
                    segment_id=segment,
                    metric_id=metric,
                )
        opening_quantities = {
            metric: _forecast_quantity(
                inputs[f"forecast.opening.{metric}"],
                as_of,
                fact=True,
            )
            for metric in _OPENING_METRICS
        }
        for metric in _OPENING_METRICS:
            item = inputs[f"forecast.opening.{metric}"]
            facts[item.fact_id] = _snapshot_fact(
                item,
                request.security_id,
                scope="company",
                segment_id="",
                metric_id=metric,
            )
        opening = CompanyOpeningBalanceSheet(**opening_quantities)

        for field in _BRIDGE_FIELDS:
            item = inputs[f"valuation.bridge.opening.{field}"]
            facts[item.fact_id] = _snapshot_fact(
                item,
                request.security_id,
                scope="company",
                segment_id="",
                metric_id=field,
            )
        enterprise = inputs["valuation.reverse.enterprise_value"]
        facts[enterprise.fact_id] = _snapshot_fact(
            enterprise,
            request.security_id,
            scope="company",
            segment_id="",
            metric_id="observed_enterprise_value",
        )
        snapshot = DataSnapshot(
            snapshot_id=evidence.data_snapshot_id,
            security_id=request.security_id,
            as_of=as_of,
            segment_baselines=tuple(baselines),
            company_opening_balance_sheet=opening,
            facts=tuple(facts.values()),
        )
        forecast = ForecastRequest(
            security=Security(
                security_id=request.security_id,
                company_name=str(inputs["forecast.company_name"].value),
                market="A-share",
                reporting_currency="CNY",
                archetype=archetype,
                segment_ids=segments,
            ),
            as_of=as_of,
            data_snapshot=snapshot,
            forecast_periods=periods,
            assumption_overrides=(),
            review_date=request.evaluation_plan.horizon.review_by,
        )
        scenarios = tuple(
            ScenarioDefinition(
                scenario_id=role.value,
                role=role,
                label=role.value.title(),
                mutually_exclusive_group=(
                    f"operating_outlook_{periods[-1]}"
                ),
                partition_basis=(
                    "Exact frozen driver assumptions partition stress, "
                    "base, and improvement."
                ),
                driver_overrides=tuple(
                    SegmentForecastOverride(
                        segment_id=segment,
                        period=period,
                        **{
                            metric: _decimal(
                                inputs[
                                    f"scenario.{role.value}.{period}."
                                    f"{segment}.{metric}"
                                ].value
                            )
                            for metric in _OVERRIDE_METRICS
                        },
                    )
                    for period in periods
                    for segment in segments
                ),
                probability_evidence=None,
                rationale_refs=(
                    "Assumption:scenario_partition:"
                    + canonical_hash(
                        {
                            "snapshot": evidence.data_snapshot_id,
                            "role": role.value,
                        }
                    )[:24],
                ),
            )
            for role in (
                ScenarioRole.STRESS,
                ScenarioRole.BASE,
                ScenarioRole.IMPROVEMENT,
            )
        )
        plan = self._valuation_plan(
            request,
            inputs,
            segments,
            periods[-1],
        )
        return DeterministicScenarioRequest(
            base_forecast_request=forecast,
            scenarios=scenarios,
            valuation_plan=plan,
        )

    def _valuation_plan(
        self,
        request: ResearchWorkflowRequest,
        inputs: Mapping[str, _Input],
        segments: tuple[str, ...],
        terminal_period: str,
    ) -> ValuationPlan:
        as_of = request.evaluation_plan.horizon.as_of
        opening_bridge = _bridge(
            inputs,
            "opening",
            EquityBridgeTiming.OPENING,
            as_of,
        )
        terminal_bridge = _bridge(
            inputs,
            "terminal",
            EquityBridgeTiming.TERMINAL,
            as_of,
        )
        discount = tuple(
            _forecast_quantity(
                inputs[f"valuation.dcf.discount_rate_{case}"],
                as_of,
                fact=False,
            )
            for case in ("low", "base", "high")
        )
        growth = tuple(
            _forecast_quantity(
                inputs[f"valuation.dcf.terminal_growth_{case}"],
                as_of,
                fact=False,
            )
            for case in ("low", "base", "high")
        )
        discount = (
            replace(
                discount[0],
                lineage_refs=tuple(
                    dict.fromkeys(
                        (*discount[1].lineage_refs, *discount[0].lineage_refs)
                    )
                ),
            ),
            discount[1],
            replace(
                discount[2],
                lineage_refs=tuple(
                    dict.fromkeys(
                        (*discount[1].lineage_refs, *discount[2].lineage_refs)
                    )
                ),
            ),
        )
        growth = (
            replace(
                growth[0],
                lineage_refs=tuple(
                    dict.fromkeys(
                        (*growth[1].lineage_refs, *growth[0].lineage_refs)
                    )
                ),
            ),
            growth[1],
            replace(
                growth[2],
                lineage_refs=tuple(
                    dict.fromkeys(
                        (*growth[1].lineage_refs, *growth[2].lineage_refs)
                    )
                ),
            ),
        )
        status = str(inputs["valuation.dcf.status"].value)
        if status not in {"allowed", "caution", "blocked"}:
            raise ValueError("DCF_GATE_INVALID")
        applicability = DcfApplicability.from_validated_gate(
            status=status,  # type: ignore[arg-type]
            reason=str(inputs["valuation.dcf.reason"].value),
            subject_id=request.security_id,
            as_of=as_of,
            evidence_refs=tuple(
                dict.fromkeys(
                    (
                        *discount[1].lineage_refs,
                        *growth[1].lineage_refs,
                    )
                )
            ),
            diagnostics=(),
            gated_wacc=discount[1] if status != "blocked" else None,
            gated_terminal_growth=(
                growth[1] if status != "blocked" else None
            ),
        )
        return ValuationPlan(
            present_value_bridge=opening_bridge,
            terminal_value_bridge=terminal_bridge,
            dcf=DcfValuationSpec(
                applicability=applicability,
                discount_rate_low=discount[0],
                discount_rate_base=discount[1],
                discount_rate_high=discount[2],
                terminal_growth_low=growth[0],
                terminal_growth_base=growth[1],
                terminal_growth_high=growth[2],
                minimum_explicit_periods=len(
                    _forecast_periods(request)
                ),
            ),
            sotp=SotpValuationSpec(
                components=tuple(
                    SotpComponentSpec(
                        segment_id=segment,
                        metric=str(
                            inputs[
                                f"valuation.sotp.{segment}.metric"
                            ].value
                        ),
                        multiple_low=_forecast_quantity(
                            inputs[
                                f"valuation.sotp.{segment}.multiple_low"
                            ],
                            as_of,
                            fact=False,
                        ),
                        multiple_base=_forecast_quantity(
                            inputs[
                                f"valuation.sotp.{segment}.multiple_base"
                            ],
                            as_of,
                            fact=False,
                        ),
                        multiple_high=_forecast_quantity(
                            inputs[
                                f"valuation.sotp.{segment}.multiple_high"
                            ],
                            as_of,
                            fact=False,
                        ),
                    )
                    for segment in segments
                )
            ),
            reverse_dcf=ReverseDcfSpec(
                current_enterprise_value=_financial_quantity(
                    inputs["valuation.reverse.enterprise_value"],
                    as_of,
                    kind="money",
                    fact=True,
                ),
                discount_rate=_forecast_quantity(
                    inputs["valuation.reverse.discount_rate"],
                    as_of,
                    fact=False,
                ),
            ),
            relative_methods=(),
        )

    def _simulation_request(
        self,
        request: ResearchWorkflowRequest,
        scenario_artifact_id: str,
        formula_version: str,
        low: FinancialQuantity,
        base: FinancialQuantity,
        high: FinancialQuantity,
        inputs: Mapping[str, _Input],
        observations: tuple[_Input, ...],
    ) -> ValuationSimulationRequest:
        values = tuple(_decimal(item.value) for item in observations)
        evidence_refs = tuple(
            item.member.normalized_version_id for item in observations
        )
        published_at = max(
            item.member.published_at for item in observations
        )
        available_at = max(
            item.member.available_at for item in observations
        )
        retrieved_at = max(
            item.member.retrieved_at for item in observations
        )
        calibration = CalibrationEvidence(
            sample_id="valuation_calibration_"
            + canonical_hash(
                {
                    "members": evidence_refs,
                    "values": values,
                }
            )[:24],
            observations=values,
            window_start=min(item.period for item in observations),
            window_end=max(item.period for item in observations),
            as_of=request.evaluation_plan.horizon.as_of,
            published_at=published_at,
            available_at=available_at,
            retrieved_at=retrieved_at,
            basis=(
                "Frozen historical per-share valuation-output calibration."
            ),
            evidence_refs=evidence_refs,
        )
        assumption_id = "per_share_valuation_output"
        distribution = CalibratedDistribution(
            assumption_id=assumption_id,
            family="empirical",
            parameters=(),
            reference_value=base.normalized_value,
            unit=base.unit,
            scale=Decimal("1"),
            currency=base.currency,
            hard_min=_decimal(inputs["simulation.hard_min"].value),
            hard_max=_decimal(inputs["simulation.hard_max"].value),
            calibration=calibration,
            user_override_identity=scenario_artifact_id,
        )
        dependency_calibration = DependencyCalibrationEvidence(
            sample_id=calibration.sample_id,
            observation_vectors=tuple((item,) for item in values),
            window_start=calibration.window_start,
            window_end=calibration.window_end,
            as_of=calibration.as_of,
            published_at=calibration.published_at,
            available_at=calibration.available_at,
            retrieved_at=calibration.retrieved_at,
            basis=calibration.basis,
            evidence_refs=calibration.evidence_refs,
        )
        identity = canonical_hash(
            {
                "scenario": scenario_artifact_id,
                "calibration": calibration.to_dict(),
                "policy": str(
                    inputs["simulation.policy_identity"].value
                ),
            }
        )
        return ValuationSimulationRequest(
            simulation_id=f"valuation_simulation_{identity[:24]}",
            security_id=request.security_id,
            as_of=request.evaluation_plan.horizon.as_of,
            valuation_source_identity=scenario_artifact_id,
            model_identity=self.IDENTITY,
            policy_identity=str(
                inputs["simulation.policy_identity"].value
            ),
            assumptions=(distribution,),
            dependency_model=DependencyModel(
                model_identity="single_output_dependency@1",
                assumption_ids=(assumption_id,),
                correlation_matrix=((Decimal("1"),),),
                calibration=dependency_calibration,
                calibration_tolerance=Decimal("0"),
                user_override_identity=None,
            ),
            valuation_model=AffineSimulationModel(
                formula_id="direct_calibrated_per_share_output@1",
                intercept=Decimal("0"),
                terms=(
                    SimulationTerm(
                        assumption_id=assumption_id,
                        coefficient=Decimal("1"),
                        coefficient_unit=f"{base.unit} per {base.unit}",
                    ),
                ),
                output_unit=base.unit,
                currency=base.currency,
                period=base.period,
                output_level="per_share_value",
                minimum_output=Decimal("0"),
                maximum_output=None,
            ),
            deterministic_fallback=DeterministicValueFallback(
                scenario_id="base",
                method_id="fcff_dcf",
                formula_version=formula_version,
                low=low.normalized_value,
                base=base.normalized_value,
                high=high.normalized_value,
                unit=base.unit,
                currency=base.currency,
                period=base.period,
                output_level="per_share_value",
            ),
            tail_threshold=_decimal(
                inputs["simulation.tail_threshold"].value
            ),
            budget=SimulationBudget(
                rng_algorithm=ValuationSimulationEngine.RNG_ALGORITHM,
                seed=int(identity[:16], 16),
                sample_budget=_integer(
                    inputs["simulation.sample_budget"].value
                ),
                batch_size=_integer(
                    inputs["simulation.batch_size"].value
                ),
                convergence_tolerance=_decimal(
                    inputs["simulation.convergence_tolerance"].value
                ),
                stable_batches_required=_integer(
                    inputs["simulation.stable_batches_required"].value
                ),
                maximum_invalid_path_rate=_decimal(
                    inputs[
                        "simulation.maximum_invalid_path_rate"
                    ].value
                ),
                minimum_tail_observations=_integer(
                    inputs["simulation.minimum_tail_observations"].value
                ),
            ),
        )


def _model_inputs(
    evidence: SnapshotEvidence,
    *,
    prefixes: tuple[str, ...],
) -> tuple[dict[str, _Input], bool, str | None]:
    result: dict[str, _Input] = {}
    duplicate = False
    failure_code: str | None = None
    for member in evidence.member_evidence:
        if member.dataset != "research_model_input":
            continue
        for field in member.extracted_fields:
            try:
                path = exact_model_path(field)
            except ValueError as error:
                failure_code = failure_code or str(error)
                continue
            if not any(path.startswith(prefix) for prefix in prefixes):
                continue
            field_failure = typed_model_field_failure(
                field,
                expected_subject_id=evidence.scope_id,
            )
            if field_failure is not None:
                failure_code = failure_code or field_failure
                continue
            if path in result:
                duplicate = True
                continue
            result[path] = _Input(
                path=path,
                value=field["value"],
                period=field["period"],
                unit=field["unit"],
                currency=field["currency"],
                member=member,
            )
    return result, duplicate, failure_code


def _source_ids(inputs: Mapping[str, _Input]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.member.normalized_version_id
            for item in inputs.values()
        )
    )


def _forecast_periods(
    request: ResearchWorkflowRequest,
) -> tuple[str, ...]:
    start = datetime.fromisoformat(
        request.evaluation_plan.horizon.as_of
    ).year + 1
    end = datetime.fromisoformat(
        request.evaluation_plan.horizon.forecast_end
    ).year
    return tuple(f"{year}E" for year in range(start, end + 1))


def _forecast_quantity(
    item: _Input,
    as_of: str,
    *,
    fact: bool,
) -> ForecastQuantity:
    return ForecastQuantity(
        value=_decimal(item.value),
        unit=item.unit,
        scale=Decimal("1"),
        currency=item.currency,
        period=item.period,
        as_of=as_of,
        lineage_refs=(
            item.fact_ref if fact else item.assumption_ref,
        ),
    )


def _snapshot_fact(
    item: _Input,
    security_id: str,
    *,
    scope: str,
    segment_id: str,
    metric_id: str,
) -> SnapshotFact:
    return SnapshotFact(
        fact_id=item.fact_id,
        subject_id=security_id,
        scope=scope,
        segment_id=segment_id,
        metric_id=metric_id,
        field_name=item.path,
        period=item.period,
        value=_decimal(item.value),
        unit=item.unit,
        currency=item.currency,
        source_id=item.member.normalized_version_id,
        available_at=item.member.available_at[:10],
        official=True,
    )


def _financial_quantity(
    item: _Input,
    as_of: str,
    *,
    kind: str,
    fact: bool,
) -> FinancialQuantity:
    return FinancialQuantity(
        value=_decimal(item.value),
        unit=item.unit,
        scale=Decimal("1"),
        currency=item.currency,
        period=item.period,
        as_of=as_of,
        provenance_refs=(
            item.fact_ref if fact else item.assumption_ref,
        ),
        kind=kind,  # type: ignore[arg-type]
    )


def _bridge(
    inputs: Mapping[str, _Input],
    name: str,
    timing: EquityBridgeTiming,
    as_of: str,
) -> EquityBridgeSpec:
    values = {
        field: inputs[f"valuation.bridge.{name}.{field}"]
        for field in _BRIDGE_FIELDS
    }
    fact = name == "opening"
    return EquityBridgeSpec(
        timing=timing,
        diluted_shares=_financial_quantity(
            values["diluted_shares"],
            as_of,
            kind="shares",
            fact=fact,
        ),
        lease_debt=_financial_quantity(
            values["lease_debt"],
            as_of,
            kind="money",
            fact=fact,
        ),
        preferred_stock=_financial_quantity(
            values["preferred_stock"],
            as_of,
            kind="money",
            fact=fact,
        ),
        minority_interest=_financial_quantity(
            values["minority_interest"],
            as_of,
            kind="money",
            fact=fact,
        ),
        pension_deficit=_financial_quantity(
            values["pension_deficit"],
            as_of,
            kind="money",
            fact=fact,
        ),
        associates_jv_value=_financial_quantity(
            values["associates_jv_value"],
            as_of,
            kind="money",
            fact=fact,
        ),
        non_operating_assets=_financial_quantity(
            values["non_operating_assets"],
            as_of,
            kind="money",
            fact=fact,
        ),
    )


def _decimal(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise InvalidOperation
    return result


def _integer(value: Any) -> int:
    result = _decimal(value)
    if result != result.to_integral_value():
        raise ValueError("INTEGER_REQUIRED")
    return int(result)


__all__ = [
    "FrozenFinancialModelCompiler",
    "FrozenModelCompilation",
    "FrozenSimulationCompilation",
]
