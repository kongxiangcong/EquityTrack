from __future__ import annotations

import json
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping, Protocol

from trading_platform.application.account_snapshots import GetAccountSnapshot
from trading_platform.application.risk_policies import GetPortfolioRiskPolicy
from trading_platform.application.strategy_catalog import GetStrategyCatalog
from trading_platform.application.trade_plan_authoring import (
    PlanCommandActor,
    _UpsertOpenTradePlanDraft,
)
from trading_platform.application.workflow_ledger import (
    DecisionViewPayload,
)
from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.domain.plans import (
    ActiveTradePlan,
    CoreFloor,
    CoreSleeve,
    GridSleeve,
    PlanValidationError,
    TradePlanDraft,
    TradePlanMasterId,
    TradePlanRule,
    build_trade_plan_draft_graph,
    validate_sleeve_quantities,
)
from trading_platform.domain.recent_trend import RecentTrendAssessment
from trading_platform.domain.risk_policies import (
    PortfolioRiskPolicyService,
    PortfolioRiskPolicyVersion,
)
from trading_platform.domain.rules import (
    CandidateIntent,
    GridConstraint,
    OperandState,
    OperandValue,
    RuleAstV2,
    RuleClass,
    RulePriority,
    RuleScope,
)
from trading_platform.domain.strategies import StrategyVersion
from trading_platform.identity import canonical_hash
from trading_platform.research_view import ResearchDecisionView, ResearchViewError


@dataclass(frozen=True)
class TrendHoldBreakExitIntent:
    core_floor_quantity: Decimal
    candidate_decrease_quantity: Decimal | None
    break_confirmation_sessions: int
    horizon_end: str
    review_by: str
    schema_version: str = "TrendHoldBreakExitIntent@1"

    def validate(self) -> None:
        try:
            review = date.fromisoformat(self.review_by)
            end = date.fromisoformat(self.horizon_end)
        except ValueError as error:
            raise PlanValidationError(
                "PLAN_AUTHORING_INTENT_HORIZON_INVALID"
            ) from error
        quantities = (
            self.core_floor_quantity,
            self.candidate_decrease_quantity,
        )
        if (
            self.schema_version != "TrendHoldBreakExitIntent@1"
            or not _whole_quantity(self.core_floor_quantity, allow_zero=True)
            or (
                self.candidate_decrease_quantity is not None
                and not _whole_quantity(
                    self.candidate_decrease_quantity,
                    allow_zero=False,
                )
            )
            or isinstance(self.break_confirmation_sessions, bool)
            or self.break_confirmation_sessions < 1
            or review > end
            or any(value is not None and not value.is_finite() for value in quantities)
        ):
            raise PlanValidationError("PLAN_AUTHORING_INTENT_INVALID")


@dataclass(frozen=True)
class CorePlusGridIntent:
    core_floor_quantity: Decimal
    grid_lower_price: Decimal
    grid_upper_price: Decimal
    grid_level_count: int
    grid_quantity_per_level: Decimal
    grid_total_quantity_budget: Decimal
    grid_trigger_mode: str
    cooldown_trading_sessions: int
    horizon_end: str
    review_by: str
    schema_version: str = "CorePlusGridIntent@1"

    def validate(self) -> None:
        try:
            review = date.fromisoformat(self.review_by)
            end = date.fromisoformat(self.horizon_end)
        except ValueError as error:
            raise PlanValidationError(
                "PLAN_AUTHORING_INTENT_HORIZON_INVALID"
            ) from error
        if (
            self.schema_version != "CorePlusGridIntent@1"
            or not _whole_quantity(self.core_floor_quantity, allow_zero=True)
            or not _whole_quantity(self.grid_quantity_per_level, allow_zero=False)
            or not _whole_quantity(self.grid_total_quantity_budget, allow_zero=False)
            or self.grid_quantity_per_level % Decimal("100") != 0
            or not self.grid_lower_price.is_finite()
            or not self.grid_upper_price.is_finite()
            or self.grid_lower_price <= 0
            or self.grid_upper_price <= self.grid_lower_price
            or isinstance(self.grid_level_count, bool)
            or not 2 <= self.grid_level_count <= 100
            or self.grid_trigger_mode
            not in {"crosses_level", "closes_at_or_beyond_level"}
            or isinstance(self.cooldown_trading_sessions, bool)
            or self.cooldown_trading_sessions < 0
            or review > end
        ):
            raise PlanValidationError("PLAN_AUTHORING_INTENT_INVALID")


@dataclass(frozen=True)
class _CompileTradePlanDraft:
    invocation_id: str
    workflow_run_id: str
    recent_trend_assessment_id: str
    account_id: str
    strategy_key: str
    intent: TrendHoldBreakExitIntent | CorePlusGridIntent
    created_at: str
    actor: PlanCommandActor
    schema_version: str = "CompileTradePlanDraft@1"

    def validate(self) -> None:
        self.intent.validate()
        self.actor.validate()
        try:
            created = datetime.fromisoformat(self.created_at)
        except ValueError as error:
            raise PlanValidationError("PLAN_AUTHORING_CREATED_AT_INVALID") from error
        if (
            self.schema_version != "CompileTradePlanDraft@1"
            or not all(
                (
                    self.invocation_id,
                    self.workflow_run_id,
                    self.recent_trend_assessment_id,
                    self.account_id,
                    self.strategy_key,
                )
            )
            or created.tzinfo is None
            or created.utcoffset() is None
        ):
            raise PlanValidationError("PLAN_AUTHORING_COMMAND_INVALID")


class ResearchDecisionReader(Protocol):
    def decision_view(self, workflow_run_id: str) -> DecisionViewPayload: ...


class RecentTrendAssessmentReader(Protocol):
    def get(self, assessment_id: str) -> RecentTrendAssessment: ...


class AccountSnapshotReader(Protocol):
    def get(self, query: GetAccountSnapshot) -> AccountSnapshotVersion: ...


