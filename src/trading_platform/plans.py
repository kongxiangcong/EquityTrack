from __future__ import annotations

from dataclasses import asdict
from typing import Protocol

from trading_platform.domain.plans import (
    ActivatePlanVersionCommand, ActivePlanView, ChangePlanLifecycleCommand,
    ConfirmPlanDraftCommand, CreatePlanDraftCommand, DiscardPlanDraftCommand,
    PlanConfirmationSection, PlanConfirmationView, PlanDiffItem, PlanDraftContent,
    PlanValidationError as PlanError, TradePlanDraftView, TradePlanVersionView,
    UpdatePlanDraftCommand,
)


class PlanRepository(Protocol):
    def validate_content(self, content: PlanDraftContent) -> None: ...
    def create_draft(self, command: CreatePlanDraftCommand) -> TradePlanDraftView: ...
    def update_draft(self, command: UpdatePlanDraftCommand) -> TradePlanDraftView: ...
    def discard_draft(self, command: DiscardPlanDraftCommand) -> TradePlanDraftView: ...
    def confirm_draft(self, command: ConfirmPlanDraftCommand) -> TradePlanVersionView: ...
    def activate_version(self, command: ActivatePlanVersionCommand) -> TradePlanVersionView: ...
    def deactivate(self, command: ChangePlanLifecycleCommand) -> ActivePlanView: ...
    def end(self, command: ChangePlanLifecycleCommand) -> ActivePlanView: ...
    def get_draft(self, draft_id: str) -> TradePlanDraftView: ...
    def get_version(self, version_id: str) -> TradePlanVersionView: ...
    def get_active_for_security(self, security_id: str) -> ActivePlanView: ...
    def get_lifecycle(self, plan_id: str) -> ActivePlanView: ...


class PlanService:
    """Application use cases for user-authored plan drafts and immutable versions."""

    def __init__(self, repository: PlanRepository) -> None:
        self.repository = repository

    def create_draft(self, command: CreatePlanDraftCommand) -> TradePlanDraftView:
        self.repository.validate_content(command.content)
        return self.repository.create_draft(command)

    def update_draft(self, command: UpdatePlanDraftCommand) -> TradePlanDraftView:
        self.repository.validate_content(command.content)
        return self.repository.update_draft(command)

    def discard_draft(self, command: DiscardPlanDraftCommand) -> TradePlanDraftView:
        return self.repository.discard_draft(command)

    def confirm_draft(self, command: ConfirmPlanDraftCommand) -> TradePlanVersionView:
        draft = self.repository.get_draft(command.draft_id)
        self.repository.validate_content(draft.content)
        return self.repository.confirm_draft(command)

    def activate_version(self, command: ActivatePlanVersionCommand) -> TradePlanVersionView:
        return self.repository.activate_version(command)

    def deactivate(self, command: ChangePlanLifecycleCommand) -> ActivePlanView:
        return self.repository.deactivate(command)

    def end(self, command: ChangePlanLifecycleCommand) -> ActivePlanView:
        return self.repository.end(command)

    def get_draft(self, draft_id: str) -> TradePlanDraftView:
        return self.repository.get_draft(draft_id)

    def get_version(self, version_id: str) -> TradePlanVersionView:
        return self.repository.get_version(version_id)

    def get_active_for_security(self, security_id: str) -> ActivePlanView:
        return self.repository.get_active_for_security(security_id)

    def get_lifecycle(self, plan_id: str) -> ActivePlanView:
        return self.repository.get_lifecycle(plan_id)

    def confirmation(self, draft_id: str) -> PlanConfirmationView:
        draft = self.repository.get_draft(draft_id)
        if draft.status != "open":
            raise PlanError("PLAN_DRAFT_NOT_OPEN")
        if draft.content.based_on_version_id:
            before = asdict(self.repository.get_version(draft.content.based_on_version_id).content)
            after = asdict(draft.content)
            diff = tuple(PlanDiffItem(key, before.get(key), after.get(key)) for key in sorted(after) if before.get(key) != after.get(key))
        else:
            diff = (PlanDiffItem("initial_version", None, "v1"),)
        content = draft.content
        sections = (
            PlanConfirmationSection("basis_and_horizon", (("security_id", content.security_id), ("references", content.references), ("data_snapshot_id", content.data_snapshot_id), ("horizon_start", content.horizon_start), ("horizon_end", content.horizon_end), ("review_by", content.review_by), ("rationale", content.rationale))),
            PlanConfirmationSection("rules", (("rules", content.rules), ("metric_catalog_version", content.metric_catalog_version), ("evaluator_policy_version", content.evaluator_policy_version))),
            PlanConfirmationSection("risk_budget", (("currency", content.currency), ("max_planned_notional", content.max_planned_notional), ("max_planned_loss", content.max_planned_loss), ("portfolio_feasibility", "not_applicable_no_account_or_position"))),
            PlanConfirmationSection("market_gates", (("market_gate_policy_version", content.market_gate_policy_version), ("market_gate_rules", tuple(rule for rule in content.rules if rule.rule_kind == "market_gate")))),
        )
        return PlanConfirmationView(draft_id, content, draft.content_hash, sections, diff, content.user_input_source, "records_user_rules_only_no_trade_execution", "not_applicable_no_account_or_position")


__all__ = ["PlanError", "PlanService"]
