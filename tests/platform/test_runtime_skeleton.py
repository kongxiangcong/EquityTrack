from __future__ import annotations

import ast
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path

import pytest

from trading_platform.application import (
    Capability,
    CapabilityStatus,
    HealthQuery,
    open_platform_health,
    open_platform_operations,
)
from trading_platform.identity import CanonicalDate, build_code_identity, canonical_hash


ROOT = Path(__file__).resolve().parents[2]

OWNING_SQLITE_TESTS = {
    "test_chart_annotations.py",
    "test_data_sync_pit.py",
    "test_workflow_ledger_forecast_review.py",
    "test_market_evaluation.py",
    "test_market_path_simulation_artifact.py",
    "test_operations_backup_restore.py",
    "test_trade_plans.py",
    "test_workflow_ledger.py",
    "test_workflow_ledger_recovery.py",
    "test_workspace_persistence.py",
}


class Mode(str, Enum):
    FIXTURE = "fixture"


def test_health_is_a_named_task_without_a_root_or_facade(tmp_path: Path) -> None:
    assert open_platform_operations(tmp_path).bootstrap()["status"] == "passed"
    with open_platform_health(tmp_path) as health_task:
        health = health_task.inspect(HealthQuery())
        assert health.capabilities[Capability.HEALTH] is CapabilityStatus.AVAILABLE
        assert health.capabilities[Capability.PERSISTENCE] is CapabilityStatus.AVAILABLE
        assert not hasattr(health_task, "facade")
        assert not hasattr(health_task, "services")


def test_production_web_index_references_tracked_build_assets() -> None:
    index = ROOT / "web/dist/index.html"
    references = re.findall(r'(?:src|href)="(/assets/[^"]+)"', index.read_text(encoding="utf-8"))
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "web/dist/assets"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
    )

    assert references
    assert {f"web/dist{reference}" for reference in references} <= tracked