class RiskPolicyReader(Protocol):
    def get(self, query: GetPortfolioRiskPolicy) -> PortfolioRiskPolicyVersion: ...


class StrategyReader(Protocol):
    def get(self, query: GetStrategyCatalog) -> tuple[StrategyVersion, ...]: ...


class _OpenTradePlanDraftWriter(Protocol):
    def upsert(self, command: _UpsertOpenTradePlanDraft) -> TradePlanDraft: ...

    def get_open(self, account_id: str, security_id: str) -> TradePlanDraft | None: ...

    def get_by_invocation(self, invocation_id: str) -> TradePlanDraft | None: ...

    def get_active(self, account_id: str, security_id: str) -> ActiveTradePlan: ...


@dataclass(frozen=True)
class _PlanAuthoringTarget:
    plan_id: str
    version_no: int
    supersedes_version_id: str | None


class TradePlanCompiler:
    """Compiles frozen research and account evidence into one OPEN draft."""

    def __init__(
        self,
        *,
        research: ResearchDecisionReader,
        recent_trends: RecentTrendAssessmentReader,
        accounts: AccountSnapshotReader,
        risk_policies: RiskPolicyReader,
        strategies: StrategyReader,
        drafts: _OpenTradePlanDraftWriter,
    ) -> None:
        self._research = research
        self._recent_trends = recent_trends
        self._accounts = accounts
        self._risk_policies = risk_policies
        self._strategies = strategies
        self._drafts = drafts
        self._risk_service = PortfolioRiskPolicyService()

    def compile(self, command: _CompileTradePlanDraft) -> TradePlanDraft:
        command.validate()
        replay = self._drafts.get_by_invocation(command.invocation_id)
        if replay is not None:
            return self._validate_replay(command, replay)
        decision_payload, decision_view = self._load_decision_view(
            command.workflow_run_id
        )
        trend = self._recent_trends.get(command.recent_trend_assessment_id)
        account = self._accounts.get(GetAccountSnapshot(account_id=command.account_id))
        risk_policy = self._risk_policies.get(
            GetPortfolioRiskPolicy(account_id=command.account_id)
        )
        strategy = self._select_strategy(command.strategy_key)
        self._validate_authorities(
            command=command,
            decision_payload=decision_payload,
            decision_view=decision_view,
            trend=trend,
            account=account,
            risk_policy=risk_policy,
            strategy=strategy,
        )
        target = self._resolve_target(
            account_id=account.account_id,
            security_id=decision_view.security_id,
            strategy=strategy,
        )
        compiler = (
            self._compile_trend_draft
            if isinstance(command.intent, TrendHoldBreakExitIntent)
            else self._compile_grid_draft
        )
        mutation = compiler(
            command=command,
            decision_payload=decision_payload,
            decision_view=decision_view,
            trend=trend,
            account=account,
            risk_policy=risk_policy,
            strategy=strategy,
            target=target,
        )
        persisted = self._drafts.upsert(mutation)
        if persisted.status != "open":
            raise PlanValidationError("PLAN_AUTHORING_PERSISTED_DRAFT_NOT_OPEN")
        return persisted

    @staticmethod
    def _validate_replay(
        command: _CompileTradePlanDraft,
        replay: ActiveTradePlan | TradePlanDraft,
    ) -> TradePlanDraft:
        expected_strategy_key = (
            "trend_hold_break_exit"
            if isinstance(command.intent, TrendHoldBreakExitIntent)
            else "core_plus_grid"
        )
        if not isinstance(replay, TradePlanDraft):
            raise PlanValidationError("INVOCATION_CONFLICT")
        replay.validate()
        version = replay.proposed_graph.version
        if (
            replay.status != "open"
            or replay.account_id != command.account_id
            or replay.content.get("research_workflow_run_id") != command.workflow_run_id
            or replay.content.get("recent_trend_assessment_id")
            != command.recent_trend_assessment_id
            or replay.content.get("strategy_key") != command.strategy_key
            or command.strategy_key != expected_strategy_key
            or replay.content.get("authoring_intent_hash")
            != canonical_hash(command.intent)
            or version.horizon_end != command.intent.horizon_end
            or version.review_by != command.intent.review_by
            or replay.updated_at != command.created_at
            or replay.decision_actor != command.actor.decision_actor
            or replay.interaction_channel != command.actor.interaction_channel
            or replay.transport_actor != command.actor.transport_actor
        ):
            raise PlanValidationError("INVOCATION_CONFLICT")
        return replay

    def _select_strategy(self, strategy_key: str) -> StrategyVersion:
        catalog = self._strategies.get(GetStrategyCatalog())
        if not isinstance(catalog, tuple):
            raise PlanValidationError("PLAN_AUTHORING_STRATEGY_NOT_SELECTABLE")
        selected = tuple(
            strategy
            for strategy in catalog
            if isinstance(strategy, StrategyVersion)
            and strategy.strategy_key == strategy_key
        )
        if len(selected) != 1:
            raise PlanValidationError("PLAN_AUTHORING_STRATEGY_NOT_SELECTABLE")
        return selected[0]

    def _resolve_target(
        self,
        *,
        account_id: str,
        security_id: str,
        strategy: StrategyVersion,
    ) -> _PlanAuthoringTarget:
        plan_id = TradePlanMasterId.derive(account_id, security_id).value
        open_draft = self._drafts.get_open(account_id, security_id)
        if open_draft is not None:
            if not isinstance(open_draft, TradePlanDraft):
                raise PlanValidationError("PLAN_AUTHORING_OPEN_DRAFT_INVALID")
            open_draft.validate()
            proposed = open_draft.proposed_graph.version
            if (
                open_draft.status != "open"
                or open_draft.plan_id != plan_id
                or open_draft.account_id != account_id
                or open_draft.security_id != security_id
                or open_draft.strategy_version_id != strategy.strategy_version_id
            ):
                raise PlanValidationError("PLAN_AUTHORING_PLAN_MASTER_MISMATCH")
            return _PlanAuthoringTarget(
                plan_id=plan_id,
                version_no=proposed.version_no,
                supersedes_version_id=(proposed.supersedes_version_id),
            )
        try:
            active = self._drafts.get_active(account_id, security_id)
        except PlanValidationError as error:
            if error.code != "ACTIVE_PLAN_NOT_FOUND":
                raise
            active = None
        if active is None:
            return _PlanAuthoringTarget(plan_id, 1, None)
        if not isinstance(active, ActiveTradePlan):
            raise PlanValidationError("PLAN_AUTHORING_ACTIVE_PLAN_INVALID")
        active.master.validate()
        version = active.version
        if version is None or active.activation is None:
            raise PlanValidationError("PLAN_AUTHORING_ACTIVE_VERSION_REQUIRED")
        version.validate()
        if (
            active.master.lifecycle_status != "active"
            or active.master.plan_id.value != plan_id
            or active.master.plan_id.account_id != account_id
            or active.master.plan_id.security_id != security_id
            or active.master.strategy_version_id != strategy.strategy_version_id
            or version.plan_id != plan_id
            or version.strategy_version_id != strategy.strategy_version_id
            or active.activation.plan_id != plan_id
            or active.activation.plan_version_id != version.plan_version_id
        ):
            raise PlanValidationError("PLAN_AUTHORING_PLAN_MASTER_MISMATCH")
        return _PlanAuthoringTarget(
            plan_id=plan_id,
            version_no=version.version_no + 1,
            supersedes_version_id=version.plan_version_id,
        )

    def _validate_authorities(
        self,
        *,
        command: _CompileTradePlanDraft,
        decision_payload: DecisionViewPayload,
        decision_view: ResearchDecisionView,
        trend: RecentTrendAssessment,
        account: AccountSnapshotVersion,
        risk_policy: PortfolioRiskPolicyVersion,
        strategy: StrategyVersion,
    ) -> None:
        del decision_payload
        if not isinstance(trend, RecentTrendAssessment):
            raise PlanValidationError("PLAN_AUTHORING_RECENT_TREND_REQUIRED")
        trend.validate()
        trend_binding = _bound_recent_trend(decision_view)
        try:
            trend_session = date.fromisoformat(trend.as_of_session)
            research_as_of = date.fromisoformat(decision_view.as_of)
        except ValueError as error:
            raise PlanValidationError(
                "PLAN_AUTHORING_TREND_IDENTITY_MISMATCH"
            ) from error
        if (
            trend.assessment_id != command.recent_trend_assessment_id
            or trend.assessment_id != trend_binding["assessment_id"]
            or trend.content_hash != trend_binding["content_hash"]
            or trend.evidence_refs != trend_binding["source_member_ids"]
            or trend.security_id != decision_view.security_id
            or trend.data_snapshot_id != decision_view.data_snapshot_id
            or trend.as_of_session != trend_binding["as_of_session"]
            or trend_session > research_as_of
            or trend.price_basis != "unadjusted_close"
            or trend.status != "complete"
        ):
            raise PlanValidationError("PLAN_AUTHORING_TREND_IDENTITY_MISMATCH")
        if (
            not isinstance(account, AccountSnapshotVersion)
            or account.account_id != command.account_id
            or not account.confirmed_by.startswith("user:")
            or account.currency != "CNY"
            or account.session_semantics != "complete_session"
        ):
            raise PlanValidationError("PLAN_AUTHORING_ACCOUNT_AUTHORITY_INVALID")
        if not isinstance(risk_policy, PortfolioRiskPolicyVersion):
            raise PlanValidationError("PLAN_AUTHORING_RISK_POLICY_AUTHORITY_INVALID")
        self._risk_service.verify(risk_policy)
        if (
            risk_policy.account_id != account.account_id
            or risk_policy.currency != account.currency
        ):
            raise PlanValidationError("PLAN_AUTHORING_RISK_POLICY_ACCOUNT_MISMATCH")
        if (
            not isinstance(strategy, StrategyVersion)
            or strategy.strategy_key != command.strategy_key
        ):
            raise PlanValidationError("PLAN_AUTHORING_STRATEGY_AUTHORITY_INVALID")
        strategy.validate_integrity()
        expected_strategy_key = (
            "trend_hold_break_exit"
            if isinstance(command.intent, TrendHoldBreakExitIntent)
            else "core_plus_grid"
        )
        if (
            strategy.status != "active"
            or not strategy.publicly_selectable
            or strategy.strategy_definition.authoring_mode != "built_in"
            or strategy.strategy_key != expected_strategy_key
        ):
            raise PlanValidationError("PLAN_AUTHORING_STRATEGY_NOT_SELECTABLE")
        self._validate_temporal_authority(
            command, decision_view, account, risk_policy, strategy
        )

    @staticmethod
    def _validate_temporal_authority(
        command: _CompileTradePlanDraft,
        decision_view: ResearchDecisionView,
        account: AccountSnapshotVersion,
        risk_policy: PortfolioRiskPolicyVersion,
        strategy: StrategyVersion,
    ) -> None:
        try:
            research_as_of = date.fromisoformat(decision_view.as_of)
            if account.as_of_precision == "date":
                account_as_of_date = date.fromisoformat(account.as_of_at)
                account_as_of = None
            elif account.as_of_precision == "instant":
                account_as_of = datetime.fromisoformat(account.as_of_at)
                account_as_of_date = account_as_of.date()
            else:
                raise ValueError("unsupported account as-of precision")
            account_confirmed = datetime.fromisoformat(account.confirmed_at)
            policy_confirmed = datetime.fromisoformat(risk_policy.confirmed_at)
            strategy_created = datetime.fromisoformat(strategy.created_at)
            created = datetime.fromisoformat(command.created_at)
        except ValueError as error:
            raise PlanValidationError(
                "PLAN_AUTHORING_TEMPORAL_AUTHORITY_INVALID"
            ) from error
        if (
            (account_as_of is not None and account_as_of.tzinfo is None)
            or account_confirmed.tzinfo is None
            or policy_confirmed.tzinfo is None
            or strategy_created.tzinfo is None
            or account_as_of_date > research_as_of
            or created.date() < research_as_of
            or account_confirmed > created
            or policy_confirmed > created
            or strategy_created > created
        ):
            raise PlanValidationError("PLAN_AUTHORING_TEMPORAL_AUTHORITY_INVALID")

    def _compile_trend_draft(
        self,
        *,
        command: _CompileTradePlanDraft,
        decision_payload: DecisionViewPayload,
        decision_view: ResearchDecisionView,
        trend: RecentTrendAssessment,
        account: AccountSnapshotVersion,
        risk_policy: PortfolioRiskPolicyVersion,
        strategy: StrategyVersion,
        target: _PlanAuthoringTarget,
    ) -> _UpsertOpenTradePlanDraft:
        intent = command.intent
        total_quantity = _position_quantity(account, decision_view.security_id)
        candidate = intent.candidate_decrease_quantity
        if intent.core_floor_quantity > total_quantity or (
            candidate is not None
            and total_quantity - candidate < intent.core_floor_quantity
        ):
            raise PlanValidationError("PLAN_AUTHORING_CORE_FLOOR_EXCEEDS_POSITION")
        nav = _known_decimal(
            account.nav_state,
            account.nav_value,
            "PLAN_AUTHORING_ACCOUNT_NAV_INVALID",
        )
        single_security_limit = (
            None
            if nav is None
            else nav * _required_limit(risk_policy.limits.single_security_exposure)
        )
        single_plan_loss = (
            None
            if nav is None
            else nav * _required_limit(risk_policy.limits.single_plan_loss)
        )
        assert trend.close is not None
        assert trend.window_low_20 is not None
        core = CoreSleeve(
            sleeve_id=_identity(
                "position_sleeve",
                account.account_id,
                decision_view.security_id,
                strategy.strategy_version_id,
                "core",
            ),
            quantity_budget=total_quantity,
            core_floor=CoreFloor(intent.core_floor_quantity),
            max_notional=single_security_limit,
            max_loss=single_plan_loss,
        )
        validate_sleeve_quantities(
            (core,),
            total_quantity=total_quantity,
            remaining_quantity=total_quantity,
            candidate_grid_decrease=None,
        )
        parameters = _trend_parameters(intent)
        strategy.validate_parameters(parameters)
        candidate_intent = _candidate_intent(
            total_quantity=total_quantity,
            decrease_quantity=candidate,
            close=trend.close,
            assessment=trend,
        )
        rules = _trend_rules(
            plan_owner=(account.account_id, decision_view.security_id),
            sleeve_id=core.sleeve_id,
            break_below=trend.window_low_20,
            break_confirmation_sessions=(intent.break_confirmation_sessions),
            core_floor=intent.core_floor_quantity,
            candidate=candidate_intent,
        )
        references = _evidence_references(
            decision_payload=decision_payload,
            decision_view=decision_view,
            trend=trend,
            account=account,
            risk_policy=risk_policy,
            strategy=strategy,
        )
        identity = canonical_hash(
            {
                "schema_version": command.schema_version,
                "workflow_run_id": command.workflow_run_id,
                "recent_trend_assessment_id": trend.assessment_id,
                "account_snapshot_version_id": (account.account_snapshot_version_id),
                "portfolio_risk_policy_version_id": (
                    risk_policy.portfolio_risk_policy_version_id
                ),
                "strategy_version_id": strategy.strategy_version_id,
                "plan_id": target.plan_id,
                "version_no": target.version_no,
                "supersedes_version_id": target.supersedes_version_id,
                "intent": intent,
            }
        )
        risk_limits = {
            field.name: self._risk_service.render_decimal(
                _required_limit(getattr(risk_policy.limits, field.name))
            )
            for field in fields(risk_policy.limits)
        }
        current_notional = total_quantity * trend.close
        content = {
            "schema_version": "TradePlanContent@1",
            "authoring_schema_version": command.schema_version,
            "authoring_input_hash": identity,
            "authoring_intent_hash": canonical_hash(intent),
            "research_workflow_run_id": command.workflow_run_id,
            "research_view_id": decision_view.view_id,
            "recent_trend_assessment_id": trend.assessment_id,
            "account_snapshot_version_id": (account.account_snapshot_version_id),
            "portfolio_risk_policy_version_id": (
                risk_policy.portfolio_risk_policy_version_id
            ),
            "strategy_version_id": strategy.strategy_version_id,
            "strategy_key": strategy.strategy_key,
            "strategy_parameters": parameters,
            "observed_trend": {
                "classification": trend.classification,
                "close": str(trend.close),
                "window_low_20": str(trend.window_low_20),
                "price_basis": trend.price_basis,
            },
            "risk_policy_limits": risk_limits,
            "risk_budget_state": (
                "account_nav_unknown"
                if single_security_limit is None
                else (
                    "requires_review"
                    if current_notional > single_security_limit
                    else "within_limit"
                )
            ),
        }
        graph = build_trade_plan_draft_graph(
            plan_version_id=f"trade_plan_version_{identity[:24]}",
            plan_id=target.plan_id,
            version_no=target.version_no,
            supersedes_version_id=target.supersedes_version_id,
            strategy_version_id=strategy.strategy_version_id,
            investment_thesis_version_id=None,
            account_snapshot_version_id=(account.account_snapshot_version_id),
            data_snapshot_id=decision_view.data_snapshot_id,
            horizon_start=decision_view.as_of,
            horizon_end=intent.horizon_end,
            review_by=intent.review_by,
            risk_policy_version_id=(risk_policy.portfolio_risk_policy_version_id),
            metric_catalog_version="metric-catalog@2",
            evaluator_policy_version="plan-evaluator@2",
            content=content,
            sleeves=(core,),
            rules=rules,
            evidence_references=references,
            adjusted_price_evidence=(),
        )
        return _UpsertOpenTradePlanDraft(
            invocation_id=command.invocation_id,
            account_id=account.account_id,
            security_id=decision_view.security_id,
            proposed_graph=graph,
            parameters=parameters,
            updated_at=command.created_at,
            actor=command.actor,
        )

    def _compile_grid_draft(
        self,
        *,
        command: _CompileTradePlanDraft,
        decision_payload: DecisionViewPayload,
        decision_view: ResearchDecisionView,
        trend: RecentTrendAssessment,
        account: AccountSnapshotVersion,
        risk_policy: PortfolioRiskPolicyVersion,
        strategy: StrategyVersion,
        target: _PlanAuthoringTarget,
    ) -> _UpsertOpenTradePlanDraft:
        intent = command.intent
        if not isinstance(intent, CorePlusGridIntent):
            raise PlanValidationError("PLAN_AUTHORING_INTENT_INVALID")
        grid_research_evidence = _require_grid_research_evidence(decision_view)
        total_quantity = _position_quantity(account, decision_view.security_id)
        if (
            intent.core_floor_quantity > total_quantity
            or intent.grid_total_quantity_budget
            > total_quantity - intent.core_floor_quantity
        ):
            raise PlanValidationError("PLAN_AUTHORING_GRID_BUDGET_EXCEEDS_POSITION")
        nav = _known_decimal(
            account.nav_state,
            account.nav_value,
            "PLAN_AUTHORING_ACCOUNT_NAV_INVALID",
        )
        max_notional = (
            None
            if nav is None
            else nav * _required_limit(risk_policy.limits.single_security_exposure)
        )
        max_loss = (
            None
            if nav is None
            else nav * _required_limit(risk_policy.limits.single_plan_loss)
        )
        core_budget = total_quantity - intent.grid_total_quantity_budget
        core_share = core_budget / total_quantity
        grid_share = intent.grid_total_quantity_budget / total_quantity
        core_floor = CoreFloor(intent.core_floor_quantity)
        constraint = GridConstraint(
            grid_constraint_id=_identity(
                "grid_constraint",
                account.account_id,
                decision_view.security_id,
                strategy.strategy_version_id,
            ),
            lower_price=intent.grid_lower_price,
            upper_price=intent.grid_upper_price,
            level_count=intent.grid_level_count,
            quantity_per_level=intent.grid_quantity_per_level,
            total_quantity_budget=intent.grid_total_quantity_budget,
            price_basis="unadjusted",
            trigger_mode=intent.grid_trigger_mode,
            cooldown_trading_sessions=(intent.cooldown_trading_sessions),
        )
        core = CoreSleeve(
            sleeve_id=_identity(
                "position_sleeve",
                account.account_id,
                decision_view.security_id,
                strategy.strategy_version_id,
                "core",
            ),
            quantity_budget=core_budget,
            core_floor=core_floor,
            max_notional=(None if max_notional is None else max_notional * core_share),
            max_loss=None if max_loss is None else max_loss * core_share,
        )
        grid = GridSleeve(
            sleeve_id=_identity(
                "position_sleeve",
                account.account_id,
                decision_view.security_id,
                strategy.strategy_version_id,
                "grid",
            ),
            quantity_budget=intent.grid_total_quantity_budget,
            core_floor=core_floor,
            max_notional=(None if max_notional is None else max_notional * grid_share),
            max_loss=None if max_loss is None else max_loss * grid_share,
            constraint=constraint,
        )
        sleeves = (core, grid)
        validate_sleeve_quantities(
            sleeves,
            total_quantity=total_quantity,
        )
        parameters = _grid_parameters(intent, account)
        strategy.validate_parameters(parameters)
        rules = _grid_rules(
            plan_owner=(account.account_id, decision_view.security_id),
            core_sleeve_id=core.sleeve_id,
            grid_sleeve_id=grid.sleeve_id,
            constraint=constraint,
            core_floor=intent.core_floor_quantity,
        )
        references = _evidence_references(
            decision_payload=decision_payload,
            decision_view=decision_view,
            trend=trend,
            account=account,
            risk_policy=risk_policy,
            strategy=strategy,
        )
        identity = canonical_hash(
            {
                "schema_version": command.schema_version,
                "workflow_run_id": command.workflow_run_id,
                "recent_trend_assessment_id": trend.assessment_id,
                "account_snapshot_version_id": (account.account_snapshot_version_id),
                "portfolio_risk_policy_version_id": (
                    risk_policy.portfolio_risk_policy_version_id
                ),
                "strategy_version_id": strategy.strategy_version_id,
                "plan_id": target.plan_id,
                "version_no": target.version_no,
                "supersedes_version_id": target.supersedes_version_id,
                "intent": intent,
            }
        )
        risk_limits = {
            field.name: self._risk_service.render_decimal(
                _required_limit(getattr(risk_policy.limits, field.name))
            )
            for field in fields(risk_policy.limits)
        }
        assert trend.close is not None
        content = {
            "schema_version": "TradePlanContent@1",
            "authoring_schema_version": command.schema_version,
            "authoring_input_hash": identity,
            "authoring_intent_hash": canonical_hash(intent),
            "research_workflow_run_id": command.workflow_run_id,
            "research_view_id": decision_view.view_id,
            "recent_trend_assessment_id": trend.assessment_id,
            "account_snapshot_version_id": (account.account_snapshot_version_id),
            "portfolio_risk_policy_version_id": (
                risk_policy.portfolio_risk_policy_version_id
            ),
            "strategy_version_id": strategy.strategy_version_id,
            "strategy_key": strategy.strategy_key,
            "strategy_parameters": parameters,
            "risk_increase_evidence": {
                "valuation_status": decision_view.valuation_view["status"],
                "formal_per_share_valuation": True,
                "scenario_roles": ("stress", "base", "improvement"),
                **grid_research_evidence,
            },
            "risk_policy_limits": risk_limits,
            "risk_budget_state": (
                "account_nav_unknown"
                if max_notional is None
                else (
                    "requires_review"
                    if total_quantity * trend.close > max_notional
                    else "within_limit"
                )
            ),
        }
        graph = build_trade_plan_draft_graph(
            plan_version_id=f"trade_plan_version_{identity[:24]}",
            plan_id=target.plan_id,
            version_no=target.version_no,
            supersedes_version_id=target.supersedes_version_id,
            strategy_version_id=strategy.strategy_version_id,
            investment_thesis_version_id=None,
            account_snapshot_version_id=(account.account_snapshot_version_id),
            data_snapshot_id=decision_view.data_snapshot_id,
            horizon_start=decision_view.as_of,
            horizon_end=intent.horizon_end,
            review_by=intent.review_by,
            risk_policy_version_id=(risk_policy.portfolio_risk_policy_version_id),
            metric_catalog_version="metric-catalog@2",
            evaluator_policy_version="plan-evaluator@2",
            content=content,
            sleeves=sleeves,
            rules=rules,
            evidence_references=references,
            adjusted_price_evidence=(),
        )
        return _UpsertOpenTradePlanDraft(
            invocation_id=command.invocation_id,
            account_id=account.account_id,
            security_id=decision_view.security_id,
            proposed_graph=graph,
            parameters=parameters,
            updated_at=command.created_at,
            actor=command.actor,
        )

    def _load_decision_view(
        self, workflow_run_id: str
    ) -> tuple[DecisionViewPayload, ResearchDecisionView]:
        payload = self._research.decision_view(workflow_run_id)
        if not isinstance(payload, DecisionViewPayload) or not all(
            (
                payload.manifest_id,
                payload.json_artifact_id,
                payload.html_artifact_id,
                payload.pdf_artifact_id,
            )
        ):
            raise PlanValidationError("PLAN_AUTHORING_RESEARCH_ARTIFACT_INVALID")
        try:
            decoded = json.loads(payload.json_bytes)
            if not isinstance(decoded, Mapping):
                raise ResearchViewError("RESEARCH_VIEW_FIELDS_INVALID")
            view = ResearchDecisionView.from_dict(decoded)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ResearchViewError,
        ) as error:
            raise PlanValidationError("PLAN_AUTHORING_RESEARCH_VIEW_INVALID") from error
        if (
            view.workflow_run_id != workflow_run_id
            or view.subject_id != view.security_id
            or view.data_snapshot_id != view.model_data_snapshot_identity
            or view.status not in {"completed", "completed_with_limits"}
        ):
            raise PlanValidationError("PLAN_AUTHORING_RESEARCH_IDENTITY_MISMATCH")
        try:
            date.fromisoformat(view.as_of)
        except ValueError as error:
            raise PlanValidationError(
                "PLAN_AUTHORING_RESEARCH_AS_OF_INVALID"
            ) from error
        return payload, view


