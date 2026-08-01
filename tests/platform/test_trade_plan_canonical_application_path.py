from __future__ import annotations

from pathlib import Path

import pytest

import trading_platform.application as application
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
    CreatePlanChangeProposal,
    DecisionActor,
    InteractionChannel,
    TransportActor,
    open_application_commands,
    open_plan_impacts,
)


@pytest.mark.parametrize(
    "symbol",
    (
        "open_trade_plan",
        "TradePlanTasks",
        "CreateTradePlanDraft",
        "ReviseTradePlanDraft",
    ),
)
def test_public_application_hides_low_level_trade_plan_mutations(
    symbol: str,
) -> None:
    assert symbol not in application.__all__
    assert not hasattr(application, symbol)


def _proposal_authority(tmp_path: Path, suffix: str):
    from tests.platform.test_plan_change_proposals import (
        _proposal_authority as existing_proposal_authority,
    )

    return existing_proposal_authority(tmp_path, suffix)


def _accept_envelope(
    *,
    proposal_id: str,
    expected_revision: int,
    invocation_id: str,
    decided_at: str,
    extra_payload: dict[str, object] | None = None,
) -> ApplicationCommandEnvelopeV1:
    payload: dict[str, object] = {
        "proposal_id": proposal_id,
        "decided_at": decided_at,
    }
    if extra_payload is not None:
        payload.update(extra_payload)
    return ApplicationCommandEnvelopeV1(
        command_name="plan_change_proposal.accept@1",
        invocation_id=invocation_id,
        payload_schema_version="AcceptPlanChangeProposal@1",
        expected_revision=expected_revision,
        decision_actor=DecisionActor("user", "local-user"),
        interaction_channel=InteractionChannel.CODEX,
        transport_actor=TransportActor("agent", "codex"),
        approval_challenge_id=None,
        payload=payload,
    )


@pytest.mark.parametrize(
    "legacy_payload",
    (
        {"draft_id": "caller-selected-draft"},
        {
            "draft_id": "caller-selected-draft",
            "expected_draft_revision": None,
        },
    ),
    ids=("draft_id", "expected_draft_revision"),
)
def test_proposal_accept_rejects_caller_selected_draft_identity(
    tmp_path: Path,
    legacy_payload: dict[str, object],
) -> None:
    data_root, _, proposal = _proposal_authority(
        tmp_path, f"legacy-{next(iter(legacy_payload))}"
    )
    envelope = _accept_envelope(
        proposal_id=proposal.proposal_id,
        expected_revision=proposal.revision,
        invocation_id=(
            "proposal:accept:legacy:"
            + "-".join(sorted(legacy_payload))
        ),
        decided_at="2026-07-27T16:45:00+08:00",
        extra_payload=legacy_payload,
    )

    with open_application_commands(data_root) as dispatcher:
        result = dispatcher.dispatch(envelope)

    assert isinstance(result, ApplicationCommandFailure)
    assert result.code == "PROPOSAL_DISPOSITION_COMMAND_FIELDS_INVALID"


def test_public_proposal_accept_creates_then_revises_owner_open_draft(
    tmp_path: Path,
) -> None:
    data_root, assessment, first_proposal = _proposal_authority(
        tmp_path, "owner-open-draft"
    )
    with open_plan_impacts(data_root) as impacts:
        second_proposal = impacts.create_proposal(
            CreatePlanChangeProposal(
                invocation_id="proposal:create:owner-open-draft:second",
                assessment_id=assessment.assessment_id,
                proposed_content={
                    "schema_version": "TradePlanContent@1",
                    "purpose": "owner-open-draft-second",
                },
                parameters={"proposal": "owner-open-draft-second"},
                created_by="agent",
                created_at="2026-07-27T16:45:30+08:00",
            )
        )

    first_envelope = _accept_envelope(
        proposal_id=first_proposal.proposal_id,
        expected_revision=first_proposal.revision,
        invocation_id="proposal:accept:owner-open-draft:first",
        decided_at="2026-07-27T16:46:00+08:00",
    )
    second_envelope = _accept_envelope(
        proposal_id=second_proposal.proposal_id,
        expected_revision=second_proposal.revision,
        invocation_id="proposal:accept:owner-open-draft:second",
        decided_at="2026-07-27T16:47:00+08:00",
    )
    assert set(first_envelope.payload) == {"proposal_id", "decided_at"}
    assert set(second_envelope.payload) == {"proposal_id", "decided_at"}

    with open_application_commands(data_root) as dispatcher:
        first = dispatcher.dispatch(first_envelope)
        replay = dispatcher.dispatch(first_envelope)
        second = dispatcher.dispatch(second_envelope)

        assert isinstance(first, ApplicationCommandResult)
        assert replay == first
        assert isinstance(second, ApplicationCommandResult)
        assert first.result["accepted_draft_id"]
        assert (
            second.result["accepted_draft_id"]
            == first.result["accepted_draft_id"]
        )

        challenge = dispatcher.dispatch(
            ApplicationCommandEnvelopeV1(
                command_name=(
                    "trade_plan.issue_confirmation_challenge@1"
                ),
                invocation_id="proposal:owner-open-draft:challenge",
                payload_schema_version=(
                    "IssuePlanConfirmationChallenge@1"
                ),
                expected_revision=2,
                decision_actor=DecisionActor("user", "local-user"),
                interaction_channel=InteractionChannel.CODEX,
                transport_actor=TransportActor("agent", "codex"),
                approval_challenge_id=None,
                payload={
                    "draft_id": first.result["accepted_draft_id"],
                    "activation_intent": "confirm_only",
                    "issued_at": "2026-07-27T16:48:00+08:00",
                    "expires_at": "2026-07-27T17:48:00+08:00",
                },
            )
        )

    assert isinstance(challenge, ApplicationCommandResult)
    assert challenge.result_type == "PlanConfirmationChallenge"
