from dataclasses import replace
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from equity_research import ResearchEngine, ResearchRequest
from trading_platform.domain.research_inputs import ResearchInputs
from equity_research.forecast import (
    CompanyArchetype,
    CompanyOpeningBalanceSheet,
    DataInsufficientForecastRequest,
    DataInsufficientSnapshot,
    DataSnapshot,
    ForecastEdge,
    ForecastEngine,
    ForecastAssumption,
    ForecastInvariantError,
    ForecastNodeKind,
    ForecastQuantity,
    ForecastRequest,
    Security,
    SegmentBaseline,
    SegmentForecastOverride,
    SnapshotFact,
)


def test_forecast_build_owns_typed_data_insufficient_degradation() -> None:
    snapshot = DataInsufficientSnapshot(
        "snapshot_missing",
        "security_missing",
        AS_OF,
        ("official_financial_statements",),
    )
    request = DataInsufficientForecastRequest(
        Security(
            "security_missing",
            "Missing-data subject",
            "SZSE",
            "CNY",
            CompanyArchetype.GENERAL_MANUFACTURING,
            ("company",),
        ),
        AS_OF,
        snapshot,
        ("2027E",),
        "2026-08-07",
    )

    graph = ForecastEngine().build(request)

    assert graph.template_id == "data_insufficient@1"
    assert {node.quantity.unit for node in graph.nodes} == {"availability_state"}
    with pytest.raises(ForecastInvariantError):
        DataInsufficientForecastRequest(
            request.security,
            AS_OF,
            snapshot,
            ("2027FY",),
            request.review_date,
        )


AS_OF = "2026-07-07"
FORECAST_SOURCE_ID = "SRC_FORECAST_OFFICIAL"


def contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_float(item) for item in value)
    return False


def quantity(
    value: str,
    unit: str,
    ref: str,
    *,
    currency: str = "CNY",
    period: str = "2025FY",
) -> ForecastQuantity:
    return ForecastQuantity(
        value=Decimal(value),
        unit=unit,
        scale=Decimal("1"),
        currency=currency,
        period=period,
        as_of=AS_OF,
        lineage_refs=(f"Fact:{ref}",),
    )


def baseline(
    segment_id: str,
    *,
    volume: str,
    asp: str,
    capacity: str,
    unit_cost: str,
    operating_expense: str,
    capex: str,
    working_capital: str,
    depreciation: str,
) -> SegmentBaseline:
    return SegmentBaseline(
        segment_id=segment_id,
        volume=quantity(volume, "units", f"{segment_id}:volume", currency="N/A"),
        asp=quantity(asp, "CNY/unit", f"{segment_id}:asp"),
        capacity=quantity(capacity, "units", f"{segment_id}:capacity", currency="N/A"),
        utilization=quantity(
            "1", "decimal", f"{segment_id}:utilization", currency="N/A"
        ),
        unit_cost=quantity(unit_cost, "CNY/unit", f"{segment_id}:unit_cost"),
        operating_expense=quantity(operating_expense, "CNY", f"{segment_id}:opex"),
        capex=quantity(capex, "CNY", f"{segment_id}:capex"),
        working_capital=quantity(
            working_capital, "CNY", f"{segment_id}:working_capital"
        ),
        depreciation=quantity(depreciation, "CNY", f"{segment_id}:depreciation"),
        tax_rate=quantity("0.25", "decimal", f"{segment_id}:tax_rate", currency="N/A"),
    )


def opening_balance_sheet() -> CompanyOpeningBalanceSheet:
    return CompanyOpeningBalanceSheet(
        cash=quantity("200", "CNY", "company:cash"),
        working_capital=quantity("350", "CNY", "company:working_capital"),
        net_ppe=quantity("1000", "CNY", "company:net_ppe"),
        other_assets=quantity("100", "CNY", "company:other_assets"),
        debt=quantity("400", "CNY", "company:debt"),
        other_liabilities=quantity(
            "250",
            "CNY",
            "company:other_liabilities",
        ),
        equity=quantity("1000", "CNY", "company:equity"),
    )


def snapshot_facts(
    baselines: tuple[SegmentBaseline, ...],
    opening: CompanyOpeningBalanceSheet,
) -> tuple[SnapshotFact, ...]:
    bound_quantities = tuple(
        (
            "segment",
            baseline.segment_id,
            metric,
            f"{baseline.segment_id}_{metric}".replace("-", "_"),
            quantity,
        )
        for baseline in baselines
        for metric, quantity in baseline.named_quantities()
    ) + tuple(
        ("company", "", metric, f"company_{metric}", quantity)
        for metric, quantity in opening.named_quantities()
    )
    facts: list[SnapshotFact] = []
    for scope, segment_id, metric_id, field_name, item in bound_quantities:
        for lineage_ref in item.lineage_refs:
            fact_id = lineage_ref.removeprefix("Fact:")
            facts.append(
                SnapshotFact(
                    fact_id=fact_id,
                    subject_id="002897.SZ",
                    scope=scope,
                    segment_id=segment_id,
                    metric_id=metric_id,
                    field_name=field_name,
                    period=item.period,
                    value=item.normalized_value,
                    unit=item.unit,
                    currency=item.currency,
                    source_id=FORECAST_SOURCE_ID,
                    available_at="2026-04-29",
                    official=True,
                )
            )
    return tuple(facts)


