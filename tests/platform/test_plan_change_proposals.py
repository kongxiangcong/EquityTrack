from __future__ import annotations

from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import (
    SQLiteOwningAdapterFixture,
)
from tests.platform.test_plan_confirmation import (
    USER,
    _open_trade_plan_test_seams,
)
from tests.platform.test_plan_impact_assessments import (
    _assessment_command,
    _impact_authority,
)
from trading_platform.application import (
    AcceptPlanChangeProposal,
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
    ConfirmTradePlanVersion,
    CreatePlanChangeProposal,
    GetActiveTradePlan,
    IssuePlanConfirmationChallenge,
    PlanCommandActor,
    RejectPlanChangeProposal,
    open_plan_impacts,
    open_application_commands,
    open_read_models,
)
from trading_platform.application.command_envelope import (
    DecisionActor,
    InteractionChannel,
    TransportActor,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.plan_impacts import PlanImpactError


def test_agent_cannot_accept_plan_change_proposal() -> None:
    with pytest.raises(PlanImpactError, match="PROPOSAL_DISPOSITION_DENIED"):
        AcceptPlanChangeProposal(
            invocation_id="proposal:accept:agent-denied",
            proposal_id="proposal",
            expected_revision=1,
            decided_at="2026-07-27T16:00:00+08:00",
            actor=PlanCommandActor(
                "agent:codex", "skill", "agent:codex"
            ),
        ).validate()


def _proposal_authority(tmp_path: Path, suffix: str):
    data_root, run_id, item_id, _ = _impact_authority(tmp_path)
    with open_plan_impacts(data_root) as impacts:
        assessment = impacts.create_assessment(
            _assessment_command(
                run_id,
                item_id,
                invocation_id=f"impact:assessment:{suffix}",
            )
        )
        proposal = impacts.create_proposal(
            CreatePlanChangeProposal(
                invocation_id=f"impact:proposal:{suffix}",
                assessment_id=assessment.assessment_id,
                proposed_content={
                    "schema_version": "TradePlanContent@1",
                    "purpose": f"proposal-{suffix}",
                },
                parameters={"proposal": suffix},
                created_by="agent",
                created_at="2026-07-27T16:40:00+08:00",
            )
        )
    return data_root, assessment, proposal


def test_accept_or_reject_proposal_has_only_draft_side_effects(
    tmp_path: Path,
) -> None:
    data_root, assessment, accepted_source = _proposal_authority(
        tmp_path, "accept"
    )
    with _open_trade_plan_test_seams(data_root) as (plans, _):
        before = plans.get(
            GetActiveTradePlan("account_local", "security_600000")
        )
    accept = AcceptPlanChangeProposal(
        invocation_id="impact:accept",
        proposal_id=accepted_source.proposal_id,
        expected_revision=accepted_source.revision,
        decided_at="2026-07-27T16:45:00+08:00",
        actor=USER,
    )
    with open_plan_impacts(data_root) as impacts:
        accepted = impacts.accept(accept)
        replay = impacts.accept(accept)
        revised_source = impacts.create_proposal(
            CreatePlanChangeProposal(
                invocation_id="impact:proposal:revise",
                assessment_id=assessment.assessment_id,
                proposed_content={
                    "schema_version": "TradePlanContent@1",
                    "purpose": "proposal-revise",
                },
                parameters={"proposal": "revise"},
                created_by="agent",
                created_at="2026-07-27T16:45:30+08:00",
            )
        )
        revised = impacts.accept(
            AcceptPlanChangeProposal(
                invocation_id="impact:accept:revise",
                proposal_id=revised_source.proposal_id,
                expected_revision=revised_source.revision,
                decided_at="2026-07-27T16:46:00+08:00",
                actor=USER,
            )
        )
        rejected_source = impacts.create_proposal(
            CreatePlanChangeProposal(
                invocation_id="impact:proposal:reject",
                assessment_id=assessment.assessment_id,
                proposed_content={
                    "schema_version": "TradePlanContent@1",
                    "purpose": "proposal-reject",
                },
                parameters={"proposal": "reject"},
                created_by="agent",
                created_at="2026-07-27T16:46:00+08:00",
            )
        )
        rejected = impacts.reject(
            RejectPlanChangeProposal(
                invocation_id="impact:reject",
                proposal_id=rejected_source.proposal_id,
                expected_revision=rejected_source.revision,
                decided_at="2026-07-27T16:47:00+08:00",
                actor=USER,
            )
        )
    assert replay == accepted
    assert accepted.status == "accepted"
    assert accepted.accepted_draft_id
    assert revised.accepted_draft_id == accepted.accepted_draft_id
    assert rejected.status == "rejected"
    assert rejected.accepted_draft_id is None
    with _open_trade_plan_test_seams(data_root) as (plans, _):
        after = plans.get(
            GetActiveTradePlan("account_local", "security_600000")
        )
        assert after == before
        challenge = plans.execute(
            IssuePlanConfirmationChallenge(
                invocation_id="impact:challenge",
                draft_id=accepted.accepted_draft_id,
                expected_revision=2,
                activation_intent=ActivationIntent.CONFIRM_ONLY,
                issued_at="2026-07-27T16:50:00+08:00",
                expires_at="2026-07-27T17:50:00+08:00",
                actor=USER,
            )
        )
    assert challenge.canonical_diff.changed_components == ("version",)
    with open_read_models(data_root) as reads:
        detail = reads.plan_detail(
            before.version.plan_id, "2026-07-27T16:51:00+08:00"
        )
    proposal_diff = next(
        item["readable_diff"]
        for item in detail.change_diffs
        if item["change_kind"] == "revision_proposal"
        and item["status"] == "accepted"
        and any(
            change.get("after") == "proposal-revise"
            for change in item["readable_diff"]["modified"]
        )
    )
    public_change = next(
        item
        for item in detail.change_diffs
        if item["change_kind"] == "revision_proposal"
        and item["status"] == "accepted"
        and any(
            change.get("after") == "proposal-revise"
            for change in item["readable_diff"]["modified"]
        )
    )
    assert set(public_change) == {
        "change_kind",
        "status",
        "revision",
        "changed_at",
        "readable_diff",
    }
    assert proposal_diff["added"] == ()
    assert proposal_diff["removed"] == ()
    assert proposal_diff["modified"] == (
        {
            "path": "purpose",
            "before": "confirmation",
            "after": "proposal-revise",
        },
    )
    assert detail.confirmation_state["readable_diff"] == proposal_diff
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM plan_activation"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT status || ':' || revision "
        "FROM trade_plan_draft WHERE draft_id=?",
        (accepted.accepted_draft_id,),
    ).fetchone()[0] == "open:2"
    assert connection.execute(
        "SELECT count(*) FROM plan_confirmation_challenge "
        "WHERE draft_id=?",
        (accepted.accepted_draft_id,),
    ).fetchone()[0] == 1
    connection.close()


