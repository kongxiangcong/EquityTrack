from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

from trading_platform.application.workflow_ledger import WorkflowPersistenceError
from pathlib import Path
from trading_platform.operations import OperationError
from trading_platform.persistence import PlatformStore
from trading_platform.provider_qualification import LedgerQualifiedEquivalentAuthority
from trading_platform.application import (
    open_acceptance_evidence,
    open_platform_operations,
    open_provider_qualification,
)

from tests.platform.provider_runtime_fixture import LoopbackTushareRuntime


def test_tushare_live_qualification_uses_production_sync_path_and_redacts_secret(tmp_path: Path) -> None:
    calls: list[str] = []
    responses = {
        "trade_cal": {"code": 0, "data": {"fields": ["exchange", "cal_date", "is_open"], "items": [["SZSE", "20260710", 1]]}},
        "stock_basic": {"code": 0, "data": {"fields": ["ts_code", "list_date"], "items": [["002897.SZ", "20170907"]]}},
        "daily": {"code": 0, "data": {"fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"], "items": [["002897.SZ", "20260710", 88.51, 91.0, 82.33, 82.33, 221879.03, 1926373.75544]]}},
        "income": {"code": 0, "data": {"fields": ["ts_code", "ann_date", "end_date", "report_type", "update_flag", "revenue", "n_income_attr_p"], "items": [["002897.SZ", "20260429", "20260331", "1", "1", 1000.0, 100.0]]}},
        "balancesheet": {"code": 0, "data": {"fields": ["ts_code", "ann_date", "end_date", "report_type", "update_flag", "money_cap", "st_borr"], "items": [["002897.SZ", "20260429", "20260331", "1", "1", 500.0, 200.0]]}},
        "cashflow": {"code": 0, "data": {"fields": ["ts_code", "ann_date", "end_date", "report_type", "update_flag", "n_cashflow_act", "c_pay_acq_const_fiolta"], "items": [["002897.SZ", "20260429", "20260331", "1", "1", 150.0, 50.0]]}},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            size = int(self.headers["Content-Length"])
            request = json.loads(self.rfile.read(size))
            calls.append(request["api_name"])
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
            "schema_version": "ProviderJob@2",
            "provider": {
                "provider_id": "tushare-compatible",
                "adapter_version": "tushare-http@2",
                "credential_env": "TUSHARE_TOKEN",
            },
            "query_policy": {
                "schema_version": "QueryPolicy@1",
                "lookback_days": 550,
                "market_universe_list_status": "L",
                "adjustment_mode": "none",
            },
            "source_policy": {
                "schema_version": "SourcePolicy@1",
                "provider_id": "tushare-compatible",
                "adapter_version": "tushare-http@2",
                "source_identity": "preconfigured_tushare_compatible_non_official",
                "source_authority": "structured_aggregator",
                "terms_profile": "gateway-terms-pending@1",
                "rights": {
                    "automation_allowed": True,
                    "local_storage_allowed": True,
                    "deterministic_replay_allowed": True,
                    "derived_use_allowed": True,
                    "redistribution_allowed": False,
                    "reviewed_on": "2026-07-24",
                    "evidence_sha256": None,
                },
                "routes": [
                    {
                        "dataset": dataset,
                            "freshness_max_stale_days": 1,
                        "completeness": (
                            "optional"
                            if dataset == "cashflow"
                            else "required"
                        ),
                            "retry_max_attempts": 1,
                        "fallback": "no_fallback",
                        "failure_disposition": (
                            "quarantine"
                            if dataset == "cashflow"
                            else "block"
                        ),
                    }
                    for dataset in (
                        "trade_cal",
                        "market_universe",
                        "daily",
                        "income",
                        "balancesheet",
                        "cashflow",
                    )
                ],
            },
            "request": {
                "invocation_id": "qualify-live",
                "security_id": "security_yihua",
                "security_code": "002897",
                "requested_date": "2026-07-10",
                "as_of_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                "market_timezone": "Asia/Shanghai",
                "market": "SZSE",
                "snapshot_purpose": "workflow",
                "datasets": [
                    "trade_cal",
                    "market_universe",
                    "daily",
                    "income",
                    "balancesheet",
                    "cashflow",
                ],
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

        assert open_platform_operations(tmp_path / "data").bootstrap()["status"] == "passed"
        with open_provider_qualification(
            tmp_path / "data", job_path, provider_runtime=LoopbackTushareRuntime(f"http://127.0.0.1:{server.server_port}/")
        ) as qualification:
            result = qualification.run()
        artifact_path = tmp_path / "qualification.json"
        with open_provider_qualification(
            tmp_path / "data", job_path, provider_runtime=LoopbackTushareRuntime(f"http://127.0.0.1:{server.server_port}/")
        ) as replay_qualification:
            replay_result = replay_qualification.run()
        assert replay_result.receipt_artifact_id == result.receipt_artifact_id
        cached_job = json.loads(job_path.read_text(encoding="utf-8"))
        cached_job["request"]["invocation_id"] = "qualify-cached"
        cached_job_path = tmp_path / "cached-job.json"
        cached_job_path.write_text(
            json.dumps(cached_job),
            encoding="utf-8",
        )
        with open_provider_qualification(
            tmp_path / "data",
            cached_job_path,
            provider_runtime=LoopbackTushareRuntime(
                f"http://127.0.0.1:{server.server_port}/"
            ),
        ) as cached_qualification:
            cached_result = cached_qualification.run()
        assert cached_result.status == "qualified"

    finally:
        server.shutdown()
        server.server_close()

    assert result.status == "qualified"
    assert result.provider_identity == "preconfigured_tushare_compatible_non_official"
    assert {item.dataset for item in result.attempts} == {
        "trade_cal",
        "market_universe",
        "daily",
        "income",
        "balancesheet",
        "cashflow",
    }
    assert all(item.status == "complete" and item.raw_sha256 is not None and len(item.raw_sha256) == 64 for item in result.attempts)
    assert "secret-not-for-artifacts" not in json.dumps(result.to_dict())
    expected_calls = [
        "trade_cal",
        "stock_basic",
        "daily",
        "income",
        "balancesheet",
        "cashflow",
    ]
    assert calls == expected_calls * 2
    artifact_id = result.receipt_artifact_id
    live = open_acceptance_evidence(
        tmp_path / "data",
        Path(__file__).resolve().parents[2],
    )._live_status(artifact_id)
    repo = Path(__file__).resolve().parents[2]
    store = PlatformStore(tmp_path / "data", repo / "migrations")
    try:
        authority = LedgerQualifiedEquivalentAuthority(store.workflow_ledger)
        with pytest.raises(OperationError) as nonproduction_authority:
            authority.authorize(
                result.receipt_artifact_id, result.provider_id, result.adapter_version,
                result.source_policy_identity, "daily", result.adapter_code_identity,
                result.transport_identity,
            )
        assert nonproduction_authority.value.code == "QUALIFIED_EQUIVALENT_NOT_AUTHORIZED"
    finally:
        store.close()

    assert live["status"] == "qualified"
    assert artifact_id.startswith("artifact_")
    with sqlite3.connect(tmp_path / "data/platform.sqlite3") as connection:
        receipt = connection.execute(
            "SELECT command_name,result_type,result_id FROM command_receipt "
            "WHERE invocation_id='qualify-live'"
        ).fetchone()
        raw_object = connection.execute(
            "SELECT o.relative_path FROM provider_attempt a "
            "JOIN object_blob o ON o.sha256=a.raw_sha256 "
            "WHERE a.invocation_id='qualify-live' ORDER BY a.attempt_id LIMIT 1"
        ).fetchone()
    assert receipt == ("provider-qualify@2", "ProviderQualificationReceipt", artifact_id)
    with sqlite3.connect(tmp_path / "data/platform.sqlite3") as connection:
        connection.execute(
            "UPDATE data_snapshot SET quality_status='blocking' WHERE data_snapshot_id=?",
            (result.data_snapshot_id,),
        )
    with pytest.raises(WorkflowPersistenceError) as blocked_snapshot:
        with open_provider_qualification(
            tmp_path / "data", job_path,
            provider_runtime=LoopbackTushareRuntime(f"http://127.0.0.1:{server.server_port}/"),
        ) as replay_qualification:
            replay_qualification.run()
    assert blocked_snapshot.value.code == "QUALIFICATION_RECEIPT_LINEAGE_INVALID"
    with sqlite3.connect(tmp_path / "data/platform.sqlite3") as connection:
        connection.execute(
            "UPDATE data_snapshot SET quality_status='pass' WHERE data_snapshot_id=?",
            (result.data_snapshot_id,),
        )

    assert not artifact_path.exists()

    raw_path = tmp_path / "data" / Path(*raw_object[0].split("/"))
    raw_path.write_bytes(b"tampered-provider-response")
    with pytest.raises(WorkflowPersistenceError) as tampered:
        with open_provider_qualification(
            tmp_path / "data", job_path,
            provider_runtime=LoopbackTushareRuntime(f"http://127.0.0.1:{server.server_port}/"),
        ) as replay_qualification:
            replay_qualification.run()
    assert tampered.value.code == "QUALIFICATION_RECEIPT_INTEGRITY_FAILED"


def test_provider_job_v2_rejects_retired_class_selector_contract(tmp_path: Path) -> None:
    job_path = tmp_path / "retired-job.json"
    job_path.write_text(
        json.dumps(
            {
                "provider": {
                    "provider_" + "type": "tushare_compatible",
                    "provider_id": "retired",
                    "adapter_version": "retired@1",
                },
                "request": {},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_platform.cli",
            "sync",
            "--data-root",
            str(tmp_path / "data"),
            "--job-file",
            str(job_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert envelope["error"]["code"] == "PROVIDER_JOB_INVALID"


def test_public_qualification_rejects_caller_spoofed_source_authority(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    job = json.loads(
        (repo / "examples/platform/tushare-compatible-yihua-job.json").read_text(encoding="utf-8")
    )
    job["source_policy"]["source_authority"] = "official"
    job["request"]["invocation_id"] = "spoofed-source-authority"
    job_path = tmp_path / "spoofed-job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    assert open_platform_operations(tmp_path / "data").bootstrap()["status"] == "passed"

    with pytest.raises(Exception) as rejected:
        with open_provider_qualification(
            tmp_path / "data", job_path,
            provider_runtime=LoopbackTushareRuntime("http://127.0.0.1:9/"),
        ) as qualification:
            qualification.run()

    job["source_policy"]["source_authority"] = "structured_aggregator"
    job["source_policy"]["routes"][0]["retry_max_attempts"] = 5
    job["request"]["invocation_id"] = "caller-selected-source-route"
    route_job_path = tmp_path / "caller-route-job.json"
    route_job_path.write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(Exception) as route_rejected:
        with open_provider_qualification(
            tmp_path / "data", route_job_path,
            provider_runtime=LoopbackTushareRuntime("http://127.0.0.1:9/"),
        ) as qualification:
            qualification.run()
    assert getattr(route_rejected.value, "code", None) == "PROVIDER_SOURCE_POLICY_UNTRUSTED"
    assert getattr(rejected.value, "code", None) == "PROVIDER_SOURCE_POLICY_UNTRUSTED"
