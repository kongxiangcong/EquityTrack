from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


_OPEN_CONNECTIONS: set[SQLiteOwningAdapterFixture] = set()
_OPEN_CONNECTIONS_LOCK = threading.Lock()


class SQLiteOwningAdapterFixture(sqlite3.Connection):
    """Real SQLite connection restricted to owning persistence/fault tests."""

    def __init__(self, data_root: Path) -> None:
        super().__init__(str(data_root / "platform.sqlite3"), isolation_level=None)
        self.row_factory = sqlite3.Row
        with _OPEN_CONNECTIONS_LOCK:
            _OPEN_CONNECTIONS.add(self)

    def close(self) -> None:
        with _OPEN_CONNECTIONS_LOCK:
            _OPEN_CONNECTIONS.discard(self)
        super().close()

    @contextmanager
    def transaction(self):
        self.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()


def close_open_owning_adapter_connections() -> None:
    """Close every owning-test connection at the deterministic pytest boundary."""
    with _OPEN_CONNECTIONS_LOCK:
        connections = tuple(_OPEN_CONNECTIONS)
    for connection in connections:
        connection.close()
