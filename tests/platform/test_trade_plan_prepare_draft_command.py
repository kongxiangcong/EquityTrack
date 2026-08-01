from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.test_research_workflow import _request
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
)
from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.data.providers import (
    TransportResponse,
    TushareCompatibleProvider,
)
from trading_platform.domain.data import (
    CompletenessRequirement,
    FallbackMode,
    QueryPolicy,
    SnapshotPurpose,
    SourceAuthority,
    SourceFailureDisposition,
    SourcePolicy,
    SourceRights,
    SourceRoute,
    SyncRequest,
    SyncStatus,
)


def _encoded(
    *,
    invocation_id: str,
    payload: dict[str, object],
    actor_type: str = "agent",
    interaction_channel: str = "skill",
    transport_actor_type: str = "agent",
    command_name: str = "trade_plan.prepare_draft@1",
    payload_schema_version: str = "PrepareTradePlanDraft@1",
    expected_revision: int | None = None,
) -> bytes:
    return json.dumps(
        {
            "schema_version": "ApplicationCommandEnvelope@1",
            "command_name": command_name,
            "invocation_id": invocation_id,
            "payload_schema_version": payload_schema_version,
            "expected_revision": expected_revision,
            "decision_actor": {
                "actor_type": actor_type,
                "actor_id": ("local-user" if actor_type == "user" else "codex"),
            },
            "interaction_channel": interaction_channel,
            "transport_actor": {
                "actor_type": transport_actor_type,
                "actor_id": (
                    "workflow" if transport_actor_type == "system" else "codex"
                ),
            },
            "approval": None,
            "payload": payload,
        },
        sort_keys=True,
    ).encode()


def _trading_sessions() -> tuple[str, ...]:
    cursor = date(2026, 7, 10)
    sessions: list[date] = []
    while len(sessions) < 60:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    return tuple(item.strftime("%Y%m%d") for item in reversed(sessions))


def _market_runtime() -> tuple[
    TushareCompatibleProvider,
    QueryPolicy,
    SourcePolicy,
]:
    sessions = _trading_sessions()
    responses = {
        "trade_cal": {
            "code": 0,
            "data": {
                "fields": ["exchange", "cal_date", "is_open"],
                "items": [
                    ["SZSE", "20260711", 0],
                    ["SZSE", "20260710", 1],
                ],
            },
        },
        "stock_basic": {
            "code": 0,
            "data": {
                "fields": ["ts_code", "name", "list_date"],
                "items": [["002897.SZ", "意华股份", "20170907"]],
            },
        },
        "daily": {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ],
                "items": [
                    [
                        "002897.SZ",
                        session,
                        str(index),
                        str(index + 1),
                        str(index - 1),
                        str(index),
                        "100000",
                        str(index * 100000),
                    ]
                    for index, session in enumerate(sessions, start=20)
                ],
            },
        },
    }

    def transport(request) -> TransportResponse:
        body = json.loads(request.data.decode("utf-8"))
        return TransportResponse(
            json.dumps(responses[body["api_name"]]).encode(),
            {},
        )

    provider = TushareCompatibleProvider(
        "authoring-fixture-gateway",
        "tushare-http@2",
        "http://127.0.0.1:9/",
        "redacted-fixture-token",
        "preconfigured_tushare_compatible_non_official",
        "gateway-terms-pending@1",
        transport,
        SourceAuthority.STRUCTURED_AGGREGATOR,
    )
    datasets = ("trade_cal", "market_universe", "daily")
    policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        "preconfigured_tushare_compatible_non_official",
        SourceAuthority.STRUCTURED_AGGREGATOR,
        "gateway-terms-pending@1",
        SourceRights(True, True, True, True, False, "2026-07-01"),
        tuple(
            SourceRoute(
                dataset,
                1,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            )
            for dataset in datasets
        ),
    )
    return provider, QueryPolicy("QueryPolicy@1", 180, "L", "none"), policy


