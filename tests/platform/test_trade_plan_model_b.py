from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from tests.platform.test_plan_confirmation import (
    _open_trade_plan_test_seams,
)

from trading_platform.application import (
    ConfirmTradePlanVersion,
    GetActiveTradePlan,
    GetTradePlanGraph,
    IssuePlanConfirmationChallenge,
    PlanCommandActor,

)
from trading_platform.application.trade_plan_authoring import (
    _OpenTradePlanDrafts,
    _UpsertOpenTradePlanDraft,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.domain.plans import (
    CoreFloor,
    CoreSleeve,
    PlanValidationError,
    TradePlanMaster,
    TradePlanMasterId,
    TradePlanRule,
    build_trade_plan_draft_graph,
    build_trade_plan_draft,
)
from trading_platform.domain.rules import (
    RuleAstV2,
    RuleClass,
    RulePriority,
    RuleScope,
)
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import PersistenceError
from tests.platform.test_account_snapshots import _ready_root
from tests.platform.test_account_snapshots import _draft
from tests.platform.test_estimated_account_state import _confirmed


def test_plan_master_identity_is_owned_by_account_and_security() -> None:
    first = TradePlanMasterId.derive("account_local", "security_600000")
    replay = TradePlanMasterId.derive("account_local", "security_600000")
    other_account = TradePlanMasterId.derive(
        "account_other", "security_600000"
    )
    assert first == replay
    assert first != other_account
    master = TradePlanMaster(
        plan_id=first,
        strategy_version_id="strategy_version_core_plus_grid_1",
        lifecycle_status="inactive",
        transition_seq=0,
        created_at="2026-07-27T00:00:00+08:00",
    )
    master.validate()
    with pytest.raises(PlanValidationError) as missing:
        TradePlanMasterId.derive("", "security_600000")
    assert missing.value.code == "PLAN_OWNERSHIP_REQUIRED"


def test_storage_rejects_a_master_without_account_ownership(tmp_path) -> None:
    data_root = _ready_root(tmp_path)
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO trade_plan_master VALUES(?,?,?,?,?,?,?,?)",
            (
                "master_without_account",
                None,
                "security_600000",
                "strategy_version_core_plus_grid_1",
                "inactive",
                0,
                "2026-07-27T00:00:00+08:00",
                0,
            ),
        )
    connection.close()


def _with_hash(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "content_hash": canonical_hash(payload)}


def _seed_data_snapshot(connection: sqlite3.Connection) -> None:
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


def _graph(
    *,
    plan_id: str,
    snapshot_id: str,
    suffix: str,
    version_no: int,
    supersedes: str | None,
) -> object:
    sleeve = CoreSleeve(
        sleeve_id=f"core_{suffix}",
        quantity_budget=Decimal("100"),
        core_floor=CoreFloor(Decimal("80")),
    )


    rule = TradePlanRule.build(
        rule_id=f"rule_{suffix}",
        rule_class=RuleClass.HARD,
        rule_kind="fixture_guard",
        priority=RulePriority.ORDINARY,
        scope=RuleScope.CORE,
        sleeve_id=f"core_{suffix}",
        effect="record_rule_outcome",
        applies_to="plan",
        candidate_intent=None,
        input_applicability=("account.total_quantity",),
        condition=RuleAstV2(
            node="comparison",
            operand_id="account.total_quantity",
            operator="lt",
            expected=Decimal("0"),
        ),
    )
    evidence = _with_hash(
        {
            "ref_type": "Evidence",
            "ref_id": f"evidence_{suffix}",
            "resolution_status": "resolved",
        }
    )
    content = {
        "schema_version": "TradePlanContent@1",
        "purpose": f"synthetic-{suffix}",
    }
    return build_trade_plan_draft_graph(
        plan_version_id=f"trade_plan_version_{suffix}",
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
        content=content,
        sleeves=(sleeve,),
        rules=(rule,),
        evidence_references=(evidence,),
        adjusted_price_evidence=(),
    )


_PLAN_ACTOR = PlanCommandActor(
    "user:local-user", "skill", "agent:codex"
)


def _prepare_confirmation(
    tasks,
    graph,
    suffix: str,
    intent: ActivationIntent = ActivationIntent.CONFIRM_AND_ACTIVATE,
):
    draft = build_trade_plan_draft(
        draft_id=f"trade_plan_draft_{suffix}",
        account_id="account_local",
        security_id="security_600000",
        proposed_graph=graph,
        parameters={"fixture": suffix},
        created_at="2026-07-27T00:00:00+08:00",
        decision_actor=_PLAN_ACTOR.decision_actor,
        interaction_channel=_PLAN_ACTOR.interaction_channel,
        transport_actor=_PLAN_ACTOR.transport_actor,
    )
    created = _OpenTradePlanDrafts(tasks._store).upsert(
        _UpsertOpenTradePlanDraft(
            invocation_id=f"create:{suffix}",
            account_id=draft.account_id,
            security_id=draft.security_id,
            proposed_graph=draft.proposed_graph,
            parameters=draft.parameters,
            updated_at=draft.updated_at,
            actor=_PLAN_ACTOR,
        )
    )
    challenge = tasks.execute(
        IssuePlanConfirmationChallenge(
            invocation_id=f"challenge:{suffix}",
            draft_id=created.draft_id,
            expected_revision=created.revision,
            activation_intent=intent,
            issued_at="2026-07-27T00:05:00+08:00",
            expires_at="2026-07-27T01:05:00+08:00",
            actor=_PLAN_ACTOR,
        )
    )
    return ConfirmTradePlanVersion(
        invocation_id=f"confirm:{suffix}",
        challenge_id=challenge.challenge_id,
        expected_revision=challenge.expected_revision,
        expected_draft_hash=challenge.expected_draft_hash,
        expected_diff_hash=challenge.canonical_diff.content_hash,
        activation_intent=intent,
        approved_at="2026-07-27T00:10:00+08:00",
        actor=_PLAN_ACTOR,
    )


