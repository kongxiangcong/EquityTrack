from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from trading_platform.application.account_snapshots import GetAccountSnapshot
from trading_platform.application.plan_compiler import (
    _CompileTradePlanDraft,
    CorePlusGridIntent,
    TradePlanCompiler,
    TrendHoldBreakExitIntent,
)
from trading_platform.application.risk_policies import GetPortfolioRiskPolicy
from trading_platform.application.strategy_catalog import StrategyQueries
from trading_platform.application.trade_plan_authoring import (
    PlanCommandActor,
    _UpsertOpenTradePlanDraft,
)
from trading_platform.application.workflow_ledger import DecisionViewPayload
from trading_platform.domain.account_snapshots import (
    AccountSnapshotPosition,
    AccountSnapshotVersion,
)
from trading_platform.domain.market import MarketBar
from trading_platform.domain.plans import (
    ActiveTradePlan,
    PlanActivation,
    PlanValidationError,
    TradePlanDraft,
    TradePlanMaster,
    TradePlanMasterId,
    build_trade_plan_draft,
)
from trading_platform.domain.recent_trend import assess_recent_trend
from trading_platform.domain.risk_policies import (
    PortfolioRiskLimits,
    PortfolioRiskPolicyService,
)
from trading_platform.domain.strategies import builtin_strategy_versions
from trading_platform.research_view import ResearchDecisionView


class _Research:
    def __init__(self, payload: DecisionViewPayload) -> None:
        self.payload = payload

    def decision_view(self, workflow_run_id: str) -> DecisionViewPayload:
        return self.payload


class _RecentTrends:
    def __init__(self, assessment: object) -> None:
        self.assessment = assessment

    def get(self, assessment_id: str) -> object:
        return self.assessment


class _Accounts:
    def __init__(self, snapshot: AccountSnapshotVersion) -> None:
        self.snapshot = snapshot

    def get(self, query: object) -> AccountSnapshotVersion:
        assert query == GetAccountSnapshot(account_id=self.snapshot.account_id)
        return self.snapshot


class _RiskPolicies:
    def __init__(self, policy: object) -> None:
        self.policy = policy

    def get(self, query: object) -> object:
        assert query == GetPortfolioRiskPolicy(account_id=self.policy.account_id)
        return self.policy


class _StrategyReader:
    def all_versions(self) -> tuple[object, ...]:
        return builtin_strategy_versions()


class _Plans:
    def __init__(self) -> None:
        self.commands: list[_UpsertOpenTradePlanDraft] = []
        self.open_draft: TradePlanDraft | None = None
        self.active_plan: ActiveTradePlan | None = None
        self.invocations: dict[str, TradePlanDraft] = {}

    def upsert(self, command: _UpsertOpenTradePlanDraft) -> TradePlanDraft:
        prepared = build_trade_plan_draft(
            draft_id=(
                self.open_draft.draft_id
                if self.open_draft is not None
                else "trade_plan_draft_unit_authoring"
            ),
            account_id=command.account_id,
            security_id=command.security_id,
            proposed_graph=command.proposed_graph,
            parameters=command.parameters,
            created_at=command.updated_at,
            decision_actor=command.actor.decision_actor,
            interaction_channel=command.actor.interaction_channel,
            transport_actor=command.actor.transport_actor,
        )
        result = (
            prepared
            if self.open_draft is None
            else replace(
                prepared,
                revision=self.open_draft.revision + 1,
                created_at=self.open_draft.created_at,
            )
        )
        result.validate()
        self.commands.append(command)
        self.open_draft = result
        self.invocations[command.invocation_id] = result
        return result

    def get_open(self, account_id: str, security_id: str) -> TradePlanDraft | None:
        return self.open_draft

    def get_by_invocation(self, invocation_id: str) -> TradePlanDraft | None:
        return self.invocations.get(invocation_id)

    def get_active(self, account_id: str, security_id: str) -> ActiveTradePlan:
        if self.active_plan is None:
            raise PlanValidationError("ACTIVE_PLAN_NOT_FOUND")
        return self.active_plan


