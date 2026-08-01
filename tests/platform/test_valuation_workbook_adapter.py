from __future__ import annotations

from trading_platform.application.contracts import StartResearchWorkflow


import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from trading_platform.valuation_workbook import (
    ValuationWorkbookAdapter,
    ValuationWorkbookError,
)
from trading_platform.research_view import ResearchDecisionView
from tests.platform.test_research_workflow import (
    _request,
    _root,
)
from tests.platform.test_research_bundle_decision_projection import (
    _project,
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
    exported = adapter.export(
        _ready_view(),
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
        adapter.validate_export(tampered)