def _bound_recent_trend(
    view: ResearchDecisionView,
) -> Mapping[str, object]:
    summary = view.audit.get("recent_trend_assessment")
    if not isinstance(summary, Mapping):
        raise PlanValidationError("PLAN_AUTHORING_TREND_IDENTITY_MISMATCH")
    assessment = summary.get("assessment")
    source_member_ids = summary.get("source_member_ids")
    if (
        summary.get("schema_version") != "ResearchComponentResult@1"
        or summary.get("component") != "recent_trend_assessment"
        or summary.get("status") != "complete"
        or not isinstance(summary.get("artifact_id"), str)
        or not summary["artifact_id"]
        or not isinstance(assessment, Mapping)
        or not isinstance(source_member_ids, (list, tuple))
        or not isinstance(assessment.get("assessment_id"), str)
        or not isinstance(assessment.get("as_of_session"), str)
        or not isinstance(assessment.get("content_hash"), str)
    ):
        raise PlanValidationError("PLAN_AUTHORING_TREND_IDENTITY_MISMATCH")
    return {
        "assessment_id": assessment["assessment_id"],
        "as_of_session": assessment["as_of_session"],
        "content_hash": assessment["content_hash"],
        "source_member_ids": tuple(str(value) for value in source_member_ids),
    }


