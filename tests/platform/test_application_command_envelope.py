from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from tests.platform.test_account_snapshots import _draft, _ready_root
from tests.platform.test_plan_confirmation import (
    _authority_root,
    _draft as _plan_draft,
)
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
    open_application_commands,
    open_platform_operations,
)
from trading_platform.application.command_envelope import COMMAND_REGISTRY


def _encoded(
    *,
    command_name: str = "account_snapshot.create_draft@1",
    payload_schema_version: str = "CreateAccountSnapshotDraft@1",
    invocation_id: str = "envelope:create:1",
    actor_type: str = "agent",
    expected_revision: int | None = None,
    payload: dict[str, object] | None = None,
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
                "actor_id": "local-user" if actor_type == "user" else "codex",
            },
            "interaction_channel": "skill",
            "transport_actor": {
                "actor_type": "agent",
                "actor_id": "codex",
            },
            "approval": None,
            "payload": payload or {"draft": asdict(_draft())},
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode()


def _graph_payload(graph) -> dict[str, object]:
    version = graph.version
    return {
        "schema_version": graph.schema_version,
        "version": {
            "plan_version_id": version.plan_version_id,
            "plan_id": version.plan_id,
            "version_no": version.version_no,
            "supersedes_version_id": version.supersedes_version_id,
            "strategy_version_id": version.strategy_version_id,
            "investment_thesis_version_id": version.investment_thesis_version_id,
            "account_snapshot_version_id": version.account_snapshot_version_id,
            "data_snapshot_id": version.data_snapshot_id,
            "horizon_start": version.horizon_start,
            "horizon_end": version.horizon_end,
            "review_by": version.review_by,
            "risk_policy_version_id": version.risk_policy_version_id,
            "metric_catalog_version": version.metric_catalog_version,
            "evaluator_policy_version": version.evaluator_policy_version,
            "conflict_policy_version": version.conflict_policy_version,
            "ast_version": version.ast_version,
            "content": version.content,
            "content_hash": version.content_hash,
            "graph_seal_hash": version.graph_seal_hash,
            "confirmed_at": version.confirmed_at,
            "user_approval_receipt_id": version.user_approval_receipt_id,
        },
        "sleeves": [
            {**sleeve.canonical_content, "grid_constraint": None}
            for sleeve in graph.sleeves
        ],
        "rules": [],
        "evidence_references": list(graph.evidence_references),
        "adjusted_price_evidence": list(graph.adjusted_price_evidence),
    }


def test_skill_cli_and_web_codecs_share_request_hash_and_result_schema(
    tmp_path: Path,
) -> None:
    encoded = _encoded()
    decoded = tuple(
        ApplicationCommandEnvelopeV1.from_bytes(encoded)
        for _channel_adapter in ("skill", "cli", "web")
    )

    data_root = _ready_root(tmp_path)
    with open_application_commands(data_root) as dispatcher:
        first = dispatcher.dispatch(decoded[0])
        replay = dispatcher.dispatch(decoded[1])

    assert isinstance(first, ApplicationCommandResult)
    assert isinstance(replay, ApplicationCommandResult)
    assert first.schema_version == replay.schema_version == "ApplicationCommandResult@1"
    assert first.request_hash == replay.request_hash
    assert first.revision_or_version_id == replay.revision_or_version_id
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    stored_hash = connection.execute(
        "SELECT request_hash FROM application_command_receipt " "WHERE invocation_id=?",
        (first.invocation_id,),
    ).fetchone()[0]
    connection.close()
    assert stored_hash == first.request_hash


def test_actor_channel_transport_are_distinct_and_agent_confirmation_is_denied(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    with open_application_commands(data_root) as dispatcher:
        created = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(_encoded())
        )
        assert isinstance(created, ApplicationCommandResult)
        denied = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.confirm@1",
                    payload_schema_version="ConfirmAccountSnapshot@1",
                    invocation_id="envelope:confirm:denied",
                    expected_revision=1,
                    payload={"draft_id": "draft_local_1"},
                )
            )
        )

    assert isinstance(denied, ApplicationCommandFailure)
    assert denied.code == "USER_DECISION_CAPABILITY_REQUIRED"
    assert denied.request_hash


