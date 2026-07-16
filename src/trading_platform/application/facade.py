from __future__ import annotations

from .contracts import (
    ApplicationError,
    ApplicationStatus,
    Capability,
    CapabilityResult,
    CapabilityStatus,
    CancelWorkflowCommand,
    ErrorCode,
    HealthQuery,
    HealthResult,
    PlatformCommand,
    ResumeWorkflowCommand,
    SecurityIdentity,
    DoctorReport,
    WatchlistView,
)
from trading_platform.domain.data import ProviderAttemptEvidence, SnapshotMemberView, SyncRequest, SyncResult
from trading_platform.domain.workflow import ArtifactManifestView, ResearchArtifactView, ResearchWorkflowRequest, ResearchWorkflowResult, WorkflowHistory
from trading_platform.domain.chart import AnnotationCommand, AnnotationVersion, ChartSeries, CoordinateMigration, CoordinateMigrationResult
from trading_platform.domain.plans import ActivatePlanVersionCommand, ActivePlanView, ChangePlanLifecycleCommand, ConfirmPlanDraftCommand, CreatePlanDraftCommand, DiscardPlanDraftCommand, PlanConfirmationView, TradePlanDraftView, TradePlanVersionView, UpdatePlanDraftCommand
from trading_platform.application.market_contracts import BuildMarketSnapshotCommand, EvaluatePlanCommand
from trading_platform.domain.market import MarketSnapshotView, PlanEvaluationView

from .ports import AccountPort, ChartPort, DataSyncPort, MarketPort, PlanPort, PlatformPersistence, ResearchWorkflowPort, WorkspacePort


class ApplicationFacade:
    """The sole command/query boundary used by local adapters."""

    VERSION = "platform-skeleton@1"

    def __init__(self, store: PlatformPersistence | None = None, data_sync: DataSyncPort | None = None, research_workflow: ResearchWorkflowPort | None = None, chart: ChartPort | None = None, plans: PlanPort | None = None, market: MarketPort | None = None, workspace: WorkspacePort | None = None, accounts: AccountPort | None = None) -> None:
        self._store = store
        self._data_sync = data_sync
        self._research_workflow = research_workflow
        self._chart = chart
        self._plans = plans
        self._market = market
        self._workspace = workspace
        self._accounts = accounts

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

    def get_data_snapshot_members(self, snapshot_id: str) -> tuple[SnapshotMemberView, ...]:
        if self._data_sync is None:
            raise RuntimeError("sync unavailable")
        return self._data_sync.snapshot_members(snapshot_id)

    def get_provider_attempt_evidence(self, attempt_ids: tuple[str, ...]) -> tuple[ProviderAttemptEvidence, ...]:
        if self._data_sync is None:
            raise RuntimeError("sync unavailable")
        return self._data_sync.provider_attempt_evidence(attempt_ids)

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

    def get_research_artifact(self, artifact_record_id: str) -> ResearchArtifactView:
        if self._research_workflow is None:
            raise RuntimeError("research workflow unavailable")
        return self._research_workflow.get_research_artifact(artifact_record_id)

    def get_research_run_payload(self, research_run_id: str):
        if self._research_workflow is None:
            raise RuntimeError("research workflow unavailable")
        return self._research_workflow.get_research_run_payload(research_run_id)

    def resume_workflow(self, command: ResumeWorkflowCommand) -> ResearchWorkflowResult:
        if self._research_workflow is None: raise RuntimeError("research workflow unavailable")
        return self._research_workflow.resume(command)

    def cancel_workflow(self, command: CancelWorkflowCommand) -> None:
        if self._research_workflow is None: raise RuntimeError("research workflow unavailable")
        self._research_workflow.cancel(command)

    def get_workspace(self, security_id: str, snapshot_id: str):
        if self._workspace is None:
            raise RuntimeError("workspace unavailable")
        return self._workspace.build(security_id, snapshot_id)

    def get_account_opening(self, account_id: str):
        if self._accounts is None: raise RuntimeError("accounts unavailable")
        return self._accounts.get_detail(account_id)

    def authorize_workspace_update(self, invocation_id: str, security_id: str, requested_date: str, effective_session_date: str):
        if self._workspace is None:
            raise RuntimeError("workspace unavailable")
        return self._workspace.authorize_update(invocation_id, security_id, requested_date, effective_session_date)

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

    def create_plan_draft(self, command: CreatePlanDraftCommand) -> TradePlanDraftView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.create_draft(command)

    def update_plan_draft(self, command: UpdatePlanDraftCommand) -> TradePlanDraftView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.update_draft(command)

    def discard_plan_draft(self, command: DiscardPlanDraftCommand) -> TradePlanDraftView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.discard_draft(command)

    def confirm_plan_draft(self, command: ConfirmPlanDraftCommand) -> TradePlanVersionView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.confirm_draft(command)

    def activate_plan_version(self, command: ActivatePlanVersionCommand) -> TradePlanVersionView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.activate_version(command)

    def deactivate_plan(self, command: ChangePlanLifecycleCommand) -> ActivePlanView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.deactivate(command)

    def end_plan(self, command: ChangePlanLifecycleCommand) -> ActivePlanView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.end(command)

    def get_plan_draft(self, draft_id: str) -> TradePlanDraftView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.get_draft(draft_id)

    def get_plan_version(self, version_id: str) -> TradePlanVersionView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.get_version(version_id)

    def get_active_plan_for_security(self, security_id: str) -> ActivePlanView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.get_active_for_security(security_id)

    def get_plan_lifecycle(self, plan_id: str) -> ActivePlanView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.get_lifecycle(plan_id)

    def get_plan_confirmation(self, draft_id: str) -> PlanConfirmationView:
        if self._plans is None: raise RuntimeError("plans unavailable")
        return self._plans.confirmation(draft_id)

    def get_plan_version_diff(self, draft_id: str):
        return self.get_plan_confirmation(draft_id).diff

    def build_market_snapshot(self, command: BuildMarketSnapshotCommand) -> MarketSnapshotView:
        if self._market is None: raise RuntimeError("market unavailable")
        return self._market.build_market_snapshot(command)

    def evaluate_plan(self, command: EvaluatePlanCommand) -> PlanEvaluationView:
        if self._market is None: raise RuntimeError("market unavailable")
        return self._market.evaluate_plan(command)

    def get_market_snapshot_detail(self, market_snapshot_id: str) -> MarketSnapshotView:
        if self._market is None: raise RuntimeError("market unavailable")
        return self._market.get_market_snapshot(market_snapshot_id)

    def get_plan_evaluation_detail(self, evaluation_id: str) -> PlanEvaluationView:
        if self._market is None: raise RuntimeError("market unavailable")
        return self._market.get_plan_evaluation(evaluation_id)
