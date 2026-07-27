from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from trading_platform.account import AccountOpeningService
from trading_platform.account_acceptance import AccountAcceptanceService
from trading_platform.account_history import AccountHistoryImportService
from trading_platform.account_import import TonghuashunImportPreviewer
from trading_platform.acceptance import AcceptanceEvidenceService
from trading_platform.chart import ChartService
from trading_platform.data.repository import DataRepository
from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import DataProvider, FixtureRights
from trading_platform.market import MarketEvaluationService
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.account_snapshots import (
    SQLiteAccountSnapshotProjection,
    SQLiteAccountSnapshotRepository,
)
from trading_platform.persistence.market import SQLiteMarketRepository
from trading_platform.persistence.plans import SQLiteTradePlanRepository
from trading_platform.persistence.presence import RuntimePresence
from trading_platform.persistence.workspace import WorkspaceService
from trading_platform.operations import PlatformOperations
from trading_platform.operations import OperationError
from trading_platform.provider_config import ProviderRuntimeAdapter, load_sync_job
from trading_platform.provider_qualification import ProviderQualificationService
from trading_platform.credentials import CredentialAdapter
from trading_platform.workflows.research import ResearchWorkflow
from trading_platform.verification import (
    ProjectVerification,
    SubprocessVerificationExecutor,
)

