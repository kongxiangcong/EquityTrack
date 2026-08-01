from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    EvaluationHorizon,
    EvaluationPurpose,
    ResearchEvaluationPlan,
    ResearchWorkflowRequest,
    StrategyValidationSelection,
)
from trading_platform.research_pdf import ResearchDecisionPdf


def _poppler(name: str) -> tuple[str, dict[str, str]]:
    located = shutil.which(name)
    if located is None:
        raise AssertionError(f"{name} is required for PDF acceptance")
    binary = Path(located)
    bundled = (
        binary.parents[2]
        / "native"
        / "poppler"
        / "Library"
        / "bin"
        / f"{name}.exe"
    )
    if binary.suffix.lower() == ".cmd" and bundled.is_file():
        binary = bundled
    environment = dict(os.environ)
    environment["PATH"] = (
        str(binary.parent) + os.pathsep + environment.get("PATH", "")
    )
    return str(binary), environment


def _request() -> ResearchWorkflowRequest:
    return ResearchWorkflowRequest(
        schema_version="ResearchWorkflowRequest@2",
        invocation_id="research-pdf",
        security_id="security_yihua",
        requested_date="2026-07-11",
        effective_session_date="2026-07-10",
        data_snapshot_id="snapshot_filing",
        evaluation_plan=ResearchEvaluationPlan(
            schema_version="ResearchEvaluationPlan@1",
            purpose=EvaluationPurpose.COMPANY_OUTLOOK,
            horizon=EvaluationHorizon(
                as_of="2026-07-11",
                forecast_end="2028-12-31",
                review_by="2026-10-31",
            ),
            required_dimensions=(
                EvaluationDimension.SOURCE_QUALITY,
                EvaluationDimension.FORECAST,
                EvaluationDimension.VALUATION,
            ),
            strategy_validation=(
                StrategyValidationSelection.REQUESTED_UNAVAILABLE
            ),
        ),
    )


def test_pdf_is_deterministic_projection_of_persisted_view_and_renders(
    tmp_path: Path,
) -> None:
    root = PlatformTaskFixture(tmp_path)
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
    result = root.research.handle(StartResearchWorkflow(_request()))
    persisted = root.archive.decision_view(result.workflow_run_id)
    view = json.loads(persisted.json_bytes)

    projected = ResearchDecisionPdf().render(view)

    assert projected == persisted.pdf_bytes
    assert projected == ResearchDecisionPdf().render(view)
    assert persisted.pdf_artifact_id == result.pdf_artifact_id
    assert projected.startswith(b"%PDF-")
    assert b"ResearchDecisionPdf@1" in projected

    report = tmp_path / "research-decision.pdf"
    report.write_bytes(projected)
    pdfinfo, pdf_environment = _poppler("pdfinfo")
    info = subprocess.run(
        [pdfinfo, str(report)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=pdf_environment,
    )
    pages_line = next(
        line
        for line in info.stdout.splitlines()
        if line.startswith("Pages:")
    )
    assert int(pages_line.partition(":")[2].strip()) >= 2
    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(str(report)).pages
    )
    forecast_status = view["audit"]["evaluation_bundle"]["components"][
        "forecast"
    ]["status"]
    assert "Research pipeline" in pdf_text
    assert "forecast" in pdf_text
    assert str(forecast_status) in pdf_text
    prefix = tmp_path / "research-decision-page"
    pdftoppm, render_environment = _poppler("pdftoppm")
    subprocess.run(
        [
            pdftoppm,
            "-f",
            "1",
            "-singlefile",
            "-png",
            str(report),
            str(prefix),
        ],
        check=True,
        capture_output=True,
        env=render_environment,
    )
    with Image.open(prefix.with_suffix(".png")) as image:
        assert image.width >= 1000
        assert image.height >= 1400
    root.close()

def test_pdf_bounds_long_unbroken_audit_tokens() -> None:
    view = {
        "schema_version": "ResearchDecisionView@2",
        "view_id": "view-long-token",
        "subject_id": "security_yihua",
        "as_of": "2026-07-30",
        "status": "completed_with_limits",
        "boundary": "Research only.",
        "audit": {
            "evidence": "x" * 200_000,
            "evaluation_bundle": {"components": {}},
        },
    }

    rendered = ResearchDecisionPdf().render(view)

    assert rendered.startswith(b"%PDF-")
