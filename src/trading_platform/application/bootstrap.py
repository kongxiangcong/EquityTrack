from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from equity_research import ResearchEngine
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
from trading_platform.persistence.market import SQLiteMarketRepository
from trading_platform.persistence.plans import SQLitePlanRepository
from trading_platform.persistence.presence import RuntimePresence
from trading_platform.persistence.workspace import WorkspaceService
from trading_platform.plans import PlanService
from trading_platform.operations import PlatformOperations
from trading_platform.operations import OperationError
from trading_platform.provider_config import ProviderRuntimeAdapter, load_sync_job
from trading_platform.provider_qualification import ProviderQualificationService
from trading_platform.credentials import CredentialAdapter
from trading_platform.research import SnapshotToResearchRequestAssembler
from trading_platform.workflows.research import ResearchWorkflow
from trading_platform.verification import (
    ProjectVerification,
    SubprocessVerificationExecutor,
)

from .cli_tasks import DailyResearchCycle, DataSynchronization
from .health import Health
from .watchlist import Watchlist
from .research_tasks import ResearchArchive, WorkflowInspection
from .workflow_ledger import QualificationReceiptQuery, ResearchViewCutoverCompleteQuery, WorkflowLedgerPort
from .web_tasks import (
    ChartAnnotations,
    ChartWorkspace,
    DecisionWorkspace,
    PlanConfirmation,
    UpdateAuthorizations,
)
from .browser_acceptance import BrowserAcceptanceFixture, load_browser_fixture


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
        if not _ledger(store).load(ResearchViewCutoverCompleteQuery()):
            raise OperationError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
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
            DataSyncService(repository, loaded.provider, loaded.query_policy, loaded.source_policy),
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
        data = DataSyncService(repository, loaded.provider, loaded.query_policy, loaded.source_policy)
        synchronization = DataSynchronization(loaded.job, loaded.request, store.watchlist, data)
        yield ProviderQualificationService(
            loaded, synchronization, data, _ledger(store)
        )


@contextmanager
def open_daily_research_cycle(
    data_root: Path,
    job_file: Path,
    *,
    credential_adapter: CredentialAdapter | None = None,
    migrations_root: Path | None = None,
    provider_runtime: ProviderRuntimeAdapter | None = None,
) -> Iterator[DailyResearchCycle]:
    loaded = load_sync_job(job_file, credential_adapter, provider_runtime)
    with _store(data_root, migrations_root) as store:
        repository = DataRepository(
            store.connection,
            _ledger(store),
            store.data_root,
            store.writer_lock,
        )
        research = ResearchWorkflow(
            _ledger(store),
            ResearchEngine(),
            SnapshotToResearchRequestAssembler(),
            _repo_root(),
        )
        plans = PlanService(SQLitePlanRepository(store.connection, store.writer_lock))
        market = MarketEvaluationService(
            SQLiteMarketRepository(store.connection, store.writer_lock), plans
        )
        yield DailyResearchCycle(
            loaded.job,
            loaded.request,
            store.watchlist,
            DataSyncService(repository, loaded.provider, loaded.query_policy, loaded.source_policy),
            research,
            market,
            store,
        )


@contextmanager
def open_research_workflow(
    data_root: Path,
    *,
    migrations_root: Path | None = None,
    research_engine: ResearchEngine | None = None,
    fault_injector=None,
) -> Iterator[ResearchWorkflow]:
    with _store(data_root, migrations_root) as store:
        store.workflow_ledger.fault_injector = fault_injector
        yield ResearchWorkflow(
            _ledger(store),
            research_engine or ResearchEngine(),
            SnapshotToResearchRequestAssembler(),
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
        yield WorkspaceService(store.connection, _ledger(store), store.writer_lock)


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
) -> Iterator[PlanConfirmation]:
    with _store(data_root, migrations_root) as store:
        yield PlanService(SQLitePlanRepository(store.connection, store.writer_lock))


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
                ResearchEngine(),
                SnapshotToResearchRequestAssembler(),
                repo_root,
            ),
            PlanService(SQLitePlanRepository(store.connection, store.writer_lock)),
            repo_root,
        )


@contextmanager
def open_market(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[MarketEvaluationService]:
    with _store(data_root, migrations_root) as store:
        plans = PlanService(SQLitePlanRepository(store.connection, store.writer_lock))
        yield MarketEvaluationService(
            SQLiteMarketRepository(store.connection, store.writer_lock), plans
        )


def open_account(
    data_root: Path,
    repo_root: Path | None = None,
    migrations_root: Path | None = None,
) -> AccountOpeningService:
    root = repo_root or _repo_root()
    migration_path = migrations_root or root / "migrations"
    _assert_store_ready(data_root, migration_path)
    return AccountOpeningService(data_root, root, migration_path)


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
    "open_account",
    "open_account_acceptance",
    "open_account_history",
    "open_acceptance_evidence",
    "open_chart_annotations",
    "open_chart_workspace",
    "open_browser_acceptance_fixture",
    "open_data_synchronization",
    "open_daily_research_cycle",
    "open_import_preview",
    "open_market",
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
