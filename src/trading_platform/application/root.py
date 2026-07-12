from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from trading_platform.data.repository import DataRepository
from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import DataProvider, FixtureRights
from trading_platform.persistence import PlatformStore
from trading_platform.research import ResearchAdapter, SnapshotToResearchRequestAssembler
from trading_platform.workflows import ResearchWorkflowService
from trading_platform.workflows.repository import WorkflowRepository
from equity_research import ResearchEngine
from trading_platform.chart import ChartService
from trading_platform.persistence.plans import SQLitePlanRepository
from trading_platform.plans import PlanService
from trading_platform.market import MarketEvaluationService
from trading_platform.persistence.market import SQLiteMarketRepository
from trading_platform.workspace import WorkspaceService

from .facade import ApplicationFacade


class ProductionCompositionRoot:
    """Owns one facade instance and, later, its production dependencies."""

    def __init__(self, data_root: Path | None = None, migrations_root: Path | None = None, providers: Sequence[DataProvider] = (), fixture_rights: Mapping[tuple[str, str], FixtureRights] | None = None, research_engine: ResearchEngine | None = None, workflow_fault_injector=None) -> None:
        self._store = None
        data_sync = None
        research_workflow = None
        chart = None
        plans = None
        market = None
        workspace = None
        if data_root is not None:
            root = Path(__file__).resolve().parents[3]
            self._store = PlatformStore(data_root, migrations_root or root / "migrations")
            self._store.migrate()
            self._store.objects.fault_injector = workflow_fault_injector
            if providers:
                repository = DataRepository(self._store.connection, self._store.objects, self._store.writer_lock)
                repository.fault_injector = workflow_fault_injector
                self._data_sync_repository = repository
                data_sync = DataSyncService(repository, providers, fixture_rights)
            workflow_repository = WorkflowRepository(self._store.connection, self._store.objects, self._store.writer_lock)
            self._workflow_repository = workflow_repository
            research_workflow = ResearchWorkflowService(workflow_repository, ResearchAdapter(research_engine or ResearchEngine()), SnapshotToResearchRequestAssembler(), root, workflow_fault_injector)
            chart = ChartService(self._store.connection, self._store.writer_lock)
            plans = PlanService(SQLitePlanRepository(self._store.connection, self._store.writer_lock))
            market = MarketEvaluationService(SQLiteMarketRepository(self._store.connection, self._store.writer_lock), plans)
            workspace = WorkspaceService(self._store.connection, self._store.writer_lock)
        self._facade = ApplicationFacade(self._store, data_sync, research_workflow, chart, plans, market, workspace)

    @property
    def facade(self) -> ApplicationFacade:
        return self._facade

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
