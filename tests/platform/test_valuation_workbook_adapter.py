from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest

from tests.platform.test_research_bundle_decision_projection import (
    _project,
)
from tests.platform.test_research_workflow import (
    _request,
    _root,
)
from trading_platform.application.contracts import StartResearchWorkflow
from trading_platform.research_view import ResearchDecisionView
from trading_platform.valuation_workbook import (
    ValuationWorkbookAdapter,
    ValuationWorkbookError,
)


ROOT = Path(__file__).resolve().parents[2]
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


def _canonical_view(tmp_path: Path) -> ResearchDecisionView:
    root = _root(tmp_path / "store")
    result = root.research.handle(StartResearchWorkflow(_request("valuation-workbook:canonical")))
    payload = json.loads(root.archive.decision_view(result.workflow_run_id).json_bytes)
    root.close()
    return ResearchDecisionView.from_dict(payload)


def _ready_view() -> ResearchDecisionView:
    payload = _project(ready=True)
    for scenario in payload["scenarios"]:
        for method in scenario["methods"]:
            value_range = method["conditional_value_range"]
            for point in value_range.values():
                value = point["basis_value"]["value"]
                point["bridge_trace"] = [
                    {
                        "operation": "basis_value",
                        "amount": value,
                        "ref_ids": ["source_ready"],
                    },
                    {
                        "operation": "divide_diluted_shares",
                        "amount": "1",
                        "ref_ids": ["source_ready"],
                    },
                ]
            method["reconciliation"] = value_range
    return ResearchDecisionView.from_dict(payload)

def _reconciliation_view(
    *,
    canonical_equity: str = "110",
    per_share: str = "10",
) -> ResearchDecisionView:
    point = {
        "basis_value": {"value": "100"},
        "equity_value": {"value": canonical_equity},
        "per_share_value": {"value": per_share},
    }
    return replace(
        _ready_view(),
        scenarios=(
            {
                "role": "base",
                "methods": (
                    {
                        "method_id": "fcff_dcf",
                        "status": "ready",
                        "conditional_value_range": {"base": point},
                        "reconciliation": {"base": point},
                    },
                ),
            },
        ),
    )




def _inline_cell(reference: str, value: str) -> str:
    return (
        f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
    )


def _number_cell(reference: str, value: str) -> str:
    return f'<c r="{reference}"><v>{value}</v></c>'


def _worksheet(*rows: str) -> bytes:
    content = "".join(rows)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        f'spreadsheetml/2006/main"><sheetData>{content}</sheetData>'
        '</worksheet>'
    ).encode("utf-8")


def _row(number: int, *cells: str) -> str:
    return f'<row r="{number}">{"".join(cells)}</row>'


