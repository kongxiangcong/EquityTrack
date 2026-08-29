"""The sole application Interface and its composition root."""

from __future__ import annotations

from pathlib import Path

from trading_platform.application.core import Application, STABLE_FAILURES
from trading_platform.result import OperationResult
from trading_platform.storage import SQLiteStore


def open_application(data_root: Path, *, fault_at: str | None = None) -> Application:
    return Application(SQLiteStore(Path(data_root), fault_at=fault_at))


__all__ = ["Application", "OperationResult", "STABLE_FAILURES", "open_application"]
