from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.test_financial_pipeline_bundle_applicability import (
    _request_and_evidence as complete_model_fixture,
)
from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.data.providers import (
    FixtureProvider,
    TushareCompatibleProvider,
)
from trading_platform.domain.data import (
    CompletenessRequirement,
    FetchStatus,
    FallbackMode,
    FixtureRights,
    QueryPolicy,
    ResearchComponentInputQuery,
    SnapshotPurpose,
    SourceAuthority,
    SourceFailureDisposition,
    SourcePolicy,
    SourceRights,
    SourceRoute,
    SyncRequest,
    SyncStatus,
)


SECURITY_ID = "security_complete_model"
SOURCE_IDENTITY = "synthetic-official-component-pipeline"
DATASETS = (
    "trade_cal",
    "market_universe",
    "daily",
    "research_model_input",
    "market_path_policy",
)


def _json_rows(rows: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"rows": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payloads() -> dict[str, bytes]:
    request, evidence = complete_model_fixture()
    model_rows = [
        {
            "component_input_id": member.normalized_version_id,
            "security_id": SECURITY_ID,
            "published_at": member.published_at,
            "available_at": member.available_at,
            "availability_basis": "publisher_timestamp",
            "extracted_fields": list(member.extracted_fields),
        }
        for member in evidence.member_evidence
        if member.dataset == "research_model_input"
    ]
    session = request.effective_session_date
    common = {
        "published_precision": "date",
        "availability_basis": "publisher_timestamp",
    }
    policy_fields = [
        {
            "field_name": name,
            "subject_id": SECURITY_ID,
            "semantic_role": "market_path_constraint",
            "period": session,
            "value": value,
            "unit": unit,
            "currency": "N/A",
            "extraction_method": "confirmed_test_policy",
            "confidence": "high",
        }
        for name, value, unit in (
            ("one_way_transaction_cost_bps", "10", "bps"),
            ("price_limit_fraction", "0.10", "decimal"),
            ("price_tick_size", "0.01", "CNY/share"),
            (
                "market_path_policy_identity",
                "MarketPathPolicy@public-persistence-test",
                "identity",
            ),
        )
    ]
    return {
        "trade_cal": _json_rows(
            [
                {
                    **common,
                    "market": "SZSE",
                    "session_date": session,
                    "is_open": True,
                    "calendar_version": "synthetic-calendar@1",
                    "published_at": session,
                    "available_at": session + "T00:00:00+00:00",
                }
            ]
        ),
        "market_universe": _json_rows(
            [
                {
                    **common,
                    "market_scope_id": "SZSE",
                    "security_id": SECURITY_ID,
                    "listed_from": "2010-01-01",
                    "source_ref": SOURCE_IDENTITY + ":security-master",
                    "published_at": "2010-01-01",
                    "available_at": "2010-01-01T00:00:00+00:00",
                }
            ]
        ),
        "daily": _json_rows(
            [
                {
                    **common,
                    "security_id": SECURITY_ID,
                    "session_date": session,
                    "market_timezone": "Asia/Shanghai",
                    "adjustment_mode": "none",
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10",
                    "volume": "1000",
                    "volume_unit": "hand",
                    "amount": "10000",
                    "amount_unit": "thousand_cny",
                    "currency": "CNY",
                    "adjustment_factor": "1",
                    "suspended": False,
                    "limit_state": "none",
                    "corporate_action_identity": None,
                    "published_at": session,
                    "available_at": session + "T07:00:00+00:00",
                }
            ]
        ),
        "research_model_input": _json_rows(model_rows),
        "market_path_policy": _json_rows(
            [
                {
                    "component_input_id": "confirmed-market-path-policy",
                    "security_id": SECURITY_ID,
                    "published_at": session + "T07:00:00+00:00",
                    "available_at": session + "T07:30:00+00:00",
                    "availability_basis": "publisher_timestamp",
                    "extracted_fields": policy_fields,
                }
            ]
        ),
    }


def _composition() -> tuple[
    FixtureProvider,
    QueryPolicy,
    SourcePolicy,
    dict[tuple[str, str], FixtureRights],
]:
    provider = FixtureProvider(
        "official-component-fixture",
        "fixture@1",
        _payloads(),
        SOURCE_IDENTITY,
        "synthetic-pipeline-test-terms@1",
        SourceAuthority.OFFICIAL,
    )
    policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        SOURCE_IDENTITY,
        SourceAuthority.OFFICIAL,
        "synthetic-pipeline-test-terms@1",
        SourceRights(True, True, True, True, False, "2026-07-30"),
        tuple(
            SourceRoute(
                dataset,
                1,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            )
            for dataset in DATASETS
        ),
    )
    rights = {
        (provider.provider_id, dataset): FixtureRights(
            f"{provider.provider_id}:{dataset}",
            SOURCE_IDENTITY,
            True,
            True,
            True,
            True,
            "synthetic-pipeline-test-terms@1",
            "2026-07-30",
        )
        for dataset in DATASETS
    }
    return provider, QueryPolicy("QueryPolicy@1", 550, "L", "none"), policy, rights