def _write_reconciliation_fixture(
    path: Path,
    *,
    canonical_equity: str = "110",
    diluted_shares: str = "11",
) -> None:
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships"><sheets>'
        '<sheet name="Summary" sheetId="1" r:id="rId1"/>'
        '<sheet name="Canonical Inputs" sheetId="2" r:id="rId2"/>'
        '<sheet name="Bridge Trace" sheetId="3" r:id="rId3"/>'
        '</sheets></workbook>'
    ).encode("utf-8")
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Target="worksheets/sheet3.xml"/>'
        '</Relationships>'
    ).encode("utf-8")
    summary = _worksheet(
        _row(
            12,
            _inline_cell("B12", "fcff_dcf"),
            '<c r="C12"><f>\'Reconciliation\'!J2</f><v>10</v></c>',
        )
    )
    canonical = _worksheet(
        _row(
            1,
            *(
                _inline_cell(f"{column}1", label)
                for column, label in zip(
                    "ABCDEFG",
                    (
                        "Scenario Role",
                        "Scenario Label",
                        "Method",
                        "Point",
                        "Canonical Basis",
                        "Canonical Equity",
                        "Canonical Per Share",
                    ),
                )
            ),
        ),
        _row(
            2,
            _inline_cell("A2", "base"),
            _inline_cell("B2", "Base"),
            _inline_cell("C2", "fcff_dcf"),
            _inline_cell("D2", "base"),
            _number_cell("E2", "100"),
            _number_cell("F2", canonical_equity),
            _number_cell("G2", "10"),
        ),
    )
    bridge = _worksheet(
        _row(
            1,
            *(
                _inline_cell(f"{column}1", label)
                for column, label in zip(
                    "ABCDEFGH",
                    (
                        "Scenario Role",
                        "Method",
                        "Point",
                        "Step",
                        "Operation",
                        "Amount",
                        "Evidence Refs",
                        "Equity Output Step",
                    ),
                )
            ),
        ),
        *(
            _row(
                row_number,
                _inline_cell(f"A{row_number}", "base"),
                _inline_cell(f"B{row_number}", "fcff_dcf"),
                _inline_cell(f"C{row_number}", "base"),
                _number_cell(f"D{row_number}", str(step)),
                _inline_cell(f"E{row_number}", operation),
                _number_cell(f"F{row_number}", amount),
                _inline_cell(f"G{row_number}", evidence),
                _number_cell(f"H{row_number}", equity_output),
            )
            for row_number, (step, operation, amount, evidence, equity_output)
            in enumerate(
                (
                    (1, "basis_value", "100", "basis", "0"),
                    (2, "add_cash", "20", "cash", "0"),
                    (3, "subtract_debt", "10", "debt", "1"),
                    (4, "divide_diluted_shares", diluted_shares, "shares", "0"),
                ),
                start=2,
            )
        ),
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", summary)
        archive.writestr("xl/worksheets/sheet2.xml", canonical)
        archive.writestr("xl/worksheets/sheet3.xml", bridge)


def test_workbook_recomputes_canonical_equity_bridge_and_per_share(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "decimal-reconciliation.xlsx"
    _write_reconciliation_fixture(workbook)

    ValuationWorkbookAdapter.validate_export(
        workbook, expected_view=_reconciliation_view()
    )


def test_workbook_rejects_tampered_canonical_equity(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "tampered-equity.xlsx"
    _write_reconciliation_fixture(workbook, canonical_equity="111")

    with pytest.raises(
        ValuationWorkbookError,
        match="VALUATION_WORKBOOK_EQUITY_RECONCILIATION_FAILED",
    ):
        ValuationWorkbookAdapter.validate_export(
            workbook,
            expected_view=_reconciliation_view(canonical_equity="111"),
        )


def test_workbook_rejects_tampered_diluted_shares(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "tampered-shares.xlsx"
    _write_reconciliation_fixture(workbook, diluted_shares="10")

    with pytest.raises(
        ValuationWorkbookError,
        match="VALUATION_WORKBOOK_PER_SHARE_RECONCILIATION_FAILED",
    ):
        ValuationWorkbookAdapter.validate_export(
            workbook,
            expected_view=_reconciliation_view(),
        )


def test_workbook_validator_requires_canonical_decision_view(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "missing-expected-view.xlsx"
    _write_reconciliation_fixture(workbook)
    with pytest.raises(TypeError):
        ValuationWorkbookAdapter.validate_export(workbook)


def test_workbook_adapter_rejects_noncanonical_input(
    tmp_path: Path,
) -> None:
    adapter = ValuationWorkbookAdapter(
        node_executable=tmp_path / "node",
        node_modules=tmp_path / "node_modules",
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )
    with pytest.raises(
        ValuationWorkbookError,
        match="VALUATION_WORKBOOK_VIEW_INVALID",
    ):
        adapter.export({"schema_version": "SourceRun@3"}, tmp_path / "x.xlsx")


@pytest.mark.skipif(
    not (
        os.environ.get("CODEX_ARTIFACT_NODE")
        and os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    ),
    reason="bundled artifact runtime is not configured",
)
def test_workbook_reconciles_canonical_valuation_artifact(
    tmp_path: Path,
) -> None:
    adapter = ValuationWorkbookAdapter(
        node_executable=Path(os.environ["CODEX_ARTIFACT_NODE"]),
        node_modules=Path(os.environ["CODEX_ARTIFACT_NODE_MODULES"]),
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )
    exported = adapter.export(
        _ready_view(),
        tmp_path / "valuation.xlsx",
    )

    assert exported.workbook_path.stat().st_size > 8_000
    assert exported.preview_path.stat().st_size > 1_000
    with zipfile.ZipFile(exported.workbook_path) as archive:
        assert _cell_text(
            archive, "xl/worksheets/sheet4.xml", "L2"
        ) == "OK"
        assert _cell_text(
            archive, "xl/worksheets/sheet4.xml", "M2"
        ) == "OK"
        assert _cell_text(
            archive, "xl/worksheets/sheet5.xml", "A5"
        ) == "Research analysis plan"
        assert _cell_text(
            archive, "xl/worksheets/sheet5.xml", "B5"
        ) == "ResearchAnalysisPlan@1"
        assert _cell_text(
            archive, "xl/worksheets/sheet5.xml", "E5"
        ) == "bound"
        assert _cell_text(
            archive, "xl/worksheets/sheet6.xml", "A7"
        ) == "Workbook Projection Status"


@pytest.mark.skipif(
    not (
        os.environ.get("CODEX_ARTIFACT_NODE")
        and os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    ),
    reason="bundled artifact runtime is not configured",
)
def test_workbook_carries_unavailable_valuation_without_numeric_substitution(
    tmp_path: Path,
) -> None:
    view = _canonical_view(tmp_path)
    assert view.valuation_view["status"] == "unavailable"
    assert [scenario["role"] for scenario in view.scenarios] == [
        "stress",
        "base",
        "improvement",
    ]
    assert all(
        method["status"] == "blocked"
        and method["conditional_value_range"] is None
        for scenario in view.scenarios
        for method in scenario["methods"]
    )
    adapter = ValuationWorkbookAdapter(
        node_executable=Path(os.environ["CODEX_ARTIFACT_NODE"]),
        node_modules=Path(os.environ["CODEX_ARTIFACT_NODE_MODULES"]),
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )

    exported = adapter.export(view, tmp_path / "limited.xlsx")
    assert exported.workbook_path.stat().st_size > 8_000
    with zipfile.ZipFile(exported.workbook_path) as archive:
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


@pytest.mark.skipif(
    not (
        os.environ.get("CODEX_ARTIFACT_NODE")
        and os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    ),
    reason="bundled artifact runtime is not configured",
)
def test_workbook_timeout_has_a_stable_typed_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"test-node")
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    adapter = ValuationWorkbookAdapter(
        node_executable=node,
        node_modules=node_modules,
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )

    view = _canonical_view(tmp_path)

    def timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired("render-workbook", 120)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(
        ValuationWorkbookError,
        match="RESEARCH_WORKBOOK_RENDERER_TIMEOUT",
    ):
        adapter.project(view)


@pytest.mark.skipif(
    not (
        os.environ.get("CODEX_ARTIFACT_NODE")
        and os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    ),
    reason="bundled artifact runtime is not configured",
)
def test_workbook_rejects_hardcoded_summary_output(
    tmp_path: Path,
) -> None:
    adapter = ValuationWorkbookAdapter(
        node_executable=Path(os.environ["CODEX_ARTIFACT_NODE"]),
        node_modules=Path(os.environ["CODEX_ARTIFACT_NODE_MODULES"]),
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )
    view = _ready_view()
    exported = adapter.export(
        view,
        tmp_path / "valuation.xlsx",
    )
    tampered = tmp_path / "hardcoded-summary.xlsx"
    with (
        zipfile.ZipFile(exported.workbook_path) as source,
        zipfile.ZipFile(tampered, "w") as target,
    ):
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                payload, replacements = re.subn(
                    rb"<(?:[A-Za-z0-9_]+:)?f>"
                    rb"[^<]*Reconciliation[^<]*"
                    rb"</(?:[A-Za-z0-9_]+:)?f>",
                    b"",
                    payload,
                    count=1,
                )
                assert replacements == 1
            target.writestr(item, payload)

    with pytest.raises(
        ValuationWorkbookError,
        match="VALUATION_WORKBOOK_SUMMARY_FORMULA_CHAIN_BROKEN",
    ):
        adapter.validate_export(tampered, expected_view=view)
