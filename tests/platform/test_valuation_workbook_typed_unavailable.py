from __future__ import annotations

import os
from pathlib import Path
import zipfile
from xml.etree import ElementTree

import pytest

from trading_platform.research_view import ResearchDecisionView
from trading_platform.valuation_workbook import ValuationWorkbookAdapter


ROOT = Path(__file__).resolve().parents[2]
SHEET_PREVIEWS = {
    "summary.png",
    "canonical-inputs.png",
    "bridge-trace.png",
    "reconciliation.png",
    "sources-audit.png",
    "checks.png",
}
_MAIN = {
    "main": (
        "http://schemas.openxmlformats.org/"
        "spreadsheetml/2006/main"
    )
}


def _cell_text(
    archive: zipfile.ZipFile,
    sheet_name: str,
    cell_ref: str,
) -> str:
    sheet = ElementTree.fromstring(archive.read(sheet_name))
    cell = sheet.find(f".//main:c[@r='{cell_ref}']", _MAIN)
    assert cell is not None
    if cell.attrib.get("t") == "inlineStr":
        return "".join(
            node.text or ""
            for node in cell.findall(".//main:t", _MAIN)
        )
    value = cell.find("main:v", _MAIN)
    assert value is not None and value.text is not None
    if cell.attrib.get("t") == "s":
        shared = ElementTree.fromstring(
            archive.read("xl/sharedStrings.xml")
        )
        strings = [
            "".join(
                node.text or ""
                for node in item.findall(".//main:t", _MAIN)
            )
            for item in shared.findall("main:si", _MAIN)
        ]
        return strings[int(value.text)]
    return value.text


def _formula(
    archive: zipfile.ZipFile,
    sheet_name: str,
    cell_ref: str,
) -> str | None:
    sheet = ElementTree.fromstring(archive.read(sheet_name))
    cell = sheet.find(f".//main:c[@r='{cell_ref}']", _MAIN)
    assert cell is not None
    formula = cell.find("main:f", _MAIN)
    return None if formula is None else formula.text


def _typed_unavailable_view(status: str) -> ResearchDecisionView:
    return ResearchDecisionView(
        schema_version="ResearchDecisionView@2",
        view_id=f"research_view_{status}",
        workflow_run_id=f"workflow_{status}",
        research_run_id=f"research_bundle_{status}",
        data_snapshot_id="snapshot_unavailable",
        model_data_snapshot_identity="snapshot_unavailable",
        security_id="security_002407_szse",
        forecast_artifact_record_id=None,
        valuation_artifact_record_id=None,
        simulation_artifact_record_id=None,
        market_path_artifact_record_id=None,
        subject_id="security_002407_szse",
        as_of="2026-07-29",
        model_identity="engine:test",
        policy_identity="ResearchEvaluationPolicy@2",
        status="completed_with_limits",
        valuation_view={
            "status": status,
            "summary": "No numeric valuation conclusion is published.",
            "reason_code": "FORMAL_VALUATION_UNAVAILABLE",
            "methods": (),
        },
        risk_reward_summary=(
            "Research evidence remains usable within explicit data limits."
        ),
        data_quality_grade="D",
        key_uncertainties=("Official critical financial inputs are absent.",),
        what_would_change_the_view=(
            "Qualified official disclosures become available.",
        ),
        story={},
        key_drivers=(),
        scenarios=(),
        market_implied_expectations=(),
        valuation_simulation={
            "status": "not_run",
            "reason_code": "FORMAL_VALUATION_UNAVAILABLE",
        },
        market_price_paths={
            "status": "not_run",
            "reason_code": "MARKET_PATH_INPUTS_UNAVAILABLE",
        },
        value_market_divergence=None,
        audit={
            "artifact_records": (),
            "formula_identities": (),
            "source_policy_identity": "source-policy:test",
        },
        boundary=(
            "Conditional research output is not personalized investment advice."
        ),
    )


@pytest.mark.skipif(
    not (
        os.environ.get("CODEX_ARTIFACT_NODE")
        and os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    ),
    reason="bundled artifact runtime is not configured",
)
@pytest.mark.parametrize("valuation_status", ("unavailable", "blocked"))
def test_workbook_preserves_typed_unavailable_status_and_renders_every_sheet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    valuation_status: str,
) -> None:
    configured_qa = os.environ.get("VALUATION_WORKBOOK_QA_DIR")
    qa_root = (
        Path(configured_qa)
        if configured_qa
        else tmp_path / "qa"
    ) / valuation_status
    monkeypatch.setenv("VALUATION_WORKBOOK_QA_DIR", str(qa_root))
    adapter = ValuationWorkbookAdapter(
        node_executable=Path(os.environ["CODEX_ARTIFACT_NODE"]),
        node_modules=Path(os.environ["CODEX_ARTIFACT_NODE_MODULES"]),
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )

    exported = adapter.export(
        _typed_unavailable_view(valuation_status),
        tmp_path / f"{valuation_status}.xlsx",
    )

    assert exported.workbook_path.stat().st_size > 8_000
    assert exported.preview_path.stat().st_size > 1_000
    assert {path.name for path in qa_root.glob("*.png")} == SHEET_PREVIEWS
    with zipfile.ZipFile(exported.workbook_path) as archive:
        workbook_xml = b"".join(
            archive.read(name)
            for name in archive.namelist()
            if name.endswith(".xml")
        ).decode("utf-8")
        assert _formula(
            archive, "xl/worksheets/sheet1.xml", "C12"
        ) is None
        assert _cell_text(
            archive, "xl/worksheets/sheet1.xml", "C12"
        ) == "NOT_READY"
        assert _formula(
            archive, "xl/worksheets/sheet4.xml", "D2"
        ) == (
            """IF('Canonical Inputs'!E2="","",'Canonical Inputs'!E2)"""
        )
        assert _formula(
            archive, "xl/worksheets/sheet4.xml", "F2"
        ) == (
            """IF('Canonical Inputs'!F2="","",'Canonical Inputs'!F2)"""
        )
        assert _formula(
            archive, "xl/worksheets/sheet4.xml", "J2"
        ) == (
            """IF('Canonical Inputs'!G2="","",'Canonical Inputs'!G2)"""
        )
    assert valuation_status in workbook_xml
    assert "not_ready" not in workbook_xml