def test_stale_source_plan_fails_before_creating_draft(
    tmp_path: Path,
) -> None:
    data_root, assessment, first = _proposal_authority(
        tmp_path, "stale-first"
    )
    with open_plan_impacts(data_root) as impacts:
        stale = impacts.create_proposal(
            CreatePlanChangeProposal(
                invocation_id="impact:proposal:stale-second",
                assessment_id=assessment.assessment_id,
                proposed_content={
                    "schema_version": "TradePlanContent@1",
                    "purpose": "proposal-stale-second",
                },
                parameters={"proposal": "stale-second"},
                created_by="agent",
                created_at="2026-07-27T16:41:00+08:00",
            )
        )
        accepted = impacts.accept(
            AcceptPlanChangeProposal(
                invocation_id="impact:accept:stale-first",
                proposal_id=first.proposal_id,
                expected_revision=first.revision,
                decided_at="2026-07-27T16:42:00+08:00",
                actor=USER,
            )
        )
    with _open_trade_plan_test_seams(data_root) as (plans, _):
        challenge = plans.execute(
            IssuePlanConfirmationChallenge(
                invocation_id="impact:challenge:stale-first",
                draft_id=accepted.accepted_draft_id,
                expected_revision=1,
                activation_intent=(
                    ActivationIntent.CONFIRM_AND_ACTIVATE
                ),
                issued_at="2026-07-27T16:43:00+08:00",
                expires_at="2026-07-27T17:43:00+08:00",
                actor=USER,
            )
        )
        plans.execute(
            ConfirmTradePlanVersion(
                invocation_id="impact:confirm:stale-first",
                challenge_id=challenge.challenge_id,
                expected_revision=challenge.expected_revision,
                expected_draft_hash=challenge.expected_draft_hash,
                expected_diff_hash=(
                    challenge.canonical_diff.content_hash
                ),
                activation_intent=challenge.activation_intent,
                approved_at="2026-07-27T16:44:00+08:00",
                actor=USER,
            )
        )
    with open_plan_impacts(data_root) as impacts:
        with pytest.raises(
            PlanImpactError, match="PROPOSAL_BASE_PLAN_STALE"
        ):
            impacts.accept(
                AcceptPlanChangeProposal(
                    invocation_id="impact:accept:stale",
                    proposal_id=stale.proposal_id,
                    expected_revision=stale.revision,
                    decided_at="2026-07-27T16:45:00+08:00",
                    actor=USER,
                )
            )
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT count(*) FROM trade_plan_draft "
        "WHERE decision_actor=? AND updated_at=?",
        (USER.decision_actor, "2026-07-27T16:45:00+08:00"),
    ).fetchone()[0] == 0
    connection.close()


