from __future__ import annotations

from .contracts import (
    ApplicationError,
    ApplicationStatus,
    Capability,
    CapabilityResult,
    CapabilityStatus,
    ErrorCode,
    HealthQuery,
    HealthResult,
    PlatformCommand,
    SecurityIdentity,
    DoctorReport,
    WatchlistView,
)
from trading_platform.domain.data import SyncRequest, SyncResult
from trading_platform.domain.workflow import ArtifactManifestView, ResearchWorkflowRequest, ResearchWorkflowResult, WorkflowHistory
from trading_platform.domain.chart import AnnotationCommand, AnnotationVersion, ChartSeries, CoordinateMigration, CoordinateMigrationResult

from .ports import ChartPort, DataSyncPort, PlatformPersistence, ResearchWorkflowPort


class ApplicationFacade:
    """The sole command/query boundary used by local adapters."""

    VERSION = "platform-skeleton@1"

    def __init__(self, store: PlatformPersistence | None = None, data_sync: DataSyncPort | None = None, research_workflow: ResearchWorkflowPort | None = None, chart: ChartPort | None = None) -> None:
        self._store = store
        self._data_sync = data_sync
        self._research_workflow = research_workflow
        self._chart = chart

    def query_health(self, query: HealthQuery) -> HealthResult:
        del query
        return HealthResult(
            status=ApplicationStatus.AVAILABLE_WITH_LIMITS,
            application_version=self.VERSION,
            capabilities={
                Capability.HEALTH: CapabilityStatus.AVAILABLE,
                Capability.PERSISTENCE: CapabilityStatus.AVAILABLE if self._store is not None else CapabilityStatus.UNAVAILABLE,
                Capability.SYNC: CapabilityStatus.AVAILABLE if self._data_sync is not None else CapabilityStatus.UNAVAILABLE,
                Capability.DAILY: CapabilityStatus.UNAVAILABLE,
                Capability.SERVE: CapabilityStatus.UNAVAILABLE,
            },
        )

    def execute(self, command: PlatformCommand) -> CapabilityResult:
        return CapabilityResult(
            status=CapabilityStatus.UNAVAILABLE,
            error=ApplicationError(
                code=ErrorCode.CAPABILITY_UNAVAILABLE,
                message=f"Capability '{command.capability.value}' is not implemented in this slice.",
            ),
        )

    def add_watchlist_item(self, invocation_id: str, security: SecurityIdentity) -> WatchlistView:
        if self._store is None:
            raise RuntimeError("persistence unavailable")
        return self._store.add_watchlist_item(invocation_id, security)

    def list_watchlist_items(self) -> tuple[WatchlistView, ...]:
        return () if self._store is None else self._store.list_watchlist_items()

    def doctor(self) -> DoctorReport:
        if self._store is None:
            return DoctorReport("failed", (), ("PERSISTENCE_UNAVAILABLE",))
        return self._store.doctor()

    def sync_data(self, request: SyncRequest) -> SyncResult:
        if self._data_sync is None:
            raise RuntimeError("sync unavailable")
        return self._data_sync.sync(request)

    def run_research_workflow(self, request: ResearchWorkflowRequest) -> ResearchWorkflowResult:
        if self._research_workflow is None:
            raise RuntimeError("research workflow unavailable")
        return self._research_workflow.run(request)

    def get_workflow_history(self, workflow_run_id: str) -> WorkflowHistory:
        if self._research_workflow is None:
            raise RuntimeError("research workflow unavailable")
        return self._research_workflow.get_history(workflow_run_id)

    def get_artifact_manifest(self, manifest_id: str) -> ArtifactManifestView:
        if self._research_workflow is None:
            raise RuntimeError("research workflow unavailable")
        return self._research_workflow.get_manifest(manifest_id)

    def get_chart_series(self, security_id: str, snapshot_id: str, interval: str = "1d", adjustment_mode: str = "none", factor_snapshot_id: str | None = None) -> ChartSeries:
        if self._chart is None:
            raise RuntimeError("chart unavailable")
        return self._chart.get_series(security_id, snapshot_id, interval, adjustment_mode, factor_snapshot_id)

    def create_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        if self._chart is None: raise RuntimeError("chart unavailable")
        return self._chart.create(command)

    def revise_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        if self._chart is None: raise RuntimeError("chart unavailable")
        return self._chart.revise(command)

    def delete_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        if self._chart is None: raise RuntimeError("chart unavailable")
        return self._chart.delete(command)

    def restore_annotation(self, command: AnnotationCommand) -> AnnotationVersion:
        if self._chart is None: raise RuntimeError("chart unavailable")
        return self._chart.restore(command)

    def migrate_annotation_coordinates(self, command: CoordinateMigration) -> CoordinateMigrationResult:
        if self._chart is None: raise RuntimeError("chart unavailable")
        return self._chart.migrate(command)

    def get_annotation_history(self, annotation_id: str) -> tuple[AnnotationVersion, ...]:
        if self._chart is None: raise RuntimeError("chart unavailable")
        return self._chart.get_history(annotation_id)

    def list_annotation_history(self, security_id: str) -> tuple[AnnotationVersion, ...]:
        if self._chart is None: raise RuntimeError("chart unavailable")
        return self._chart.list_history(security_id)
