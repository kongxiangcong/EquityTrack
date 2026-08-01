from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from trading_platform.credentials import CredentialAdapter, LocalCredentialAdapter
from trading_platform.data.providers import TushareCompatibleProvider
from trading_platform.data.official_disclosures import (
    CninfoOfficialDisclosureProvider,
    SzseOfficialDisclosureProvider,
)
from trading_platform.domain.data import (
    CompletenessRequirement,
    DataProvider,
    FallbackMode,
    QueryPolicy,
    SnapshotPurpose,
    SourceAuthority,
    SourceFailureDisposition,
    SourcePolicy,
    SourceRights,
    SourceRoute,
    SyncRequest,
)
from trading_platform.identity import canonical_hash
from trading_platform.application.command_codecs import (
    decode_market_snapshot_command_value,
    decode_provider_security_identity_value,
)
from trading_platform.application.provider_job import ProviderJob
from trading_platform.application.research_request_codec import decode_research_workflow_request
from trading_platform.operations import OperationError

@dataclass(frozen=True)
class DecodedProviderJob:
    job: ProviderJob
    request: SyncRequest
    query_policy: QueryPolicy
    source_policy: SourcePolicy
    provider_id: str
    adapter_version: str
    credential_variable: str


@dataclass(frozen=True)
class LoadedProviderJob:
    job: ProviderJob
    provider: DataProvider
    request: SyncRequest
    transport_identity: str
    query_policy: QueryPolicy
    qualification_profile: str
    source_policy: SourcePolicy
    credential_scope_id: str
    credential_variable: str

@dataclass(frozen=True)
class ProviderRuntimeBinding:
    provider: DataProvider
    credential_scope_id: str
    credential_variable: str
    transport_identity: str

    qualification_profile: str

class ProviderRuntimeAdapter(Protocol):
    def bind(self, decoded: DecodedProviderJob) -> ProviderRuntimeBinding: ...


_TUSHARE_PROVIDER_ID = "tushare-compatible"
_TUSHARE_ADAPTER_VERSION = "tushare-http@2"
_TUSHARE_SOURCE_IDENTITY = "preconfigured_tushare_compatible_non_official"
_TUSHARE_TERMS_PROFILE = "gateway-terms-pending@1"
_TUSHARE_CREDENTIAL_SCOPE = "TUSHARE_TOKEN"
def canonical_preconfigured_source_policy() -> SourcePolicy:
    return SourcePolicy(
        "SourcePolicy@1",
        _TUSHARE_PROVIDER_ID,
        _TUSHARE_ADAPTER_VERSION,
        _TUSHARE_SOURCE_IDENTITY,
        SourceAuthority.STRUCTURED_AGGREGATOR,
        _TUSHARE_TERMS_PROFILE,
        SourceRights(True, True, True, True, False, "2026-07-24"),
        tuple(
            SourceRoute(
                dataset,
                1,
                (
                    CompletenessRequirement.OPTIONAL
                    if dataset == "cashflow"
                    else CompletenessRequirement.REQUIRED
                ),
                1,
                FallbackMode.NO_FALLBACK,
                (
                    SourceFailureDisposition.QUARANTINE
                    if dataset == "cashflow"
                    else SourceFailureDisposition.BLOCK
                ),
            )
            for dataset in (
                "trade_cal",
                "market_universe",
                "daily",
                "income",
                "balancesheet",
                "cashflow",
            )
        ),
    )


_TUSHARE_ENDPOINT = "http://8.136.22.187:8010/"


def validate_preconfigured_source_policy(decoded: DecodedProviderJob) -> None:
    policy = decoded.source_policy
    if (
        decoded.provider_id != _TUSHARE_PROVIDER_ID
        or decoded.adapter_version != _TUSHARE_ADAPTER_VERSION
        or decoded.credential_variable != _TUSHARE_CREDENTIAL_SCOPE
        or policy.source_identity != _TUSHARE_SOURCE_IDENTITY
        or policy.source_authority is not SourceAuthority.STRUCTURED_AGGREGATOR
        or policy.terms_profile != _TUSHARE_TERMS_PROFILE
        or policy != canonical_preconfigured_source_policy()
    ):
        raise OperationError(
            "PROVIDER_SOURCE_POLICY_UNTRUSTED",
            "ProviderJob@2 does not match the statically composed source policy.",
        )