def test_user_registers_screenshot_account_identity_before_creating_draft(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    assert open_platform_operations(data_root).bootstrap()["status"] == "passed"
    registration_payload = {
        "account_id": "account_kong",
        "alias": "kong",
        "base_currency": "CNY",
        "source_kind": "user_declared_from_broker_screenshot",
        "redacted_source_ref": "local-screenshot:portfolio-20260728",
        "registered_at": "2026-07-28T22:37:00+08:00",
        "securities": [
            {
                "market": "SZSE",
                "code": code,
                "currency": "CNY",
                "observed_on": "2026-07-28",
            }
            for code in ("002407", "002155", "002241", "002897")
        ],
    }
    with open_application_commands(data_root) as dispatcher:
        registered = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.register_account@2",
                    payload_schema_version="RegisterAccountForSnapshots@2",
                    invocation_id="envelope:account:register",
                    actor_type="user",
                    payload=registration_payload,
                )
            )
        )
        assert isinstance(registered, ApplicationCommandResult)
        assert registered.result_type == "AccountRegistration"
        replayed = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.register_account@2",
                    payload_schema_version="RegisterAccountForSnapshots@2",
                    invocation_id="envelope:account:register",
                    actor_type="user",
                    payload=registration_payload,
                )
            )
        )
        assert replayed == registered
        identities = {
            item["code"]: item["security_id"]
            for item in registered.result["securities"]
        }
        assert set(identities) == {"002407", "002155", "002241", "002897"}
        second_payload = {
            **registration_payload,
            "account_id": "account_second",
            "alias": "second",
            "registered_at": "2026-07-29T22:37:00+08:00",
            "securities": [
                {**identity, "observed_on": "2026-07-29"}
                for identity in registration_payload["securities"]
            ],
        }
        second = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.register_account@2",
                    payload_schema_version="RegisterAccountForSnapshots@2",
                    invocation_id="envelope:account:register:second",
                    actor_type="user",
                    payload=second_payload,
                )
            )
        )
        assert isinstance(second, ApplicationCommandResult)
        assert {
            item["code"]: item["security_id"] for item in second.result["securities"]
        } == identities

        draft = {
            "draft_id": "draft_kong_20260728",
            "account_id": registered.result["account_id"],
            "revision": 1,
            "status": "open",
            "source_kind": "user_declared_from_broker_screenshot",
            "redacted_source_ref": "local-screenshot:portfolio-20260728",
            "as_of_at": "2026-07-28",
            "as_of_precision": "date",
            "timezone": "Asia/Shanghai",
            "session_semantics": "complete_session",
            "currency": "CNY",
            "cash_state": "known",
            "cash_value": "102.10",
            "nav_state": "known",
            "nav_value": "105442.10",
            "fees_state": "unknown",
            "fees_value": None,
            "positions": [
                {
                    "security_id": identities[code],
                    "total_quantity": quantity,
                    "available_quantity_state": "known",
                    "available_quantity_value": quantity,
                    "cost_state": "known",
                    "cost_value": cost,
                    "market_value_state": "known",
                    "market_value_value": market_value,
                }
                for code, quantity, cost, market_value in (
                    ("002407", "1000", "30.628", "34200.00"),
                    ("002155", "1000", "22.133", "22310.00"),
                    ("002241", "900", "22.403", "20565.00"),
                    ("002897", "500", "96.601", "28265.00"),
                )
            ],
            "created_by": "agent:codex",
        }
        created = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    invocation_id="envelope:kong:draft:create",
                    payload={"draft": draft},
                )
            )
        )
        confirmed = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.confirm@1",
                    payload_schema_version="ConfirmAccountSnapshot@1",
                    invocation_id="envelope:kong:draft:confirm",
                    actor_type="user",
                    expected_revision=1,
                    payload={"draft_id": "draft_kong_20260728"},
                )
            )
        )

    assert isinstance(created, ApplicationCommandResult)
    assert created.result["validation_state"] == "valid"
    assert created.result["account_id"] == "account_kong"
    assert isinstance(confirmed, ApplicationCommandResult)
    assert confirmed.result_type == "AccountSnapshotVersion"
    assert confirmed.result["confirmed_by"] == "user:local-user"
    assert confirmed.result["source_draft_id"] == "draft_kong_20260728"