def test_shared_envelope_requires_user_and_persists_proposal_receipt(
    tmp_path: Path,
) -> None:
    data_root, _, proposal = _proposal_authority(
        tmp_path, "envelope"
    )

    def envelope(actor_type: str, invocation_id: str):
        return ApplicationCommandEnvelopeV1(
            command_name="plan_change_proposal.accept@1",
            invocation_id=invocation_id,
            payload_schema_version="AcceptPlanChangeProposal@1",
            expected_revision=proposal.revision,
            decision_actor=DecisionActor(
                actor_type,
                "local-user" if actor_type == "user" else "codex",
            ),
            interaction_channel=InteractionChannel.CODEX,
            transport_actor=TransportActor("agent", "codex"),
            approval_challenge_id=None,
            payload={
                "proposal_id": proposal.proposal_id,
                "decided_at": "2026-07-27T16:45:00+08:00",
            },
        )

    with open_application_commands(data_root) as dispatcher:
        denied = dispatcher.dispatch(
            envelope("agent", "impact:envelope:denied")
        )
        accepted = dispatcher.dispatch(
            envelope("user", "impact:envelope:accepted")
        )
    assert isinstance(denied, ApplicationCommandFailure)
    assert denied.code == "USER_DECISION_CAPABILITY_REQUIRED"
    assert isinstance(accepted, ApplicationCommandResult)
    assert accepted.result["status"] == "accepted"
    connection = SQLiteOwningAdapterFixture(data_root)
    receipt = connection.execute(
        "SELECT command_name,request_hash,status "
        "FROM application_command_receipt WHERE invocation_id=?",
        (accepted.invocation_id,),
    ).fetchone()
    assert tuple(receipt) == (
        "plan_change_proposal.accept@1",
        accepted.request_hash,
        "accepted",
    )
    connection.close()


def test_failed_disposition_rolls_back_revision_and_replay_recovers(
    tmp_path: Path,
) -> None:
    data_root, _, proposal = _proposal_authority(
        tmp_path, "rollback"
    )
    command = AcceptPlanChangeProposal(
        invocation_id="impact:accept:rollback",
        proposal_id=proposal.proposal_id,
        expected_revision=proposal.revision,
        decided_at="2026-07-27T16:45:00+08:00",
        actor=USER,
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    connection.execute(
        "CREATE TRIGGER inject_proposal_disposition_failure "
        "BEFORE INSERT ON plan_change_proposal "
        "WHEN new.status='accepted' "
        "BEGIN SELECT RAISE(ABORT,'INJECTED_PROPOSAL_FAILURE'); END"
    )
    connection.close()
    with open_plan_impacts(data_root) as impacts:
        with pytest.raises(
            PlanImpactError, match="PROPOSAL_STORAGE_CONFLICT"
        ):
            impacts.accept(command)
    connection = SQLiteOwningAdapterFixture(data_root)
    assert connection.execute(
        "SELECT status FROM plan_change_proposal "
        "WHERE proposal_id=? ORDER BY revision DESC LIMIT 1",
        (proposal.proposal_id,),
    ).fetchone()[0] == "open"
    assert connection.execute(
        "SELECT count(*) FROM application_command_receipt "
        "WHERE invocation_id='impact:accept:rollback'"
    ).fetchone()[0] == 0
    persisted_draft = connection.execute(
        "SELECT draft_id,status FROM trade_plan_draft "
        "WHERE decision_actor=? AND updated_at=?",
        (USER.decision_actor, command.decided_at),
    ).fetchone()
    assert persisted_draft[1] == "open"
    connection.execute("DROP TRIGGER inject_proposal_disposition_failure")
    connection.close()
    with open_plan_impacts(data_root) as impacts:
        recovered = impacts.accept(command)
    assert recovered.status == "accepted"
    assert recovered.accepted_draft_id == persisted_draft[0]
