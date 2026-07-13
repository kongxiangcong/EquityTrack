from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from trading_platform.provider_qualification import ProviderQualificationService


class _CredentialAdapter:
    def get(self, scope: str) -> str | None:
        return "secret-not-for-artifacts" if scope == "TUSHARE_TOKEN" else None


def test_tushare_live_qualification_uses_production_sync_path_and_redacts_secret(tmp_path: Path) -> None:
    responses = {
        "trade_cal": {"code": 0, "data": {"fields": ["exchange", "cal_date", "is_open"], "items": [["SZSE", "20260710", 1]]}},
        "stock_basic": {"code": 0, "data": {"fields": ["ts_code", "list_date"], "items": [["002897.SZ", "20170907"]]}},
        "daily": {"code": 0, "data": {"fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"], "items": [["002897.SZ", "20260710", 88.51, 91.0, 82.33, 82.33, 221879.03, 1926373.75544]]}},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            size = int(self.headers["Content-Length"])
            request = json.loads(self.rfile.read(size))
            assert request["token"] == "secret-not-for-artifacts"
            payload = json.dumps(responses[request["api_name"]]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        job_path = tmp_path / "job.json"
        job_path.write_text(json.dumps({
            "provider": {
                "provider_type": "tushare_compatible",
                "provider_id": "tushare-compatible",
                "adapter_version": "tushare-http@1",
                "endpoint": f"http://127.0.0.1:{server.server_port}/",
                "credential_env": "TUSHARE_TOKEN",
                "source_identity": "preconfigured_tushare_compatible_non_official",
                "terms_profile": "gateway-terms-pending@1",
            },
            "request": {
                "invocation_id": "qualify-live",
                "security_id": "security_yihua",
                "provider_security_code": "002897.SZ",
                "requested_date": "2026-07-10",
                "as_of_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                "market_timezone": "Asia/Shanghai",
                "market": "SZSE",
                "snapshot_purpose": "workflow",
                "datasets": ["trade_cal", "market_universe", "daily"],
                "network_authorized": True,
                "offline": False,
            },
            "security_identity": {
                "security_id": "security_yihua",
                "venue": "SZSE",
                "code": "002897",
                "currency": "CNY",
                "listed_from": "2017-09-07"
            },
        }), encoding="utf-8")

        result = ProviderQualificationService(tmp_path / "data", _CredentialAdapter()).run(job_path)
        artifact_path = tmp_path / "qualification.json"
        environment = os.environ.copy()
        environment["TUSHARE_TOKEN"] = "secret-not-for-artifacts"
        completed = subprocess.run(
            [sys.executable, "-m", "trading_platform.cli", "provider-qualify", "--data-root", str(tmp_path / "cli-data"), "--job-file", str(job_path), "--output", str(artifact_path)],
            cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True, text=True, encoding="utf-8", check=False,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result["status"] == "qualified"
    assert result["provider_identity"] == "preconfigured_tushare_compatible_non_official"
    assert {item["dataset"] for item in result["attempts"]} == {"trade_cal", "market_universe", "daily"}
    assert all(item["status"] == "complete" and len(item["raw_sha256"]) == 64 for item in result["attempts"])
    assert "secret-not-for-artifacts" not in json.dumps(result)
    envelope = json.loads(completed.stdout)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert completed.returncode == 0 and envelope["result"]["status"] == "qualified"
    assert artifact["status"] == "qualified" and "secret-not-for-artifacts" not in artifact_path.read_text(encoding="utf-8")
