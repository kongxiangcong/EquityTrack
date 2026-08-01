from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class PersistenceError(RuntimeError):
    def __init__(self, code: str, message: str, owner_ref: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.owner_ref = owner_ref


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class DataRootWriterLock:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / ".writer.lock"

    @contextmanager
    def acquire(self, owner_ref: str) -> Iterator[None]:
        lease_id = uuid.uuid4().hex
        payload = {
            "owner_ref": owner_ref,
            "pid": os.getpid(),
            "lease_id": lease_id,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        for attempt in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                break
            except (FileExistsError, PermissionError) as error:
                parsed = True
                try:
                    current = json.loads(
                        self.path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError, TypeError):
                    parsed = False
                    current = {"owner_ref": "unknown"}
                owner = str(current.get("owner_ref", "unknown"))
                pid = current.get("pid")
                if (
                    attempt == 0
                    and parsed
                    and isinstance(pid, int)
                    and not _process_is_alive(pid)
                ):
                    try:
                        self.path.unlink(missing_ok=True)
                    except PermissionError as unlink_error:
                        raise PersistenceError(
                            "RUNTIME_BUSY",
                            "Another mutation writer owns this data root.",
                            owner,
                        ) from unlink_error
                    continue
                raise PersistenceError(
                    "RUNTIME_BUSY",
                    "Another mutation writer owns this data root.",
                    owner,
                ) from error
        try:
            yield
        finally:
            try:
                current = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                current = {}
            if current.get("lease_id") == lease_id:
                for attempt in range(40):
                    try:
                        self.path.unlink(missing_ok=True)
                        break
                    except PermissionError:
                        if attempt == 39:
                            raise
                        time.sleep(0.05)
