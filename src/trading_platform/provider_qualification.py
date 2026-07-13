from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from trading_platform import ProductionCompositionRoot
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.credentials import CredentialAdapter
from trading_platform.operations import OperationError
from trading_platform.provider_config import load_sync_job


def register_job_security(root: ProductionCompositionRoot, job: dict[str, Any]) -> None:
    identity = job.get("security_identity")
    if not isinstance(identity, dict):
        return
    root.facade.add_watchlist_item(
        str(identity.get("invocation_id") or f"provider-security:{identity['security_id']}"),
        SecurityIdentity(
            identity["security_id"], identity["venue"], identity["code"],
            identity["currency"], identity["listed_from"],
        ),
    )


class ProviderQualificationService:
    def __init__(self, data_root: Path, credential_adapter: CredentialAdapter | None = None) -> None:
        self.data_root = data_root
        self.credential_adapter = credential_adapter

    def run(self, job_file: Path) -> dict[str, Any]:
        job, provider, request = load_sync_job(job_file, self.credential_adapter)
        if request.offline or not request.network_authorized:
            raise OperationError("LIVE_QUALIFICATION_NETWORK_REQUIRED", "Live qualification requires explicit network authorization.")
        root = ProductionCompositionRoot(self.data_root, providers=(provider,))
        try:
            register_job_security(root, job)
            result = root.facade.sync_data(request)
            evidence = root.facade.get_provider_attempt_evidence(result.attempt_ids)
        finally:
            root.close()
        attempts = []
        blockers = []
        for item in evidence:
            row = asdict(item)
            blockers.extend(f"{item.attempt_id}:{code}" for code in item.blocking_codes)
            row.pop("blocking_codes")
            attempts.append(row)
        completed = {item["dataset"] for item in attempts if item["status"] == "complete" and item["raw_sha256"]}
        required = set(request.datasets)
        blockers.extend(f"dataset_not_qualified:{dataset}" for dataset in sorted(required - completed))
        provider_config = job["provider"]
        credential_scope = str(provider_config["credential_env"])
        return {
            "status": "qualified" if not blockers else "failed",
            "provider_identity": provider_config["source_identity"],
            "source_authority": "structured_aggregator_not_official_disclosure",
            "terms_profile": provider_config["terms_profile"],
            "provider_type": provider_config.get("provider_type", "http_json"),
            "credential_scope_id": hashlib.sha256(credential_scope.encode()).hexdigest(),
            "attempts": attempts,
            "blockers": blockers,
        }

    @staticmethod
    def write_artifact(result: dict[str, Any], output: Path) -> Path:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
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


__all__ = ["ProviderQualificationService", "register_job_security"]
