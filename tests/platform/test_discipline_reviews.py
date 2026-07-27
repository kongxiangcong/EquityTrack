from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_decision_tasks import _actor_fields, _task_review
from tests.platform.test_execution_records import _declare
from tests.platform.test_manual_portfolio_review import _complete_session
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
    ConfirmDisciplineReviewVersion,
    CreateDisciplineReviewDraft,
    DeferDecisionTask,
    GetDisciplineReview,
    ResolveDecisionTask,
    open_decision_tasks,
    open_decision_journal,
    open_discipline_reviews,
    open_application_commands,
)
from trading_platform.domain.decision_tasks import (
    DeferralCondition,
    UserDisposition,
)
from trading_platform.domain.discipline_reviews import (
    DisciplineReviewError,
    DisciplineReviewPeriod,
)


def _draft_command(
    *,
    invocation_id: str,
    period_kind: str = "weekly",
) -> CreateDisciplineReviewDraft:
    return CreateDisciplineReviewDraft(
        invocation_id=invocation_id,
        account_id="account_local",
        period=DisciplineReviewPeriod(
            period_kind=period_kind,
            period_start_session="2026-07-27",
            period_end_session="2026-07-27",
            timezone="Asia/Shanghai",
        ),
        created_at="2026-07-27T19:00:00+08:00",
        decision_actor="agent:codex",
        interaction_channel="skill",
        transport_actor="agent:codex",
    )


def _confirm_command(
    review_id: str,
    version_no: int,
    invocation_id: str,
) -> ConfirmDisciplineReviewVersion:
    return ConfirmDisciplineReviewVersion(
        invocation_id=invocation_id,
        discipline_review_id=review_id,
        expected_version_no=version_no,
        confirmed_at="2026-07-27T20:00:00+08:00",
        decision_actor="user:local-user",
        interaction_channel="skill",
        transport_actor="agent:codex",
    )


def test_overridden_is_identified_and_unrecorded_is_not_skipped(
    tmp_path: Path,
) -> None:
    overridden_root, _, overridden_task = _task_review(
        tmp_path / "overridden",
        suffix="discipline-overridden",
        invocation_id="discipline:overridden-review",
    )
    with open_decision_tasks(overridden_root) as tasks:
        tasks.resolve(
            ResolveDecisionTask(
                invocation_id="discipline:override",
                decision_task_id=overridden_task.decision_task_id,
                disposition=UserDisposition.OVERRIDDEN,
                reason="user chose a different evidenced action",
                occurred_at="2026-07-27T17:00:00+08:00",
                **_actor_fields(),
            )
        )
    with open_discipline_reviews(overridden_root) as reviews:
        overridden = reviews.create_draft(
            _draft_command(invocation_id="discipline:draft:overridden")
        )
    assert overridden.overridden_items == (
        overridden_task.decision_task_id,
    )
    assert overridden.unrecorded_items == ()
    assert {item.kind for item in overridden.exceptions} == {
        "overridden"
    }
    assert overridden.exceptions[0].action_log_entry_id

    unrecorded_root, _, unrecorded_task = _task_review(
        tmp_path / "unrecorded",
        suffix="discipline-unrecorded",
        invocation_id="discipline:unrecorded-review",
    )
    with open_discipline_reviews(unrecorded_root) as reviews:
        unrecorded = reviews.create_draft(
            _draft_command(invocation_id="discipline:draft:unrecorded")
        )
    assert unrecorded.unrecorded_items == (
        unrecorded_task.decision_task_id,
    )
    assert {item.kind for item in unrecorded.exceptions} == {
        "unrecorded"
    }

    skipped_root, _, skipped_task = _task_review(
        tmp_path / "skipped",
        suffix="discipline-skipped",
        invocation_id="discipline:skipped-review",
    )
    with open_decision_tasks(skipped_root) as tasks:
        tasks.resolve(
            ResolveDecisionTask(
                invocation_id="discipline:skip",
                decision_task_id=skipped_task.decision_task_id,
                disposition=UserDisposition.SKIPPED,
                reason="explicit skip",
                occurred_at="2026-07-27T17:00:00+08:00",
                **_actor_fields(),
            )
        )
    with open_discipline_reviews(skipped_root) as reviews:
        skipped = reviews.create_draft(
            _draft_command(invocation_id="discipline:draft:skipped")
        )
    assert skipped.unrecorded_items == ()
    assert skipped.overridden_items == ()
    assert {item.kind for item in skipped.exceptions} == {"skipped"}