def _register_confirmed_authorities(
    root: PlatformTaskFixture,
) -> str:
    registered = root.application_commands.dispatch(
        ApplicationCommandEnvelopeV1.from_bytes(
            _encoded(
                command_name="account_snapshot.register_account@2",
                payload_schema_version="RegisterAccountForSnapshots@2",
                invocation_id="authoring:account:register",
                actor_type="user",
                payload={
                    "account_id": "account_authoring",
                    "alias": "authoring",
                    "base_currency": "CNY",
                    "source_kind": ("user_declared_from_broker_screenshot"),
                    "redacted_source_ref": ("local-screenshot:authoring-fixture"),
                    "registered_at": "2026-07-11T16:00:00+08:00",
                    "securities": [
                        {
                            "market": "SZSE",
                            "code": "002897",
                            "security_id": "security_yihua",
                            "currency": "CNY",
                            "observed_on": "2026-07-10",
                        }
                    ],
                },
            )
        )
    )
    assert isinstance(registered, ApplicationCommandResult)
    assert registered.result["securities"][0]["security_id"] == ("security_yihua")
    created = root.application_commands.dispatch(
        ApplicationCommandEnvelopeV1.from_bytes(
            _encoded(
                command_name="account_snapshot.create_draft@1",
                payload_schema_version="CreateAccountSnapshotDraft@1",
                invocation_id="authoring:account:draft",
                payload={
                    "draft": {
                        "draft_id": "account_snapshot_draft_authoring",
                        "account_id": "account_authoring",
                        "revision": 1,
                        "status": "open",
                        "source_kind": ("user_declared_from_broker_screenshot"),
                        "redacted_source_ref": ("local-screenshot:authoring-fixture"),
                        "as_of_at": "2026-07-10T15:30:00+08:00",
                        "as_of_precision": "instant",
                        "timezone": "Asia/Shanghai",
                        "session_semantics": "complete_session",
                        "currency": "CNY",
                        "cash_state": "known",
                        "cash_value": "50000",
                        "nav_state": "known",
                        "nav_value": "129000",
                        "fees_state": "unknown",
                        "fees_value": None,
                        "positions": [
                            {
                                "security_id": "security_yihua",
                                "total_quantity": "1000",
                                "available_quantity_state": "known",
                                "available_quantity_value": "1000",
                                "cost_state": "known",
                                "cost_value": "50",
                                "market_value_state": "known",
                                "market_value_value": "79000",
                            }
                        ],
                        "created_by": "agent:codex",
                    }
                },
            )
        )
    )
    assert isinstance(created, ApplicationCommandResult)
    confirmed = root.application_commands.dispatch(
        ApplicationCommandEnvelopeV1.from_bytes(
            _encoded(
                command_name="account_snapshot.confirm@1",
                payload_schema_version="ConfirmAccountSnapshot@1",
                invocation_id="authoring:account:confirm",
                actor_type="user",
                expected_revision=1,
                payload={"draft_id": "account_snapshot_draft_authoring"},
            )
        )
    )
    assert isinstance(confirmed, ApplicationCommandResult)
    policy = root.application_commands.dispatch(
        ApplicationCommandEnvelopeV1.from_bytes(
            _encoded(
                command_name="portfolio_risk_policy.confirm@1",
                payload_schema_version="ConfirmPortfolioRiskPolicy@1",
                invocation_id="authoring:risk:confirm",
                actor_type="user",
                payload={
                    "account_id": "account_authoring",
                    "currency": "CNY",
                    "limits": {
                        "single_security_exposure": "0.90",
                        "industry_exposure": "0.90",
                        "gross_exposure": "0.95",
                        "minimum_cash": "0.05",
                        "single_plan_loss": "0.02",
                        "aggregate_active_plan_loss": "0.05",
                        "drawdown_review": "0.10",
                        "drawdown_freeze": "0.15",
                        "plan_daily_liquidity": "0.05",
                        "position_daily_liquidity": "0.10",
                    },
                },
            )
        )
    )
    assert isinstance(policy, ApplicationCommandResult)
    assert policy.result["account_id"] == confirmed.result["account_id"]
    return str(confirmed.result["account_id"])


def _author_payload(
    *,
    account_ref: str,
    security_ref: str,
    requested_at: str,
) -> dict[str, object]:
    return {
        "account_ref": account_ref,
        "security_ref": security_ref,
        "plan_style": "existing_position_review",
        "requested_at": requested_at,
    }


