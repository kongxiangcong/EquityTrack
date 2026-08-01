from __future__ import annotations

import pytest

from trading_platform.application.command_envelope import (
    ApplicationCommandEnvelopeV1,
    COMMAND_REGISTRY,
    CommandEnvelopeError,
    DecisionActor,
    InteractionChannel,
    TransportActor,
)


def _manual_review_envelope(
    *,
    command_name: str,
    payload_schema_version: str,
) -> ApplicationCommandEnvelopeV1:
    return ApplicationCommandEnvelopeV1(
        command_name=command_name,
        invocation_id="manual-review:v2:contract",
        payload_schema_version=payload_schema_version,
        expected_revision=None,
        decision_actor=DecisionActor("agent", "codex"),
        interaction_channel=InteractionChannel.CODEX,
        transport_actor=TransportActor("agent", "codex"),
        approval_challenge_id=None,
        payload={
            "account_id": "account_local",
            "requested_at": "2026-07-30T16:00:00+08:00",
            "session_selection": "latest_proven_complete_session",
        },
    )


def test_manual_review_v2_is_the_registered_control_plane_contract() -> None:
    assert "manual_portfolio_review.run@2" in COMMAND_REGISTRY
    envelope = _manual_review_envelope(
        command_name="manual_portfolio_review.run@2",
        payload_schema_version="RunManualPortfolioReview@2",
    )
    assert set(envelope.payload) == {
        "account_id",
        "requested_at",
        "session_selection",
    }
    assert (
        envelope.payload["session_selection"]
        == "latest_proven_complete_session"
    )


def test_manual_review_v1_is_not_a_registered_compatibility_path() -> None:
    assert "manual_portfolio_review.run@1" not in COMMAND_REGISTRY
    with pytest.raises(
        CommandEnvelopeError, match="COMMAND_NAME_UNSUPPORTED"
    ):
        _manual_review_envelope(
            command_name="manual_portfolio_review.run@1",
            payload_schema_version="RunManualPortfolioReview@1",
        )
