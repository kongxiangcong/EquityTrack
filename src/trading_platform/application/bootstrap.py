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
from trading_platform.provider_config import load_sync_job
from trading_platform.provider_qualification import ProviderQualificationService
from trading_platform.credentials import CredentialAdapter
from trading_platform.research import SnapshotToResearchRequestAssembler
from trading_platform.workflows.research import ResearchWorkflow, research_engine_identity
from trading_platform.verification import ProjectVerification, SubprocessVerificationExecutor

from .facade import ApplicationFacade
from .cli_tasks import DailyResearchCycle, DataSynchronization
from .health import Health
from .watchlist import Watchlist
from .research_tasks import ForecastReview, ResearchArchive, WorkflowInspection
from .workflow_ledger import ResearchViewCutoverCompleteQuery, WorkflowLedgerPort


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ledger(store: PlatformStore) -> WorkflowLedgerPort:
    return cast(WorkflowLedgerPort, store.workflow_ledger)


@contextmanager
def _store(data_root: Path, migrations_root: Path | None = None) -> Iterator[PlatformStore]:
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


def _assert_store_ready(
    data_root: Path, migrations_root: Path | None = None
) -> None:
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
def open_data_sync(
    data_root: Path,
    *,
    providers: Sequence[DataProvider],
    fixture_rights: Mapping[tuple[str, str], FixtureRights] | None = None,
    migrations_root: Path | None = None,
    fault_injector=None,
) -> Iterator[DataSyncService]:
    with _store(data_root, migrations_root) as store:
        repository = DataRepository(
            store.connection,
            _ledger(store),
            store.data_root,
            store.writer_lock,
        )
        repository.fault_injector = fault_injector
        yield DataSyncService(repository, providers, fixture_rights)


@contextmanager
def open_data_synchronization(
    data_root: Path,
    job_file: Path,
    *,
    credential_adapter: CredentialAdapter | None = None,
    migrations_root: Path | None = None,
) -> Iterator[DataSynchronization]:
    job, provider, request = load_sync_job(job_file, credential_adapter)
    with _store(data_root, migrations_root) as store:
        repository = DataRepository(
            store.connection,
            _ledger(store),
            store.data_root,
            store.writer_lock,
        )
        yield DataSynchronization(
            job,
            request,
            store.watchlist,
            DataSyncService(repository, (provider,)),
        )


@contextmanager
def open_provider_qualification(
    data_root: Path,
    job_file: Path,
    *,
    credential_adapter: CredentialAdapter | None = None,
    migrations_root: Path | None = None,
) -> Iterator[ProviderQualificationService]:
    job, provider, request = load_sync_job(job_file, credential_adapter)
    with _store(data_root, migrations_root) as store:
        repository = DataRepository(
            store.connection,
            _ledger(store),
            store.data_root,
            store.writer_lock,
        )
        data = DataSyncService(repository, (provider,))
        synchronization = DataSynchronization(
            job, request, store.watchlist, data
        )
        yield ProviderQualificationService(
            dict(job["provider"]), request, synchronization, data
        )


@contextmanager
def open_daily_research_cycle(
    data_root: Path,
    job_file: Path,
    *,
    credential_adapter: CredentialAdapter | None = None,
    migrations_root: Path | None = None,
) -> Iterator[DailyResearchCycle]:
    job, provider, request = load_sync_job(job_file, credential_adapter)
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
            job,
            request,
            store.watchlist,
            DataSyncService(repository, (provider,)),
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
def open_forecast_review(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ForecastReview]:
    with _store(data_root, migrations_root) as store:
        yield ForecastReview(_ledger(store), research_engine_identity(_repo_root()))


@contextmanager
def open_workspace(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[WorkspaceService]:
    with _store(data_root, migrations_root) as store:
        yield WorkspaceService(
            store.connection, _ledger(store), store.writer_lock
        )


@contextmanager
def open_chart(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ChartService]:
    with _store(data_root, migrations_root) as store:
        yield ChartService(store.connection, store.writer_lock)


@contextmanager
def open_plans(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[PlanService]:
    with _store(data_root, migrations_root) as store:
        yield PlanService(SQLitePlanRepository(store.connection, store.writer_lock))


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
    return AccountOpeningService(
        data_root, root, migration_path
    )


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
    return AcceptanceEvidenceService(data_root, repo_root)


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


@contextmanager
def open_web_application(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ApplicationFacade]:
    """Temporary Web-only composition seam removed by Ticket 14."""

    with _store(data_root, migrations_root) as store:
        chart = ChartService(store.connection, store.writer_lock)
        plans = PlanService(SQLitePlanRepository(store.connection, store.writer_lock))
        workspace = WorkspaceService(
            store.connection, _ledger(store), store.writer_lock
        )
        yield ApplicationFacade(chart=chart, plans=plans, workspace=workspace)


__all__ = [
    "open_account",
    "open_account_acceptance",
    "open_account_history",
    "open_acceptance_evidence",
    "open_chart",
    "open_data_sync",
    "open_data_synchronization",
    "open_daily_research_cycle",
    "open_forecast_review",
    "open_import_preview",
    "open_market",
    "open_plans",
    "open_platform_health",
    "open_platform_operations",
    "open_project_verification",
    "open_provider_qualification",
    "open_research_archive",
    "open_research_workflow",
    "open_watchlist",
    "open_web_application",
    "open_server_runtime",
    "open_workflow_runtime",
    "open_workflow_inspection",
    "open_workspace",
]
