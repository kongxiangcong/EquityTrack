from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from trading_platform.data.repository import DataRepository
from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import DataProvider, FixtureRights
from trading_platform.persistence import PlatformStore

from .facade import ApplicationFacade


class ProductionCompositionRoot:
    """Owns one facade instance and, later, its production dependencies."""

    def __init__(self, data_root: Path | None = None, migrations_root: Path | None = None, providers: Sequence[DataProvider] = (), fixture_rights: Mapping[tuple[str, str], FixtureRights] | None = None) -> None:
        self._store = None
        data_sync = None
        if data_root is not None:
            root = Path(__file__).resolve().parents[3]
            self._store = PlatformStore(data_root, migrations_root or root / "migrations")
            self._store.migrate()
            if providers:
                repository = DataRepository(self._store.connection, self._store.objects, self._store.writer_lock)
                data_sync = DataSyncService(repository, providers, fixture_rights)
        self._facade = ApplicationFacade(self._store, data_sync)

    @property
    def facade(self) -> ApplicationFacade:
        return self._facade

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
