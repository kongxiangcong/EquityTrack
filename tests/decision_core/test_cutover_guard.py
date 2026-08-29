from __future__ import annotations

import ast
from pathlib import Path

from trading_platform.cli import MUTATIONS, parser


ROOT = Path(__file__).resolve().parents[2]
RETIRED = {
    "ResearchRun", "DataSnapshot", "EvidenceSnapshot", "PortfolioSnapshot",
    "InvestmentThesisVersion", "TradePlanVersion", "WorkflowRun", "ArtifactManifest",
    "PlanConfirmationChallenge", "UserApprovalReceipt", "PlanImpactAssessment",
    "PlanChangeProposal", "ActionLogEntry", "DisciplineReviewVersion", "ResearchRequest",
    "ResearchAnalysisPlan", "CompleteReport",
}


def test_cli_exposes_only_the_eight_application_operations() -> None:
    action = next(action for action in parser()._actions if action.dest == "operation")
    assert set(action.choices) == {"account-show", *MUTATIONS}


def test_active_runtime_and_control_plane_have_no_retired_symbols() -> None:
    paths = [ROOT / "src", ROOT / "skills", ROOT / "README.md"]
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for root in paths
        for path in ([root] if root.is_file() else root.rglob("*"))
        if path.is_file()
    )
    assert not RETIRED.intersection(text.split())
    for symbol in RETIRED:
        assert symbol not in text
    for forbidden in ("dual_read", "dual_write", "fallback_to_old", "feature_flag", "runtime llm", "broker order"):
        assert forbidden not in text.lower()


def test_domain_modules_do_not_import_cli_application_or_storage() -> None:
    modules = [
        ROOT / "src/trading_platform/evidence.py",
        ROOT / "src/trading_platform/portfolio.py",
        ROOT / "src/trading_platform/research/core.py",
        ROOT / "src/trading_platform/valuation.py",
        ROOT / "src/trading_platform/planning.py",
        ROOT / "src/trading_platform/review.py",
    ]
    forbidden = {"trading_platform.application", "trading_platform.cli", "trading_platform.storage"}
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(any(name == blocked or name.startswith(blocked + ".") for blocked in forbidden) for name in imports), path


def test_skill_has_exactly_six_current_task_documents() -> None:
    tasks = {path.name for path in (ROOT / "skills/tasks").glob("*.md")}
    assert tasks == {"account.md", "research.md", "valuation.md", "planning.md", "monitoring.md", "review.md"}
