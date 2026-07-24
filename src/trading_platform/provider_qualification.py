from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from trading_platform.application.cli_tasks import DataSynchronization
from trading_platform.application.workflow_ledger import (
    QualificationReceiptCommit,
    QualificationReceiptQuery,
    WorkflowLedgerPort,
    QualificationReceiptReplayQuery,
)
from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import CompletenessRequirement, ProviderAttemptEvidence
from trading_platform.identity import canonical_hash
from trading_platform.operations import OperationError
from trading_platform.provider_config import LoadedProviderJob


@dataclass(frozen=True)
class ProviderQualificationResult:
    status: str
    receipt_artifact_id: str
    invocation_id: str
    qualification_id: str
    provider_identity: str
    source_authority: str
    terms_profile: str
    provider_id: str
    adapter_version: str
    adapter_code_identity: str
    transport_identity: str
    qualification_profile: str
    source_policy: dict[str, Any]
    credential_scope_id: str
    query_policy_identity: str
    source_policy_identity: str
    request_fingerprint: str
    data_snapshot_id: str | None
    requested_date: str
    effective_session_date: str | None
    as_of_at: str
    qualified_at: str
    attempts: tuple[ProviderAttemptEvidence, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["attempts"] = list(value["attempts"])
        value["blockers"] = list(value["blockers"])
        return value



class LedgerQualifiedEquivalentAuthority:
    """Authorizes an equivalent provider only from a persisted qualification receipt."""

    def __init__(self, ledger: WorkflowLedgerPort) -> None:
        self._ledger = ledger

    def authorize(
        self,
        receipt_artifact_id: str,
        provider_id: str,
        adapter_version: str,
        source_policy_identity: str,
        dataset: str,
        adapter_code_identity: str,
        transport_identity: str,
    ) -> None:
        try:
            receipt = json.loads(
                self._ledger.load(QualificationReceiptQuery(receipt_artifact_id))
            )
            attempts = receipt["attempts"]
            routes = receipt["source_policy"]["routes"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise OperationError(
                "QUALIFIED_EQUIVALENT_RECEIPT_INVALID",
                "Qualified-equivalent receipt evidence is invalid.",
            ) from error
        route = next(
            (item for item in routes if isinstance(item, dict) and item.get("dataset") == dataset),
            None,
        )
        dataset_attempts = [
            item for item in attempts
            if isinstance(item, dict) and item.get("dataset") == dataset
        ]
        try:
            qualified_at = datetime.fromisoformat(str(receipt["qualified_at"]))
            receipt_age = datetime.now(timezone.utc) - qualified_at.astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError) as error:
            raise OperationError("QUALIFIED_EQUIVALENT_RECEIPT_INVALID", "Qualification time is invalid.") from error

        if (
            receipt.get("status") != "qualified"
            or receipt.get("adapter_code_identity") != adapter_code_identity
            or receipt.get("transport_identity") != transport_identity
            or receipt.get("qualification_profile") != "production"
            or not -timedelta(minutes=5) <= receipt_age <= timedelta(hours=24)
            or receipt.get("provider_id") != provider_id
            or receipt.get("adapter_version") != adapter_version
            or receipt.get("source_policy_identity") != source_policy_identity
            or receipt.get("data_snapshot_id") is None
            or route is None
            or not any(
                item.get("status") == "complete"
                and item.get("raw_sha256")
                and not item.get("blocking_codes")
                for item in dataset_attempts
            )
        ):
            raise OperationError(
                "QUALIFIED_EQUIVALENT_NOT_AUTHORIZED",
                "The persisted receipt does not authorize this equivalent source route.",
            )

class ProviderQualificationService:
    """Run and persist one authoritative qualification receipt through the canonical sync path."""

    def __init__(
        self,
        loaded: LoadedProviderJob,
        synchronization: DataSynchronization,
        data: DataSyncService,
        ledger: WorkflowLedgerPort,
    ) -> None:
        self._loaded = loaded
        self._synchronization = synchronization
        self._data = data
        self._ledger = ledger

    def _request_fingerprint(self) -> str:
        request = self._loaded.request
        return canonical_hash({
            "invocation_id": request.invocation_id,
            "security_id": request.security_id,
            "security_code": request.security_code,
            "requested_date": request.requested_date,
            "as_of_at": request.as_of_at,
            "market_timezone": request.market_timezone,
            "market": request.market,
            "snapshot_purpose": request.snapshot_purpose.value,
            "datasets": list(request.datasets),
            "network_authorized": request.network_authorized,
            "offline": request.offline,
            "query_policy_identity": self._loaded.query_policy.identity,
            "source_policy_identity": self._loaded.source_policy.identity,
            "transport_identity": self._loaded.transport_identity,
            "adapter_code_identity": self._loaded.provider.code_identity,
            "credential_scope_id": self._loaded.credential_scope_id,
        })

    def run(self) -> ProviderQualificationResult:
        request = self._loaded.request
        if request.offline or not request.network_authorized:
            raise OperationError("LIVE_QUALIFICATION_NETWORK_REQUIRED", "Live qualification requires explicit network authorization.")
        request_fingerprint = self._request_fingerprint()
        replay = self._ledger.load(
            QualificationReceiptReplayQuery(request.invocation_id, request_fingerprint)
        )
        if replay is not None:
            return decode_provider_qualification_receipt(replay.payload, replay.artifact_id)

        result = self._synchronization.run()
        evidence = self._data.provider_attempt_evidence(result.attempt_ids)
        blockers = [
            f"{item.attempt_id}:{code}"
            for item in evidence
            for code in item.blocking_codes
        ]
        completed = {
            item.dataset
            for item in evidence
            if item.status == "complete" and item.raw_sha256
        }
        blockers.extend(
            f"dataset_not_qualified:{dataset}"
            for dataset in sorted({route.dataset for route in self._loaded.source_policy.routes if route.completeness is CompletenessRequirement.REQUIRED} - completed)
        )
        if result.status.value not in {"complete", "complete_with_substitution"}:
            blockers.append(f"sync_status:{result.status.value}")
        if result.quality.value != "pass":
            blockers.append(f"snapshot_quality:{result.quality.value}")
        if result.coverage.missing:
            blockers.append(f"coverage_missing:{result.coverage.missing}")
        qualified_at = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "schema_version": "ProviderQualificationReceipt@1",
            "status": "qualified" if not blockers else "failed",
            "invocation_id": request.invocation_id,
            "qualification_id": "qualification_" + canonical_hash({
                "request_fingerprint": request_fingerprint,
                "attempt_ids": [item.attempt_id for item in evidence],
                "snapshot_id": result.snapshot_id,
            })[:24],
            "provider_identity": self._loaded.source_policy.source_identity,
            "source_authority": self._loaded.source_policy.source_authority.value,
            "terms_profile": self._loaded.source_policy.terms_profile,
            "provider_id": self._loaded.source_policy.provider_id,
            "adapter_version": self._loaded.source_policy.adapter_version,
            "adapter_code_identity": self._loaded.provider.code_identity,
            "sync_status": result.status.value,
            "transport_identity": self._loaded.transport_identity,
            "qualification_profile": self._loaded.qualification_profile,
            "substitution_receipt_ids": list(result.disposition.substitution_receipt_ids),
            "snapshot_quality": result.quality.value,
            "coverage": asdict(result.coverage),
            "credential_scope_id": self._loaded.credential_scope_id,
            "query_policy_identity": self._loaded.query_policy.identity,
            "query_policy": self._loaded.query_policy.canonical_content,
            "source_policy": self._loaded.source_policy.canonical_content,
            "source_policy_identity": self._loaded.source_policy.identity,
            "request_fingerprint": request_fingerprint,
            "data_snapshot_id": result.snapshot_id,
            "requested_date": result.requested_date,
            "effective_session_date": result.effective_session_date,
            "as_of_at": request.as_of_at.isoformat(),
            "qualified_at": qualified_at,
            "attempts": [asdict(item) for item in evidence],
            "blockers": blockers,
        }
        receipt_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        artifact_id = self._ledger.commit_artifacts(
            QualificationReceiptCommit(request.invocation_id, request_fingerprint, receipt_payload)
        )
        authoritative = decode_provider_qualification_receipt(
            self._ledger.load(QualificationReceiptQuery(artifact_id)),
            artifact_id,
        )
        return authoritative


