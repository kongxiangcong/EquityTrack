from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from trading_platform.domain.discipline_reviews import (
    DisciplineReviewError,
    DisciplineReviewInputs,
    DisciplineReviewPeriod,
    DisciplineReviewPeriodRequest,
    DisciplineReviewService,
    DisciplineReviewVersion,
    MonthlyDisciplineSummary,
)
from trading_platform.identity import canonical_hash


@dataclass(frozen=True)
class CreateDisciplineReviewDraft:
    invocation_id: str
    account_id: str
    period_request: DisciplineReviewPeriodRequest
    decision_actor: str
    interaction_channel: str
    transport_actor: str


@dataclass(frozen=True)
class ConfirmDisciplineReviewVersion:
    invocation_id: str
    discipline_review_id: str
    expected_version_no: int
    confirmed_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "ConfirmDisciplineReview@1"


@dataclass(frozen=True)
class GetDisciplineReview:
    discipline_review_id: str
    version_no: int | None = None


class DisciplineReviewRepository(Protocol):
    def by_draft_invocation(
        self, invocation_id: str
    ) -> DisciplineReviewVersion | None: ...

    def latest(
        self, discipline_review_id: str
    ) -> DisciplineReviewVersion | None: ...

    def resolve_period(
        self, request: DisciplineReviewPeriodRequest
    ) -> tuple[DisciplineReviewPeriod, tuple[str, ...]]: ...

    def collect(
        self,
        account_id: str,
        period: DisciplineReviewPeriod,
    ) -> DisciplineReviewInputs: ...

    def insert_draft(
        self, review: DisciplineReviewVersion
    ) -> DisciplineReviewVersion: ...

    def confirm(
        self,
        command: ConfirmDisciplineReviewVersion,
        confirmed: DisciplineReviewVersion,
    ) -> DisciplineReviewVersion: ...

    def confirmation_replay(
        self, command: ConfirmDisciplineReviewVersion
    ) -> DisciplineReviewVersion | None: ...

    def get(
        self, query: GetDisciplineReview
    ) -> DisciplineReviewVersion: ...

    def confirmed_for_month(
        self, account_id: str, month: str
    ) -> tuple[DisciplineReviewVersion, ...]: ...


class DisciplineReviews:
    """Owns immutable review drafting, confirmation, and aggregation."""

    def __init__(
        self,
        repository: DisciplineReviewRepository,
        service: DisciplineReviewService,
    ) -> None:
        self._repository = repository
        self._service = service

    def create_draft(
        self, command: CreateDisciplineReviewDraft
    ) -> DisciplineReviewVersion:
        if (
            not command.invocation_id
            or not command.account_id
            or not command.decision_actor.startswith(
                ("agent:", "system:", "user:")
            )
            or command.interaction_channel
            not in {"skill", "workflow", "cli"}
            or not command.transport_actor
        ):
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_COMMAND_INVALID"
            )
        command.period_request.validate()
        period, selection_gaps = self._repository.resolve_period(
            command.period_request
        )
        replay = self._repository.by_draft_invocation(
            command.invocation_id
        )
        if replay is not None:
            if (
                replay.account_id != command.account_id
                or replay.period != period
                or replay.created_at != command.period_request.requested_at
                or not set(selection_gaps).issubset(
                    replay.evidence_gap_summary
                )
            ):
                raise DisciplineReviewError(
                    "DISCIPLINE_REVIEW_INVOCATION_CONFLICT"
                )
            return replay
        inputs = replace(
            self._repository.collect(command.account_id, period),
            selection_evidence_gaps=selection_gaps,
        )
        review_id = "discipline_review_"
        review_id += canonical_hash(
            {
                "account_id": command.account_id,
                "period": period,
            }
        )[:24]
        draft = self._service.create_draft(
            inputs=inputs,
            invocation_id=command.invocation_id,
            prior=self._repository.latest(review_id),
            created_at=command.period_request.requested_at,
        )
        return self._repository.insert_draft(draft)

    def confirm(
        self, command: ConfirmDisciplineReviewVersion
    ) -> DisciplineReviewVersion:
        if (
            command.schema_version != "ConfirmDisciplineReview@1"
            or not command.invocation_id
            or not command.discipline_review_id
            or command.expected_version_no < 1
            or not command.decision_actor.startswith("user:")
            or command.interaction_channel not in {"skill", "cli"}
            or (
                command.interaction_channel == "skill"
                and not command.transport_actor.startswith("agent:")
            )
        ):
            raise DisciplineReviewError(
                "USER_REVIEW_CONFIRMATION_REQUIRED"
            )
        replay = self._repository.confirmation_replay(command)
        if replay is not None:
            return replay
        draft = self._repository.get(
            GetDisciplineReview(
                command.discipline_review_id,
                command.expected_version_no,
            )
        )
        confirmed = self._service.confirm(
            draft,
            invocation_id=command.invocation_id,
            confirmed_at=command.confirmed_at,
        )
        return self._repository.confirm(command, confirmed)

    def get(
        self, query: GetDisciplineReview
    ) -> DisciplineReviewVersion:
        if not query.discipline_review_id:
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_ID_REQUIRED"
            )
        return self._repository.get(query)

    def aggregate_month(
        self, account_id: str, month: str
    ) -> MonthlyDisciplineSummary:
        return self._service.aggregate_month(
            account_id=account_id,
            month=month,
            reviews=self._repository.confirmed_for_month(
                account_id, month
            ),
        )


__all__ = [
    "ConfirmDisciplineReviewVersion",
    "CreateDisciplineReviewDraft",
    "GetDisciplineReview",
]
