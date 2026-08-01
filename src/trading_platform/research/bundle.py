from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import math
from typing import Any, Mapping

from equity_research import (
    MarketPathEngine,
    MarketPathInvariantError,
    ResearchRun,
    SimulationInvariantError,
    ValuationSimulationEngine,
)
from equity_research.forecast import (
    CompanyArchetype,
    DataInsufficientForecastRequest,
    DataInsufficientSnapshot,
    ForecastEngine,
    ForecastGraph,
    ForecastInvariantError,
    Security,
)
from equity_research.scenario_valuation import (
    DataInsufficientScenarioRequest,
    DeterministicScenarioResult,
    ScenarioInvariantError,
    ScenarioValuationEngine,
)

from trading_platform.application.workflow_ledger import SnapshotEvidence
from trading_platform.domain.market import MarketBar
from trading_platform.domain.recent_trend import assess_recent_trend
from trading_platform.domain.research_bundle import (
    ResearchComponentResult,
    ResearchComponentStatus,
    ResearchEvaluationBundle,
    ResearchEvaluationOrigin,
)
from trading_platform.domain.research_evaluation import ResearchWorkflowRequest
from trading_platform.research.financial_model_inputs import (
    FrozenFinancialModelCompiler,
)
from trading_platform.research.market_path_inputs import (
    FrozenMarketPathCompiler,
)