def _confirm_graph(
    tasks,
    graph,
    suffix: str,
    intent: ActivationIntent = ActivationIntent.CONFIRM_AND_ACTIVATE,
):
    return tasks.execute(
        _prepare_confirmation(tasks, graph, suffix, intent)
    )


def _authority_root(tmp_path) -> tuple[object, str]:
    data_root = _ready_root(tmp_path)
    confirmed = _confirmed(
        data_root,
        _draft(),
        create_invocation="model-b:snapshot:create",
        confirm_invocation="model-b:snapshot:confirm",
    )
    assert isinstance(confirmed, AccountSnapshotVersion)
    connection = sqlite3.connect(data_root / "platform.sqlite3")
    _seed_data_snapshot(connection)
    connection.commit()
    connection.close()
    return data_root, confirmed.account_snapshot_version_id



def test_confirmed_plan_graph_rejects_late_mutation(tmp_path) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with _open_trade_plan_test_seams(data_root) as (tasks, _):
        plan_id = TradePlanMasterId.derive(
            "account_local", "security_600000", "sealed"
        ).value
        graph = _graph(
            plan_id=plan_id,
            snapshot_id=snapshot_id,
            suffix="sealed",
            version_no=1,
            supersedes=None,
        )
        sealed = _confirm_graph(tasks, graph, "sealed").graph
        assert tasks.get(
            GetTradePlanGraph(sealed.version.plan_version_id)
        ) == sealed

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    for statement in (
        "UPDATE trade_plan_version SET content_json='{}'",
        "UPDATE trade_plan_sleeve SET core_floor_value='0'",
        "DELETE FROM trade_plan_rule",
        "INSERT INTO trade_plan_evidence_reference "
        "VALUES('trade_plan_version_sealed',99,'Evidence','late','resolved','{}','late')",
    ):
        with pytest.raises(
            sqlite3.IntegrityError, match="TRADE_PLAN_GRAPH_IMMUTABLE"
        ):
            connection.execute(statement)
    connection.close()


def test_new_activation_preserves_old_version_history(tmp_path) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with _open_trade_plan_test_seams(data_root) as (tasks, _):
        plan_id = TradePlanMasterId.derive(
            "account_local", "security_600000", "history"
        ).value
        first = _graph(
            plan_id=plan_id,
            snapshot_id=snapshot_id,
            suffix="history_v1",
            version_no=1,
            supersedes=None,
        )
        first_command = _prepare_confirmation(
            tasks, first, "history_v1"
        )
        first_result = tasks.execute(first_command)
        first = first_result.graph
        old_graph = tasks.get(GetTradePlanGraph(first.version.plan_version_id))
        connection = sqlite3.connect(data_root / "platform.sqlite3")
        old_activation = connection.execute(
            "SELECT * FROM plan_activation WHERE plan_version_id=?",
            (first.version.plan_version_id,),
        ).fetchone()

        connection.close()
        second = _graph(
            plan_id=plan_id,
            snapshot_id=snapshot_id,
            suffix="history_v2",
            version_no=2,
            supersedes=first.version.plan_version_id,
        )
        second = _confirm_graph(
            tasks, second, "history_v2"
        ).graph
        assert tasks.get(
            GetTradePlanGraph(first.version.plan_version_id)
        ) == old_graph
        active = tasks.get(
            GetActiveTradePlan("account_local", "security_600000")
        )
        assert active.version == second.version
        replay = tasks.execute(first_command)
        assert replay.graph == old_graph
        assert replay.active_plan.activation.ended_at is not None

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    after = connection.execute(
        "SELECT activation_id,plan_id,plan_version_id,activated_event_id,"
        "activated_at,user_approval_receipt_id,command_invocation_id "
        "FROM plan_activation WHERE plan_version_id=?",
        (first.version.plan_version_id,),
    ).fetchone()
    assert after == (
        old_activation[0],
        old_activation[1],
        old_activation[2],
        old_activation[3],
        old_activation[4],
        old_activation[8],
        old_activation[9],
    )
    assert connection.execute(
        "SELECT count(*) FROM plan_activation WHERE plan_id=?",
        (plan_id,),
    ).fetchone()[0] == 2
    connection.close()
