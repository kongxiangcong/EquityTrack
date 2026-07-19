from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from equity_research import (
    CalibrationEvidence,
    DependencyCalibrationEvidence,
    DeterministicValueFallback,
    FinancialQuantity,
    MarketPathEngine,
    MarketPathObservation,
    SimulationInvariantError,
    ValuationSimulationEngine,
    validated_income_calibration_vectors,
)
from equity_research.scenario_valuation import (
    CommodityCurvePoint,
    EquityBridgeSpec,
    EquityBridgeTiming,
    ScenarioDefinition,
    ScenarioRole,
    ScenarioValuationEngine,
)
from equity_research.forecast import (
    CompanyArchetype,
    CompanyOpeningBalanceSheet,
    DataSnapshot,
    ForecastAssumption,
    ForecastEngine,
    ForecastNarrativeStatement,
    ForecastQuantity,
    ForecastRequest,
    NarrativeBasis,
    NarrativeCategory,
    Security,
    SegmentBaseline,
    SegmentForecastOverride,
    SnapshotFact,
)
from tests.platform.test_market_path_simulation_artifact import (
    _install_market_snapshot,
    _market_path_drafts,
)
from tests.platform.test_outlook_artifacts import _request as yihua_request
from tests.platform.test_research_workflow import CountingEngine, _root
from tests.test_market_path_simulation import request as market_path_request
from tests.test_scenario_valuation import cyclical_request, cyclical_resource_spec
from tests.test_valuation_simulation import distribution, request as simulation_request
from trading_platform import ProductionCompositionRoot
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.domain.workflow import (
    FieldSemantics,
    ImmutableArtifactDraft,
    ResearchProjection,
    ResearchWorkflowRequest,
)
from trading_platform.workflows.research import ResearchWorkflowService, WorkflowError


ROOT = Path(__file__).resolve().parents[2]
DFD_EXAMPLE = ROOT / "examples" / "duofuduo-002407"
FORBIDDEN = ("BUY", "HOLD", "SELL", "买入", "卖出", "持有", "目标价")


def _load_dfd(name: str):
    return json.loads((DFD_EXAMPLE / name).read_text(encoding="utf-8"))


