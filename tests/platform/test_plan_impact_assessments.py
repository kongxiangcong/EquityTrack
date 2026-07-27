from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest

from tests.platform.owning_adapter_fixture import (
    SQLiteOwningAdapterFixture,
)
from tests.platform.test_manual_portfolio_review import (
    _complete_session,
    _start,
)
from tests.platform.test_plan_confirmation import (
    USER,
    _authority_root,
    _confirm,
    _create_and_challenge,
    _draft,
)
from trading_platform.application import (
    CreatePlanImpactAssessment,
    open_plan_impacts,
    open_trade_plan,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.plan_impacts import PlanImpactError
from trading_platform.domain.plans import (
    TradePlanRule,
    build_plan_version,
    build_trade_plan_draft,
)
from trading_platform.domain.rules import (
    RuleAstV2,
    RuleClass,
    RulePriority,
    RuleScope,
)


def test_assessment_command_requires_agent_or_system_authorship() -> None:
    with pytest.raises(PlanImpactError, match="PLAN_IMPACT_AUTHOR_DENIED"):
        CreatePlanImpactAssessment(
            invocation_id="assessment:user-denied",
            review_run_id="review",
            review_item_id="item",
            review_rule_id="rule",
            impact_kind="requires_review",
            materiality="medium",
            uncertainties=("uncertain",),
            what_changed="new evidence",
            what_would_change_the_view="verified evidence",
            model_identity="model:test",
            policy_identity="policy:test",
            prompt_identity="prompt:test",
            created_by="user",
            created_at="2026-07-27T16:00:00+08:00",
        ).validate()


def _impact_authority(tmp_path: Path):
    data_root, snapshot_id = _authority_root(tmp_path)
    original = _draft(snapshot_id, suffix="impact-authority")
    base = original.proposed_graph
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
    version = base.version
    graph = build_plan_version(
        plan_version_id=version.plan_version_id,
        plan_id=version.plan_id,
        version_no=version.version_no,
        supersedes_version_id=version.supersedes_version_id,
        strategy_version_id=version.strategy_version_id,
        investment_thesis_version_id=(
            version.investment_thesis_version_id
        ),
        account_snapshot_version_id=version.account_snapshot_version_id,
        data_snapshot_id=version.data_snapshot_id,
        horizon_start=version.horizon_start,
        horizon_end=version.horizon_end,
        review_by=version.review_by,
        risk_policy_version_id=version.risk_policy_version_id,
        metric_catalog_version=version.metric_catalog_version,
        evaluator_policy_version=version.evaluator_policy_version,
        content=version.content,
        sleeves=base.sleeves,
        rules=(review_rule,),
        evidence_references=base.evidence_references,
        adjusted_price_evidence=base.adjusted_price_evidence,
        confirmed_at=version.confirmed_at,
        user_approval_receipt_id=version.user_approval_receipt_id,
    )
    draft = build_trade_plan_draft(
        draft_id=original.draft_id,
        account_id=original.account_id,
        security_id=original.security_id,
        proposed_graph=graph,
        parameters=original.parameters,
        created_at=original.created_at,
        decision_actor=USER.decision_actor,
        interaction_channel=USER.interaction_channel,
        transport_actor=USER.transport_actor,
    )
    with open_trade_plan(data_root) as plans:
        _, challenge = _create_and_challenge(
            plans,
            draft,
            "impact-authority",
            ActivationIntent.CONFIRM_AND_ACTIVATE,
        )
        _confirm(plans, challenge, "impact-authority")
    _complete_session(data_root, "2026-07-27")
    review = _start(
        data_root,
        invocation_id="impact:manual-review",
        selected_session="2026-07-27",
    )
    connection = SQLiteOwningAdapterFixture(data_root)
    row = connection.execute(
        "SELECT review_item_id FROM manual_portfolio_review_item "
        "WHERE review_run_id=?",
        (review.review_run_id,),
    ).fetchone()
    connection.close()
    assert row is not None
    return data_root, review.review_run_id, row["review_item_id"], draft


def _assessment_command(
    review_run_id: str,
    review_item_id: str,
    *,
    invocation_id: str = "impact:assessment",
) -> CreatePlanImpactAssessment:
    return CreatePlanImpactAssessment(
        invocation_id=invocation_id,
        review_run_id=review_run_id,
        review_item_id=review_item_id,
        review_rule_id="review_rule_evidence_change",
        impact_kind="unable_to_determine",
        materiality="unable",
        uncertainties=("compatible evaluation unavailable",),
        what_changed="review evidence could not determine the rule",
        what_would_change_the_view="a complete compatible evaluation",
        model_identity="model:test",
        policy_identity="policy:test",
        prompt_identity="prompt:test",
        created_by="agent",
        created_at="2026-07-27T16:30:00+08:00",
    )


def test_unable_assessment_uses_immutable_frozen_review_authority(
    tmp_path: Path,
) -> None:
    data_root, run_id, item_id, draft = _impact_authority(tmp_path)
    command = _assessment_command(run_id, item_id)
    with open_plan_impacts(data_root) as impacts:
        assessment = impacts.create_assessment(command)
        replay = impacts.create_assessment(command)
    assert replay == assessment
    assert assessment.evidence.review_rule_result == "unable_to_determine"
    assert assessment.evidence.plan_version_id == (
        draft.proposed_graph.version.plan_version_id
    )
    assert assessment.evidence.evidence_manifest_id
    connection = SQLiteOwningAdapterFixture(data_root)
    with pytest.raises(
        sqlite3.IntegrityError, match="PLAN_IMPACT_IMMUTABLE"
    ):
        connection.execute(
            "UPDATE plan_impact_assessment SET what_changed='tampered'"
        )
    connection.close()


def test_unable_review_rule_cannot_be_authored_as_determined(
    tmp_path: Path,
) -> None:
    data_root, run_id, item_id, _ = _impact_authority(tmp_path)
    invalid = replace(
        _assessment_command(run_id, item_id),
        impact_kind="challenges_current_plan",
        materiality="high",
    )
    with open_plan_impacts(data_root) as impacts:
        with pytest.raises(
            PlanImpactError, match="PLAN_IMPACT_FINDING_INVALID"
        ):
            impacts.create_assessment(invalid)
