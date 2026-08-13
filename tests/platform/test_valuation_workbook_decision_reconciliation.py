from __future__ import annotations

import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from tests.platform.test_valuation_workbook_adapter import (
    ROOT,
    _MAIN,
    _cell_text,
    _ready_view,
)
from trading_platform.valuation_workbook import (
    ValuationWorkbookAdapter,
    ValuationWorkbookError,
)


@pytest.mark.skipif(
    not (
        os.environ.get("CODEX_ARTIFACT_NODE")
        and os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    ),
    reason="bundled artifact runtime is not configured",
)
def test_expected_decision_ledger_rejects_coordinated_workbook_row_deletion(
    tmp_path: Path,
) -> None:
    adapter = ValuationWorkbookAdapter(
        node_executable=Path(os.environ["CODEX_ARTIFACT_NODE"]),
        node_modules=Path(os.environ["CODEX_ARTIFACT_NODE_MODULES"]),
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )
    view = _ready_view()
    exported = adapter.export(view, tmp_path / "valuation.xlsx")
    tampered = tmp_path / "coordinated-row-deletion.xlsx"

    with (
        zipfile.ZipFile(exported.workbook_path) as source,
        zipfile.ZipFile(tampered, "w") as target,
    ):
        removed_key = (
            _cell_text(source, "xl/worksheets/sheet2.xml", "A2"),
            _cell_text(source, "xl/worksheets/sheet2.xml", "C2"),
            _cell_text(source, "xl/worksheets/sheet2.xml", "D2"),
        )
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet2.xml":
                sheet = ElementTree.fromstring(payload)
                sheet_data = sheet.find("main:sheetData", _MAIN)
                assert sheet_data is not None
                row = sheet_data.find("main:row[@r='2']", _MAIN)
                assert row is not None
                sheet_data.remove(row)
                payload = ElementTree.tostring(
                    sheet,
                    encoding="utf-8",
                    xml_declaration=True,
                )
            elif item.filename == "xl/worksheets/sheet3.xml":
                sheet = ElementTree.fromstring(payload)
                sheet_data = sheet.find("main:sheetData", _MAIN)
                assert sheet_data is not None
                for row in tuple(sheet_data.findall("main:row", _MAIN))[1:]:
                    row_number = row.attrib["r"]
                    key = (
                        _cell_text(source, item.filename, f"A{row_number}"),
                        _cell_text(source, item.filename, f"B{row_number}"),
                        _cell_text(source, item.filename, f"C{row_number}"),
                    )
                    if key == removed_key:
                        sheet_data.remove(row)
                payload = ElementTree.tostring(
                    sheet,
                    encoding="utf-8",
                    xml_declaration=True,
                )
            target.writestr(item, payload)

    with pytest.raises(
        ValuationWorkbookError,
        match="VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED",
    ):
        adapter.validate_export(tampered, expected_view=view)