def test_canonicalization_is_locale_independent_and_preserves_domain_encodings() -> None:
    instant = datetime(2026, 7, 11, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    left = {"z": None, "amount": Decimal("10.500"), "at": instant, "day": CanonicalDate(date(2026, 7, 10)), "mode": Mode.FIXTURE, "members": {"b", "a"}}
    right = {"members": {"a", "b"}, "mode": Mode.FIXTURE, "day": CanonicalDate(date(2026, 7, 10)), "at": datetime(2026, 7, 11, 0, 30, tzinfo=timezone.utc), "amount": Decimal("10.5"), "z": None}
    assert canonical_hash(left) == canonical_hash(right)
    assert canonical_hash(Decimal("10.5")) != canonical_hash("10.5")
    assert canonical_hash(Mode.FIXTURE) != canonical_hash("fixture")
    with pytest.raises(TypeError, match="binary float"):
        canonical_hash({"amount": 10.5})
    with pytest.raises(ValueError, match="offset"):
        canonical_hash(datetime(2026, 7, 11, 0, 30))
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_hash({1: "numeric", "1": "text"})


def test_code_identity_changes_with_source_lock_workflow_frontend_migration_and_config(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(); (tmp_path / "src/a.py").write_text("a=1", encoding="utf-8")
    (tmp_path / "web").mkdir(); (tmp_path / "web/app.js").write_text("1", encoding="utf-8")
    (tmp_path / "migrations").mkdir(); (tmp_path / "migrations/0001.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "src/trading_platform/workflows").mkdir(parents=True); (tmp_path / "src/trading_platform/workflows/research.py").write_text("V=1", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    first = build_code_identity(tmp_path, {"mode": "offline"})
    assert first.random_seed is None and first.determinism_basis == "deterministic"
    (tmp_path / "src/a.py").write_text("a=2", encoding="utf-8")
    second = build_code_identity(tmp_path, {"mode": "offline"})
    assert first.source_hash != second.source_hash
    (tmp_path / "pyproject.toml").write_text("[project]\nname='changed'", encoding="utf-8")
    assert first.lock_hash != build_code_identity(tmp_path, {"mode": "offline"}).lock_hash
    (tmp_path / "migrations/0001.sql").write_text("select 2", encoding="utf-8")
    assert first.migration_hash != build_code_identity(tmp_path, {"mode": "offline"}).migration_hash
    (tmp_path / "src/trading_platform/workflows/research.py").write_text("V=2", encoding="utf-8")
    assert first.workflow_hash != build_code_identity(tmp_path, {"mode": "offline"}).workflow_hash
    (tmp_path / "web/app.js").write_text("2", encoding="utf-8")
    assert first.frontend_hash != build_code_identity(tmp_path, {"mode": "offline"}).frontend_hash
    assert first.config_hash != build_code_identity(tmp_path, {"mode": "fixture"}).config_hash

    (tmp_path / "src/equity_research").mkdir(parents=True)
    (tmp_path / "src/equity_research/policies.py").write_text("POLICY=1", encoding="utf-8")
    before_policy_change = build_code_identity(tmp_path, {"mode": "offline"})
    (tmp_path / "src/equity_research/policies.py").write_text("POLICY=2", encoding="utf-8")
    assert before_policy_change.model_policy_hash != build_code_identity(tmp_path, {"mode": "offline"}).model_policy_hash


def test_platform_imports_only_public_research_package_and_has_no_forbidden_runtime_surface() -> None:
    forbidden_tokens = {"openai", "anthropic", "gemini", "kimi", "deepseek", "llm", "broker", "order", "skill", "prompt"}
    forbidden_execution_symbols = {
        "tradeexecution", "tradingexecution", "executetrade", "tradeexecutor",
        "executionrequest", "executioncommand", "executionadapter", "executionservice",
    }
    platform_root = ROOT / "src/trading_platform"
    for path in platform_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("equity_research"):
                assert node.module in {
                    "equity_research",
                    "equity_research.forecast",
                    "equity_research.scenario_valuation",
                }, f"private research import in {path}: {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("equity_research"):
                        assert alias.name == "equity_research", f"private research import in {path}: {alias.name}"
        public_symbols = [
            (node.id if isinstance(node, ast.Name) else node.name).lower()
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Name))
        ]
        assert not any(token in symbol for token in forbidden_tokens for symbol in public_symbols), path
        assert not any(token in symbol.replace("_", "") for token in forbidden_execution_symbols for symbol in public_symbols), path
        lowered = source.lower()
        assert not any(f"import {token}" in lowered or f"from {token}" in lowered for token in forbidden_tokens), path
        assert not any(
            legacy in lowered
            for legacy in (
                "source_manifest_validator",
                "model_validator",
                "report_validator",
            )
        ), path

    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert not any(token in project for token in forbidden_tokens)
    for resource in platform_root.rglob("*"):
        if resource.is_file() and resource.suffix not in {".py", ".pyc"}:
            lowered = resource.read_text(encoding="utf-8").lower()
            assert not any(token in lowered or token in resource.name.lower() for token in forbidden_tokens), resource
            compact = re.sub(r"[^a-z]", "", f"{resource.name} {lowered}")
            assert not any(token in compact for token in forbidden_execution_symbols), resource


def test_direct_sql_fixture_is_confined_to_owning_persistence_and_fault_suites() -> None:
    platform_tests = ROOT / "tests/platform"
    fixture_module = "tests.platform.owning_adapter_fixture"
    importers: set[str] = set()
    for path in platform_tests.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ImportFrom) and node.module == fixture_module
            for node in ast.walk(tree)
        ):
            importers.add(path.name)
    assert importers == OWNING_SQLITE_TESTS