def production_transport_identity() -> str:
    return canonical_hash({"provider_id": _TUSHARE_PROVIDER_ID, "adapter_version": _TUSHARE_ADAPTER_VERSION, "destination": _TUSHARE_ENDPOINT})


class PreconfiguredTushareRuntime:
    """Own the approved destination, credential scope, and production adapter composition."""

    def __init__(self, credential_adapter: CredentialAdapter | None = None) -> None:
        self._credentials = credential_adapter or LocalCredentialAdapter()

    def bind(self, decoded: DecodedProviderJob) -> ProviderRuntimeBinding:
        validate_preconfigured_source_policy(decoded)
        credential = self._credentials.get(decoded.credential_variable)
        if not credential:
            raise OperationError("CREDENTIAL_MISSING", "Configured credential scope is missing.")
        provider = TushareCompatibleProvider(
            decoded.provider_id,
            decoded.adapter_version,
            _TUSHARE_ENDPOINT,
            credential,
            decoded.source_policy.source_identity,
            decoded.source_policy.terms_profile,
            source_authority=decoded.source_policy.source_authority,
        )
        return ProviderRuntimeBinding(
            provider,
            hashlib.sha256(decoded.credential_variable.encode()).hexdigest(),
            decoded.credential_variable,
            production_transport_identity(),
            "production",
        )


def canonical_official_source_policy(provider_id: str) -> SourcePolicy:
    if provider_id == "szse-official-disclosure":
        adapter_version = "szse-announcement@1"
        source_identity = "szse-statutory-disclosure"
        terms_profile = "szse-local-noncommercial@2026-07-24"
    elif provider_id == "cninfo-official-disclosure":
        adapter_version = "cninfo-announcement@1"
        source_identity = "cninfo-statutory-disclosure"
        terms_profile = "cninfo-local-noncommercial@2026-07-24"
    else:
        raise OperationError(
            "PROVIDER_SOURCE_POLICY_UNTRUSTED",
            "Official provider identity is not statically composed.",
        )
    return SourcePolicy(
        "SourcePolicy@1",
        provider_id,
        adapter_version,
        source_identity,
        SourceAuthority.OFFICIAL,
        terms_profile,
        SourceRights(True, True, True, True, False, "2026-07-24"),
        (
            SourceRoute(
                "official_filing",
                30,
                CompletenessRequirement.REQUIRED,
                1,
                FallbackMode.NO_FALLBACK,
                SourceFailureDisposition.BLOCK,
            ),
        ),
    )


class PreconfiguredProviderRuntime:
    """Statically compose the one approved adapter for each provider identity."""

    def __init__(
        self, credential_adapter: CredentialAdapter | None = None
    ) -> None:
        self._tushare = PreconfiguredTushareRuntime(credential_adapter)

    def bind(self, decoded: DecodedProviderJob) -> ProviderRuntimeBinding:
        if decoded.provider_id == _TUSHARE_PROVIDER_ID:
            return self._tushare.bind(decoded)
        policy = canonical_official_source_policy(decoded.provider_id)
        if (
            decoded.credential_variable != "not_applicable"
            or decoded.source_policy != policy
            or decoded.adapter_version != policy.adapter_version
        ):
            raise OperationError(
                "PROVIDER_SOURCE_POLICY_UNTRUSTED",
                "ProviderJob@2 does not match the statically composed official source policy.",
            )
        provider: DataProvider
        if decoded.provider_id == "szse-official-disclosure":
            provider = SzseOfficialDisclosureProvider()
        elif decoded.provider_id == "cninfo-official-disclosure":
            provider = CninfoOfficialDisclosureProvider()
        else:
            raise OperationError(
                "PROVIDER_SOURCE_POLICY_UNTRUSTED",
                "Official provider identity is not statically composed.",
            )
        return ProviderRuntimeBinding(
            provider,
            hashlib.sha256(b"not_applicable").hexdigest(),
            "not_applicable",
            provider.transport_identity,
            "production",
        )



