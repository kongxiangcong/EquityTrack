from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from trading_platform.application import (
    ActivateTradePlanVersion,
    CreateTradePlanMaster,
    GetActiveTradePlan,
    GetTradePlanGraph,
    SealTradePlanGraph,
    open_trade_plan,
)
from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.domain.plans import (
    PlanValidationError,
    TradePlanMaster,
    TradePlanMasterId,
    build_plan_version,
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


def _seed_approval(
    connection: sqlite3.Connection,
    *,
    plan_id: str,
    suffix: str,
    content_hash: str,
    activation_intent: str = "confirm_and_enable",
) -> str:
    draft_id = f"plan_draft_{suffix}"
    challenge_id = f"plan_challenge_{suffix}"
    receipt_id = f"user_approval_receipt_{suffix}"
    now = "2026-07-27T00:00:00+08:00"
    connection.execute(
        "INSERT INTO trade_plan_draft VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            draft_id,
            plan_id,
            "account_local",
            "security_600000",
            "strategy_version_trend_hold_break_exit_1",
            None,
            1,
            "open",
            "{}",
            "{}",
            content_hash,
            now,
            now,
            "user:local-user",
            "skill",
            "agent:codex",
        ),
    )
    diff_hash = canonical_hash({"initial": True, "suffix": suffix})
    challenge_hash = canonical_hash(
        {
            "challenge_id": challenge_id,
            "content_hash": content_hash,
            "diff_hash": diff_hash,
        }
    )
    connection.execute(
        "INSERT INTO plan_confirmation_challenge "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            challenge_id,
            "PlanConfirmationChallenge@1",
            plan_id,
            draft_id,
            1,
            content_hash,
            '{"initial":true}',
            diff_hash,
            '["confirm_and_enable","confirm_without_enable"]',
            "user:local-user",
            "skill",
            "agent:codex",
            now,
            "2026-07-28T00:00:00+08:00",
            now,
            receipt_id,
            challenge_hash,
        ),
    )
    receipt_hash = canonical_hash(
        {
            "receipt_id": receipt_id,
            "challenge_id": challenge_id,
            "content_hash": content_hash,
            "activation_intent": activation_intent,
        }
    )
    connection.execute(
        "INSERT INTO user_approval_receipt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            receipt_id,
            "UserApprovalReceipt@1",
            challenge_id,
            plan_id,
            draft_id,
            1,
            content_hash,
            diff_hash,
            activation_intent,
            "user:local-user",
            "skill",
            "agent:codex",
            f"approve:{suffix}",
            now,
            receipt_hash,
        ),
    )
    connection.commit()
    return receipt_id


