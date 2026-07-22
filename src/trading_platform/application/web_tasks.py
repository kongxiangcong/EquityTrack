from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from trading_platform.domain.chart import (
    AnnotationLifecycleCommand,
    AnnotationVersion,
    ChartSeries,
)
from trading_platform.domain.plans import (
    ConfirmPlanDraftCommand,
    TradePlanVersionView,
)


@dataclass(frozen=True)
class WorkspaceUpdateCommand:
    invocation_id: str
    security_id: str
    requested_date: str
    effective_session_date: str


class DecisionWorkspace(Protocol):
    def build(self, security_id: str, snapshot_id: str) -> Mapping[str, Any]: ...


class ChartWorkspace(Protocol):
    def get_series(self, security_id: str, snapshot_id: str) -> ChartSeries: ...


class ChartAnnotations(Protocol):
    def apply(self, command: AnnotationLifecycleCommand) -> AnnotationVersion: ...

    def list_history(self, security_id: str) -> tuple[AnnotationVersion, ...]: ...


class PlanConfirmation(Protocol):
    def confirm_draft(
        self, command: ConfirmPlanDraftCommand
    ) -> TradePlanVersionView: ...


class UpdateAuthorizations(Protocol):
    def authorize(self, command: WorkspaceUpdateCommand) -> Mapping[str, Any]: ...


__all__ = [
    "ChartAnnotations",
    "ChartWorkspace",
    "DecisionWorkspace",
    "PlanConfirmation",
    "UpdateAuthorizations",
    "WorkspaceUpdateCommand",
]