def test_component_inputs_survive_sync_snapshot_workflow_and_restart(
    tmp_path,
) -> None:
    provider, query_policy, source_policy, rights = _composition()
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
        fixture_rights=rights,
    )
    root.watchlist.add(
        "watch:" + SECURITY_ID,
        SecurityIdentity(
            SECURITY_ID,
            "SZSE",
            "000001",
            "CNY",
            "2010-01-01",
        ),
    )
    request, _ = complete_model_fixture()
    synced = root.data.sync(
        SyncRequest(
            "component-input-public-sync",
            SECURITY_ID,
            "000001",
            request.requested_date,
            datetime(
                2025,
                7,
                7,
                9,
                0,
                tzinfo=timezone.utc,
            ),
            "Asia/Shanghai",
            "SZSE",
            SnapshotPurpose.RESEARCH,
            DATASETS,
            False,
            False,
        )
    )
    assert synced.status is SyncStatus.COMPLETE
    assert synced.snapshot_id is not None
    root.close()

    restarted = PlatformTaskFixture(tmp_path)
    frozen = restarted.inspection.snapshot(synced.snapshot_id)
    assert {
        member.dataset for member in frozen.member_evidence
    } >= {"research_model_input", "market_path_policy", "daily", "trade_cal"}
    daily_field = next(
        field
        for member in frozen.member_evidence
        if member.dataset == "daily"
        for field in member.extracted_fields
        if field["field_name"] == "current_price"
    )
    assert daily_field["adjustment_factor"] == "1"
    assert daily_field["suspended"] is False
    assert daily_field["limit_state"] == "none"
    assert any(
        field["field_name"] == "trading_session"
        for member in frozen.member_evidence
        if member.dataset == "trade_cal"
        for field in member.extracted_fields
    )

    workflow_request = replace(
        request,
        invocation_id="component-input-workflow-after-restart",
        data_snapshot_id=synced.snapshot_id,
    )
    result = restarted.research.handle(
        StartResearchWorkflow(workflow_request)
    )
    view = json.loads(
        restarted.archive.decision_view(result.workflow_run_id).json_bytes
    )
    components = view["audit"]["evaluation_bundle"]["components"]
    assert components["forecast"]["status"] == "complete"
    assert components["scenario_valuation"]["status"] in {
        "complete",
        "limited",
    }
    assert components["valuation_simulation_decision"]["status"] in {
        "complete",
        "limited",
    }
    restarted.close()


def test_tushare_gateway_rejects_local_component_inputs_before_transport() -> None:
    calls: list[object] = []
    provider = TushareCompatibleProvider(
        "gateway",
        "tushare-http@2",
        "http://127.0.0.1:9/",
        "redacted-test-secret",
        "compatible-gateway-not-official",
        "gateway-terms-pending@1",
        lambda request: calls.append(request),
    )
    result = provider.fetch(
        ResearchComponentInputQuery(
            "component-input-gateway-boundary",
            SECURITY_ID,
            "2025-07-07",
            "research_model_input",
            None,
            SECURITY_ID,
            True,
        )
    ).envelopes[0]
    assert calls == []
    assert result.status is FetchStatus.FAILED
    assert result.error_code == "TUSHARE_QUERY_UNSUPPORTED"