def manifest_with_forecast_facts(
    manifest: dict,
    snapshot: DataSnapshot,
) -> dict:
    enriched = json.loads(json.dumps(manifest))
    enriched["sources"].append(
        {
            "source_id": FORECAST_SOURCE_ID,
            "tier": "official",
            "publisher": "Official Forecast Fixture",
            "title": "Typed operating and opening-balance facts",
            "url_or_api": "https://example.invalid/official-forecast-fixture",
            "retrieved_at": "2026-07-07T09:00:00+08:00",
            "report_date": "2026-04-29",
            "extracted_fields": [
                {
                    "field_name": fact.field_name,
                    "semantic_role": fact.field_name,
                    "subject_id": fact.subject_id,
                    "period": fact.period,
                    "value": format(fact.value, "f"),
                    "unit": fact.unit,
                    "currency": fact.currency,
                    "extraction_method": "typed_test_fixture",
                    "confidence": "high",
                }
                for fact in snapshot.facts
            ],
            "cross_checks": [],
        }
    )
    return enriched


def request() -> ForecastRequest:
    baselines = (
        baseline(
            "components",
            volume="100",
            asp="10",
            capacity="120",
            unit_cost="6",
            operating_expense="100",
            capex="50",
            working_capital="200",
            depreciation="20",
        ),
        baseline(
            "connectors",
            volume="50",
            asp="20",
            capacity="60",
            unit_cost="12",
            operating_expense="100",
            capex="30",
            working_capital="150",
            depreciation="15",
        ),
    )
    opening = opening_balance_sheet()
    snapshot = DataSnapshot(
        snapshot_id="ds_2025fy",
        security_id="002897.SZ",
        as_of=AS_OF,
        segment_baselines=baselines,
        company_opening_balance_sheet=opening,
        facts=snapshot_facts(baselines, opening),
    )
    return ForecastRequest(
        security=Security(
            security_id="002897.SZ",
            company_name="Worked Manufacturing Co",
            market="CN",
            reporting_currency="CNY",
            archetype=CompanyArchetype.MULTI_SEGMENT_MANUFACTURING,
            segment_ids=("components", "connectors"),
        ),
        as_of=AS_OF,
        data_snapshot=snapshot,
        forecast_periods=("2026E",),
        assumption_overrides=(
            SegmentForecastOverride(
                segment_id="components",
                period="2026E",
                demand_growth=Decimal("0.10"),
                asp_growth=Decimal("0.05"),
                capacity_growth=Decimal("0"),
                target_utilization=Decimal("0.95"),
                unit_cost_growth=Decimal("0.02"),
                operating_expense_growth=Decimal("0.03"),
                capex_growth=Decimal("0.10"),
                depreciation_growth=Decimal("0"),
                working_capital_to_revenue=Decimal("0.20"),
                tax_rate=Decimal("0.25"),
            ),
            SegmentForecastOverride(
                segment_id="connectors",
                period="2026E",
                demand_growth=Decimal("0.20"),
                asp_growth=Decimal("0"),
                capacity_growth=Decimal("0.10"),
                target_utilization=Decimal("0.90"),
                unit_cost_growth=Decimal("0"),
                operating_expense_growth=Decimal("0"),
                capex_growth=Decimal("0"),
                depreciation_growth=Decimal("0"),
                working_capital_to_revenue=Decimal("0.15"),
                tax_rate=Decimal("0.25"),
            ),
        ),
        review_date="2026-07-31",
    )


def test_multi_segment_forecast_graph_propagates_drivers_to_fcff() -> None:
    graph = ForecastEngine().build(request())

    assert graph.template_id == "manufacturing_driver_graph@2"
    assert "multi-segment manufacturing" in graph.routing_explanation
    assert graph.quantity("company.revenue.2026E").normalized_value == Decimal("2343")
    assert graph.quantity("company.fcff.2026E").normalized_value == Decimal("430.05")
    assert graph.quantity("valuation.fcff.2026E").normalized_value == Decimal("430.05")
    assert {node.kind for node in graph.nodes} == {
        ForecastNodeKind.EVENT,
        ForecastNodeKind.DRIVER,
        ForecastNodeKind.FINANCIAL_FORECAST,
        ForecastNodeKind.VALUATION_INPUT,
    }
    assert all(node.horizon == node.quantity.period for node in graph.nodes)
    assert all(node.milestone for node in graph.nodes)
    assert all(node.leading_indicators for node in graph.nodes)
    assert all(node.trigger_conditions for node in graph.nodes)
    assert all(node.invalidation_conditions for node in graph.nodes)
    assert all(node.review_date == "2026-07-31" for node in graph.nodes)
    assert all(node.lineage_refs for node in graph.nodes)
    for node_id in (
        "components.demand_event.2026E",
        "company.revenue.2026E",
        "company.ebit.2026E",
        "company.fcff.2026E",
        "valuation.fcff.2026E",
    ):
        lineage = graph.node(node_id).lineage_refs
        assert any(ref.startswith("Fact:") for ref in lineage)
        assert any(ref.startswith("Assumption:") for ref in lineage)
    assert (
        graph.quantity("company.balance_sheet_reconciliation.2026E").normalized_value
        == 0
    )
    assert (
        graph.quantity("company.cash_flow_reconciliation.2026E").normalized_value == 0
    )


