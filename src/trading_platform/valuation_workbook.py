from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree

from trading_platform.research_view import ResearchDecisionView
from trading_platform.application.research_workbook import (
    ResearchWorkbookArtifact,
    ResearchWorkbookProjectionError,
)


class ValuationWorkbookError(ResearchWorkbookProjectionError):
    def __init__(self, code: str) -> None:
        stable_code = code.split(":", 1)[0]
        if (
            not stable_code
            or not stable_code.replace("_", "").isalnum()
            or stable_code.upper() != stable_code
        ):
            stable_code = "RESEARCH_WORKBOOK_RENDERER_FAILED"
        super().__init__(stable_code)


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

    def project(
        self, view: ResearchDecisionView
    ) -> ResearchWorkbookArtifact:
        try:
            with tempfile.TemporaryDirectory(
                prefix="research-workbook-projection-"
            ) as temporary:
                exported = self.export(
                    view, Path(temporary) / "research-decision.xlsx"
                )
                return ResearchWorkbookArtifact.ready(
                    exported.workbook_path.read_bytes()
                )
        except ValuationWorkbookError:
            raise
        except subprocess.TimeoutExpired as error:
            raise ValuationWorkbookError(
                "RESEARCH_WORKBOOK_RENDERER_TIMEOUT"
            ) from error
        except (OSError, RuntimeError) as error:
            raise ValuationWorkbookError(
                "RESEARCH_WORKBOOK_RENDERER_FAILED"
            ) from error

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
        self.validate_export(output_path, expected_view=view)
        if not preview_path.is_file() or preview_path.stat().st_size == 0:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_PREVIEW_MISSING"
            )
        return ValuationWorkbookExport(output_path, preview_path)

    @staticmethod
    def validate_export(
        workbook_path: Path,
        *,
        expected_view: ResearchDecisionView,
    ) -> None:
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
                additional_worksheets: dict[str, ElementTree.Element] = {}
                for sheet_name in (
                    "Canonical Inputs",
                    "Bridge Trace",
                ):
                    sheet = next(
                        item
                        for item in workbook.findall(
                            "main:sheets/main:sheet",
                            namespaces,
                        )
                        if item.attrib.get("name") == sheet_name
                    )
                    relationship_id = sheet.attrib[
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
                    sheet_path_for_name = (
                        target.removeprefix("/")
                        if target.startswith("/")
                        else "xl/" + target.removeprefix("../")
                    )
                    additional_worksheets[sheet_name] = (
                        ElementTree.fromstring(
                            archive.read(sheet_path_for_name)
                        )
                    )
                shared_strings: list[str] = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    shared = ElementTree.fromstring(
                        archive.read("xl/sharedStrings.xml")
                    )
                    shared_strings = [
                        "".join(
                            node.text or ""
                            for node in item.findall(
                                ".//main:t", namespaces
                            )
                        )
                        for item in shared.findall(
                            "main:si", namespaces
                        )
                    ]
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
        not_ready_rows = 0
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
            if formula_node is not None and formula_node.text:
                formulas.append(formula_node.text)
                continue
            method = ValuationWorkbookAdapter._cell_text(
                cells["B"], namespaces, shared_strings
            )
            displayed = (
                ValuationWorkbookAdapter._cell_text(
                    formula, namespaces, shared_strings
                )
                if formula is not None
                else ""
            )
            if (
                displayed != "NOT_READY"
                or method not in {"not_ready", "unavailable", "blocked"}
            ):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_SUMMARY_FORMULA_CHAIN_BROKEN"
                )
            not_ready_rows += 1
        if (
            summary_row_count == 0
            or len(formulas) + not_ready_rows != summary_row_count
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
        ValuationWorkbookAdapter._validate_decimal_reconciliation(
            additional_worksheets["Canonical Inputs"],
            additional_worksheets["Bridge Trace"],
            namespaces,
            shared_strings,
            expected_canonical_values=(
                ValuationWorkbookAdapter._expected_canonical_values(expected_view)
            ),
        )

    @staticmethod
    def _validate_decimal_reconciliation(
        canonical_sheet: ElementTree.Element,
        bridge_sheet: ElementTree.Element,
        namespaces: dict[str, str],
        shared_strings: list[str],
        *,
        expected_canonical_values: Mapping[
            tuple[str, str, str], tuple[Decimal, Decimal, Decimal] | None
        ],
    ) -> None:
        """Recalculate only the published bridge; this is not a DCF engine."""

        canonical_rows = canonical_sheet.findall(
            ".//main:row",
            namespaces,
        )
        bridge_rows = bridge_sheet.findall(
            ".//main:row",
            namespaces,
        )
        if not canonical_rows:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_CANONICAL_INPUT_INVALID"
            )
        if not bridge_rows:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
            )

        canonical_header = ValuationWorkbookAdapter._row_values(
            canonical_rows[0],
            namespaces,
            shared_strings,
        )
        expected_canonical_header = {
            "A": "Scenario Role",
            "B": "Scenario Label",
            "C": "Method",
            "D": "Point",
            "E": "Canonical Basis",
            "F": "Canonical Equity",
            "G": "Canonical Per Share",
        }
        if any(
            canonical_header.get(column) != label
            for column, label in expected_canonical_header.items()
        ):
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_CANONICAL_INPUT_INVALID"
            )

        canonical_values: dict[
            tuple[str, str, str],
            tuple[Decimal, Decimal, Decimal] | None,
        ] = {}
        for row in canonical_rows[1:]:
            values = ValuationWorkbookAdapter._row_values(
                row,
                namespaces,
                shared_strings,
            )
            if not any(values.values()):
                continue
            key = (
                values.get("A", ""),
                values.get("C", ""),
                values.get("D", ""),
            )
            if not all(key) or key in canonical_values:
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_CANONICAL_INPUT_INVALID"
                )
            decimal_texts = tuple(
                values.get(column, "") for column in ("E", "F", "G")
            )
            if not any(decimal_texts):
                canonical_values[key] = None
                continue
            if not all(decimal_texts):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_CANONICAL_INPUT_INVALID"
                )
            parsed_values = tuple(
                ValuationWorkbookAdapter._decimal_value(
                    value,
                    "VALUATION_WORKBOOK_CANONICAL_INPUT_INVALID",
                )
                for value in decimal_texts
            )
            canonical_values[key] = (
                parsed_values[0],
                parsed_values[1],
                parsed_values[2],
            )
        if not canonical_values:
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_CANONICAL_INPUT_INVALID"
            )

        if set(canonical_values) != set(expected_canonical_values):
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED"
            )
        for key, expected_values in expected_canonical_values.items():
            actual_values = canonical_values[key]
            if actual_values is None or expected_values is None:
                if actual_values is not expected_values:
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED"
                    )
                continue
            if any(
                not ValuationWorkbookAdapter._matches(actual, expected)
                for actual, expected in zip(actual_values, expected_values)
            ):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED"
                )

        bridge_header = ValuationWorkbookAdapter._row_values(
            bridge_rows[0],
            namespaces,
            shared_strings,
        )
        expected_bridge_header = {
            "A": "Scenario Role",
            "B": "Method",
            "C": "Point",
            "D": "Step",
            "E": "Operation",
            "F": "Amount",
            "G": "Evidence Refs",
            "H": "Equity Output Step",
        }
        if any(
            bridge_header.get(column) != label
            for column, label in expected_bridge_header.items()
        ):
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
            )

        traces: dict[
            tuple[str, str, str],
            list[tuple[int, str, Decimal | None, str]],
        ] = {}
        for row in bridge_rows[1:]:
            values = ValuationWorkbookAdapter._row_values(
                row,
                namespaces,
                shared_strings,
            )
            if not any(values.values()):
                continue
            key = (
                values.get("A", ""),
                values.get("B", ""),
                values.get("C", ""),
            )
            operation = values.get("E", "")
            if not all(key) or not operation:
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                )
            step_value = ValuationWorkbookAdapter._decimal_value(
                values.get("D", ""),
                "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID",
            )
            if (
                step_value < 1
                or step_value != step_value.to_integral_value()
            ):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                )
            amount_text = values.get("F", "")
            amount = (
                ValuationWorkbookAdapter._decimal_value(
                    amount_text,
                    "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID",
                )
                if amount_text
                else None
            )
            traces.setdefault(key, []).append(
                (
                    int(step_value),
                    operation,
                    amount,
                    values.get("H", ""),
                )
            )

        if set(traces) != set(canonical_values):
            raise ValuationWorkbookError(
                "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
            )

        for key, expected in canonical_values.items():
            trace = traces[key]
            if expected is None:
                if trace != [(1, "basis_value", None, "")]:
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                    )
                continue
            if (
                [item[0] for item in trace]
                != list(range(1, len(trace) + 1))
                or not trace
                or trace[0][1] != "basis_value"
                or any(item[2] is None for item in trace)
            ):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                )

            divide_indexes = [
                index
                for index, item in enumerate(trace)
                if item[1] == "divide_diluted_shares"
            ]
            if divide_indexes != [len(trace) - 1] or len(trace) < 2:
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                )
            divide_index = divide_indexes[0]
            for index, item in enumerate(trace):
                expected_flag = "1" if index == divide_index - 1 else "0"
                if item[3] != expected_flag:
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                    )

            running = Decimal("0")
            equity_value: Decimal | None = None
            per_share_value: Decimal | None = None
            basis_value: Decimal | None = None
            for index, (_, operation, amount, _) in enumerate(trace):
                if amount is None:
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                    )
                if operation == "basis_value":
                    if index != 0:
                        raise ValuationWorkbookError(
                            "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                        )
                    running = amount
                    basis_value = amount
                elif operation.startswith("add_") and len(operation) > 4:
                    running += amount
                elif (
                    operation.startswith("subtract_")
                    and len(operation) > 9
                ):
                    running -= amount
                elif operation == "convert_fx":
                    if amount <= 0:
                        raise ValuationWorkbookError(
                            "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                        )
                    running *= amount
                elif operation == "divide_diluted_shares":
                    if amount <= 0 or index != len(trace) - 1:
                        raise ValuationWorkbookError(
                            "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                        )
                    equity_value = running
                    per_share_value = running / amount
                else:
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_BRIDGE_TRACE_INVALID"
                    )

            if basis_value is None or not ValuationWorkbookAdapter._matches(
                basis_value,
                expected[0],
            ):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_BASIS_RECONCILIATION_FAILED"
                )
            if equity_value is None or not ValuationWorkbookAdapter._matches(
                equity_value,
                expected[1],
            ):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_EQUITY_RECONCILIATION_FAILED"
                )
            if (
                per_share_value is None
                or not ValuationWorkbookAdapter._matches(
                    per_share_value,
                    expected[2],
                )
            ):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_PER_SHARE_RECONCILIATION_FAILED"
                )

    @staticmethod
    def _expected_canonical_values(
        view: ResearchDecisionView,
    ) -> dict[
        tuple[str, str, str],
        tuple[Decimal, Decimal, Decimal] | None,
    ]:
        expected: dict[
            tuple[str, str, str],
            tuple[Decimal, Decimal, Decimal] | None,
        ] = {}
        for scenario in view.scenarios:
            role = str(scenario.get("role", ""))
            methods = scenario.get("methods", ())
            if not role or not isinstance(methods, (list, tuple)):
                raise ValuationWorkbookError(
                    "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED"
                )
            for method in methods:
                if not isinstance(method, Mapping):
                    raise ValuationWorkbookError(
                        "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED"
                    )
                value_range = method.get("conditional_value_range")
                if (
                    method.get("status") != "ready"
                    or not isinstance(value_range, Mapping)
                ):
                    continue
                reconciliation = method.get("reconciliation")
                if not isinstance(reconciliation, Mapping):
                    continue
                method_id = str(method.get("method_id", ""))
                for point in ("low", "base", "high"):
                    source_point = reconciliation.get(point)
                    if not isinstance(source_point, Mapping):
                        continue
                    key = (role, method_id, point)
                    basis = source_point.get("basis_value")
                    equity = source_point.get("equity_value")
                    per_share = source_point.get("per_share_value")
                    if (
                        not method_id
                        or key in expected
                        or not isinstance(basis, Mapping)
                        or not isinstance(equity, Mapping)
                        or per_share is not None
                        and not isinstance(per_share, Mapping)
                    ):
                        raise ValuationWorkbookError(
                            "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED"
                        )
                    expected[key] = (
                        ValuationWorkbookAdapter._decimal_value(
                            str(basis.get("value")),
                            "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED",
                        ),
                        ValuationWorkbookAdapter._decimal_value(
                            str(equity.get("value")),
                            "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED",
                        ),
                        ValuationWorkbookAdapter._decimal_value(
                            "0" if per_share is None else str(per_share.get("value")),
                            "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED",
                        ),
                    )
        if expected:
            return expected
        valuation_status = str(view.valuation_view.get("status", "unknown"))
        if valuation_status in {"not_ready", "unavailable", "blocked"}:
            return {("limited", valuation_status, "base"): None}
        raise ValuationWorkbookError(
            "VALUATION_WORKBOOK_DECISION_VIEW_RECONCILIATION_FAILED"
        )

    @staticmethod
    def _row_values(
        row: ElementTree.Element,
        namespaces: dict[str, str],
        shared_strings: list[str],
    ) -> dict[str, str]:
        values: dict[str, str] = {}
        for cell in row.findall("main:c", namespaces):
            reference = cell.attrib.get("r", "")
            column = "".join(
                character for character in reference if character.isalpha()
            )
            if column:
                values[column] = ValuationWorkbookAdapter._cell_text(
                    cell,
                    namespaces,
                    shared_strings,
                )
        return values

    @staticmethod
    def _decimal_value(value: str, error_code: str) -> Decimal:
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValuationWorkbookError(error_code) from error
        if not parsed.is_finite():
            raise ValuationWorkbookError(error_code)
        return parsed

    @staticmethod
    def _matches(left: Decimal, right: Decimal) -> bool:
        return abs(left - right) < Decimal("0.0000001")

    @staticmethod
    def _cell_text(
        cell: ElementTree.Element,
        namespaces: dict[str, str],
        shared_strings: list[str],
    ) -> str:
        if cell.attrib.get("t") == "inlineStr":
            return "".join(
                node.text or ""
                for node in cell.findall(".//main:t", namespaces)
            )
        value = cell.find("main:v", namespaces)
        if value is None or value.text is None:
            return ""
        if cell.attrib.get("t") == "s":
            try:
                return shared_strings[int(value.text)]
            except (IndexError, ValueError):
                return ""
        return value.text