def _graph(
    *,
    plan_id: str,
    snapshot_id: str,
    suffix: str,
    version_no: int,
    supersedes: str | None,
    receipt_id: str,
) -> object:
    sleeve = _with_hash(
        {
            "sleeve_id": f"core_{suffix}",
            "sleeve_kind": "core",
            "quantity_budget_state": "known",
            "quantity_budget_value": "100",
            "core_floor_state": "known",
            "core_floor_value": "80",
            "max_notional_state": "unknown",
            "max_notional_value": None,
            "max_loss_state": "unknown",
            "max_loss_value": None,
            "grid_constraint_id": None,
        }
    )
    rule = _with_hash(
        {
            "rule_id": f"rule_{suffix}",
            "rule_class": "hard",
            "priority": "ordinary",
            "scope": "core",
            "ast_version": "plan-rule-ast@2",
            "condition": {
                "ast_version": "plan-rule-ast@2",
                "node": "always_false_fixture",
            },
            "candidate_intent": None,
        }
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
    return build_plan_version(
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
        confirmed_at="2026-07-27T00:00:00+08:00",
        user_approval_receipt_id=receipt_id,
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


def _create_master(tasks, seed: str) -> TradePlanMaster:
    identity = TradePlanMasterId.derive(
        "account_local", "security_600000", seed
    )
    result = tasks.execute(
        CreateTradePlanMaster(
            TradePlanMaster(
                plan_id=identity,
                strategy_version_id=(
                    "strategy_version_trend_hold_break_exit_1"
                ),
                lifecycle_status="inactive",
                transition_seq=0,
                created_at="2026-07-27T00:00:00+08:00",
            )
        )
    )
    assert isinstance(result, TradePlanMaster)
    return result


def test_database_allows_one_active_master_per_account_security(
    tmp_path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as tasks:
        first = _create_master(tasks, "first")
        second = _create_master(tasks, "second")
        connection = sqlite3.connect(data_root / "platform.sqlite3")
        first_content_hash = canonical_hash(
            {
                "schema_version": "TradePlanContent@1",
                "purpose": "synthetic-first",
            }
        )
        first_receipt = _seed_approval(
            connection,
            plan_id=first.plan_id.value,
            suffix="first",
            content_hash=first_content_hash,
        )
        first_graph = _graph(
            plan_id=first.plan_id.value,
            snapshot_id=snapshot_id,
            suffix="first",
            version_no=1,
            supersedes=None,
            receipt_id=first_receipt,
        )
        tasks.execute(SealTradePlanGraph(first_graph))

        second_content_hash = canonical_hash(
            {
                "schema_version": "TradePlanContent@1",
                "purpose": "synthetic-second",
            }
        )
        second_receipt = _seed_approval(
            connection,
            plan_id=second.plan_id.value,
            suffix="second",
            content_hash=second_content_hash,
        )
        connection.close()
        second_graph = _graph(
            plan_id=second.plan_id.value,
            snapshot_id=snapshot_id,
            suffix="second",
            version_no=1,
            supersedes=None,
            receipt_id=second_receipt,
        )
        tasks.execute(SealTradePlanGraph(second_graph))

    commands = (
        ActivateTradePlanVersion(
            first.plan_id.value,
            first_graph.version.plan_version_id,
            first_receipt,
            "activate:first",
        ),
        ActivateTradePlanVersion(
            second.plan_id.value,
            second_graph.version.plan_version_id,
            second_receipt,
            "activate:second",
        ),
    )

    def activate(command):
        try:
            with open_trade_plan(data_root) as concurrent_tasks:
                result = concurrent_tasks.execute(command)
            return result.master.plan_id.value
        except PlanValidationError as error:
            return error.code
        except PersistenceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(activate, commands))

    failure_codes = {
        "RUNTIME_BUSY",
        "ACTIVE_MASTER_OWNERSHIP_CONFLICT",
    }
    assert sum(outcome in failure_codes for outcome in outcomes) == 1
    winning_plan_id = next(
        outcome
        for outcome in outcomes
        if outcome not in failure_codes
    )
    losing_index = next(
        index
        for index, outcome in enumerate(outcomes)
        if outcome in failure_codes
    )
    with open_trade_plan(data_root) as tasks:
        if outcomes[losing_index] == "RUNTIME_BUSY":
            with pytest.raises(
                PlanValidationError,
                match="ACTIVE_MASTER_OWNERSHIP_CONFLICT",
            ):
                tasks.execute(commands[losing_index])
        active = tasks.get(
            GetActiveTradePlan("account_local", "security_600000")
        )
        assert active.master.plan_id.value == winning_plan_id


def test_confirmed_plan_graph_rejects_late_mutation(tmp_path) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as tasks:
        master = _create_master(tasks, "sealed")
        connection = sqlite3.connect(data_root / "platform.sqlite3")
        receipt = _seed_approval(
            connection,
            plan_id=master.plan_id.value,
            suffix="sealed",
            content_hash=canonical_hash(
                {
                    "schema_version": "TradePlanContent@1",
                    "purpose": "synthetic-sealed",
                }
            ),
        )
        connection.close()
        graph = _graph(
            plan_id=master.plan_id.value,
            snapshot_id=snapshot_id,
            suffix="sealed",
            version_no=1,
            supersedes=None,
            receipt_id=receipt,
        )
        sealed = tasks.execute(SealTradePlanGraph(graph))
        assert tasks.get(
            GetTradePlanGraph(sealed.version.plan_version_id)
        ) == sealed

    connection = sqlite3.connect(data_root / "platform.sqlite3")
    for statement in (
        "UPDATE trade_plan_version SET content_json='{}'",
        "UPDATE trade_plan_sleeve SET core_floor_value='0'",
        "DELETE FROM trade_plan_rule",
        "INSERT INTO trade_plan_evidence_reference "
        "VALUES('trade_plan_version_sealed',99,'Evidence','late','resolved','late')",
    ):
        with pytest.raises(
            sqlite3.IntegrityError, match="TRADE_PLAN_GRAPH_IMMUTABLE"
        ):
            connection.execute(statement)
    connection.close()


def test_new_activation_preserves_old_version_history(tmp_path) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    with open_trade_plan(data_root) as tasks:
        master = _create_master(tasks, "history")
        connection = sqlite3.connect(data_root / "platform.sqlite3")
        first_receipt = _seed_approval(
            connection,
            plan_id=master.plan_id.value,
            suffix="history_v1",
            content_hash=canonical_hash(
                {
                    "schema_version": "TradePlanContent@1",
                    "purpose": "synthetic-history_v1",
                }
            ),
        )
        first = _graph(
            plan_id=master.plan_id.value,
            snapshot_id=snapshot_id,
            suffix="history_v1",
            version_no=1,
            supersedes=None,
            receipt_id=first_receipt,
        )
        tasks.execute(SealTradePlanGraph(first))
        tasks.execute(
            ActivateTradePlanVersion(
                master.plan_id.value,
                first.version.plan_version_id,
                first_receipt,
                "activate:history:v1",
            )
        )
        old_graph = tasks.get(GetTradePlanGraph(first.version.plan_version_id))
        old_activation = connection.execute(
            "SELECT * FROM plan_activation WHERE plan_version_id=?",
            (first.version.plan_version_id,),
        ).fetchone()

        second_receipt = _seed_approval(
            connection,
            plan_id=master.plan_id.value,
            suffix="history_v2",
            content_hash=canonical_hash(
                {
                    "schema_version": "TradePlanContent@1",
                    "purpose": "synthetic-history_v2",
                }
            ),
        )
        connection.close()
        second = _graph(
            plan_id=master.plan_id.value,
            snapshot_id=snapshot_id,
            suffix="history_v2",
            version_no=2,
            supersedes=first.version.plan_version_id,
            receipt_id=second_receipt,
        )
        tasks.execute(SealTradePlanGraph(second))
        tasks.execute(
            ActivateTradePlanVersion(
                master.plan_id.value,
                second.version.plan_version_id,
                second_receipt,
                "activate:history:v2",
            )
        )
        assert tasks.get(
            GetTradePlanGraph(first.version.plan_version_id)
        ) == old_graph
        active = tasks.get(
            GetActiveTradePlan("account_local", "security_600000")
        )
        assert active.version == second.version

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
        (master.plan_id.value,),
    ).fetchone()[0] == 2
    connection.close()