def _require_grid_research_evidence(
    view: ResearchDecisionView,
) -> Mapping[str, str]:
    valuation_status = view.valuation_view.get("status")
    formal_valuation = view.valuation_view.get("formal_per_share_valuation")
    scenario_roles = {
        role
        for scenario in view.scenarios
        if isinstance(scenario, Mapping)
        for role in (_scenario_role(scenario),)
        if role is not None
    }
    bundle = view.audit.get("evaluation_bundle")
    components = bundle.get("components") if isinstance(bundle, Mapping) else None
    required_components = (
        "forecast",
        "scenario_valuation",
        "valuation_method_route",
    )
    resolved: dict[str, str] = {}
    if isinstance(components, Mapping):
        for name in required_components:
            component = components.get(name)
            if (
                not isinstance(component, Mapping)
                or component.get("schema_version") != "ResearchComponentResult@1"
                or component.get("component") != name
                or component.get("status") != "complete"
                or not isinstance(component.get("artifact_id"), str)
                or not component["artifact_id"]
            ):
                break
            resolved[name] = str(component["artifact_id"])
    if (
        view.status != "completed"
        or valuation_status != "ready"
        or formal_valuation is not True
        or view.data_quality_grade not in {"A", "B", "C"}
        or not view.key_drivers
        or scenario_roles != {"stress", "base", "improvement"}
        or not isinstance(bundle, Mapping)
        or bundle.get("schema_version") != "ResearchEvaluationBundle@1"
        or not isinstance(bundle.get("bundle_id"), str)
        or not bundle["bundle_id"]
        or set(resolved) != set(required_components)
    ):
        raise PlanValidationError("PLAN_AUTHORING_RISK_INCREASE_EVIDENCE_INSUFFICIENT")
    return {
        "research_bundle_id": str(bundle["bundle_id"]),
        "forecast_component_artifact_id": resolved["forecast"],
        "scenario_valuation_component_artifact_id": resolved["scenario_valuation"],
        "valuation_method_route_component_artifact_id": resolved[
            "valuation_method_route"
        ],
    }


