from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from trading_platform.application.research_publication import (
    ResearchPublicationError,
)
from trading_platform.domain.market_time import SHANGHAI_TIMEZONE

from .locking import DataRootWriterLock


_ALLOWED_FILENAMES = {
    "research-report.json",
    "research-report.html",
    "research-report.pdf",
    "research-workbook.xlsx",
    "research-workbook-limitation.json",
    "price-chart.html",
}


class FilesystemResearchPublicationRepository:
    """Owns immutable, user-readable publication paths and integrity."""

    def __init__(
        self, data_root: Path, writer_lock: DataRootWriterLock
    ) -> None:
        self._root = data_root.resolve() / "exports" / "research"
        self._writer_lock = writer_lock

    def publish(
        self,
        *,
        subject: str,
        as_of: str,
        published_at: str,
        artifacts: Mapping[str, bytes],
        limitations: tuple[str, ...],
    ) -> Mapping[str, Path]:
        try:
            date.fromisoformat(as_of)
            published = datetime.fromisoformat(published_at)
        except ValueError as error:
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_IDENTITY_INVALID"
            ) from error
        if (
            not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", subject)
            or published.tzinfo is None
            or published.utcoffset() is None
            or not artifacts
            or set(artifacts) - _ALLOWED_FILENAMES
            or "research-report.html" not in artifacts
            or "research-report.pdf" not in artifacts
            or "price-chart.html" not in artifacts
        ):
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_IDENTITY_INVALID"
            )
        stamp = published.astimezone(SHANGHAI_TIMEZONE).strftime(
            "%Y%m%dT%H%M%S"
        )
        parent = self._root / subject / as_of
        target = parent / stamp
        manifest = {
            "schema_version": "ResearchPublicationManifest@1",
            "subject": subject,
            "as_of": as_of,
            "published_at": published_at,
            "limitations": list(limitations),
            "files": [
                {
                    "filename": name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
                for name, payload in sorted(artifacts.items())
            ],
        }
        encoded_manifest = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        with self._writer_lock.acquire(
            f"research-publication:{subject}:{as_of}:{stamp}"
        ):
            if target.exists():
                self._verify_existing(
                    target, encoded_manifest, artifacts
                )
                return self._paths(target, artifacts)
            parent.mkdir(parents=True, exist_ok=True)
            temporary = parent / f".{stamp}-{uuid.uuid4().hex}.tmp"
            temporary.mkdir()
            try:
                for name, payload in artifacts.items():
                    (temporary / name).write_bytes(payload)
                (temporary / "publication-manifest.json").write_bytes(
                    encoded_manifest
                )
                temporary.rename(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        self._verify_existing(target, encoded_manifest, artifacts)
        return self._paths(target, artifacts)

    @staticmethod
    def _verify_existing(
        target: Path,
        expected_manifest: bytes,
        artifacts: Mapping[str, bytes],
    ) -> None:
        manifest = target / "publication-manifest.json"
        if (
            not target.is_dir()
            or not manifest.is_file()
            or manifest.read_bytes() != expected_manifest
            or any(
                not (target / name).is_file()
                or (target / name).read_bytes() != payload
                for name, payload in artifacts.items()
            )
        ):
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_CONFLICT"
            )

    @staticmethod
    def _paths(
        target: Path, artifacts: Mapping[str, bytes]
    ) -> Mapping[str, Path]:
        roles = {
            "report_html": "research-report.html",
            "report_pdf": "research-report.pdf",
            "report_json": "research-report.json",
            "chart_html": "price-chart.html",
            "workbook": next(
                name for name in artifacts if name.startswith("research-workbook")
            ),
        }
        return {
            role: (target / filename).resolve()
            for role, filename in roles.items()
        }


__all__ = ["FilesystemResearchPublicationRepository"]