def _research_audit(
    trend: object,
    *,
    complete_report: bool,
) -> dict[str, object]:
    names = (
        "forecast",
        "scenario_valuation",
        "valuation_method_route",
        "valuation_simulation_decision",
        "market_path_decision",
        "recent_trend_assessment",
    )
    components = {
        name: {
            "artifact_id": f"{name}_component_exact",
            "schema_version": "ResearchComponentResult@1",
            "component": name,
            "status": (
                "complete"
                if complete_report or name == "recent_trend_assessment"
                else "limited"
            ),
            "reason_codes": (
                (
                    f"{name.upper()}_COMPLETE"
                    if complete_report or name == "recent_trend_assessment"
                    else f"{name.upper()}_LIMITED"
                ),
            ),
            "source_member_ids": trend.evidence_refs,
            "content_schema_version": f"{name}@1",
        }
        for name in names
    }
    return {
        "evaluation_bundle": {
            "bundle_id": "research_bundle_exact",
            "schema_version": "ResearchEvaluationBundle@1",
            "origin": {},
            "estimates": None,
            "components": components,
        },
        "recent_trend_assessment": {
            **components["recent_trend_assessment"],
            "assessment": {
                "assessment_id": trend.assessment_id,
                "as_of_session": trend.as_of_session,
                "content_hash": trend.content_hash,
            },
        },
    }