def _scenario_role(scenario: Mapping[str, object]) -> str | None:
    for key in ("scenario_role", "role", "scenario_id"):
        value = scenario.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        for role in ("stress", "base", "improvement"):
            if normalized == role or normalized.endswith("_" + role):
                return role
    return None


def _grid_parameters(
    intent: CorePlusGridIntent,
    account: AccountSnapshotVersion,
) -> Mapping[str, object]:
    return {
        "core_floor_quantity": (
            PortfolioRiskPolicyService.render_decimal(intent.core_floor_quantity)
        ),
        "grid_lower_price": PortfolioRiskPolicyService.render_decimal(
            intent.grid_lower_price
        ),
        "grid_upper_price": PortfolioRiskPolicyService.render_decimal(
            intent.grid_upper_price
        ),
        "grid_level_count": intent.grid_level_count,
        "grid_quantity_per_level": (
            PortfolioRiskPolicyService.render_decimal(intent.grid_quantity_per_level)
        ),
        "grid_total_quantity_budget": (
            PortfolioRiskPolicyService.render_decimal(intent.grid_total_quantity_budget)
        ),
        "grid_price_basis": "unadjusted",
        "grid_trigger_mode": intent.grid_trigger_mode,
        "cooldown_trading_sessions": intent.cooldown_trading_sessions,
        "cash_operand_policy": (
            "known_required"
            if account.cash_state == "known"
            else "unknown_manual_review_required"
        ),
        "quantity_operand_policy": "known_required",
    }