class ProviderJobCodecError(ValueError):
    def __init__(self, cause_type: str) -> None:
        super().__init__("PROVIDER_JOB_INVALID")
        self.code = "PROVIDER_JOB_INVALID"
        self.substep = "provider_job.decode"
        self.cause_type = cause_type


def decode_sync_job(job_file: Path) -> DecodedProviderJob:
    try:
        raw = json.loads(job_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("job must be an object")
        allowed_top = {
            "schema_version", "provider", "query_policy", "source_policy", "request",
            "security_identity", "research_request", "market",
        }
        if set(raw) - allowed_top or raw.get("schema_version") != "ProviderJob@2":
            raise TypeError("ProviderJob@2 is required")

        def strict_object(container: dict, name: str, fields: set[str]) -> dict:
            value = container[name]
            if not isinstance(value, dict) or set(value) != fields:
                raise TypeError(f"{name} fields are invalid")
            return value

        def required_text(container: dict, name: str) -> str:
            value = container[name]
            if not isinstance(value, str) or not value:
                raise TypeError(f"{name} must be a non-empty string")
            return value

        provider_data = strict_object(raw, "provider", {"provider_id", "adapter_version", "credential_env"})
        query_data = strict_object(raw, "query_policy", {"schema_version", "lookback_days", "market_universe_list_status", "adjustment_mode"})
        source_data = strict_object(raw, "source_policy", {"schema_version", "provider_id", "adapter_version", "source_identity", "source_authority", "terms_profile", "rights", "routes"})
        request_data = strict_object(raw, "request", {"invocation_id", "security_id", "security_code", "requested_date", "as_of_at", "market_timezone", "market", "snapshot_purpose", "datasets", "network_authorized", "offline"})
        rights_data = strict_object(
            source_data,
            "rights",
            {
                "automation_allowed",
                "local_storage_allowed",
                "deterministic_replay_allowed",
                "derived_use_allowed",
                "redistribution_allowed",
                "reviewed_on",
                "evidence_sha256",
            },
        )
        if any(
            type(rights_data[name]) is not bool
            for name in (
                "automation_allowed",
                "local_storage_allowed",
                "deterministic_replay_allowed",
                "derived_use_allowed",
                "redistribution_allowed",
            )
        ):
            raise TypeError("source rights must be booleans")
        required_text(rights_data, "reviewed_on")
        if (
            rights_data["evidence_sha256"] is not None
            and (
                not isinstance(rights_data["evidence_sha256"], str)
                or len(rights_data["evidence_sha256"]) != 64
            )
        ):
            raise TypeError("source rights evidence must be a sha256 or null")

        routes_data = source_data["routes"]
        if not isinstance(routes_data, list) or not routes_data:
            raise TypeError("source routes must be a non-empty array")
        routes = []
        route_required = {"dataset", "freshness_max_stale_days", "completeness", "retry_max_attempts", "fallback", "failure_disposition"}
        for value in routes_data:
            if not isinstance(value, dict) or set(value) - (route_required | {"qualified_equivalent_receipt_ids", "fallback_on_error_codes"}) or not route_required.issubset(value):
                raise TypeError("source route fields are invalid")
            qualified_ids = value.get("qualified_equivalent_receipt_ids", [])
            if not isinstance(qualified_ids, list) or not all(isinstance(item, str) and item for item in qualified_ids):
                raise TypeError("qualified receipt ids are invalid")
            fallback_codes = value.get("fallback_on_error_codes", [])
            if not isinstance(fallback_codes, list) or not all(isinstance(item, str) and item for item in fallback_codes):
                raise TypeError("fallback error codes are invalid")
            if type(value["freshness_max_stale_days"]) is not int or type(value["retry_max_attempts"]) is not int:
                raise TypeError("source route integers are invalid")
            routes.append(SourceRoute(
                required_text(value, "dataset"),
                value["freshness_max_stale_days"],
                CompletenessRequirement(required_text(value, "completeness")),
                value["retry_max_attempts"],
                FallbackMode(required_text(value, "fallback")),
                SourceFailureDisposition(required_text(value, "failure_disposition")),
                tuple(qualified_ids),
                tuple(fallback_codes),
            ))

        query_policy = QueryPolicy(
            required_text(query_data, "schema_version"),
            query_data["lookback_days"],
            required_text(query_data, "market_universe_list_status"),
            required_text(query_data, "adjustment_mode"),
        )
        if type(query_policy.lookback_days) is not int:
            raise TypeError("lookback_days must be an integer")
        source_policy = SourcePolicy(
            required_text(source_data, "schema_version"),
            required_text(source_data, "provider_id"),
            required_text(source_data, "adapter_version"),
            required_text(source_data, "source_identity"),
            SourceAuthority(required_text(source_data, "source_authority")),
            required_text(source_data, "terms_profile"),
            SourceRights(**rights_data),
            tuple(routes),
        )
        provider_id = required_text(provider_data, "provider_id")
        adapter_version = required_text(provider_data, "adapter_version")
        if (provider_id, adapter_version) != (source_policy.provider_id, source_policy.adapter_version):
            raise TypeError("source policy provider identity mismatch")

        datasets = request_data["datasets"]
        if not isinstance(datasets, list) or not all(isinstance(item, str) and item for item in datasets):
            raise TypeError("datasets must be an array of non-empty strings")
        if any(dataset not in {route.dataset for route in routes} for dataset in datasets):
            raise TypeError("dataset is not declared by SourcePolicy@1")
        network_authorized = request_data["network_authorized"]
        offline = request_data["offline"]
        if type(network_authorized) is not bool or type(offline) is not bool:
            raise TypeError("network flags must be booleans")
        request = SyncRequest(
            required_text(request_data, "invocation_id"),
            required_text(request_data, "security_id"),
            required_text(request_data, "security_code"),
            required_text(request_data, "requested_date"),
            datetime.fromisoformat(required_text(request_data, "as_of_at")),
            required_text(request_data, "market_timezone"),
            required_text(request_data, "market"),
            SnapshotPurpose(required_text(request_data, "snapshot_purpose")),
            tuple(datasets),
            network_authorized,
            offline,
        )

        identity_value = raw.get("security_identity")
        security_identity = None
        security_invocation_id = None
        if identity_value is not None:
            if not isinstance(identity_value, dict):
                raise TypeError("security identity must be an object")
            identity_payload = dict(identity_value)
            security_invocation_id = identity_payload.pop("invocation_id", None)
            if security_invocation_id is not None and not isinstance(security_invocation_id, str):
                raise TypeError("security invocation id must be a string")
            security_identity = decode_provider_security_identity_value(identity_payload)
        research_request = None if raw.get("research_request") is None else decode_research_workflow_request(json.dumps(raw["research_request"]).encode("utf-8"))
        market_command = None if raw.get("market") is None else decode_market_snapshot_command_value(dict(raw["market"]))
        job = ProviderJob(
            "ProviderJob@2",
            security_identity,
            security_invocation_id,
            research_request,
            market_command,
        )
        credential_variable = required_text(provider_data, "credential_env")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ProviderJobCodecError(type(error).__name__) from None

    return DecodedProviderJob(
        job,
        request,
        query_policy,
        source_policy,
        provider_id,
        adapter_version,
        credential_variable,
    )


def load_sync_job(job_file: Path, credential_adapter: CredentialAdapter | None = None, provider_runtime: ProviderRuntimeAdapter | None = None) -> LoadedProviderJob:
    decoded = decode_sync_job(job_file)
    binding = (
        provider_runtime or PreconfiguredProviderRuntime(credential_adapter)
    ).bind(decoded)
    return LoadedProviderJob(
        decoded.job,
        binding.provider,
        decoded.request,
        binding.transport_identity,
        decoded.query_policy,
        binding.qualification_profile,
        decoded.source_policy,
        binding.credential_scope_id,
        binding.credential_variable,
    )


__all__ = ["DecodedProviderJob", "LoadedProviderJob", "PreconfiguredProviderRuntime", "ProviderJobCodecError", "ProviderRuntimeAdapter", "ProviderRuntimeBinding", "canonical_official_source_policy", "canonical_preconfigured_source_policy", "decode_sync_job", "load_sync_job", "production_transport_identity", "validate_preconfigured_source_policy"]