def test_forecast_graph_rejects_cycles() -> None:
    graph = ForecastEngine().build(request())
    cycle_edge = ForecastEdge(
        source_id="valuation.fcff.2026E",
        target_id="company.fcff.2026E",
        formula_id="passthrough",
        operand_role="value",
        coefficient=Decimal("1"),
        source_unit="CNY",
        source_scale=Decimal("1"),
        target_unit="CNY",
        target_scale=Decimal("1"),
        period_rule="same",
        currency_rule="same",
    )

    with pytest.raises(ForecastInvariantError) as error:
        replace(graph, edges=graph.edges + (cycle_edge,))

    assert error.value.code == "FORECAST_GRAPH_CYCLE"


def test_forecast_builder_blocks_cross_currency_driver_inputs() -> None:
    subject = request()
    connectors = subject.data_snapshot.segment_baselines[1]
    bad_unit_cost = replace(connectors.unit_cost, unit="USD/unit", currency="USD")
    bad_baselines = (
        subject.data_snapshot.segment_baselines[0],
        replace(connectors, unit_cost=bad_unit_cost),
    )
    bad_snapshot = replace(
        subject.data_snapshot,
        content_hash="",
        segment_baselines=bad_baselines,
        facts=snapshot_facts(
            bad_baselines,
            subject.data_snapshot.company_opening_balance_sheet,
        ),
    )

    with pytest.raises(ForecastInvariantError) as error:
        ForecastEngine().build(replace(subject, data_snapshot=bad_snapshot))

    assert error.value.code == "FORECAST_CURRENCY_MISMATCH"


def test_forecast_request_rejects_free_mapping_overrides() -> None:
    subject = request()

    with pytest.raises(ForecastInvariantError) as error:
        replace(subject, assumption_overrides={})

    assert error.value.code == "FORECAST_OVERRIDE_TYPE_INVALID"


def test_forecast_graph_is_deterministic_and_links_prior_period_drivers() -> None:
    subject = replace(
        request(),
        forecast_periods=("2026E", "2027E"),
    )

    first = ForecastEngine().build(subject)
    second = ForecastEngine().build(subject)

    assert first.graph_id == second.graph_id
    assert first.to_dict() == second.to_dict()
    assert not contains_float(first.to_dict())
    assert any(edge.period_rule == "prior" for edge in first.edges)
    assert first.quantity("valuation.fcff.2027E").period == "2027E"
    assert (
        first.replay()["valuation.fcff.2027E"]
        == first.quantity("valuation.fcff.2027E").normalized_value
    )


def test_forecast_graph_identity_v2_covers_archetype_semantics() -> None:
    subject = request()
    financial = replace(
        subject,
        security=replace(
            subject.security,
            archetype=CompanyArchetype.FINANCIAL_INSTITUTION,
        ),
    )
    additional_assumption = ForecastAssumption(
        assumption_id="financial_regulatory_capital_policy",
        description="A distinct regulatory-capital policy assumption.",
        available_at=AS_OF,
        evidence_refs=(
            f"Fact:{subject.data_snapshot.facts[0].fact_id}",
        ),
    )

    baseline = ForecastEngine().build(financial)
    changed = ForecastEngine().build(
        replace(
            financial,
            assumptions=financial.assumptions + (additional_assumption,),
        )
    )

    assert baseline.graph_id.startswith("fg2_")
    assert changed.graph_id.startswith("fg2_")
    assert baseline.graph_id != changed.graph_id
    reviewed_later = ForecastEngine().build(
        replace(financial, review_date="2026-08-08")
    )
    assert reviewed_later.graph_id != baseline.graph_id
    general = ForecastEngine().build(
        replace(
            subject,
            security=replace(
                subject.security,
                archetype=CompanyArchetype.GENERAL_MANUFACTURING,
            ),
        )
    )
    multi_segment = ForecastEngine().build(
        replace(
            subject,
            security=replace(
                subject.security,
                archetype=CompanyArchetype.MULTI_SEGMENT_MANUFACTURING,
            ),
        )
    )
    assert general.graph_id != multi_segment.graph_id


