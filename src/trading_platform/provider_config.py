from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from trading_platform.credentials import CredentialAdapter, EnvironmentCredentialAdapter
from trading_platform.data.providers import HttpJsonProvider, TushareCompatibleProvider
from trading_platform.domain.data import SnapshotPurpose, SyncRequest
from trading_platform.operations import OperationError


def load_sync_job(job_file: Path, credential_adapter: CredentialAdapter | None = None):
    job = json.loads(job_file.read_text(encoding="utf-8"))
    provider = job["provider"]
    endpoint = str(provider["endpoint"])
    if not endpoint.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise OperationError("PROVIDER_DESTINATION_INVALID", "Provider endpoint must be HTTPS or loopback.")
    credential_variable = str(provider["credential_env"])
    credential = (credential_adapter or EnvironmentCredentialAdapter()).get(credential_variable)
    if not credential:
        raise OperationError("CREDENTIAL_MISSING", "Configured credential scope is missing.")
    provider_type = provider.get("provider_type", "http_json")
    provider_class = {
        "http_json": HttpJsonProvider,
        "tushare_compatible": TushareCompatibleProvider,
    }.get(provider_type)
    if provider_class is None:
        raise OperationError("PROVIDER_TYPE_UNSUPPORTED", "Configured provider type is unsupported.")
    adapter = provider_class(
        provider["provider_id"], provider["adapter_version"], endpoint, credential,
        provider["source_identity"], provider["terms_profile"],
    )
    request_data = job["request"]
    request = SyncRequest(
        request_data["invocation_id"], request_data["security_id"], request_data["provider_security_code"],
        request_data["requested_date"], datetime.fromisoformat(request_data["as_of_at"]),
        request_data["market_timezone"], request_data["market"], SnapshotPurpose(request_data["snapshot_purpose"]),
        tuple(request_data["datasets"]), bool(request_data["network_authorized"]), bool(request_data["offline"]),
    )
    return job, adapter, request


__all__ = ["load_sync_job"]
