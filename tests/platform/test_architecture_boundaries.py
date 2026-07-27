from __future__ import annotations

import ast
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUSINESS_ROOTS = (
    ROOT / "src" / "trading_platform" / "application",
    ROOT / "src" / "trading_platform" / "domain",
    ROOT / "src" / "trading_platform" / "persistence",
)
FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "apscheduler",
    "celery",
    "deepseek",
    "google.generativeai",
    "openai",
}
FORBIDDEN_EXECUTION_SYMBOLS = {
    "auto_order",
    "broker_client",
    "cancel_order",
    "order_router",
    "place_order",
    "schedule_order",
    "submit_order",
}


def test_business_import_graph_has_no_llm_order_or_scheduler_surface() -> None:
    imports: list[dict[str, str]] = []
    forbidden: list[dict[str, str]] = []
    files = sorted(
        path
        for root in BUSINESS_ROOTS
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            for name in names:
                imports.append({"file": relative, "module": name})
                if any(
                    name == root or name.startswith(f"{root}.")
                    for root in FORBIDDEN_IMPORT_ROOTS
                ):
                    forbidden.append({"file": relative, "module": name})
            if isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ) and node.name.casefold() in FORBIDDEN_EXECUTION_SYMBOLS:
                forbidden.append({"file": relative, "symbol": node.name})

    assert forbidden == []
    report = {
        "schema_version": "BusinessImportGraphEvidence@1",
        "file_count": len(files),
        "edge_count": len(imports),
        "forbidden_import_roots": sorted(FORBIDDEN_IMPORT_ROOTS),
        "forbidden_execution_symbols": sorted(FORBIDDEN_EXECUTION_SYMBOLS),
        "violations": forbidden,
    }
    evidence_root = os.environ.get("TDK_ACCEPTANCE_EVIDENCE_ROOT")
    if evidence_root:
        target = Path(evidence_root) / "architecture-import-graph.json"
        target.write_text(
            json.dumps(report, sort_keys=True, indent=2),
            encoding="utf-8",
        )
