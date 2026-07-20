from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from trading_platform.research_view import ResearchDecisionView


class ValuationWorkbookError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValuationWorkbookExport:
    workbook_path: Path
    preview_path: Path


class ValuationWorkbookAdapter:
    """XLSX output adapter for a canonical ResearchDecisionView."""

    def __init__(
        self,
        *,
        node_executable: Path,
        node_modules: Path,
        builder_script: Path,
    ) -> None:
        self.node_executable = node_executable
        self.node_modules = node_modules
        self.builder_script = builder_script

    def export(
        self,
        view: ResearchDecisionView,
        output_path: Path,
    ) -> ValuationWorkbookExport:
        if not isinstance(view, ResearchDecisionView):
            raise ValuationWorkbookError("VALUATION_WORKBOOK_VIEW_INVALID")
        payload = view.to_dict()
        if not self.node_executable.is_file():
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_NODE_MISSING"
            )
        if not self.node_modules.is_dir():
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_RUNTIME_MISSING"
            )
        if not self.builder_script.is_file():
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_BUILDER_MISSING"
            )
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path = output_path.with_suffix(".preview.png")
        with tempfile.TemporaryDirectory(
            prefix="valuation-workbook-"
        ) as temporary:
            workdir = Path(temporary)
            input_path = workdir / "decision-view.json"
            runner = workdir / "render_valuation_xlsx.mjs"
            input_path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            shutil.copyfile(self.builder_script, runner)
            link = workdir / "node_modules"
            try:
                os.symlink(
                    self.node_modules,
                    link,
                    target_is_directory=True,
                )
            except OSError:
                if os.name != "nt":
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_RUNTIME_LINK_FAILED"
                    )
                link_environment = os.environ.copy()
                link_environment["VALUATION_WORKBOOK_LINK"] = str(link)
                link_environment["VALUATION_WORKBOOK_TARGET"] = str(
                    self.node_modules
                )
                completed_link = subprocess.run(
                    (
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "New-Item -ItemType Junction "
                        "-Path $env:VALUATION_WORKBOOK_LINK "
                        "-Target $env:VALUATION_WORKBOOK_TARGET | Out-Null",
                    ),
                    env=link_environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                if completed_link.returncode != 0 or not link.is_dir():
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_RUNTIME_LINK_FAILED:"
                        + (
                            completed_link.stderr
                            or completed_link.stdout
                        )[-1000:]
                    )
            completed = subprocess.run(
                (
                    str(self.node_executable),
                    str(runner),
                    str(input_path),
                    str(output_path),
                    str(preview_path),
                ),
                cwd=workdir,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        if completed.returncode != 0:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_EXPORT_FAILED:"
                + (completed.stderr or completed.stdout)[-2000:]
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_OUTPUT_MISSING"
            )
        self.validate_export(output_path)
        if not preview_path.is_file() or preview_path.stat().st_size == 0:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_PREVIEW_MISSING"
            )
        return ValuationWorkbookExport(output_path, preview_path)

    @staticmethod
    def validate_export(workbook_path: Path) -> None:
        try:
            with zipfile.ZipFile(workbook_path) as archive:
                workbook = ElementTree.fromstring(
                    archive.read("xl/workbook.xml")
                )
                relationships = ElementTree.fromstring(
                    archive.read(
                        "xl/_rels/workbook.xml.rels"
                    )
                )
                namespaces = {
                    "main": (
                        "http://schemas.openxmlformats.org/"
                        "spreadsheetml/2006/main"
                    ),
                    "rel": (
                        "http://schemas.openxmlformats.org/"
                        "officeDocument/2006/relationships"
                    ),
                    "pkg": (
                        "http://schemas.openxmlformats.org/"
                        "package/2006/relationships"
                    ),
                }
                summary = next(
                    sheet
                    for sheet in workbook.findall(
                        "main:sheets/main:sheet",
                        namespaces,
                    )
                    if sheet.attrib.get("name") == "Summary"
                )
                relationship_id = summary.attrib[
                    f"{{{namespaces['rel']}}}id"
                ]
                target = next(
                    relationship.attrib["Target"]
                    for relationship in relationships.findall(
                        "pkg:Relationship",
                        namespaces,
                    )
                    if relationship.attrib.get("Id")
                    == relationship_id
                )
                sheet_path = (
                    target.removeprefix("/")
                    if target.startswith("/")
                    else "xl/" + target.removeprefix("../")
                )
                worksheet = ElementTree.fromstring(
                    archive.read(sheet_path)
                )
        except (
            KeyError,
            StopIteration,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ) as error:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_STRUCTURE_INVALID"
            ) from error

        formulas = []
        summary_row_count = 0
        for row in worksheet.findall(
            ".//main:row",
            namespaces,
        ):
            try:
                row_number = int(row.attrib.get("r", "0"))
            except ValueError:
                continue
            if row_number < 12:
                continue
            cells = {
                cell.attrib.get("r", "")[:1]: cell
                for cell in row.findall("main:c", namespaces)
            }
            if "B" not in cells:
                continue
            summary_row_count += 1
            formula = cells.get("C")
            formula_node = (
                formula.find("main:f", namespaces)
                if formula is not None
                else None
            )
            if formula_node is None or not formula_node.text:
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_SUMMARY_FORMULA_CHAIN_BROKEN"
                )
            formulas.append(formula_node.text)
        if (
            not formulas
            or len(formulas) != summary_row_count
            or any(
                not formula.startswith(
                    (
                        "'Reconciliation'!D",
                        "'Reconciliation'!F",
                        "'Reconciliation'!J",
                    )
                )
                for formula in formulas
            )
        ):
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_SUMMARY_FORMULA_CHAIN_BROKEN"
            )