def test_agent_cannot_register_user_declared_account_identity(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    assert open_platform_operations(data_root).bootstrap()["status"] == "passed"
    with open_application_commands(data_root) as dispatcher:
        denied = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.register_account@2",
                    payload_schema_version="RegisterAccountForSnapshots@2",
                    invocation_id="envelope:account:register:denied",
                    payload={
                        "account_id": "account_kong",
                        "alias": "kong",
                        "base_currency": "CNY",
                        "source_kind": "user_declared_from_broker_screenshot",
                        "redacted_source_ref": "local-screenshot:portfolio-20260728",
                        "registered_at": "2026-07-28T22:37:00+08:00",
                        "securities": [],
                    },
                )
            )
        )

    assert isinstance(denied, ApplicationCommandFailure)
    assert denied.code == "USER_DECISION_CAPABILITY_REQUIRED"


def test_account_registration_fails_closed_on_future_security_identity(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    assert open_platform_operations(data_root).bootstrap()["status"] == "passed"

    def registration(
        account_id: str, alias: str, observed_on: str
    ) -> dict[str, object]:
        return {
            "account_id": account_id,
            "alias": alias,
            "base_currency": "CNY",
            "source_kind": "user_declared_from_broker_screenshot",
            "redacted_source_ref": f"local-screenshot:{alias}",
            "registered_at": f"{observed_on}T22:37:00+08:00",
            "securities": [
                {
                    "market": "SZSE",
                    "code": "002407",
                    "currency": "CNY",
                    "observed_on": observed_on,
                }
            ],
        }

    with open_application_commands(data_root) as dispatcher:
        future = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.register_account@2",
                    payload_schema_version="RegisterAccountForSnapshots@2",
                    invocation_id="envelope:account:future",
                    actor_type="user",
                    payload=registration("account_future", "future", "2026-07-29"),
                )
            )
        )
        conflict = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="account_snapshot.register_account@2",
                    payload_schema_version="RegisterAccountForSnapshots@2",
                    invocation_id="envelope:account:earlier",
                    actor_type="user",
                    payload=registration("account_earlier", "earlier", "2026-07-28"),
                )
            )
        )

    assert isinstance(future, ApplicationCommandResult)
    assert isinstance(conflict, ApplicationCommandFailure)
    assert conflict.code == "SECURITY_IDENTIFIER_TEMPORAL_CONFLICT"


def test_plan_create_challenge_and_confirmation_use_the_same_dispatcher(
    tmp_path: Path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    draft = _plan_draft(snapshot_id, suffix="envelope")
    create_payload = {
        "draft": {
            "draft_id": draft.draft_id,
            "account_id": draft.account_id,
            "security_id": draft.security_id,
            "parameters": dict(draft.parameters),
            "created_at": draft.created_at,
            "proposed_graph": _graph_payload(draft.proposed_graph),
        }
    }
    with open_application_commands(data_root) as dispatcher:
        created = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name="trade_plan.create_draft@1",
                    payload_schema_version="CreateTradePlanDraft@1",
                    invocation_id="envelope:plan:create",
                    payload=create_payload,
                )
            )
        )
        assert isinstance(created, ApplicationCommandResult)
        challenge = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                _encoded(
                    command_name=("trade_plan.issue_confirmation_challenge@1"),
                    payload_schema_version=("IssuePlanConfirmationChallenge@1"),
                    invocation_id="envelope:plan:challenge",
                    actor_type="user",
                    expected_revision=1,
                    payload={
                        "draft_id": draft.draft_id,
                        "activation_intent": "confirm_and_activate",
                        "issued_at": "2026-07-27T01:05:00+08:00",
                        "expires_at": "2026-07-27T02:05:00+08:00",
                    },
                )
            )
        )
        assert isinstance(challenge, ApplicationCommandResult)
        raw_challenge = challenge.result
        confirm = json.loads(
            _encoded(
                command_name="trade_plan.confirm@1",
                payload_schema_version="ConfirmTradePlanDraft@1",
                invocation_id="envelope:plan:confirm",
                actor_type="user",
                expected_revision=1,
                payload={
                    "expected_draft_hash": raw_challenge["expected_draft_hash"],
                    "expected_diff_hash": raw_challenge["canonical_diff"][
                        "content_hash"
                    ],
                    "activation_intent": "confirm_and_activate",
                    "approved_at": "2026-07-27T01:10:00+08:00",
                },
            )
        )
        confirm["approval"] = {"challenge_id": raw_challenge["challenge_id"]}
        confirmed = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(json.dumps(confirm).encode())
        )
    assert isinstance(confirmed, ApplicationCommandResult)
    assert confirmed.result_type == "PlanConfirmationResult"
    assert confirmed.result["active_plan"]["version"]["plan_version_id"] == (
        draft.proposed_graph.version.plan_version_id
    )
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    stored_hash = connection.execute(
        "SELECT request_hash FROM application_command_receipt " "WHERE invocation_id=?",
        (confirmed.invocation_id,),
    ).fetchone()[0]
    connection.close()
    assert stored_hash == confirmed.request_hash