@dataclass(frozen=True)
class ResearchBundleAssembler:
    """Owns typed local degradation across the complete research pipeline."""

    research_policy_identity: str
    estimation_policy_identity: str

    def assemble(
        self,
        *,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        research_run: ResearchRun,
        estimates: Mapping[str, object] | None,
    ) -> ResearchEvaluationBundle:
        member_ids = tuple(
            item.normalized_version_id for item in evidence.member_evidence
        )
        origin = ResearchEvaluationOrigin(
            data_snapshot_id=evidence.data_snapshot_id,
            source_policy_identity=evidence.source_policy_identity,
            snapshot_member_ids=member_ids,
            research_policy_identity=self.research_policy_identity,
            estimation_policy_identity=self.estimation_policy_identity,
        )
        model_compilation = FrozenFinancialModelCompiler().compile_scenarios(
            request=request,
            evidence=evidence,
        )
        scenario_result: DeterministicScenarioResult
        if model_compilation.scenario_request is not None:
            try:
                forecast_graph = ForecastEngine().build(
                    model_compilation.scenario_request.base_forecast_request
                )
            except ForecastInvariantError:
                forecast, forecast_graph = self._forecast(
                    request,
                    evidence,
                    research_run,
                )
                scenario_valuation, scenario_result = (
                    self._scenario_valuation(
                        request,
                        evidence,
                        forecast,
                        forecast_graph,
                        reason_codes=(
                            "RESEARCH_MODEL_ENGINE_INPUT_INVALID",
                        ),
                    )
                )
            else:
                forecast = ResearchComponentResult(
                    component="forecast",
                    status=ResearchComponentStatus.COMPLETE,
                    reason_codes=("FORECAST_COMPLETE",),
                    content=forecast_graph.to_dict(),
                    source_member_ids=model_compilation.source_member_ids,
                )
                try:
                    scenario_result = ScenarioValuationEngine().run(
                        model_compilation.scenario_request
                    )
                except (ForecastInvariantError, ScenarioInvariantError):
                    _, degraded_forecast_graph = self._forecast(
                        request,
                        evidence,
                        research_run,
                    )
                    scenario_valuation, scenario_result = (
                        self._scenario_valuation(
                            request,
                            evidence,
                            forecast,
                            degraded_forecast_graph,
                            reason_codes=(
                                "RESEARCH_MODEL_ENGINE_INPUT_INVALID",
                            ),
                        )
                    )
                else:
                    scenario_valuation = self._ready_scenario_valuation(
                        scenario_result,
                        model_compilation.source_member_ids,
                    )
        else:
            forecast, forecast_graph = self._forecast(
                request,
                evidence,
                research_run,
            )
            scenario_valuation, scenario_result = self._scenario_valuation(
                request,
                evidence,
                forecast,
                forecast_graph,
                reason_codes=(
                    model_compilation.missing_gates
                    or ("VALUATION_METHOD_INPUTS_INSUFFICIENT",)
                ),
            )
        valuation_route = self._valuation_method_route(
            research_run,
            member_ids,
            scenario_result=(
                scenario_result
                if model_compilation.scenario_request is not None
                else None
            ),
        )
        valuation_simulation = self._valuation_simulation_decision(
            request,
            evidence,
            scenario_valuation,
            scenario_result,
            member_ids,
        )
        bars = self._daily_bars(request, evidence)
        recent_trend = self._recent_trend(request, evidence, bars)
        market_path = self._market_path_decision(
            request,
            evidence,
            valuation_simulation.artifact_id,
        )
        return ResearchEvaluationBundle(
            origin=origin,
            estimates=estimates,
            research_run=_exact_payload(research_run.to_dict()),
            forecast=forecast,
            scenario_valuation=scenario_valuation,
            valuation_method_route=valuation_route,
            valuation_simulation_decision=valuation_simulation,
            market_path_decision=market_path,
            recent_trend_assessment=recent_trend,
        )

    @staticmethod
    def _forecast(
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        research_run: ResearchRun,
    ) -> tuple[ResearchComponentResult, ForecastGraph]:
        missing = tuple(
            dict.fromkeys(
                (
                    *(
                        str(item.get("field_name", "")).strip()
                        for item in research_run.declared_missing
                    ),
                    "typed_segment_driver_baselines",
                    "typed_forecast_assumptions",
                )
            )
        )
        forecast_periods = _forecast_periods(
            request.evaluation_plan.horizon.as_of,
            request.evaluation_plan.horizon.forecast_end,
        )
        graph = ForecastEngine().build(
            DataInsufficientForecastRequest(
                security=Security(
                    security_id=request.security_id,
                    company_name=str(
                        research_run.company.get(
                            "name",
                            request.security_id,
                        )
                    ),
                    market=str(research_run.company.get("market", "A-share")),
                    reporting_currency=str(
                        research_run.company.get(
                            "reporting_currency",
                            "CNY",
                        )
                    ),
                    archetype=CompanyArchetype.GENERAL_MANUFACTURING,
                    segment_ids=("company",),
                ),
                as_of=request.evaluation_plan.horizon.as_of,
                data_snapshot=DataInsufficientSnapshot(
                    snapshot_id=evidence.data_snapshot_id,
                    security_id=request.security_id,
                    as_of=request.evaluation_plan.horizon.as_of,
                    missing_fields=missing,
                ),
                forecast_periods=forecast_periods,
                review_date=request.evaluation_plan.horizon.review_by,
            )
        )
        return (
            ResearchComponentResult(
                component="forecast",
                status=ResearchComponentStatus.BLOCKED,
                reason_codes=("FORECAST_TYPED_INPUTS_INSUFFICIENT",),
                content=graph.to_dict(),
                source_member_ids=tuple(
                    item.normalized_version_id
                    for item in evidence.member_evidence
                ),
            ),
            graph,
        )

    @staticmethod
    def _scenario_valuation(
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        forecast: ResearchComponentResult,
        forecast_graph: ForecastGraph,
        *,
        reason_codes: tuple[str, ...] = (
            "VALUATION_METHOD_INPUTS_INSUFFICIENT",
        ),
    ) -> tuple[ResearchComponentResult, DeterministicScenarioResult]:
        result = ScenarioValuationEngine().run(
            DataInsufficientScenarioRequest(
                forecast_graph,
                _forecast_periods(
                    request.evaluation_plan.horizon.as_of,
                    request.evaluation_plan.horizon.forecast_end,
                )[-1],
            )
        )
        return (
            ResearchComponentResult(
                component="scenario_valuation",
                status=ResearchComponentStatus.BLOCKED,
                reason_codes=reason_codes,
                content=result.to_dict(),
                source_member_ids=forecast.source_member_ids,
            ),
            result,
        )

    @staticmethod
    def _ready_scenario_valuation(
        result: DeterministicScenarioResult,
        member_ids: tuple[str, ...],
    ) -> ResearchComponentResult:
        statuses = tuple(
            method.status
            for scenario in result.scenarios
            for method in scenario.methods
        )
        if statuses and all(status == "ready" for status in statuses):
            status = ResearchComponentStatus.COMPLETE
            reason = "SCENARIO_VALUATION_COMPLETE"
        elif any(status == "ready" for status in statuses):
            status = ResearchComponentStatus.LIMITED
            reason = "SCENARIO_VALUATION_PARTIAL"
        else:
            status = ResearchComponentStatus.BLOCKED
            reason = "VALUATION_METHOD_NOT_APPLICABLE"
        return ResearchComponentResult(
            component="scenario_valuation",
            status=status,
            reason_codes=(reason,),
            content=result.to_dict(),
            source_member_ids=member_ids,
        )

    @staticmethod
    def _valuation_method_route(
        research_run: ResearchRun,
        member_ids: tuple[str, ...],
        *,
        scenario_result: DeterministicScenarioResult | None,
    ) -> ResearchComponentResult:
        if scenario_result is not None:
            methods = _exact_payload(
                {
                    scenario.role.value: {
                        method.method_id: method.to_dict()
                        for method in scenario.methods
                    }
                    for scenario in scenario_result.scenarios
                }
            )
            ready = tuple(
                dict.fromkeys(
                    method.method_id
                    for scenario in scenario_result.scenarios
                    for method in scenario.methods
                    if method.status == "ready"
                )
            )
            formal_per_share = any(
                method.status == "ready"
                and method.conditional_value_range is not None
                and method.conditional_value_range.base.per_share_value
                is not None
                for scenario in scenario_result.scenarios
                for method in scenario.methods
            )
        else:
            methods = _exact_payload(
                {
                    method_id: result.to_dict()
                    for method_id, result in research_run.methods.items()
                }
            )
            ready = tuple(
                method_id
                for method_id, result in research_run.methods.items()
                if result.status == "ready"
            )
            formal_per_share = bool(
                research_run.permissions.get(
                    "formal_per_share_valuation",
                    False,
                )
            )
        status = (
            ResearchComponentStatus.COMPLETE
            if ready
            else ResearchComponentStatus.BLOCKED
        )
        return ResearchComponentResult(
            component="valuation_method_route",
            status=status,
            reason_codes=(
                ("VALUATION_METHOD_ROUTE_COMPLETE",)
                if ready
                else ("VALUATION_METHOD_NOT_APPLICABLE",)
            ),
            content={
                "schema_version": "ValuationMethodRoute@1",
                "ready_method_ids": list(ready),
                "methods": methods,
                "formal_per_share_valuation": formal_per_share,
            },
            source_member_ids=member_ids,
        )

    @staticmethod
    def _valuation_simulation_decision(
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        scenario_valuation: ResearchComponentResult,
        scenario_result: DeterministicScenarioResult,
        member_ids: tuple[str, ...],
    ) -> ResearchComponentResult:
        compiled = FrozenFinancialModelCompiler().compile_simulation(
            request=request,
            evidence=evidence,
            scenario_result=scenario_result,
            scenario_artifact_id=scenario_valuation.artifact_id,
        )
        if compiled.request is None:
            reasons = compiled.missing_gates or (
                "VALUATION_SIMULATION_INPUTS_UNAVAILABLE",
            )
            return ResearchComponentResult(
                component="valuation_simulation_decision",
                status=ResearchComponentStatus.NOT_RUN,
                reason_codes=reasons,
                content={
                    "schema_version": "ValuationSimulationDecision@1",
                    "status": "not_run",
                    "reason_code": reasons[0],
                    "missing_gates": list(reasons),
                    "scenario_valuation_artifact_id": (
                        scenario_valuation.artifact_id
                    ),
                    "result": None,
                    "interpretation": (
                        "Intrinsic-value uncertainty simulation is distinct "
                        "from market-price paths and is not a target price."
                    ),
                },
                source_member_ids=(
                    compiled.source_member_ids or member_ids
                ),
            )
        try:
            result = ValuationSimulationEngine().run(compiled.request)
        except SimulationInvariantError as error:
            return ResearchComponentResult(
                component="valuation_simulation_decision",
                status=ResearchComponentStatus.BLOCKED,
                reason_codes=(error.code,),
                content={
                    "schema_version": "ValuationSimulationDecision@1",
                    "status": "blocked",
                    "reason_code": error.code,
                    "missing_gates": [],
                    "scenario_valuation_artifact_id": (
                        scenario_valuation.artifact_id
                    ),
                    "result": None,
                    "interpretation": (
                        "Intrinsic-value uncertainty simulation is distinct "
                        "from market-price paths and is not a target price."
                    ),
                },
                source_member_ids=compiled.source_member_ids,
            )
        status = (
            ResearchComponentStatus.COMPLETE
            if result.status == "ready"
            else ResearchComponentStatus.LIMITED
        )
        reason = (
            "VALUATION_SIMULATION_COMPLETE"
            if result.status == "ready"
            else "VALUATION_SIMULATION_PARTIAL"
        )
        return ResearchComponentResult(
            component="valuation_simulation_decision",
            status=status,
            reason_codes=(reason,),
            content={
                "schema_version": "ValuationSimulationDecision@1",
                "status": result.status,
                "reason_code": reason,
                "missing_gates": [],
                "scenario_valuation_artifact_id": (
                    scenario_valuation.artifact_id
                ),
                "result": result.to_dict(),
                "interpretation": (
                    "Intrinsic-value uncertainty simulation is distinct "
                    "from market-price paths and is not a target price."
                ),
            },
            source_member_ids=compiled.source_member_ids,
        )

    @staticmethod
    def _market_path_decision(
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        valuation_simulation_decision_id: str,
    ) -> ResearchComponentResult:
        compiled = FrozenMarketPathCompiler().compile(
            request=request,
            evidence=evidence,
            valuation_simulation_decision_id=(
                valuation_simulation_decision_id
            ),
        )
        if compiled.request is None:
            reasons = compiled.missing_gates or (
                "MARKET_PATH_INPUTS_UNAVAILABLE",
            )
            return ResearchComponentResult(
                component="market_path_decision",
                status=ResearchComponentStatus.NOT_RUN,
                reason_codes=reasons,
                content={
                    "schema_version": "MarketPathDecision@1",
                    "status": "not_run",
                    "reason_code": reasons[0],
                    "missing_gates": list(reasons),
                    "result": None,
                    "interpretation": (
                        "Market-price path risk is not intrinsic value, a "
                        "target price, or a trading instruction."
                    ),
                },
                source_member_ids=compiled.source_member_ids,
            )
        try:
            result = MarketPathEngine().run(compiled.request)
        except MarketPathInvariantError as error:
            return ResearchComponentResult(
                component="market_path_decision",
                status=ResearchComponentStatus.BLOCKED,
                reason_codes=(error.code,),
                content={
                    "schema_version": "MarketPathDecision@1",
                    "status": "blocked",
                    "reason_code": error.code,
                    "missing_gates": [],
                    "result": None,
                    "interpretation": MarketPathEngine.INTERPRETATION,
                },
                source_member_ids=compiled.source_member_ids,
            )
        status = (
            ResearchComponentStatus.COMPLETE
            if result.status == "ready"
            else ResearchComponentStatus.LIMITED
        )
        reason = (
            "MARKET_PATH_COMPLETE"
            if result.status == "ready"
            else "MARKET_PATH_PARTIAL"
        )
        return ResearchComponentResult(
            component="market_path_decision",
            status=status,
            reason_codes=(reason,),
            content={
                "schema_version": "MarketPathDecision@1",
                "status": result.status,
                "reason_code": reason,
                "missing_gates": [],
                "result": result.to_dict(),
                "interpretation": result.interpretation,
            },
            source_member_ids=compiled.source_member_ids,
        )

    @staticmethod
    def _recent_trend(
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        bars: tuple[MarketBar, ...],
    ) -> ResearchComponentResult:
        assessment = assess_recent_trend(
            security_id=request.security_id,
            data_snapshot_id=evidence.data_snapshot_id,
            as_of_session=request.effective_session_date,
            bars=bars,
        )
        return ResearchComponentResult(
            component="recent_trend_assessment",
            status=(
                ResearchComponentStatus.COMPLETE
                if assessment.status == "complete"
                else ResearchComponentStatus.BLOCKED
            ),
            reason_codes=(
                ("RECENT_TREND_COMPLETE",)
                if assessment.status == "complete"
                else assessment.reason_codes
            ),
            content=_recent_trend_mapping(assessment),
            source_member_ids=assessment.evidence_refs,
        )

    @staticmethod
    def _daily_bars(
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
    ) -> tuple[MarketBar, ...]:
        bars: dict[str, MarketBar] = {}
        for member in evidence.member_evidence:
            if member.dataset != "daily":
                continue
            for field in member.extracted_fields:
                if str(field.get("field_name", "")) != "current_price":
                    continue
                period = str(field.get("period", "")).strip()
                try:
                    close = Decimal(str(field.get("value", "")))
                    date.fromisoformat(period)
                except (InvalidOperation, ValueError):
                    continue
                if not close.is_finite() or close <= 0:
                    continue
                bars[period] = MarketBar(
                    security_id=request.security_id,
                    session_date=period,
                    close=close,
                    amount=None,
                    normalized_version_id=member.normalized_version_id,
                )
        return tuple(bars[key] for key in sorted(bars))


