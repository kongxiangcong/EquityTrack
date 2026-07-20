from __future__ import annotations

from typing import Protocol

from trading_platform.domain.chart import AnnotationCommand, AnnotationVersion, ChartSeries
from trading_platform.domain.plans import (
    ConfirmPlanDraftCommand,
    TradePlanVersionView,
)


class ChartPort(Protocol):
    def get_series(
        self,
        security_id: str,
        snapshot_id: str,
        interval: str = "1d",
        adjustment_mode: str = "none",
        factor_snapshot_id: str | None = None,
    ) -> ChartSeries: ...

    def create(self, command: AnnotationCommand) -> AnnotationVersion: ...
    def revise(self, command: AnnotationCommand) -> AnnotationVersion: ...
    def delete(self, command: AnnotationCommand) -> AnnotationVersion: ...
    def restore(self, command: AnnotationCommand) -> AnnotationVersion: ...
    def get_history(self, annotation_id: str) -> tuple[AnnotationVersion, ...]: ...
    def list_history(self, security_id: str) -> tuple[AnnotationVersion, ...]: ...


class PlanPort(Protocol):
    def confirm_draft(
        self, command: ConfirmPlanDraftCommand
    ) -> TradePlanVersionView: ...


class WorkspacePort(Protocol):
    def build(self, security_id: str, snapshot_id: str): ...
    def authorize_update(
        self,
        invocation_id: str,
        security_id: str,
        requested_date: str,
        effective_session_date: str,
    ): ...


__all__ = ["ChartPort", "PlanPort", "WorkspacePort"]
