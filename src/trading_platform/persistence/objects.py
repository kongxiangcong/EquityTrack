from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

from .locking import DataRootWriterLock, PersistenceError


class ContentAddressedObjectStore:
    def __init__(self, connection: sqlite3.Connection, data_root: Path, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.data_root = data_root
        self.root = data_root / "objects/sha256"
        self.root.mkdir(parents=True, exist_ok=True)
        self.writer_lock = writer_lock
        self.fault_injector = None

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    def publish(self, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        with self.writer_lock.acquire(f"object:{digest}"):
            target = self.root / digest[:2] / digest
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.stat().st_size != len(payload) or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise PersistenceError("OBJECT_HASH_MISMATCH", "Existing content-addressed object is corrupt.")
            else:
                descriptor, temp_name = tempfile.mkstemp(prefix=f".{digest}.", dir=target.parent)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    self._fault("object.temp_fsynced")
                    temp = Path(temp_name)
                    if temp.stat().st_size != len(payload) or hashlib.sha256(temp.read_bytes()).hexdigest() != digest:
                        raise PersistenceError("OBJECT_HASH_MISMATCH", "Temporary object hash mismatch.")
                    os.replace(temp, target)
                    self._fault("object.renamed")
                finally:
                    Path(temp_name).unlink(missing_ok=True)
            relative = target.relative_to(self.data_root).as_posix()
            self._fault("object.before_db_registration")
            with self.connection:
                self.connection.execute("INSERT OR IGNORE INTO object_blob VALUES(?,?,?)", (digest, len(payload), relative))
            self._fault("object.db_registered")
            return digest

    def verify_all(self) -> tuple[str, ...]:
        errors: list[str] = []
        for row in self.connection.execute("SELECT * FROM object_blob"):
            path = self.data_root / row["relative_path"]
            if not path.is_file() or path.stat().st_size != row["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                errors.append("OBJECT_INTEGRITY_FAILED")
        return tuple(errors)
