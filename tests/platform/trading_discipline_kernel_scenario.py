from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from trading_platform.application import (
    AcceptPlanChangeProposal,
    ConfirmAccountSnapshot,
    ConfirmDisciplineReviewVersion,
    ConfirmTradePlanVersion,
    CreateAccountSnapshotDraft,
    CreateDisciplineReviewDraft,
    CreatePlanChangeProposal,
    CreatePlanImpactAssessment,
    CreateTradePlanDraft,
    DeclareExecution,
    DeferDecisionTask,
    GetActiveTradePlan,
    IssuePlanConfirmationChallenge,
    ListDecisionTasks,
    PlanCommandActor,
    RejectPlanChangeProposal,
    ReopenDecisionTasks,
    ResolveDecisionTask,
    StartManualPortfolioReview,
    open_account_snapshot_commands,
    open_decision_journal,
    open_decision_tasks,
    open_discipline_reviews,
    open_manual_portfolio_review,
    open_plan_impacts,
    open_trade_plan,
)
from trading_platform.domain.account_snapshots import (
    AccountSnapshotDraft,
    AccountSnapshotError,
    AccountSnapshotPosition,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.decision_tasks import (
    DeferralCondition,
    UserDisposition,
)
from trading_platform.domain.discipline_reviews import (
    DisciplineReviewPeriod,
)
from trading_platform.domain.plans import (
    CoreFloor,
    CoreSleeve,
    GridSleeve,
    PlanValidationError,
    TradePlanMasterId,
    TradePlanRule,
    build_plan_version,
    build_trade_plan_draft,
)
from trading_platform.domain.rules import (
    GridConstraint,
    RuleAstV2,
    RuleClass,
    RulePriority,
    RuleScope,
)
from trading_platform.operations import PlatformOperations


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "trading_discipline_kernel"
USER = PlanCommandActor("user:local-user", "skill", "agent:codex")
AGENT = PlanCommandActor("agent:codex", "skill", "agent:codex")


@dataclass(frozen=True)
class KernelScenario:
    data_root: Path
    snapshot_version_id: str
    first_plan_version_ids: tuple[str, str]
    current_plan_version_ids: tuple[str, str]
    review_run_ids: tuple[str, str]
    first_task_id: str
    second_task_id: str
    execution_record_id: str
    discipline_review_version_id: str
    accepted_draft_id: str
    proposal_rejected: bool
    agent_snapshot_denied: bool
    agent_plan_denied: bool
    replay_execution_equal: bool
    steps: tuple[str, ...]


def build_kernel_scenario(data_root: Path) -> KernelScenario:
    fixture = json.loads(
        (FIXTURE_ROOT / "account.json").read_text(encoding="utf-8")
    )
    PlatformOperations(data_root, ROOT / "migrations").bootstrap()
    adapter = SQLiteOwningAdapterFixture(data_root)
    adapter.execute(
        "INSERT INTO account VALUES(?,?,?,?,?)",
        (
            fixture["account_id"],
            "local",
            fixture["currency"],
            "2026-07-27T00:00:00+00:00",
            "synthetic_fixture",
        ),
    )
    for position in fixture["positions"]:
        adapter.execute(
            "INSERT INTO security VALUES(?,?)",
            (position["security_id"], "CNY"),
        )
    adapter.close()

    account_draft = AccountSnapshotDraft(
        draft_id="tdk_account_draft_1",
        account_id="account_local",
        revision=1,
        status="open",
        source_kind="user_declared",
        redacted_source_ref="synthetic-fixture",
        as_of_at=fixture["as_of_at"],
        as_of_precision="date",
        timezone="Asia/Shanghai",
        session_semantics="complete_session",
        currency="CNY",
        cash_state=fixture["cash"]["state"],
        cash_value=fixture["cash"]["value"],
        positions=tuple(
            AccountSnapshotPosition(
                security_id=item["security_id"],
                total_quantity=item["total_quantity"],
                available_quantity_state=item["available_quantity"]["state"],
                available_quantity_value=item["available_quantity"]["value"],
            )
            for item in fixture["positions"]
        ),
        created_by="agent:codex",
    )
    with open_account_snapshot_commands(data_root) as accounts:
        created = accounts.execute(
            CreateAccountSnapshotDraft(
                invocation_id="tdk:snapshot:create",
                draft=account_draft,
                decision_actor_type="agent",
                decision_actor_id="codex",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )
        denied = False
        try:
            accounts.execute(
                ConfirmAccountSnapshot(
                    invocation_id="tdk:snapshot:agent-denied",
                    draft_id=created.draft_id,
                    expected_revision=created.revision,
                    decision_actor_type="agent",
                    decision_actor_id="codex",
                    interaction_channel="skill",
                    transport_actor_type="agent",
                    transport_actor_id="codex",
                )
            )
        except AccountSnapshotError as error:
            denied = str(error) == "USER_CONFIRMATION_CAPABILITY_REQUIRED"
        snapshot = accounts.execute(
            ConfirmAccountSnapshot(
                invocation_id="tdk:snapshot:confirm",
                draft_id=created.draft_id,
                expected_revision=created.revision,
                decision_actor_type="user",
                decision_actor_id="local-user",
                interaction_channel="skill",
                transport_actor_type="agent",
                transport_actor_id="codex",
            )
        )

    _insert_data_authority(data_root)
    plan_drafts = (
        _plan_draft(
            snapshot.account_snapshot_version_id,
            "security_002897_sz",
            "002897",
            grid=False,
        ),
        _plan_draft(
            snapshot.account_snapshot_version_id,
            "security_600183_sh",
            "600183",
            grid=True,
        ),
    )
    plan_denied = False
    first_versions: list[str] = []
    with open_trade_plan(data_root) as plans:
        for index, draft in enumerate(plan_drafts, start=1):
            created_plan = plans.execute(
                CreateTradePlanDraft(
                    f"tdk:plan:create:{index}",
                    draft,
                    USER,
                )
            )
            challenge = plans.execute(
                IssuePlanConfirmationChallenge(
                    invocation_id=f"tdk:plan:challenge:{index}",
                    draft_id=draft.draft_id,
                    expected_revision=created_plan.revision,
                    activation_intent=ActivationIntent.CONFIRM_AND_ACTIVATE,
                    issued_at="2026-07-27T01:05:00+08:00",
                    expires_at="2026-07-27T02:05:00+08:00",
                    actor=USER,
                )
            )
            command = ConfirmTradePlanVersion(
                invocation_id=f"tdk:plan:confirm:{index}",
                challenge_id=challenge.challenge_id,
                expected_revision=challenge.expected_revision,
                expected_draft_hash=challenge.expected_draft_hash,
                expected_diff_hash=challenge.canonical_diff.content_hash,
                activation_intent=challenge.activation_intent,
                approved_at="2026-07-27T01:10:00+08:00",
                actor=USER,
            )
            if index == 1:
                try:
                    plans.execute(
                        replace(
                            command,
                            invocation_id="tdk:plan:agent-denied",
                            actor=AGENT,
                        )
                    )
                except PlanValidationError as error:
                    plan_denied = error.code == "PLAN_COMMAND_ACTOR_INVALID"
            confirmed = plans.execute(command)
            first_versions.append(
                confirmed.graph.version.plan_version_id
            )

    first_review, first_task = _review_session(
        data_root,
        session="2026-07-27",
        invocation="tdk:review:first",
        first_window_start="2026-07-24",
        plan_versions=tuple(first_versions),
        grid_rule_id="grid-rule-1",
    )
    with open_decision_tasks(data_root) as tasks:
        deferred = tasks.defer(
            DeferDecisionTask(
                invocation_id="tdk:task:defer",
                decision_task_id=first_task,
                condition=DeferralCondition(
                    "specific_date_or_session",
                    "2026-07-31",
                ),
                occurred_at="2026-07-27T17:00:00+08:00",
                decision_actor="user:local-user",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )
        reopened = tasks.reopen(
            ReopenDecisionTasks(
                trigger_kind="date_or_session",
                trigger_value="2026-07-31",
                occurred_at="2026-07-31T09:00:00+08:00",
                decision_actor="system:workflow",
                interaction_channel="workflow",
                transport_actor="adapter:decision-tasks",
            )
        )
        tasks.resolve(
            ResolveDecisionTask(
                invocation_id="tdk:task:override",
                decision_task_id=first_task,
                disposition=UserDisposition.OVERRIDDEN,
                reason="synthetic user selected an evidenced alternative",
                occurred_at="2026-07-31T09:30:00+08:00",
                decision_actor="user:local-user",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )
    assert deferred.state.value == "deferred"
    assert [item.decision_task_id for item in reopened] == [first_task]

    with open_discipline_reviews(data_root) as reviews:
        discipline = reviews.create_draft(
            CreateDisciplineReviewDraft(
                invocation_id="tdk:discipline:draft",
                account_id="account_local",
                period=DisciplineReviewPeriod(
                    period_kind="weekly",
                    period_start_session="2026-07-27",
                    period_end_session="2026-07-27",
                    timezone="Asia/Shanghai",
                ),
                created_at="2026-07-31T19:00:00+08:00",
                decision_actor="agent:codex",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )
        confirmed_discipline = reviews.confirm(
            ConfirmDisciplineReviewVersion(
                invocation_id="tdk:discipline:confirm",
                discipline_review_id=discipline.discipline_review_id,
                expected_version_no=discipline.version_no,
                confirmed_at="2026-07-31T20:00:00+08:00",
                decision_actor="user:local-user",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )

    second_review, second_task = _review_session(
        data_root,
        session="2026-08-03",
        invocation="tdk:review:second",
        first_window_start=None,
        plan_versions=tuple(first_versions),
        grid_rule_id="grid-rule-2",
    )
    execution_command = DeclareExecution(
        invocation_id="tdk:execution:declare",
        decision_task_id=second_task,
        reason="synthetic user-declared completed execution",
        effective_at="2026-08-03T14:30:00+08:00",
        effective_session="2026-08-03",
        intent_type="decrease",
        quantity="10",
        price_state="known",
        price_value="9.50",
        fee_state="unknown",
        fee_value=None,
        currency="CNY",
        confirmed_at="2026-08-03T18:00:00+08:00",
        decision_actor="user:local-user",
        interaction_channel="skill",
        transport_actor="agent:codex",
    )
    with open_decision_journal(data_root) as journal:
        execution = journal.declare(execution_command)
    with open_decision_journal(data_root) as restarted_journal:
        replay = restarted_journal.declare(execution_command)

    review_item_id = _review_item_id(
        data_root,
        second_review.review_run_id,
        "security_002897_sz",
    )
    with open_plan_impacts(data_root) as impacts:
        assessment = impacts.create_assessment(
            CreatePlanImpactAssessment(
                invocation_id="tdk:impact:assessment",
                review_run_id=second_review.review_run_id,
                review_item_id=review_item_id,
                review_rule_id="review_rule_evidence_change",
                impact_kind="unable_to_determine",
                materiality="unable",
                uncertainties=("synthetic evidence changed",),
                what_changed="synthetic session evidence changed",
                what_would_change_the_view="a later complete session",
                model_identity="model:synthetic",
                policy_identity="policy:synthetic",
                prompt_identity="prompt:synthetic",
                created_by="agent",
                created_at="2026-08-03T18:30:00+08:00",
            )
        )
        accepted_source = impacts.create_proposal(
            CreatePlanChangeProposal(
                invocation_id="tdk:proposal:create:accepted",
                assessment_id=assessment.assessment_id,
                proposed_content={
                    "schema_version": "TradePlanContent@1",
                    "purpose": "synthetic-proposal",
                },
                parameters={"review": "synthetic"},
                created_by="agent",
                created_at="2026-08-03T18:40:00+08:00",
            )
        )
        accepted = impacts.accept(
            AcceptPlanChangeProposal(
                invocation_id="tdk:proposal:accept",
                proposal_id=accepted_source.proposal_id,
                expected_revision=accepted_source.revision,
                draft_id="tdk_plan_draft_from_proposal",
                expected_draft_revision=None,
                decided_at="2026-08-03T18:45:00+08:00",
                actor=USER,
            )
        )
        rejected_source = impacts.create_proposal(
            CreatePlanChangeProposal(
                invocation_id="tdk:proposal:create:rejected",
                assessment_id=assessment.assessment_id,
                proposed_content={
                    "schema_version": "TradePlanContent@1",
                    "purpose": "synthetic-rejected",
                },
                parameters={"review": "rejected"},
                created_by="agent",
                created_at="2026-08-03T18:46:00+08:00",
            )
        )
        rejected = impacts.reject(
            RejectPlanChangeProposal(
                invocation_id="tdk:proposal:reject",
                proposal_id=rejected_source.proposal_id,
                expected_revision=rejected_source.revision,
                decided_at="2026-08-03T18:47:00+08:00",
                actor=USER,
            )
        )

    with open_trade_plan(data_root) as plans:
        before_activation = plans.get(
            GetActiveTradePlan("account_local", "security_002897_sz")
        )
        assert (
            before_activation.version.plan_version_id
            == first_versions[0]
        )
        challenge = plans.execute(
            IssuePlanConfirmationChallenge(
                invocation_id="tdk:proposal:challenge",
                draft_id=accepted.accepted_draft_id,
                expected_revision=1,
                activation_intent=ActivationIntent.CONFIRM_AND_ACTIVATE,
                issued_at="2026-08-03T18:50:00+08:00",
                expires_at="2026-08-03T19:50:00+08:00",
                actor=USER,
            )
        )
        activated = plans.execute(
            ConfirmTradePlanVersion(
                invocation_id="tdk:proposal:confirm",
                challenge_id=challenge.challenge_id,
                expected_revision=challenge.expected_revision,
                expected_draft_hash=challenge.expected_draft_hash,
                expected_diff_hash=challenge.canonical_diff.content_hash,
                activation_intent=challenge.activation_intent,
                approved_at="2026-08-03T19:00:00+08:00",
                actor=USER,
            )
        )
        grid_active = plans.get(
            GetActiveTradePlan("account_local", "security_600183_sh")
        )

    steps = (
        "agent_snapshot_draft",
        "user_snapshot_confirmation",
        "two_agent_plan_drafts",
        "agent_plan_confirmation_denied",
        "user_challenge_confirmation",
        "one_active_plan_per_security",
        "grid_core_floor_preserved",
        "multi_session_manual_review",
        "no_change_creates_no_task",
        "grid_trigger_creates_one_task",
        "execution_updates_estimated_state",
        "deferred_task_reappears",
        "overridden_discipline_review",
        "proposal_is_draft_only",
        "rejected_proposal_does_not_pollute_active_plan",
        "new_plan_version_preserves_history",
        "web_skill_read_model_parity",
        "restart_replay_idempotent",
        "backup_restore_rebuild",
        "missing_broker_evidence_is_unverified",
    )
    return KernelScenario(
        data_root=data_root,
        snapshot_version_id=snapshot.account_snapshot_version_id,
        first_plan_version_ids=tuple(first_versions),
        current_plan_version_ids=(
            activated.graph.version.plan_version_id,
            grid_active.version.plan_version_id,
        ),
        review_run_ids=(
            first_review.review_run_id,
            second_review.review_run_id,
        ),
        first_task_id=first_task,
        second_task_id=second_task,
        execution_record_id=execution.execution_record_id,
        discipline_review_version_id=(
            f"{confirmed_discipline.discipline_review_id}:"
            f"{confirmed_discipline.version_no}"
        ),
        accepted_draft_id=accepted.accepted_draft_id,
        proposal_rejected=rejected.status == "rejected",
        agent_snapshot_denied=denied,
        agent_plan_denied=plan_denied,
        replay_execution_equal=replay == execution,
        steps=steps,
    )


def _insert_data_authority(data_root: Path) -> None:
    adapter = SQLiteOwningAdapterFixture(data_root)
    adapter.execute(
        "INSERT INTO query_policy_record VALUES(?,?,?,?,?)",
        (
            "query_policy_tdk@1",
            "QueryPolicy@1",
            "query-policy-tdk-hash",
            "{}",
            "2026-07-27T00:00:00+08:00",
        ),
    )
    adapter.execute(
        "INSERT INTO source_policy_record VALUES(?,?,?,?,?)",
        (
            "source_policy_tdk@1",
            "SourcePolicy@1",
            "source-policy-tdk-hash",
            "{}",
            "2026-07-27T00:00:00+08:00",
        ),
    )
    for security_id, suffix in (
        ("security_002897_sz", "002897"),
        ("security_600183_sh", "600183"),
    ):
        adapter.execute(
            "INSERT INTO data_snapshot VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"data_snapshot_plan_{suffix}",
                security_id,
                "research",
                "2026-07-27",
                "2026-07-24",
                "2026-07-24T15:00:00+08:00",
                "Asia/Shanghai",
                "calendar_tdk@1",
                "query_policy_tdk@1",
                "source_policy_tdk@1",
                "freshness_tdk@1",
                f"membership-{suffix}",
                "valid",
                "pass",
                0,
                0,
                0,
                0,
                0,
                "synthetic_fixture",
                "2026-07-24T15:00:00+08:00",
            ),
        )
    adapter.close()


def _plan_draft(
    snapshot_id: str,
    security_id: str,
    suffix: str,
    *,
    grid: bool,
):
    plan_id = TradePlanMasterId.derive(
        "account_local",
        security_id,
        f"tdk-{suffix}",
    ).value
    core = CoreSleeve(
        sleeve_id="core",
        quantity_budget=Decimal("80" if grid else "100"),
        core_floor=CoreFloor(Decimal("80")),
    )
    sleeves = [core]
    if grid:
        sleeves.append(
            GridSleeve(
                sleeve_id="grid",
                quantity_budget=Decimal("20"),
                core_floor=CoreFloor(Decimal("80")),
                constraint=GridConstraint(
                    grid_constraint_id=f"grid_constraint_{suffix}",
                    lower_price=Decimal("8"),
                    upper_price=Decimal("12"),
                    level_count=5,
                    quantity_per_level=Decimal("100"),
                    total_quantity_budget=Decimal("20"),
                    price_basis="unadjusted",
                    trigger_mode="crosses_level",
                    cooldown_trading_sessions=1,
                ),
            )
        )
    review_rule = TradePlanRule.build(
        rule_id="review_rule_evidence_change",
        rule_class=RuleClass.REVIEW,
        rule_kind="evidence_change",
        priority=RulePriority.ORDINARY,
        scope=RuleScope.MASTER,
        sleeve_id=None,
        effect="route_frozen_evidence",
        applies_to="plan",
        candidate_intent=None,
        input_applicability=("account.cash",),
        condition=RuleAstV2(
            node="comparison",
            operand_id="account.cash",
            operator="lt",
            expected=Decimal("0"),
        ),
    )
    graph = build_plan_version(
        plan_version_id=f"trade_plan_version_tdk_{suffix}_1",
        plan_id=plan_id,
        version_no=1,
        supersedes_version_id=None,
        strategy_version_id=(
            "strategy_version_core_plus_grid_1"
            if grid
            else "strategy_version_trend_hold_break_exit_1"
        ),
        investment_thesis_version_id=None,
        account_snapshot_version_id=snapshot_id,
        data_snapshot_id=f"data_snapshot_plan_{suffix}",
        horizon_start="2026-07-27",
        horizon_end="2026-10-27",
        review_by="2026-08-27",
        risk_policy_version_id=None,
        metric_catalog_version="metric-catalog@2",
        evaluator_policy_version="plan-evaluator@2",
        content={
            "schema_version": "TradePlanContent@1",
            "purpose": f"tdk-{suffix}",
        },
        sleeves=tuple(sleeves),
        rules=(review_rule,),
        evidence_references=(),
        adjusted_price_evidence=(),
        confirmed_at="1970-01-01T00:00:00+00:00",
        user_approval_receipt_id="pending-user-approval",
    )
    return build_trade_plan_draft(
        draft_id=f"trade_plan_draft_tdk_{suffix}_1",
        account_id="account_local",
        security_id=security_id,
        proposed_graph=graph,
        parameters={"fixture": suffix},
        created_at="2026-07-27T01:00:00+08:00",
        decision_actor=USER.decision_actor,
        interaction_channel=USER.interaction_channel,
        transport_actor=USER.transport_actor,
    )


def _review_session(
    data_root: Path,
    *,
    session: str,
    invocation: str,
    first_window_start: str | None,
    plan_versions: tuple[str, str],
    grid_rule_id: str,
):
    compact = session.replace("-", "")
    adapter = SQLiteOwningAdapterFixture(data_root)
    adapter.execute(
        "INSERT INTO market_universe_version VALUES(?,?,?,?,?)",
        (
            f"market_universe_{compact}",
            "CN_A_SHARE",
            f"{session}T15:00:00+08:00",
            "synthetic_fixture",
            f"membership-{compact}",
        ),
    )
    for index, (security_id, suffix, plan_version_id) in enumerate(
        (
            ("security_002897_sz", "002897", plan_versions[0]),
            ("security_600183_sh", "600183", plan_versions[1]),
        )
    ):
        source = adapter.execute(
            "SELECT * FROM data_snapshot WHERE data_snapshot_id=?",
            (f"data_snapshot_plan_{suffix}",),
        ).fetchone()
        values = list(source)
        values[0] = f"data_snapshot_review_{compact}_{suffix}"
        values[3] = session
        values[4] = session
        values[5] = f"{session}T15:00:00+08:00"
        values[19] = "effective_complete_session"
        values[20] = f"{session}T15:00:00+08:00"
        adapter.execute(
            "INSERT INTO data_snapshot VALUES("
            + ",".join("?" for _ in values)
            + ")",
            values,
        )
        market_snapshot_id = f"market_snapshot_{compact}_{suffix}"
        adapter.execute(
            "INSERT INTO market_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                market_snapshot_id,
                security_id,
                "CN_A_SHARE",
                session,
                session,
                values[0],
                f"market_universe_{compact}",
                "cn-a-share-market@1",
                "freshness_tdk@1",
                "code:tdk",
                f"market-input-{compact}-{suffix}",
                "complete",
                1,
                f"{session}T15:00:00+08:00",
            ),
        )
        outcome = "no_action" if index == 0 else "decision_task"
        reason = (
            "NO_RULE_TRIGGERED"
            if index == 0
            else "GRID_TRIGGER_REQUIRES_DISPOSITION"
        )
        resolution = (
            "{}"
            if index == 0
            else json.dumps(
                {
                    "winner": {
                        "rule_id": grid_rule_id,
                        "intent_type": "decrease",
                    },
                    "evidence_identity": f"evidence-{compact}-{suffix}",
                },
                separators=(",", ":"),
            )
        )
        with adapter.transaction():
            adapter.execute(
                "INSERT INTO plan_evaluation VALUES("
                + ",".join("?" for _ in range(15))
                + ")",
                (
                    f"plan_evaluation_{compact}_{suffix}",
                    plan_version_id,
                    market_snapshot_id,
                    "plan-evaluator@2",
                    "trade-plan-conflict@1",
                    "completed",
                    outcome,
                    reason,
                    resolution,
                    f"resolution-hash-{compact}-{suffix}",
                    "complete",
                    1,
                    f"evaluation-hash-{compact}-{suffix}",
                    0,
                    f"{session}T15:30:00+08:00",
                ),
            )
            adapter.execute(
                "INSERT INTO plan_rule_evaluation VALUES(?,?,?,?,?,?,?,?)",
                (
                    f"plan_evaluation_{compact}_{suffix}",
                    0,
                    "review_rule_evidence_change",
                    "unable_to_determine",
                    "EVIDENCE_INCOMPLETE",
                    "{}",
                    f"replay-hash-{compact}-{suffix}",
                    0,
                ),
            )
    adapter.close()
    with open_manual_portfolio_review(data_root) as reviews:
        review = reviews.start(
            StartManualPortfolioReview(
                invocation_id=invocation,
                account_id="account_local",
                requested_at=f"{session}T16:00:00+08:00",
                selected_complete_session=session,
                first_window_start_exclusive=first_window_start,
                code_identity="code:tdk",
                config_identity="config:tdk",
                decision_actor="agent:codex",
                interaction_channel="skill",
                transport_actor="agent:codex",
            )
        )
    with open_decision_tasks(data_root) as tasks:
        candidates = [
            item
            for item in tasks.list(ListDecisionTasks("account_local"))
            if item.state.value == "open"
        ]
    assert len(candidates) == 1
    return review, candidates[0].decision_task_id


def _review_item_id(
    data_root: Path,
    review_run_id: str,
    security_id: str,
) -> str:
    adapter = SQLiteOwningAdapterFixture(data_root)
    row = adapter.execute(
        "SELECT review_item_id FROM manual_portfolio_review_item "
        "WHERE review_run_id=? AND security_id=?",
        (review_run_id, security_id),
    ).fetchone()
    adapter.close()
    assert row is not None
    return str(row["review_item_id"])