def _authoring(
    *,
    security_id: str = "security_002897_sz",
    trend_data_snapshot_id: str = "data_snapshot_research",
    complete_report: bool = False,
    account_as_of_at: str = "2026-03-04T15:30:00+08:00",
    account_as_of_precision: str = "instant",
) -> tuple[TradePlanCompiler, _Plans, object, object, object]:
    trend = assess_recent_trend(
        security_id=security_id,
        data_snapshot_id=trend_data_snapshot_id,
        as_of_session="2026-03-04",
        bars=tuple(
            MarketBar(
                security_id=security_id,
                session_date=(
                    f"2026-{(index // 28) + 1:02d}-" f"{(index % 28) + 1:02d}"
                ),
                close=Decimal(index + 1),
                amount=Decimal("1000000"),
                normalized_version_id=f"daily:{index + 1}",
            )
            for index in range(60)
        ),
    )
    view = ResearchDecisionView(
        schema_version="ResearchDecisionView@2",
        view_id="research_view_exact",
        workflow_run_id="workflow_research_exact",
        research_run_id="research_run_exact",
        data_snapshot_id="data_snapshot_research",
        model_data_snapshot_identity="data_snapshot_research",
        security_id=security_id,
        forecast_artifact_record_id=None,
        valuation_artifact_record_id=None,
        simulation_artifact_record_id=None,
        market_path_artifact_record_id=None,
        subject_id=security_id,
        as_of="2026-03-04",
        model_identity="research-model@1",
        policy_identity="ResearchEvaluationPolicy@2",
        status="completed" if complete_report else "completed_with_limits",
        valuation_view=(
            {"status": "ready", "formal_per_share_valuation": True}
            if complete_report
            else {"status": "limited"}
        ),
        risk_reward_summary="Conditional evidence only.",
        data_quality_grade="C",
        key_uncertainties=("official_source_gap",),
        what_would_change_the_view=("new_official_disclosure",),
        story={"what_happens": "conditional"},
        key_drivers=(
            ({"metric_id": "revenue", "evidence_id": "evidence_revenue"},)
            if complete_report
            else ()
        ),
        scenarios=(
            tuple({"scenario_role": role} for role in ("stress", "base", "improvement"))
            if complete_report
            else ()
        ),
        market_implied_expectations=(),
        valuation_simulation={"status": "not_run"},
        market_price_paths={"status": "not_run"},
        value_market_divergence=None,
        audit=_research_audit(
            trend,
            complete_report=complete_report,
        ),
        boundary="Not personalized investment advice.",
    )
    decision = DecisionViewPayload(
        manifest_id="artifact_manifest_decision",
        json_artifact_id="artifact_decision_json",
        html_artifact_id="artifact_decision_html",
        pdf_artifact_id="artifact_decision_pdf",
        workbook_artifact_id="artifact_workbook_limitation",
        json_bytes=json.dumps(view.to_dict()).encode(),
        html_bytes=b"<html></html>",
        pdf_bytes=b"%PDF-1.4",
        workbook_bytes=(
            b'{"schema_version":"ResearchWorkbookProjection@1",' b'"status":"limited"}'
        ),
        workbook_media_type="application/json",
        workbook_schema_version="ResearchWorkbookProjection@1",
        workbook_filename="research-workbook-limitation.json",
        workbook_status="limited",
        workbook_reason_code="RESEARCH_WORKBOOK_RENDERER_UNAVAILABLE",
    )
    position = AccountSnapshotPosition(
        security_id=security_id,
        total_quantity="1000",
        available_quantity_state="known",
        available_quantity_value="1000",
        market_value_state="known",
        market_value_value="60000",
        content_hash="position-hash",
    )
    account = AccountSnapshotVersion(
        account_snapshot_version_id="account_snapshot_version_exact",
        account_id="account_local",
        version_no=1,
        source_draft_id="account_snapshot_draft_exact",
        as_of_at=account_as_of_at,
        as_of_precision=account_as_of_precision,
        timezone="Asia/Shanghai",
        session_semantics="complete_session",
        currency="CNY",
        source_kind="user_declared_from_broker_screenshot",
        redacted_source_ref="broker-screenshot:redacted",
        previous_snapshot_version_id=None,
        revises_snapshot_version_id=None,
        corrects_snapshot_version_id=None,
        correction_reason=None,
        confirmed_by="user:local-user",
        confirmed_at="2026-03-04T16:00:00+08:00",
        content_hash="account-content-hash",
        graph_seal_hash="account-graph-seal",
        cash_state="known",
        cash_value="40000",
        nav_state="known",
        nav_value="100000",
        fees_state="unknown",
        fees_value=None,
        positions=(position,),
        capabilities=(),
    )
    limits = PortfolioRiskLimits(
        single_security_exposure=Decimal("0.30"),
        industry_exposure=Decimal("0.50"),
        gross_exposure=Decimal("0.80"),
        minimum_cash=Decimal("0.20"),
        single_plan_loss=Decimal("0.02"),
        aggregate_active_plan_loss=Decimal("0.05"),
        drawdown_review=Decimal("0.10"),
        drawdown_freeze=Decimal("0.15"),
        plan_daily_liquidity=Decimal("0.05"),
        position_daily_liquidity=Decimal("0.10"),
    )
    risk_service = PortfolioRiskPolicyService()
    policy = risk_service.create_version(
        risk_service.prepare("account_local", "CNY", limits),
        version_no=1,
        previous_version_id=None,
        confirmed_by="user:local-user",
        confirmed_at="2026-03-04T16:05:00+08:00",
    )
    plans = _Plans()
    authoring = TradePlanCompiler(
        research=_Research(decision),
        recent_trends=_RecentTrends(trend),
        accounts=_Accounts(account),
        risk_policies=_RiskPolicies(policy),
        strategies=StrategyQueries(_StrategyReader()),
        drafts=plans,
    )
    return authoring, plans, trend, account, policy


