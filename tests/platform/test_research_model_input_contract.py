from __future__ import annotations

from dataclasses import replace

import pytest

from tests.platform.test_financial_pipeline_bundle_applicability import (
    _request_and_evidence,
)
from trading_platform.research.analysis_plan import (
    ResearchAnalysisPlanCompiler,
)


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    (
        ({"period": ""}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"unit": ""}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"currency": ""}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"value": None}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"value": 1.5}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        ({"value": True}, "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"),
        (
            {"subject_id": "security_other"},
            "RESEARCH_COMPONENT_INPUT_SUBJECT_INVALID",
        ),
    ),
)
def test_capability_binding_rejects_malformed_typed_model_fields(
    changes: dict[str, object],
    reason_code: str,
) -> None:
    request, evidence = _request_and_evidence()
    member = evidence.member_evidence[0]
    fields = tuple(
        ({**field, **changes} if index == 0 else field)
        for index, field in enumerate(member.extracted_fields)
    )
    changed = replace(
        evidence,
        member_evidence=(
            replace(member, extracted_fields=fields),
            *evidence.member_evidence[1:],
        ),
    )

    plan = ResearchAnalysisPlanCompiler().compile(
        request=request,
        evidence=changed,
    )

    assert plan.capability_binding["status"] == "limited"
    assert reason_code in plan.capability_binding["reason_codes"]


def test_capability_binding_rejects_duplicate_path_across_members() -> None:
    request, evidence = _request_and_evidence()
    member = evidence.member_evidence[0]
    duplicate = replace(
        member,
        normalized_version_id=member.normalized_version_id + "_duplicate",
        source_identity=member.source_identity + "_duplicate",
    )
    changed = replace(
        evidence,
        members={
            **evidence.members,
            duplicate.normalized_version_id: duplicate.dataset,
        },
        member_evidence=(member, duplicate, *evidence.member_evidence[1:]),
    )

    plan = ResearchAnalysisPlanCompiler().compile(
        request=request,
        evidence=changed,
    )

    assert plan.capability_binding["status"] == "limited"
    assert "RESEARCH_MODEL_INPUT_DUPLICATE" in plan.capability_binding[
        "reason_codes"
    ]
