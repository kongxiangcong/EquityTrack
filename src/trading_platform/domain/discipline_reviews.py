from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from trading_platform.identity import canonical_hash

from .decision_journal import ActionLogEntry, ExecutionRecord
from .decision_tasks import DecisionTask, UserDisposition


class DisciplineReviewError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DisciplineReviewPeriod:
    period_kind: str
    period_start_session: str
    period_end_session: str
    timezone: str = "Asia/Shanghai"

    def validate(self) -> None:
        try:
            start = date.fromisoformat(self.period_start_session)
            end = date.fromisoformat(self.period_end_session)
        except ValueError as error:
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_PERIOD_INVALID"
            ) from error
        if (
            self.period_kind not in {"weekly", "custom"}
            or self.timezone != "Asia/Shanghai"
            or start > end
            or (
                self.period_kind == "weekly"
                and (end - start).days > 7
            )
        ):
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_PERIOD_INVALID"
            )


@dataclass(frozen=True)
class DisciplineException:
    exception_id: str
    kind: str
    decision_task_id: str
    action_log_entry_id: str | None
    execution_record_id: str | None
    evidence_refs: tuple[str, ...]
    content_hash: str

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key != "content_hash"
        }
        if (
            not self.exception_id
            or self.kind
            not in {
                "overridden",
                "skipped",
                "deferred",
                "unrecorded",
                "unverified",
            }
            or not self.decision_task_id
            or not self.evidence_refs
            or self.content_hash != canonical_hash(identity)
        ):
            raise DisciplineReviewError(
                "DISCIPLINE_EXCEPTION_INVALID"
            )


@dataclass(frozen=True)
class DisciplineReviewVersion:
    discipline_review_id: str
    version_no: int
    supersedes_version_no: int | None
    account_id: str
    period: DisciplineReviewPeriod
    status: str
    review_run_ids: tuple[str, ...]
    decision_task_ids: tuple[str, ...]
    action_log_entry_ids: tuple[str, ...]
    execution_record_ids: tuple[str, ...]
    plan_version_ids: tuple[str, ...]
    account_snapshot_version_ids: tuple[str, ...]
    exceptions: tuple[DisciplineException, ...]
    overridden_items: tuple[str, ...]
    unrecorded_items: tuple[str, ...]
    unverified_items: tuple[str, ...]
    drift_assessment_ids: tuple[str, ...]
    evidence_gap_summary: tuple[str, ...]
    content_hash: str
    created_at: str
    draft_invocation_id: str | None
    confirmed_at: str | None
    confirmation_command_receipt_id: str | None
    schema_version: str = "DisciplineReviewVersion@1"

    def validate(self) -> None:
        self.period.validate()
        try:
            created = datetime.fromisoformat(self.created_at)
            confirmed = (
                datetime.fromisoformat(self.confirmed_at)
                if self.confirmed_at is not None
                else None
            )
        except ValueError as error:
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_TIME_INVALID"
            ) from error
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key != "content_hash"
        }
        if (
            self.schema_version != "DisciplineReviewVersion@1"
            or not self.discipline_review_id
            or self.version_no < 1
            or (
                self.version_no == 1
                and self.supersedes_version_no is not None
            )
            or (
                self.version_no > 1
                and self.supersedes_version_no != self.version_no - 1
            )
            or not self.account_id
            or self.status not in {"draft", "confirmed", "superseded"}
            or created.tzinfo is None
            or (
                self.status == "confirmed"
                and (
                    confirmed is None
                    or not self.confirmation_command_receipt_id
                )
            )
            or (
                self.status != "confirmed"
                and (
                    confirmed is not None
                    or self.confirmation_command_receipt_id is not None
                )
            )
            or self.content_hash != canonical_hash(identity)
        ):
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_INVALID"
            )
        for exception in self.exceptions:
            exception.validate()


@dataclass(frozen=True)
class DisciplineReviewInputs:
    account_id: str
    period: DisciplineReviewPeriod
    tasks: tuple[DecisionTask, ...]
    actions: tuple[ActionLogEntry, ...]
    executions: tuple[ExecutionRecord, ...]
    review_run_ids: tuple[str, ...]
    account_snapshot_version_ids: tuple[str, ...]
    drift_assessment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MonthlyDisciplineSummary:
    account_id: str
    month: str
    confirmed_review_versions: tuple[tuple[str, int], ...]
    overridden_items: tuple[str, ...]
    unrecorded_items: tuple[str, ...]
    unverified_items: tuple[str, ...]


