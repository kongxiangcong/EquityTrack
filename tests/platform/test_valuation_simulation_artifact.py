from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from equity_research import DeterministicValueFallback, ValuationSimulationEngine
from tests.platform.test_outlook_artifacts import _drafts, _request
from tests.platform.test_research_workflow import CountingEngine, _root
from tests.test_valuation_simulation import distribution, request
from trading_platform import ProductionCompositionRoot
from trading_platform.domain.workflow import ImmutableArtifactDraft


def _simulation_drafts() -> tuple[ImmutableArtifactDraft, ...]:
    deterministic = _drafts()
    valuation = deterministic[-1]
    scenario = valuation.payload["scenarios"][0]
    method = next(
        item
        for item in scenario["methods"]
        if item["status"] == "ready"
        and item["conditional_value_range"] is not None
    )
    value_range = method["conditional_value_range"]
    quantities = {
        label: value_range[label]["per_share_value"]
        for label in ("low", "base", "high")
    }
    fallback = DeterministicValueFallback(
        scenario_id=scenario["scenario_id"],
        method_id=method["method_id"],
        formula_version=method["formula_version"],
        low=Decimal(quantities["low"]["normalized_value"]),
        base=Decimal(quantities["base"]["normalized_value"]),
        high=Decimal(quantities["high"]["normalized_value"]),
        unit=quantities["base"]["unit"],
        currency=quantities["base"]["currency"],
        period=quantities["base"]["period"],
        output_level="per_share_value",
    )
    assumptions = (distribution("volume_growth"), distribution("margin"))
    coefficients = ("3", "8")
    with localcontext() as context:
        context.prec = 80
        reference_effect = sum(
            (
                Decimal(coefficient)
                * assumption.reference_value
                * assumption.scale
                for assumption, coefficient in zip(
                    assumptions,
                    coefficients,
                    strict=True,
                )
            ),
            Decimal("0"),
        )
        intercept = fallback.base - reference_effect
    simulation_request = replace(
        request(
            assumptions,
            matrix=(("1", "0.4"), ("0.4", "1")),
            coefficients=coefficients,
            intercept=str(intercept),
        ),
        security_id=valuation.subject_id,
        as_of=valuation.as_of,
        valuation_source_identity=valuation.source_identity,
        deterministic_fallback=fallback,
    )
    result = ValuationSimulationEngine().run(simulation_request)
    simulation = ImmutableArtifactDraft.from_valuation_simulation(
        result,
        valuation_artifact=valuation,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    return (*deterministic, simulation)


def test_simulation_artifact_persists_as_valuation_child_and_replays(
    tmp_path: Path,
) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    drafts = _simulation_drafts()
    first = root.facade.run_research_workflow(
        _request("simulation-artifact:first", drafts)
    )
    artifacts = tuple(
        root.facade.get_research_artifact(record_id)
        for record_id in first.artifact_record_ids
    )

    assert [item.artifact_kind for item in artifacts] == [
        "DataSnapshot",
        "Forecast",
        "Valuation",
        "Simulation",
    ]
    simulation = artifacts[-1]
    assert simulation.status == "ready"
    assert simulation.dependency_record_ids == (artifacts[-2].artifact_record_id,)
    assert simulation.payload["converged"] is True
    assert simulation.payload["quantiles"]["p50"]
    assert simulation.summary["valuation_input_fingerprint"] == drafts[-2].content_hash
    workspace = root.facade.get_workspace(
        "security_yihua",
        first.research_snapshot_id,
    )
    simulation_view = workspace["research_views"][0]["valuation_simulation"]
    assert simulation_view is None
    root.close()

    rebuilt = ProductionCompositionRoot(tmp_path, research_engine=engine)
    replay = rebuilt.facade.run_research_workflow(
        _request("simulation-artifact:replay", _simulation_drafts())
    )
    assert replay.artifact_record_ids == first.artifact_record_ids
    assert (
        rebuilt.facade.get_research_artifact(replay.artifact_record_ids[-1]).content_hash
        == simulation.content_hash
    )
    rebuilt.close()


def test_simulation_fallback_must_match_exact_parent_scenario_method_and_range() -> None:
    drafts = _simulation_drafts()
    valuation = drafts[-2]
    simulation = drafts[-1]
    result = ValuationSimulationEngine().run(
        replace(
            request((distribution("volume_growth"),)),
            security_id=valuation.subject_id,
            as_of=valuation.as_of,
            valuation_source_identity=valuation.source_identity,
        )
    )
    with pytest.raises(
        ValueError,
        match="RESEARCH_ARTIFACT_SIMULATION_FALLBACK_INVALID",
    ):
        ImmutableArtifactDraft.from_valuation_simulation(
            result,
            valuation_artifact=valuation,
            model_identity="company-outlook-model@1",
            policy_identity="company-outlook-policy@1",
        )

    assert simulation.payload["deterministic_fallback"]["scenario_id"]
    assert simulation.payload["deterministic_fallback"]["method_id"]
    assert simulation.payload["deterministic_fallback"]["formula_version"]
