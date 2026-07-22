from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_platform.acceptance import AcceptanceEvidenceService, BrowserAcceptanceError


@pytest.mark.release_acceptance
def test_acceptance_cli_executes_fixed_suites_and_freezes_evidence(tmp_path: Path) -> None:
    fixture = Path.cwd() / "tests/fixtures/platform_data/manifest.json"
    qualification = tmp_path / "qualification.json"
    qualification.write_text(json.dumps({
        "status": "qualified",
        "provider_identity": "preconfigured_tushare_compatible_non_official",
        "source_authority": "structured_aggregator_not_official_disclosure",
        "terms_profile": "gateway-terms-pending@1",
        "credential_scope_id": "c" * 64,
        "attempts": [{"attempt_id": "attempt-redacted", "dataset": "daily", "status": "complete", "raw_sha256": "a" * 64, "retrieved_at": "2026-07-14T00:00:00+00:00", "error_code": None}],
        "blockers": [],
    }), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "trading_platform.cli", "acceptance", "--data-root", str(tmp_path / "data"), "--fixture-manifest", str(fixture), "--repo-root", str(Path.cwd()), "--live-qualification-file", str(qualification)],
        cwd=Path.cwd(), capture_output=True, text=True, encoding="utf-8", check=False,
    )
    envelope = json.loads(completed.stdout)
    manifest_path = tmp_path / "data/acceptance" / envelope["result"]["manifest_ref"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert envelope["ok"] is True
    assert manifest["slice_acceptance"] == "passed"
    assert manifest["live_qualification"]["status"] == "qualified"
    assert manifest["long_term_platform_complete"] is False
    assert len(manifest["criteria"]) == 51
    assert all(item["assertion_ids"] for item in manifest["criteria"])
    assert {item["name"] for item in manifest["suites"]} == set(AcceptanceEvidenceService.REQUIRED_SUITES)
    assert all(item["status"] == "passed" and item["command_identity"] for item in manifest["suites"])
    assert all("path" not in item for item in manifest["artifact_evidence"].values())
    assert manifest["browser_evidence_ref"] == "browser_cdp"
    assert manifest["artifact_evidence"]["browser_cdp"]["sha256"]
    assert manifest_path.stat().st_mode & stat.S_IWUSR == 0
    assert str(tmp_path) not in completed.stdout


def test_browser_evidence_must_prove_real_cdp_journey(tmp_path: Path) -> None:
    evidence = tmp_path / "browser-evidence.json"
    evidence.write_text(json.dumps({"status": "passed"}), encoding="utf-8")

    with pytest.raises(ValueError, match="BROWSER_EVIDENCE_INVALID"):
        AcceptanceEvidenceService(tmp_path / "data", Path.cwd()).validate_browser_evidence(evidence)


def test_browser_verifier_failure_preserves_redacted_substep_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "browser-verifier-secret"
    monkeypatch.setenv("BROWSER_API_TOKEN", secret)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=7,
            stdout=f"token={secret}",
            stderr="CDP connection refused",
        ),
    )
    fixture = Path.cwd() / "tests/fixtures/platform_data/manifest.json"

    with pytest.raises(BrowserAcceptanceError) as captured:
        AcceptanceEvidenceService(tmp_path / "data", Path.cwd()).run(fixture)

    error = captured.value
    assert error.code == "BROWSER_ACCEPTANCE_FAILED"
    assert error.substep == "acceptance.browser_cdp"
    assert error.exit_code == 7
    assert error.command_identity
    assert secret not in error.output_tail
    assert "[REDACTED]" in error.output_tail
    assert "CDP connection refused" in error.output_tail


def test_acceptance_rejects_fixture_manifest_outside_trusted_root(tmp_path: Path) -> None:
    untrusted = tmp_path / "manifest.json"
    untrusted.write_text("{}", encoding="utf-8")

    try:
        AcceptanceEvidenceService(tmp_path / "data", Path.cwd()).run(untrusted)
    except ValueError as error:
        assert str(error) == "FIXTURE_MANIFEST_OUTSIDE_TRUSTED_ROOT"
    else:
        raise AssertionError("untrusted fixture manifest was accepted")


def test_live_qualified_accepts_redacted_production_attempt_evidence() -> None:
    failures: list[str] = []
    result = AcceptanceEvidenceService._live_qualification(
        {
            "status": "qualified",
            "provider_identity": "gateway",
            "source_authority": "structured_aggregator_not_official_disclosure",
            "terms_profile": "terms@1",
            "attempts": [
                {"attempt_id": "attempt-redacted", "dataset": "daily", "status": "complete", "raw_sha256": "a" * 64, "retrieved_at": "2026-07-14T00:00:00+00:00", "error_code": None}
            ],
            "blockers": [],
        },
        failures,
    )

    assert result["status"] == "qualified"
    assert failures == []