@pytest.mark.parametrize(
    "archetype",
    tuple(CompanyArchetype),
)
def test_every_supported_archetype_uses_graph_identity_v2(
    archetype: CompanyArchetype,
) -> None:
    subject = request()

    graph = ForecastEngine().build(
        replace(subject, security=replace(subject.security, archetype=archetype))
    )

    assert graph.graph_id.startswith("fg2_")


def test_archetype_semantics_have_pairwise_distinct_graph_identities() -> None:
    subject = request()

    identities = {
        ForecastEngine()
        .build(
            replace(
                subject,
                security=replace(subject.security, archetype=archetype),
            )
        )
        .graph_id
        for archetype in CompanyArchetype
    }

    assert len(identities) == len(tuple(CompanyArchetype))


def test_forecast_graph_validates_edge_dimensions() -> None:
    graph = ForecastEngine().build(request())
    passthrough = next(
        edge for edge in graph.edges if edge.target_id == "valuation.fcff.2026E"
    )

    with pytest.raises(ForecastInvariantError) as unit_error:
        replace(
            graph,
            edges=tuple(
                (
                    replace(edge, source_unit="CNY million")
                    if edge == passthrough
                    else edge
                )
                for edge in graph.edges
            ),
        )
    assert unit_error.value.code == "FORECAST_EDGE_UNIT_MISMATCH"

    with pytest.raises(ForecastInvariantError) as period_error:
        replace(
            graph,
            edges=tuple(
                replace(edge, period_rule="prior") if edge == passthrough else edge
                for edge in graph.edges
            ),
        )
    assert period_error.value.code == "FORECAST_EDGE_PERIOD_MISMATCH"

    valuation = graph.node("valuation.fcff.2026E")
    cross_currency = replace(
        valuation,
        quantity=replace(valuation.quantity, currency="USD"),
    )
    with pytest.raises(ForecastInvariantError) as currency_error:
        replace(
            graph,
            nodes=tuple(
                cross_currency if node == valuation else node for node in graph.nodes
            ),
        )
    assert currency_error.value.code == "FORECAST_EDGE_CURRENCY_MISMATCH"


def test_forecast_router_uses_dedicated_financial_institution_shell() -> None:
    subject = request()
    financial_security = replace(
        subject.security,
        archetype=CompanyArchetype.FINANCIAL_INSTITUTION,
    )

    graph = ForecastEngine().build(
        replace(subject, security=financial_security)
    )

    assert graph.template_id == "financial_institution_valuation_shell@1"
    assert "Industrial FCFF/WACC" in graph.routing_explanation
    assert all(
        node.node_id.startswith("financial.horizon.")
        for node in graph.nodes
    )
    assert len(graph.edges) == len(subject.forecast_periods) - 1
    assert all(edge.period_rule == "prior" for edge in graph.edges)


def test_forecast_router_uses_dedicated_biopharma_pipeline_shell() -> None:
    subject = request()
    biopharma_security = replace(
        subject.security,
        archetype=CompanyArchetype.BIOPHARMA,
    )

    graph = ForecastEngine().build(
        replace(subject, security=biopharma_security)
    )

    assert graph.template_id == "biopharma_pipeline_valuation_shell@1"
    assert "Ordinary FCFF/WACC" in graph.routing_explanation
    opening_period = (
        subject.data_snapshot.company_opening_balance_sheet.cash.period
    )
    assert {
        node.node_id
        for node in graph.nodes
        if node.node_id.startswith("company.baseline.")
    } == {
        f"company.baseline.cash.{opening_period}",
        f"company.baseline.debt.{opening_period}",
    }
    assert all(
        node.node_id.startswith(
            ("biopharma.horizon.", "company.baseline.")
        )
        for node in graph.nodes
    )
    assert len(graph.edges) == len(subject.forecast_periods) - 1
    assert all(edge.period_rule == "prior" for edge in graph.edges)


def test_snapshot_hash_binds_security_and_typed_content() -> None:
    subject = request()
    snapshot = subject.data_snapshot

    with pytest.raises(ForecastInvariantError) as hash_error:
        replace(snapshot, content_hash="a" * 64)
    assert hash_error.value.code == "FORECAST_SNAPSHOT_HASH_MISMATCH"

    with pytest.raises(ForecastInvariantError) as subject_error:
        replace(subject, security=replace(subject.security, security_id="OTHER.SZ"))
    assert subject_error.value.code == "FORECAST_SNAPSHOT_SUBJECT_MISMATCH"