def _forecast_periods(as_of: str, forecast_end: str) -> tuple[str, ...]:
    first_year = date.fromisoformat(as_of).year + 1
    final_year = date.fromisoformat(forecast_end).year
    if final_year < first_year:
        first_year = final_year
    return tuple(
        f"{year}E" for year in range(first_year, final_year + 1)
    )


def _recent_trend_mapping(assessment: object) -> Mapping[str, object]:
    values = dict(getattr(assessment, "canonical_content"))
    for key in (
        "close",
        "sma20",
        "sma60",
        "sma20_five_sessions_prior",
        "window_low_20",
    ):
        value = values[key]
        values[key] = (
            format(value.normalize(), "f")
            if isinstance(value, Decimal)
            else None
        )
    values["evidence_refs"] = list(values["evidence_refs"])
    values["reason_codes"] = list(values["reason_codes"])
    return {
        "assessment_id": getattr(assessment, "assessment_id"),
        **values,
        "content_hash": getattr(assessment, "content_hash"),
    }


def _exact_payload(value: Any) -> Any:
    """Remove binary-float ambiguity at the formal artifact boundary."""

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("RESEARCH_BUNDLE_NUMBER_INVALID")
        rendered = format(Decimal(repr(value)).normalize(), "f")
        return "0" if rendered == "-0" else rendered
    if isinstance(value, Mapping):
        return {
            str(key): _exact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_exact_payload(item) for item in value]
    return value


__all__ = ["ResearchBundleAssembler"]
