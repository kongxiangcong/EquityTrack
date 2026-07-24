from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from equity_research import ResearchEngine
from trading_platform.account import AccountOpeningService
from trading_platform.account_acceptance import AccountAcceptanceService
from trading_platform.account_history import AccountHistoryImportService
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
from trading_platform.domain.data import DataProvider, FixtureRights, QueryPolicy, SourcePolicy
from trading_platform.market import MarketEvaluationService
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.market import SQLiteMarketRepository
from trading_platform.persistence.plans import SQLitePlanRepository
from trading_platform.persistence.workspace import WorkspaceService
from trading_platform.plans import PlanService
from trading_platform.operations import PlatformOperations
from trading_platform.research import SnapshotToResearchRequestAssembler
from trading_platform.workflows.research import (
    ResearchWorkflow,
    research_engine_identity,
)


class StorageFaultFixture:
    """Raw adapter seam reserved for corruption, migration, and rollback tests."""

    def __init__(self, store: PlatformStore) -> None:
        self._store = store
        self._data_repository: DataRepository | None = None

    def set_workflow_fault_injector(self, injector) -> None:
        self._store.workflow_ledger.fault_injector = injector

    def set_data_fault_injector(self, injector) -> None:
        if self._data_repository is None:
            raise AssertionError("Data repository is not configured for this fixture.")
        self._data_repository.fault_injector = injector

    def attach_data_repository(self, fault_injector=None) -> DataRepository:
        """Own the raw sync adapter used by data-fault tests."""
        repository = DataRepository(
            self._store.connection,
            self._store.workflow_ledger,
            self._store.data_root,
            self._store.writer_lock,
        )
        repository.fault_injector = fault_injector
        self._data_repository = repository
        return repository

    def corrupt_object(self, relative_path: str, payload: bytes) -> None:
        """Mutate one object payload for integrity-failure tests."""
        (self._store.data_root / relative_path).write_bytes(payload)

    def legacy_research_cutover(self):
        """Own otherwise-unrepresentable legacy migration state."""
        from tests.platform.research_cutover_fixture import LegacyResearchCutoverFixture

        return LegacyResearchCutoverFixture(self._store)

    def record_incomplete_account(self) -> None:
        """Create an account lacking a position snapshot for projection tests."""
        with self._store.connection:
            self._store.connection.execute(
                "INSERT INTO account VALUES(?,?,?,?,?)",
                (
                    "incomplete-account",
                    "local",
                    "CNY",
                    "2026-07-10",
                    "incomplete-source",
                ),
            )

    def record_market_only_workflow_snapshot(self) -> None:
        """Create a market-only workflow candidate for reuse-policy tests."""
        with self._store.connection:
            self._store.connection.execute(
                "INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "snapshot_market_20260710", "security_yihua", "workflow",
                    "2026-07-11", "2026-07-10", "2026-07-11T00:00:00+00:00",
                    "Asia/Shanghai", "cn-calendar@2026", "query@1", "source@1",
                    "freshness@1", "market-members", "valid", "pass", 0, 0, 0,
                    0, 0, "test workflow snapshot", "2026-07-11T00:00:00+00:00",
                ),
            )
            self._store.connection.execute(
                "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("attempt_market", "market-refresh", "fixture", "fixture@1", "daily", "derived-fixture", "fixture", "urn:test:daily", "{}", "{}", "date", "test-terms", "complete", "created", None, "2026-07-10T09:00:00+00:00", None, None, None, "not_applicable"),
            )
            self._store.connection.execute("INSERT INTO normalized_record VALUES(?,?,?)", ("record_market", "daily", "security_yihua:2026-07-10"))
            self._store.connection.execute("INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ("daily:2026-07-10", "record_market", 1, "market-content", "attempt_market", "2026-07-10", "2026-07-10", "date", "2026-07-10T09:00:00+00:00", "publisher_timestamp", "2026-07-10T09:00:00+00:00", "pass", None))
            self._store.connection.execute("INSERT INTO data_snapshot_member VALUES(?,?,?,?)", ("snapshot_market_20260710", "daily:2026-07-10", "daily", 0))

    def record_official_filing_workflow_snapshot(self) -> None:
        """Create a research-relevant filing candidate for PIT policy tests."""
        with self._store.connection:
            self._store.connection.execute("INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("attempt_filing", "filing-refresh", "official", "official@1", "financial_statement", "CNINFO", "official", "urn:test:filing", "{}", "{}", "timestamp", "official-terms", "complete", "created", None, "2026-07-10T09:00:00+00:00", None, None, None, "not_applicable"))
            self._store.connection.execute("INSERT INTO normalized_record VALUES(?,?,?)", ("record_filing", "financial_statement", "security_yihua:2026Q2"))
            self._store.connection.execute("INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ("filing:2026Q2", "record_filing", 1, "filing-content", "attempt_filing", "2026-06-30", "2026-07-10T08:00:00+00:00", "timestamp", "2026-07-10T08:00:00+00:00", "publisher_timestamp", "2026-07-10T09:00:00+00:00", "pass", None))
            self._store.connection.execute("INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("snapshot_filing", "security_yihua", "workflow", "2026-07-11", "2026-07-10", "2026-07-11T00:00:00+00:00", "Asia/Shanghai", "cn-calendar@2026", "query@1", "source@1", "freshness@1", "filing-members", "valid", "pass", 1, 1, 0, 0, 0, "official filing candidate", "2026-07-11T00:00:00+00:00"))
            self._store.connection.execute("INSERT INTO data_snapshot_member VALUES(?,?,?,?)", ("snapshot_filing", "filing:2026Q2", "financial_statement", 0))

class PlatformTaskFixture:
    """Test composition whose fields are the production named task seams."""

    def __init__(
        self,
        data_root: Path,
        migrations_root: Path | None = None,
        provider: DataProvider | None = None,
        query_policy: QueryPolicy | None = None,
        source_policy: SourcePolicy | None = None,
        qualified_equivalents=(),
        qualified_equivalent_authority=None,
        fixture_rights: Mapping[tuple[str, str], FixtureRights] | None = None,
        research_engine: ResearchEngine | None = None,
        workflow_fault_injector=None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.data_root = data_root.resolve()
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
        self.health = Health(persistence=True, sync=provider is not None)
        self.watchlist = store.watchlist
        self.data = None
        if provider is not None:
            if query_policy is None or source_policy is None:
                raise ValueError("TEST_PROVIDER_POLICY_REQUIRED")
            repository = self.faults.attach_data_repository(workflow_fault_injector)
            self.data = DataSyncService(repository, provider, query_policy, source_policy, fixture_rights, tuple(qualified_equivalents), qualified_equivalent_authority)
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

    def close(self) -> None:
        self._store.close()


__all__ = ["PlatformTaskFixture", "StorageFaultFixture"]