class DisciplineReviewService:
    """Builds evidence classifications without behavioral scoring."""

    def create_draft(
        self,
        *,
        inputs: DisciplineReviewInputs,
        invocation_id: str,
        prior: DisciplineReviewVersion | None,
        created_at: str,
    ) -> DisciplineReviewVersion:
        inputs.period.validate()
        review_id = "discipline_review_" + canonical_hash(
            {
                "account_id": inputs.account_id,
                "period": inputs.period,
            }
        )[:24]
        if prior is not None and prior.discipline_review_id != review_id:
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_IDENTITY_CONFLICT"
            )
        actions_by_task: dict[str, list[ActionLogEntry]] = {}
        for action in inputs.actions:
            actions_by_task.setdefault(
                action.decision_task_id, []
            ).append(action)
        active_executions = _active_executions(inputs.executions)
        executions_by_action = {
            execution.action_log_entry_id: execution
            for execution in active_executions
        }
        exceptions: list[DisciplineException] = []
        for task in inputs.tasks:
            task_actions = actions_by_task.get(
                task.decision_task_id, []
            )
            if not task_actions:
                exceptions.append(
                    _exception(
                        "unrecorded",
                        task.decision_task_id,
                        None,
                        None,
                        (task.evidence_manifest_id,),
                    )
                )
                continue
            for action in task_actions:
                kind = {
                    UserDisposition.OVERRIDDEN: "overridden",
                    UserDisposition.SKIPPED: "skipped",
                    UserDisposition.DEFERRED: "deferred",
                }.get(action.disposition)
                if kind is not None:
                    exceptions.append(
                        _exception(
                            kind,
                            task.decision_task_id,
                            action.action_log_entry_id,
                            None,
                            (
                                task.evidence_manifest_id,
                                action.content_hash,
                            ),
                        )
                    )
                execution = executions_by_action.get(
                    action.action_log_entry_id
                )
                if (
                    execution is not None
                    and execution.verification_status.value
                    != "broker_matched"
                ):
                    exceptions.append(
                        _exception(
                            "unverified",
                            task.decision_task_id,
                            action.action_log_entry_id,
                            execution.execution_record_id,
                            (
                                task.evidence_manifest_id,
                                execution.content_hash,
                            ),
                        )
                    )
        exceptions = sorted(
            exceptions, key=lambda item: item.exception_id
        )
        version_no = 1 if prior is None else prior.version_no + 1
        base = DisciplineReviewVersion(
            discipline_review_id=review_id,
            version_no=version_no,
            supersedes_version_no=(
                prior.version_no if prior is not None else None
            ),
            account_id=inputs.account_id,
            period=inputs.period,
            status="draft",
            review_run_ids=tuple(sorted(set(inputs.review_run_ids))),
            decision_task_ids=tuple(
                sorted(task.decision_task_id for task in inputs.tasks)
            ),
            action_log_entry_ids=tuple(
                sorted(action.action_log_entry_id for action in inputs.actions)
            ),
            execution_record_ids=tuple(
                sorted(
                    execution.execution_record_id
                    for execution in inputs.executions
                )
            ),
            plan_version_ids=tuple(
                sorted(
                    {
                        task.plan_version_id
                        for task in inputs.tasks
                        if task.plan_version_id is not None
                    }
                )
            ),
            account_snapshot_version_ids=tuple(
                sorted(set(inputs.account_snapshot_version_ids))
            ),
            exceptions=tuple(exceptions),
            overridden_items=_exception_refs(
                exceptions, "overridden", "decision_task_id"
            ),
            unrecorded_items=_exception_refs(
                exceptions, "unrecorded", "decision_task_id"
            ),
            unverified_items=_exception_refs(
                exceptions, "unverified", "execution_record_id"
            ),
            drift_assessment_ids=tuple(
                sorted(set(inputs.drift_assessment_ids))
            ),
            evidence_gap_summary=tuple(
                sorted(
                    {
                        f"{item.kind}:{item.decision_task_id}"
                        for item in exceptions
                        if item.kind
                        in {"deferred", "unrecorded", "unverified"}
                    }
                )
            ),
            content_hash="",
            created_at=created_at,
            draft_invocation_id=invocation_id,
            confirmed_at=None,
            confirmation_command_receipt_id=None,
        )
        return _hashed_review(base)

    def confirm(
        self,
        draft: DisciplineReviewVersion,
        *,
        invocation_id: str,
        confirmed_at: str,
    ) -> DisciplineReviewVersion:
        if draft.status != "draft":
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_NOT_DRAFT"
            )
        confirmed = replace(
            draft,
            version_no=draft.version_no + 1,
            supersedes_version_no=draft.version_no,
            status="confirmed",
            content_hash="",
            draft_invocation_id=None,
            confirmed_at=confirmed_at,
            confirmation_command_receipt_id=invocation_id,
        )
        return _hashed_review(confirmed)

    def aggregate_month(
        self,
        *,
        account_id: str,
        month: str,
        reviews: tuple[DisciplineReviewVersion, ...],
    ) -> MonthlyDisciplineSummary:
        try:
            date.fromisoformat(f"{month}-01")
        except ValueError as error:
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_MONTH_INVALID"
            ) from error
        latest: dict[str, DisciplineReviewVersion] = {}
        for review in reviews:
            if (
                review.account_id == account_id
                and review.status == "confirmed"
                and review.period.period_end_session.startswith(month)
                and (
                    review.discipline_review_id not in latest
                    or review.version_no
                    > latest[review.discipline_review_id].version_no
                )
            ):
                latest[review.discipline_review_id] = review
        selected = tuple(
            sorted(
                latest.values(),
                key=lambda item: (
                    item.period.period_end_session,
                    item.discipline_review_id,
                ),
            )
        )
        return MonthlyDisciplineSummary(
            account_id=account_id,
            month=month,
            confirmed_review_versions=tuple(
                (
                    review.discipline_review_id,
                    review.version_no,
                )
                for review in selected
            ),
            overridden_items=_collected_review_items(
                selected, "overridden_items"
            ),
            unrecorded_items=_collected_review_items(
                selected, "unrecorded_items"
            ),
            unverified_items=_collected_review_items(
                selected, "unverified_items"
            ),
        )


