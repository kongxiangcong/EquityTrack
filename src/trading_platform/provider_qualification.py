from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from trading_platform.application.cli_tasks import DataSynchronization
from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import SyncRequest
from trading_platform.operations import OperationError


@dataclass(frozen=True)
class ProviderQualificationResult:
    status: str
    provider_identity: str
    source_authority: str
    terms_profile: str
    provider_type: str
    credential_scope_id: str
    attempts: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderQualificationService:
    """Own live qualification around the canonical configured synchronization."""

    def __init__(
        self,
        provider_config: dict[str, Any],
        request: SyncRequest,
        synchronization: DataSynchronization,
        data: DataSyncService,
    ) -> None:
        self._provider_config = provider_config
        self._request = request
        self._synchronization = synchronization
        self._data = data

    def run(self) -> ProviderQualificationResult:
        request = self._request
        if request.offline or not request.network_authorized:
            raise OperationError("LIVE_QUALIFICATION_NETWORK_REQUIRED", "Live qualification requires explicit network authorization.")
        result = self._synchronization.run()
        evidence = self._data.provider_attempt_evidence(result.attempt_ids)
        attempts = []
        blockers: list[str] = []
        for item in evidence:
            row = asdict(item)
            blockers.extend(f"{item.attempt_id}:{code}" for code in item.blocking_codes)
            row.pop("blocking_codes")
            attempts.append(row)
        completed = {item["dataset"] for item in attempts if item["status"] == "complete" and item["raw_sha256"]}
        required = set(request.datasets)
        blockers.extend(f"dataset_not_qualified:{dataset}" for dataset in sorted(required - completed))
        provider_config = self._provider_config
        credential_scope = str(provider_config["credential_env"])
        return ProviderQualificationResult(
            status="qualified" if not blockers else "failed",
            provider_identity=provider_config["source_identity"],
            source_authority="structured_aggregator_not_official_disclosure",
            terms_profile=provider_config["terms_profile"],
            provider_type=provider_config.get("provider_type", "http_json"),
            credential_scope_id=hashlib.sha256(credential_scope.encode()).hexdigest(),
            attempts=tuple(attempts),
            blockers=tuple(blockers),
        )

    @staticmethod
    def write_artifact(result: ProviderQualificationResult, output: Path) -> Path:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".provider-qualification-", dir=output.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, output)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        output.chmod(stat.S_IREAD)
        return output


__all__ = ["ProviderQualificationResult", "ProviderQualificationService"]
