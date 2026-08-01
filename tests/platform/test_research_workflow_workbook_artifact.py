from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import zipfile

from trading_platform.application.contracts import StartResearchWorkflow
from trading_platform.application.research_workbook import (
    OOXML_MEDIA_TYPE,
    ResearchWorkbookArtifact,
)
from trading_platform.valuation_workbook import ValuationWorkbookError

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.test_research_workflow import _request


class ReadyWorkbookProjector:
    def project(self, view) -> ResearchWorkbookArtifact:
        del view
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as workbook:
            workbook.writestr("[Content_Types].xml", "<Types />")
            workbook.writestr("xl/workbook.xml", "<workbook />")
        return ResearchWorkbookArtifact.ready(output.getvalue())


class TimeoutWorkbookProjector:
    def project(self, view) -> ResearchWorkbookArtifact:
        del view
        raise ValuationWorkbookError(
            "RESEARCH_WORKBOOK_RENDERER_TIMEOUT"
        )


def _root(
    tmp_path: Path,
    workbook_projector=None,
) -> PlatformTaskFixture:
    root = PlatformTaskFixture(
        tmp_path,
        workbook_projector=workbook_projector,
    )
    from trading_platform.application.contracts import SecurityIdentity

    root.watchlist.add(
        "watch:security_yihua",
        SecurityIdentity(
            "security_yihua",
            "SZSE",
            "002897",
            "CNY",
            "2017-09-07",
        ),
    )
    root.faults.record_official_filing_workflow_snapshot()
    return root


def test_workflow_keeps_one_typed_workbook_slot_when_renderer_is_unavailable(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)

    result = root.research.handle(
        StartResearchWorkflow(_request("workflow:workbook-limited"))
    )
    decision = root.archive.decision_view(result.workflow_run_id)
    limitation = json.loads(decision.workbook_bytes)

    assert result.workbook_status == "limited"
    assert decision.workbook_media_type == "application/json"
    assert (
        decision.workbook_schema_version
        == "ResearchWorkbookProjection@1"
    )
    assert decision.workbook_filename.endswith(".json")
    assert limitation["status"] == "limited"
    assert limitation["reason_code"] == (
        "RESEARCH_WORKBOOK_RENDERER_UNAVAILABLE"
    )
    assert tuple(
        member["member_role"]
        for member in root.archive.manifest(
            result.final_manifest_id
        ).members
    ).count("decision_view_workbook") == 1
    root.close()


def test_workflow_translates_workbook_timeout_to_one_typed_limitation(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, TimeoutWorkbookProjector())

    result = root.research.handle(
        StartResearchWorkflow(_request("workflow:workbook-timeout"))
    )
    decision = root.archive.decision_view(result.workflow_run_id)
    limitation = json.loads(decision.workbook_bytes)

    assert result.workbook_status == "limited"
    assert result.workbook_reason_code == (
        "RESEARCH_WORKBOOK_RENDERER_TIMEOUT"
    )
    assert limitation["reason_code"] == (
        "RESEARCH_WORKBOOK_RENDERER_TIMEOUT"
    )
    assert tuple(
        member["member_role"]
        for member in root.archive.manifest(
            result.final_manifest_id
        ).members
    ).count("decision_view_workbook") == 1
    root.close()


def test_workflow_commits_real_ooxml_in_the_same_workbook_slot(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, ReadyWorkbookProjector())

    result = root.research.handle(
        StartResearchWorkflow(_request("workflow:workbook-ready"))
    )
    decision = root.archive.decision_view(result.workflow_run_id)

    assert result.workbook_status == "ready"
    assert decision.workbook_media_type == OOXML_MEDIA_TYPE
    assert (
        decision.workbook_schema_version
        == "ResearchDecisionWorkbook@1"
    )
    assert decision.workbook_filename == "research-decision.xlsx"
    assert decision.workbook_bytes.startswith(b"PK")
    assert tuple(
        member["member_role"]
        for member in root.archive.manifest(
            result.final_manifest_id
        ).members
    ).count("decision_view_workbook") == 1
    root.close()
