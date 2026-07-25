from __future__ import annotations

import json
import stat
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_platform.acceptance import AcceptanceEvidenceService, BrowserAcceptanceError
from trading_platform.application import open_platform_operations, open_provider_qualification
from trading_platform.data.providers import TransportResponse, TushareCompatibleProvider


@pytest.mark.release_acceptance
def test_acceptance_cli_executes_fixed_suites_and_freezes_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Path.cwd() / "tests/fixtures/platform_data/manifest.json"
    data_root = tmp_path / "data"
    responses = {
        "trade_cal": {"code": 0, "data": {"fields": ["exchange", "cal_date", "is_open"], "items": [["SZSE", "20260710", 1]]}},
        "stock_basic": {"code": 0, "data": {"fields": ["ts_code", "list_date"], "items": [["002897.SZ", "20170907"]]}},
        "daily": {"code": 0, "data": {"fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"], "items": [["002897.SZ", "20260710", 88.51, 91.0, 82.33, 82.33, 221879.03, 1926373.75544]]}},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            payload = json.dumps(responses[request["api_name"]]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    def production_transport(request) -> TransportResponse:
        body = json.loads(request.data.decode("utf-8"))
        return TransportResponse(json.dumps(responses[body["api_name"]]).encode(), {})

    monkeypatch.setenv("TUSHARE_TOKEN", "acceptance-secret")
    monkeypatch.setattr(TushareCompatibleProvider, "_default_transport", staticmethod(production_transport))

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        job_path = tmp_path / "provider-job.json"
        job_path.write_text(json.dumps({
            "schema_version": "ProviderJob@2",
            "provider": {"provider_id": "tushare-compatible", "adapter_version": "tushare-http@2", "credential_env": "TUSHARE_TOKEN"},
            "query_policy": {"schema_version": "QueryPolicy@1", "lookback_days": 7, "market_universe_list_status": "L", "adjustment_mode": "none"},
            "source_policy": {
                "schema_version": "SourcePolicy@1", "provider_id": "tushare-compatible", "adapter_version": "tushare-http@2",
                "source_identity": "preconfigured_tushare_compatible_non_official", "source_authority": "structured_aggregator", "terms_profile": "gateway-terms-pending@1",
                "rights": {"automation_allowed": True, "local_storage_allowed": True, "deterministic_replay_allowed": True, "derived_use_allowed": True, "redistribution_allowed": False, "reviewed_on": "2026-07-24", "evidence_sha256": None},
                "routes": [{"dataset": dataset, "freshness_max_stale_days": 1, "completeness": "required", "retry_max_attempts": 1, "fallback": "no_fallback", "failure_disposition": "block"} for dataset in ("trade_cal", "market_universe", "daily")],
            },
            "request": {"invocation_id": "acceptance-qualification", "security_id": "security_yihua", "security_code": "002897", "requested_date": "2026-07-10", "as_of_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(), "market_timezone": "Asia/Shanghai", "market": "SZSE", "snapshot_purpose": "workflow", "datasets": ["trade_cal", "market_universe", "daily"], "network_authorized": True, "offline": False},
            "security_identity": {"security_id": "security_yihua", "venue": "SZSE", "code": "002897", "currency": "CNY", "listed_from": "2017-09-07"},
        }), encoding="utf-8")
        assert open_platform_operations(data_root).bootstrap()["status"] == "passed"
        with open_provider_qualification(data_root, job_path) as qualification:
            receipt_artifact_id = qualification.run().receipt_artifact_id
    finally:
        server.shutdown()
        server.server_close()

    completed = subprocess.run(
        [sys.executable, "-m", "trading_platform.cli", "acceptance", "--data-root", str(data_root), "--fixture-manifest", str(fixture), "--repo-root", str(Path.cwd()), "--live-qualification-artifact-id", receipt_artifact_id],
        cwd=Path.cwd(), capture_output=True, text=True, encoding="utf-8", check=False,
    )
    envelope = json.loads(completed.stdout)
    manifest_path = tmp_path / "data/acceptance" / envelope["result"]["manifest_ref"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert envelope["ok"] is True
    assert manifest["slice_acceptance"] == "passed"
    assert manifest["live_qualification"]["status"] == "qualified"
    stale_receipt = dict(manifest["live_qualification"])
    stale_receipt["qualified_at"] = "2026-07-20T00:00:00+00:00"
    stale_failures: list[str] = []
    stale = AcceptanceEvidenceService._live_qualification(stale_receipt, stale_failures)
    assert stale["status"] == "failed"
    assert "LIVE_QUALIFICATION_EVIDENCE_INVALID" in stale_failures
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


def test_acceptance_cli_rejects_retired_caller_authored_qualification_file(tmp_path: Path) -> None:
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({"status": "qualified"}), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable, "-m", "trading_platform.cli", "acceptance",
            "--data-root", str(tmp_path / "data"),
            "--fixture-manifest", str(Path.cwd() / "tests/fixtures/platform_data/manifest.json"),
            "--live-qualification-" + "file", str(forged),
        ],
        cwd=Path.cwd(), capture_output=True, text=True, encoding="utf-8", check=False,
    )

    assert completed.returncode == 2
    envelope = json.loads(completed.stdout)
    assert envelope["error"]["code"] == "CLI_ARGUMENT_INVALID"
    assert "qualified" not in completed.stdout

def test_acceptance_cli_rejects_unregistered_receipt_artifact_id(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    assert open_platform_operations(data_root).bootstrap()["status"] == "passed"
    completed = subprocess.run(
        [
            sys.executable, "-m", "trading_platform.cli", "acceptance",
            "--data-root", str(data_root),
            "--fixture-manifest", str(Path.cwd() / "tests/fixtures/platform_data/manifest.json"),
            "--live-qualification-artifact-id", "artifact_" + "a" * 24,
        ],
        cwd=Path.cwd(), capture_output=True, text=True, encoding="utf-8", check=False,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert envelope["error"]["code"] == "QUALIFICATION_RECEIPT_NOT_FOUND"
