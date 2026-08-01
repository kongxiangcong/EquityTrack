from __future__ import annotations

from trading_platform.application.contracts import StartResearchWorkflow

from tests.platform.test_research_workflow import _request, _root


def test_workflow_result_resolves_the_exact_manifest_recent_trend(
    tmp_path,
) -> None:
    root = _root(tmp_path)

    result = root.research.handle(
        StartResearchWorkflow(_request("workflow:artifact-bundle"))
    )
    assert result.recent_trend_assessment_id is not None

    assessment = root.archive.get(
        result.recent_trend_assessment_id
    )

    assert assessment.assessment_id == result.recent_trend_assessment_id
    assert assessment.data_snapshot_id == result.research_snapshot_id
    assert assessment.status == "blocked"
    assert assessment.reason_codes == (
        "RECENT_TREND_OBSERVATIONS_REQUIRED",
    )
    assessment.validate()
    root.close()