def test_company_opening_balance_sheet_is_sourced_and_reconciled() -> None:
    subject = request()
    graph = ForecastEngine().build(subject)

    assert not any(
        node.node_id.startswith("baseline.components.cash") for node in graph.nodes
    )
    assert graph.quantity("company.baseline.equity.2025FY").normalized_value == Decimal(
        "1000"
    )
    with pytest.raises(ForecastInvariantError) as error:
        replace(
            subject.data_snapshot.company_opening_balance_sheet,
            equity=quantity("999", "CNY", "company:equity"),
        )
    assert error.value.code == "FORECAST_OPENING_BALANCE_UNRECONCILED"


def test_snapshot_reconciliation_ignores_ambient_decimal_precision() -> None:
    subject = request()
    components, connectors = subject.data_snapshot.segment_baselines
    precise_baselines = (
        replace(
            components,
            working_capital=quantity(
                "50.2",
                "CNY",
                "components:working_capital",
            ),
        ),
        replace(
            connectors,
            working_capital=quantity(
                "50.2",
                "CNY",
                "connectors:working_capital",
            ),
        ),
    )
    opening = replace(
        subject.data_snapshot.company_opening_balance_sheet,
        working_capital=quantity("100.5", "CNY", "company:working_capital"),
        equity=quantity("750.5", "CNY", "company:equity"),
    )

    with localcontext() as context:
        context.prec = 2
        with pytest.raises(ForecastInvariantError) as error:
            replace(
                subject.data_snapshot,
                content_hash="",
                segment_baselines=precise_baselines,
                company_opening_balance_sheet=opening,
                facts=snapshot_facts(precise_baselines, opening),
            )

    assert error.value.code == "FORECAST_OPENING_WORKING_CAPITAL_MISMATCH"


def test_snapshot_rejects_unregistered_fact_lineage() -> None:
    subject = request()

    with pytest.raises(ForecastInvariantError) as error:
        replace(
            subject.data_snapshot,
            content_hash="",
            facts=subject.data_snapshot.facts[1:],
        )

    assert error.value.code == "FORECAST_FACT_REFERENCE_MISSING"


def test_snapshot_rejects_same_value_fact_from_wrong_field_path() -> None:
    subject = request()
    components, connectors = subject.data_snapshot.segment_baselines
    swapped_opex = replace(
        components.operating_expense,
        lineage_refs=("Fact:company:other_assets",),
    )

    with pytest.raises(ForecastInvariantError) as error:
        replace(
            subject.data_snapshot,
            content_hash="",
            segment_baselines=(
                replace(components, operating_expense=swapped_opex),
                connectors,
            ),
        )

    assert error.value.code == "FORECAST_FACT_BINDING_MISMATCH"


def test_snapshot_preserves_raw_segment_identity_across_canonical_collisions() -> None:
    dashed = baseline(
        "a-b",
        volume="100",
        asp="10",
        capacity="120",
        unit_cost="6",
        operating_expense="100",
        capex="50",
        working_capital="200",
        depreciation="20",
    )
    underscored = baseline(
        "a_b",
        volume="50",
        asp="20",
        capacity="60",
        unit_cost="12",
        operating_expense="100",
        capex="30",
        working_capital="150",
        depreciation="15",
    )
    opening = opening_balance_sheet()
    facts = snapshot_facts((dashed, underscored), opening)
    swapped = replace(
        dashed,
        operating_expense=replace(
            dashed.operating_expense,
            lineage_refs=("Fact:a_b:opex",),
        ),
    )

    with pytest.raises(ForecastInvariantError) as error:
        DataSnapshot(
            snapshot_id="collision",
            security_id="002897.SZ",
            as_of=AS_OF,
            segment_baselines=(swapped, underscored),
            company_opening_balance_sheet=opening,
            facts=facts,
        )

    assert error.value.code == "FORECAST_FACT_BINDING_MISMATCH"


def test_graph_replays_named_signed_operands_and_prior_working_capital() -> None:
    graph = ForecastEngine().build(request())
    change_edges = [
        edge
        for edge in graph.edges
        if edge.target_id == "company.change_working_capital.2026E"
    ]

    assert {(edge.operand_role, edge.coefficient) for edge in change_edges} == {
        ("current", Decimal("1")),
        ("prior", Decimal("-1")),
    }
    assert any(edge.period_rule == "prior" for edge in change_edges)
    assert graph.replay()["company.fcff.2026E"] == Decimal("430.05")


def test_replay_rejects_a_derived_node_with_deleted_operands() -> None:
    graph = ForecastEngine().build(request())

    with pytest.raises(ForecastInvariantError) as error:
        replace(
            graph,
            edges=tuple(
                edge for edge in graph.edges if edge.target_id != "company.tax.2026E"
            ),
        )

    assert error.value.code == "FORECAST_DERIVED_FORMULA_MISSING"


