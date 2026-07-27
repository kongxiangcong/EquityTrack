from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from trading_platform.acceptance import AcceptanceEvidenceService
from trading_platform.application import open_platform_operations


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "trading_discipline_kernel"
    / "expected-manifest.json"
)


@pytest.mark.release_acceptance
def test_acceptance_cli_executes_canonical_kernel_gate() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "acceptance",
            "--data-root",
            str(ROOT / ".scratch" / "trading-discipline-kernel" / "acceptance-data"),
            "--fixture-manifest",
            str(FIXTURE),
            "--repo-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=1800,
    )
    envelope = json.loads(completed.stdout)
    manifest_path = (
        ROOT
        / ".scratch"
        / "trading-discipline-kernel"
        / "evidence"
        / "acceptance"
        / envelope["result"]["manifest_ref"]
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert envelope["ok"] is True
    assert (
        envelope["result"]["trading_discipline_kernel_acceptance"]
        == "passed"
    )
    assert manifest["trading_discipline_kernel_acceptance"] == "passed"
    assert manifest["trading_discipline_kernel_complete"] is True
    assert len(manifest["criteria"]) == 35
    assert all(item["status"] == "passed" for item in manifest["criteria"])
    assert {item["name"] for item in manifest["suites"]} == set(
        AcceptanceEvidenceService.REQUIRED_SUITES
    )
    assert all(item["status"] == "passed" for item in manifest["suites"])
    assert manifest["browser"]["status"] == "passed"
    assert all(
        "path" not in item
        for item in manifest["artifact_evidence"].values()
    )
    assert manifest_path.stat().st_mode & stat.S_IWUSR == 0


def test_report_preserves_exact_failure_timeout_and_external_status(
    tmp_path: Path,
) -> None:
    service = AcceptanceEvidenceService(tmp_path / "data", ROOT)
    artifacts = {}
    for name in (*service.REQUIRED_SUITES, "browser_cdp"):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps({"name": name}, sort_keys=True),
            encoding="utf-8",
        )
        artifacts[name] = service._artifact(path)

    statuses = {
        "contract": "passed",
        "workflow_and_journal": "failed",
        "presentation": "timeout",
        "migration_and_operations": "passed",
    }
    suites = [
        {
            "name": name,
            "status": status,
            "duration_seconds": 1.0,
            "exit_code": 0 if status == "passed" else None,
            "collected": 1,
            "passed": 1 if status == "passed" else 0,
            "failed": 1 if status == "failed" else 0,
            "skipped": 0,
            "timed_out": status == "timeout",
            "assertion_ids": [f"fixture::{name}"],
            "command_identity": name,
            "artifact_refs": [name],
            "first_failing_substep": (
                None if status == "passed" else f"{name}:fixture"
            ),
            "output_tail": "",
        }
        for name, status in statuses.items()
    ]
    criteria = [
        {
            "criterion": criterion,
            "status": "failed",
            "suite": suite,
            "assertion_ids": [],
            "artifact_refs": [suite],
        }
        for criterion, suite, _ in service.CRITERIA
    ]
    result = service._freeze(
        {
            "fixture": {
                "schema_version": service.FIXTURE_SCHEMA_VERSION,
                "manifest_sha256": "fixture",
            },
            "criteria": criteria,
            "suites": suites,
            "browser": {
                "name": "browser_cdp",
                "status": "failed",
                "duration_seconds": 2.0,
                "exit_code": 7,
                "first_failing_substep": "cdp.connect",
            },
            "artifacts": artifacts,
            "migration_hashes": {},
            "external_checks": [
                {
                    "name": "live_provider_qualification",
                    "status": "external_blocked",
                    "reason": "fixture",
                }
            ],
        }
    )
    report = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.status == "failed"
    assert [item["status"] for item in report["suites"]] == [
        "passed",
        "failed",
        "timeout",
        "passed",
    ]
    assert report["browser"]["status"] == "failed"
    assert report["external_checks"][0]["status"] == "external_blocked"
    assert report["trading_discipline_kernel_complete"] is False
    evidence_root = os.environ.get("TDK_ACCEPTANCE_EVIDENCE_ROOT")
    if evidence_root:
        (Path(evidence_root) / "acceptance-status-semantics.json").write_text(
            json.dumps(
                {
                    "schema_version": "AcceptanceStatusSemanticsEvidence@1",
                    "suite_statuses": [
                        item["status"] for item in report["suites"]
                    ],
                    "browser_status": report["browser"]["status"],
                    "external_status": report["external_checks"][0]["status"],
                    "overall_status": result.status,
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )


def test_browser_evidence_must_prove_real_cdp_journey(tmp_path: Path) -> None:
    evidence = tmp_path / "browser-evidence.json"
    evidence.write_text(json.dumps({"status": "passed"}), encoding="utf-8")

    with pytest.raises(ValueError, match="BROWSER_EVIDENCE_INVALID"):
        AcceptanceEvidenceService(
            tmp_path / "data",
            ROOT,
        ).validate_browser_evidence(evidence)


def test_acceptance_rejects_fixture_manifest_outside_trusted_root(
    tmp_path: Path,
) -> None:
    untrusted = tmp_path / "expected-manifest.json"
    untrusted.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="FIXTURE_MANIFEST_OUTSIDE_TRUSTED_ROOT"):
        AcceptanceEvidenceService(tmp_path / "data", ROOT)._load_fixture(
            untrusted
        )


def test_acceptance_cli_rejects_unregistered_receipt_artifact_id(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    assert open_platform_operations(data_root).bootstrap()["status"] == "passed"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "acceptance",
            "--data-root",
            str(data_root),
            "--fixture-manifest",
            str(FIXTURE),
            "--repo-root",
            str(ROOT),
            "--live-qualification-artifact-id",
            "artifact_" + "a" * 24,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert envelope["error"]["code"] == "QUALIFICATION_RECEIPT_NOT_FOUND"
