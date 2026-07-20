from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable

from trading_platform.domain.data import Coverage, CursorCheckpoint, DistributionQualification, FixtureRights, FreshnessStatus, NextStep, ProviderAttemptEvidence, QualityStatus, RawEnvelope, SyncDisposition, SyncRequest, SyncResult, SyncStatus
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock, PersistenceError
from trading_platform.application.workflow_ledger import GenericObjectCommit, WorkflowLedgerPort

from .normalizer import NormalizedItem, parse_instant


class DataRepository:
    def __init__(self, connection: sqlite3.Connection, workflow_ledger: WorkflowLedgerPort, data_root: Path, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.workflow_ledger = workflow_ledger
        self.data_root = data_root
        self.writer_lock = writer_lock
        self.fault_injector = None

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    def record_attempt(self, invocation_id: str, provider_id: str, adapter_version: str, dataset: str, envelope: RawEnvelope, cache_disposition: str, cursor_before: str | None) -> tuple[str, str | None, bool]:
        expected_hash = hashlib.sha256(envelope.payload).hexdigest() if envelope.payload is not None else None
        if expected_hash != envelope.raw_sha256:
            raise PersistenceError("RAW_HASH_MISMATCH", "Provider raw hash does not match payload.")
        object_commit = (
            self.workflow_ledger.commit_artifacts(GenericObjectCommit(envelope.payload))
            if envelope.payload is not None
            else None
        )
        raw_hash = None if object_commit is None else object_commit.sha256
        already_cached = (
            object_commit is not None
            and object_commit.disposition.value == "reused"
        )
        attempt_id = f"attempt_{canonical_hash({'invocation': invocation_id, 'provider': provider_id, 'adapter': adapter_version, 'dataset': dataset, 'retrieved': envelope.retrieved_at, 'source': envelope.source_identity})[:24]}"
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, invocation_id, provider_id, adapter_version, dataset, envelope.source_identity, envelope.source_authority.value, envelope.real_source_url, json.dumps(dict(envelope.redacted_params), sort_keys=True), json.dumps(dict(envelope.response_headers), sort_keys=True), envelope.source_time_precision, envelope.terms_profile, envelope.status.value, "reused" if already_cached else cache_disposition, raw_hash, envelope.retrieved_at.isoformat(), envelope.error_code, cursor_before, envelope.cursor_value, "not_advanced"),
            )
        return attempt_id, raw_hash, not already_cached and raw_hash is not None

    def register_rights(self, rights: FixtureRights, raw_hash: str | None) -> None:
        if not rights.local_storage_allowed or not rights.deterministic_replay_allowed:
            raise PersistenceError("FIXTURE_RIGHTS_BLOCKING", "Fixture is not authorized for local deterministic replay.")
        if rights.raw_sha256 is not None and rights.raw_sha256 != raw_hash:
            raise PersistenceError("FIXTURE_RIGHTS_HASH_MISMATCH", "Fixture rights hash does not match raw content.")
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO fixture_rights_profile VALUES(?,?,?,?,?,?,?,?,?)",
                (rights.member_id, rights.source_identity, int(rights.local_storage_allowed), int(rights.deterministic_replay_allowed), int(rights.repository_redistribution_allowed), int(rights.packaged_distribution_allowed), rights.terms_version, rights.reviewed_on, raw_hash or rights.raw_sha256),
            )

    def current_cursor(self, provider_id: str, adapter_version: str, dataset: str, scope_id: str) -> str | None:
        row = self.connection.execute("SELECT cursor_value FROM sync_cursor WHERE provider_id=? AND adapter_version=? AND dataset=? AND scope_id=? AND cursor_schema_version='cursor@1'", (provider_id, adapter_version, dataset, scope_id)).fetchone()
        return None if row is None else row[0]

    def provider_attempt_evidence(self, attempt_ids: tuple[str, ...]) -> tuple[ProviderAttemptEvidence, ...]:
        if not attempt_ids:
            return ()
        placeholders = ",".join("?" for _ in attempt_ids)
        attempts = self.connection.execute(
            f"SELECT attempt_id,dataset,status,raw_sha256,retrieved_at,error_code FROM provider_attempt WHERE attempt_id IN ({placeholders}) ORDER BY dataset,attempt_id",
            attempt_ids,
        ).fetchall()
        issues = self.connection.execute(
            f"SELECT attempt_id,code FROM data_quality_issue WHERE severity IN ('blocking','quarantine') AND attempt_id IN ({placeholders}) ORDER BY attempt_id,code",
            attempt_ids,
        ).fetchall()
        blocking_by_attempt: dict[str, list[str]] = {}
        for issue in issues:
            blocking_by_attempt.setdefault(str(issue["attempt_id"]), []).append(str(issue["code"]))
        return tuple(
            ProviderAttemptEvidence(
                attempt_id=str(row["attempt_id"]),
                dataset=str(row["dataset"]),
                status=str(row["status"]),
                raw_sha256=None if row["raw_sha256"] is None else str(row["raw_sha256"]),
                retrieved_at=str(row["retrieved_at"]),
                error_code=None if row["error_code"] is None else str(row["error_code"]),
                blocking_codes=tuple(blocking_by_attempt.get(str(row["attempt_id"]), ())),
            )
            for row in attempts
        )

    def distribution_qualification(self) -> DistributionQualification:
        blocked = self.connection.execute("SELECT 1 FROM fixture_rights_profile WHERE repository_redistribution_allowed=0 OR packaged_distribution_allowed=0 LIMIT 1").fetchone()
        if blocked is None:
            blocked = self.connection.execute("SELECT 1 FROM provider_attempt WHERE error_code IN ('FIXTURE_RIGHTS_BLOCKING','PRIVATE_FIXTURE_IN_GIT_WORKTREE') LIMIT 1").fetchone()
        return DistributionQualification.EXTERNAL_BLOCKED if blocked else DistributionQualification.QUALIFIED

    def snapshot_members(self, snapshot_id: str) -> tuple[tuple[str, str], ...]:
        return tuple((str(row[0]), str(row[1])) for row in self.connection.execute("SELECT m.normalized_version_id,r.dataset FROM data_snapshot_member m JOIN normalized_version v USING(normalized_version_id) JOIN normalized_record r USING(normalized_record_id) WHERE m.data_snapshot_id=? ORDER BY m.member_order", (snapshot_id,)))

    def validate_fixture_location(self, rights: FixtureRights) -> None:
        if rights.repository_redistribution_allowed and rights.packaged_distribution_allowed:
            return
        if any((parent / ".git").exists() for parent in (self.data_root, *self.data_root.parents)):
            raise PersistenceError("PRIVATE_FIXTURE_IN_GIT_WORKTREE", "Private fixture raw must use a data root outside the Git worktree.")

    def persist_items(self, attempt_id: str, items: Iterable[NormalizedItem], cutoff: datetime, cursor: CursorCheckpoint | None = None) -> tuple[tuple[tuple[str, str], ...], bool, int, int]:
        items = tuple(items)
        admitted: list[tuple[str, str]] = []
        accepted_items: list[NormalizedItem] = []
        batch_blocked = False
        created_count = 0
        reused_count = 0
        with self.writer_lock.acquire(f"normalize:{attempt_id}"):
            with self.connection:
                for item in items:
                    record_id = f"record_{canonical_hash({'dataset': item.dataset, 'key': item.natural_key})[:24]}"
                    content = json.dumps(item.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    self.connection.execute("INSERT OR IGNORE INTO normalized_record VALUES(?,?,?)", (record_id, item.dataset, item.natural_key))
                    existing = self.connection.execute("SELECT normalized_version_id FROM normalized_version WHERE normalized_record_id=? AND content_hash=?", (record_id, content_hash)).fetchone()
                    if existing:
                        version_id = existing[0]
                        reused_count += 1
                    else:
                        previous = self.connection.execute("SELECT nv.normalized_version_id,nv.revision_no,pa.provider_id,pa.source_authority FROM normalized_version nv JOIN provider_attempt pa ON pa.attempt_id=nv.source_attempt_id WHERE nv.normalized_record_id=? ORDER BY nv.revision_no DESC LIMIT 1", (record_id,)).fetchone()
                        current_attempt = self.connection.execute("SELECT provider_id,source_authority FROM provider_attempt WHERE attempt_id=?", (attempt_id,)).fetchone()
                        authority_rank = {"official": 4, "structured_aggregator": 3, "secondary": 2, "fixture": 1}
                        if previous and previous["provider_id"] != current_attempt["provider_id"] and authority_rank.get(current_attempt["source_authority"], 0) <= authority_rank.get(previous["source_authority"], 0):
                            issue_id = f"quality_{canonical_hash({'record': record_id, 'code': 'SOURCE_CONFLICT'})[:24]}"
                            self.connection.execute("INSERT OR IGNORE INTO data_quality_issue VALUES(?,?,?,?,?,?)", (issue_id, attempt_id, None, "blocking", "SOURCE_CONFLICT", "Same-authority providers disagree for one natural key."))
                            batch_blocked = True
                            continue
                        revision = 1 if previous is None else previous["revision_no"] + 1
                        version_id = f"version_{canonical_hash({'record': record_id, 'content': content_hash})[:24]}"
                        self.connection.execute(
                            "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (version_id, record_id, revision, content_hash, attempt_id, item.event_at, item.published_at, item.published_precision, item.available_at, item.availability_basis, datetime.now(timezone.utc).isoformat(), item.quality.value, previous["normalized_version_id"] if previous else None),
                        )
                        created_count += 1
                        self._persist_typed_payload(version_id, attempt_id, item)
                        for severity, code in item.issues:
                            issue_id = f"quality_{canonical_hash({'version': version_id, 'code': code})[:24]}"
                            self.connection.execute("INSERT OR IGNORE INTO data_quality_issue VALUES(?,?,?,?,?,?)", (issue_id, attempt_id, version_id, severity, code, code))
                    accepted_items.append(item)
                    try:
                        available_instant = parse_instant(item.available_at)
                    except ValueError:
                        available_instant = None
                    if item.quality in {QualityStatus.PASS, QualityStatus.WARNING} and available_instant is not None and available_instant <= cutoff:
                        admitted.append((version_id, item.dataset))
                    elif available_instant is not None and available_instant > cutoff:
                        issue_id = f"quality_{canonical_hash({'version': version_id, 'code': 'PIT_FUTURE_EXCLUDED'})[:24]}"
                        self.connection.execute("INSERT OR IGNORE INTO data_quality_issue VALUES(?,?,?,?,?,?)", (issue_id, attempt_id, version_id, "warning", "PIT_FUTURE_EXCLUDED", "available_at is after snapshot cutoff"))
                universe_items = [item for item in accepted_items if item.dataset == "market_universe" and item.quality in {QualityStatus.PASS, QualityStatus.WARNING} and parse_instant(item.available_at) <= cutoff]
                if universe_items:
                    identity = [{"security_id": item.payload["security_id"], "listed_from": item.payload["listed_from"], "delisted_after": item.payload.get("delisted_after"), "st_from": item.payload.get("st_from"), "st_to": item.payload.get("st_to"), "source_ref": item.payload["source_ref"]} for item in sorted(universe_items, key=lambda value: value.payload["security_id"])]
                    membership_hash = canonical_hash(identity)
                    universe_id = f"universe_{membership_hash[:24]}"
                    self.connection.execute("INSERT OR IGNORE INTO market_universe_version VALUES(?,?,?,?,?)", (universe_id, universe_items[0].payload["market_scope_id"], cutoff.isoformat(), "universe-source@1", membership_hash))
                    for item in universe_items:
                        row = item.payload
                        self.connection.execute("INSERT OR IGNORE INTO market_universe_member VALUES(?,?,?,?,?,?,?)", (universe_id, row["security_id"], row["listed_from"], row.get("delisted_after"), row.get("st_from"), row.get("st_to"), row["source_ref"]))
                if cursor is not None and not batch_blocked:
                    current = self.current_cursor(cursor.provider_id, cursor.adapter_version, cursor.dataset, cursor.scope_id)
                    if current == cursor.cursor_value:
                        self.connection.execute("UPDATE provider_attempt SET cursor_disposition='unchanged' WHERE attempt_id=?", (attempt_id,))
                    else:
                        self.connection.execute("INSERT OR REPLACE INTO sync_cursor VALUES(?,?,?,?,?,?,?)", (cursor.provider_id, cursor.adapter_version, cursor.dataset, cursor.scope_id, "cursor@1", cursor.cursor_value, datetime.now(timezone.utc).isoformat()))
                        self.connection.execute("UPDATE provider_attempt SET cursor_disposition='advanced' WHERE attempt_id=?", (attempt_id,))
                self._fault("data.before_commit")
            self._fault("data.after_commit")
        return tuple(admitted), batch_blocked, created_count, reused_count

    def record_blocking_issue(self, attempt_id: str, code: str) -> None:
        issue_id = f"quality_{canonical_hash({'attempt': attempt_id, 'code': code})[:24]}"
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO data_quality_issue VALUES(?,?,?,?,?,?)", (issue_id, attempt_id, None, "blocking", code, code))

    def _persist_typed_payload(self, version_id: str, attempt_id: str, item: NormalizedItem) -> None:
        row = item.payload
        if item.dataset == "daily":
            values = [format(Decimal(str(row[key])), "f") for key in ("open", "high", "low", "close", "volume")]
            amount = None if row.get("amount") is None else format(Decimal(str(row["amount"])), "f")
            self.connection.execute("INSERT INTO ohlcv_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (version_id, row["security_id"], row["session_date"], row.get("market_timezone", "Asia/Shanghai"), "none", *values, row["volume_unit"], amount, row.get("amount_unit"), row["currency"]))
        elif item.dataset == "trade_cal":
            session_id = f"session_{canonical_hash({'market': row['market'], 'date': row['session_date'], 'version': row['calendar_version']})[:24]}"
            self.connection.execute("INSERT OR IGNORE INTO market_session_version VALUES(?,?,?,?,?,?,?)", (session_id, row["market"], row["session_date"], int(bool(row["is_open"])), row["calendar_version"], item.available_at, attempt_id))

    def build_snapshot(self, request: SyncRequest, admitted: Iterable[tuple[str, str]], disposition: SyncDisposition) -> SyncResult:
        members = sorted(set(admitted))
        sessions = self.connection.execute("SELECT session_date,calendar_version FROM market_session_version WHERE market=? AND is_open=1 AND session_date<=? AND available_at<=? ORDER BY session_date DESC", (request.market, request.requested_date, request.as_of_at.isoformat())).fetchall()
        if not sessions:
            return SyncResult(SyncStatus.MISSING, None, request.requested_date, None, FreshnessStatus.MISSING, QualityStatus.BLOCKING, (), Coverage(0, 0, 0, 0), NextStep.SYNC_TRADE_CALENDAR, 0, "no_cutoff_legal_calendar", None, self.distribution_qualification(), disposition)
        effective_session, calendar_version = sessions[0]
        universe = self.connection.execute("SELECT market_universe_version_id FROM market_universe_version WHERE market_scope_id=? AND as_of_at<=? ORDER BY as_of_at DESC LIMIT 1", (request.market, request.as_of_at.isoformat())).fetchone()
        universe_payloads = [] if universe is None else self.connection.execute("SELECT * FROM market_universe_member WHERE market_universe_version_id=? ORDER BY security_id", (universe[0],)).fetchall()
        expected = len(universe_payloads)
        eligible_ids = {row["security_id"] for row in universe_payloads if row["listed_from"] <= effective_session and (row["delisted_after"] is None or row["delisted_after"] > effective_session)}
        admitted_ids = [version_id for version_id, role in members if role == "daily"]
        daily_ids: set[str] = set()
        for version_id in admitted_ids:
            row = self.connection.execute("SELECT security_id,amount_decimal FROM ohlcv_version WHERE normalized_version_id=? AND session_date=?", (version_id, effective_session)).fetchone()
            if row is not None and row["amount_decimal"] is not None:
                daily_ids.add(row["security_id"])
        missing = len(eligible_ids - daily_ids) if universe is not None else 1
        excluded = expected - len(eligible_ids)
        coverage = Coverage(expected, len(eligible_ids), excluded, missing)
        quality = QualityStatus.BLOCKING if missing or universe is None else QualityStatus.PASS
        eligible_members = [(version_id, role) for version_id, role in members if self.connection.execute("SELECT quality_status FROM normalized_version WHERE normalized_version_id=?", (version_id,)).fetchone()[0] in {"pass", "warning"}]
        membership_hash = canonical_hash([{"id": item[0], "role": item[1]} for item in eligible_members])
        stale_by_days = max(0, (date.fromisoformat(request.requested_date) - date.fromisoformat(effective_session)).days - 1)
        freshness = FreshnessStatus.VALID if stale_by_days == 0 else FreshnessStatus.STALE
        snapshot_id = f"snapshot_{canonical_hash({'purpose': request.snapshot_purpose, 'scope': request.security_id, 'cutoff': request.as_of_at, 'members': membership_hash, 'query': 'query@1', 'source': 'source@1', 'freshness': 'freshness@1'})[:24]}"
        last_success_at = datetime.now(timezone.utc).isoformat()
        snapshot_exists = self.connection.execute("SELECT 1 FROM data_snapshot WHERE data_snapshot_id=?", (snapshot_id,)).fetchone() is not None
        disposition = SyncDisposition(disposition.raw_created, disposition.raw_reused, disposition.normalized_created, disposition.normalized_reused, not snapshot_exists, snapshot_exists)
        with self.writer_lock.acquire(f"snapshot:{snapshot_id}"):
            with self.connection:
                self.connection.execute("INSERT OR IGNORE INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (snapshot_id, request.security_id, request.snapshot_purpose.value, request.requested_date, effective_session, request.as_of_at.isoformat(), request.market_timezone, calendar_version, "query@1", "source@1", "freshness@1", membership_hash, freshness.value, "blocking" if quality is QualityStatus.BLOCKING else "pass", expected, len(eligible_ids), excluded, missing, stale_by_days, "effective_complete_session", last_success_at))
                if universe is not None:
                    self.connection.execute("INSERT OR IGNORE INTO data_snapshot_universe_ref VALUES(?,?,?)", (snapshot_id, universe[0], request.market))
                for ordinal, (version_id, role) in enumerate(eligible_members):
                    self.connection.execute("INSERT OR IGNORE INTO data_snapshot_member VALUES(?,?,?,?)", (snapshot_id, version_id, role, ordinal))
        status = SyncStatus.BLOCKED if quality is QualityStatus.BLOCKING else SyncStatus.COMPLETE
        return SyncResult(status, snapshot_id, request.requested_date, effective_session, freshness, quality, (), coverage, NextStep.RESOLVE_MISSING_CROSS_SECTION if missing else None, stale_by_days, "effective_complete_session", last_success_at, self.distribution_qualification(), disposition)

    def offline_result(self, request: SyncRequest) -> SyncResult:
        row = self.connection.execute("SELECT * FROM data_snapshot WHERE scope_id=? AND snapshot_purpose=? AND as_of_at<=? ORDER BY as_of_at DESC LIMIT 1", (request.security_id, request.snapshot_purpose.value, request.as_of_at.isoformat())).fetchone()
        if row is None:
            return SyncResult(SyncStatus.MISSING, None, request.requested_date, None, FreshnessStatus.MISSING, QualityStatus.BLOCKING, (), Coverage(0, 0, 0, 0), NextStep.AUTHORIZE_SYNC, 0, "no_cutoff_legal_cache", None, self.distribution_qualification(), SyncDisposition(0, 0, 0, 0, False, False))
        freshness = FreshnessStatus.VALID if row["requested_date"] == request.requested_date else FreshnessStatus.STALE
        stale_by_days = max(0, (date.fromisoformat(request.requested_date) - date.fromisoformat(row["effective_session_date"])).days - 1)
        coverage = Coverage(row["coverage_expected"], row["coverage_eligible"], row["coverage_excluded"], row["coverage_missing"])
        return SyncResult(SyncStatus.CACHED if freshness is FreshnessStatus.VALID else SyncStatus.CACHED_WITH_LIMITS, row["data_snapshot_id"], request.requested_date, row["effective_session_date"], freshness, QualityStatus(row["quality_status"]), (), coverage, None if freshness is FreshnessStatus.VALID else NextStep.AUTHORIZE_REFRESH, stale_by_days, row["freshness_basis"], row["last_success_at"], self.distribution_qualification(), SyncDisposition(0, 0, 0, 0, False, True))
