from __future__ import annotations

from pathlib import Path

from trading_platform.application.contracts import DoctorReport, SecurityIdentity, WatchlistView

from .database import open_database
from .doctor import DoctorService
from .locking import DataRootWriterLock, PersistenceError
from .migration import MigrationRunner
from .watchlist import WatchlistRepository
from .workflow_ledger import WorkflowLedger


class PlatformStore:
    def __init__(self, data_root: Path, migrations_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.migrations_root = migrations_root.resolve()
        self.connection = open_database(self.data_root)
        self.writer_lock = DataRootWriterLock(self.data_root)
        self.migrations = MigrationRunner(self.connection, self.data_root, self.migrations_root, self.writer_lock)
        self.workflow_ledger = WorkflowLedger(self.connection, self.data_root, self.writer_lock)
        self.watchlist = WatchlistRepository(self.connection, self.writer_lock)
        self.doctor_service = DoctorService(self.connection, self.migrations, self.workflow_ledger)

    def migrate(self, fail_after: int | None = None) -> None:
        self.migrations.migrate(fail_after)

    def add_watchlist_item(self, invocation_id: str, security: SecurityIdentity) -> WatchlistView:
        return self.watchlist.add(invocation_id, security)

    def list_watchlist_items(self) -> tuple[WatchlistView, ...]:
        return self.watchlist.list()

    def doctor(self) -> DoctorReport:
        return self.doctor_service.run()

    def close(self) -> None:
        self.connection.close()


__all__ = ["PersistenceError", "PlatformStore"]
