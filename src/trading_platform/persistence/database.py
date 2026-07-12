from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .locking import PersistenceError


def validate_local_data_root(path: Path) -> None:
    lowered = str(path).casefold()
    remote_drive = False
    if os.name == "nt" and path.drive:
        import ctypes

        remote_drive = ctypes.windll.kernel32.GetDriveTypeW(f"{path.drive}\\") == 4
    synchronized_names = {"onedrive", "dropbox", "googledrive", "sharepoint"}
    if lowered.startswith("\\\\") or remote_drive or any(part.casefold() in synchronized_names for part in path.parts):
        raise PersistenceError("DATA_ROOT_NOT_LOCAL", "Active data root must be on a local, non-synchronized path.")


def open_database(data_root: Path) -> sqlite3.Connection:
    validate_local_data_root(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(data_root / "platform.sqlite3", timeout=5, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection
