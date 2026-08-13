from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import cast

from trading_platform.account import AccountOpeningService
from trading_platform.account_acceptance import AccountAcceptanceService
from trading_platform.account_history import AccountHistoryImportService
from trading_platform.application.health import Health
from trading_platform.application.account_snapshots import (
    AccountSnapshotCommands,
    AccountSnapshotQueries,
)
from trading_platform.application.account_state import AccountStateQueries
from trading_platform.application.commands import (
    ApplicationCommandDispatcher,
)
from trading_platform.application.decision_journal import DecisionJournal
from trading_platform.application.decision_tasks import DecisionTasks
from trading_platform.application.discipline_reviews import (
    DisciplineReviews,
)
from trading_platform.application.manual_portfolio_review import (
    ManualPortfolioReview,
)
from trading_platform.application.plan_impacts import PlanImpacts
from trading_platform.application.read_models import ReadModelService
from trading_platform.application.plan_compiler import (
    TradePlanCompiler,
)
from trading_platform.application.plan_drafting import TradePlanDrafting
from trading_platform.application.risk_policies import (
    PortfolioRiskPolicies,
)
from trading_platform.application.strategy_catalog import StrategyQueries
from trading_platform.application.trade_plan_authoring import (
    TradePlanTasks,
    _OpenTradePlanDrafts,
)
from trading_platform.application.research_tasks import (
    ForecastReview,
    ResearchArchive,
    WorkflowInspection,
)
from trading_platform.application.workflow_ledger import WorkflowLedgerPort
from trading_platform.chart import ChartService
from trading_platform.data.repository import DataRepository
from trading_platform.data.service import DataSyncService
from trading_platform.domain.account_snapshots import (
    AccountSnapshotService,
)
from trading_platform.domain.data import (
    CompletenessRequirement,
    DataProvider,
    FallbackMode,
    FixtureRights,
    QueryPolicy,
    SourceAuthority,
    SourceFailureDisposition,
    SourcePolicy,
    SourceRights,
    SourceRoute,
)
from trading_platform.domain.discipline_reviews import (
    DisciplineReviewService,
)
from trading_platform.market import MarketEvaluationService
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.account_snapshots import (
    SQLiteAccountSnapshotProjection,
    SQLiteAccountSnapshotRepository,
)
from trading_platform.persistence.decision_tasks import (
    SQLiteDecisionTaskRepository,
)
from trading_platform.persistence.discipline_reviews import (
    SQLiteDisciplineReviewRepository,
)
from trading_platform.persistence.manual_portfolio_review import (
    SQLiteManualPortfolioReviewRepository,
)
from trading_platform.persistence.market import SQLiteMarketRepository
from trading_platform.persistence.plan_impacts import (
    SQLitePlanImpactRepository,
)
from trading_platform.persistence.plans import SQLiteTradePlanRepository
from trading_platform.persistence.risk_policies import (
    SQLitePortfolioRiskPolicyRepository,
)
from trading_platform.persistence.strategies import (
    SQLiteStrategyRepository,
)
from trading_platform.persistence.workspace import (
    WorkspaceUpdateAuthorizationService,
)
from trading_platform.persistence.read_models import (
    SQLiteReadModelProjection,
)
from trading_platform.persistence.decision_journal import (
    SQLiteDecisionJournalRepository,
)
from trading_platform.operations import PlatformOperations
from trading_platform.workflows.research import (
    ResearchWorkflow,
    research_engine_identity,
)

