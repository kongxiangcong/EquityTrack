from __future__ import annotations

import sqlite3
from typing import Mapping

from dataclasses import replace

from trading_platform.domain.data import CompletenessRequirement, CursorCheckpoint, DataProvider, FallbackMode, FetchStatus, FixtureRights, ProviderAttemptEvidence, QualifiedEquivalentAuthority, QualifiedEquivalentBinding, QualityStatus, QueryPolicy, SnapshotMemberView, SourceFailureDisposition, SourcePolicy, SyncDisposition, SyncRequest, SyncResult, SyncStatus

from .normalizer import normalize
from .repository import DataRepository
from trading_platform.persistence.locking import PersistenceError


class DataSyncService:
    def __init__(
        self, repository: DataRepository, provider: DataProvider,
        query_policy: QueryPolicy, source_policy: SourcePolicy,
        fixture_rights: Mapping[tuple[str, str], FixtureRights] | None = None,
        qualified_equivalents: tuple[QualifiedEquivalentBinding, ...] = (),
        qualified_equivalent_authority: QualifiedEquivalentAuthority | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.query_policy = query_policy
        self.source_policy = source_policy
        self.fixture_rights = dict(fixture_rights or {})
        if (provider.provider_id, provider.adapter_version) != (source_policy.provider_id, source_policy.adapter_version):
            raise ValueError("SOURCE_POLICY_PROVIDER_MISMATCH")
        declared_receipts = {
            receipt_id for route in source_policy.routes
            for receipt_id in route.qualified_equivalent_receipt_ids
        }
        supplied_receipts = {binding.qualification_receipt_id for binding in qualified_equivalents}
        if supplied_receipts - declared_receipts:
            raise ValueError("QUALIFIED_EQUIVALENT_UNDECLARED")
        for route in source_policy.routes:
            if route.fallback is FallbackMode.QUALIFIED_EQUIVALENT and not (
                set(route.qualified_equivalent_receipt_ids) & supplied_receipts
            ):
                raise ValueError("QUALIFIED_EQUIVALENT_NOT_COMPOSED")
        self.qualified_equivalents = {
            binding.qualification_receipt_id: binding for binding in qualified_equivalents
        }
        if qualified_equivalents and qualified_equivalent_authority is None:
            raise ValueError("QUALIFIED_EQUIVALENT_AUTHORITY_REQUIRED")
        for route in source_policy.routes:
            for receipt_id in route.qualified_equivalent_receipt_ids:
                binding = self.qualified_equivalents.get(receipt_id)
                if binding is None:
                    continue
                if (
                    binding.source_policy.source_authority is not source_policy.source_authority
                    or binding.source_policy.rights != source_policy.rights
                ):
                    raise ValueError("QUALIFIED_EQUIVALENT_POLICY_INCOMPATIBLE")
                equivalent_route = binding.source_policy.route_for(route.dataset)
                if equivalent_route.completeness is not route.completeness:
                    raise ValueError("QUALIFIED_EQUIVALENT_ROLE_MISMATCH")
                assert qualified_equivalent_authority is not None
                qualified_equivalent_authority.authorize(
                    receipt_id,
                    binding.provider.provider_id,
                    binding.provider.adapter_version,
                    binding.source_policy.identity,
                    route.dataset,
                    binding.provider.code_identity,
                    binding.provider.transport_identity,
                )

    def sync(self, request: SyncRequest) -> SyncResult:
        if request.offline:
            return self.repository.offline_result(request)
        if "official_filing" in request.datasets and request.datasets != (
            "official_filing",
        ):
            raise PersistenceError(
                "OFFICIAL_FILING_MIXED_DATASET_FORBIDDEN",
                "Official filings must use the dedicated atomic sync task.",
            )
        if request.datasets == ("official_filing",):
            return self._sync_official_filing(request)
        admitted: list[tuple[str, str]] = []
        attempt_ids: list[str] = []
        raw_created = raw_reused = normalized_created = normalized_reused = 0
        substitution_receipt_ids: set[str] = set()
        admission_complete = True
        for dataset in request.datasets:
            completed = False
            route = self.source_policy.route_for(dataset)
            candidates = [(self.provider, self.source_policy, None)]
            candidates.extend(
                (binding.provider, binding.source_policy, receipt_id)
                for receipt_id in route.qualified_equivalent_receipt_ids
                if (binding := self.qualified_equivalents.get(receipt_id)) is not None
            )
            if not all(policy.rights.local_storage_allowed for _, policy, _ in candidates):
                raise PersistenceError("SOURCE_RIGHTS_STORAGE_BLOCKED", "Source policy forbids local storage.")
            for candidate_index, (provider, active_policy, receipt_id) in enumerate(candidates):
              rights = (
                  self.fixture_rights.get((provider.provider_id, dataset))
                  if provider.fixture
                  else None
              )
              rights_profile_id = self.repository.register_policy_context(
                  self.query_policy,
                  active_policy,
                  rights,
              )
              candidate_error_codes: set[str] = set()
              hard_failure = False
              for _attempt in range(route.retry_max_attempts):
                cursor_value = self.repository.current_cursor(provider.provider_id, provider.adapter_version, dataset, request.security_id)
                fetch = self.query_policy.build(dataset, request, cursor_value)
                batch = provider.fetch(fetch)
                for envelope in batch.envelopes:
                    if (
                        envelope.source_identity != active_policy.source_identity
                        or envelope.source_authority is not active_policy.source_authority
                        or envelope.terms_profile != active_policy.terms_profile
                    ):
                        blocked = replace(envelope, status=FetchStatus.FAILED, payload=None, raw_sha256=None, cursor_value=None, error_code="SOURCE_POLICY_EVIDENCE_MISMATCH")
                        attempt_id, _, _ = self.repository.record_attempt(
                            request.invocation_id, provider.provider_id, provider.adapter_version,
                            dataset, blocked, "not_stored", cursor_value,
                            self.query_policy.identity, active_policy.identity,
                            rights_profile_id,
                            None, False,
                        )
                        attempt_ids.append(attempt_id)
                        hard_failure = True
                        break
                    if provider.fixture and (rights is None or rights.source_identity != envelope.source_identity or not rights.local_storage_allowed or not rights.deterministic_replay_allowed):
                        blocked = replace(envelope, status=FetchStatus.FAILED, payload=None, raw_sha256=None, cursor_value=None, error_code="FIXTURE_RIGHTS_BLOCKING")
                        attempt_id, _, _ = self.repository.record_attempt(request.invocation_id, provider.provider_id, provider.adapter_version, dataset, blocked, "not_stored", cursor_value, self.query_policy.identity, active_policy.identity, rights_profile_id, None, False)
                        attempt_ids.append(attempt_id)
                        hard_failure = True
                        break
                    if rights is not None:
                        try:
                            self.repository.validate_fixture_location(rights)
                        except PersistenceError as error:
                            blocked = replace(envelope, status=FetchStatus.FAILED, payload=None, raw_sha256=None, cursor_value=None, error_code=error.code)
                            attempt_id, _, _ = self.repository.record_attempt(request.invocation_id, provider.provider_id, provider.adapter_version, dataset, blocked, "not_stored", cursor_value, self.query_policy.identity, active_policy.identity, rights_profile_id, None, False)
                            attempt_ids.append(attempt_id)
                            hard_failure = True
                            break
                    raw_hash, was_raw_created = (
                        self.repository.publish_raw(envelope)
                    )
                    attempt_id, raw_hash, was_raw_created = self.repository.record_attempt(
                        request.invocation_id,
                        provider.provider_id,
                        provider.adapter_version,
                        dataset,
                        envelope,
                        (
                            "fetched"
                            if was_raw_created or raw_hash is None
                            else "reused"
                        ),
                        cursor_value,
                        self.query_policy.identity,
                        active_policy.identity,
                        rights_profile_id,
                        raw_hash,
                        was_raw_created,
                    )
                    if raw_hash is not None:
                        raw_created += int(was_raw_created)
                        raw_reused += int(not was_raw_created)
                    attempt_ids.append(attempt_id)
                    if provider.fixture:
                        assert rights is not None
                        self.repository.register_rights(rights, raw_hash)
                    if envelope.status is not FetchStatus.COMPLETE or envelope.payload is None:
                        candidate_error_codes.add(
                            envelope.error_code or f"FETCH_{envelope.status.value.upper()}"
                        )
                        continue
                    try:
                        items = normalize(dataset, envelope.payload, request.security_id, request.market, envelope.source_identity, envelope.retrieved_at)
                    except ValueError as error:
                        self.repository.record_blocking_issue(attempt_id, str(error))
                        hard_failure = True
                        break
                    blocking = any(item.quality in {QualityStatus.BLOCKING, QualityStatus.QUARANTINE} for item in items)
                    cursor = None if blocking or not envelope.cursor_value else CursorCheckpoint(provider.provider_id, provider.adapter_version, dataset, request.security_id, envelope.cursor_value)
                    try:
                        prepared_items = self.repository.prepare_items(items)
                        dataset_members, persistence_blocked, created_count, reused_count = self.repository.persist_items(attempt_id, prepared_items, request.as_of_at, cursor)
                    except (sqlite3.IntegrityError, PersistenceError, ValueError):
                        self.repository.record_blocking_issue(
                            attempt_id, "IDENTITY_OR_PERSISTENCE_CONFLICT"
                        )
                        hard_failure = True
                        break
                    admitted.extend(dataset_members)
                    normalized_created += created_count
                    normalized_reused += reused_count
                    completed = not blocking and not persistence_blocked
                    if completed:
                        break
                if hard_failure:
                    break
              if completed:
                if receipt_id is not None:
                    substitution_receipt_ids.add(receipt_id)
                break
              if hard_failure or (
                  not candidate_error_codes
                  or not candidate_error_codes <= set(route.fallback_on_error_codes)
              ):
                break
            if not completed and (
                route.completeness is CompletenessRequirement.REQUIRED
                or route.failure_disposition is SourceFailureDisposition.BLOCK
            ):
                admission_complete = False
        disposition = SyncDisposition(raw_created, raw_reused, normalized_created, normalized_reused, False, False, tuple(sorted(substitution_receipt_ids)))
        freshness_limit = min(
            (
                self.source_policy.route_for(dataset).freshness_max_stale_days
                for dataset in request.datasets
                if self.source_policy.route_for(dataset).completeness is CompletenessRequirement.REQUIRED
            ),
            default=0,
        )
        result = self.repository.build_snapshot(
            request, admitted, disposition, self.query_policy.identity,
            self.source_policy.identity, admission_complete, freshness_limit,
        )
        status = (
            SyncStatus.COMPLETE_WITH_SUBSTITUTION
            if result.status is SyncStatus.COMPLETE and substitution_receipt_ids
            else result.status
        )
        final_disposition = replace(
            result.disposition,
            substitution_receipt_ids=tuple(sorted(substitution_receipt_ids)),
        )
        return SyncResult(status, result.snapshot_id, result.requested_date, result.effective_session_date, result.freshness, result.quality, tuple(attempt_ids), result.coverage, result.next_step, result.stale_by_days, result.freshness_basis, result.last_success_at, result.distribution_qualification, final_disposition)

    def _sync_official_filing(self, request: SyncRequest) -> SyncResult:
        dataset = "official_filing"
        route = self.source_policy.route_for(dataset)
        if (
            route.fallback is not FallbackMode.NO_FALLBACK
            or route.qualified_equivalent_receipt_ids
        ):
            raise PersistenceError(
                "OFFICIAL_FILING_FALLBACK_FORBIDDEN",
                "Critical official filing evidence has no fallback route.",
            )
        if not self.source_policy.rights.local_storage_allowed:
            raise PersistenceError(
                "SOURCE_RIGHTS_STORAGE_BLOCKED",
                "Source policy forbids local storage.",
            )
        provider = self.provider
        rights = (
            self.fixture_rights.get((provider.provider_id, dataset))
            if provider.fixture
            else None
        )
        if provider.fixture and (
            rights is None
            or rights.source_identity != self.source_policy.source_identity
            or not rights.local_storage_allowed
            or not rights.deterministic_replay_allowed
        ):
            raise PersistenceError(
                "FIXTURE_RIGHTS_BLOCKING",
                "Official filing fixture rights are incomplete.",
            )
        if rights is not None:
            self.repository.validate_fixture_location(rights)

        cursor_value = self.repository.current_cursor(
            provider.provider_id,
            provider.adapter_version,
            dataset,
            request.security_id,
        )
        query = self.query_policy.build(dataset, request, cursor_value)
        batch = provider.fetch(query)
        if len(batch.envelopes) != 1:
            raise PersistenceError(
                "OFFICIAL_FILING_BATCH_INVALID",
                "Official filing providers return one bounded evidence envelope.",
            )
        envelope = batch.envelopes[0]
        if (
            envelope.source_identity != self.source_policy.source_identity
            or envelope.source_authority
            is not self.source_policy.source_authority
            or envelope.terms_profile != self.source_policy.terms_profile
        ):
            envelope = replace(
                envelope,
                status=FetchStatus.FAILED,
                payload=None,
                raw_sha256=None,
                cursor_value=None,
                error_code="SOURCE_POLICY_EVIDENCE_MISMATCH",
            )

        raw_hash, raw_was_created = self.repository.publish_raw(envelope)
        prepared_items = ()
        blocking_code = None
        cursor = None
        if (
            envelope.status is FetchStatus.COMPLETE
            and envelope.payload is not None
        ):
            try:
                items = normalize(
                    dataset,
                    envelope.payload,
                    request.security_id,
                    request.market,
                    envelope.source_identity,
                    envelope.retrieved_at,
                )
                prepared_items = self.repository.prepare_items(items)
                if any(
                    item.quality
                    in {QualityStatus.BLOCKING, QualityStatus.QUARANTINE}
                    for item in prepared_items
                ):
                    blocking_code = "OFFICIAL_FILING_QUALITY_BLOCKED"
                elif envelope.cursor_value:
                    cursor = CursorCheckpoint(
                        provider.provider_id,
                        provider.adapter_version,
                        dataset,
                        request.security_id,
                        envelope.cursor_value,
                    )
            except ValueError as error:
                blocking_code = str(error)

        attempt_ids: tuple[str, ...]
        with self.repository.atomic_write(
            f"official-filing-sync:{request.invocation_id}"
        ):
            rights_profile_id = self.repository.register_policy_context(
                self.query_policy,
                self.source_policy,
                rights,
            )
            attempt_id, _, _ = self.repository.record_attempt(
                request.invocation_id,
                provider.provider_id,
                provider.adapter_version,
                dataset,
                envelope,
                (
                    "fetched"
                    if raw_was_created or raw_hash is None
                    else "reused"
                ),
                cursor_value,
                self.query_policy.identity,
                self.source_policy.identity,
                rights_profile_id,
                raw_hash,
                raw_was_created,
            )
            attempt_ids = (attempt_id,)
            if provider.fixture:
                assert rights is not None
                self.repository.register_rights(rights, raw_hash)
            admitted: tuple[tuple[str, str], ...] = ()
            normalized_created = normalized_reused = 0
            persistence_blocked = False
            if prepared_items:
                (
                    admitted,
                    persistence_blocked,
                    normalized_created,
                    normalized_reused,
                ) = self.repository.persist_items(
                    attempt_id,
                    prepared_items,
                    request.as_of_at,
                    cursor,
                )
            if blocking_code is not None:
                self.repository.record_blocking_issue(
                    attempt_id, blocking_code
                )
            admission_complete = (
                envelope.status is FetchStatus.COMPLETE
                and envelope.payload is not None
                and bool(prepared_items)
                and blocking_code is None
                and not persistence_blocked
            )
            disposition = SyncDisposition(
                int(raw_hash is not None and raw_was_created),
                int(raw_hash is not None and not raw_was_created),
                normalized_created,
                normalized_reused,
                False,
                False,
            )
            result = self.repository.build_snapshot(
                request,
                admitted,
                disposition,
                self.query_policy.identity,
                self.source_policy.identity,
                admission_complete,
                route.freshness_max_stale_days,
            )
        return SyncResult(
            result.status,
            result.snapshot_id,
            result.requested_date,
            result.effective_session_date,
            result.freshness,
            result.quality,
            attempt_ids,
            result.coverage,
            result.next_step,
            result.stale_by_days,
            result.freshness_basis,
            result.last_success_at,
            result.distribution_qualification,
            result.disposition,
        )

    def snapshot_members(self, snapshot_id: str) -> tuple[SnapshotMemberView, ...]:
        return tuple(SnapshotMemberView(version_id, dataset) for version_id, dataset in self.repository.snapshot_members(snapshot_id))

    def provider_attempt_evidence(self, attempt_ids: tuple[str, ...]) -> tuple[ProviderAttemptEvidence, ...]:
        return self.repository.provider_attempt_evidence(attempt_ids)

    def snapshot_source_attempt_ids(
        self, snapshot_id: str
    ) -> tuple[str, ...]:
        return self.repository.snapshot_source_attempt_ids(snapshot_id)
