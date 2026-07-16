from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from trading_platform.domain.workflow import ResearchArtifactView
from trading_platform.identity import canonical_hash


class ResearchViewError(ValueError):
    pass


@dataclass(frozen=True)
class ResearchDecisionView:
    schema_version: str
    view_id: str
    workflow_run_id: str
    research_run_id: str
    data_snapshot_id: str
    model_data_snapshot_identity: str
    valuation_artifact_record_id: str
    simulation_artifact_record_id: str | None
    market_path_artifact_record_id: str | None
    subject_id: str
    as_of: str
    model_identity: str
    policy_identity: str
    status: str
    story: Mapping[str, Any]
    key_drivers: tuple[Mapping[str, Any], ...]
    scenarios: tuple[Mapping[str, Any], ...]
    market_implied_expectations: tuple[Mapping[str, Any], ...]
    valuation_simulation: Mapping[str, Any] | None
    market_price_paths: Mapping[str, Any] | None
    value_market_divergence: Mapping[str, Any] | None
    audit: Mapping[str, Any]
    boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchDecisionViewBuilder:
    SCHEMA_VERSION = "ResearchDecisionView@2"
    SCENARIO_LABELS = {
        "stress": "压力",
        "base": "基准",
        "improvement": "改善",
    }
    DRIVER_SUFFIXES = (
        ".volume.",
        ".asp.",
        ".utilization.",
        ".unit_cost.",
        ".capacity.",
    )
    FINANCIAL_IDS = (
        "company.revenue",
        "company.ebit",
        "company.fcff",
    )

    def build(
        self,
        *,
        workflow_run_id: str,
        data_snapshot: ResearchArtifactView,
        forecast: ResearchArtifactView,
        valuation: ResearchArtifactView,
        simulation: ResearchArtifactView | None = None,
        market_data_snapshot: ResearchArtifactView | None = None,
        market_path: ResearchArtifactView | None = None,
        research_run_payload: Mapping[str, Any],
    ) -> ResearchDecisionView:
        self._validate_artifacts(
            data_snapshot,
            forecast,
            valuation,
            simulation,
            market_data_snapshot,
            market_path,
            research_run_payload,
        )
        scenario_payloads = valuation.payload.get("scenarios")
        if not isinstance(scenario_payloads, list) or not scenario_payloads:
            raise ResearchViewError("RESEARCH_VIEW_SCENARIOS_MISSING")
        scenarios_with_expectations = tuple(
            self._scenario(item) for item in scenario_payloads
        )
        by_role = {item["role"]: item for item in scenarios_with_expectations}
        if set(by_role) != set(self.SCENARIO_LABELS):
            raise ResearchViewError("RESEARCH_VIEW_SCENARIO_PARTITION_INVALID")
        key_drivers = tuple(by_role["base"]["drivers"])
        market_implied = tuple(
            expectation
            for item in scenarios_with_expectations
            for expectation in item["market_implied_expectations"]
        )
        scenarios = tuple(
            {
                key: value
                for key, value in item.items()
                if key != "market_implied_expectations"
            }
            for item in scenarios_with_expectations
        )
        story = self._story(by_role, forecast.payload)
        artifact_records = tuple(
            {
                "artifact_record_id": item.artifact_record_id,
                "artifact_kind": item.artifact_kind,
                "schema_version": item.schema_version,
                "content_hash": item.content_hash,
                "source_identity": item.source_identity,
                "status": item.status,
            }
            for item in (
                data_snapshot,
                forecast,
                valuation,
                simulation,
                market_data_snapshot,
                market_path,
            )
            if item is not None
        )
        fact_evidence = tuple(
            {
                key: fact.get(key)
                for key in (
                    "fact_id",
                    "subject_id",
                    "metric_id",
                    "field_name",
                    "period",
                    "value",
                    "unit",
                    "currency",
                    "source_id",
                    "available_at",
                    "official",
                )
            }
            for fact in data_snapshot.payload.get("facts", ())
            if isinstance(fact, Mapping)
        )
        parameters = tuple(
            {
                "scenario_id": scenario.get("scenario_id"),
                "method_id": method.get("method_id"),
                "assumptions": method.get("assumptions", ()),
                "sensitivity": method.get("sensitivity", ()),
            }
            for scenario in scenario_payloads
            if isinstance(scenario, Mapping)
            for method in scenario.get("methods", ())
            if isinstance(method, Mapping)
        )
        diagnostics = tuple(
            str(item)
            for item in valuation.payload.get("weighting_diagnostics", ())
        ) + tuple(
            str(diagnostic)
            for scenario in scenario_payloads
            if isinstance(scenario, Mapping)
            for method in scenario.get("methods", ())
            if isinstance(method, Mapping)
            for diagnostic in method.get("diagnostics", ())
        ) + tuple(
            str(item)
            for item in (
                simulation.payload.get("diagnostics", ())
                if simulation is not None
                else ()
            )
        ) + tuple(
            str(item)
            for item in (
                market_path.payload.get("diagnostics", ())
                if market_path is not None
                else ()
            )
        )
        simulation_view = (
            self._simulation(simulation.payload) if simulation is not None else None
        )
        market_path_view = (
            self._market_path(market_path.payload)
            if market_path is not None
            else None
        )
        divergence_view = self._value_market_divergence(
            simulation_view,
            market_path_view,
        )
        view_id = "research_view_" + canonical_hash(
            {
                "schema": self.SCHEMA_VERSION,
                "workflow_run_id": workflow_run_id,
                "artifacts": [item["content_hash"] for item in artifact_records],
            }
        )[:24]
        return ResearchDecisionView(
            schema_version=self.SCHEMA_VERSION,
            view_id=view_id,
            workflow_run_id=workflow_run_id,
            research_run_id=valuation.research_run_id,
            data_snapshot_id=valuation.data_snapshot_id,
            model_data_snapshot_identity=valuation.model_data_snapshot_identity,
            valuation_artifact_record_id=valuation.artifact_record_id,
            simulation_artifact_record_id=(
                simulation.artifact_record_id if simulation is not None else None
            ),
            market_path_artifact_record_id=(
                market_path.artifact_record_id if market_path is not None else None
            ),
            subject_id=valuation.subject_id,
            as_of=valuation.as_of,
            model_identity=valuation.model_identity,
            policy_identity=valuation.policy_identity,
            status=valuation.status,
            story=story,
            key_drivers=key_drivers,
            scenarios=scenarios,
            market_implied_expectations=market_implied,
            valuation_simulation=simulation_view,
            market_price_paths=market_path_view,
            value_market_divergence=divergence_view,
            audit={
                "artifact_records": artifact_records,
                "sources": tuple(
                    research_run_payload.get("sources", ())
                    or (
                        research_run_payload.get("audit", {}).get(
                            "sources",
                            (),
                        )
                        if isinstance(
                            research_run_payload.get("audit"),
                            Mapping,
                        )
                        else ()
                    )
                ),
                "fact_evidence": fact_evidence,
                "formula_identities": tuple(
                    sorted(
                        {
                            formula
                            for item in (
                                data_snapshot,
                                forecast,
                                valuation,
                                simulation,
                                market_data_snapshot,
                                market_path,
                            )
                            if item is not None
                            for formula in item.formula_identities
                        }
                    )
                ),
                "parameters": parameters,
                "diagnostics": diagnostics,
                "versions": {
                    "research_schema": research_run_payload.get(
                        "schema_version"
                    ),
                    "model_identity": valuation.model_identity,
                    "policy_identity": valuation.policy_identity,
                    "code_identity": valuation.code_identity,
                },
            },
            boundary="条件研究结果用于理解未来路径与不确定性，不构成个性化投资建议。",
        )

    def _validate_artifacts(
        self,
        data_snapshot: ResearchArtifactView,
        forecast: ResearchArtifactView,
        valuation: ResearchArtifactView,
        simulation: ResearchArtifactView | None,
        market_data_snapshot: ResearchArtifactView | None,
        market_path: ResearchArtifactView | None,
        research_run_payload: Mapping[str, Any],
    ) -> None:
        if (
            (data_snapshot.artifact_kind, forecast.artifact_kind, valuation.artifact_kind)
            != ("DataSnapshot", "Forecast", "Valuation")
            or forecast.dependency_record_ids != (data_snapshot.artifact_record_id,)
            or valuation.dependency_record_ids != (forecast.artifact_record_id,)
        ):
            raise ResearchViewError("RESEARCH_VIEW_ARTIFACT_GRAPH_INVALID")
        if simulation is not None and (
            simulation.artifact_kind != "Simulation"
            or simulation.dependency_record_ids
            != (valuation.artifact_record_id,)
            or simulation.payload.get("valuation_source_identity")
            != valuation.source_identity
        ):
            raise ResearchViewError("RESEARCH_VIEW_SIMULATION_GRAPH_INVALID")
        if market_path is not None and (
            simulation is None
            or market_data_snapshot is None
            or market_path.artifact_kind != "MarketPathSimulation"
            or set(market_path.dependency_record_ids)
            != {
                simulation.artifact_record_id,
                market_data_snapshot.artifact_record_id,
            }
            or market_path.payload.get("valuation_simulation_source_identity")
            != simulation.source_identity
            or market_path.payload.get("calibration")
            != market_data_snapshot.payload
        ):
            raise ResearchViewError("RESEARCH_VIEW_MARKET_PATH_GRAPH_INVALID")
        if market_data_snapshot is not None and (
            market_data_snapshot.artifact_kind != "MarketDataSnapshot"
            or market_data_snapshot.dependency_record_ids
        ):
            raise ResearchViewError("RESEARCH_VIEW_MARKET_DATA_GRAPH_INVALID")
        identities = {
            (
                item.research_run_id,
                item.data_snapshot_id,
                item.model_data_snapshot_identity,
                item.platform_security_id,
                item.subject_id,
                item.as_of,
                item.model_identity,
                item.policy_identity,
                item.code_identity,
            )
            for item in (
                data_snapshot,
                forecast,
                valuation,
                simulation,
                market_data_snapshot,
                market_path,
            )
            if item is not None
        }
        payload_run_id = (
            research_run_payload.get("research_run_id")
            if str(research_run_payload.get("schema_version", "")).startswith(
                "ResearchDecisionView@"
            )
            else research_run_payload.get("run_id")
        )
        if len(identities) != 1 or payload_run_id != valuation.research_run_id:
            raise ResearchViewError("RESEARCH_VIEW_IDENTITY_MISMATCH")

    @staticmethod
    def _simulation(value: Mapping[str, Any]) -> dict[str, Any]:
        model = value.get("valuation_model")
        budget = value.get("budget")
        if not isinstance(model, Mapping) or not isinstance(budget, Mapping):
            raise ResearchViewError("RESEARCH_VIEW_SIMULATION_INVALID")
        unit = model.get("output_unit")
        currency = model.get("currency")
        period = model.get("period")

        def quantity(raw: object) -> dict[str, Any]:
            return {
                "value": raw,
                "unit": unit,
                "currency": currency,
                "period": period,
            }

        raw_quantiles = value.get("quantiles")
        quantiles = (
            {
                key: quantity(raw_quantiles.get(key))
                for key in ("p5", "p25", "p50", "p75", "p95")
            }
            if isinstance(raw_quantiles, Mapping)
            else None
        )
        tail = value.get("tail_results")
        tail_view = (
            {
                "threshold": quantity(tail.get("threshold")),
                "probability_below_threshold": {
                    "value": tail.get("probability_below_threshold"),
                    "unit": "decimal",
                },
                "conditional_tail_mean": quantity(
                    tail.get("conditional_tail_mean")
                ),
            }
            if isinstance(tail, Mapping)
            else None
        )
        return {
            "status": value.get("status"),
            "converged": value.get("converged"),
            "quantiles": quantiles,
            "tail_results": tail_view,
            "contributions": tuple(value.get("contributions", ())),
            "assumptions": tuple(value.get("assumptions", ())),
            "dependency_model": value.get("dependency_model"),
            "rng_algorithm": budget.get("rng_algorithm"),
            "seed": budget.get("seed"),
            "sample_budget": budget.get("sample_budget"),
            "completed_samples": value.get("completed_samples"),
            "batch_size": budget.get("batch_size"),
            "invalid_path_rate": value.get("invalid_path_rate"),
            "convergence_tolerance": budget.get("convergence_tolerance"),
            "stable_batches_required": budget.get("stable_batches_required"),
            "stable_batches": value.get("stable_batches"),
            "constraint_path": tuple(value.get("constraint_path", ())),
            "deterministic_fallback": value.get("deterministic_fallback"),
            "diagnostics": tuple(value.get("diagnostics", ())),
        }

    @staticmethod
    def _market_path(value: Mapping[str, Any]) -> dict[str, Any]:
        def quantity(
            raw: object,
            unit: str,
            period: object,
        ) -> dict[str, Any]:
            return {
                "value": raw,
                "unit": unit,
                "currency": value.get("currency") if unit != "decimal" else None,
                "period": period,
            }

        def quantiles(
            name: str,
            unit: str,
            period: object,
        ) -> dict[str, Any] | None:
            raw = value.get(name)
            return (
                {
                    key: quantity(raw.get(key), unit, period)
                    for key in ("p5", "p25", "p50", "p75", "p95")
                }
                if isinstance(raw, Mapping)
                else None
            )

        return {
            "status": value.get("status"),
            "interpretation": value.get("interpretation"),
            "starting_price": quantity(
                value.get("starting_price"),
                str(value.get("price_unit")),
                value.get("starting_price_session"),
            ),
            "starting_price_session": value.get("starting_price_session"),
            "starting_price_member_id": value.get("starting_price_member_id"),
            "starting_price_available_at": value.get(
                "starting_price_available_at"
            ),
            "starting_price_evidence_refs": tuple(
                value.get("starting_price_evidence_refs", ())
            ),
            "current_market_state": value.get("current_market_state"),
            "current_state_available_at": value.get(
                "current_state_available_at"
            ),
            "current_state_evidence_refs": tuple(
                value.get("current_state_evidence_refs", ())
            ),
            "terminal_price_quantiles": quantiles(
                "terminal_price_quantiles",
                str(value.get("price_unit")),
                value.get("terminal_period"),
            ),
            "horizon_return_quantiles": quantiles(
                "horizon_return_quantiles",
                "decimal",
                value.get("risk_horizon_period"),
            ),
            "maximum_drawdown_quantiles": quantiles(
                "maximum_drawdown_quantiles",
                "decimal",
                value.get("risk_horizon_period"),
            ),
            "threshold_trigger_probabilities": tuple(
                value.get("threshold_trigger_probabilities", ())
            ),
            "tail_results": value.get("tail_results"),
            "price_unit": value.get("price_unit"),
            "currency": value.get("currency"),
            "horizon_return_basis": value.get("horizon_return_basis"),
            "execution_period": value.get("execution_period"),
            "terminal_period": value.get("terminal_period"),
            "risk_horizon_period": value.get("risk_horizon_period"),
            "calibration": value.get("calibration"),
            "constraints": value.get("constraints"),
            "budget": value.get("budget"),
            "completed_paths": value.get("completed_paths"),
            "diagnostics": tuple(value.get("diagnostics", ())),
        }

    @staticmethod
    def _value_market_divergence(
        valuation_simulation: Mapping[str, Any] | None,
        market_path: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if valuation_simulation is None or market_path is None:
            return None
        valuation_quantiles = valuation_simulation.get("quantiles")
        market_quantiles = market_path.get("terminal_price_quantiles")
        if not isinstance(valuation_quantiles, Mapping) or not isinstance(
            market_quantiles,
            Mapping,
        ):
            return {
                "status": "limited",
                "explanation": (
                    "价值分布或市场路径分布受限，当前不比较两者中位数。"
                ),
            }
        valuation_p50 = valuation_quantiles.get("p50")
        market_p50 = market_quantiles.get("p50")
        if not isinstance(valuation_p50, Mapping) or not isinstance(
            market_p50,
            Mapping,
        ):
            return None
        dimensions = (
            valuation_p50.get("unit"),
            valuation_p50.get("currency"),
        )
        if dimensions != (
            market_p50.get("unit"),
            market_p50.get("currency"),
        ):
            return {
                "status": "not_comparable",
                "explanation": (
                    "价值分布与市场路径的单位或币种不同；未提供冻结汇率转换，"
                    "因此禁止计算两者背离。"
                ),
            }
        if valuation_p50.get("period") != market_p50.get("period"):
            return {
                "status": "not_comparable_horizon",
                "valuation_p50": valuation_p50,
                "market_path_p50": market_p50,
                "explanation": (
                    "基本面价值分布与市场路径终点的期限不同，禁止直接计算数值背离。"
                    "两者仍可并列理解不同机制下的不确定性，但不是目标价或交易动作。"
                ),
            }
        try:
            value = Decimal(str(valuation_p50.get("value")))
            price = Decimal(str(market_p50.get("value")))
        except (InvalidOperation, ValueError):
            return None
        direction = "高于" if price > value else "低于" if price < value else "接近"
        return {
            "status": "comparable_with_limits",
            "valuation_p50": valuation_p50,
            "market_path_p50": market_p50,
            "difference": {
                "value": str(price - value),
                "unit": valuation_p50.get("unit"),
                "currency": valuation_p50.get("currency"),
            },
            "explanation": (
                f"市场路径中位终点{direction}基本面价值分布中位数。"
                "两者来自不同机制和期限：前者描述状态条件下的交易价格，"
                "后者描述经营与估值假设下的条件价值；背离不是目标价或交易动作。"
            ),
        }

    def _scenario(self, value: Mapping[str, Any]) -> dict[str, Any]:
        role = str(value.get("role", ""))
        graph = value.get("forecast_graph")
        methods = value.get("methods")
        if role not in self.SCENARIO_LABELS or not isinstance(graph, Mapping) or not isinstance(methods, list):
            raise ResearchViewError("RESEARCH_VIEW_SCENARIO_INVALID")
        terminal_period = self._terminal_period(graph)
        drivers = tuple(
            self._node_metric(node)
            for node in graph.get("nodes", ())
            if isinstance(node, Mapping)
            and node.get("kind") == "Driver"
            and node.get("origin") == "derived"
            and isinstance(node.get("node_id"), str)
            and any(suffix in node["node_id"] for suffix in self.DRIVER_SUFFIXES)
            and self._node_period(node) == terminal_period
        )[:6]
        financials = tuple(
            self._node_metric(node, metric_id=metric_id)
            for metric_id in self.FINANCIAL_IDS
            for node in graph.get("nodes", ())
            if isinstance(node, Mapping)
            and node.get("node_id") == f"{metric_id}.{terminal_period}"
        )
        method_views = tuple(self._method(method) for method in methods if isinstance(method, Mapping))
        implied = tuple(
            {
                "scenario_role": role,
                "scenario_label": self.SCENARIO_LABELS[role],
                "metric_id": sensitivity.get("name"),
                "low": self._quantity(sensitivity.get("low")),
                "base": self._quantity(sensitivity.get("base")),
                "high": self._quantity(sensitivity.get("high")),
                "explanation": "当前观察到的企业价值需要该经营情景与隐含终值增长共同成立。",
            }
            for method in methods
            if isinstance(method, Mapping) and method.get("method_id") == "reverse_dcf"
            for sensitivity in method.get("sensitivity", ())
            if isinstance(sensitivity, Mapping)
            and sensitivity.get("name") == "implied_terminal_growth"
        )
        return {
            "scenario_id": value.get("scenario_id"),
            "role": role,
            "label": self.SCENARIO_LABELS[role],
            "terminal_period": terminal_period,
            "rationale_refs": tuple(value.get("rationale_refs", ())),
            "drivers": drivers,
            "financials": financials,
            "methods": method_views,
            "market_implied_expectations": implied,
        }

    def _method(self, value: Mapping[str, Any]) -> dict[str, Any]:
        conditional = value.get("conditional_value_range")
        diagnostics = tuple(str(item) for item in value.get("diagnostics", ()))
        reconciliation = (
            {
                point: self._valuation_point(conditional.get(point))
                for point in ("low", "base", "high")
            }
            if isinstance(conditional, Mapping)
            else None
        )
        return {
            "method_id": value.get("method_id"),
            "status": value.get("status"),
            "applicability": value.get("applicability"),
            "display_applicability": self._applicability_text(
                str(value.get("applicability", ""))
            ),
            "value_basis": value.get("value_basis"),
            "horizon": value.get("horizon"),
            "formula_version": value.get("formula_version"),
            "conditional_per_share_range": (
                {
                    point: self._quantity(conditional.get(point, {}).get("per_share_value"))
                    for point in ("low", "base", "high")
                }
                if isinstance(conditional, Mapping)
                else None
            ),
            "reconciliation": reconciliation,
            "diagnostics": diagnostics,
            "display_diagnostics": tuple(
                self._diagnostic_text(item) for item in diagnostics
            ),
        }

    def _valuation_point(self, value: object) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        return {
            "basis_value": self._quantity(value.get("basis_value")),
            "equity_value": self._quantity(value.get("equity_value")),
            "per_share_value": self._quantity(value.get("per_share_value")),
            "bridge_trace": tuple(
                {
                    "operation": str(item.get("operation", "")),
                    "amount": item.get("amount"),
                    "ref_ids": tuple(str(ref) for ref in item.get("ref_ids", ())),
                }
                for item in value.get("bridge_trace", ())
                if isinstance(item, Mapping)
            ),
        }

    def _story(
        self,
        by_role: Mapping[str, Mapping[str, Any]],
        forecast_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        stress_revenue = self._financial_value(by_role["stress"], "company.revenue")
        base_revenue = self._financial_value(by_role["base"], "company.revenue")
        improvement_revenue = self._financial_value(by_role["improvement"], "company.revenue")
        period = by_role["base"]["terminal_period"]
        event_labels = tuple(
            str(node.get("label"))
            for node in forecast_payload.get("nodes", ())
            if isinstance(node, Mapping) and node.get("kind") == "Event"
        )[:3]
        change_conditions = tuple(
            self._condition_text(node)
            for node in forecast_payload.get("nodes", ())
            if isinstance(node, Mapping)
            and node.get("kind") == "Driver"
            and node.get("invalidation_conditions")
        )[:5]
        stress_ebit = self._financial_value(by_role["stress"], "company.ebit")
        stress_fcff = self._financial_value(by_role["stress"], "company.fcff")
        return {
            "what_happens": (
                f"到 {period}，压力/基准/改善情景的营业收入分别为 "
                f"{stress_revenue} / {base_revenue} / {improvement_revenue}；"
                "差异来自业务 Driver 的条件变化。"
            ),
            "why_it_matters": "收入、成本与产能路径会继续传导到 EBIT、FCFF 和多方法条件每股价值区间。",
            "transmission": event_labels + ("事件 → Driver → 财务预测 → 条件价值区间",),
            "counterevidence": (
                f"若压力路径成立，{period} 营业收入仅为 {stress_revenue}，基准增长故事将被削弱。",
                f"压力路径下 {period} EBIT 为 {stress_ebit}、FCFF 为 {stress_fcff}，利润与现金流未达到基准情景。",
                "若压力情景的 Driver 与失效条件持续出现，应优先修订 Forecast，而不是维持原有叙事。",
            ),
            "what_would_change_the_view": change_conditions or ("关键 Driver 超出当前复核阈值。",),
        }

    @staticmethod
    def _applicability_text(value: str) -> str:
        if "no caller-declared multiples are accepted" in value:
            return "当前没有通过来源门禁的估值倍数输入。"
        if value == "ready":
            return "适用"
        if value == "caution":
            return "仅作交叉检查"
        return value or "输入不足"

    @staticmethod
    def _diagnostic_text(value: str) -> str:
        translations = (
            (
                "Terminal value exceeds 70% of enterprise value",
                "终值现值占企业价值超过 70%，该区间需要其他方法交叉验证。",
            ),
            (
                "Terminal value exceeds 80% of enterprise value",
                "终值现值占企业价值超过 80%，该区间对远期假设高度敏感。",
            ),
            (
                "Present value of terminal value exceeds 80% of enterprise value",
                "终值现值占企业价值超过 80%，该区间对远期假设高度敏感。",
            ),
            (
                "The explicit FCFF forecast contains negative periods",
                "明确预测期内存在负 FCFF，需要结合现金消耗路径解释。",
            ),
            (
                "DCF applicability gate permits this method only as a cross-check",
                "DCF 适用性门禁仅允许该方法作为交叉检查。",
            ),
        )
        for marker, translated in translations:
            if marker in value:
                return translated
        return value

    @staticmethod
    def _terminal_period(graph: Mapping[str, Any]) -> str:
        periods = {
            str(node.get("quantity", {}).get("period"))
            for node in graph.get("nodes", ())
            if isinstance(node, Mapping)
            and isinstance(node.get("quantity"), Mapping)
            and str(node["quantity"].get("period", "")).endswith("E")
        }
        if not periods:
            raise ResearchViewError("RESEARCH_VIEW_TERMINAL_PERIOD_MISSING")
        return max(periods, key=lambda item: int(item.removesuffix("E")))

    @staticmethod
    def _node_period(node: Mapping[str, Any]) -> str:
        quantity = node.get("quantity")
        return str(quantity.get("period", "")) if isinstance(quantity, Mapping) else ""

    def _node_metric(
        self,
        node: Mapping[str, Any],
        *,
        metric_id: str | None = None,
    ) -> dict[str, Any]:
        quantity = self._quantity(node.get("quantity"))
        return {
            "metric_id": metric_id or str(node.get("node_id", "")).rsplit(".", 1)[0],
            "label": node.get("label"),
            **quantity,
        }

    @staticmethod
    def _quantity(value: object) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        return {
            "value": value.get("normalized_value", value.get("value")),
            "unit": value.get("unit"),
            "scale": value.get("scale"),
            "currency": value.get("currency"),
            "period": value.get("period"),
            "as_of": value.get("as_of"),
        }

    @staticmethod
    def _financial_value(scenario: Mapping[str, Any], metric_id: str) -> str:
        match = next(
            (item for item in scenario["financials"] if item["metric_id"] == metric_id),
            None,
        )
        if match is None:
            return "数据不足"
        value = str(match.get("value", ""))
        try:
            rendered = format(Decimal(value).quantize(Decimal("0.01")), "f")
        except (InvalidOperation, ValueError):
            rendered = value
        return f"{rendered} {match.get('currency') or ''}".strip()

    @staticmethod
    def _condition_text(node: Mapping[str, Any]) -> str:
        condition = node.get("invalidation_conditions", ())[0]
        if not isinstance(condition, Mapping):
            return str(node.get("label", "关键 Driver"))
        threshold = condition.get("threshold")
        value = threshold.get("normalized_value") if isinstance(threshold, Mapping) else None
        unit = threshold.get("unit") if isinstance(threshold, Mapping) else None
        return (
            f"{node.get('label')}：{condition.get('metric_id')} "
            f"{condition.get('operator')} {value} {unit}"
        )
