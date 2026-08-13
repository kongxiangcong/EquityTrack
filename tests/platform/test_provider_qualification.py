from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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

from tests.platform.provider_runtime_fixture import (
    FakeAgentGwRuntime,
    RawResponse,
    csv_response,
)


_KIMI_JOB_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "platform"
    / "kimi-agentgw-yihua-job.json"
)


def _agentgw_handler(calls: list[str]):
    responses = {
        "wind_get_index_price": csv_response(
            ["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"],
            [["2026-07-10", "000001.SH", "3808", "3858", "3793", "3858", "1", "1"]],
        ),
        "wind_get_stock_info": csv_response(
            ["wind_code", "证券简称", "首发上市日期"],
            [["002897.SZ", "意华股份", "2017-09-07"]],
        ),
        "wind_get_price": csv_response(
            ["trade_date", "wind_code", "open", "high", "low", "close", "volume", "amt"],
            [["2026-07-10", "002897.SZ", "88.51", "91.0", "82.33", "82.33", "22187903", "1926373755"]],
        ),
        "ifind_get_financial_statements": csv_response(
            [
                "ths_operating_total_revenue_stock",
                "ths_np_atoopc_stock",
                "ths_currency_fund_stock",
                "ths_st_borrow_stock",
                "ths_ncf_from_oa_stock",
                "ths_cash_paid_for_assets_stock",
            ],
            [["1000.0", "100.0", "500.0", "200.0", "150.0", "50.0"]],
        ),
        "ifind_get_forecast": csv_response(
            ["ths_fore_np_fy1_stock"],
            [["2427375000.0"]],
        ),
    }

    def handle(payload: dict) -> RawResponse:
        calls.append(payload["api_name"])
        return RawResponse(responses[payload["api_name"]])

    return handle


def _kimi_job(invocation_id: str) -> dict:
    job = json.loads(_KIMI_JOB_TEMPLATE.read_text(encoding="utf-8"))
    job["request"]["invocation_id"] = invocation_id
    job["request"]["requested_date"] = "2026-07-10"
    job["request"]["as_of_at"] = (
        datetime.now(timezone.utc) + timedelta(minutes=1)
    ).isoformat()
    return job


def test_kimi_agentgw_live_qualification_uses_production_sync_path(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = FakeAgentGwRuntime(_agentgw_handler(calls))

    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(_kimi_job("qualify-live")), encoding="utf-8")

    assert open_platform_operations(tmp_path / "data").bootstrap()["status"] == "passed"
    with open_provider_qualification(
        tmp_path / "data", job_path, provider_runtime=runtime
    ) as qualification:
        result = qualification.run()
    artifact_path = tmp_path / "qualification.json"
    with open_provider_qualification(
        tmp_path / "data", job_path, provider_runtime=runtime
    ) as replay_qualification:
        replay_result = replay_qualification.run()
    assert replay_result.receipt_artifact_id == result.receipt_artifact_id
    cached_job_path = tmp_path / "cached-job.json"
    cached_job_path.write_text(
        json.dumps(_kimi_job("qualify-cached")),
        encoding="utf-8",
    )
    with open_provider_qualification(
        tmp_path / "data", cached_job_path, provider_runtime=runtime
    ) as cached_qualification:
        cached_result = cached_qualification.run()
    assert cached_result.status == "qualified"

    assert result.status == "qualified"
    assert result.provider_identity == "kimi_agentgw_wind_ifind_non_official"
    assert {item.dataset for item in result.attempts} == {
        "trade_cal",
        "market_universe",
        "daily",
        "income",
        "balancesheet",
        "cashflow",
        "forecast_actual",
    }
    assert all(item.status == "complete" and item.raw_sha256 is not None and len(item.raw_sha256) == 64 for item in result.attempts)
    live_call_kinds = set(calls)
    assert live_call_kinds == {
        "wind_get_index_price",
        "wind_get_stock_info",
        "wind_get_price",
        "ifind_get_financial_statements",
        "ifind_get_forecast",
    }
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
            tmp_path / "data", job_path, provider_runtime=runtime
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
            tmp_path / "data", job_path, provider_runtime=runtime
        ) as replay_qualification:
            replay_qualification.run()
    assert tampered.value.code == "QUALIFICATION_RECEIPT_INTEGRITY_FAILED"


def test_provider_job_v2_rejects_retired_class_selector_contract(tmp_path: Path) -> None:
    job_path = tmp_path / "retired-job.json"
    job_path.write_text(
        json.dumps(
            {
                "provider": {
                    "provider_" + "type": "agentgw_compatible",
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
    def unexpected_call(payload: dict) -> RawResponse:
        raise AssertionError("untrusted jobs must never reach the datasource")

    runtime = FakeAgentGwRuntime(unexpected_call)
    job = json.loads(_KIMI_JOB_TEMPLATE.read_text(encoding="utf-8"))
    job["source_policy"]["source_authority"] = "official"
    job["request"]["invocation_id"] = "spoofed-source-authority"
    job_path = tmp_path / "spoofed-job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    assert open_platform_operations(tmp_path / "data").bootstrap()["status"] == "passed"

    with pytest.raises(Exception) as rejected:
        with open_provider_qualification(
            tmp_path / "data", job_path, provider_runtime=runtime
        ) as qualification:
            qualification.run()

    job["source_policy"]["source_authority"] = "structured_aggregator"
    job["source_policy"]["routes"][0]["retry_max_attempts"] = 5
    job["request"]["invocation_id"] = "caller-selected-source-route"
    route_job_path = tmp_path / "caller-route-job.json"
    route_job_path.write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(Exception) as route_rejected:
        with open_provider_qualification(
            tmp_path / "data", route_job_path, provider_runtime=runtime
        ) as qualification:
            qualification.run()
    assert getattr(route_rejected.value, "code", None) == "PROVIDER_SOURCE_POLICY_UNTRUSTED"
    assert getattr(rejected.value, "code", None) == "PROVIDER_SOURCE_POLICY_UNTRUSTED"
