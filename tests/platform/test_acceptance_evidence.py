from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

from trading_platform.acceptance import AcceptanceEvidenceService


def test_acceptance_cli_executes_fixed_suites_and_freezes_evidence(tmp_path: Path) -> None:
    fixture = Path.cwd() / "tests/fixtures/platform_data/manifest.json"
    completed = subprocess.run(
        [sys.executable, "-m", "trading_platform.cli", "acceptance", "--data-root", str(tmp_path / "data"), "--fixture-manifest", str(fixture), "--repo-root", str(Path.cwd())],
        cwd=Path.cwd(), capture_output=True, text=True, encoding="utf-8", check=False,
    )
    envelope = json.loads(completed.stdout)
    manifest_path = tmp_path / "data/acceptance" / envelope["result"]["manifest_ref"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert envelope["ok"] is True
    assert manifest["slice_acceptance"] == "passed"
    assert manifest["live_qualification"]["status"] == "external_blocked"
    assert manifest["long_term_platform_complete"] is False
    assert len(manifest["criteria"]) == 51
    assert all(item["assertion_ids"] for item in manifest["criteria"])
    assert {item["name"] for item in manifest["suites"]} == set(AcceptanceEvidenceService.REQUIRED_SUITES)
    assert all(item["status"] == "passed" and item["command_identity"] for item in manifest["suites"])
    assert all("path" not in item for item in manifest["artifact_evidence"].values())
    assert manifest_path.stat().st_mode & stat.S_IWUSR == 0
    assert str(tmp_path) not in completed.stdout


def test_acceptance_rejects_fixture_manifest_outside_trusted_root(tmp_path: Path) -> None:
    untrusted = tmp_path / "manifest.json"
    untrusted.write_text("{}", encoding="utf-8")

    try:
        AcceptanceEvidenceService(tmp_path / "data", Path.cwd()).run(untrusted)
    except ValueError as error:
        assert str(error) == "FIXTURE_MANIFEST_OUTSIDE_TRUSTED_ROOT"
    else:
        raise AssertionError("untrusted fixture manifest was accepted")


def test_live_qualified_requires_real_attempt_evidence() -> None:
    failures: list[str] = []
    result = AcceptanceEvidenceService._live_qualification(
        {"status": "qualified", "provider_identity": "gateway", "source_authority": "not_official", "terms_profile": "terms@1", "attempts": []},
        failures,
    )

    assert result["status"] == "failed"
    assert failures == ["LIVE_QUALIFICATION_RUNNER_UNAVAILABLE"]
