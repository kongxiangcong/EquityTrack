from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .locking import DataRootWriterLock, PersistenceError, _process_is_alive


class RuntimePresence:
    def __init__(self, data_root: Path, role: str) -> None:
        self.path = data_root / f".{role}.presence"
        self.role = role

    @contextmanager
    def acquire(self) -> Iterator[None]:
        payload = {"role": self.role, "pid": os.getpid()}
        with DataRootWriterLock(self.path.parent).acquire(f"runtime-presence:{self.role}"):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as error:
                try: current = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError): current = {"pid": -1}
                if not _process_is_alive(int(current.get("pid", -1))):
                    self.path.unlink(missing_ok=True)
                    descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                else: raise PersistenceError("RUNTIME_BUSY", f"Active {self.role} runtime blocks maintenance.") from error
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
        try: yield
        finally:
            try: current = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError): current = {}
            if current.get("pid") == os.getpid(): self.path.unlink(missing_ok=True)


def assert_maintenance_available(data_root: Path) -> None:
    for role in ("server", "workflow"):
        presence = RuntimePresence(data_root, role)
        if not presence.path.exists(): continue
        try: current = json.loads(presence.path.read_text(encoding="utf-8"))
        except (OSError, ValueError): current = {"pid": -1}
        if _process_is_alive(int(current.get("pid", -1))): raise PersistenceError("MAINTENANCE_RUNTIME_ACTIVE", f"Active {role} runtime blocks maintenance.")
        presence.path.unlink(missing_ok=True)
