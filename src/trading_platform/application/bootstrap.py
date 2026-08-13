from __future__ import annotations

import os
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
from trading_platform.persistence.risk_policies import (
    SQLitePortfolioRiskPolicyRepository,
)
from trading_platform.persistence.presence import RuntimePresence
from trading_platform.persistence.workspace import (
    WorkspaceUpdateAuthorizationService,
)
from trading_platform.operations import PlatformOperations
from trading_platform.operations import OperationError
from trading_platform.provider_config import ProviderRuntimeAdapter, load_sync_job
from trading_platform.provider_qualification import ProviderQualificationService
from trading_platform.workflows.research import ResearchWorkflow
from trading_platform.verification import (
    ProjectVerification,
    SubprocessVerificationExecutor,
)
from trading_platform.application.research_workbook import (
    ResearchWorkbookProjector,
)
from trading_platform.valuation_workbook import ValuationWorkbookAdapter

from .cli_tasks import DataSynchronization
from .health import Health
from .watchlist import Watchlist
from .research_tasks import ResearchArchive, WorkflowInspection
from .research_publication import ResearchPublication
from .workflow_ledger import QualificationReceiptQuery, WorkflowLedgerPort
from .web_tasks import (
    ChartWorkspace,
    UpdateAuthorizations,
)
from .browser_acceptance import BrowserAcceptanceFixture, load_browser_fixture
from .account_snapshots import AccountSnapshotCommands, AccountSnapshotQueries
from .account_state import AccountStateQueries
from .strategy_catalog import StrategyQueries
from .risk_policies import PortfolioRiskPolicies
from .trade_plan_authoring import (
    TradePlanTasks,
    _OpenTradePlanDrafts,
)
from .plan_compiler import TradePlanCompiler
from .plan_drafting import TradePlanDrafting
from .commands import ApplicationCommandDispatcher
from .manual_portfolio_review import ManualPortfolioReview
from .decision_tasks import DecisionTasks
from .decision_journal import DecisionJournal
from .discipline_reviews import DisciplineReviews
from .plan_impacts import PlanImpacts
from .read_models import ReadModelService
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
from trading_platform.persistence.plan_impacts import (
    SQLitePlanImpactRepository,
)
from trading_platform.persistence.research_publication import (
    FilesystemResearchPublicationRepository,
)
from trading_platform.persistence.read_models import (
    SQLiteReadModelProjection,
)
from trading_platform.domain.discipline_reviews import (
    DisciplineReviewService,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _research_workbook_projector(
    repo_root: Path,
) -> ResearchWorkbookProjector | None:
    node = os.environ.get("CODEX_ARTIFACT_NODE")
    node_modules = os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    if not node or not node_modules:
        return None
    return ValuationWorkbookAdapter(
        node_executable=Path(node),
        node_modules=Path(node_modules),
        builder_script=repo_root / "scripts" / "render_valuation_xlsx.mjs",
    )


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
    resolved_migrations = migrations_root or _repo_root() / "migrations"
    store = PlatformStore(data_root, resolved_migrations)
    try:
        files, applied = store.migrations.validate()
        if len(files) != len(applied):
            store.close()
            migrated = PlatformOperations(
                data_root, resolved_migrations
            ).migrate()
            if migrated.get("status") != "passed":
                raise OperationError(
                    "PLATFORM_MIGRATION_FAILED",
                    ",".join(migrated.get("errors", ())),
                )
            store = PlatformStore(data_root, resolved_migrations)
            files, applied = store.migrations.validate()
            if len(files) != len(applied):
                raise OperationError(
                    "PLATFORM_MIGRATION_INCOMPLETE",
                    "The safe lifecycle migration did not reach the current schema.",
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
    migrations_root: Path | None = None,
    provider_runtime: ProviderRuntimeAdapter | None = None,
) -> Iterator[DataSynchronization]:
    loaded = load_sync_job(job_file, provider_runtime)
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
    migrations_root: Path | None = None,
    provider_runtime: ProviderRuntimeAdapter | None = None,
) -> Iterator[ProviderQualificationService]:
    loaded = load_sync_job(job_file, provider_runtime)
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
            _research_workbook_projector(_repo_root()),
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
def open_research_publication(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ResearchPublication]:
    with _store(data_root, migrations_root) as store:
        yield ResearchPublication(
            _ledger(store),
            ChartService(store.connection, store.writer_lock),
            store.watchlist,
            FilesystemResearchPublicationRepository(
                store.data_root, store.writer_lock
            ),
        )