def test_weekly_custom_non_friday_and_deferred_evidence(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="discipline-deferred",
        invocation_id="discipline:deferred-review",
    )
    with open_decision_tasks(data_root) as tasks:
        tasks.defer(
            DeferDecisionTask(
                invocation_id="discipline:defer",
                decision_task_id=task.decision_task_id,
                condition=DeferralCondition(
                    "next_manual_review", None
                ),
                occurred_at="2026-07-27T17:00:00+08:00",
                **_actor_fields(),
            )
        )
    with open_discipline_reviews(data_root) as reviews:
        weekly = reviews.create_draft(
            _draft_command(invocation_id="discipline:weekly")
        )
        custom = reviews.create_draft(
            _draft_command(
                invocation_id="discipline:custom",
                period_kind="custom",
            )
        )
    assert weekly.period.period_kind == "weekly"
    assert weekly.period.period_end_session == "2026-07-27"
    assert {item.kind for item in weekly.exceptions} == {"deferred"}
    assert custom.period.period_kind == "custom"
    assert custom.discipline_review_id != weekly.discipline_review_id


def test_user_declared_execution_is_preserved_as_unverified_evidence(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="discipline-unverified",
        invocation_id="discipline:unverified-review",
    )
    with open_decision_journal(data_root) as journal:
        execution = journal.declare(
            _declare(
                task.decision_task_id,
                "discipline:unverified-execution",
            )
        )
    with open_discipline_reviews(data_root) as reviews:
        review = reviews.create_draft(
            _draft_command(
                invocation_id="discipline:unverified-draft"
            )
        )
    assert review.unverified_items == (
        execution.execution_record_id,
    )
    assert {item.kind for item in review.exceptions} == {
        "unverified"
    }


def test_incomplete_period_boundary_fails_before_draft_write(
    tmp_path: Path,
) -> None:
    data_root, _, _ = _task_review(
        tmp_path,
        suffix="discipline-incomplete",
        invocation_id="discipline:incomplete-review",
    )
    command = _draft_command(invocation_id="discipline:incomplete")
    command = CreateDisciplineReviewDraft(
        **{
            **command.__dict__,
            "period": DisciplineReviewPeriod(
                "custom",
                "2026-07-27",
                "2026-07-28",
                "Asia/Shanghai",
            ),
        }
    )
    with open_discipline_reviews(data_root) as reviews, pytest.raises(
        DisciplineReviewError,
        match="DISCIPLINE_REVIEW_SESSION_NOT_COMPLETE",
    ):
        reviews.create_draft(command)
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM discipline_review_version"
    ).fetchone()[0] == 0
    connection.close()


def test_open_task_carries_into_later_complete_session(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="discipline-carry",
        invocation_id="discipline:carry-review",
    )
    _complete_session(data_root, "2026-07-31")
    command = CreateDisciplineReviewDraft(
        invocation_id="discipline:carry-draft",
        account_id="account_local",
        period=DisciplineReviewPeriod(
            "custom",
            "2026-07-31",
            "2026-07-31",
            "Asia/Shanghai",
        ),
        created_at="2026-07-31T19:00:00+08:00",
        decision_actor="agent:codex",
        interaction_channel="skill",
        transport_actor="agent:codex",
    )
    with open_discipline_reviews(data_root) as reviews:
        carried = reviews.create_draft(command)
    assert carried.unrecorded_items == (task.decision_task_id,)


