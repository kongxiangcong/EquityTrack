from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta

from trading_platform.application.decision_journal import (
    ListDecisionJournal,
)
from trading_platform.application.decision_tasks import (
    ListDecisionTasks,
)
from trading_platform.application.discipline_reviews import (
    ConfirmDisciplineReviewVersion,
    GetDisciplineReview,
)
from trading_platform.domain.discipline_reviews import (
    DisciplineException,
    DisciplineReviewError,
    DisciplineReviewInputs,
    DisciplineReviewPeriod,
    DisciplineReviewPeriodRequest,
    DisciplineReviewVersion,
)
from trading_platform.domain.decision_tasks import DecisionTaskState
from trading_platform.identity import canonical_hash
from trading_platform.domain.market_time import SHANGHAI_TIMEZONE

from .decision_journal import SQLiteDecisionJournalRepository
from .decision_tasks import SQLiteDecisionTaskRepository
from .locking import DataRootWriterLock


class SQLiteDisciplineReviewRepository:
    """Owns review authority reads and immutable version transactions."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock
        self._tasks = SQLiteDecisionTaskRepository(
            connection, writer_lock
        )
        self._journal = SQLiteDecisionJournalRepository(
            connection, writer_lock
        )

    def by_draft_invocation(
        self, invocation_id: str
    ) -> DisciplineReviewVersion | None:
        row = self._connection.execute(
            "SELECT * FROM discipline_review_version "
            "WHERE draft_invocation_id=?",
            (invocation_id,),
        ).fetchone()
        return self._review(row) if row is not None else None

    def latest(
        self, discipline_review_id: str
    ) -> DisciplineReviewVersion | None:
        row = self._connection.execute(
            "SELECT * FROM discipline_review_version "
            "WHERE discipline_review_id=? "
            "ORDER BY version_no DESC LIMIT 1",
            (discipline_review_id,),
        ).fetchone()
        return self._review(row) if row is not None else None

    def resolve_period(
        self, request: DisciplineReviewPeriodRequest
    ) -> tuple[DisciplineReviewPeriod, tuple[str, ...]]:
        request.validate()
        requested = datetime.fromisoformat(request.requested_at)
        local_date = requested.astimezone(SHANGHAI_TIMEZONE).date()
        complete_dates: set[date] = set()
        rows = self._connection.execute(
            "SELECT DISTINCT s.effective_session_date,s.as_of_at,"
            "s.last_success_at FROM data_snapshot s "
            "JOIN data_snapshot_universe_ref u "
            "ON u.data_snapshot_id=s.data_snapshot_id "
            "JOIN market_universe_version v "
            "ON v.market_universe_version_id=u.market_universe_version_id "
            "WHERE s.market_timezone='Asia/Shanghai' "
            "AND s.snapshot_purpose IN ('research','workflow','market') "
            "AND u.market_scope_id='CN_A_SHARE' "
            "AND v.market_scope_id='CN_A_SHARE' "
            "AND s.quality_status='pass' "
            "AND s.freshness_status='valid' "
            "AND s.coverage_expected>0 AND s.coverage_eligible>0 "
            "AND s.coverage_missing=0 "
            "AND s.coverage_eligible+s.coverage_excluded="
            "s.coverage_expected "
            "AND s.freshness_basis='effective_complete_session' "
            "AND EXISTS(SELECT 1 FROM market_universe_member m "
            "WHERE m.market_universe_version_id="
            "u.market_universe_version_id)"
        ).fetchall()
        for row in rows:
            try:
                session = date.fromisoformat(
                    str(row["effective_session_date"])
                )
                as_of = datetime.fromisoformat(str(row["as_of_at"]))
                last_success = datetime.fromisoformat(
                    str(row["last_success_at"])
                )
            except ValueError as error:
                raise DisciplineReviewError(
                    "DISCIPLINE_REVIEW_SESSION_TIME_INVALID"
                ) from error
            if (
                as_of.tzinfo is None
                or as_of.utcoffset() is None
                or last_success.tzinfo is None
                or last_success.utcoffset() is None
            ):
                raise DisciplineReviewError(
                    "DISCIPLINE_REVIEW_SESSION_TIME_INVALID"
                )
            if (
                session <= local_date
                and as_of <= requested
                and last_success <= requested
            ):
                complete_dates.add(session)
        if not complete_dates:
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_COMPLETE_SESSION_UNAVAILABLE"
            )
        notes: list[str] = []
        if request.period_kind == "weekly":
            week_start = local_date - timedelta(
                days=local_date.weekday()
            )
            selected = sorted(
                value
                for value in complete_dates
                if week_start <= value <= local_date
            )
            if not selected:
                latest = max(complete_dates)
                fallback_start = latest - timedelta(
                    days=latest.weekday()
                )
                selected = sorted(
                    value
                    for value in complete_dates
                    if fallback_start <= value <= latest
                )
                notes.append("used_latest_available_complete_week")
        else:
            assert request.requested_start_date is not None
            assert request.requested_end_date is not None
            requested_start = date.fromisoformat(
                request.requested_start_date
            )
            requested_end = min(
                date.fromisoformat(request.requested_end_date),
                local_date,
            )
            selected = sorted(
                value
                for value in complete_dates
                if requested_start <= value <= requested_end
            )
            if not selected:
                raise DisciplineReviewError(
                    "DISCIPLINE_REVIEW_COMPLETE_SESSION_UNAVAILABLE"
                )
            if selected[0] != requested_start:
                notes.append("period_start_adjusted_to_complete_session")
            if selected[-1] != requested_end:
                notes.append("period_end_adjusted_to_complete_session")
        period = DisciplineReviewPeriod(
            period_kind=request.period_kind,
            period_start_session=selected[0].isoformat(),
            period_end_session=selected[-1].isoformat(),
        )
        period.validate()
        return period, tuple(notes)

    def collect(
        self,
        account_id: str,
        period: DisciplineReviewPeriod,
    ) -> DisciplineReviewInputs:
        for boundary in (
            period.period_start_session,
            period.period_end_session,
        ):
            if self._connection.execute(
                "SELECT 1 FROM data_snapshot "
                "WHERE effective_session_date=? "
                "AND market_timezone='Asia/Shanghai' "
                "AND quality_status='pass' "
                "AND freshness_basis='effective_complete_session'",
                (boundary,),
            ).fetchone() is None:
                raise DisciplineReviewError(
                    "DISCIPLINE_REVIEW_SESSION_NOT_COMPLETE"
                )
        journal = self._journal.list(
            ListDecisionJournal(account_id)
        )
        actions = tuple(
            action
            for action in journal.actions
            if period.period_start_session
            <= action.occurred_at[:10]
            <= period.period_end_session
        )
        executions = tuple(
            execution
            for execution in journal.executions
            if period.period_start_session
            <= execution.effective_session
            <= period.period_end_session
        )
        active_task_ids = {
            item.decision_task_id for item in actions
        } | {
            item.decision_task_id for item in executions
        }
        tasks = tuple(
            task
            for task in self._tasks.list(
                ListDecisionTasks(account_id)
            )
            if (
                period.period_start_session
                <= task.created_at[:10]
                <= period.period_end_session
                or task.state
                in {
                    DecisionTaskState.OPEN,
                    DecisionTaskState.DEFERRED,
                }
                or task.decision_task_id in active_task_ids
            )
        )
        task_ids = {task.decision_task_id for task in tasks}
        actions = tuple(
            action
            for action in actions
            if action.decision_task_id in task_ids
        )
        executions = tuple(
            execution
            for execution in executions
            if execution.decision_task_id in task_ids
        )
        review_rows = self._connection.execute(
            "SELECT review_run_id FROM manual_portfolio_review_run "
            "WHERE account_id=? AND status IN "
            "('succeeded','succeeded_with_limits') "
            "AND selected_complete_session BETWEEN ? AND ? "
            "ORDER BY selected_complete_session,review_run_id",
            (
                account_id,
                period.period_start_session,
                period.period_end_session,
            ),
        ).fetchall()
        review_run_ids = tuple(
            str(row["review_run_id"]) for row in review_rows
        )
        snapshot_ids = tuple(
            sorted(
                {
                    str(row["account_snapshot_version_id"])
                    for row in self._connection.execute(
                        "SELECT account_snapshot_version_id "
                        "FROM manual_portfolio_review_manifest "
                        "WHERE review_run_id IN ("
                        + ",".join("?" for _ in review_run_ids)
                        + ")",
                        review_run_ids,
                    )
                }
            )
            if review_run_ids
            else ()
        )
        return DisciplineReviewInputs(
            account_id=account_id,
            period=period,
            tasks=tasks,
            actions=actions,
            executions=executions,
            review_run_ids=review_run_ids,
            account_snapshot_version_ids=snapshot_ids,
        )

    def insert_draft(
        self, review: DisciplineReviewVersion
    ) -> DisciplineReviewVersion:
        review.validate()
        if review.status != "draft":
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_NOT_DRAFT"
            )
        with self._writer_lock.acquire(
            f"discipline-review-draft:{review.discipline_review_id}"
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self.by_draft_invocation(
                    str(review.draft_invocation_id)
                )
                if replay is not None:
                    self._connection.rollback()
                    return replay
                latest = self.latest(review.discipline_review_id)
                expected = 1 if latest is None else latest.version_no + 1
                if review.version_no != expected:
                    raise DisciplineReviewError(
                        "DISCIPLINE_REVIEW_VERSION_CONFLICT"
                    )
                self._insert(review)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return review

    def confirmation_replay(
        self, command: ConfirmDisciplineReviewVersion
    ) -> DisciplineReviewVersion | None:
        row = self._connection.execute(
            "SELECT command_name,request_hash,aggregate_id,"
            "revision_or_version_id FROM application_command_receipt "
            "WHERE invocation_id=?",
            (command.invocation_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            row["command_name"] != "discipline_review.confirm@1"
            or row["request_hash"] != canonical_hash(command)
            or row["aggregate_id"] != command.discipline_review_id
        ):
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_INVOCATION_CONFLICT"
            )
        version_id = str(row["revision_or_version_id"])
        prefix = f"{command.discipline_review_id}:v"
        if not version_id.startswith(prefix):
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_RECEIPT_CORRUPT"
            )
        return self.get(
            GetDisciplineReview(
                command.discipline_review_id,
                int(version_id.removeprefix(prefix)),
            )
        )

    def confirm(
        self,
        command: ConfirmDisciplineReviewVersion,
        confirmed: DisciplineReviewVersion,
    ) -> DisciplineReviewVersion:
        confirmed.validate()
        with self._writer_lock.acquire(
            f"discipline-review-confirm:{confirmed.discipline_review_id}"
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                replay = self.confirmation_replay(command)
                if replay is not None:
                    self._connection.rollback()
                    return replay
                latest = self.latest(
                    confirmed.discipline_review_id
                )
                if (
                    latest is None
                    or latest.status != "draft"
                    or latest.version_no
                    != command.expected_version_no
                    or confirmed.version_no != latest.version_no + 1
                ):
                    raise DisciplineReviewError(
                        "DISCIPLINE_REVIEW_VERSION_CONFLICT"
                    )
                version_id = (
                    f"{confirmed.discipline_review_id}:"
                    f"v{confirmed.version_no}"
                )
                self._connection.execute(
                    "INSERT INTO application_command_receipt VALUES("
                    "?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        command.invocation_id,
                        "discipline_review.confirm@1",
                        canonical_hash(command),
                        "DisciplineReviewVersion",
                        confirmed.discipline_review_id,
                        version_id,
                        "confirmed",
                        command.decision_actor,
                        command.interaction_channel,
                        command.transport_actor,
                        command.confirmed_at,
                    ),
                )
                self._insert(confirmed)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return confirmed

    def get(
        self, query: GetDisciplineReview
    ) -> DisciplineReviewVersion:
        if query.version_no is None:
            row = self._connection.execute(
                "SELECT * FROM discipline_review_version "
                "WHERE discipline_review_id=? "
                "ORDER BY version_no DESC LIMIT 1",
                (query.discipline_review_id,),
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT * FROM discipline_review_version "
                "WHERE discipline_review_id=? AND version_no=?",
                (
                    query.discipline_review_id,
                    query.version_no,
                ),
            ).fetchone()
        if row is None:
            raise DisciplineReviewError(
                "DISCIPLINE_REVIEW_NOT_FOUND"
            )
        return self._review(row)

    def confirmed_for_month(
        self, account_id: str, month: str
    ) -> tuple[DisciplineReviewVersion, ...]:
        return tuple(
            self._review(row)
            for row in self._connection.execute(
                "SELECT * FROM discipline_review_version "
                "WHERE account_id=? AND status='confirmed' "
                "AND period_end_session LIKE ? "
                "ORDER BY period_end_session,"
                "discipline_review_id,version_no",
                (account_id, f"{month}-%"),
            )
        )

    def _insert(self, review: DisciplineReviewVersion) -> None:
        self._connection.execute(
            "INSERT INTO discipline_review_version VALUES("
            + ",".join("?" for _ in range(27))
            + ")",
            (
                review.discipline_review_id,
                review.version_no,
                review.supersedes_version_no,
                review.account_id,
                review.period.period_kind,
                review.period.period_start_session,
                review.period.period_end_session,
                review.period.timezone,
                review.status,
                self._json(review.review_run_ids),
                self._json(review.decision_task_ids),
                self._json(review.action_log_entry_ids),
                self._json(review.execution_record_ids),
                self._json(review.plan_version_ids),
                self._json(review.account_snapshot_version_ids),
                self._json(
                    tuple(asdict(item) for item in review.exceptions)
                ),
                self._json(review.overridden_items),
                self._json(review.unrecorded_items),
                self._json(review.unverified_items),
                self._json(review.drift_assessment_ids),
                self._json(review.evidence_gap_summary),
                review.content_hash,
                review.created_at,
                review.draft_invocation_id,
                review.confirmed_at,
                review.confirmation_command_receipt_id,
                review.schema_version,
            ),
        )

    @staticmethod
    def _review(row: sqlite3.Row) -> DisciplineReviewVersion:
        exceptions = tuple(
            DisciplineException(
                exception_id=item["exception_id"],
                kind=item["kind"],
                decision_task_id=item["decision_task_id"],
                action_log_entry_id=item["action_log_entry_id"],
                execution_record_id=item["execution_record_id"],
                evidence_refs=tuple(item["evidence_refs"]),
                content_hash=item["content_hash"],
            )
            for item in json.loads(row["exceptions_json"])
        )
        review = DisciplineReviewVersion(
            discipline_review_id=row["discipline_review_id"],
            version_no=int(row["version_no"]),
            supersedes_version_no=(
                int(row["supersedes_version_no"])
                if row["supersedes_version_no"] is not None
                else None
            ),
            account_id=row["account_id"],
            period=DisciplineReviewPeriod(
                row["period_kind"],
                row["period_start_session"],
                row["period_end_session"],
                row["timezone"],
            ),
            status=row["status"],
            review_run_ids=tuple(
                json.loads(row["review_run_ids_json"])
            ),
            decision_task_ids=tuple(
                json.loads(row["decision_task_ids_json"])
            ),
            action_log_entry_ids=tuple(
                json.loads(row["action_log_entry_ids_json"])
            ),
            execution_record_ids=tuple(
                json.loads(row["execution_record_ids_json"])
            ),
            plan_version_ids=tuple(
                json.loads(row["plan_version_ids_json"])
            ),
            account_snapshot_version_ids=tuple(
                json.loads(
                    row["account_snapshot_version_ids_json"]
                )
            ),
            exceptions=exceptions,
            overridden_items=tuple(
                json.loads(row["overridden_items_json"])
            ),
            unrecorded_items=tuple(
                json.loads(row["unrecorded_items_json"])
            ),
            unverified_items=tuple(
                json.loads(row["unverified_items_json"])
            ),
            drift_assessment_ids=tuple(
                json.loads(row["drift_assessment_ids_json"])
            ),
            evidence_gap_summary=tuple(
                json.loads(row["evidence_gap_summary_json"])
            ),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            draft_invocation_id=row["draft_invocation_id"],
            confirmed_at=row["confirmed_at"],
            confirmation_command_receipt_id=row[
                "confirmation_command_receipt_id"
            ],
            schema_version=row["schema_version"],
        )
        review.validate()
        return review

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


__all__ = ["SQLiteDisciplineReviewRepository"]