def test_envelope_authors_one_open_draft_from_persisted_research(
    tmp_path: Path,
) -> None:
    provider, query_policy, source_policy = _market_runtime()
    root = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
    )
    try:
        root.watchlist.add(
            "authoring:watchlist",
            SecurityIdentity(
                "security_yihua",
                "SZSE",
                "002897",
                "CNY",
                "2017-09-07",
            ),
        )
        assert root.data is not None
        snapshot = root.data.sync(
            SyncRequest(
                "authoring:market:sync",
                "security_yihua",
                "002897",
                "2026-07-11",
                datetime(2026, 7, 11, tzinfo=timezone.utc),
                "Asia/Shanghai",
                "SZSE",
                SnapshotPurpose.RESEARCH,
                ("trade_cal", "market_universe", "daily"),
                True,
                False,
            )
        )
        assert snapshot.status is SyncStatus.COMPLETE
        assert snapshot.snapshot_id is not None
        research = root.research.handle(
            StartResearchWorkflow(
                _request(
                    "authoring:research",
                    snapshot_id=snapshot.snapshot_id,
                )
            )
        )
        assert research.recent_trend_assessment_id is not None
        trend = root.archive.get(research.recent_trend_assessment_id)
        assert trend.status == "complete"
        assert trend.as_of_session == "2026-07-10"
        account_id = _register_confirmed_authorities(root)
        created_at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        payload = _author_payload(
            account_ref="authoring",
            security_ref="002897.SZ",
            requested_at=created_at,
        )
        assert set(payload) == {
            "account_ref",
            "security_ref",
            "plan_style",
            "requested_at",
        }
        encoded = _encoded(
            invocation_id="authoring:plan:draft",
            payload=payload,
        )

        first = root.application_commands.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(encoded)
        )
        replay = root.application_commands.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(encoded)
        )

        assert isinstance(first, ApplicationCommandResult)
        assert replay == first
        assert first.result_type == "TradePlanDraft"
        assert first.result["status"] == "open"
        assert first.result["revision"] == 1
        assert first.result["decision_actor"] == "agent:codex"
        assert first.result["content"]["research_workflow_run_id"] == (
            research.workflow_run_id
        )
        assert first.result["content"]["recent_trend_assessment_id"] == (
            trend.assessment_id
        )
        assert first.result["proposed_graph"]["schema_version"] == (
            "TradePlanDraftGraph@1"
        )

        conflicting = json.loads(json.dumps(payload))
        conflicting["requested_at"] = (
            datetime.fromisoformat(created_at) + timedelta(seconds=1)
        ).isoformat()
        conflict = root.application_commands.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    invocation_id="authoring:plan:draft",
                    payload=conflicting,
                )
            )
        )
        assert isinstance(conflict, ApplicationCommandFailure)
        assert conflict.code == "INVOCATION_CONFLICT"
    finally:
        root.close()


def test_authoring_authorization_and_payload_shape_fail_closed(
    tmp_path: Path,
) -> None:
    root = PlatformTaskFixture(tmp_path)
    try:
        payload = _author_payload(
            account_ref="account_missing",
            security_ref="security_missing",
            requested_at="2026-07-30T16:00:00+08:00",
        )
        system_denied = root.application_commands.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    invocation_id="authoring:system:denied",
                    payload=payload,
                    actor_type="system",
                    interaction_channel="workflow",
                    transport_actor_type="system",
                )
            )
        )
        assert isinstance(system_denied, ApplicationCommandFailure)
        assert system_denied.code == "SYSTEM_DECISION_CAPABILITY_DENIED"

        supplied_graph = {
            **payload,
            "proposed_graph": {"schema_version": "TradePlanDraftGraph@1"},
        }
        graph_denied = root.application_commands.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    invocation_id="authoring:graph:denied",
                    payload=supplied_graph,
                )
            )
        )
        assert isinstance(graph_denied, ApplicationCommandFailure)
        assert graph_denied.code == ("PLAN_DRAFT_COMMAND_FIELDS_INVALID")
    finally:
        root.close()
