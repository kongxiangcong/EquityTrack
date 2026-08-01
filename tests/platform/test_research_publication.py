from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tests.platform.canonical_plan_journey_fixture import (
    SECURITY_ID,
    arrange_canonical_plan_journey,
)
from trading_platform.application import (
    PublishLatestResearch,
    open_research_publication,
)


def test_latest_research_publishes_openable_report_and_chart(
    tmp_path: Path,
) -> None:
    journey = arrange_canonical_plan_journey(
        tmp_path / "authority", activate=False
    )
    data_root = journey.platform.data_root
    journey.close()
    requested_at = (
        datetime.now().astimezone() + timedelta(minutes=1)
    ).isoformat()
    command = PublishLatestResearch(SECURITY_ID, requested_at)
    with open_research_publication(data_root) as publications:
        first = publications.publish(command)
        replay = publications.publish(command)

    assert replay == first
    assert first.subject == "002897.SZ"
    assert first.status == "completed_with_limits"
    assert first.data_quality_grade in {"A", "B", "C", "D"}
    assert set(first.artifact_paths) == {
        "report_html",
        "report_pdf",
        "report_json",
        "chart_html",
        "workbook",
    }
    for path in first.artifact_paths.values():
        assert path.is_file()
        assert "objects" not in path.parts
        assert "exports" in path.parts
    assert "<svg" in first.artifact_paths["chart_html"].read_text(
        encoding="utf-8"
    )
    assert "ResearchDecisionView" in first.artifact_paths[
        "report_html"
    ].read_text(encoding="utf-8")
    assert first.artifact_paths["report_pdf"].read_bytes().startswith(
        b"%PDF"
    )
    publication_dirs = tuple(
        path
        for path in (
            data_root / "exports" / "research" / first.subject / first.as_of
        ).iterdir()
        if path.is_dir()
    )
    assert len(publication_dirs) == 1