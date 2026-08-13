from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from trading_platform.application import (
    SecurityIdentity,
    open_account_current_export,
    open_account_acceptance,
    open_account_history,
    open_platform_health,
)
from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.test_research_workflow import _request
from trading_platform.operations import OperationError


ROOT = Path(__file__).resolve().parents[2]


def test_health_cli_uses_named_task_and_preserves_json_envelope(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    bootstrap = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "bootstrap",
            "--data-root",
            str(data_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "health",
            "--data-root",
            str(data_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert envelope["ok"] is True
    assert envelope["operation"] == "health"
    assert envelope["result"]["capabilities"]["health"] == "available"
    assert envelope["result"]["capabilities"]["persistence"] == "available"


def test_cli_application_command_uses_shared_envelope_and_dispatcher(
    tmp_path: Path,
) -> None:
    from tests.platform.test_account_snapshots import _draft, _ready_root

    data_root = _ready_root(tmp_path)
    command_file = tmp_path / "command.json"
    command_file.write_text(
        json.dumps(
            {
                "schema_version": "ApplicationCommandEnvelope@1",
                "command_name": "account_snapshot.create_draft@1",
                "invocation_id": "cli-envelope:create:1",
                "payload_schema_version": "CreateAccountSnapshotDraft@1",
                "expected_revision": None,
                "decision_actor": {
                    "actor_type": "agent",
                    "actor_id": "codex",
                },
                "interaction_channel": "skill",
                "transport_actor": {
                    "actor_type": "agent",
                    "actor_id": "codex",
                },
                "approval": None,
                "payload": {"draft": asdict(_draft())},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "application-command",
            "--data-root",
            str(data_root),
            "--envelope-file",
            str(command_file),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert envelope["operation"] == "application-command"
    assert envelope["result"]["schema_version"] == "ApplicationCommandResult@1"
    assert envelope["result"]["command_name"] == "account_snapshot.create_draft@1"


def test_named_task_openers_never_bootstrap_or_migrate_implicitly(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "uninitialized"
    with pytest.raises(OperationError) as caught:
        with open_platform_health(data_root):
            pass

    assert caught.value.code == "PLATFORM_NOT_BOOTSTRAPPED"
    assert not (data_root / "platform.sqlite3").exists()

    for opener in (
        lambda: open_account_current_export(data_root, ROOT),
        lambda: open_account_history(data_root, ROOT),
        lambda: open_account_acceptance(data_root, ROOT / "migrations"),
    ):
        with pytest.raises(OperationError) as account_caught:
            opener()
        assert account_caught.value.code == "PLATFORM_NOT_BOOTSTRAPPED"
        assert not (data_root / "platform.sqlite3").exists()


def test_cli_imports_public_named_tasks_not_root_facade_or_persistence() -> None:
    source = (ROOT / "src/trading_platform/cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "trading_platform.application.root" not in imports
    assert "trading_platform.application.facade" not in imports
    assert not any(
        module.startswith("trading_platform.persistence") for module in imports
    )
    application_imports = {
        module
        for module in imports
        if module.startswith("trading_platform.application")
    }
    assert application_imports == {"trading_platform.application"}
    assert "ProductionCompositionRoot" not in source
    assert ".facade" not in source


def test_retired_routes_facade_ports_and_forwarders_are_deleted() -> None:
    retired = (
        ROOT / "scripts/research.py",
        ROOT / "scripts/serve_chart_workspace.py",
        ROOT / "src/equity_research/cli.py",
        ROOT / "src/equity_research/__main__.py",
        ROOT / "src/equity_research/report.py",
        ROOT / "src/equity_research/professional_report.py",
        ROOT / "src/trading_platform/application/root.py",
        ROOT / "src/trading_platform/application/facade.py",
        ROOT / "src/trading_platform/application/ports.py",
    )
    assert not any(path.exists() for path in retired)

    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'trading-platform = "trading_platform.cli:main"' in project
    assert "equity_research.cli" not in project
    cli = (ROOT / "src/trading_platform/cli.py").read_text(encoding="utf-8")
    assert 'add_parser("daily")' not in cli
    assert "open_daily_research_cycle" not in cli


def test_application_tasks_depend_inward_and_composition_has_no_locator() -> None:
    application = ROOT / "src/trading_platform/application"
    for path in application.glob("*.py"):
        if path.name == "bootstrap.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not any(
            module.startswith("trading_platform.persistence") for module in imports
        ), path

    bootstrap = (application / "bootstrap.py").read_text(encoding="utf-8")
    assert "ProductionCompositionRoot" not in bootstrap
    assert "service_lookup" not in bootstrap
    assert "task_bag" not in bootstrap


def test_research_cli_failure_is_typed_actionable_and_redacted(tmp_path: Path) -> None:
    secret = "local-secret-must-not-leak"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"unexpected": secret}), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "research",
            "--data-root",
            str(tmp_path / "data"),
            "--request-file",
            str(request),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert envelope["error"]["code"] == "RESEARCH_REQUEST_INVALID"
    assert envelope["error"]["diagnostic"] == {
        "cause_type": "KeyError",
        "substep": "research_request.decode",
    }
    assert secret not in completed.stdout + completed.stderr


def test_sync_job_failure_is_typed_actionable_and_redacted(tmp_path: Path) -> None:
    secret = "provider-secret-must-not-leak"
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"provider": {"secret": secret}}), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "sync",
            "--data-root",
            str(tmp_path / "data"),
            "--job-file",
            str(job),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert envelope["error"]["code"] == "PROVIDER_JOB_INVALID"
    assert envelope["error"]["diagnostic"] == {
        "cause_type": "TypeError",
        "substep": "provider_job.decode",
    }
    assert secret not in completed.stdout + completed.stderr


def test_research_inspection_and_archive_cli_cross_named_tasks(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    fixture = PlatformTaskFixture(data_root)
    fixture.watchlist.add(
        "cli:watch",
        SecurityIdentity("security_yihua", "SZSE", "002897", "CNY", "2017-09-07"),
    )
    fixture.faults.record_official_filing_workflow_snapshot()
    fixture.close()
    request_file = tmp_path / "request.json"
    request_file.write_text(
        json.dumps(asdict(_request("cli:research")), ensure_ascii=False),
        encoding="utf-8",
    )

    def run(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, "-m", "trading_platform.cli", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return json.loads(completed.stdout)

    research = run(
        "research",
        "--data-root",
        str(data_root),
        "--request-file",
        str(request_file),
    )["result"]
    history = run(
        "history",
        "--data-root",
        str(data_root),
        "--workflow-run-id",
        research["workflow_run_id"],
    )["result"]
    manifest = run(
        "archive",
        "--data-root",
        str(data_root),
        "--kind",
        "manifest",
        "--id",
        history["final_manifest_id"],
    )["result"]

    assert history["status"] in {"succeeded", "succeeded_with_limits"}
    assert manifest["producer_id"] == research["workflow_run_id"]


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "trading_platform.cli", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_account_show_cli_resolves_alias_and_projects_security_codes(
    tmp_path: Path,
) -> None:
    from tests.platform.test_account_snapshots import _draft, _ready_root
    from tests.platform.test_estimated_account_state import _confirmed
    from trading_platform.application import open_watchlist

    data_root = _ready_root(tmp_path)
    _confirmed(
        data_root,
        _draft(
            cash_state="known",
            cash_value="1000",
            available_state="known",
            available_value="100",
        ),
        create_invocation="cli-account-show:create:1",
        confirm_invocation="cli-account-show:confirm:1",
    )
    with open_watchlist(data_root) as watchlist:
        watchlist.add(
            "cli-account-show:watch:1",
            SecurityIdentity("security_600000", "SHSE", "600000", "CNY", "2026-07-24"),
        )

    completed = _run_cli(
        "account-show", "--data-root", str(data_root), "--account", "local"
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert envelope["ok"] is True
    assert envelope["operation"] == "account-show"
    result = envelope["result"]
    assert result["account_reference"] == "local"
    assert result["resolved_account_id"] == "account_local"
    state = result["estimated_account_state"]
    assert state["cash_state"] == "known"
    assert state["cash_value"] == "1000"
    assert len(state["positions"]) == 1
    position = state["positions"][0]
    assert position["security_id"] == "security_600000"
    assert position["total_quantity"] == "100"
    assert position["market"] == "SHSE"
    assert position["code"] == "600000"


def test_account_show_cli_reports_typed_error_for_unknown_account(
    tmp_path: Path,
) -> None:
    from tests.platform.test_account_snapshots import _ready_root

    data_root = _ready_root(tmp_path)

    completed = _run_cli(
        "account-show", "--data-root", str(data_root), "--account", "missing"
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert envelope["ok"] is False
    assert envelope["operation"] == "account-show"
    assert envelope["error"]["code"] == "ACCOUNT_REFERENCE_NOT_FOUND"
