from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Mapping, Sequence

from dataclasses import replace

from trading_platform.domain.data import CursorCheckpoint, DataProvider, FetchRequest, FetchStatus, FixtureRights, QualityStatus, SnapshotMemberView, SyncDisposition, SyncRequest, SyncResult

from .normalizer import normalize
from .repository import DataRepository
from trading_platform.persistence.locking import PersistenceError


class DataSyncService:
    def __init__(self, repository: DataRepository, providers: Sequence[DataProvider], fixture_rights: Mapping[tuple[str, str], FixtureRights] | None = None) -> None:
        self.repository = repository
        self.providers = tuple(providers)
        self.fixture_rights = dict(fixture_rights or {})

    def sync(self, request: SyncRequest) -> SyncResult:
        if request.offline:
            return self.repository.offline_result(request)
        admitted: list[tuple[str, str]] = []
        attempt_ids: list[str] = []
        raw_created = raw_reused = normalized_created = normalized_reused = 0
        for dataset in request.datasets:
            completed = False
            for provider in self.providers:
                cursor_value = self.repository.current_cursor(provider.provider_id, provider.adapter_version, dataset, request.security_id)
                compact_date = request.requested_date.replace("-", "")
                compact_start = (date.fromisoformat(request.requested_date) - timedelta(days=7)).strftime("%Y%m%d")
                if dataset == "trade_cal":
                    params = {"exchange": request.market, "start_date": compact_start, "end_date": compact_date}
                elif dataset == "daily":
                    params = {"ts_code": request.provider_security_code, "start_date": compact_start, "end_date": compact_date}
                else:
                    params = {"ts_code": request.provider_security_code, "list_status": "L"}
                fetch = FetchRequest(request.invocation_id, provider.provider_id, provider.adapter_version, dataset, provider.endpoint, request.security_id, request.market, compact_start, request.requested_date, cursor_value, request.security_id, params, "configured" if not provider.fixture else "fixture-none", request.network_authorized)
                batch = provider.fetch(fetch)
                for envelope in batch.envelopes:
                    rights = self.fixture_rights.get((provider.provider_id, dataset)) if provider.fixture else None
                    if provider.fixture and (rights is None or rights.source_identity != envelope.source_identity or not rights.local_storage_allowed or not rights.deterministic_replay_allowed):
                        blocked = replace(envelope, status=FetchStatus.FAILED, payload=None, raw_sha256=None, cursor_value=None, error_code="FIXTURE_RIGHTS_BLOCKING")
                        attempt_id, _, _ = self.repository.record_attempt(request.invocation_id, provider.provider_id, provider.adapter_version, dataset, blocked, "not_stored", cursor_value)
                        attempt_ids.append(attempt_id)
                        continue
                    if rights is not None:
                        try:
                            self.repository.validate_fixture_location(rights)
                        except PersistenceError as error:
                            blocked = replace(envelope, status=FetchStatus.FAILED, payload=None, raw_sha256=None, cursor_value=None, error_code=error.code)
                            attempt_id, _, _ = self.repository.record_attempt(request.invocation_id, provider.provider_id, provider.adapter_version, dataset, blocked, "not_stored", cursor_value)
                            attempt_ids.append(attempt_id)
                            continue
                    attempt_id, raw_hash, was_raw_created = self.repository.record_attempt(request.invocation_id, provider.provider_id, provider.adapter_version, dataset, envelope, "fetched", cursor_value)
                    if raw_hash is not None:
                        raw_created += int(was_raw_created)
                        raw_reused += int(not was_raw_created)
                    attempt_ids.append(attempt_id)
                    if provider.fixture:
                        assert rights is not None
                        self.repository.register_rights(rights, raw_hash)
                    if envelope.status is not FetchStatus.COMPLETE or envelope.payload is None:
                        continue
                    try:
                        items = normalize(dataset, envelope.payload, request.security_id, request.market, envelope.source_identity, envelope.retrieved_at)
                    except ValueError as error:
                        self.repository.record_blocking_issue(attempt_id, str(error))
                        continue
                    blocking = any(item.quality in {QualityStatus.BLOCKING, QualityStatus.QUARANTINE} for item in items)
                    cursor = None if blocking or not envelope.cursor_value else CursorCheckpoint(provider.provider_id, provider.adapter_version, dataset, request.security_id, envelope.cursor_value)
                    try:
                        dataset_members, persistence_blocked, created_count, reused_count = self.repository.persist_items(attempt_id, items, request.as_of_at, cursor)
                    except (sqlite3.IntegrityError, PersistenceError, ValueError) as error:
                        self.repository.record_blocking_issue(attempt_id, "IDENTITY_OR_PERSISTENCE_CONFLICT")
                        continue
                    admitted.extend(dataset_members)
                    normalized_created += created_count
                    normalized_reused += reused_count
                    completed = not blocking and not persistence_blocked
                    if completed:
                        break
                if completed:
                    break
        disposition = SyncDisposition(raw_created, raw_reused, normalized_created, normalized_reused, False, False)
        result = self.repository.build_snapshot(request, admitted, disposition)
        return SyncResult(result.status, result.snapshot_id, result.requested_date, result.effective_session_date, result.freshness, result.quality, tuple(attempt_ids), result.coverage, result.next_step, result.stale_by_days, result.freshness_basis, result.last_success_at, result.distribution_qualification, result.disposition)

    def snapshot_members(self, snapshot_id: str) -> tuple[SnapshotMemberView, ...]:
        return tuple(SnapshotMemberView(version_id, dataset) for version_id, dataset in self.repository.snapshot_members(snapshot_id))