def _exception(
    kind: str,
    decision_task_id: str,
    action_log_entry_id: str | None,
    execution_record_id: str | None,
    evidence_refs: tuple[str, ...],
) -> DisciplineException:
    exception_id = "discipline_exception_" + canonical_hash(
        {
            "kind": kind,
            "decision_task_id": decision_task_id,
            "action_log_entry_id": action_log_entry_id,
            "execution_record_id": execution_record_id,
            "evidence_refs": evidence_refs,
        }
    )[:24]
    base = DisciplineException(
        exception_id=exception_id,
        kind=kind,
        decision_task_id=decision_task_id,
        action_log_entry_id=action_log_entry_id,
        execution_record_id=execution_record_id,
        evidence_refs=evidence_refs,
        content_hash="",
    )
    return replace(
        base,
        content_hash=canonical_hash(
            {
                key: value
                for key, value in base.__dict__.items()
                if key != "content_hash"
            }
        ),
    )


def _hashed_review(
    review: DisciplineReviewVersion,
) -> DisciplineReviewVersion:
    prepared = replace(
        review,
        content_hash=canonical_hash(
            {
                key: value
                for key, value in review.__dict__.items()
                if key != "content_hash"
            }
        ),
    )
    prepared.validate()
    return prepared


def _active_executions(
    executions: tuple[ExecutionRecord, ...],
) -> tuple[ExecutionRecord, ...]:
    corrected = {
        execution.corrects_execution_record_id
        for execution in executions
        if execution.corrects_execution_record_id is not None
    }
    return tuple(
        execution
        for execution in executions
        if execution.execution_record_id not in corrected
    )


def _exception_refs(
    exceptions: list[DisciplineException],
    kind: str,
    field: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value)
                for item in exceptions
                if item.kind == kind
                for value in (getattr(item, field),)
                if value is not None
            }
        )
    )


def _collected_review_items(
    reviews: tuple[DisciplineReviewVersion, ...],
    field: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value
                for review in reviews
                for value in getattr(review, field)
            }
        )
    )


__all__ = [
    "DisciplineException",
    "DisciplineReviewPeriod",
    "DisciplineReviewService",
    "DisciplineReviewVersion",
]
