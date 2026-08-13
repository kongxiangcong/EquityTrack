from __future__ import annotations

from dataclasses import replace


import pytest
from tests.platform.test_financial_pipeline_bundle_applicability import (
    _request_and_evidence,
)
from trading_platform.research.analysis_plan import (
    ResearchAnalysisPlanCompiler,
)


def _by_id(plan) -> dict[str, dict[str, object]]:
    return {str(node["node_id"]): dict(node) for node in plan.nodes}


def test_analysis_plan_is_closed_deterministic_and_bound_to_capabilities() -> None:
    request, evidence = _request_and_evidence()
    compiler = ResearchAnalysisPlanCompiler()

    first = compiler.compile(request=request, evidence=evidence)
    second = compiler.compile(request=request, evidence=evidence)

    assert first.identity == second.identity
    assert first.to_dict() == second.to_dict()
    assert first.capability_binding["status"] == "bound"
    assert first.layers[0] == ("evidence_binding",)
    assert first.layers[-1] == ("decision_projection",)
    nodes = _by_id(first)
    assert nodes["forecast"]["requirement"] == "required"
    assert nodes["valuation_simulation_decision"]["requirement"] == ("required")
    assert nodes["decision_projection"]["output_contract"] == ("ResearchDecisionProjection@1")
    assert all(str(node["node_hash"]) for node in first.nodes)


def test_capability_change_records_direct_and_descendant_invalidation() -> None:
    request, evidence = _request_and_evidence()
    compiler = ResearchAnalysisPlanCompiler()
    first = compiler.compile(request=request, evidence=evidence)
    changed_member = replace(
        evidence.member_evidence[0],
        normalized_version_id=(
            evidence.member_evidence[0].normalized_version_id + "_v2"
        ),
    )
    changed = replace(
        evidence,
        member_evidence=(changed_member, *evidence.member_evidence[1:]),
    )

    second = compiler.compile(request=request, evidence=changed)

    first_nodes = _by_id(first)
    second_nodes = _by_id(second)
    assert first.identity != second.identity
    assert (
        first_nodes["forecast"]["direct_capability_digest"]
        != second_nodes["forecast"]["direct_capability_digest"]
    )
    assert (
        first_nodes["recent_trend_assessment"]["direct_capability_digest"]
        == second_nodes["recent_trend_assessment"]["direct_capability_digest"]
    )
    assert all(
        first_nodes[node_id]["node_hash"] != second_nodes[node_id]["node_hash"]
        for node_id in first_nodes
    )


def test_invalid_model_field_contract_is_visible_before_calculation() -> None:
    request, evidence = _request_and_evidence()
    member = evidence.member_evidence[0]
    malformed = tuple(
        (
            {key: value for key, value in field.items() if key != "model_path"}
            if index == 0
            else field
        )
        for index, field in enumerate(member.extracted_fields)
    )
    changed = replace(
        evidence,
        member_evidence=(
            replace(member, extracted_fields=malformed),
            *evidence.member_evidence[1:],
        ),
    )

    plan = ResearchAnalysisPlanCompiler().compile(
        request=request,
        evidence=changed,
    )

    assert plan.capability_binding["status"] == "limited"
    assert plan.capability_binding["reason_codes"] == [
        "RESEARCH_MODEL_INPUT_PATH_INVALID"
    ]
