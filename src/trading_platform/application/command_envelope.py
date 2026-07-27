from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from trading_platform.identity import canonical_hash


class CommandEnvelopeError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        substep: str = "application_command_envelope.decode",
        cause_type: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.substep = substep
        self.cause_type = cause_type


class InteractionChannel(str, Enum):
    CODEX = "skill"
    CLI = "cli"
    WEB = "web"
    WORKFLOW = "workflow"


class ApprovalCapability(str, Enum):
    DRAFT_MUTATION = "draft_mutation"
    ACCOUNT_CONFIRMATION = "account_confirmation"
    PLAN_CONFIRMATION = "plan_confirmation"
    TASK_DISPOSITION = "task_disposition"
    EXECUTION_TRUTH = "execution_truth"
    REVIEW_CONFIRMATION = "review_confirmation"


@dataclass(frozen=True)
class DecisionActor:
    actor_type: str
    actor_id: str

    def __post_init__(self) -> None:
        if self.actor_type not in {"user", "agent", "system"} or not self.actor_id:
            raise CommandEnvelopeError("COMMAND_DECISION_ACTOR_INVALID")

    @property
    def identity(self) -> str:
        return f"{self.actor_type}:{self.actor_id}"


@dataclass(frozen=True)
class TransportActor:
    actor_type: str
    actor_id: str

    def __post_init__(self) -> None:
        if (
            self.actor_type not in {"user", "agent", "adapter", "system"}
            or not self.actor_id
        ):
            raise CommandEnvelopeError("COMMAND_TRANSPORT_ACTOR_INVALID")

    @property
    def identity(self) -> str:
        return f"{self.actor_type}:{self.actor_id}"


_PAYLOAD_SCHEMAS = {
    "account_snapshot.create_draft@1": "CreateAccountSnapshotDraft@1",
    "account_snapshot.update_draft@1": "UpdateAccountSnapshotDraft@1",
    "account_snapshot.confirm@1": "ConfirmAccountSnapshot@1",
    "trade_plan.create_draft@1": "CreateTradePlanDraft@1",
    "trade_plan.revise_draft@1": "ReviseTradePlanDraft@1",
    "trade_plan.reject_draft@1": "RejectTradePlanDraft@1",
    "trade_plan.issue_confirmation_challenge@1": (
        "IssuePlanConfirmationChallenge@1"
    ),
    "trade_plan.confirm@1": "ConfirmTradePlanDraft@1",
    "manual_portfolio_review.run@1": "RunManualPortfolioReview@1",
    "decision_task.defer@1": "DeferDecisionTask@1",
    "decision_task.resolve@1": "ResolveDecisionTask@1",
    "execution_record.declare@1": "DeclareExecutionRecord@1",
    "execution_record.correct@1": "CorrectExecutionRecord@1",
    "discipline_review.confirm@1": "ConfirmDisciplineReview@1",
    "plan_change_proposal.accept@1": "AcceptPlanChangeProposal@1",
    "plan_change_proposal.reject@1": "RejectPlanChangeProposal@1",
}


@dataclass(frozen=True)
class ApplicationCommandEnvelopeV1:
    command_name: str
    invocation_id: str
    payload_schema_version: str
    expected_revision: int | None
    decision_actor: DecisionActor
    interaction_channel: InteractionChannel
    transport_actor: TransportActor
    approval_challenge_id: str | None
    payload: Mapping[str, object]
    schema_version: str = "ApplicationCommandEnvelope@1"

    def __post_init__(self) -> None:
        if self.schema_version != "ApplicationCommandEnvelope@1":
            raise CommandEnvelopeError("COMMAND_ENVELOPE_SCHEMA_UNSUPPORTED")
        expected_schema = _PAYLOAD_SCHEMAS.get(self.command_name)
        if expected_schema is None:
            raise CommandEnvelopeError("COMMAND_NAME_UNSUPPORTED")
        if self.payload_schema_version != expected_schema:
            raise CommandEnvelopeError("COMMAND_PAYLOAD_SCHEMA_MISMATCH")
        if not self.invocation_id:
            raise CommandEnvelopeError("COMMAND_INVOCATION_ID_REQUIRED")
        if self.expected_revision is not None and (
            isinstance(self.expected_revision, bool)
            or self.expected_revision < 1
        ):
            raise CommandEnvelopeError("COMMAND_EXPECTED_REVISION_INVALID")
        if not isinstance(self.payload, Mapping):
            raise CommandEnvelopeError("COMMAND_PAYLOAD_INVALID")
        canonical_hash(self.canonical_content)

    @classmethod
    def from_bytes(cls, encoded: bytes) -> "ApplicationCommandEnvelopeV1":
        try:
            raw = json.loads(encoded)
            if not isinstance(raw, Mapping):
                raise TypeError("object required")
            decision = raw["decision_actor"]
            transport = raw["transport_actor"]
            approval = raw.get("approval")
            if not isinstance(decision, Mapping) or not isinstance(
                transport, Mapping
            ):
                raise TypeError("actor object required")
            if approval is not None and not isinstance(approval, Mapping):
                raise TypeError("approval object required")
            return cls(
                schema_version=str(raw["schema_version"]),
                command_name=str(raw["command_name"]),
                invocation_id=str(raw["invocation_id"]),
                payload_schema_version=str(raw["payload_schema_version"]),
                expected_revision=(
                    int(raw["expected_revision"])
                    if raw.get("expected_revision") is not None
                    else None
                ),
                decision_actor=DecisionActor(
                    str(decision["actor_type"]), str(decision["actor_id"])
                ),
                interaction_channel=InteractionChannel(
                    str(raw["interaction_channel"])
                ),
                transport_actor=TransportActor(
                    str(transport["actor_type"]), str(transport["actor_id"])
                ),
                approval_challenge_id=(
                    str(approval["challenge_id"])
                    if approval is not None
                    and approval.get("challenge_id") is not None
                    else None
                ),
                payload=raw["payload"],
            )
        except CommandEnvelopeError:
            raise
        except Exception as error:
            raise CommandEnvelopeError(
                "COMMAND_ENVELOPE_INVALID",
                cause_type=type(error).__name__,
            ) from error

    @property
    def canonical_content(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "command_name": self.command_name,
            "invocation_id": self.invocation_id,
            "payload_schema_version": self.payload_schema_version,
            "expected_revision": self.expected_revision,
            "decision_actor": {
                "actor_type": self.decision_actor.actor_type,
                "actor_id": self.decision_actor.actor_id,
            },
            "interaction_channel": self.interaction_channel.value,
            "transport_actor": {
                "actor_type": self.transport_actor.actor_type,
                "actor_id": self.transport_actor.actor_id,
            },
            "approval": (
                {"challenge_id": self.approval_challenge_id}
                if self.approval_challenge_id is not None
                else None
            ),
            "payload": self.payload,
        }


COMMAND_REGISTRY = tuple(_PAYLOAD_SCHEMAS)


__all__ = [
    "ApplicationCommandEnvelopeV1",
    "ApprovalCapability",
    "COMMAND_REGISTRY",
    "CommandEnvelopeError",
    "DecisionActor",
    "InteractionChannel",
    "TransportActor",
]
