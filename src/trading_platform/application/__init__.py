"""Canonical public application task and command interface."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .account_state import (
        AccountStateQueries,
        CompareConfirmedAccountState,
        GetEstimatedAccountState,
    )
    from .strategy_catalog import (
        GetStrategyCatalog,
        GetStrategyVersion,
        StrategyQueries,
    )
    from .trade_plan_authoring import (
        ConfirmTradePlanVersion,
        CreateTradePlanDraft,
        GetActiveTradePlan,
        GetTradePlanGraph,
        IssuePlanConfirmationChallenge,
        PlanCommandActor,
        PlanConfirmationResult,
        RejectTradePlanDraft,
        ReviseTradePlanDraft,
        TradePlanTasks,
    )
    from .account_snapshots import (
        AccountSnapshotCommands,
        AccountSnapshotQueries,
        ConfirmAccountSnapshot,
        CreateAccountSnapshotDraft,
        GetAccountSnapshot,
        UpdateAccountSnapshotDraft,
    )
    from .command_envelope import (
        ApplicationCommandEnvelopeV1,
        ApprovalCapability,
        CommandEnvelopeError,
        DecisionActor,
        InteractionChannel,
        TransportActor,
    )
    from .commands import (
        ApplicationCommandDispatcher,
        ApplicationCommandFailure,
        ApplicationCommandResult,
    )
    from .browser_acceptance import BrowserAcceptanceFixtureResult
    from .bootstrap import (
        open_acceptance_evidence,
        open_account_current_export,
        open_account_snapshot_commands,
        open_account_snapshot_queries,
        open_application_commands,
        open_account_state_queries,
        open_strategy_queries,
        open_account_acceptance,
        open_account_history,
        open_daily_research_cycle,
        open_data_synchronization,
        open_import_preview,
        open_chart_annotations,
        open_chart_workspace,
        open_browser_acceptance_fixture,
        open_decision_workspace,
        open_market,
        open_platform_health,
        open_platform_operations,
        open_project_verification,
        open_provider_qualification,
        open_research_archive,
        open_research_workflow,
        open_server_runtime,
        open_watchlist,
        open_trade_plan,
        open_update_authorizations,
        open_workflow_inspection,
        open_workflow_runtime,
    )
    from .command_codecs import (
        CommandCodecError,
    )
    from .contracts import (
        Capability,
        CapabilityStatus,
        HealthQuery,
        HealthResult,
        ResumeWorkflowCommand,
        SecurityIdentity,
        StartResearchWorkflow,
    )
    from .research_request_codec import decode_research_workflow_request
    from .web_tasks import (
        ChartAnnotations,
        ChartWorkspace,
        DecisionWorkspace,
        UpdateAuthorizations,
        WorkspaceUpdateCommand,
    )

_EXPORT_MODULES = {
    "AccountStateQueries": ".account_state",
    "CompareConfirmedAccountState": ".account_state",
    "GetEstimatedAccountState": ".account_state",
    "GetStrategyCatalog": ".strategy_catalog",
    "GetStrategyVersion": ".strategy_catalog",
    "StrategyQueries": ".strategy_catalog",
    "ConfirmTradePlanVersion": ".trade_plan_authoring",
    "CreateTradePlanDraft": ".trade_plan_authoring",
    "GetActiveTradePlan": ".trade_plan_authoring",
    "GetTradePlanGraph": ".trade_plan_authoring",
    "IssuePlanConfirmationChallenge": ".trade_plan_authoring",
    "PlanCommandActor": ".trade_plan_authoring",
    "PlanConfirmationResult": ".trade_plan_authoring",
    "RejectTradePlanDraft": ".trade_plan_authoring",
    "ReviseTradePlanDraft": ".trade_plan_authoring",
    "TradePlanTasks": ".trade_plan_authoring",
    "AccountSnapshotCommands": ".account_snapshots",
    "AccountSnapshotQueries": ".account_snapshots",
    "ConfirmAccountSnapshot": ".account_snapshots",
    "CreateAccountSnapshotDraft": ".account_snapshots",
    "GetAccountSnapshot": ".account_snapshots",
    "UpdateAccountSnapshotDraft": ".account_snapshots",
    "ApplicationCommandEnvelopeV1": ".command_envelope",
    "ApprovalCapability": ".command_envelope",
    "CommandEnvelopeError": ".command_envelope",
    "DecisionActor": ".command_envelope",
    "InteractionChannel": ".command_envelope",
    "TransportActor": ".command_envelope",
    "ApplicationCommandDispatcher": ".commands",
    "ApplicationCommandFailure": ".commands",
    "ApplicationCommandResult": ".commands",
    "BrowserAcceptanceFixtureResult": ".browser_acceptance",
    "ChartAnnotations": ".web_tasks",
    "ChartWorkspace": ".web_tasks",
    "CommandCodecError": ".command_codecs",
    "Capability": ".contracts",
    "CapabilityStatus": ".contracts",
    "HealthQuery": ".contracts",
    "HealthResult": ".contracts",
    "ResumeWorkflowCommand": ".contracts",
    "SecurityIdentity": ".contracts",
    "StartResearchWorkflow": ".contracts",
    "DecisionWorkspace": ".web_tasks",
    "UpdateAuthorizations": ".web_tasks",
    "WorkspaceUpdateCommand": ".web_tasks",
    "decode_research_workflow_request": ".research_request_codec",
    "open_acceptance_evidence": ".bootstrap",
    "open_account_current_export": ".bootstrap",
    "open_account_snapshot_commands": ".bootstrap",
    "open_account_snapshot_queries": ".bootstrap",
    "open_application_commands": ".bootstrap",
    "open_account_state_queries": ".bootstrap",
    "open_strategy_queries": ".bootstrap",
    "open_account_acceptance": ".bootstrap",
    "open_account_history": ".bootstrap",
    "open_chart_annotations": ".bootstrap",
    "open_chart_workspace": ".bootstrap",
    "open_browser_acceptance_fixture": ".bootstrap",
    "open_daily_research_cycle": ".bootstrap",
    "open_decision_workspace": ".bootstrap",
    "open_data_synchronization": ".bootstrap",
    "open_import_preview": ".bootstrap",
    "open_market": ".bootstrap",
    "open_platform_health": ".bootstrap",
    "open_platform_operations": ".bootstrap",
    "open_project_verification": ".bootstrap",
    "open_provider_qualification": ".bootstrap",
    "open_research_archive": ".bootstrap",
    "open_research_workflow": ".bootstrap",
    "open_server_runtime": ".bootstrap",
    "open_watchlist": ".bootstrap",
    "open_trade_plan": ".bootstrap",
    "open_update_authorizations": ".bootstrap",
    "open_workflow_inspection": ".bootstrap",
    "open_workflow_runtime": ".bootstrap",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    """Load a public task contract only when a caller requests it."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