def test_system_and_first_release_web_plan_mutations_fail_closed(
    tmp_path: Path,
) -> None:
    data_root = _ready_root(tmp_path)
    system = json.loads(_encoded())
    system["decision_actor"] = {"actor_type": "system", "actor_id": "workflow"}
    system["interaction_channel"] = "workflow"
    system["transport_actor"] = {
        "actor_type": "system",
        "actor_id": "workflow",
    }
    web = json.loads(_encoded())
    web.update(
        {
            "command_name": "trade_plan.reject_draft@1",
            "payload_schema_version": "RejectTradePlanDraft@1",
            "expected_revision": 1,
            "decision_actor": {
                "actor_type": "user",
                "actor_id": "local-user",
            },
            "interaction_channel": "web",
            "transport_actor": {
                "actor_type": "adapter",
                "actor_id": "local-web",
            },
            "payload": {
                "draft_id": "trade_plan_draft_1",
                "rejected_at": "2026-07-27T00:00:00+08:00",
            },
        }
    )
    with open_application_commands(data_root) as dispatcher:
        system_denied = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(json.dumps(system).encode())
        )
        web_denied = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(json.dumps(web).encode())
        )
    assert isinstance(system_denied, ApplicationCommandFailure)
    assert system_denied.code == "SYSTEM_DECISION_CAPABILITY_DENIED"
    assert isinstance(web_denied, ApplicationCommandFailure)
    assert web_denied.code == "WEB_MUTATION_CAPABILITY_DENIED"


def test_all_mutations_cross_named_tasks_and_envelope() -> None:
    assert COMMAND_REGISTRY == (
        "account_snapshot.register_account@2",
        "account_snapshot.create_draft@1",
        "account_snapshot.update_draft@1",
        "account_snapshot.confirm@1",
        "trade_plan.create_draft@1",
        "trade_plan.revise_draft@1",
        "trade_plan.reject_draft@1",
        "trade_plan.issue_confirmation_challenge@1",
        "trade_plan.confirm@1",
        "manual_portfolio_review.run@1",
        "decision_task.defer@1",
        "decision_task.resolve@1",
        "execution_record.declare@1",
        "execution_record.correct@1",
        "discipline_review.confirm@1",
        "plan_impact_assessment.create@1",
        "plan_change_proposal.create@1",
        "plan_change_proposal.accept@1",
        "plan_change_proposal.reject@1",
    )
    cli = (
        Path(__file__).resolve().parents[2] / "src/trading_platform/cli.py"
    ).read_text(encoding="utf-8")
    assert 'add_parser("application-command")' in cli
    assert 'add_parser("watchlist-add")' not in cli
    assert 'add_parser("market-build")' not in cli
    assert 'add_parser("market-evaluate")' not in cli


def test_envelope_failure_redacts_payload_values() -> None:
    secret = "must-not-leak"
    try:
        ApplicationCommandEnvelopeV1.from_bytes(json.dumps({"secret": secret}).encode())
    except ValueError as error:
        assert getattr(error, "code") == "COMMAND_ENVELOPE_INVALID"
        assert getattr(error, "substep") == "application_command_envelope.decode"
        assert secret not in str(error)
    else:
        raise AssertionError("invalid envelope accepted")