def decode_provider_qualification_receipt(payload: bytes, artifact_id: str) -> ProviderQualificationResult:
    try:
        value = json.loads(payload)
        if not isinstance(value, dict) or value.get("schema_version") != "ProviderQualificationReceipt@1":
            raise TypeError("qualification receipt schema is invalid")
        attempts_value = value["attempts"]
        blockers_value = value["blockers"]
        if not isinstance(attempts_value, list) or not isinstance(blockers_value, list):
            raise TypeError("qualification receipt evidence is invalid")
        attempts = tuple(ProviderAttemptEvidence(
            attempt_id=item["attempt_id"],
            dataset=item["dataset"],
            status=item["status"],
            raw_sha256=item["raw_sha256"],
            retrieved_at=item["retrieved_at"],
            error_code=item["error_code"],
            blocking_codes=tuple(item["blocking_codes"]),
        ) for item in attempts_value)
        text_fields = (
            "status", "invocation_id", "qualification_id", "provider_identity", "source_authority",
            "terms_profile", "provider_id", "adapter_version", "adapter_code_identity",
            "credential_scope_id", "query_policy_identity", "source_policy_identity",
            "request_fingerprint", "requested_date", "as_of_at", "qualified_at",
            "transport_identity", "qualification_profile",
        )
        if any(not isinstance(value.get(field), str) or not value[field] for field in text_fields):
            raise TypeError("qualification receipt identity is incomplete")
        if value["status"] not in {"qualified", "failed", "external_blocked"}:
            raise TypeError("qualification receipt status is invalid")
        if not all(isinstance(item, str) and item for item in blockers_value):
            raise TypeError("qualification receipt blockers are invalid")
        if not isinstance(value.get("source_policy"), dict):
            raise TypeError("qualification source policy is invalid")
        return ProviderQualificationResult(
            status=value["status"],
            receipt_artifact_id=artifact_id,
            invocation_id=value["invocation_id"],
            qualification_id=value["qualification_id"],
            provider_identity=value["provider_identity"],
            source_authority=value["source_authority"],
            terms_profile=value["terms_profile"],
            provider_id=value["provider_id"],
            adapter_version=value["adapter_version"],
            adapter_code_identity=value["adapter_code_identity"],
            credential_scope_id=value["credential_scope_id"],
            query_policy_identity=value["query_policy_identity"],
            source_policy_identity=value["source_policy_identity"],
            request_fingerprint=value["request_fingerprint"],
            data_snapshot_id=value.get("data_snapshot_id"),
            requested_date=value["requested_date"],
            effective_session_date=value.get("effective_session_date"),
            as_of_at=value["as_of_at"],
            transport_identity=value["transport_identity"],
            qualification_profile=value["qualification_profile"],
            source_policy=dict(value["source_policy"]),
            qualified_at=value["qualified_at"],
            attempts=attempts,
            blockers=tuple(blockers_value),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise OperationError("QUALIFICATION_RECEIPT_INVALID", type(error).__name__) from None


__all__ = ["LedgerQualifiedEquivalentAuthority", "ProviderQualificationResult", "ProviderQualificationService", "decode_provider_qualification_receipt"]
