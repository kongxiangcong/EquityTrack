from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tests.platform.canonical_plan_journey_fixture import (
    application_envelope_bytes,
    arrange_canonical_plan_journey,
)
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
)
from trading_platform.domain.plans import PlanValidationError
from trading_platform.persistence.plans import SQLiteTradePlanRepository


def test_confirmation_round_trip_failure_rolls_back_public_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with arrange_canonical_plan_journey(
        tmp_path, activate=False
    ) as journey:
        issued_at = datetime.fromisoformat(journey.review_requested_at)
        challenge = journey.platform.application_commands.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                application_envelope_bytes(
                    command_name=(
                        "trade_plan.issue_confirmation_challenge@1"
                    ),
                    payload_schema_version=(
                        "IssuePlanConfirmationChallenge@1"
                    ),
                    invocation_id="atomicity:challenge",
                    actor_type="user",
                    expected_revision=journey.draft_revision,
                    payload={
                        "draft_id": journey.draft_id,
                        "activation_intent": "confirm_and_activate",
                        "issued_at": issued_at.isoformat(),
                        "expires_at": (
                            issued_at + timedelta(hours=1)
                        ).isoformat(),
                    },
                )
            )
        )
        assert isinstance(challenge, ApplicationCommandResult)
        challenge_result = challenge.result
        canonical_diff = challenge_result["canonical_diff"]
        assert isinstance(canonical_diff, dict)
        confirm = ApplicationCommandEnvelopeV1.from_bytes(
            application_envelope_bytes(
                command_name="trade_plan.confirm@1",
                payload_schema_version="ConfirmTradePlanDraft@1",
                invocation_id="atomicity:confirm",
                actor_type="user",
                expected_revision=int(
                    challenge_result["expected_revision"]
                ),
                approval_challenge_id=str(
                    challenge_result["challenge_id"]
                ),
                payload={
                    "expected_draft_hash": str(
                        challenge_result["expected_draft_hash"]
                    ),
                    "expected_diff_hash": str(
                        canonical_diff["content_hash"]
                    ),
                    "activation_intent": "confirm_and_activate",
                    "approved_at": (
                        issued_at + timedelta(minutes=1)
                    ).isoformat(),
                },
            )
        )

        def reject_round_trip(_row) -> None:
            raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")

        with monkeypatch.context() as context:
            context.setattr(
                SQLiteTradePlanRepository,
                "_decode_reference",
                staticmethod(reject_round_trip),
            )
            failed = journey.platform.application_commands.dispatch(
                confirm
            )
        assert isinstance(failed, ApplicationCommandFailure)
        assert failed.code == "PLAN_GRAPH_CHILD_INVALID"

        succeeded = journey.platform.application_commands.dispatch(confirm)
        assert isinstance(succeeded, ApplicationCommandResult)
        assert succeeded.result_type == "PlanConfirmationResult"
        assert succeeded.result["active_plan"]["activation"] is not None
