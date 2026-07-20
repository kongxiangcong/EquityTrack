from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from trading_platform.credentials import CredentialAdapter, EnvironmentCredentialAdapter
from trading_platform.data.providers import HttpJsonProvider, TushareCompatibleProvider
from trading_platform.domain.data import SnapshotPurpose, SyncRequest
from trading_platform.operations import OperationError


class ProviderJobCodecError(ValueError):
    def __init__(self, cause_type: str) -> None:
        super().__init__("PROVIDER_JOB_INVALID")
        self.code = "PROVIDER_JOB_INVALID"
        self.substep = "provider_job.decode"
        self.cause_type = cause_type


def load_sync_job(job_file: Path, credential_adapter: CredentialAdapter | None = None):
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
        if not isinstance(job, dict):
            raise TypeError("job must be an object")
        provider = job["provider"]
        request_data = job["request"]
        if not isinstance(provider, dict) or not isinstance(request_data, dict):
            raise TypeError("provider and request must be objects")

        def required_text(container: dict, name: str) -> str:
            value = container[name]
            if not isinstance(value, str) or not value:
                raise TypeError(f"{name} must be a non-empty string")
            return value

        endpoint = required_text(provider, "endpoint")
        provider_type = provider.get("provider_type", "http_json")
        if not isinstance(provider_type, str):
            raise TypeError("provider_type must be a string")
        datasets = request_data["datasets"]
        if not isinstance(datasets, list) or not all(
            isinstance(item, str) and item for item in datasets
        ):
            raise TypeError("datasets must be an array of non-empty strings")
        network_authorized = request_data["network_authorized"]
        offline = request_data["offline"]
        if type(network_authorized) is not bool or type(offline) is not bool:
            raise TypeError("network flags must be booleans")
        as_of_at = datetime.fromisoformat(required_text(request_data, "as_of_at"))
        snapshot_purpose = SnapshotPurpose(
            required_text(request_data, "snapshot_purpose")
        )
        credential_variable = required_text(provider, "credential_env")
        provider_id = required_text(provider, "provider_id")
        adapter_version = required_text(provider, "adapter_version")
        source_identity = required_text(provider, "source_identity")
        terms_profile = required_text(provider, "terms_profile")
        invocation_id = required_text(request_data, "invocation_id")
        security_id = required_text(request_data, "security_id")
        provider_security_code = required_text(request_data, "provider_security_code")
        requested_date = required_text(request_data, "requested_date")
        market_timezone = required_text(request_data, "market_timezone")
        market = required_text(request_data, "market")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ProviderJobCodecError(type(error).__name__) from None
    if not endpoint.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise OperationError("PROVIDER_DESTINATION_INVALID", "Provider endpoint must be HTTPS or loopback.")
    credential = (credential_adapter or EnvironmentCredentialAdapter()).get(credential_variable)
    if not credential:
        raise OperationError("CREDENTIAL_MISSING", "Configured credential scope is missing.")
    provider_class = {
        "http_json": HttpJsonProvider,
        "tushare_compatible": TushareCompatibleProvider,
    }.get(provider_type)
    if provider_class is None:
        raise OperationError("PROVIDER_TYPE_UNSUPPORTED", "Configured provider type is unsupported.")
    adapter = provider_class(
        provider_id,
        adapter_version,
        endpoint,
        credential,
        source_identity,
        terms_profile,
    )
    request = SyncRequest(
        invocation_id,
        security_id,
        provider_security_code,
        requested_date,
        as_of_at,
        market_timezone,
        market,
        snapshot_purpose,
        tuple(datasets),
        network_authorized,
        offline,
    )
    return job, adapter, request


__all__ = ["ProviderJobCodecError", "load_sync_job"]