def _dfd_projection() -> ResearchProjection:
    manifest = _load_dfd("source_manifest.json")
    semantics = tuple(
        FieldSemantics(
            source_id=source["source_id"],
            source_authority=source["tier"],
            field_name=field["field_name"],
            period=field["period"],
            statement_scope=field.get("statement_scope", "consolidated"),
            unit=field.get("unit", ""),
            currency=field.get("currency", ""),
            scale=str(field.get("scale", "1")),
            restatement_status=field.get("restatement_status", "as_reported"),
            published_at=source.get("published_at", source["report_date"]),
            available_at=source.get("available_at", source["retrieved_at"]),
            retrieved_at=source["retrieved_at"],
            supersedes_identity=source.get("supersedes_identity"),
            availability_basis=(
                "publisher_timestamp"
                if source.get("available_at")
                else "conservative_retrieval_time"
            ),
        )
        for source in manifest["sources"]
        for field in source["extracted_fields"]
    )
    return ResearchProjection(
        manifest=manifest,
        estimates=None,
        context=_load_dfd("research_context.json"),
        as_of_date="2026-07-18",
        profile="standard",
        field_semantics=semantics,
        diluted_share_identity="",
        net_debt_bridge_identity="SRC_CNINFO_2026Q1:cash+debt:2026Q1",
        source_manifest_validation_result={
            "validator": "source_manifest_validator",
            "validator_version": 2,
            "authority": "platform_source_manifest_gate@1",
            "manifest_content_hash": hashlib.sha256(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "passed": True,
            "source_manifest_status": "valid_with_limits",
        },
        source_manifest_path="examples/duofuduo-002407/source_manifest.json",
    )


def _dfd_request(invocation_id: str) -> ResearchWorkflowRequest:
    return ResearchWorkflowRequest(
        invocation_id=invocation_id,
        security_id="security_duofuduo",
        requested_date="2026-07-18",
        effective_session_date="2026-07-17",
        projection=_dfd_projection(),
    )


DFD_AS_OF = "2026-07-18"
DFD_OPENING_PERIOD = "2025FY"
DFD_FORECAST_PERIODS = ("2026E", "2027E", "2028E", "2029E", "2030E")


def _dfd_forecast_quantity(
    value: str,
    unit: str,
    fact_id: str,
    *,
    currency: str = "CNY",
    period: str = DFD_OPENING_PERIOD,
) -> ForecastQuantity:
    return ForecastQuantity(
        value=Decimal(value),
        unit=unit,
        scale=Decimal("1"),
        currency=currency,
        period=period,
        as_of=DFD_AS_OF,
        lineage_refs=(f"Fact:{fact_id}",),
    )


def _dfd_money(
    value: str,
    fact_id: str,
    *,
    period: str = DFD_OPENING_PERIOD,
    terminal: bool = False,
) -> FinancialQuantity:
    refs = (f"Fact:{fact_id}",)
    if terminal:
        refs += (
            f"Assumption:bridge_roll_forward:no_change:{fact_id.rsplit(':', 1)[-1]}",
        )
    return FinancialQuantity(
        value=Decimal(value),
        unit="CNY",
        scale=Decimal("1"),
        currency="CNY",
        period=period,
        as_of=DFD_AS_OF,
        provenance_refs=refs,
        kind="money",
    )


def _dfd_forecast_request() -> ForecastRequest:
    baseline = SegmentBaseline(
        segment_id="consolidated",
        volume=_dfd_forecast_quantity(
            "1", "units", "dfd:activity_volume", currency="N/A"
        ),
        asp=_dfd_forecast_quantity(
            "9434247610.47", "CNY/unit", "dfd:revenue"
        ),
        capacity=_dfd_forecast_quantity(
            "1", "units", "dfd:activity_capacity", currency="N/A"
        ),
        utilization=_dfd_forecast_quantity(
            "1", "decimal", "dfd:activity_utilization", currency="N/A"
        ),
        unit_cost=_dfd_forecast_quantity(
            "8117050427.96", "CNY/unit", "dfd:operating_cost"
        ),
        operating_expense=_dfd_forecast_quantity(
            "1074378619.96", "CNY", "dfd:operating_expense"
        ),
        capex=_dfd_forecast_quantity("1056712029.23", "CNY", "dfd:capex"),
        working_capital=_dfd_forecast_quantity(
            "2479919210.4", "CNY", "dfd:segment_working_capital"
        ),
        depreciation=_dfd_forecast_quantity(
            "1057319278.58", "CNY", "dfd:depreciation"
        ),
        tax_rate=_dfd_forecast_quantity(
            "0.28714203966508835",
            "decimal",
            "dfd:effective_tax_rate",
            currency="N/A",
        ),
    )
    opening = CompanyOpeningBalanceSheet(
        cash=_dfd_forecast_quantity("5030602303.23", "CNY", "dfd:cash"),
        working_capital=_dfd_forecast_quantity(
            "2479919210.4", "CNY", "dfd:opening_working_capital"
        ),
        net_ppe=_dfd_forecast_quantity("8503083657", "CNY", "dfd:net_ppe"),
        other_assets=_dfd_forecast_quantity(
            "8901426186.22", "CNY", "dfd:other_assets"
        ),
        debt=_dfd_forecast_quantity("6708875673.5", "CNY", "dfd:debt"),
        other_liabilities=_dfd_forecast_quantity(
            "7214625530.61", "CNY", "dfd:other_liabilities"
        ),
        equity=_dfd_forecast_quantity(
            "10991530152.74", "CNY", "dfd:total_equity"
        ),
    )
    bindings = (
        ("segment", "consolidated", "volume", "consolidated_activity_volume", baseline.volume),
        ("segment", "consolidated", "asp", "revenue", baseline.asp),
        ("segment", "consolidated", "capacity", "consolidated_activity_capacity", baseline.capacity),
        ("segment", "consolidated", "utilization", "consolidated_activity_utilization", baseline.utilization),
        ("segment", "consolidated", "unit_cost", "operating_cost", baseline.unit_cost),
        ("segment", "consolidated", "operating_expense", "operating_expense", baseline.operating_expense),
        ("segment", "consolidated", "capex", "capex", baseline.capex),
        ("segment", "consolidated", "working_capital", "working_capital", baseline.working_capital),
        ("segment", "consolidated", "depreciation", "depreciation_and_amortization", baseline.depreciation),
        ("segment", "consolidated", "tax_rate", "effective_tax_rate", baseline.tax_rate),
        *(("company", "", metric, field_name, quantity) for metric, field_name, quantity in (
            ("cash", "cash", opening.cash),
            ("working_capital", "working_capital", opening.working_capital),
            ("net_ppe", "net_ppe", opening.net_ppe),
            ("other_assets", "other_assets", opening.other_assets),
            ("debt", "debt", opening.debt),
            ("other_liabilities", "other_liabilities", opening.other_liabilities),
            ("equity", "total_equity", opening.equity),
        )),
    )
    calculated_fields = {
        "operating_expense",
        "working_capital",
        "depreciation_and_amortization",
        "effective_tax_rate",
        "other_assets",
        "debt",
        "other_liabilities",
    }
    facts = tuple(
        SnapshotFact(
            fact_id=quantity.lineage_refs[0].removeprefix("Fact:"),
            subject_id="002407.SZ",
            scope=scope,
            segment_id=segment_id,
            metric_id=metric,
            field_name=field_name,
            period=quantity.period,
            value=quantity.normalized_value,
            unit=quantity.unit,
            currency=quantity.currency,
            source_id=(
                "SRC_MODEL_NORMALIZATION_DFD_2025"
                if field_name.startswith("consolidated_activity_")
                else "SRC_CNINFO_2025AR"
            ),
            available_at="2026-04-16",
            official=not field_name.startswith("consolidated_activity_"),
            derivation_refs=(
                (
                    "Fact:dfd:revenue",
                    "Assumption:consolidated_one_unit_normalization@1",
                )
                if field_name.startswith("consolidated_activity_")
                else ()
            ),
            evidence_kind=(
                "model_derived"
                if field_name.startswith("consolidated_activity_")
                else "source_extracted"
                if field_name in calculated_fields
                else "reported"
            ),
            calculation_identity=(
                "consolidated-one-unit-normalization@1"
                if field_name.startswith("consolidated_activity_")
                else ""
            ),
            calculation_formula=(
                "normalized_value = revenue / revenue"
                if field_name.startswith("consolidated_activity_")
                else ""
            ),
        )
        for scope, segment_id, metric, field_name, quantity in bindings
    )
    snapshot = DataSnapshot(
        snapshot_id="dfd_official_2025fy_asof_20260717",
        security_id="002407.SZ",
        as_of=DFD_AS_OF,
        segment_baselines=(baseline,),
        company_opening_balance_sheet=opening,
        facts=facts,
    )
    narrative = tuple(
        ForecastNarrativeStatement(
            statement_id=statement_id,
            category=category,
            basis=basis,
            text=text,
            evidence_refs=refs,
        )
        for statement_id, category, basis, text, refs in (
            (
                "dfd.core_thesis",
                NarrativeCategory.CORE_THESIS,
                NarrativeBasis.JUDGMENT,
                "多氟多的核心不是单季利润增速，而是锂盐周期修复能否穿透到现金流，同时电子化学品选择权能否从叙事转为可验证收入。",
                ("Fact:dfd:revenue", "Fact:dfd:capex", "Fact:dfd:debt"),
            ),
            (
                "dfd.variant_view",
                NarrativeCategory.VARIANT_VIEW,
                NarrativeBasis.JUDGMENT,
                "市场可能低估利润修复中的营运资本和债务代价，并高估低收入基数电子化学品对短期业绩的贡献。",
                (
                    "Fact:dfd:opening_working_capital",
                    "Fact:dfd:debt",
                    "Assumption:electronic_materials_option_requires_validation",
                ),
            ),
            (
                "dfd.business_quality",
                NarrativeCategory.BUSINESS_QUALITY,
                NarrativeBasis.JUDGMENT,
                "氟资源到锂盐的一体化具有工艺和成本价值，但跨入电池及多类电子材料提高了资本配置难度。",
                ("Fact:dfd:operating_cost", "Fact:dfd:capex"),
            ),
            (
                "dfd.earnings_outlook",
                NarrativeCategory.EARNINGS_OUTLOOK,
                NarrativeBasis.ASSUMPTION,
                "后续盈利路径取决于锂盐价格与订单、毛利率以及现金流能否同步改善。",
                (
                    "Fact:dfd:revenue",
                    "Fact:dfd:operating_cost",
                    "Assumption:dfd_cycle_scenarios@2026-07-17",
                ),
            ),
            (
                "dfd.valuation_view",
                NarrativeCategory.VALUATION_VIEW,
                NarrativeBasis.JUDGMENT,
                "采用中周期研究视角；缺少完整权益桥时只展示企业价值，不形成正式每股价值或价格结论。",
                ("Fact:dfd:debt", "Assumption:per_share_gate_requires_dilution_bridge"),
            ),
            (
                "dfd.risk_reward",
                NarrativeCategory.RISK_REWARD,
                NarrativeBasis.RISK,
                "潜在改善来自锂盐利润延续、成本优势和电子材料放量；主要约束是现金流、债务、资本开支、周期回落和主题预期。",
                (
                    "Fact:dfd:revenue",
                    "Fact:dfd:operating_cost",
                    "Fact:dfd:debt",
                    "Fact:dfd:capex",
                ),
            ),
            *(
                (
                    f"dfd.uncertainty.{index}",
                    NarrativeCategory.KEY_UNCERTAINTY,
                    NarrativeBasis.RISK,
                    text,
                    refs,
                )
                for index, (text, refs) in enumerate(
                    (
                        ("LiPF6 单吨利润", ("Fact:dfd:revenue", "Fact:dfd:operating_cost")),
                        ("经营现金流", ("Fact:dfd:capex", "Fact:dfd:opening_working_capital")),
                        ("电子化学品收入占比", ("Assumption:electronic_materials_option_requires_validation",)),
                        ("电池业务盈利", ("Assumption:battery_economics_require_segment_validation",)),
                        ("债务和资本开支", ("Fact:dfd:debt", "Fact:dfd:capex")),
                    ),
                    start=1,
                )
            ),
            (
                "dfd.guardrail.no_double_count",
                NarrativeCategory.VALUATION_GUARDRAIL,
                NarrativeBasis.JUDGMENT,
                "分部 SOTP 必须从合并经营价值中剔除已独立计价部分；电池与电子材料只能按增量权益和可验证现金流计入，不能在合并收入或利润估值后再次完整叠加。",
                ("Fact:dfd:revenue", "Assumption:sotp_incremental_rights_only"),
            ),
            (
                "dfd.guardrail.option_gate",
                NarrativeCategory.VALUATION_GUARDRAIL,
                NarrativeBasis.JUDGMENT,
                "电子材料等长期选择权只有在客户认证、收入贡献、增量资本开支与资金成本形成同一证据链后才进入数值估值；否则只保留为待验证叙事。",
                (
                    "Fact:dfd:capex",
                    "Fact:dfd:debt",
                    "Assumption:electronic_materials_option_requires_validation",
                ),
            ),
            *(
                (
                    f"dfd.view_change.{index}",
                    NarrativeCategory.VIEW_CHANGE,
                    NarrativeBasis.JUDGMENT,
                    text,
                    refs,
                )
                for index, (text, refs) in enumerate(
                    (
                        ("半年报现金流转正且应收库存周转改善", ("Fact:dfd:opening_working_capital",)),
                        ("官方披露锂盐订单与单吨盈利的可持续证据", ("Fact:dfd:revenue", "Fact:dfd:operating_cost")),
                        ("电子化学品收入占比显著提升", ("Assumption:electronic_materials_option_requires_validation",)),
                        ("利润修复但现金流继续恶化或债务持续上升", ("Fact:dfd:debt", "Fact:dfd:capex")),
                    ),
                    start=1,
                )
            ),
        )
    )
    assumption_evidence = {
        "consolidated_one_unit_normalization@1": ("Fact:dfd:revenue",),
        "electronic_materials_option_requires_validation": (
            "Fact:dfd:revenue",
            "Fact:dfd:capex",
        ),
        "dfd_cycle_scenarios@2026-07-17": (
            "Fact:dfd:revenue",
            "Fact:dfd:operating_cost",
        ),
        "per_share_gate_requires_dilution_bridge": ("Fact:dfd:debt",),
        "battery_economics_require_segment_validation": (
            "Fact:dfd:revenue",
            "Fact:dfd:capex",
        ),
        "sotp_incremental_rights_only": ("Fact:dfd:revenue",),
    }
    assumptions = tuple(
        ForecastAssumption(
            assumption_id=assumption_id,
            description=(
                "Explicit analyst or model condition used by the typed narrative; "
                "it is not an observed company fact."
            ),
            available_at=DFD_AS_OF,
            evidence_refs=evidence_refs,
        )
        for assumption_id, evidence_refs in assumption_evidence.items()
    )
    return ForecastRequest(
        security=Security(
            security_id="002407.SZ",
            company_name="多氟多新材料股份有限公司",
            market="CN",
            reporting_currency="CNY",
            archetype=CompanyArchetype.CYCLICAL_MANUFACTURING,
            segment_ids=("consolidated",),
        ),
        as_of=DFD_AS_OF,
        data_snapshot=snapshot,
        forecast_periods=DFD_FORECAST_PERIODS,
        assumption_overrides=(),
        review_date="2026-08-31",
        assumptions=assumptions,
        narrative_statements=narrative,
    )


def _dfd_scenario_request():
    forecast = _dfd_forecast_request()
    curve_values = {
        "2026E": ("9000000000", "11200000000", "13000000000"),
        "2027E": ("8800000000", "10800000000", "12600000000"),
        "2028E": ("9000000000", "10500000000", "12000000000"),
        "2029E": ("9200000000", "10400000000", "11600000000"),
        "2030E": ("9400000000", "10400000000", "11400000000"),
    }
    def curve_quantity(value: str, period: str, case: str) -> ForecastQuantity:
        return replace(
            _dfd_forecast_quantity(
                value,
                "CNY/unit",
                f"dfd:cycle_curve:{period}:{case}",
                period=period,
            ),
            lineage_refs=(
                f"Assumption:dfd_cycle_curve:{period}:{case}",
            ),
        )

    curve = tuple(
        CommodityCurvePoint(
            segment_id="consolidated",
            period=period,
            price_low=curve_quantity(values[0], period, "low"),
            price_base=curve_quantity(values[1], period, "base"),
            price_high=curve_quantity(values[2], period, "high"),
        )
        for period, values in curve_values.items()
    )
    curve_assumptions = tuple(
        ForecastAssumption(
            assumption_id=quantity.lineage_refs[0].removeprefix(
                "Assumption:"
            ),
            description=(
                f"Analyst {case} consolidated cycle revenue path for {point.period}; "
                "not an observed fact or consensus estimate."
            ),
            available_at=DFD_AS_OF,
            evidence_refs=("Fact:dfd:revenue", "Fact:dfd:operating_cost"),
            value=quantity.normalized_value,
            unit=quantity.unit,
            currency=quantity.currency,
            period=quantity.period,
            scope="segment",
            segment_id="consolidated",
            metric_id="commodity_curve_price",
        )
        for point in curve
        for case, quantity in (
            ("low", point.price_low),
            ("base", point.price_base),
            ("high", point.price_high),
        )
    )
    bridge_values = {
        "lease_debt": "700861812.14",
        "preferred_stock": "0",
        "minority_interest": "2594330853.91",
        "associates_jv_value": "349869593.46",
        "non_operating_assets": "186939457.32",
    }
    source_extracted_bridge_fields = {"lease_debt", "non_operating_assets"}
    bridge_facts = tuple(
        SnapshotFact(
            fact_id=f"dfd:{field_name}",
            subject_id="002407.SZ",
            scope="company",
            segment_id="",
            metric_id=field_name,
            field_name=field_name,
            period=DFD_OPENING_PERIOD,
            value=Decimal(value),
            unit="CNY",
            currency="CNY",
            source_id="SRC_CNINFO_2025AR",
            available_at="2026-04-16",
            official=True,
            evidence_kind=(
                "source_extracted"
                if field_name in source_extracted_bridge_fields
                else "reported"
            ),
        )
        for field_name, value in bridge_values.items()
    )
    forecast = replace(
        forecast,
        assumptions=forecast.assumptions + curve_assumptions,
        data_snapshot=replace(
            forecast.data_snapshot,
            facts=forecast.data_snapshot.facts + bridge_facts,
            content_hash="",
        ),
    )

    def bridge(timing: EquityBridgeTiming) -> EquityBridgeSpec:
        terminal = timing == EquityBridgeTiming.TERMINAL
        period = DFD_FORECAST_PERIODS[-1] if terminal else DFD_OPENING_PERIOD
        return EquityBridgeSpec(
            timing=timing,
            diluted_shares=None,
            pension_deficit=None,
            output_currency="CNY",
            **{
                field_name: _dfd_money(
                    value,
                    f"dfd:{field_name}",
                    period=period,
                    terminal=terminal,
                )
                for field_name, value in bridge_values.items()
            },
        )

    route = cyclical_request()
    plan = replace(
        route.valuation_plan,
        present_value_bridge=bridge(EquityBridgeTiming.OPENING),
        terminal_value_bridge=bridge(EquityBridgeTiming.TERMINAL),
        cyclical_resource=replace(
            cyclical_resource_spec(),
            curve_version="dfd-consolidated-cycle-curve@2026-07-17",
            curve_as_of=DFD_AS_OF,
            commodity_curve=curve,
            assets=(),
            historical_observations=(),
        ),
    )
    settings = {
        ScenarioRole.STRESS: ("-0.10", "-0.10", "0.05", "0.08", "3000000000"),
        ScenarioRole.BASE: ("0.08", "0.02", "0.01", "0.05", "1500000000"),
        ScenarioRole.IMPROVEMENT: ("0.15", "0.08", "-0.03", "0.04", "800000000"),
    }
    scenarios = tuple(
        ScenarioDefinition(
            scenario_id=role.value,
            role=role,
            label=role.value.title(),
            mutually_exclusive_group="dfd_cycle_outlook_2030",
            partition_basis="Cycle demand, realized pricing, cost and capital intensity.",
            driver_overrides=tuple(
                SegmentForecastOverride(
                    segment_id="consolidated",
                    period=period,
                    demand_growth=Decimal(settings[role][0]),
                    asp_growth=Decimal(settings[role][1]),
                    capacity_growth=Decimal("0"),
                    target_utilization=Decimal("1"),
                    unit_cost_growth=Decimal(settings[role][2]),
                    operating_expense_growth=Decimal("0.03"),
                    capex_growth=Decimal(settings[role][3]),
                    depreciation_growth=Decimal("0.03"),
                    working_capital_to_revenue=Decimal("0.263"),
                    tax_rate=Decimal("0.28714203966508835"),
                    debt_change=Decimal(settings[role][4]),
                    event_probability=Decimal("1"),
                )
                for period in DFD_FORECAST_PERIODS
            ),
            probability_evidence=None,
            rationale_refs=(f"Assumption:dfd_cycle_scenario:{role.value}",),
        )
        for role in (ScenarioRole.STRESS, ScenarioRole.BASE, ScenarioRole.IMPROVEMENT)
    )
    return replace(
        route,
        base_forecast_request=forecast,
        scenarios=scenarios,
        valuation_plan=plan,
    )


def _dfd_analysis_drafts() -> tuple[ImmutableArtifactDraft, ...]:
    request = _dfd_scenario_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    valuation_result = ScenarioValuationEngine().run(request)
    model_identity = "dfd-cyclical-manufacturing-model@1"
    policy_identity = "dfd-evidence-constrained-policy@1"
    data_snapshot = ImmutableArtifactDraft.from_data_snapshot(
        request.base_forecast_request.data_snapshot,
        model_identity=model_identity,
        policy_identity=policy_identity,
    )
    forecast = ImmutableArtifactDraft.from_forecast_graph(
        graph,
        model_identity=model_identity,
        policy_identity=policy_identity,
    )
    valuation = ImmutableArtifactDraft.from_scenario_valuation(
        valuation_result,
        forecast_graph=graph,
        model_identity=model_identity,
        policy_identity=policy_identity,
    )
    scenario = next(
        item for item in valuation.payload["scenarios"] if item["role"] == "base"
    )
    method = next(
        item for item in scenario["methods"] if item["method_id"] == "mid_cycle_ev_ebitda"
    )
    value_range = method["conditional_value_range"]
    fallback_values = {
        point: value_range[point]["basis_value"]
        for point in ("low", "base", "high")
    }
    fallback = DeterministicValueFallback(
        scenario_id=scenario["scenario_id"],
        method_id=method["method_id"],
        formula_version=method["formula_version"],
        low=Decimal(fallback_values["low"]["normalized_value"]),
        base=Decimal(fallback_values["base"]["normalized_value"]),
        high=Decimal(fallback_values["high"]["normalized_value"]),
        unit="CNY",
        currency="CNY",
        period=fallback_values["base"]["period"],
        output_level="basis_value",
    )
    calibration_asset = _load_dfd(
        "assets/dfd_income_calibration_2018_2025.json"
    )
    vectors = validated_income_calibration_vectors(
        _load_dfd("assets/dfd_income_selected_cumulative_2018_2025.json"),
        calibration_asset,
    )
    calibration_refs = (
        "Evidence:SRC_TUSHARE_DFD_INCOME_CALIBRATION_2018_2025",
        "Evidence:SRC_MODEL_DFD_INCOME_DERIVATION_2019_2025",
    )
    calibration_fields = {
        "window_start": "2019-01-01",
        "window_end": "2025-12-31",
        "as_of": DFD_AS_OF,
        "published_at": "2026-04-16T00:00:00+08:00",
        "available_at": calibration_asset["retrieved_at"],
        "retrieved_at": calibration_asset["retrieved_at"],
        "basis": (
            "Single-quarter observations derived from version-selected cumulative "
            "income statements supplied by the preconfigured non-official "
            "Tushare-compatible gateway; secondary calibration only."
        ),
        "evidence_refs": calibration_refs,
    }
    assumptions = tuple(
        distribution(
            assumption_id,
            family="empirical",
            parameters=(),
            hard_bounds=(
                format(min(observations), "f"),
                format(max(observations), "f"),
            ),
            evidence=CalibrationEvidence(
                sample_id=f"dfd_{assumption_id}_2019q1_2025q4",
                observations=observations,
                **calibration_fields,
            ),
        )
        for assumption_id, observations in (
            ("historical_revenue_growth", tuple(row[0] for row in vectors)),
            ("historical_operating_margin", tuple(row[1] for row in vectors)),
        )
    )
    base_result = next(
        item
        for item in valuation_result.scenarios
        if item.role == ScenarioRole.BASE
    )
    terminal_revenue = base_result.forecast_graph.quantity(
        f"company.revenue.{DFD_FORECAST_PERIODS[-1]}"
    ).normalized_value
    mid_cycle_multiple = Decimal(
        next(
            item["quantity"]["normalized_value"]
            for item in method["assumptions"]
            if item["name"] == "mid_cycle_multiple"
        )
    )
    coefficients = (
        fallback.base,
        terminal_revenue * mid_cycle_multiple,
    )
    with localcontext() as context:
        context.prec = 80
        intercept = fallback.base - sum(
            (
                coefficient * assumption.reference_value
                for coefficient, assumption in zip(
                    coefficients,
                    assumptions,
                    strict=True,
                )
            ),
            Decimal("0"),
        )
    base_simulation = simulation_request(
        assumptions,
        matrix=(
            ("1", "0.6516658652505007468879121768"),
            ("0.6516658652505007468879121768", "1"),
        ),
        coefficients=tuple(format(item, "f") for item in coefficients),
        intercept=format(intercept, "f"),
        minimum_output="0",
        sample_budget=100_000,
        tail_threshold=format(fallback.base * Decimal("0.20"), "f"),
        dependency_override_identity=None,
    )
    simulation_input = replace(
        base_simulation,
        simulation_id="dfd_enterprise_value_simulation@1",
        security_id="002407.SZ",
        as_of=DFD_AS_OF,
        valuation_source_identity=valuation.source_identity,
        model_identity="dfd-enterprise-value-affine-simulation@1",
        policy_identity=policy_identity,
        budget=replace(
            base_simulation.budget,
            batch_size=10_000,
            convergence_tolerance=Decimal("0.05"),
            maximum_invalid_path_rate=Decimal("0.10"),
        ),
        dependency_model=replace(
            base_simulation.dependency_model,
            model_identity="dfd-cycle-cost-dependency@1",
            calibration=DependencyCalibrationEvidence(
                sample_id="dfd_revenue_growth_margin_dependency_2019q1_2025q4",
                observation_vectors=vectors,
                derivation_kind="cumulative_income_quarterly",
                raw_observation_content_hash="11DDFC3DA05FEFF15879E3E40C6424D2EE9142A3C489160E1F587832777C1C98".lower(),
                derivation_ledger_content_hash="A947F0B69FFA2E493D787634193F3FC0D77C5ED7689A2A798FC949E39B6FF4AA".lower(),
                **calibration_fields,
            ),
            calibration_tolerance=Decimal("0.000001"),
            user_override_identity=None,
        ),
        valuation_model=replace(
            base_simulation.valuation_model,
            formula_id="dfd-first-order-mid-cycle-enterprise-value@1",
            output_unit="CNY",
            currency="CNY",
            period=fallback.period,
            output_level="basis_value",
            terms=tuple(
                replace(term, coefficient_unit="CNY")
                for term in base_simulation.valuation_model.terms
            ),
        ),
        deterministic_fallback=fallback,
    )
    simulation_result = ValuationSimulationEngine().run(simulation_input)
    simulation = ImmutableArtifactDraft.from_valuation_simulation(
        simulation_result,
        valuation_artifact=valuation,
        model_identity=model_identity,
        policy_identity=policy_identity,
    )
    return data_snapshot, forecast, valuation, simulation


def _dfd_market_path_request():
    raw = _load_dfd(
        "assets/dfd_market_path_calibration_20260401_20260717.json"
    )
    rows = [
        item
        for item in raw["rows"]
        if 20260520 <= item["trade_date"] < 20260717
    ]
    observations = []
    previous_ref = None
    previous_close = None
    for item in rows:
        session = str(item["trade_date"])
        session_date = f"{session[:4]}-{session[4:6]}-{session[6:]}"
        close = Decimal(str(item["close"]))
        daily_return = (
            close / previous_close - Decimal("1")
            if previous_close is not None
            else Decimal("0")
        )
        limit_tolerance = (
            Decimal("0.005") / previous_close
            if previous_close is not None
            else Decimal("0")
        )
        evidence_ref = (
            "Evidence:SRC_TUSHARE_DFD_MARKET_PATH_CALIBRATION_"
            f"20260401_20260717:{session}"
        )
        observations.append(
            MarketPathObservation(
                session_date=session_date,
                unadjusted_close=close,
                adjustment_factor=Decimal("1"),
                market_state=(
                    "warmup"
                    if previous_close is None
                    else "risk_on"
                    if daily_return > 0
                    else "risk_off"
                    if daily_return < 0
                    else "flat"
                ),
                close_available_at=f"{session_date}T15:00:00+08:00",
                factor_available_at=f"{session_date}T15:00:00+08:00",
                state_available_at=f"{session_date}T15:00:00+08:00",
                retrieved_at=raw["retrieved_at"],
                suspended=False,
                limit_state=(
                    "up"
                    if abs(daily_return - Decimal("0.10")) <= limit_tolerance
                    else "down"
                    if abs(daily_return + Decimal("0.10")) <= limit_tolerance
                    else "none"
                ),
                corporate_action_identity=None,
                evidence_refs=tuple(
                    ref
                    for ref in (evidence_ref, previous_ref)
                    if ref is not None
                ),
            )
        )
        previous_ref = evidence_ref
        previous_close = close
    assert len(observations) >= 40
    starting_ref = (
        "Evidence:SRC_TUSHARE_DFD_DAILY_20260717:20260717"
    )
    base = market_path_request(rows=tuple(observations), state="risk_off")
    return replace(
        base,
        simulation_id="dfd_market_path_simulation@1",
        security_id="002407.SZ",
        as_of=DFD_AS_OF,
        as_of_at="2026-07-18T20:07:26+08:00",
        model_identity="dfd-state-block-bootstrap@1",
        policy_identity="dfd-market-path-policy@1",
        starting_price=Decimal("31.24"),
        starting_price_session="2026-07-17",
        starting_price_member_id=starting_ref,
        starting_price_available_at="2026-07-17T15:00:00+08:00",
        starting_price_evidence_refs=(starting_ref,),
        current_market_state="risk_off",
        current_state_available_at="2026-07-17T15:00:00+08:00",
        current_state_evidence_refs=(
            starting_ref,
            observations[-1].evidence_refs[0],
            "one_session_return_sign@1",
        ),
        calibration=replace(
            base.calibration,
            snapshot_id="dfd-market-calibration-20260520-20260716@1",
            market="SZSE",
            market_timezone="Asia/Shanghai",
            series_identity="dfd-pit-unadjusted-close-stable-factor-window@1",
            series_evidence_refs=tuple(
                item.evidence_refs[0] for item in observations
            ),
            trading_calendar_identity="szse-trade-cal-20260717@1",
            calendar_evidence_refs=tuple(
                f"Calendar:SZSE:{item.session_date}"
                for item in observations
            )
            + ("Calendar:SZSE:2026-07-17",),
            calendar_member_ids=tuple(
                f"Calendar:SZSE:{item.session_date}"
                for item in observations
            ),
            trading_sessions=tuple(
                item.session_date for item in observations
            ),
            next_session_date="2026-07-17",
            next_session_calendar_member_id="Calendar:SZSE:2026-07-17",
            series_member_ids=tuple(
                item.evidence_refs[0] for item in observations
            ),
            observations=tuple(observations),
            window_start=observations[0].session_date,
            window_end=observations[-1].session_date,
            as_of=DFD_AS_OF,
            basis=(
                "State-conditioned contiguous block bootstrap over the frozen "
                "post-corporate-action stable-factor window; raw close and "
                "adjustment-factor rows remain hash-bound in the source manifest."
            ),
        ),
        budget=replace(base.budget, seed=20260717),
        price_thresholds=(Decimal("28"), Decimal("40")),
    )


def _dfd_market_path_drafts(
    deterministic: tuple[ImmutableArtifactDraft, ...],
    bound_request,
) -> tuple[ImmutableArtifactDraft, ...]:
    simulation = deterministic[-1]
    result = MarketPathEngine().run(
        replace(
            bound_request,
            valuation_simulation_source_identity=simulation.source_identity,
        )
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        result.calibration,
        security_id=simulation.subject_id,
        model_identity="dfd-cyclical-manufacturing-model@1",
        policy_identity="dfd-evidence-constrained-policy@1",
    )
    market_path = ImmutableArtifactDraft.from_market_path_simulation(
        result,
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="dfd-cyclical-manufacturing-model@1",
        policy_identity="dfd-evidence-constrained-policy@1",
    )
    return (*deterministic, market_data, market_path)


def test_yihua_complete_outlook_replays_after_restart(tmp_path: Path) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    request = replace(
        yihua_request(
            "journey:yihua:first",
            _market_path_drafts(bound_request),
        ),
        workflow_snapshot_id=bound_request.calibration.platform_snapshot_id,
        candidate_member_ids=market_member_ids,
        market_only_member_ids=market_member_ids,
    )
    first = root.facade.run_research_workflow(request)
    research_run = root.facade.get_research_run_payload(first.research_run_id)
    assert research_run["status"] != "blocked"
    artifacts = tuple(
        root.facade.get_research_artifact(record_id)
        for record_id in first.artifact_record_ids
    )
    assert [item.artifact_kind for item in artifacts] == [
        "DataSnapshot",
        "Forecast",
        "Valuation",
        "Simulation",
        "MarketDataSnapshot",
        "MarketPathSimulation",
    ]
    assert all(item.content_hash for item in artifacts)
    manifest = root.facade.get_artifact_manifest(first.final_manifest_id)
    assert {
        "research_run_json",
        "research_report_html",
        "forecast",
        "valuation",
        "simulation",
        "market_path_simulation",
    } <= {member["member_role"] for member in manifest.members}
    view = root.facade.get_workspace(
        "security_yihua",
        first.research_snapshot_id,
    )["research_views"][0]
    assert view["story"]["what_happens"]
    assert view["key_drivers"]
    assert [item["role"] for item in view["scenarios"]] == [
        "stress",
        "base",
        "improvement",
    ]
    methods = {
        method["method_id"]
        for scenario in view["scenarios"]
        for method in scenario["methods"]
        if method["status"] == "ready"
    }
    assert {"fcff_dcf", "sotp", "reverse_dcf"} <= methods
    assert view["valuation_simulation"] is None
    assert view["audit"]["permissions"]["formal_per_share_valuation"] is False
    assert view["market_price_paths"]["terminal_price_quantiles"]
    assert view["value_market_divergence"] is None
    rendered = json.dumps(view, ensure_ascii=False)
    assert not any(term in rendered for term in FORBIDDEN)
    hashes = tuple(item.content_hash for item in artifacts)
    root.close()

    rebuilt = ProductionCompositionRoot(tmp_path, research_engine=engine)
    replay = rebuilt.facade.run_research_workflow(replace(request, invocation_id="journey:yihua:replay"))
    replayed = tuple(
        rebuilt.facade.get_research_artifact(record_id)
        for record_id in replay.artifact_record_ids
    )
    assert replay.research_run_id == first.research_run_id
    assert replay.research_snapshot_id == first.research_snapshot_id
    assert replay.artifact_record_ids == first.artifact_record_ids
    assert tuple(item.content_hash for item in replayed) == hashes
    replay_manifest = rebuilt.facade.get_artifact_manifest(replay.final_manifest_id)
    assert [item["member_role"] for item in replay_manifest.members] == [
        item["member_role"] for item in manifest.members
    ]
    first_by_role = {item["member_role"]: item for item in manifest.members}
    replay_by_role = {
        item["member_role"]: item for item in replay_manifest.members
    }
    for role in (
        "data_snapshot",
        "forecast",
        "valuation",
        "simulation",
        "market_data_snapshot",
        "market_path_simulation",
    ):
        assert replay_by_role[role]["artifact_id"] == first_by_role[role][
            "artifact_id"
        ]
    assert (
        rebuilt.facade.get_workflow_history(replay.workflow_run_id).final_manifest_id
        == replay.final_manifest_id
    )
    rebuilt.close()


def test_duofuduo_real_sources_degrade_without_inventing_dilution(tmp_path: Path) -> None:
    artifacts = _dfd_analysis_drafts()
    facts = {
        item["field_name"]: item for item in artifacts[0].payload["facts"]
    }
    assert facts["revenue"]["evidence_kind"] == "reported"
    assert facts["debt"]["evidence_kind"] == "source_extracted"
    assert not facts["debt"]["derivation_refs"]
    assert not facts["debt"]["calculation_formula"]
    assert facts["consolidated_activity_volume"]["evidence_kind"] == (
        "model_derived"
    )
    assert not any(
        item["metric_id"] == "commodity_curve_price"
        for item in artifacts[0].payload["facts"]
    )
    curve_assumptions = [
        item
        for item in artifacts[1].payload["assumptions"]
        if item["metric_id"] == "commodity_curve_price"
    ]
    assert len(curve_assumptions) == 15
    assert all(item["available_at"] == DFD_AS_OF for item in curve_assumptions)
    valuation = artifacts[2]
    simulation = artifacts[3]
    methods = {
        item["method_id"]: item
        for scenario in valuation.payload["scenarios"]
        for item in scenario["methods"]
    }
    assert methods["mid_cycle_ev_ebitda"]["status"] == "ready"
    assert methods["resource_nav"]["status"] == "blocked"
    assert methods["cyclical_historical_band"]["status"] == "blocked"
    assert all(
        point["basis_value"] is not None
        and point["equity_value"] is None
        and point["per_share_value"] is None
        for scenario in valuation.payload["scenarios"]
        for method in scenario["methods"]
        if method["method_id"] == "mid_cycle_ev_ebitda"
        for point in method["conditional_value_range"].values()
    )
    assert simulation.status == "ready"
    assert simulation.payload["valuation_model"]["output_level"] == "basis_value"
    assert simulation.payload["converged"] is True
    assert {item["family"] for item in simulation.payload["assumptions"]} == {
        "empirical"
    }
    assert all(
        item["calibration"]["evidence_refs"]
        == [
            "Evidence:SRC_TUSHARE_DFD_INCOME_CALIBRATION_2018_2025",
            "Evidence:SRC_MODEL_DFD_INCOME_DERIVATION_2019_2025",
        ]
        for item in simulation.payload["assumptions"]
    )
    assert len(
        simulation.payload["dependency_model"]["calibration"][
            "observation_vectors"
        ]
    ) == 28
    assert simulation.payload["dependency_model"]["user_override_identity"] is None
    assert simulation.payload["contributions"]

    engine = CountingEngine()
    root = ProductionCompositionRoot(tmp_path, research_engine=engine)
    root.facade.add_watchlist_item(
        "watch:security_duofuduo",
        SecurityIdentity("security_duofuduo", "SZSE", "002407", "CNY", "2010-05-18"),
    )
    bound_market_request, market_member_ids = _install_market_snapshot(
        root,
        _dfd_market_path_request(),
        security_id="security_duofuduo",
        snapshot_id="snapshot_market_path_duofuduo_20260717",
    )
    request = replace(
        _dfd_request("journey:dfd:first"),
        analysis_artifacts=_dfd_market_path_drafts(
            artifacts,
            bound_market_request,
        ),
        workflow_snapshot_id=(
            bound_market_request.calibration.platform_snapshot_id
        ),
        candidate_member_ids=market_member_ids,
        market_only_member_ids=market_member_ids,
    )
    first = root.facade.run_research_workflow(request)
    published = tuple(
        root.facade.get_research_artifact(record_id)
        for record_id in first.artifact_record_ids
    )
    assert [item.artifact_kind for item in published] == [
        "DataSnapshot",
        "Forecast",
        "Valuation",
        "Simulation",
        "MarketDataSnapshot",
        "MarketPathSimulation",
    ]
    assert all(item.content_hash for item in published)
    research_run = root.facade.get_research_run_payload(first.research_run_id)
    assert research_run["status"] != "blocked"
    view = root.facade.get_workspace(
        "security_duofuduo",
        first.research_snapshot_id,
    )["research_views"][0]
    assert view["story"]["what_happens"]
    assert view["key_drivers"]
    assert view["valuation_simulation"]["output_level"] == "basis_value"
    assert view["market_price_paths"]["terminal_price_quantiles"]
    assert view["value_market_divergence"]["status"] == "not_comparable"
    assert view["audit"]["permissions"]["formal_per_share_valuation"] is False
    assert not any(term in json.dumps(view, ensure_ascii=False) for term in FORBIDDEN)
    manifest = root.facade.get_artifact_manifest(first.final_manifest_id)
    hashes = tuple(item.content_hash for item in published)
    root.close()

    rebuilt = ProductionCompositionRoot(tmp_path, research_engine=engine)
    replay = rebuilt.facade.run_research_workflow(
        replace(request, invocation_id="journey:dfd:replay")
    )
    replayed = tuple(
        rebuilt.facade.get_research_artifact(record_id)
        for record_id in replay.artifact_record_ids
    )
    assert replay.research_run_id == first.research_run_id
    assert replay.research_snapshot_id == first.research_snapshot_id
    assert replay.artifact_record_ids == first.artifact_record_ids
    assert tuple(item.content_hash for item in replayed) == hashes
    replay_manifest = rebuilt.facade.get_artifact_manifest(
        replay.final_manifest_id
    )
    assert [item["member_role"] for item in replay_manifest.members] == [
        item["member_role"] for item in manifest.members
    ]
    first_by_role = {item["member_role"]: item for item in manifest.members}
    replay_by_role = {
        item["member_role"]: item for item in replay_manifest.members
    }
    for role in (
        "data_snapshot",
        "forecast",
        "valuation",
        "simulation",
        "market_data_snapshot",
        "market_path_simulation",
    ):
        assert replay_by_role[role]["artifact_id"] == first_by_role[role][
            "artifact_id"
        ]
    rebuilt.close()


def test_duofuduo_calibration_vectors_are_recomputed_from_raw_rows() -> None:
    raw = _load_dfd("assets/dfd_income_selected_cumulative_2018_2025.json")
    ledger = _load_dfd("assets/dfd_income_calibration_2018_2025.json")
    vectors = validated_income_calibration_vectors(raw, ledger)
    assert len(vectors) == 28

    tampered = json.loads(json.dumps(ledger))
    tampered["observation_vectors"][0][0] = "0"
    with pytest.raises(SimulationInvariantError) as caught:
        validated_income_calibration_vectors(raw, tampered)
    assert caught.value.code == "SIMULATION_CALIBRATION_VECTOR_MISMATCH"

    wrong_period = json.loads(json.dumps(ledger))
    wrong_period["quarterly_derivations"][0]["prior_row_refs"] = [
        "income:20180630:report_type_1"
    ]
    with pytest.raises(SimulationInvariantError) as caught:
        validated_income_calibration_vectors(raw, wrong_period)
    assert caught.value.code == "SIMULATION_CALIBRATION_PERIOD_BINDING_INVALID"


def test_public_facade_does_not_trust_artifact_calibration_tolerance(
    tmp_path: Path,
) -> None:
    root = ProductionCompositionRoot(tmp_path, research_engine=CountingEngine())
    root.facade.add_watchlist_item(
        "watch:security_duofuduo",
        SecurityIdentity(
            "security_duofuduo", "SZSE", "002407", "CNY", "2010-05-18"
        ),
    )
    drafts = _dfd_analysis_drafts()
    simulation = drafts[-1]
    payload = json.loads(simulation.payload_json)
    payload["dependency_model"]["calibration"]["observation_vectors"][0][0] = "0.1"
    payload["dependency_model"]["calibration_tolerance"] = "1"
    tampered = ImmutableArtifactDraft._build(
        artifact_kind=simulation.artifact_kind,
        schema_version=simulation.schema_version,
        subject_id=simulation.subject_id,
        as_of=simulation.as_of,
        source_identity=simulation.source_identity,
        model_identity=simulation.model_identity,
        policy_identity=simulation.policy_identity,
        status=simulation.status,
        formula_identities=simulation.formula_identities,
        dependency_kinds=simulation.dependency_kinds,
        payload=payload,
        summary=simulation.summary,
    )
    request = replace(
        _dfd_request("journey:dfd:forged-calibration-tolerance"),
        analysis_artifacts=(*drafts[:-1], tampered),
    )
    with pytest.raises(WorkflowError) as caught:
        root.facade.run_research_workflow(request)
    assert caught.value.code == "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED"
    root.close()


def test_public_facade_rejects_per_share_artifacts_without_dilution_identity(
    tmp_path: Path,
) -> None:
    engine = CountingEngine()
    root = ProductionCompositionRoot(tmp_path, research_engine=engine)
    root.facade.add_watchlist_item(
        "watch:security_duofuduo",
        SecurityIdentity(
            "security_duofuduo",
            "SZSE",
            "002407",
            "CNY",
            "2010-05-18",
        ),
    )
    base = _dfd_projection()
    asserted_pass = {
        **base.source_manifest_validation_result,
        "passed": True,
        "source_manifest_status": "sufficient",
    }
    request = replace(
        _dfd_request("journey:dfd:tampered-per-share"),
        projection=replace(
            base,
            source_manifest_validation_result=asserted_pass,
        ),
        analysis_artifacts=_market_path_drafts()[:4],
    )
    with pytest.raises(WorkflowError) as caught:
        root.facade.run_research_workflow(request)
    assert caught.value.code == "RESEARCH_ANALYSIS_PER_SHARE_GATE_FAILED"
    root.close()


@pytest.mark.parametrize(
    "payload",
    (
        {"output_level": "per_share_value", "low": "1"},
        {"kind": "per_share", "value": "1"},
        {"unit": "CNY/share", "value": "1"},
        {"unit": "CNY per share", "value": "1"},
    ),
)
def test_per_share_semantic_aliases_are_detected(payload: dict[str, str]) -> None:
    assert ResearchWorkflowService._has_per_share_output(payload) is True


def test_per_share_permission_recomputes_each_valuation_point() -> None:
    original = _market_path_drafts()[2].payload
    valuation = json.loads(json.dumps(original))
    bound = ResearchWorkflowService._share_bound_ready_methods(
        valuation, Decimal("100"), "diluted_shares"
    )
    assert len(bound) >= 2

    method = next(
        method
        for scenario in valuation["scenarios"]
        for method in scenario["methods"]
        if method["method_id"] in bound
    )
    method["conditional_value_range"]["base"]["per_share_value"][
        "normalized_value"
    ] = "999"
    assert method["method_id"] not in ResearchWorkflowService._share_bound_ready_methods(
        valuation, Decimal("100"), "diluted_shares"
    )

    shortened = json.loads(json.dumps(original))
    shortened_method = next(
        item
        for scenario in shortened["scenarios"]
        for item in scenario["methods"]
        if item["method_id"] in bound
    )
    shortened_method["conditional_value_range"].pop("high")
    assert shortened_method[
        "method_id"
    ] not in ResearchWorkflowService._share_bound_ready_methods(
        shortened, Decimal("100"), "diluted_shares"
    )

    extra_divide = json.loads(json.dumps(original))
    extra_method = next(
        item
        for scenario in extra_divide["scenarios"]
        for item in scenario["methods"]
        if item["method_id"] in bound
    )
    extra_method["conditional_value_range"]["base"]["bridge_trace"].append(
        {"operation": "divide_diluted_shares", "amount": "100", "ref_ids": []}
    )
    assert extra_method[
        "method_id"
    ] not in ResearchWorkflowService._share_bound_ready_methods(
        extra_divide, Decimal("100"), "diluted_shares"
    )

    missing_scenario_method = json.loads(json.dumps(original))
    target_id = next(iter(bound))
    scenario = next(
        item
        for item in missing_scenario_method["scenarios"]
        if item["role"] == "stress"
    )
    scenario["methods"] = [
        item for item in scenario["methods"] if item["method_id"] != target_id
    ]
    assert target_id not in ResearchWorkflowService._share_bound_ready_methods(
        missing_scenario_method, Decimal("100"), "diluted_shares"
    )


def test_public_facade_rejects_deleted_calibration_kind(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    drafts = _market_path_drafts()[:4]
    simulation = drafts[-1]
    payload = json.loads(simulation.payload_json)
    payload["dependency_model"]["calibration"]["derivation_kind"] = None
    tampered = ImmutableArtifactDraft._build(
        artifact_kind=simulation.artifact_kind,
        schema_version=simulation.schema_version,
        subject_id=simulation.subject_id,
        as_of=simulation.as_of,
        source_identity=simulation.source_identity,
        model_identity=simulation.model_identity,
        policy_identity=simulation.policy_identity,
        status=simulation.status,
        formula_identities=simulation.formula_identities,
        dependency_kinds=simulation.dependency_kinds,
        payload=payload,
        summary=simulation.summary,
    )
    request = yihua_request(
        "journey:yihua:deleted-calibration-kind",
        (*drafts[:-1], tampered),
    )
    with pytest.raises(WorkflowError) as caught:
        root.facade.run_research_workflow(request)
    assert caught.value.code == "RESEARCH_ANALYSIS_SOURCE_GATE_FAILED"
    root.close()


def test_public_facade_rejects_nested_per_share_range_without_dilution_identity(
    tmp_path: Path,
) -> None:
    root = ProductionCompositionRoot(tmp_path, research_engine=CountingEngine())
    root.facade.add_watchlist_item(
        "watch:security_duofuduo",
        SecurityIdentity(
            "security_duofuduo", "SZSE", "002407", "CNY", "2010-05-18"
        ),
    )
    drafts = _dfd_analysis_drafts()[:3]
    valuation = drafts[-1]
    payload = json.loads(valuation.payload_json)
    payload["weighted_method_ranges"] = [
        {"per_share_low": "1", "per_share_base": "2", "per_share_high": "3"}
    ]
    tampered = ImmutableArtifactDraft._build(
        artifact_kind=valuation.artifact_kind,
        schema_version=valuation.schema_version,
        subject_id=valuation.subject_id,
        as_of=valuation.as_of,
        source_identity=valuation.source_identity,
        model_identity=valuation.model_identity,
        policy_identity=valuation.policy_identity,
        status=valuation.status,
        formula_identities=valuation.formula_identities,
        dependency_kinds=valuation.dependency_kinds,
        payload=payload,
        summary=valuation.summary,
    )
    request = replace(
        _dfd_request("journey:dfd:nested-per-share"),
        analysis_artifacts=(*drafts[:-1], tampered),
    )
    with pytest.raises(WorkflowError) as caught:
        root.facade.run_research_workflow(request)
    assert caught.value.code == "RESEARCH_ANALYSIS_PER_SHARE_GATE_FAILED"
    root.close()


def test_public_facade_revalidates_forged_sufficient_result(
    tmp_path: Path,
) -> None:
    root = ProductionCompositionRoot(tmp_path, research_engine=CountingEngine())
    root.facade.add_watchlist_item(
        "watch:security_duofuduo",
        SecurityIdentity(
            "security_duofuduo", "SZSE", "002407", "CNY", "2010-05-18"
        ),
    )
    base = _dfd_projection()
    forged = {
        **base.source_manifest_validation_result,
        "passed": True,
        "source_manifest_status": "sufficient",
    }
    request = replace(
        _dfd_request("journey:dfd:forged-source-result"),
        projection=replace(base, source_manifest_validation_result=forged),
        analysis_artifacts=_dfd_analysis_drafts()[:3],
    )
    result = root.facade.run_research_workflow(request)
    view = root.facade.get_workspace(
        "security_duofuduo",
        result.research_snapshot_id,
    )["research_views"][0]
    assert view["audit"]["permissions"]["formal_per_share_valuation"] is False
    root.close()


def test_cyclical_model_golden_is_separate_from_duofuduo_evidence() -> None:
    request = cyclical_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    result = ScenarioValuationEngine().run(request)

    assert graph.template_id == "cyclical_resource_driver_graph@1"
    assert request.base_forecast_request.security.security_id != "002407.SZ"
    for scenario in result.scenarios:
        assert scenario.method("fcff_dcf").status == "blocked"
        assert scenario.method("mid_cycle_ev_ebitda").status == "ready"
        assert scenario.method("resource_nav").status == "ready"
        assert scenario.method("cyclical_historical_band").status == "ready"
        assert scenario.method("resource_nav").conditional_value_range is not None
        assert scenario.method("resource_nav").conditional_value_range.base.bridge_trace
        sensitivity = {
            item.name for item in scenario.method("resource_nav").sensitivity
        }
        assert {"commodity_price", "production_volume", "unit_cost", "maintenance_capex"} <= sensitivity
