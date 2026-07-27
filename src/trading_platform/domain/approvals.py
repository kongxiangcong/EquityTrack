from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

from trading_platform.identity import canonical_hash


class ApprovalError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ActivationIntent(str, Enum):
    CONFIRM_ONLY = "confirm_only"
    CONFIRM_AND_ACTIVATE = "confirm_and_activate"


@dataclass(frozen=True)
class CanonicalPlanDiff:
    based_on_graph_seal_hash: str | None
    proposed_graph_seal_hash: str
    changed_components: tuple[str, ...]
    content_hash: str
    schema_version: str = "CanonicalPlanDiff@1"

    @classmethod
    def build(
        cls,
        *,
        based_on_graph_seal_hash: str | None,
        proposed_graph_seal_hash: str,
        changed_components: tuple[str, ...],
    ) -> "CanonicalPlanDiff":
        canonical_components = tuple(
            sorted(set(changed_components))
        )
        payload = {
            "schema_version": "CanonicalPlanDiff@1",
            "based_on_graph_seal_hash": based_on_graph_seal_hash,
            "proposed_graph_seal_hash": proposed_graph_seal_hash,
            "changed_components": canonical_components,
        }
        return cls(
            based_on_graph_seal_hash=based_on_graph_seal_hash,
            proposed_graph_seal_hash=proposed_graph_seal_hash,
            changed_components=canonical_components,
            content_hash=canonical_hash(payload),
        )

    def validate(self) -> None:
        rebuilt = self.build(
            based_on_graph_seal_hash=self.based_on_graph_seal_hash,
            proposed_graph_seal_hash=self.proposed_graph_seal_hash,
            changed_components=self.changed_components,
        )
        if (
            self.schema_version != "CanonicalPlanDiff@1"
            or not self.proposed_graph_seal_hash
            or rebuilt != self
        ):
            raise ApprovalError("CANONICAL_PLAN_DIFF_INVALID")


@dataclass(frozen=True)
class PlanConfirmationChallenge:
    challenge_id: str
    plan_id: str
    draft_id: str
    expected_revision: int
    expected_draft_hash: str
    expected_graph_seal_hash: str
    canonical_diff: CanonicalPlanDiff
    activation_intent: ActivationIntent
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    issued_at: str
    expires_at: str | None
    status: str
    content_hash: str
    schema_version: str = "PlanConfirmationChallenge@1"

    def identity_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "challenge_id": self.challenge_id,
            "plan_id": self.plan_id,
            "draft_id": self.draft_id,
            "expected_revision": self.expected_revision,
            "expected_draft_hash": self.expected_draft_hash,
            "expected_graph_seal_hash": self.expected_graph_seal_hash,
            "canonical_diff_hash": self.canonical_diff.content_hash,
            "activation_intent": self.activation_intent,
            "decision_actor": self.decision_actor,
            "interaction_channel": self.interaction_channel,
            "transport_actor": self.transport_actor,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def validate(self) -> None:
        self.canonical_diff.validate()
        try:
            issued = datetime.fromisoformat(self.issued_at)
            expires = (
                datetime.fromisoformat(self.expires_at)
                if self.expires_at is not None
                else None
            )
        except ValueError as error:
            raise ApprovalError("PLAN_CHALLENGE_INVALID") from error
        if (
            self.schema_version != "PlanConfirmationChallenge@1"
            or not self.challenge_id
            or not self.plan_id
            or not self.draft_id
            or self.expected_revision < 1
            or not self.expected_draft_hash
            or self.expected_graph_seal_hash
            != self.canonical_diff.proposed_graph_seal_hash
            or not self.decision_actor.startswith("user:")
            or self.interaction_channel not in {"skill", "cli", "web"}
            or not _transport_valid(self.transport_actor)
            or issued.tzinfo is None
            or (
                expires is not None
                and (expires.tzinfo is None or expires <= issued)
            )
            or self.status
            not in {
                "issued",
                "consumed",
                "superseded",
                "cancelled",
                "expired",
            }
            or self.content_hash != canonical_hash(self.identity_payload())
        ):
            raise ApprovalError("PLAN_CHALLENGE_INVALID")


@dataclass(frozen=True)
class UserApprovalReceipt:
    approval_receipt_id: str
    challenge_id: str
    plan_id: str
    draft_id: str
    approved_revision: int
    approved_draft_hash: str
    approved_graph_seal_hash: str
    approved_diff_hash: str
    activation_intent: ActivationIntent
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    command_invocation_id: str
    approved_at: str
    content_hash: str
    schema_version: str = "UserApprovalReceipt@1"

    def identity_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "approval_receipt_id": self.approval_receipt_id,
            "challenge_id": self.challenge_id,
            "plan_id": self.plan_id,
            "draft_id": self.draft_id,
            "approved_revision": self.approved_revision,
            "approved_draft_hash": self.approved_draft_hash,
            "approved_graph_seal_hash": self.approved_graph_seal_hash,
            "approved_diff_hash": self.approved_diff_hash,
            "activation_intent": self.activation_intent,
            "decision_actor": self.decision_actor,
            "interaction_channel": self.interaction_channel,
            "transport_actor": self.transport_actor,
            "command_invocation_id": self.command_invocation_id,
            "approved_at": self.approved_at,
        }

    def validate(self) -> None:
        try:
            approved = datetime.fromisoformat(self.approved_at)
        except ValueError as error:
            raise ApprovalError("USER_APPROVAL_RECEIPT_INVALID") from error
        if (
            self.schema_version != "UserApprovalReceipt@1"
            or not self.approval_receipt_id
            or not self.challenge_id
            or not self.plan_id
            or not self.draft_id
            or self.approved_revision < 1
            or not self.approved_draft_hash
            or not self.approved_graph_seal_hash
            or not self.approved_diff_hash
            or not self.decision_actor.startswith("user:")
            or self.interaction_channel not in {"skill", "cli", "web"}
            or not _transport_valid(self.transport_actor)
            or not self.command_invocation_id
            or approved.tzinfo is None
            or self.content_hash != canonical_hash(self.identity_payload())
        ):
            raise ApprovalError("USER_APPROVAL_RECEIPT_INVALID")


def _transport_valid(value: str) -> bool:
    return any(
        value.startswith(prefix)
        for prefix in ("user:", "agent:", "adapter:")
    )


__all__ = [
    "ActivationIntent",
    "ApprovalError",
    "CanonicalPlanDiff",
    "PlanConfirmationChallenge",
    "UserApprovalReceipt",
]