def test_graph_normalizes_exact_scale_changes_without_losing_dimensions() -> None:
    subject = request()
    components, connectors = subject.data_snapshot.segment_baselines
    scaled_opex = replace(
        components.operating_expense,
        value=Decimal("1"),
        scale=Decimal("100"),
    )
    scaled_baselines = (
        replace(components, operating_expense=scaled_opex),
        connectors,
    )
    snapshot = replace(
        subject.data_snapshot,
        content_hash="",
        segment_baselines=scaled_baselines,
        facts=snapshot_facts(
            scaled_baselines,
            subject.data_snapshot.company_opening_balance_sheet,
        ),
    )

    graph = ForecastEngine().build(replace(subject, data_snapshot=snapshot))

    assert graph.quantity(
        "components.operating_expense.2026E"
    ).normalized_value == Decimal("103")
    baseline_node = graph.node("baseline.components.operating_expense.2025FY")
    assert baseline_node.quantity.scale == Decimal("100")
    assert baseline_node.trigger_conditions[0].threshold.scale == Decimal("100")
    assert graph.replay()["company.fcff.2026E"] == Decimal("430.05")


def test_monitoring_thresholds_ignore_ambient_decimal_precision() -> None:
    subject = request()
    components, connectors = subject.data_snapshot.segment_baselines
    precise_baselines = (
        replace(
            components,
            operating_expense=quantity(
                "123.456789",
                "CNY",
                "components:opex",
            ),
        ),
        connectors,
    )
    snapshot = replace(
        subject.data_snapshot,
        content_hash="",
        segment_baselines=precise_baselines,
        facts=snapshot_facts(
            precise_baselines,
            subject.data_snapshot.company_opening_balance_sheet,
        ),
    )
    precise_request = replace(subject, data_snapshot=snapshot)
    expected = ForecastEngine().build(precise_request)

    with localcontext() as context:
        context.prec = 2
        constrained = ForecastEngine().build(precise_request)

    node_id = "baseline.components.operating_expense.2025FY"
    expected_threshold = expected.node(node_id).trigger_conditions[0].threshold
    constrained_threshold = constrained.node(node_id).trigger_conditions[0].threshold
    assert expected_threshold == constrained_threshold
    assert expected_threshold.normalized_value == Decimal("12.34567890")


def test_three_statements_reconcile_before_fcff() -> None:
    graph = ForecastEngine().build(request())
    values = graph.replay()

    assert values["company.gross_profit.2026E"] == (
        values["company.revenue.2026E"] - values["company.cogs.2026E"]
    )
    assert values["company.ebit.2026E"] == (
        values["company.gross_profit.2026E"]
        - values["company.operating_expense.2026E"]
        - values["company.depreciation.2026E"]
    )
    assert values["company.net_cash_change.2026E"] == (
        values["company.cash_flow_from_operations.2026E"]
        + values["company.cash_flow_from_investing.2026E"]
        + values["company.cash_flow_from_financing.2026E"]
    )
    assert (
        values["company.assets.2026E"] == values["company.liabilities_and_equity.2026E"]
    )
    assert values["company.fcff.2026E"] == (
        values["company.cash_flow_from_operations.2026E"]
        - values["company.capex.2026E"]
    )


def test_consolidated_tax_offsets_segment_losses() -> None:
    subject = request()
    components, connectors = subject.data_snapshot.segment_baselines
    loss_baselines = (
        replace(
            components,
            operating_expense=quantity("280", "CNY", "components:opex"),
        ),
        replace(
            connectors,
            operating_expense=quantity("485", "CNY", "connectors:opex"),
        ),
    )
    snapshot = replace(
        subject.data_snapshot,
        content_hash="",
        segment_baselines=loss_baselines,
        facts=snapshot_facts(
            loss_baselines,
            subject.data_snapshot.company_opening_balance_sheet,
        ),
    )
    no_growth = tuple(
        replace(
            override,
            demand_growth=Decimal("0"),
            asp_growth=Decimal("0"),
            capacity_growth=Decimal("0"),
            target_utilization=Decimal("1"),
            unit_cost_growth=Decimal("0"),
            operating_expense_growth=Decimal("0"),
            capex_growth=Decimal("0"),
            depreciation_growth=Decimal("0"),
        )
        for override in subject.assumption_overrides
    )
    graph = ForecastEngine().build(
        replace(subject, data_snapshot=snapshot, assumption_overrides=no_growth)
    )

    assert graph.quantity("components.ebit.2026E").normalized_value == Decimal("100")
    assert graph.quantity("connectors.ebit.2026E").normalized_value == Decimal("-100")
    assert graph.quantity("company.ebit.2026E").normalized_value == Decimal("0")
    assert graph.quantity("company.tax.2026E").normalized_value == Decimal("0")


