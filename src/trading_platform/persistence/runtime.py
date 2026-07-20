from __future__ import annotations

from pathlib import Path

from trading_platform.application.contracts import DoctorReport

from .database import open_database
from .doctor import DoctorService
from .locking import DataRootWriterLock, PersistenceError
from .migration import MigrationRunner
from .watchlist import SQLiteWatchlist
from .workflow_ledger import WorkflowLedger


class PlatformStore:
    def __init__(self, data_root: Path, migrations_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.migrations_root = migrations_root.resolve()
        self.connection = open_database(self.data_root)
        self.writer_lock = DataRootWriterLock(self.data_root)
        self.migrations = MigrationRunner(self.connection, self.data_root, self.migrations_root, self.writer_lock)
        self.workflow_ledger = WorkflowLedger(self.connection, self.data_root, self.writer_lock)
        self.watchlist = SQLiteWatchlist(self.connection, self.writer_lock)
        self.doctor_service = DoctorService(self.connection, self.migrations, self.workflow_ledger)

    def migrate(self, fail_after: int | None = None) -> None:
        self.migrations.migrate(fail_after)

    def doctor(self) -> DoctorReport:
        return self.doctor_service.run()

    def close(self) -> None:
        self.connection.close()


__all__ = ["PersistenceError", "PlatformStore"]
