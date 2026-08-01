from __future__ import annotations

from dataclasses import dataclass

from .command_envelope import ApplicationCommandEnvelopeV1, InteractionChannel


class WebCommandPolicyError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WebCommandPolicy:
    """Owns the finite mutation authority of the local product surface."""

    allowed_commands: frozenset[str] = frozenset(
        {
            "account_snapshot.create_draft@1",
            "account_snapshot.update_draft@1",
            "account_snapshot.confirm@1",
            "trade_plan.issue_confirmation_challenge@1",
            "trade_plan.confirm@1",
            "chart_annotation.apply@1",
            "manual_portfolio_review.run@2",
            "decision_task.defer@1",
            "decision_task.resolve@1",
            "execution_record.declare@1",
            "discipline_review.create_draft@2",
            "discipline_review.confirm@1",
            "plan_change_proposal.accept@1",
            "plan_change_proposal.reject@1",
        }
    )

    def authorize(self, envelope: ApplicationCommandEnvelopeV1) -> None:
        if (
            envelope.interaction_channel is not InteractionChannel.WEB
            or envelope.transport_actor.identity != "adapter:web-local"
            or envelope.decision_actor.identity != "user:local-user"
            or envelope.command_name not in self.allowed_commands
        ):
            raise WebCommandPolicyError("WEB_COMMAND_CAPABILITY_DENIED")
        if (
            envelope.command_name == "trade_plan.confirm@1"
            and not envelope.approval_challenge_id
        ):
            raise WebCommandPolicyError(
                "PLAN_CONFIRMATION_CHALLENGE_REQUIRED"
            )


__all__ = ["WebCommandPolicy", "WebCommandPolicyError"]