def test_tax_consensus_preserves_exact_rate_for_three_segments() -> None:
    subject = request()
    components, connectors = subject.data_snapshot.segment_baselines
    sensors = baseline(
        "sensors",
        volume="50",
        asp="20",
        capacity="60",
        unit_cost="12",
        operating_expense="100",
        capex="30",
        working_capital="150",
        depreciation="15",
    )
    opening = replace(
        subject.data_snapshot.company_opening_balance_sheet,
        working_capital=quantity("500", "CNY", "company:working_capital"),
        equity=quantity("1150", "CNY", "company:equity"),
    )
    snapshot = replace(
        subject.data_snapshot,
        content_hash="",
        segment_baselines=(components, connectors, sensors),
        company_opening_balance_sheet=opening,
        facts=snapshot_facts((components, connectors, sensors), opening),
    )
    sensors_override = replace(
        subject.assumption_overrides[1],
        segment_id="sensors",
    )
    three_segment = replace(
        subject,
        security=replace(
            subject.security,
            segment_ids=("components", "connectors", "sensors"),
        ),
        data_snapshot=snapshot,
        assumption_overrides=subject.assumption_overrides + (sensors_override,),
    )

    graph = ForecastEngine().build(three_segment)

    assert graph.quantity("company.tax_rate.2026E").normalized_value == Decimal("0.25")
    tax_edges = [
        edge for edge in graph.edges if edge.target_id == "company.tax_rate.2026E"
    ]
    assert len(tax_edges) == 3
    assert all(edge.formula_id.value == "consensus" for edge in tax_edges)


def test_product_algebra_rejects_per_unit_currency_mismatch() -> None:
    graph = ForecastEngine().build(request())
    asp = graph.node("components.asp.2026E")
    bad_asp = replace(
        asp,
        quantity=replace(asp.quantity, currency="USD"),
        trigger_conditions=tuple(
            replace(
                condition,
                threshold=replace(condition.threshold, currency="USD"),
            )
            for condition in asp.trigger_conditions
        ),
        invalidation_conditions=tuple(
            replace(
                condition,
                threshold=replace(condition.threshold, currency="USD"),
            )
            for condition in asp.invalidation_conditions
        ),
    )
    with pytest.raises(ForecastInvariantError) as error:
        replace(
            graph,
            nodes=tuple(bad_asp if node == asp else node for node in graph.nodes),
            edges=tuple(
                (
                    replace(edge, currency_rule="not_applicable")
                    if edge.source_id == asp.node_id or edge.target_id == asp.node_id
                    else edge
                )
                for edge in graph.edges
            ),
        )
    assert error.value.code == "FORECAST_EDGE_UNIT_MISMATCH"


def test_valuation_input_is_blocked_by_statement_reconciliation() -> None:
    graph = ForecastEngine().build(request())
    check = graph.node("company.balance_sheet_reconciliation.2026E")
    assets = graph.quantity("company.assets.2026E").normalized_value
    bad_check = replace(
        check,
        quantity=replace(check.quantity, value=assets * Decimal("0.01")),
    )
    with pytest.raises(ForecastInvariantError) as error:
        replace(
            graph,
            nodes=tuple(bad_check if node == check else node for node in graph.nodes),
            edges=tuple(
                (
                    replace(edge, coefficient=Decimal("-0.99"))
                    if edge.target_id == check.node_id
                    and edge.operand_role == "liabilities_and_equity"
                    else edge
                )
                for edge in graph.edges
            ),
        )
    assert error.value.code == "FORECAST_STATEMENT_RECONCILIATION_FAILED"


def test_valuation_blocks_negative_cash_debt_or_net_ppe_balances() -> None:
    subject = request()
    overrides = (
        replace(subject.assumption_overrides[0], debt_change=Decimal("-1000")),
        subject.assumption_overrides[1],
    )

    with pytest.raises(ForecastInvariantError) as error:
        ForecastEngine().build(replace(subject, assumption_overrides=overrides))

    assert error.value.code == "FORECAST_ECONOMIC_BALANCE_INVALID"


def test_negative_net_working_capital_is_supported_when_sourced() -> None:
    subject = request()
    components, connectors = subject.data_snapshot.segment_baselines
    negative_baselines = (
        replace(
            components,
            working_capital=quantity(
                "-100",
                "CNY",
                "components:working_capital",
            ),
        ),
        replace(
            connectors,
            working_capital=quantity(
                "-50",
                "CNY",
                "connectors:working_capital",
            ),
        ),
    )
    opening = replace(
        subject.data_snapshot.company_opening_balance_sheet,
        working_capital=quantity("-150", "CNY", "company:working_capital"),
        equity=quantity("500", "CNY", "company:equity"),
    )
    snapshot = replace(
        subject.data_snapshot,
        content_hash="",
        segment_baselines=negative_baselines,
        company_opening_balance_sheet=opening,
        facts=snapshot_facts(negative_baselines, opening),
    )
    overrides = (
        replace(
            subject.assumption_overrides[0],
            working_capital_to_revenue=Decimal("-0.10"),
        ),
        replace(
            subject.assumption_overrides[1],
            working_capital_to_revenue=Decimal("-0.05"),
        ),
    )

    graph = ForecastEngine().build(
        replace(
            subject,
            data_snapshot=snapshot,
            assumption_overrides=overrides,
        )
    )

    assert graph.quantity("company.working_capital.2026E").normalized_value < 0
    assert (
        graph.quantity("valuation.fcff.2026E").normalized_value
        == graph.quantity("company.fcff.2026E").normalized_value
    )