def _grid_rules(
    *,
    plan_owner: tuple[str, str],
    core_sleeve_id: str,
    grid_sleeve_id: str,
    constraint: GridConstraint,
    core_floor: Decimal,
) -> tuple[TradePlanRule, ...]:
    account_id, security_id = plan_owner
    basis = (account_id, security_id)
    return (
        TradePlanRule.build(
            rule_id=_identity("plan_rule", *basis, "grid_level"),
            rule_class=RuleClass.HARD,
            rule_kind="grid_level_candidate",
            priority=RulePriority.ORDINARY,
            scope=RuleScope.GRID,
            sleeve_id=grid_sleeve_id,
            effect="open_decision_task",
            applies_to="plan",
            candidate_intent=None,
            input_applicability=(
                "security.close_unadjusted",
                "security.previous_close_unadjusted",
            ),
            condition=RuleAstV2(
                node="grid_constraint",
                grid_constraint=constraint,
            ),
        ),
        TradePlanRule.build(
            rule_id=_identity("plan_rule", *basis, "cash_guard"),
            rule_class=RuleClass.HARD,
            rule_kind="cash_quantity_guard",
            priority=RulePriority.RISK,
            scope=RuleScope.MASTER,
            sleeve_id=None,
            effect="block_grid_candidate_when_cash_unknown",
            applies_to="plan",
            candidate_intent=None,
            input_applicability=("account.cash",),
            condition=RuleAstV2(
                node="comparison",
                operand_id="account.cash",
                operator="gte",
                expected=Decimal("0"),
            ),
        ),
        TradePlanRule.build(
            rule_id=_identity("plan_rule", *basis, "core_floor"),
            rule_class=RuleClass.HARD,
            rule_kind="core_floor_precedence",
            priority=RulePriority.CORE_FLOOR,
            scope=RuleScope.CORE,
            sleeve_id=core_sleeve_id,
            effect="block_candidate_below_core_floor",
            applies_to="decrease",
            candidate_intent=None,
            input_applicability=("account.remaining_quantity",),
            condition=RuleAstV2(
                node="comparison",
                operand_id="account.remaining_quantity",
                operator="gte",
                expected=core_floor,
            ),
        ),
    )