def _command(trend: object, account: object, policy: object) -> _CompileTradePlanDraft:
    return _CompileTradePlanDraft(
        invocation_id="author-plan:exact",
        workflow_run_id="workflow_research_exact",
        recent_trend_assessment_id=trend.assessment_id,
        account_id=account.account_id,
        strategy_key="trend_hold_break_exit",
        intent=TrendHoldBreakExitIntent(
            core_floor_quantity=Decimal("800"),
            candidate_decrease_quantity=Decimal("100"),
            break_confirmation_sessions=2,
            horizon_end="2026-09-30",
            review_by="2026-08-04",
        ),
        created_at="2026-07-28T16:10:00+08:00",
        actor=PlanCommandActor(
            decision_actor="agent:codex",
            interaction_channel="skill",
            transport_actor="agent:codex",
        ),
    )


def _grid_command(
    trend: object,
    account: object,
    policy: object,
) -> _CompileTradePlanDraft:
    return _CompileTradePlanDraft(
        invocation_id="author-grid:exact",
        workflow_run_id="workflow_research_exact",
        recent_trend_assessment_id=trend.assessment_id,
        account_id=account.account_id,
        strategy_key="core_plus_grid",
        intent=CorePlusGridIntent(
            core_floor_quantity=Decimal("600"),
            grid_lower_price=Decimal("50"),
            grid_upper_price=Decimal("70"),
            grid_level_count=5,
            grid_quantity_per_level=Decimal("100"),
            grid_total_quantity_budget=Decimal("200"),
            grid_trigger_mode="crosses_level",
            cooldown_trading_sessions=1,
            horizon_end="2026-09-30",
            review_by="2026-08-04",
        ),
        created_at="2026-07-28T16:10:00+08:00",
        actor=PlanCommandActor(
            decision_actor="agent:codex",
            interaction_channel="skill",
            transport_actor="agent:codex",
        ),
    )


def test_high_level_intent_authors_one_open_unconfirmed_draft() -> None:
    authoring, plans, trend, account, policy = _authoring()

    draft = authoring.compile(_command(trend, account, policy))

    assert draft.status == "open"
    assert draft.revision == 1
    assert draft.proposed_graph.schema_version == "TradePlanDraftGraph@1"
    assert not hasattr(draft.proposed_graph.version, "confirmed_at")
    assert draft.proposed_graph.version.account_snapshot_version_id == (
        account.account_snapshot_version_id
    )
    assert draft.proposed_graph.version.risk_policy_version_id == (
        policy.portfolio_risk_policy_version_id
    )
    persisted_parameters = json.loads(json.dumps(draft.parameters))
    assert persisted_parameters["core_floor_quantity"] == "800"
    assert persisted_parameters["candidate_decrease_quantity"] == {
        "state": "known",
        "value": "100",
    }
    assert {item["ref_type"] for item in draft.proposed_graph.evidence_references} == {
        "ResearchDecisionView",
        "RecentTrendAssessment",
        "AccountSnapshotVersion",
        "PortfolioRiskPolicyVersion",
        "StrategyVersion",
    }
    assert len(plans.commands) == 1
    assert not hasattr(_command(trend, account, policy), "proposed_graph")


def test_complete_session_date_snapshot_is_valid_temporal_authority() -> None:
    authoring, _, trend, account, policy = _authoring(
        account_as_of_at="2026-03-04",
        account_as_of_precision="date",
    )

    draft = authoring.compile(_command(trend, account, policy))

    assert draft.proposed_graph.version.account_snapshot_version_id == (
        account.account_snapshot_version_id
    )


def test_cross_evidence_identity_drift_fails_before_persistence() -> None:
    authoring, plans, trend, account, policy = _authoring(
        trend_data_snapshot_id="data_snapshot_other"
    )

    with pytest.raises(
        PlanValidationError,
        match="PLAN_AUTHORING_TREND_IDENTITY_MISMATCH",
    ):
        authoring.compile(_command(trend, account, policy))

    assert plans.commands == []


