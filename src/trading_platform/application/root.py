from __future__ import annotations

from pathlib import Path

from trading_platform.persistence import PlatformStore

from .facade import ApplicationFacade


class ProductionCompositionRoot:
    """Owns one facade instance and, later, its production dependencies."""

    def __init__(self, data_root: Path | None = None, migrations_root: Path | None = None) -> None:
        self._store = None
        if data_root is not None:
            root = Path(__file__).resolve().parents[3]
            self._store = PlatformStore(data_root, migrations_root or root / "migrations")
            self._store.migrate()
        self._facade = ApplicationFacade(self._store)

    @property
    def facade(self) -> ApplicationFacade:
        return self._facade

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