TEST_QUERY_POLICY = QueryPolicy("QueryPolicy@1", 7, "L", "none")
TEST_CHART_QUERY_POLICY = QueryPolicy("QueryPolicy@1", 30, "L", "none")
TEST_MARKET_QUERY_POLICY = QueryPolicy("QueryPolicy@1", 365, "L", "none")
TEST_SOURCE_POLICY = SourcePolicy(
    "SourcePolicy@1",
    "test-fixture",
    "fixture@1",
    "test-fixture-source",
    SourceAuthority.FIXTURE,
    "test-terms@1",
    SourceRights(True, True, True, False, False, "2026-07-10"),
    tuple(
        SourceRoute(
            dataset,
            1,
            CompletenessRequirement.REQUIRED,
            1,
            FallbackMode.NO_FALLBACK,
            SourceFailureDisposition.BLOCK,
        )
        for dataset in ("daily", "financial_statement")
    ),
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
                "INSERT OR IGNORE INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "snapshot_market_20260710", "security_yihua", "workflow",
                    "2026-07-11", "2026-07-10", "2026-07-11T00:00:00+00:00",
                    "Asia/Shanghai", "cn-calendar@2026",
                    TEST_QUERY_POLICY.identity, TEST_SOURCE_POLICY.identity,
                    "freshness@1", "market-members", "valid", "pass", 0, 0, 0,
                    0, 0, "test workflow snapshot", "2026-07-11T00:00:00+00:00",
                ),
            )
            self._store.connection.execute(
                "INSERT OR IGNORE INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("attempt_market", "market-refresh", "fixture", "fixture@1", "daily", "derived-fixture", "fixture", "urn:test:daily", "{}", "{}", "date", "test-terms", "complete", "created", None, "2026-07-10T09:00:00+00:00", None, None, None, "not_applicable", TEST_QUERY_POLICY.identity, TEST_SOURCE_POLICY.identity, "rights_test_fixture"),
            )
            self._store.connection.execute("INSERT OR IGNORE INTO normalized_record VALUES(?,?,?)", ("record_market", "daily", "security_yihua:2026-07-10"))
            self._store.connection.execute("INSERT OR IGNORE INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("daily:2026-07-10", "record_market", 1, "market-content", "attempt_market", TEST_SOURCE_POLICY.identity, "2026-07-10", "2026-07-10", "date", "2026-07-10T09:00:00+00:00", "publisher_timestamp", "2026-07-10T09:00:00+00:00", "pass", None))
            self._store.connection.execute("INSERT OR IGNORE INTO data_snapshot_member VALUES(?,?,?,?)", ("snapshot_market_20260710", "daily:2026-07-10", "daily", 0))

    def record_official_filing_workflow_snapshot(self) -> None:
        """Create a research-relevant filing candidate for PIT policy tests."""
        with self._store.connection:
            self._store.connection.execute("INSERT OR IGNORE INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("attempt_filing", "filing-refresh", "official", "official@1", "financial_statement", "CNINFO", "official", "urn:test:filing", "{}", "{}", "timestamp", "official-terms", "complete", "created", None, "2026-07-10T09:00:00+00:00", None, None, None, "not_applicable", TEST_QUERY_POLICY.identity, TEST_SOURCE_POLICY.identity, "rights_test_fixture"))
            self._store.connection.execute("INSERT OR IGNORE INTO normalized_record VALUES(?,?,?)", ("record_filing", "financial_statement", "security_yihua:2026Q2"))
            self._store.connection.execute("INSERT OR IGNORE INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("filing:2026Q2", "record_filing", 1, "filing-content", "attempt_filing", TEST_SOURCE_POLICY.identity, "2026-06-30", "2026-07-10T08:00:00+00:00", "timestamp", "2026-07-10T08:00:00+00:00", "publisher_timestamp", "2026-07-10T09:00:00+00:00", "pass", None))
            self._store.connection.execute("INSERT OR IGNORE INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("snapshot_filing", "security_yihua", "workflow", "2026-07-11", "2026-07-10", "2026-07-11T00:00:00+00:00", "Asia/Shanghai", "cn-calendar@2026", TEST_QUERY_POLICY.identity, TEST_SOURCE_POLICY.identity, "freshness@1", "filing-members", "valid", "pass", 1, 1, 0, 0, 0, "official filing candidate", "2026-07-11T00:00:00+00:00"))
            self._store.connection.execute("INSERT OR IGNORE INTO data_snapshot_member VALUES(?,?,?,?)", ("snapshot_filing", "filing:2026Q2", "financial_statement", 0))

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
        workflow_fault_injector=None,
        workbook_projector=None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.data_root = data_root.resolve()
        migration_path = migrations_root or repo_root / "migrations"
        if not (data_root / "platform.sqlite3").is_file():
            result = PlatformOperations(data_root, migration_path).bootstrap()
            if result["status"] != "passed":
                raise RuntimeError("Test platform bootstrap failed")
        store = PlatformStore(data_root, migration_path)
        with store.connection:
            for policy in (
                TEST_QUERY_POLICY,
                TEST_CHART_QUERY_POLICY,
                TEST_MARKET_QUERY_POLICY,
            ):
                canonical_json = json.dumps(
                    policy.canonical_content,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                store.connection.execute(
                    "INSERT OR IGNORE INTO query_policy_record VALUES(?,?,?,?,?)",
                    (
                        policy.identity,
                        policy.schema_version,
                        hashlib.sha256(canonical_json.encode()).hexdigest(),
                        canonical_json,
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
            source_json = json.dumps(
                TEST_SOURCE_POLICY.canonical_content,
                sort_keys=True,
                separators=(",", ":"),
            )
            store.connection.execute(
                "INSERT OR IGNORE INTO source_policy_record VALUES(?,?,?,?,?)",
                (
                    TEST_SOURCE_POLICY.identity,
                    TEST_SOURCE_POLICY.schema_version,
                    hashlib.sha256(source_json.encode()).hexdigest(),
                    source_json,
                    "2026-07-10T00:00:00+00:00",
                ),
            )
            store.connection.execute(
                "INSERT OR IGNORE INTO source_rights_profile VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "rights_test_fixture",
                    "source",
                    "test-fixture",
                    "test-fixture-source",
                    "test-terms@1",
                    1,
                    1,
                    1,
                    0,
                    0,
                    "2026-07-10",
                    None,
                ),
            )
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
            self.data = DataSyncService(
                repository,
                provider,
                query_policy,
                source_policy,
                fixture_rights,
                tuple(qualified_equivalents),
                qualified_equivalent_authority,
            )
        self.research = ResearchWorkflow(
            ledger,
            repo_root,
            workflow_fault_injector,
            workbook_projector,
        )
        self.inspection = WorkflowInspection(ledger)
        self.archive = ResearchArchive(ledger)
        self.forecast_review = ForecastReview(
            ledger, research_engine_identity(repo_root)
        )
        self.chart = ChartService(store.connection, store.writer_lock)
        account_snapshot_projection = SQLiteAccountSnapshotProjection(
            store.connection
        )
        journal_repository = SQLiteDecisionJournalRepository(
            store.connection, store.writer_lock
        )
        account_state_queries = AccountStateQueries(
            account_snapshot_projection,
            journal_repository,
        )
        self.account_snapshot_commands = AccountSnapshotCommands(
            SQLiteAccountSnapshotRepository(
                store.connection, store.writer_lock
            ),
            AccountSnapshotService(),
        )
        self.account_snapshot_queries = AccountSnapshotQueries(
            account_snapshot_projection
        )
        self.risk_policies = PortfolioRiskPolicies(
            SQLitePortfolioRiskPolicyRepository(
                store.connection, store.writer_lock
            )
        )
        self.strategies = StrategyQueries(
            SQLiteStrategyRepository(store.connection)
        )
        plan_repository = SQLiteTradePlanRepository(
            store.connection, store.writer_lock
        )
        self.plans = TradePlanTasks(plan_repository)
        self._open_plan_drafts = _OpenTradePlanDrafts(plan_repository)
        self.plan_compiler = TradePlanCompiler(
            research=self.archive,
            recent_trends=self.archive,
            accounts=self.account_snapshot_queries,
            risk_policies=self.risk_policies,
            strategies=self.strategies,
            drafts=self._open_plan_drafts,
        )
        self.plan_drafting = TradePlanDrafting(
            archive=self.archive,
            accounts=self.account_snapshot_queries,
            watchlist=self.watchlist,
            compiler=self.plan_compiler,
        )
        self.manual_reviews = ManualPortfolioReview(
            SQLiteManualPortfolioReviewRepository(
                store.connection, store.writer_lock
            ),
            account_state_queries,
            ledger,
        )
        self.decision_tasks = DecisionTasks(
            SQLiteDecisionTaskRepository(
                store.connection, store.writer_lock
            ),
            journal_repository,
        )
        self.decision_journal = DecisionJournal(journal_repository)
        self.discipline_reviews = DisciplineReviews(
            SQLiteDisciplineReviewRepository(
                store.connection, store.writer_lock
            ),
            DisciplineReviewService(),
        )
        self.plan_impacts = PlanImpacts(
            SQLitePlanImpactRepository(
                store.connection, store.writer_lock
            ),
            self.manual_reviews,
            self.plans,
            self._open_plan_drafts,
        )
        self.application_commands = ApplicationCommandDispatcher(
            account_snapshots=self.account_snapshot_commands,
            risk_policies=self.risk_policies,
            trade_plans=self.plans,
            plan_drafting=self.plan_drafting,
            manual_reviews=self.manual_reviews,
            decision_tasks=self.decision_tasks,
            decision_journal=self.decision_journal,
            discipline_reviews=self.discipline_reviews,
            plan_impacts=self.plan_impacts,
            chart_workspace=self.chart,
        )
        self.market = MarketEvaluationService(
            SQLiteMarketRepository(store.connection, store.writer_lock),
            plan_repository,
        )
        self.update_authorizations = WorkspaceUpdateAuthorizationService(
            store.connection, store.writer_lock
        )
        self.read_models = ReadModelService(
            SQLiteReadModelProjection(
                store.connection,
                account_state_queries,
                ledger,
            ),
            self.chart,
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
