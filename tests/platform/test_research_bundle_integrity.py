from __future__ import annotations

from copy import deepcopy
import json
from typing import Callable, Mapping

import pytest

from tests.platform.test_research_bundle_decision_projection import (
    _analysis_plan,
    _bundle,
    _identified_bundle,
)
from tests.platform.test_research_workflow import _request
from trading_platform.domain.research_bundle import (
    verify_research_evaluation_bundle,
)
from trading_platform.domain.research_evaluation import (
    ResearchDecisionViewFactory,
)
from trading_platform.identity import canonical_hash


EXPECTED_MEMBERS = ("member_official", "member_market")


def _build(
    bundle: Mapping[str, object], analysis_plan=None
) -> Mapping[str, object]:
    request = _request("bundle:integrity")
    canonical_plan = _analysis_plan(request)
    candidate_plan = analysis_plan or canonical_plan
    return ResearchDecisionViewFactory().build(
        workflow_run_id="workflow_bundle_integrity",
        request=request,
        evaluation_bundle=bundle,
        model_identity="engine@test",
        source_policy_identity="source-policy@test",
        expected_snapshot_member_ids=EXPECTED_MEMBERS,
        analysis_plan=candidate_plan,
        expected_analysis_plan_identity=canonical_plan["plan_identity"],
    )


def _tamper_bundle_id(bundle: dict[str, object]) -> None:
    bundle["bundle_id"] = "research_bundle_tampered"


def _tamper_origin_id(bundle: dict[str, object]) -> None:
    origin = bundle["origin"]
    assert isinstance(origin, dict)
    origin["origin_id"] = "research_origin_tampered"


def _tamper_component_id(bundle: dict[str, object]) -> None:
    forecast = bundle["forecast"]
    assert isinstance(forecast, dict)
    forecast["artifact_id"] = "forecast_tampered"


@pytest.mark.parametrize(
    "tamper",
    (_tamper_bundle_id, _tamper_origin_id, _tamper_component_id),
)
def test_factory_rejects_tampered_bundle_identities(
    tamper: Callable[[dict[str, object]], None],
) -> None:
    bundle = deepcopy(_identified_bundle(_bundle(ready=True)))
    assert isinstance(bundle, dict)
    tamper(bundle)

    with pytest.raises(ValueError):
        _build(bundle)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("data_snapshot_id", "snapshot_other"),
        ("source_policy_identity", "source-policy@other"),
        ("evaluation_plan_identity", "evaluation_plan_other"),
        ("snapshot_member_ids", ["member_official"]),
    ),
)
def test_factory_rejects_analysis_plan_context_drift(
    field: str,
    value: object,
) -> None:
    plan = deepcopy(_analysis_plan(_request("bundle:integrity")))
    plan[field] = value

    with pytest.raises(
        ValueError,
        match="RESEARCH_ANALYSIS_PLAN_CONTEXT_MISMATCH",
    ):
        _build(_identified_bundle(_bundle(ready=True)), plan)


def test_factory_rejects_tampered_analysis_plan_hash() -> None:
    plan = deepcopy(_analysis_plan(_request("bundle:integrity")))
    plan["plan_identity"] = "research_analysis_plan_tampered"
    bundle = _identified_bundle(_bundle(ready=True))

    with pytest.raises(
        ValueError,
        match="RESEARCH_ANALYSIS_PLAN_IDENTITY_MISMATCH",
    ):
        _build(bundle, plan)


def test_factory_rejects_self_resigned_noncanonical_analysis_node() -> None:
    plan = deepcopy(_analysis_plan(_request("bundle:integrity")))
    nodes = plan["nodes"]
    assert isinstance(nodes, list)
    forecast = next(
        node for node in nodes if node["node_id"] == "forecast"
    )
    forecast["output_contract"] = "ForgedForecast@1"
    canonical_content = {
        key: value for key, value in plan.items() if key != "plan_identity"
    }
    plan["plan_identity"] = (
        "research_analysis_plan_"
        + canonical_hash(canonical_content)[:24]
    )

    with pytest.raises(
        ValueError,
        match="RESEARCH_ANALYSIS_PLAN_IDENTITY_MISMATCH",
    ):
        _build(_identified_bundle(_bundle(ready=True)), plan)