def _trend_parameters(
    intent: TrendHoldBreakExitIntent,
) -> Mapping[str, object]:
    return {
        "price_basis": "unadjusted",
        "trend_metric_ref": "security.close_unadjusted",
        "break_condition": {
            "ast_version": "plan-rule-ast@2",
            "session_scope": "complete_session",
        },
        "break_confirmation_sessions": (intent.break_confirmation_sessions),
        "core_floor_quantity": (
            PortfolioRiskPolicyService.render_decimal(intent.core_floor_quantity)
        ),
        "invalidation_review_rule_ids": ("thesis_invalidation_review",),
        "candidate_decrease_quantity": {
            "state": (
                "known" if intent.candidate_decrease_quantity is not None else "unknown"
            ),
            "value": (
                None
                if intent.candidate_decrease_quantity is None
                else PortfolioRiskPolicyService.render_decimal(
                    intent.candidate_decrease_quantity
                )
            ),
        },
        "review_by": intent.review_by,
    }


def _trend_rules(
    *,
    plan_owner: tuple[str, str],
    sleeve_id: str,
    break_below: Decimal,
    break_confirmation_sessions: int,
    core_floor: Decimal,
    candidate: CandidateIntent,
) -> tuple[TradePlanRule, ...]:
    account_id, security_id = plan_owner
    basis = (account_id, security_id)
    return (
        TradePlanRule.build(
            rule_id=_identity("plan_rule", *basis, "trend_break"),
            rule_class=RuleClass.HARD,
            rule_kind="trend_break_candidate",
            priority=RulePriority.ORDINARY,
            scope=RuleScope.CORE,
            sleeve_id=sleeve_id,
            effect="open_decision_task",
            applies_to="decrease",
            candidate_intent=candidate,
            input_applicability=(
                "security.close_unadjusted",
                "event.session",
            ),
            condition=RuleAstV2(
                node="all",
                children=(
                    RuleAstV2(
                        node="comparison",
                        operand_id="security.close_unadjusted",
                        operator="lt",
                        expected=break_below,
                    ),
                    RuleAstV2(
                        node="elapsed_trading_sessions",
                        operand_id="event.session",
                        threshold_sessions=(break_confirmation_sessions - 1),
                    ),
                ),
            ),
        ),
        TradePlanRule.build(
            rule_id=_identity("plan_rule", *basis, "thesis_invalidation"),
            rule_class=RuleClass.REVIEW,
            rule_kind="thesis_invalidation_review",
            priority=RulePriority.INVALIDATION,
            scope=RuleScope.MASTER,
            sleeve_id=None,
            effect="open_plan_review",
            applies_to="plan",
            candidate_intent=None,
            input_applicability=("event.session",),
            condition=RuleAstV2(
                node="event_window",
                event_type="thesis_invalidated",
            ),
        ),
        TradePlanRule.build(
            rule_id=_identity("plan_rule", *basis, "core_floor"),
            rule_class=RuleClass.HARD,
            rule_kind="core_floor_precedence",
            priority=RulePriority.CORE_FLOOR,
            scope=RuleScope.CORE,
            sleeve_id=sleeve_id,
            effect="block_candidate_below_core_floor",
            applies_to="decrease",
            candidate_intent=None,
            input_applicability=("account.remaining_quantity",),
            condition=RuleAstV2(
                node="comparison",
                operand_id="account.remaining_quantity",
                operator="gte",
                expected=core_floor,
            ),
        ),
    )


