from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
import sqlite3

import pytest

from tests.platform.owning_adapter_fixture import (
    SQLiteOwningAdapterFixture,
)
from tests.platform.test_account_snapshots import _draft as _account_draft
from tests.platform.test_account_snapshots import _ready_root
from tests.platform.test_estimated_account_state import _confirmed
from trading_platform.application import (
    ConfirmTradePlanVersion,
    GetActiveTradePlan,
    IssuePlanConfirmationChallenge,
    PlanCommandActor,
    RejectTradePlanDraft,
)
from trading_platform.application.bootstrap import _store
from trading_platform.application.trade_plan_authoring import (
    TradePlanTasks,
    _OpenTradePlanDrafts,
    _UpsertOpenTradePlanDraft,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.persistence.plans import SQLiteTradePlanRepository
from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.domain.plans import (
    CoreFloor,
    CoreSleeve,
    PlanValidationError,
    TradePlanMasterId,
    build_trade_plan_draft_graph,
    build_trade_plan_draft,
)


USER = PlanCommandActor("user:local", "skill", "agent:codex")
AGENT = PlanCommandActor("agent:codex", "skill", "agent:codex")


@contextmanager
def _open_trade_plan_test_seams(data_root):
    with _store(data_root) as store:
        repository = SQLiteTradePlanRepository(
            store.connection, store.writer_lock
        )
        yield (
            TradePlanTasks(repository),
            _OpenTradePlanDrafts(repository),
        )


def _upsert_draft(drafts, draft, invocation_id: str):
    return drafts.upsert(
        _UpsertOpenTradePlanDraft(
            invocation_id=invocation_id,
            account_id=draft.account_id,
            security_id=draft.security_id,
            proposed_graph=draft.proposed_graph,
            parameters=draft.parameters,
            updated_at=draft.updated_at,
            actor=USER,
        )
    )


def _authority_root(tmp_path):
    data_root = _ready_root(tmp_path)
    confirmed = _confirmed(
        data_root,
        _account_draft(),
        create_invocation="confirmation:snapshot:create",
        confirm_invocation="confirmation:snapshot:confirm",
    )
    assert isinstance(confirmed, AccountSnapshotVersion)
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    connection.execute(
        "INSERT INTO query_policy_record VALUES(?,?,?,?,?)",
        (
            "query_policy_plan_fixture@1",
            "QueryPolicy@1",
            "query-policy-plan-hash",
            "{}",
            "2026-07-27T00:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO source_policy_record VALUES(?,?,?,?,?)",
        (
            "source_policy_plan_fixture@1",
            "SourcePolicy@1",
            "source-policy-plan-hash",
            "{}",
            "2026-07-27T00:00:00+08:00",
        ),
    )
    connection.execute(
        "INSERT INTO data_snapshot VALUES("
        "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "data_snapshot_plan_fixture",
            "security_600000",
            "research",
            "2026-07-27",
            "2026-07-24",
            "2026-07-24T15:00:00+08:00",
            "Asia/Shanghai",
            "calendar_fixture@1",
            "query_policy_plan_fixture@1",
            "source_policy_plan_fixture@1",
            "freshness_fixture@1",
            "membership-plan",
            "valid",
            "pass",
            0,
            0,
            0,
            0,
            0,
            "fixture",
            "2026-07-24T15:00:00+08:00",
        ),
    )
    connection.commit()
    connection.close()
    return data_root, confirmed.account_snapshot_version_id


def _graph(
    snapshot_id: str,
    *,
    plan_id: str,
    version_id: str,
    version_no: int = 1,
    supersedes: str | None = None,
    purpose: str = "confirmation",
):
    return build_trade_plan_draft_graph(
        plan_version_id=version_id,
        plan_id=plan_id,
        version_no=version_no,
        supersedes_version_id=supersedes,
        strategy_version_id="strategy_version_trend_hold_break_exit_1",
        investment_thesis_version_id=None,
        account_snapshot_version_id=snapshot_id,
        data_snapshot_id="data_snapshot_plan_fixture",
        horizon_start="2026-07-27",
        horizon_end="2026-10-27",
        review_by="2026-08-27",
        risk_policy_version_id=None,
        metric_catalog_version="metric-catalog@2",
        evaluator_policy_version="plan-evaluator@2",
        content={
            "schema_version": "TradePlanContent@1",
            "purpose": purpose,
        },
        sleeves=(
            CoreSleeve(
                sleeve_id="core",
                quantity_budget=Decimal("100"),
                core_floor=CoreFloor(Decimal("80")),
            ),
        ),
        rules=(),
        evidence_references=(),
        adjusted_price_evidence=(),
    )


def _draft(
    snapshot_id: str,
    *,
    suffix: str,
    version_no: int = 1,
    supersedes: str | None = None,
    purpose: str = "confirmation",
):
    plan_id = TradePlanMasterId.derive(
        "account_local", "security_600000", "confirmation-plan"
    ).value
    graph = _graph(
        snapshot_id,
        plan_id=plan_id,
        version_id=f"trade_plan_version_{suffix}",
        version_no=version_no,
        supersedes=supersedes,
        purpose=purpose,
    )
    return build_trade_plan_draft(
        draft_id=f"trade_plan_draft_{suffix}",
        account_id="account_local",
        security_id="security_600000",
        proposed_graph=graph,
        parameters={"purpose": purpose},
        created_at="2026-07-27T01:00:00+08:00",
        decision_actor=USER.decision_actor,
        interaction_channel=USER.interaction_channel,
        transport_actor=USER.transport_actor,
    )


def _create_and_challenge(tasks, drafts, draft, suffix: str, intent):
    created = _upsert_draft(drafts, draft, f"create:{suffix}")
    challenge = tasks.execute(
        IssuePlanConfirmationChallenge(
            invocation_id=f"challenge:{suffix}",
            draft_id=created.draft_id,
            expected_revision=created.revision,
            activation_intent=intent,
            issued_at="2026-07-27T01:05:00+08:00",
            expires_at="2026-07-27T02:05:00+08:00",
            actor=USER,
        )
    )
    return created, challenge


def _confirm(tasks, challenge, suffix: str, actor=USER):
    return tasks.execute(
        ConfirmTradePlanVersion(
            invocation_id=f"confirm:{suffix}",
            challenge_id=challenge.challenge_id,
            expected_revision=challenge.expected_revision,
            expected_draft_hash=challenge.expected_draft_hash,
            expected_diff_hash=challenge.canonical_diff.content_hash,
            activation_intent=challenge.activation_intent,
            approved_at="2026-07-27T01:10:00+08:00",
            actor=actor,
        )
    )


def test_agent_denied_and_stale_or_mismatched_challenge_rejected(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with _open_trade_plan_test_seams(data_root) as (tasks, drafts):
        draft, challenge = _create_and_challenge(
            tasks,
            drafts,
            _draft(snapshot_id, suffix="denial"),
            "denial",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        with pytest.raises(
            PlanValidationError, match="PLAN_COMMAND_ACTOR_INVALID"
        ):
            _confirm(tasks, challenge, "agent-denied", AGENT)
        with pytest.raises(
            PlanValidationError,
            match="PLAN_CONFIRMATION_CHALLENGE_MISMATCH",
        ):
            tasks.execute(
                ConfirmTradePlanVersion(
                    invocation_id="confirm:stale",
                    challenge_id=challenge.challenge_id,
                    expected_revision=draft.revision + 1,
                    expected_draft_hash=challenge.expected_draft_hash,
                    expected_diff_hash=(
                        challenge.canonical_diff.content_hash
                    ),
                    activation_intent=(
                        ActivationIntent.CONFIRM_AND_ACTIVATE
                    ),
                    approved_at="2026-07-27T01:10:00+08:00",
                    actor=USER,
                )
            )
        base_confirmation = ConfirmTradePlanVersion(
            invocation_id="confirm:mismatch",
            challenge_id=challenge.challenge_id,
            expected_revision=challenge.expected_revision,
            expected_draft_hash=challenge.expected_draft_hash,
            expected_diff_hash=challenge.canonical_diff.content_hash,
            activation_intent=challenge.activation_intent,
            approved_at="2026-07-27T01:10:00+08:00",
            actor=USER,
        )
        mismatches = (
            replace(
                base_confirmation,
                invocation_id="confirm:hash-mismatch",
                expected_draft_hash="wrong-draft-hash",
            ),
            replace(
                base_confirmation,
                invocation_id="confirm:diff-mismatch",
                expected_diff_hash="wrong-diff-hash",
            ),
            replace(
                base_confirmation,
                invocation_id="confirm:intent-mismatch",
                activation_intent=ActivationIntent.CONFIRM_ONLY,
            ),
        )
        for mismatch in mismatches:
            with pytest.raises(
                PlanValidationError,
                match="PLAN_CONFIRMATION_CHALLENGE_MISMATCH",
            ):
                tasks.execute(mismatch)
        revised_graph = _graph(
            snapshot_id,
            plan_id=str(draft.plan_id),
            version_id=draft.proposed_graph.version.plan_version_id,
            purpose="revised",
        )
        revised = drafts.upsert(
            _UpsertOpenTradePlanDraft(
                invocation_id="revise:denial",
                account_id=draft.account_id,
                security_id=draft.security_id,
                proposed_graph=revised_graph,
                parameters={"purpose": "revised"},
                updated_at="2026-07-27T01:20:00+08:00",
                actor=USER,
            )
        )
        assert revised.revision == 2
        with pytest.raises(
            PlanValidationError,
            match="PLAN_CHALLENGE_NOT_ISSUED",
        ):
            _confirm(tasks, challenge, "superseded")
        revised_challenge = tasks.execute(
            IssuePlanConfirmationChallenge(
                invocation_id="challenge:expired",
                draft_id=revised.draft_id,
                expected_revision=revised.revision,
                activation_intent=(
                    ActivationIntent.CONFIRM_AND_ACTIVATE
                ),
                issued_at="2026-07-27T01:25:00+08:00",
                expires_at="2026-07-27T02:25:00+08:00",
                actor=USER,
            )
        )
        with pytest.raises(
            PlanValidationError, match="PLAN_CHALLENGE_EXPIRED"
        ):
            tasks.execute(
                ConfirmTradePlanVersion(
                    invocation_id="confirm:expired",
                    challenge_id=revised_challenge.challenge_id,
                    expected_revision=(
                        revised_challenge.expected_revision
                    ),
                    expected_draft_hash=(
                        revised_challenge.expected_draft_hash
                    ),
                    expected_diff_hash=(
                        revised_challenge.canonical_diff.content_hash
                    ),
                    activation_intent=(
                        revised_challenge.activation_intent
                    ),
                    approved_at="2026-07-27T03:10:00+08:00",
                    actor=USER,
                )
            )


def test_confirm_and_enable_emits_events_and_receipt_atomically(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with _open_trade_plan_test_seams(data_root) as (tasks, drafts):
        draft, challenge = _create_and_challenge(
            tasks,
            drafts,
            _draft(snapshot_id, suffix="atomic"),
            "atomic",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        assert draft.proposed_graph.schema_version == "TradePlanDraftGraph@1"
        assert (
            draft.proposed_graph.version.schema_version
            == "ProposedTradePlanVersion@1"
        )
        assert not hasattr(draft.proposed_graph.version, "confirmed_at")
        assert not hasattr(
            draft.proposed_graph.version, "user_approval_receipt_id"
        )
        result = _confirm(tasks, challenge, "atomic")
        replay = _confirm(tasks, challenge, "atomic")
        assert replay == result
        assert result.active_plan is not None
        assert result.graph.schema_version == "TradePlanGraph@1"
        assert result.graph.version.confirmed_at == (
            "2026-07-27T01:10:00+08:00"
        )
        assert result.graph.version.user_approval_receipt_id == (
            result.receipt.approval_receipt_id
        )
        assert result.active_plan.version == result.graph.version
        assert result.receipt.approved_graph_seal_hash == (
            result.graph.version.graph_seal_hash
        )
        with pytest.raises(
            PlanValidationError, match="PLAN_CHALLENGE_NOT_ISSUED|"
            "PLAN_CONFIRMATION_CHALLENGE_MISMATCH"
        ):
            _confirm(tasks, challenge, "consumed")
        with pytest.raises(PlanValidationError, match="INVOCATION_CONFLICT"):
            tasks.execute(
                replace(
                    ConfirmTradePlanVersion(
                        invocation_id="confirm:atomic",
                        challenge_id=challenge.challenge_id,
                        expected_revision=challenge.expected_revision,
                        expected_draft_hash=(
                            challenge.expected_draft_hash
                        ),
                        expected_diff_hash=(
                            challenge.canonical_diff.content_hash
                        ),
                        activation_intent=challenge.activation_intent,
                        approved_at="2026-07-27T01:10:00+08:00",
                        actor=USER,
                    ),
                    expected_draft_hash="different-request",
                )
            )

    store = SQLiteOwningAdapterFixture(data_root)
    events = tuple(
        row[0]
        for row in store.execute(
            "SELECT event_type FROM application_event "
            "WHERE aggregate_id=? ORDER BY occurred_at,event_type",
            (result.graph.version.plan_id,),
        )
    )
    assert events == ("PlanActivated", "PlanVersionConfirmed")
    assert store.execute(
        "SELECT count(*) FROM user_approval_receipt "
        "WHERE user_approval_receipt_id=?",
        (result.receipt.approval_receipt_id,),
    ).fetchone()[0] == 1
    with pytest.raises(
        sqlite3.IntegrityError,
        match="PLAN_CONFIRMATION_CHALLENGE_IMMUTABLE",
    ):
        store.execute(
            "UPDATE plan_confirmation_challenge "
            "SET expected_content_hash='tampered' "
            "WHERE challenge_id=?",
            (challenge.challenge_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        store.execute(
            "INSERT INTO user_approval_receipt "
            "SELECT 'duplicate_receipt',schema_version,challenge_id,"
            "plan_id,draft_id,approved_revision,approved_draft_hash,"
            "approved_graph_seal_hash,approved_diff_hash,"
            "activation_intent,decision_actor,interaction_channel,"
            "transport_actor,'duplicate:invocation',approved_at,"
            "'duplicate-content-hash' "
            "FROM user_approval_receipt "
            "WHERE user_approval_receipt_id=?",
            (result.receipt.approval_receipt_id,),
        )
    store.close()


def test_confirmation_failure_rolls_back_receipt_events_and_graph(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with _open_trade_plan_test_seams(data_root) as (tasks, drafts):
        draft, challenge = _create_and_challenge(
            tasks,
            drafts,
            _draft(snapshot_id, suffix="rollback"),
            "rollback",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
    fixture = SQLiteOwningAdapterFixture(data_root)
    fixture.execute(
        "CREATE TRIGGER inject_confirmation_failure "
        "BEFORE INSERT ON application_event "
        "WHEN NEW.event_type='PlanActivated' "
        "BEGIN SELECT RAISE(ABORT,'INJECTED_CONFIRMATION_FAILURE'); END"
    )
    with _open_trade_plan_test_seams(data_root) as (tasks, drafts):
        with pytest.raises(
            PlanValidationError,
            match="PLAN_CONFIRMATION_STORAGE_CONFLICT",
        ):
            _confirm(tasks, challenge, "rollback")
    assert fixture.execute(
        "SELECT count(*) FROM user_approval_receipt "
        "WHERE command_invocation_id='confirm:rollback'"
    ).fetchone()[0] == 0
    assert fixture.execute(
        "SELECT count(*) FROM trade_plan_version "
        "WHERE plan_version_id=?",
        (draft.proposed_graph.version.plan_version_id,),
    ).fetchone()[0] == 0
    assert fixture.execute(
        "SELECT count(*) FROM application_event "
        "WHERE aggregate_id=? AND event_type IN "
        "('PlanVersionConfirmed','PlanActivated')",
        (str(draft.plan_id),),
    ).fetchone()[0] == 0
    assert fixture.execute(
        "SELECT status FROM trade_plan_draft WHERE draft_id=?",
        (draft.draft_id,),
    ).fetchone()[0] == "open"
    assert fixture.execute(
        "SELECT status FROM plan_confirmation_challenge "
        "WHERE challenge_id=?",
        (challenge.challenge_id,),
    ).fetchone()[0] == "issued"
    fixture.execute("DROP TRIGGER inject_confirmation_failure")
    fixture.close()


def test_confirm_only_and_rejected_draft_leave_active_slot_unchanged(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with _open_trade_plan_test_seams(data_root) as (tasks, drafts):
        _, first_challenge = _create_and_challenge(
            tasks,
            drafts,
            _draft(snapshot_id, suffix="active"),
            "active",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        first = _confirm(tasks, first_challenge, "active")
        before = tasks.get(
            GetActiveTradePlan("account_local", "security_600000")
        )
        second_draft = _draft(
            snapshot_id,
            suffix="confirm_only",
            version_no=2,
            supersedes=first.graph.version.plan_version_id,
            purpose="confirm-only",
        )
        _, second_challenge = _create_and_challenge(
            tasks,
            drafts,
            second_draft,
            "confirm-only",
            ActivationIntent.CONFIRM_ONLY,
        )
        second = _confirm(tasks, second_challenge, "confirm-only")
        assert second.active_plan is None
        assert tasks.get(
            GetActiveTradePlan("account_local", "security_600000")
        ) == before

        rejected_draft = _draft(
            snapshot_id,
            suffix="rejected",
            version_no=3,
            supersedes=second.graph.version.plan_version_id,
            purpose="rejected",
        )
        created = _upsert_draft(
            drafts, rejected_draft, "create:rejected"
        )
        rejected = tasks.execute(
            RejectTradePlanDraft(
                invocation_id="reject:draft",
                draft_id=created.draft_id,
                expected_revision=created.revision,
                rejected_at="2026-07-27T01:30:00+08:00",
                actor=USER,
            )
        )
        assert rejected.draft_id == created.draft_id
        assert tasks.get(
            GetActiveTradePlan("account_local", "security_600000")
        ) == before