@contextmanager
def open_application_commands(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[ApplicationCommandDispatcher]:
    with _store(data_root, migrations_root) as store:
        ledger = _ledger(store)
        archive = ResearchArchive(ledger)
        journal_repository = SQLiteDecisionJournalRepository(
            store.connection, store.writer_lock
        )
        journal = DecisionJournal(journal_repository)
        account_snapshots = AccountSnapshotCommands(
            SQLiteAccountSnapshotRepository(
                store.connection, store.writer_lock
            ),
            AccountSnapshotService(),
        )
        account_snapshot_queries = AccountSnapshotQueries(
            SQLiteAccountSnapshotProjection(store.connection)
        )
        risk_policies = PortfolioRiskPolicies(
            SQLitePortfolioRiskPolicyRepository(
                store.connection, store.writer_lock
            )
        )
        plan_repository = SQLiteTradePlanRepository(
            store.connection, store.writer_lock
        )
        trade_plans = TradePlanTasks(plan_repository)
        open_drafts = _OpenTradePlanDrafts(plan_repository)
        plan_compiler = TradePlanCompiler(
            research=archive,
            recent_trends=archive,
            accounts=account_snapshot_queries,
            risk_policies=risk_policies,
            strategies=StrategyQueries(
                SQLiteStrategyRepository(store.connection)
            ),
            drafts=open_drafts,
        )
        plan_drafting = TradePlanDrafting(
            archive=archive,
            accounts=account_snapshot_queries,
            watchlist=store.watchlist,
            compiler=plan_compiler,
        )
        manual_reviews = ManualPortfolioReview(
            SQLiteManualPortfolioReviewRepository(
                store.connection, store.writer_lock
            ),
            AccountStateQueries(
                SQLiteAccountSnapshotProjection(store.connection),
                journal_repository,
            ),
            ledger,
        )
        yield ApplicationCommandDispatcher(
            account_snapshots=account_snapshots,
            risk_policies=risk_policies,
            trade_plans=trade_plans,
            plan_drafting=plan_drafting,
            manual_reviews=manual_reviews,
            decision_tasks=DecisionTasks(
                SQLiteDecisionTaskRepository(
                    store.connection, store.writer_lock
                ),
                journal_repository,
            ),
            decision_journal=journal,
            discipline_reviews=DisciplineReviews(
                SQLiteDisciplineReviewRepository(
                    store.connection, store.writer_lock
                ),
                DisciplineReviewService(),
            ),
            plan_impacts=PlanImpacts(
                SQLitePlanImpactRepository(
                    store.connection, store.writer_lock
                ),
                manual_reviews,
                trade_plans,
                open_drafts,
            ),
            chart_workspace=ChartService(
                store.connection, store.writer_lock
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
def open_plan_impacts(
    data_root: Path,
    migrations_root: Path | None = None,
) -> Iterator[PlanImpacts]:
    with _store(data_root, migrations_root) as store:
        journal_repository = SQLiteDecisionJournalRepository(
            store.connection, store.writer_lock
        )
        manual_reviews = ManualPortfolioReview(
            SQLiteManualPortfolioReviewRepository(
                store.connection, store.writer_lock
            ),
            AccountStateQueries(
                SQLiteAccountSnapshotProjection(store.connection),
                journal_repository,
            ),
            _ledger(store),
        )
        plan_repository = SQLiteTradePlanRepository(
            store.connection, store.writer_lock
        )
        plan_tasks = TradePlanTasks(plan_repository)
        open_drafts = _OpenTradePlanDrafts(plan_repository)
        yield PlanImpacts(
            SQLitePlanImpactRepository(
                store.connection, store.writer_lock
            ),
            manual_reviews,
            plan_tasks,
            open_drafts,
        )


@contextmanager
def open_read_models(
    data_root: Path,
    migrations_root: Path | None = None,
) -> Iterator[ReadModelService]:
    with _store(data_root, migrations_root) as store:
        yield ReadModelService(
            SQLiteReadModelProjection(
                store.connection,
                AccountStateQueries(
                    SQLiteAccountSnapshotProjection(store.connection),
                    SQLiteDecisionJournalRepository(
                        store.connection, store.writer_lock
                    ),
                ),
                _ledger(store),
            ),
            ChartService(store.connection, store.writer_lock),
        )


@contextmanager
def open_update_authorizations(
    data_root: Path, migrations_root: Path | None = None
) -> Iterator[UpdateAuthorizations]:
    with _store(data_root, migrations_root) as store:
        yield WorkspaceUpdateAuthorizationService(
            store.connection, store.writer_lock
        )


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
                workbook_projector=(
                    _research_workbook_projector(repo_root)
                ),
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
    "open_browser_acceptance_fixture",
    "open_data_synchronization",
    "open_import_preview",
    "open_market",
    "open_manual_portfolio_review",
    "open_decision_tasks",
    "open_decision_journal",
    "open_discipline_reviews",
    "open_platform_health",
    "open_platform_operations",
    "open_project_verification",
    "open_provider_qualification",
    "open_read_models",
    "open_research_archive",
    "open_research_workflow",
    "open_watchlist",
    "open_update_authorizations",
    "open_server_runtime",
    "open_workflow_runtime",
    "open_workflow_inspection",
]