def test_monitoring_references_resolve_and_match_dimensions() -> None:
    graph = ForecastEngine().build(request())
    ids = {node.node_id for node in graph.nodes}

    for node in graph.nodes:
        assert all(item.metric_id in ids for item in node.leading_indicators)
        for condition in node.trigger_conditions + node.invalidation_conditions:
            metric = graph.quantity(condition.metric_id)
            assert (
                condition.threshold.unit,
                condition.threshold.scale,
                condition.threshold.currency,
                condition.threshold.period,
            ) == (metric.unit, metric.scale, metric.currency, metric.period)

    target = graph.node("company.revenue.2026E")
    bad_condition = replace(
        target.trigger_conditions[0],
        metric_id="missing.metric",
    )
    with pytest.raises(ForecastInvariantError) as error:
        replace(
            graph,
            nodes=tuple(
                (
                    replace(target, trigger_conditions=(bad_condition,))
                    if node == target
                    else node
                )
                for node in graph.nodes
            ),
        )
    assert error.value.code == "FORECAST_MONITORING_REFERENCE_MISSING"


def test_lineage_is_metric_specific_and_propagates_declared_inputs() -> None:
    graph = ForecastEngine().build(request())
    volume = graph.node("components.volume.2026E")
    tax = graph.node("company.tax.2026E")

    assert not any("tax_rate" in ref for ref in volume.lineage_refs)
    assert any("demand_growth" in ref for ref in volume.lineage_refs)
    assert any("tax_rate" in ref for ref in tax.lineage_refs)
    assert any("opex" in ref for ref in tax.lineage_refs)


def test_research_engine_uses_typed_inputs_with_forecast_graph() -> None:
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "yihua-002897"
            / "source_manifest.json"
        ).read_text(encoding="utf-8")
    )
    typed_request = request()
    manifest = manifest_with_forecast_facts(manifest, typed_request.data_snapshot)
    first = ResearchEngine().run(
        ResearchRequest(
            manifest=manifest,
            as_of_date=AS_OF,
            research_inputs=ResearchInputs.from_mapping({"report_version": 0, "analyses": {"baseline": "accepted"}}),
            forecast_request=typed_request,
        )
    )
    second = ResearchEngine().run(
        ResearchRequest(
            manifest=manifest,
            as_of_date=AS_OF,
            research_inputs=ResearchInputs.from_mapping({
                "report_version": 0,
                "analyses": {"different_payload": True},
                "debate": {"case": True},
                "synthesis": {"case": True},
            }),
            forecast_request=typed_request,
        )
    )

    assert first.report_mode == "audit_report"
    assert first.summary["forecast_graph"] == second.summary["forecast_graph"]
    assert (
        first.summary["forecast_graph"]["graph_id"]
        == ForecastEngine().build(typed_request).graph_id
    )
    assert "nodes" not in first.summary["forecast_graph"]


def test_research_engine_rejects_cross_security_forecast() -> None:
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "duofuduo-002407"
            / "source_manifest.json"
        ).read_text(encoding="utf-8")
    )

    with pytest.raises(ForecastInvariantError) as error:
        ResearchEngine().run(
            ResearchRequest(
                manifest=manifest,
                as_of_date=AS_OF,
                research_inputs=ResearchInputs(),
                forecast_request=request(),
            )
        )

    assert error.value.code == "FORECAST_RESEARCH_SECURITY_MISMATCH"


def test_research_engine_rejects_fact_not_exactly_bound_to_manifest() -> None:
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "yihua-002897"
            / "source_manifest.json"
        ).read_text(encoding="utf-8")
    )
    typed_request = request()
    enriched = manifest_with_forecast_facts(manifest, typed_request.data_snapshot)
    enriched["sources"][-1]["extracted_fields"][0]["value"] = "999999"

    with pytest.raises(ForecastInvariantError) as error:
        ResearchEngine().run(
            ResearchRequest(
                manifest=enriched,
                as_of_date=AS_OF,
                research_inputs=ResearchInputs(),
                forecast_request=typed_request,
            )
        )

    assert error.value.code == "FORECAST_FACT_MANIFEST_MISMATCH"


def test_forecast_assumption_must_resolve_to_frozen_fact_lineage() -> None:
    unresolved = ForecastAssumption(
        assumption_id="unresolved_case@1",
        description="A typed analyst condition with deliberately missing lineage.",
        available_at=AS_OF,
        evidence_refs=("Fact:missing:basis",),
    )

    with pytest.raises(ForecastInvariantError) as error:
        replace(request(), assumptions=(unresolved,))

    assert error.value.code == "FORECAST_ASSUMPTION_EVIDENCE_INVALID"
