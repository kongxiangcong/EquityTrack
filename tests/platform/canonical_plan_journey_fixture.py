from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
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
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    EvaluationHorizon,
    EvaluationPurpose,
    ResearchEvaluationPlan,
    ResearchWorkflowRequest,
    StrategyValidationSelection,
)


ACCOUNT_ID = "account_authoring"
SECURITY_ID = "security_yihua"
SECURITY_CODE = "002897"


@dataclass(frozen=True)
class ConfirmedPlanAuthorities:
    account_id: str
    account_snapshot_version_id: str
    risk_policy_version_id: str


@dataclass
class CanonicalPlanJourneyFixture:
    platform: PlatformTaskFixture
    account_id: str
    security_id: str
    account_snapshot_version_id: str
    risk_policy_version_id: str
    data_snapshot_id: str
    workflow_run_id: str
    recent_trend_assessment_id: str
    draft_id: str
    draft_revision: int
    plan_id: str
    plan_version_id: str
    challenge_id: str | None
    activation_id: str | None
    review_requested_at: str
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def data_root(self) -> Path:
        return self.platform.data_root

    def close(self) -> None:
        if not self._closed:
            self.platform.close()
            self._closed = True

    def __enter__(self) -> "CanonicalPlanJourneyFixture":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.close()


def application_envelope_bytes(
    *,
    invocation_id: str,
    payload: Mapping[str, object],
    actor_type: str = "agent",
    interaction_channel: str = "skill",
    transport_actor_type: str = "agent",
    command_name: str = "trade_plan.prepare_draft@1",
    payload_schema_version: str = "PrepareTradePlanDraft@1",
    expected_revision: int | None = None,
    approval_challenge_id: str | None = None,
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
                "actor_id": (
                    "local-user" if actor_type == "user" else "codex"
                ),
            },
            "interaction_channel": interaction_channel,
            "transport_actor": {
                "actor_type": transport_actor_type,
                "actor_id": (
                    "workflow"
                    if transport_actor_type == "system"
                    else "codex"
                ),
            },
            "approval": (
                {"challenge_id": approval_challenge_id}
                if approval_challenge_id is not None
                else None
            ),
            "payload": dict(payload),
        },
        sort_keys=True,
    ).encode()


