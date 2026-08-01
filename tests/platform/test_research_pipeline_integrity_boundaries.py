from __future__ import annotations

from equity_research import ResearchEngine
from equity_research.scenario_valuation import (
    DataInsufficientScenarioRequest,
    DeterministicScenarioRequest,
    ScenarioInvariantError,
    ScenarioValuationEngine,
)

from tests.platform.test_financial_pipeline_bundle_applicability import (
    _request_and_evidence,
)
from trading_platform.domain.research_bundle import ResearchComponentStatus
from trading_platform.domain.research_evaluation import (
    ResearchDecisionViewFactory,
)
from trading_platform.research import ResearchEvaluation


def test_component_inputs_remain_traceable_metadata_without_becoming_facts() -> None:
    request, evidence = _request_and_evidence()

    bundle = ResearchEvaluation(ResearchEngine()).evaluate(request, evidence)

    expected_member_ids = tuple(
        member.normalized_version_id for member in evidence.member_evidence
    )
    sources = bundle.research_run["sources"]
    assert {source["publisher"] for source in sources} == {
        "official_model_facts",
        "confirmed_model_assumptions",
    }
    assert bundle.research_run["evidence"] == []
    assert bundle.research_run["status"] != "blocked"
    assert not any(
        issue["code"] == "SOURCES_MISSING"
        for issue in bundle.research_run["integrity_issues"]
    )
    assert tuple(bundle.origin.snapshot_member_ids) == expected_member_ids
    for component in (
        bundle.forecast,
        bundle.scenario_valuation,
        bundle.valuation_method_route,
        bundle.valuation_simulation_decision,
        bundle.market_path_decision,
        bundle.recent_trend_assessment,
    ):
        assert set(component.source_member_ids).issubset(expected_member_ids)

    view = ResearchDecisionViewFactory().build(
        workflow_run_id="workflow_model_metadata",
        request=request,
        evaluation_bundle=bundle.to_dict(),
        model_identity="engine@test",
        source_policy_identity=evidence.source_policy_identity,
        expected_snapshot_member_ids=expected_member_ids,
    )
    assert view["status"] == "completed_with_limits"
    assert view["valuation_view"]["status"] in {"ready", "limited"}


def test_scenario_engine_failure_preserves_the_complete_forecast(
    monkeypatch,
) -> None:
    request, evidence = _request_and_evidence()
    original_run = ScenarioValuationEngine.run

    def fail_deterministic_scenario(
        self: ScenarioValuationEngine,
        scenario_request: (
            DeterministicScenarioRequest | DataInsufficientScenarioRequest
        ),
    ):
        if isinstance(scenario_request, DeterministicScenarioRequest):
            raise ScenarioInvariantError(
                "SCENARIO_TEST_FAILURE",
                "Synthetic scenario-only engine failure.",
            )
        return original_run(self, scenario_request)

    monkeypatch.setattr(
        ScenarioValuationEngine,
        "run",
        fail_deterministic_scenario,
    )

    bundle = ResearchEvaluation(ResearchEngine()).evaluate(request, evidence)

    assert bundle.forecast.status is ResearchComponentStatus.COMPLETE
    assert (
        bundle.forecast.content["template_id"]
        == "manufacturing_driver_graph@2"
    )
    assert (
        bundle.scenario_valuation.status
        is ResearchComponentStatus.BLOCKED
    )
    assert bundle.scenario_valuation.reason_codes == (
        "RESEARCH_MODEL_ENGINE_INPUT_INVALID",
    )
    assert (
        bundle.scenario_valuation.source_member_ids
        == bundle.forecast.source_member_ids
    )