def _candidate_intent(
    *,
    total_quantity: Decimal,
    decrease_quantity: Decimal | None,
    close: Decimal,
    assessment: RecentTrendAssessment,
) -> CandidateIntent:
    state = (
        OperandState.KNOWN if decrease_quantity is not None else OperandState.UNKNOWN
    )
    reason = (
        None
        if decrease_quantity is not None
        else "CANDIDATE_QUANTITY_REQUIRES_USER_REVIEW"
    )
    remaining = (
        total_quantity - decrease_quantity if decrease_quantity is not None else None
    )
    notional = decrease_quantity * close if decrease_quantity is not None else None
    common = {
        "value_state": state,
        "as_of_identity": assessment.assessment_id,
        "evidence_refs": assessment.evidence_refs,
        "reason_code": reason,
    }
    candidate = CandidateIntent(
        intent_id=_identity(
            "candidate_intent",
            assessment.assessment_id,
            "trend_break",
        ),
        direction="decrease",
        quantity=OperandValue(
            operand_id="candidate.quantity",
            value=decrease_quantity,
            unit="share",
            currency=None,
            **common,
        ),
        remaining_quantity=OperandValue(
            operand_id="candidate.remaining_quantity",
            value=remaining,
            unit="share",
            currency=None,
            **common,
        ),
        notional=OperandValue(
            operand_id="candidate.notional",
            value=notional,
            unit="CNY",
            currency="CNY",
            **common,
        ),
    )
    candidate.validate()
    return candidate


def _evidence_references(
    *,
    decision_payload: DecisionViewPayload,
    decision_view: ResearchDecisionView,
    trend: RecentTrendAssessment,
    account: AccountSnapshotVersion,
    risk_policy: PortfolioRiskPolicyVersion,
    strategy: StrategyVersion,
) -> tuple[Mapping[str, object], ...]:
    return (
        _reference(
            "ResearchDecisionView",
            decision_view.view_id,
            workflow_run_id=decision_view.workflow_run_id,
            artifact_manifest_id=decision_payload.manifest_id,
            artifact_id=decision_payload.json_artifact_id,
            source_content_hash=canonical_hash(decision_view.to_dict()),
        ),
        _reference(
            "RecentTrendAssessment",
            trend.assessment_id,
            source_content_hash=trend.content_hash,
        ),
        _reference(
            "AccountSnapshotVersion",
            account.account_snapshot_version_id,
            source_content_hash=account.content_hash,
        ),
        _reference(
            "PortfolioRiskPolicyVersion",
            risk_policy.portfolio_risk_policy_version_id,
            source_content_hash=risk_policy.identity_hash,
        ),
        _reference(
            "StrategyVersion",
            strategy.strategy_version_id,
            source_content_hash=strategy.content_hash,
        ),
    )


def _reference(
    ref_type: str,
    ref_id: str,
    **details: object,
) -> Mapping[str, object]:
    content = {
        "ref_type": ref_type,
        "ref_id": ref_id,
        "resolution_status": "resolved",
        **details,
    }
    return {**content, "content_hash": canonical_hash(content)}


def _position_quantity(
    snapshot: AccountSnapshotVersion,
    security_id: str,
) -> Decimal:
    positions = tuple(
        position
        for position in snapshot.positions
        if position.security_id == security_id
    )
    if len(positions) > 1:
        raise PlanValidationError("PLAN_AUTHORING_ACCOUNT_POSITION_DUPLICATE")
    if not positions:
        return Decimal("0")
    try:
        quantity = Decimal(positions[0].total_quantity)
    except (InvalidOperation, ValueError) as error:
        raise PlanValidationError("PLAN_AUTHORING_ACCOUNT_POSITION_INVALID") from error
    if not _whole_quantity(quantity, allow_zero=True):
        raise PlanValidationError("PLAN_AUTHORING_ACCOUNT_POSITION_INVALID")
    return quantity


def _known_decimal(
    state: str,
    value: str | None,
    error_code: str,
) -> Decimal | None:
    if state != "known":
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise PlanValidationError(error_code) from error
    if not result.is_finite() or result <= 0:
        raise PlanValidationError(error_code)
    return result


def _required_limit(value: Decimal | None) -> Decimal:
    if value is None:
        raise PlanValidationError("PLAN_AUTHORING_RISK_POLICY_LIMIT_UNKNOWN")
    return value


def _whole_quantity(value: object, *, allow_zero: bool) -> bool:
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and (value >= 0 if allow_zero else value > 0)
        and value == value.to_integral_value()
    )


def _identity(prefix: str, *parts: str) -> str:
    return f"{prefix}_{canonical_hash(parts)[:24]}"