def fixture_market_runtime() -> tuple[
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
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        "preconfigured_tushare_compatible_non_official",
        SourceAuthority.STRUCTURED_AGGREGATOR,
        "gateway-terms-pending@1",
        SourceRights(
            True,
            True,
            True,
            True,
            False,
            "2026-07-01",
        ),
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
    return (
        provider,
        QueryPolicy("QueryPolicy@1", 180, "L", "none"),
        source_policy,
    )


def register_confirmed_plan_authorities(
    platform: PlatformTaskFixture,
) -> ConfirmedPlanAuthorities:
    registered = _dispatch_result(
        platform,
        application_envelope_bytes(
            command_name="account_snapshot.register_account@2",
            payload_schema_version="RegisterAccountForSnapshots@2",
            invocation_id="authoring:account:register",
            actor_type="user",
            payload={
                "account_id": ACCOUNT_ID,
                "alias": "authoring",
                "base_currency": "CNY",
                "source_kind": (
                    "user_declared_from_broker_screenshot"
                ),
                "redacted_source_ref": (
                    "local-screenshot:authoring-fixture"
                ),
                "registered_at": "2026-07-11T16:00:00+08:00",
                "securities": [
                    {
                        "market": "SZSE",
                        "code": SECURITY_CODE,
                        "security_id": SECURITY_ID,
                        "currency": "CNY",
                        "observed_on": "2026-07-09",
                    }
                ],
            },
        ),
    )
    if (
        registered.result["securities"][0]["security_id"]
        != SECURITY_ID
    ):
        raise AssertionError("Canonical security identity was not registered")

    draft_id = "account_snapshot_draft_authoring"
    _dispatch_result(
        platform,
        application_envelope_bytes(
            command_name="account_snapshot.create_draft@1",
            payload_schema_version="CreateAccountSnapshotDraft@1",
            invocation_id="authoring:account:draft",
            payload={
                "draft": {
                    "draft_id": draft_id,
                    "account_id": ACCOUNT_ID,
                    "revision": 1,
                    "status": "open",
                    "source_kind": (
                        "user_declared_from_broker_screenshot"
                    ),
                    "redacted_source_ref": (
                        "local-screenshot:authoring-fixture"
                    ),
                    "as_of_at": "2026-07-09T15:30:00+08:00",
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
                            "security_id": SECURITY_ID,
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
        ),
    )
    confirmed = _dispatch_result(
        platform,
        application_envelope_bytes(
            command_name="account_snapshot.confirm@1",
            payload_schema_version="ConfirmAccountSnapshot@1",
            invocation_id="authoring:account:confirm",
            actor_type="user",
            expected_revision=1,
            payload={"draft_id": draft_id},
        ),
    )
    risk_policy = _dispatch_result(
        platform,
        application_envelope_bytes(
            command_name="portfolio_risk_policy.confirm@1",
            payload_schema_version="ConfirmPortfolioRiskPolicy@1",
            invocation_id="authoring:risk:confirm",
            actor_type="user",
            payload={
                "account_id": ACCOUNT_ID,
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
        ),
    )
    if risk_policy.result["account_id"] != confirmed.result["account_id"]:
        raise AssertionError("Risk policy and account snapshot owners differ")
    return ConfirmedPlanAuthorities(
        account_id=str(confirmed.result["account_id"]),
        account_snapshot_version_id=str(
            confirmed.result["account_snapshot_version_id"]
        ),
        risk_policy_version_id=str(
            risk_policy.result["portfolio_risk_policy_version_id"]
        ),
    )


def author_draft_payload(
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


def canonical_research_request(
    *,
    invocation_id: str,
    snapshot_id: str,
    requested_date: str = "2026-07-11",
    effective_session_date: str = "2026-07-10",
) -> ResearchWorkflowRequest:
    return ResearchWorkflowRequest(
        "ResearchWorkflowRequest@2",
        invocation_id,
        SECURITY_ID,
        requested_date,
        effective_session_date,
        snapshot_id,
        ResearchEvaluationPlan(
            "ResearchEvaluationPlan@1",
            EvaluationPurpose.COMPANY_OUTLOOK,
            EvaluationHorizon(
                requested_date,
                "2028-12-31",
                "2026-10-31",
            ),
            (
                EvaluationDimension.SOURCE_QUALITY,
                EvaluationDimension.FORECAST,
                EvaluationDimension.VALUATION,
            ),
            StrategyValidationSelection.NOT_REQUESTED,
        ),
    )


def arrange_canonical_plan_journey(
    data_root: Path,
    *,
    activate: bool = True,
) -> CanonicalPlanJourneyFixture:
    requested_root = data_root.resolve()
    if (requested_root / "platform.sqlite3").exists():
        raise AssertionError(
            "CANONICAL_PLAN_JOURNEY_REQUIRES_FRESH_DATA_ROOT"
        )
    provider, query_policy, source_policy = fixture_market_runtime()
    platform = PlatformTaskFixture(
        requested_root,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
    )
    try:
        platform.watchlist.add(
            "authoring:watchlist",
            SecurityIdentity(
                SECURITY_ID,
                "SZSE",
                SECURITY_CODE,
                "CNY",
                "2017-09-07",
            ),
        )
        if platform.data is None:
            raise AssertionError("Canonical market fixture is unavailable")
        snapshot = platform.data.sync(
            SyncRequest(
                "authoring:market:sync",
                SECURITY_ID,
                SECURITY_CODE,
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
        if (
            snapshot.status is not SyncStatus.COMPLETE
            or snapshot.snapshot_id is None
        ):
            raise AssertionError("Canonical market snapshot did not complete")
        research = platform.research.handle(
            StartResearchWorkflow(
                canonical_research_request(
                    invocation_id="authoring:research",
                    snapshot_id=snapshot.snapshot_id,
                )
            )
        )
        if research.recent_trend_assessment_id is None:
            raise AssertionError("Research did not persist recent trend")
        trend = platform.archive.get(
            research.recent_trend_assessment_id
        )
        if trend.status != "complete":
            raise AssertionError("Recent trend assessment is not complete")
        authorities = register_confirmed_plan_authorities(platform)

        base_time = datetime.now(timezone.utc) + timedelta(minutes=1)
        authored = _dispatch_result(
            platform,
            application_envelope_bytes(
                invocation_id="authoring:plan:draft",
                payload=author_draft_payload(
                    account_ref="authoring",
                    security_ref=SECURITY_CODE,
                    requested_at=base_time.isoformat(),
                ),
            ),
        )
        if (
            authored.result_type != "TradePlanDraft"
            or authored.result["status"] != "open"
        ):
            raise AssertionError("Public author command did not return OPEN draft")
        draft_id = str(authored.result["draft_id"])
        draft_revision = int(authored.result["revision"])
        graph = _mapping(authored.result["proposed_graph"])
        version = _mapping(graph["version"])
        plan_id = str(version["plan_id"])
        plan_version_id = str(version["plan_version_id"])

        challenge_id: str | None = None
        activation_id: str | None = None
        if activate:
            challenge = _dispatch_result(
                platform,
                application_envelope_bytes(
                    command_name=(
                        "trade_plan.issue_confirmation_challenge@1"
                    ),
                    payload_schema_version=(
                        "IssuePlanConfirmationChallenge@1"
                    ),
                    invocation_id="authoring:plan:challenge",
                    actor_type="user",
                    expected_revision=draft_revision,
                    payload={
                        "draft_id": draft_id,
                        "activation_intent": "confirm_and_activate",
                        "issued_at": (
                            base_time + timedelta(minutes=1)
                        ).isoformat(),
                        "expires_at": (
                            base_time + timedelta(hours=1)
                        ).isoformat(),
                    },
                ),
            )
            challenge_id = str(challenge.result["challenge_id"])
            canonical_diff = _mapping(
                challenge.result["canonical_diff"]
            )
            confirmed = _dispatch_result(
                platform,
                application_envelope_bytes(
                    command_name="trade_plan.confirm@1",
                    payload_schema_version="ConfirmTradePlanDraft@1",
                    invocation_id="authoring:plan:confirm",
                    actor_type="user",
                    expected_revision=int(
                        challenge.result["expected_revision"]
                    ),
                    approval_challenge_id=challenge_id,
                    payload={
                        "expected_draft_hash": str(
                            challenge.result["expected_draft_hash"]
                        ),
                        "expected_diff_hash": str(
                            canonical_diff["content_hash"]
                        ),
                        "activation_intent": "confirm_and_activate",
                        "approved_at": (
                            base_time + timedelta(minutes=2)
                        ).isoformat(),
                    },
                ),
            )
            if confirmed.result_type != "PlanConfirmationResult":
                raise AssertionError(
                    "Public confirmation did not return plan result"
                )
            active = _mapping(confirmed.result["active_plan"])
            activation = _mapping(active["activation"])
            confirmed_graph = _mapping(confirmed.result["graph"])
            confirmed_version = _mapping(confirmed_graph["version"])
            if (
                str(confirmed_version["plan_id"]) != plan_id
                or str(confirmed_version["plan_version_id"])
                != plan_version_id
            ):
                raise AssertionError(
                    "Confirmed plan identity differs from authored draft"
                )
            activation_id = str(activation["activation_id"])

        return CanonicalPlanJourneyFixture(
            platform=platform,
            account_id=authorities.account_id,
            security_id=SECURITY_ID,
            account_snapshot_version_id=(
                authorities.account_snapshot_version_id
            ),
            risk_policy_version_id=authorities.risk_policy_version_id,
            data_snapshot_id=snapshot.snapshot_id,
            workflow_run_id=research.workflow_run_id,
            recent_trend_assessment_id=trend.assessment_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            challenge_id=challenge_id,
            activation_id=activation_id,
            review_requested_at=(
                base_time + timedelta(minutes=3)
            ).isoformat(),
        )
    except Exception:
        platform.close()
        raise


def _dispatch_result(
    platform: PlatformTaskFixture,
    encoded: bytes,
) -> ApplicationCommandResult:
    envelope = ApplicationCommandEnvelopeV1.from_bytes(encoded)
    result = platform.application_commands.dispatch(envelope)
    if not isinstance(result, ApplicationCommandResult):
        raise AssertionError(
            f"{envelope.command_name} failed: {result.code}"
        )
    return result


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError("Canonical journey expected an object result")
    return value


def _trading_sessions() -> tuple[str, ...]:
    cursor = date(2026, 7, 10)
    sessions: list[date] = []
    while len(sessions) < 60:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    return tuple(item.strftime("%Y%m%d") for item in reversed(sessions))


__all__ = [
    "CanonicalPlanJourneyFixture",
    "ConfirmedPlanAuthorities",
    "application_envelope_bytes",
    "arrange_canonical_plan_journey",
    "author_draft_payload",
    "canonical_research_request",
    "fixture_market_runtime",
    "register_confirmed_plan_authorities",
]
