from __future__ import annotations

from trading_platform.domain.chart import AnnotationCommand, AnnotationVersion, ChartSeries
from trading_platform.domain.plans import ConfirmPlanDraftCommand, TradePlanVersionView

from .ports import ChartPort, PlanPort, WorkspacePort


class ApplicationFacade:
    """Temporary boundary for Web routes pending the Ticket 14 cutover."""

    def __init__(
        self,
        *,
        chart: ChartPort,
        plans: PlanPort,
        workspace: WorkspacePort,
    ) -> None:
        self._chart = chart
        self._plans = plans
        self._workspace = workspace

    def get_workspace(self, security_id: str, snapshot_id: str):
        return self._workspace.build(security_id, snapshot_id)

    def authorize_workspace_update(
        self,
        invocation_id: str,
        security_id: str,
        requested_date: str,
        effective_session_date: str,
    ):
        return self._workspace.authorize_update(
            invocation_id, security_id, requested_date, effective_session_date
        )

    def get_chart_series(
        self,
        security_id: str,
        snapshot_id: str,
        interval: str = "1d",
        adjustment_mode: str = "none",
        factor_snapshot_id: str | None = None,
    ) -> ChartSeries:
        return self._chart.get_series(
            security_id,
            snapshot_id,
            interval,
            adjustment_mode,
            factor_snapshot_id,
        )

    def create_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        return self._chart.create(command)

    def revise_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        return self._chart.revise(command)

    def delete_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        return self._chart.delete(command)

    def restore_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        return self._chart.restore(command)

    def get_annotation_history(
        self, annotation_id: str
    ) -> tuple[AnnotationVersion, ...]:
        return self._chart.get_history(annotation_id)

    def list_annotation_history(
        self, security_id: str
    ) -> tuple[AnnotationVersion, ...]:
        return self._chart.list_history(security_id)

    def confirm_plan_draft(
        self, command: ConfirmPlanDraftCommand
    ) -> TradePlanVersionView:
        return self._plans.confirm_draft(command)


__all__ = ["ApplicationFacade"]
