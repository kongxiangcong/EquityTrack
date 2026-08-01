from __future__ import annotations

from copy import deepcopy
import json

from tests.platform.test_research_bundle_decision_projection import (
    _bundle,
    _identified_bundle,
)
from tests.platform.test_research_workflow import _request
from trading_platform.domain.research_evaluation import (
    ResearchDecisionViewFactory,
)


def test_contradictory_raw_valuation_is_confined_to_the_audit_appendix() -> None:
    bundle = deepcopy(_bundle(ready=True))
    assert isinstance(bundle, dict)
    research_run = bundle["research_run"]
    assert isinstance(research_run, dict)
    research_run["methods"] = {
        "raw_method": {
            "method_id": "raw_method",
            "status": "blocked",
            "explanation": "RAW_VALUATION_MARKER",
            "missing_fields": ["RAW_VALUATION_MARKER"],
        }
    }
    synthesis = research_run["synthesis"]
    assert isinstance(synthesis, dict)
    synthesis["valuation_view"] = "RAW_VALUATION_MARKER"

    projected = ResearchDecisionViewFactory().build(
        workflow_run_id="workflow_raw_valuation_audit_boundary",
        request=_request("bundle:raw-valuation-audit-boundary"),
        evaluation_bundle=_identified_bundle(bundle),
        model_identity="engine@test",
        source_policy_identity="source-policy@test",
        expected_snapshot_member_ids=(
            "member_official",
            "member_market",
        ),
    )

    decision_projection = dict(projected)
    audit = decision_projection.pop("audit")
    assert "RAW_VALUATION_MARKER" not in json.dumps(
        decision_projection,
        ensure_ascii=False,
    )
    assert "RAW_VALUATION_MARKER" in json.dumps(audit, ensure_ascii=False)