from .cli_tasks import DataSynchronization
from .health import Health
from .watchlist import Watchlist
from .research_tasks import ResearchArchive, WorkflowInspection
from .workflow_ledger import QualificationReceiptQuery, WorkflowLedgerPort
from .web_tasks import (
    ChartAnnotations,
    ChartWorkspace,
    DecisionWorkspace,
    UpdateAuthorizations,
)
from .browser_acceptance import BrowserAcceptanceFixture, load_browser_fixture
from .account_snapshots import AccountSnapshotCommands, AccountSnapshotQueries
from .account_state import AccountStateQueries, EstimatedAccountWorkspace
from .strategy_catalog import StrategyQueries
from .trade_plan_authoring import TradePlanTasks
from .commands import ApplicationCommandDispatcher
from .manual_portfolio_review import ManualPortfolioReview
from .decision_tasks import DecisionTasks
from .decision_journal import DecisionJournal
from .discipline_reviews import DisciplineReviews
from trading_platform.domain.account_state import ExecutionRecordReader
from trading_platform.domain.account_snapshots import AccountSnapshotService
from trading_platform.persistence.strategies import SQLiteStrategyRepository
from trading_platform.persistence.manual_portfolio_review import (
    SQLiteManualPortfolioReviewRepository,
)
from trading_platform.persistence.decision_tasks import (
    SQLiteDecisionTaskRepository,
)
from trading_platform.persistence.decision_journal import (
    SQLiteDecisionJournalRepository,
)
from trading_platform.persistence.discipline_reviews import (
    SQLiteDisciplineReviewRepository,
)
from trading_platform.domain.discipline_reviews import (
    DisciplineReviewService,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ledger(store: PlatformStore) -> WorkflowLedgerPort:
    return cast(WorkflowLedgerPort, store.workflow_ledger)


@contextmanager
def _store(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[PlatformStore]:
    database = data_root.resolve() / "platform.sqlite3"
    if not database.is_file():
        raise OperationError(
            "PLATFORM_NOT_BOOTSTRAPPED",
            "Run the canonical bootstrap maintenance task first.",
        )
    store = PlatformStore(data_root, migrations_root or _repo_root() / "migrations")
    try:
        files, applied = store.migrations.validate()
        if len(files) != len(applied):
            raise OperationError(
                "PLATFORM_MIGRATION_REQUIRED",
                "Run the canonical migrate maintenance task first.",
            )
        yield store
    finally:
        store.close()


def _assert_store_ready(data_root: Path, migrations_root: Path | None = None) -> None:
    with _store(data_root, migrations_root):
        pass


@contextmanager
def open_platform_health(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[Health]:
    with _store(data_root, migrations_root):
        yield Health(persistence=True)


@contextmanager
def open_workflow_runtime(data_root: Path) -> Iterator[None]:
    with RuntimePresence(data_root, "workflow").acquire():
        yield


@contextmanager
def open_server_runtime(data_root: Path) -> Iterator[None]:
    with RuntimePresence(data_root, "server").acquire():
        yield


@contextmanager
def open_watchlist(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[Watchlist]:
    with _store(data_root, migrations_root) as store:
        yield store.watchlist


@contextmanager
def open_data_synchronization(
    data_root: Path,
    job_file: Path,
    *,
    credential_adapter: CredentialAdapter | None = None,
    migrations_root: Path | None = None,
    provider_runtime: ProviderRuntimeAdapter | None = None,
) -> Iterator[DataSynchronization]:
    loaded = load_sync_job(job_file, credential_adapter, provider_runtime)
    with _store(data_root, migrations_root) as store:
        repository = DataRepository(
            store.connection,
            _ledger(store),
            store.data_root,
            store.writer_lock,
        )
        yield DataSynchronization(
            loaded.job,
            loaded.request,
            store.watchlist,
            DataSyncService(
                repository,
                loaded.provider,
                loaded.query_policy,
                loaded.source_policy,
            ),
        )


@contextmanager
def open_provider_qualification(
    data_root: Path,
    job_file: Path,
    *,
    credential_adapter: CredentialAdapter | None = None,
    migrations_root: Path | None = None,
    provider_runtime: ProviderRuntimeAdapter | None = None,
) -> Iterator[ProviderQualificationService]:
    loaded = load_sync_job(job_file, credential_adapter, provider_runtime)
    with _store(data_root, migrations_root) as store:
        repository = DataRepository(
            store.connection,
            _ledger(store),
            store.data_root,
            store.writer_lock,
        )
        data = DataSyncService(
            repository,
            loaded.provider,
            loaded.query_policy,
            loaded.source_policy,
        )
        synchronization = DataSynchronization(loaded.job, loaded.request, store.watchlist, data)
        yield ProviderQualificationService(
            loaded, synchronization, data, _ledger(store)
        )


@contextmanager
def open_research_workflow(
    data_root: Path,
    *,
    migrations_root: Path | None = None,
    fault_injector=None,
) -> Iterator[ResearchWorkflow]:
    with _store(data_root, migrations_root) as store:
        store.workflow_ledger.fault_injector = fault_injector
        yield ResearchWorkflow(
            _ledger(store),
            _repo_root(),
            fault_injector,
        )


@contextmanager
def open_workflow_inspection(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[WorkflowInspection]:
    with _store(data_root, migrations_root) as store:
        yield WorkflowInspection(_ledger(store))


@contextmanager
def open_research_archive(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ResearchArchive]:
    with _store(data_root, migrations_root) as store:
        yield ResearchArchive(_ledger(store))


@contextmanager
def open_decision_workspace(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[DecisionWorkspace]:
    with _store(data_root, migrations_root) as store:
        yield EstimatedAccountWorkspace(
            AccountStateQueries(
                SQLiteAccountSnapshotProjection(store.connection),
                SQLiteDecisionJournalRepository(
                    store.connection, store.writer_lock
                ),
            ),
            WorkspaceService(
                store.connection, _ledger(store), store.writer_lock
            ),
        )


@contextmanager
def open_chart_workspace(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ChartWorkspace]:
    with _store(data_root, migrations_root) as store:
        yield ChartService(store.connection, store.writer_lock)


@contextmanager
def open_chart_annotations(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ChartAnnotations]:
    with _store(data_root, migrations_root) as store:
        yield ChartService(store.connection, store.writer_lock)


@contextmanager
def open_trade_plan(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[TradePlanTasks]:
    with _store(data_root, migrations_root) as store:
        yield TradePlanTasks(
            SQLiteTradePlanRepository(store.connection, store.writer_lock)
        )


@contextmanager
def open_application_commands(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ApplicationCommandDispatcher]:
    with _store(data_root, migrations_root) as store:
        journal_repository = SQLiteDecisionJournalRepository(
            store.connection, store.writer_lock
        )
        journal = DecisionJournal(journal_repository)
        yield ApplicationCommandDispatcher(
            AccountSnapshotCommands(
                SQLiteAccountSnapshotRepository(
                    store.connection, store.writer_lock
                ),
                AccountSnapshotService(),
            ),
            TradePlanTasks(
                SQLiteTradePlanRepository(
                    store.connection, store.writer_lock
                )
            ),
            ManualPortfolioReview(
                SQLiteManualPortfolioReviewRepository(
                    store.connection, store.writer_lock
                ),
                AccountStateQueries(
                    SQLiteAccountSnapshotProjection(store.connection),
                    journal_repository,
                ),
                _ledger(store),
            ),
            DecisionTasks(
                SQLiteDecisionTaskRepository(
                    store.connection, store.writer_lock
                ),
                journal_repository,
            ),
            journal,
            DisciplineReviews(
                SQLiteDisciplineReviewRepository(
                    store.connection, store.writer_lock
                ),
                DisciplineReviewService(),
            ),
        )


@contextmanager
def open_manual_portfolio_review(
    data_root: Path,
    migrations_root: Path | None = None,
    *,
    fault_injector=None,
) -> Iterator[ManualPortfolioReview]:
    with _store(data_root, migrations_root) as store:
        repository = SQLiteManualPortfolioReviewRepository(
            store.connection, store.writer_lock
        )
        repository.fault_injector = fault_injector
        yield ManualPortfolioReview(
            repository,
            AccountStateQueries(
                SQLiteAccountSnapshotProjection(store.connection),
                SQLiteDecisionJournalRepository(
                    store.connection, store.writer_lock
                ),
            ),
            _ledger(store),
        )


@contextmanager
def open_decision_tasks(
    data_root: Path,
    migrations_root: Path | None = None,
    *,
    fault_injector=None,
) -> Iterator[DecisionTasks]:
    with _store(data_root, migrations_root) as store:
        journal_repository = SQLiteDecisionJournalRepository(
            store.connection, store.writer_lock
        )
        journal_repository.fault_injector = fault_injector
        yield DecisionTasks(
            SQLiteDecisionTaskRepository(
                store.connection, store.writer_lock
            ),
            journal_repository,
        )


@contextmanager
def open_decision_journal(
    data_root: Path,
    migrations_root: Path | None = None,
    *,
    fault_injector=None,
) -> Iterator[DecisionJournal]:
    with _store(data_root, migrations_root) as store:
        repository = SQLiteDecisionJournalRepository(
            store.connection, store.writer_lock
        )
        repository.fault_injector = fault_injector
        yield DecisionJournal(repository)


@contextmanager
def open_discipline_reviews(
    data_root: Path,
    migrations_root: Path | None = None,
) -> Iterator[DisciplineReviews]:
    with _store(data_root, migrations_root) as store:
        yield DisciplineReviews(
            SQLiteDisciplineReviewRepository(
                store.connection, store.writer_lock
            ),
            DisciplineReviewService(),
        )


@contextmanager
def open_update_authorizations(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[UpdateAuthorizations]:
    with _store(data_root, migrations_root) as store:
        yield WorkspaceService(store.connection, _ledger(store), store.writer_lock)


@contextmanager
def open_browser_acceptance_fixture(
    data_root: Path,
    fixture_manifest: Path,
    repo_root: Path,
    migrations_root: Path | None = None,
) -> Iterator[BrowserAcceptanceFixture]:
    provider, query_policy, source_policy, rights = load_browser_fixture(fixture_manifest)
    with _store(data_root, migrations_root) as store:
        ledger = _ledger(store)
        repository = DataRepository(
            store.connection,
            ledger,
            store.data_root,
            store.writer_lock,
        )
        yield BrowserAcceptanceFixture(
            store.watchlist,
            DataSyncService(repository, provider, query_policy, source_policy, rights),
            ResearchWorkflow(
                ledger,
                repo_root,
            ),
        )


@contextmanager
def open_market(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[MarketEvaluationService]:
    with _store(data_root, migrations_root) as store:
        plans = SQLiteTradePlanRepository(
            store.connection, store.writer_lock
        )
        yield MarketEvaluationService(
            SQLiteMarketRepository(store.connection, store.writer_lock), plans
        )


def open_account_current_export(
    data_root: Path,
    repo_root: Path | None = None,
    migrations_root: Path | None = None,
) -> AccountOpeningService:
    root = repo_root or _repo_root()
    migration_path = migrations_root or root / "migrations"
    _assert_store_ready(data_root, migration_path)
    return AccountOpeningService(data_root, root, migration_path)


@contextmanager
def open_account_snapshot_commands(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[AccountSnapshotCommands]:
    with _store(data_root, migrations_root) as store:
        yield AccountSnapshotCommands(
            SQLiteAccountSnapshotRepository(
                store.connection, store.writer_lock
            ),
            AccountSnapshotService(),
        )


@contextmanager
def open_account_snapshot_queries(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[AccountSnapshotQueries]:
    with _store(data_root, migrations_root) as store:
        yield AccountSnapshotQueries(
            SQLiteAccountSnapshotProjection(store.connection)
        )


@contextmanager
def open_account_state_queries(
    data_root: Path,
    migrations_root: Path | None = None,
    *,
    execution_reader: ExecutionRecordReader | None = None,
) -> Iterator[AccountStateQueries]:
    with _store(data_root, migrations_root) as store:
        yield AccountStateQueries(
            SQLiteAccountSnapshotProjection(store.connection),
            (
                execution_reader
                if execution_reader is not None
                else SQLiteDecisionJournalRepository(
                    store.connection, store.writer_lock
                )
            ),
        )


@contextmanager
def open_strategy_queries(
    data_root: Path,
    migrations_root: Path | None = None,
) -> Iterator[StrategyQueries]:
    with _store(data_root, migrations_root) as store:
        yield StrategyQueries(SQLiteStrategyRepository(store.connection))


def open_platform_operations(data_root: Path) -> PlatformOperations:
    return PlatformOperations(data_root)


def open_project_verification(npm_executable: str) -> ProjectVerification:
    return ProjectVerification(
        executor=SubprocessVerificationExecutor(),
        npm_executable=npm_executable,
    )


def open_acceptance_evidence(
    data_root: Path, repo_root: Path
) -> AcceptanceEvidenceService:
    def load_receipt(artifact_id: str) -> bytes:
        with _store(data_root) as store:
            return _ledger(store).load(QualificationReceiptQuery(artifact_id))

    return AcceptanceEvidenceService(data_root, repo_root, load_receipt)


def open_import_preview(repo_root: Path) -> TonghuashunImportPreviewer:
    return TonghuashunImportPreviewer(repo_root)


def open_account_history(
    data_root: Path, repo_root: Path
) -> AccountHistoryImportService:
    _assert_store_ready(data_root, repo_root / "migrations")
    return AccountHistoryImportService(data_root, repo_root)


def open_account_acceptance(
    data_root: Path, migrations_root: Path
) -> AccountAcceptanceService:
    _assert_store_ready(data_root, migrations_root)
    return AccountAcceptanceService(data_root, migrations_root)


__all__ = [
    "open_account_current_export",
    "open_account_snapshot_commands",
    "open_account_snapshot_queries",
    "open_application_commands",
    "open_account_state_queries",
    "open_strategy_queries",
    "open_account_acceptance",
    "open_account_history",
    "open_acceptance_evidence",
    "open_chart_annotations",
    "open_chart_workspace",
    "open_browser_acceptance_fixture",
    "open_data_synchronization",
    "open_import_preview",
    "open_market",
    "open_manual_portfolio_review",
    "open_decision_tasks",
    "open_decision_journal",
    "open_discipline_reviews",
    "open_decision_workspace",
    "open_platform_health",
    "open_platform_operations",
    "open_project_verification",
    "open_provider_qualification",
    "open_research_archive",
    "open_research_workflow",
    "open_watchlist",
    "open_trade_plan",
    "open_update_authorizations",
    "open_server_runtime",
    "open_workflow_runtime",
    "open_workflow_inspection",
]
