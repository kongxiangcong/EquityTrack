from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from equity_research import ResearchEngine
from trading_platform.account import AccountOpeningService
from trading_platform.account_acceptance import AccountAcceptanceService
from trading_platform.account_history import AccountHistoryImportService
from trading_platform.application.facade import ApplicationFacade
from trading_platform.application.health import Health
from trading_platform.application.research_tasks import (
    ForecastReview,
    ResearchArchive,
    WorkflowInspection,
)
from trading_platform.application.workflow_ledger import WorkflowLedgerPort
from trading_platform.chart import ChartService
from trading_platform.data.repository import DataRepository
from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import DataProvider, FixtureRights
from trading_platform.market import MarketEvaluationService
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.market import SQLiteMarketRepository
from trading_platform.persistence.plans import SQLitePlanRepository
from trading_platform.persistence.workspace import WorkspaceService
from trading_platform.plans import PlanService
from trading_platform.operations import PlatformOperations
from trading_platform.research import SnapshotToResearchRequestAssembler
from trading_platform.workflows.research import ResearchWorkflow, research_engine_identity


class StorageFaultFixture:
    """Raw adapter seam reserved for corruption, migration, and rollback tests."""

    def __init__(self, store: PlatformStore) -> None:
        self._store = store
        self.data_repository: DataRepository | None = None

    @property
    def adapter_connection(self):
        """SQLite seam for adapter ownership, rollback, and corruption tests."""
        return self._store.connection

    @property
    def workflow_ledger(self):
        """Persistence adapter seam for ledger-specific integrity tests."""
        return self._store.workflow_ledger

    def artifact_bytes(self, artifact_id: str) -> bytes:
        """Read an immutable artifact through its owning persistence schema."""
        row = self._store.connection.execute(
            "SELECT o.relative_path FROM artifact a JOIN object_blob o ON o.sha256=a.object_sha256 WHERE a.artifact_id=?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise AssertionError(f"Unknown artifact fixture: {artifact_id}")
        return (self._store.data_root / row["relative_path"]).read_bytes()

    def corrupt_object(self, relative_path: str, payload: bytes) -> None:
        """Mutate one object payload for integrity-failure tests."""
        (self._store.data_root / relative_path).write_bytes(payload)

    def delete_update_authorizations(self) -> None:
        """Attempt a forbidden adapter mutation for immutability tests."""
        self._store.connection.execute("DELETE FROM update_authorization")

    @property
    def legacy_store(self) -> PlatformStore:
        """One-way ResearchDecisionView migration fixture only."""
        return self._store

    def doctor(self):
        return self._store.doctor()


class PlatformTaskFixture:
    """Test composition whose fields are the production named task seams."""

    def __init__(
        self,
        data_root: Path,
        migrations_root: Path | None = None,
        providers: Sequence[DataProvider] = (),
        fixture_rights: Mapping[tuple[str, str], FixtureRights] | None = None,
        research_engine: ResearchEngine | None = None,
        workflow_fault_injector=None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        migration_path = migrations_root or repo_root / "migrations"
        if not (data_root / "platform.sqlite3").is_file():
            result = PlatformOperations(data_root, migration_path).bootstrap()
            if result["status"] != "passed":
                raise RuntimeError("Test platform bootstrap failed")
        store = PlatformStore(data_root, migration_path)
        store.workflow_ledger.fault_injector = workflow_fault_injector
        ledger = cast(WorkflowLedgerPort, store.workflow_ledger)
        self._store = store
        self.faults = StorageFaultFixture(store)
        self.health = Health(persistence=True, sync=bool(providers))
        self.watchlist = store.watchlist
        self.data = None
        if providers:
            self.faults.data_repository = DataRepository(
                store.connection,
                ledger,
                store.data_root,
                store.writer_lock,
            )
            self.faults.data_repository.fault_injector = workflow_fault_injector
            self.data = DataSyncService(
                self.faults.data_repository, providers, fixture_rights
            )
        self.research = ResearchWorkflow(
            ledger,
            research_engine or ResearchEngine(),
            SnapshotToResearchRequestAssembler(),
            repo_root,
            workflow_fault_injector,
        )
        self.inspection = WorkflowInspection(ledger)
        self.archive = ResearchArchive(ledger)
        self.forecast_review = ForecastReview(
            ledger, research_engine_identity(repo_root)
        )
        self.chart = ChartService(store.connection, store.writer_lock)
        self.plans = PlanService(
            SQLitePlanRepository(store.connection, store.writer_lock)
        )
        self.market = MarketEvaluationService(
            SQLiteMarketRepository(store.connection, store.writer_lock),
            self.plans,
        )
        self.workspace = WorkspaceService(
            store.connection,
            ledger,
            store.writer_lock,
        )
        self.accounts = AccountOpeningService(
            data_root, repo_root, migrations_root or repo_root / "migrations"
        )
        self.account_history = AccountHistoryImportService(data_root, repo_root)
        self.account_acceptance = AccountAcceptanceService(
            data_root, migrations_root or repo_root / "migrations"
        )
        self.web = ApplicationFacade(
            chart=self.chart,
            plans=self.plans,
            workspace=self.workspace,
        )

    def close(self) -> None:
        self._store.close()


__all__ = ["PlatformTaskFixture", "StorageFaultFixture"]