def test_complete_research_can_author_bounded_core_plus_grid_draft() -> None:
    authoring, plans, trend, account, policy = _authoring(complete_report=True)

    draft = authoring.compile(_grid_command(trend, account, policy))

    assert draft.status == "open"
    assert draft.strategy_version_id == "strategy_version_core_plus_grid_1"
    persisted_parameters = json.loads(json.dumps(draft.parameters))
    assert persisted_parameters["core_floor_quantity"] == "600"
    assert persisted_parameters["grid_lower_price"] == "50"
    assert persisted_parameters["grid_total_quantity_budget"] == "200"
    assert {sleeve.kind.value for sleeve in draft.proposed_graph.sleeves} == {
        "core",
        "grid",
    }
    risk_evidence = draft.content["risk_increase_evidence"]
    assert risk_evidence["valuation_status"] == "ready"
    assert risk_evidence["research_bundle_id"] == ("research_bundle_exact")
    assert risk_evidence["forecast_component_artifact_id"] == (
        "forecast_component_exact"
    )
    assert (
        risk_evidence["scenario_valuation_component_artifact_id"]
        == "scenario_valuation_component_exact"
    )
    assert "forecast_artifact_record_id" not in risk_evidence
    assert "valuation_artifact_record_id" not in risk_evidence
    assert len(plans.commands) == 1


def test_limited_research_cannot_author_risk_increasing_grid() -> None:
    authoring, plans, trend, account, policy = _authoring()

    with pytest.raises(
        PlanValidationError,
        match="PLAN_AUTHORING_RISK_INCREASE_EVIDENCE_INSUFFICIENT",
    ):
        authoring.compile(_grid_command(trend, account, policy))

    assert plans.commands == []


def test_reauthoring_revises_the_same_open_draft_and_replays_exactly() -> None:
    authoring, plans, trend, account, policy = _authoring()
    command = _command(trend, account, policy)

    first = authoring.compile(command)
    replay = authoring.compile(command)
    revised_command = replace(
        command,
        invocation_id="author-plan:revision-2",
        intent=replace(
            command.intent,
            candidate_decrease_quantity=Decimal("200"),
        ),
    )
    revised = authoring.compile(revised_command)

    assert replay == first
    assert revised.draft_id == first.draft_id
    assert revised.revision == 2
    assert len(plans.commands) == 2
    assert all(isinstance(item, _UpsertOpenTradePlanDraft) for item in plans.commands)
    with pytest.raises(PlanValidationError, match="INVOCATION_CONFLICT"):
        authoring.compile(
            replace(
                command,
                intent=replace(
                    command.intent,
                    candidate_decrease_quantity=Decimal("150"),
                ),
            )
        )


def test_new_draft_supersedes_the_active_confirmed_plan_version() -> None:
    authoring, plans, trend, account, policy = _authoring()
    first = authoring.compile(_command(trend, account, policy))
    confirmed = first.proposed_graph.confirm(
        confirmed_at="2026-07-28T16:20:00+08:00",
        user_approval_receipt_id="user_approval_receipt_active",
    )
    plans.open_draft = None
    plans.active_plan = ActiveTradePlan(
        master=TradePlanMaster(
            plan_id=TradePlanMasterId(
                account.account_id,
                trend.security_id,
                first.plan_id,
            ),
            strategy_version_id=first.strategy_version_id,
            lifecycle_status="active",
            transition_seq=1,
            created_at=first.created_at,
        ),
        activation=PlanActivation(
            activation_id="plan_activation_active",
            plan_id=first.plan_id,
            plan_version_id=confirmed.version.plan_version_id,
            activated_event_id="plan_activated_active",
            activated_at="2026-07-28T16:20:00+08:00",
            user_approval_receipt_id="user_approval_receipt_active",
            command_invocation_id="confirm-plan:active",
        ),
        version=confirmed.version,
    )

    next_draft = authoring.compile(
        replace(
            _command(trend, account, policy),
            invocation_id="author-plan:after-active",
        )
    )

    assert next_draft.plan_id == first.plan_id
    assert next_draft.proposed_graph.version.version_no == 2
    assert next_draft.based_on_version_id == (confirmed.version.plan_version_id)
