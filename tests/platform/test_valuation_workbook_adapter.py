from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path

import pytest

from trading_platform.valuation_workbook import (
    ValuationWorkbookAdapter,
    ValuationWorkbookError,
)
from tests.platform.test_outlook_artifacts import _request
from tests.platform.test_research_workflow import (
    CountingEngine,
    _artifact_bytes,
    _root,
)


ROOT = Path(__file__).resolve().parents[2]


def _canonical_view(tmp_path: Path) -> dict[str, object]:
    root = _root(tmp_path / "store", CountingEngine())
    result = root.facade.run_research_workflow(
        _request("valuation-workbook:canonical")
    )
    payload = json.loads(_artifact_bytes(root, result.json_artifact_id))
    root.close()
    return payload


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
        adapter.export({"schema_version": "ResearchRun@3"}, tmp_path / "x.xlsx")


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
        _canonical_view(tmp_path),
        tmp_path / "valuation.xlsx",
    )

    assert exported.workbook_path.stat().st_size > 10_000
    assert exported.preview_path.stat().st_size > 1_000


@pytest.mark.skipif(
    not (
        os.environ.get("CODEX_ARTIFACT_NODE")
        and os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    ),
    reason="bundled artifact runtime is not configured",
)
def test_workbook_fails_when_canonical_output_is_hardcoded(
    tmp_path: Path,
) -> None:
    view = _canonical_view(tmp_path)
    ready = next(
        method
        for scenario in view["scenarios"]
        for method in scenario["methods"]
        if method["status"] == "ready"
    )
    ready["reconciliation"]["base"]["equity_value"]["value"] = "1"
    adapter = ValuationWorkbookAdapter(
        node_executable=Path(os.environ["CODEX_ARTIFACT_NODE"]),
        node_modules=Path(os.environ["CODEX_ARTIFACT_NODE_MODULES"]),
        builder_script=ROOT / "scripts" / "render_valuation_xlsx.mjs",
    )

    with pytest.raises(
        ValuationWorkbookError,
        match="VALUATION_WORKBOOK_RECONCILIATION_FAILED",
    ):
        adapter.export(view, tmp_path / "broken.xlsx")


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
        _canonical_view(tmp_path),
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