def test_forecast_package_has_one_canonical_seam_and_inward_dependencies() -> None:
    import equity_research

    retired_root_aliases = {
        "CompanyArchetype",
        "DataSnapshot",
        "ForecastEngine",
        "ForecastGraph",
        "ForecastQuantity",
        "ForecastRequest",
    }
    assert not retired_root_aliases & set(vars(equity_research))

    forecast_root = ROOT / "src/equity_research/forecast"
    forbidden_dependency_parts = {
        "cli",
        "persistence",
        "presentation",
        "trading_platform",
        "web",
    }
    forbidden_runtime_paths = {
        "compatibility",
        "dual_read",
        "dual_write",
        "feature_flag",
        "legacy_builder",
        "old_new",
    }
    for path in forecast_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            forbidden_dependency_parts & set(module.split("."))
            for module in imported_modules
        ), path
        private_relative_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level > 0
            for alias in node.names
            if alias.name.startswith("_")
        }
        assert not private_relative_imports, (path, private_relative_imports)
        lowered = source.lower()
        assert not any(token in lowered for token in forbidden_runtime_paths), path


def test_scenario_valuation_has_one_canonical_package_seam() -> None:
    import equity_research
    from equity_research.scenario_valuation import ScenarioValuationEngine

    package_root = ROOT / "src/equity_research/scenario_valuation"
    assert {path.name for path in package_root.glob("*.py")} == {
        "__init__.py",
        "basis.py",
        "biopharma.py",
        "contracts.py",
        "cyclical.py",
        "engine.py",
        "financial_institution.py",
        "industrial.py",
    }
    assert (
        ScenarioValuationEngine.__module__
        == "equity_research.scenario_valuation.engine"
    )
    retired_root_aliases = {
        "DeterministicScenarioRequest",
        "DeterministicScenarioResult",
        "ScenarioDefinition",
        "ScenarioValuationEngine",
        "ValuationPlan",
    }
    assert not retired_root_aliases & set(vars(equity_research))
    assert not (ROOT / "src/equity_research/scenario.py").exists()

    forbidden_dependencies = {
        "cli",
        "persistence",
        "presentation",
        "trading_platform",
        "web",
    }
    forbidden_runtime_tokens = {
        "compatibility",
        "dual_read",
        "dual_write",
        "feature_flag",
        "legacy_builder",
        "old_new",
    }
    forbidden_private_helpers = {
        "_discount_times",
        "_financial_from_forecast",
        "_financial_projections",
    }
    for path in package_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            forbidden_dependencies & set(module.split("."))
            for module in imported_modules
        ), path
        referenced_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        assert not (forbidden_private_helpers & referenced_names), path
        lowered = source.lower()
        assert not any(token in lowered for token in forbidden_runtime_tokens), path
        if path.name != "contracts.py":
            assert "object.__new__" not in source, path
            assert "._build(" not in source, path
        if path.name not in {"engine.py", "__init__.py"}:
            assert "ForecastEngine" not in source, path

    allowed_imports = {
        "equity_research.scenario_valuation",
        "equity_research.scenario_valuation.basis",
        "equity_research.scenario_valuation.industrial",
    }
    for search_root in (ROOT / "src", ROOT / "tests"):
        for path in search_root.rglob("*.py"):
            if package_root in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            scenario_imports = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("equity_research.scenario")
            }
            assert scenario_imports <= allowed_imports, (path, scenario_imports)
            if "equity_research.scenario_valuation.basis" in scenario_imports:
                assert path == ROOT / "tests/test_scenario_valuation.py"
            if "equity_research.scenario_valuation.industrial" in scenario_imports:
                assert path == ROOT / "tests/test_scenario_valuation.py"


def test_recorded_regression_ledger_is_executable_and_complete() -> None:
    baseline = json.loads((ROOT / "tests/platform/regression_baseline.json").read_text(encoding="utf-8"))
    assert baseline["required_every_issue"] is True
    for suite in baseline["suites"]:
        assert (ROOT / suite).is_file()
    completed = subprocess.run(
        ["python", "-m", "pytest", "--collect-only", "-q", *baseline["suites"]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "collected" in completed.stdout
    for node_id in baseline["worked_examples"]:
        assert node_id in completed.stdout