def test_factory_rejects_bundle_from_another_research_policy() -> None:
    bundle = deepcopy(_bundle(ready=True))
    origin = bundle["origin"]
    assert isinstance(origin, dict)
    origin["research_policy_identity"] = "ResearchEvaluationPolicy@2"

    with pytest.raises(
        ValueError,
        match="RESEARCH_EVALUATION_POLICY_MISMATCH",
    ):
        _build(_identified_bundle(bundle))


def test_verifier_requires_the_exact_frozen_snapshot_members() -> None:
    bundle = deepcopy(_bundle(ready=True))
    assert isinstance(bundle, dict)
    origin = bundle["origin"]
    assert isinstance(origin, dict)
    origin["snapshot_member_ids"] = [
        "member_official",
        "member_market",
        "member_alien",
    ]
    identified = _identified_bundle(bundle)

    with pytest.raises(ValueError, match="RESEARCH_BUNDLE_ORIGIN_MISMATCH"):
        verify_research_evaluation_bundle(
            identified,
            expected_data_snapshot_id="snapshot_filing",
            expected_source_policy_identity="source-policy@test",
            expected_snapshot_member_ids=EXPECTED_MEMBERS,
        )


def test_verifier_rejects_component_lineage_outside_the_origin() -> None:
    bundle = deepcopy(_bundle(ready=True))
    assert isinstance(bundle, dict)
    forecast = bundle["forecast"]
    assert isinstance(forecast, dict)
    forecast["source_member_ids"] = ["member_alien"]
    identified = _identified_bundle(bundle)

    with pytest.raises(
        ValueError,
        match="RESEARCH_BUNDLE_COMPONENT_LINEAGE_INVALID",
    ):
        verify_research_evaluation_bundle(
            identified,
            expected_data_snapshot_id="snapshot_filing",
            expected_source_policy_identity="source-policy@test",
            expected_snapshot_member_ids=EXPECTED_MEMBERS,
        )


def test_formal_valuation_ignores_contradictory_raw_run_valuation() -> None:
    bundle = deepcopy(_bundle(ready=True))
    assert isinstance(bundle, dict)
    research_run = bundle["research_run"]
    assert isinstance(research_run, dict)
    research_run["methods"] = {
        "contradictory_raw_method": {
            "method_id": "contradictory_raw_method",
            "label": "CONTRADICTORY_RAW_LABEL",
            "status": "ready",
            "explanation": "CONTRADICTORY_RAW_EXPLANATION",
            "metrics": {"per_share_value": "999999"},
        }
    }
    synthesis = research_run["synthesis"]
    assert isinstance(synthesis, dict)
    synthesis["valuation_view"] = "CONTRADICTORY_RAW_NARRATIVE"

    projected = _build(_identified_bundle(bundle))
    formal = projected["valuation_view"]
    assert isinstance(formal, Mapping)
    serialized_formal = json.dumps(formal, ensure_ascii=False)

    assert [item["method_id"] for item in formal["methods"]] == ["fcff_dcf"]
    assert "CONTRADICTORY_RAW" not in serialized_formal
    assert (
        projected["audit"]["synthesis"]["valuation_view"]
        == "CONTRADICTORY_RAW_NARRATIVE"
    )
    assert "contradictory_raw_method" in projected["audit"]["methods"]


def test_local_component_states_override_non_integrity_raw_run_status() -> None:
    bundle = deepcopy(_bundle(ready=True))
    assert isinstance(bundle, dict)
    research_run = bundle["research_run"]
    assert isinstance(research_run, dict)
    research_run["status"] = "blocked"
    research_run["integrity_issues"] = []

    projected = _build(_identified_bundle(bundle))

    assert projected["status"] == "completed"
    assert projected["valuation_view"]["status"] == "ready"


def test_actual_global_integrity_failure_blocks_the_decision_view() -> None:
    bundle = deepcopy(_bundle(ready=True))
    assert isinstance(bundle, dict)
    research_run = bundle["research_run"]
    assert isinstance(research_run, dict)
    research_run["integrity_issues"] = [
        {
            "severity": "error",
            "code": "SOURCE_MANIFEST_INTEGRITY_FAILED",
            "message": "A frozen source failed structural validation.",
            "path": "sources[0]",
        }
    ]

    projected = _build(_identified_bundle(bundle))

    assert projected["status"] == "blocked"
    assert projected["valuation_view"]["status"] == "blocked"