def test_confirmation_and_later_review_append_immutable_versions(
    tmp_path: Path,
) -> None:
    data_root, _, _ = _task_review(
        tmp_path,
        suffix="discipline-version",
        invocation_id="discipline:version-review",
    )
    with open_discipline_reviews(data_root) as reviews:
        draft = reviews.create_draft(
            _draft_command(invocation_id="discipline:version:draft")
        )
        confirmed = reviews.confirm(
            _confirm_command(
                draft.discipline_review_id,
                draft.version_no,
                "discipline:version:confirm",
            )
        )
        replay = reviews.confirm(
            _confirm_command(
                draft.discipline_review_id,
                draft.version_no,
                "discipline:version:confirm",
            )
        )
        later = reviews.create_draft(
            _draft_command(
                invocation_id="discipline:version:later"
            )
        )
        loaded = reviews.get(
            GetDisciplineReview(
                draft.discipline_review_id,
                confirmed.version_no,
            )
        )
    assert replay == confirmed
    assert loaded == confirmed
    assert draft.version_no == 1
    assert confirmed.version_no == 2
    assert later.version_no == 3
    assert confirmed.status == "confirmed"
    assert later.status == "draft"
    connection = SQLiteOwningAdapterFixture(data_root)
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        connection.execute(
            "UPDATE discipline_review_version SET status='superseded' "
            "WHERE discipline_review_id=? AND version_no=?",
            (draft.discipline_review_id, confirmed.version_no),
        )
    connection.close()


def test_shared_envelope_confirms_review_with_same_receipt_hash(
    tmp_path: Path,
) -> None:
    data_root, _, _ = _task_review(
        tmp_path,
        suffix="discipline-envelope",
        invocation_id="discipline:envelope-review",
    )
    with open_discipline_reviews(data_root) as reviews:
        draft = reviews.create_draft(
            _draft_command(
                invocation_id="discipline:envelope-draft"
            )
        )

    def envelope(actor_type: str):
        return ApplicationCommandEnvelopeV1.from_bytes(
            json.dumps(
                {
                    "schema_version": "ApplicationCommandEnvelope@1",
                    "command_name": "discipline_review.confirm@1",
                    "invocation_id": "discipline:envelope-confirm",
                    "payload_schema_version": "ConfirmDisciplineReview@1",
                    "expected_revision": draft.version_no,
                    "decision_actor": {
                        "actor_type": actor_type,
                        "actor_id": (
                            "local-user"
                            if actor_type == "user"
                            else "codex"
                        ),
                    },
                    "interaction_channel": "skill",
                    "transport_actor": {
                        "actor_type": "agent",
                        "actor_id": "codex",
                    },
                    "approval": None,
                    "payload": {
                        "discipline_review_id": (
                            draft.discipline_review_id
                        ),
                        "confirmed_at": (
                            "2026-07-27T20:00:00+08:00"
                        ),
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    with open_application_commands(data_root) as dispatcher:
        denied = dispatcher.dispatch(envelope("agent"))
        result = dispatcher.dispatch(envelope("user"))
        replay = dispatcher.dispatch(envelope("user"))
    assert isinstance(denied, ApplicationCommandFailure)
    assert denied.code == "USER_DECISION_CAPABILITY_REQUIRED"
    assert isinstance(result, ApplicationCommandResult)
    assert replay == result
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT request_hash FROM application_command_receipt "
        "WHERE invocation_id='discipline:envelope-confirm'"
    ).fetchone()[0] == result.request_hash
    connection.close()


def test_monthly_aggregation_uses_confirmed_versions_without_table(
    tmp_path: Path,
) -> None:
    data_root, _, _ = _task_review(
        tmp_path,
        suffix="discipline-month",
        invocation_id="discipline:month-review",
    )
    with open_discipline_reviews(data_root) as reviews:
        confirmed_ids = []
        for kind in ("weekly", "custom"):
            draft = reviews.create_draft(
                _draft_command(
                    invocation_id=f"discipline:month:{kind}:draft",
                    period_kind=kind,
                )
            )
            confirmed = reviews.confirm(
                _confirm_command(
                    draft.discipline_review_id,
                    draft.version_no,
                    f"discipline:month:{kind}:confirm",
                )
            )
            confirmed_ids.append(
                (
                    confirmed.discipline_review_id,
                    confirmed.version_no,
                )
            )
        monthly = reviews.aggregate_month("account_local", "2026-07")
    assert monthly.confirmed_review_versions == tuple(
        sorted(confirmed_ids)
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name LIKE '%monthly%'"
    ).fetchone() is None
    connection.close()
