"""Canonical public application task and command interface."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .bootstrap import (
        open_acceptance_evidence,
        open_account,
        open_account_acceptance,
        open_account_history,
        open_daily_research_cycle,
        open_data_synchronization,
        open_import_preview,
        open_market,
        open_platform_health,
        open_platform_operations,
        open_project_verification,
        open_provider_qualification,
        open_research_archive,
        open_research_workflow,
        open_server_runtime,
        open_watchlist,
        open_web_application,
        open_workflow_inspection,
        open_workflow_runtime,
    )
    from .command_codecs import (
        CommandCodecError,
        decode_market_snapshot_command,
        decode_plan_evaluation_command,
        decode_qualification_artifact,
        decode_watchlist_identity,
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

_EXPORT_MODULES = {
    "CommandCodecError": ".command_codecs",
    "Capability": ".contracts",
    "CapabilityStatus": ".contracts",
    "HealthQuery": ".contracts",
    "HealthResult": ".contracts",
    "ResumeWorkflowCommand": ".contracts",
    "SecurityIdentity": ".contracts",
    "StartResearchWorkflow": ".contracts",
    "decode_market_snapshot_command": ".command_codecs",
    "decode_plan_evaluation_command": ".command_codecs",
    "decode_qualification_artifact": ".command_codecs",
    "decode_research_workflow_request": ".research_request_codec",
    "decode_watchlist_identity": ".command_codecs",
    "open_acceptance_evidence": ".bootstrap",
    "open_account": ".bootstrap",
    "open_account_acceptance": ".bootstrap",
    "open_account_history": ".bootstrap",
    "open_daily_research_cycle": ".bootstrap",
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
    "open_web_application": ".bootstrap",
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
