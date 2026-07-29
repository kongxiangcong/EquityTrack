from __future__ import annotations

import hashlib
import json
import sqlite3
import base64
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable, Iterator

from trading_platform.domain.data import Coverage, CursorCheckpoint, DistributionQualification, FixtureRights, FreshnessStatus, NextStep, ProviderAttemptEvidence, QualityStatus, QueryPolicy, RawEnvelope, SourcePolicy, SyncDisposition, SyncRequest, SyncResult, SyncStatus
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
        self._atomic_write_active = False

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    @contextmanager
    def atomic_write(self, owner: str) -> Iterator[None]:
        if self._atomic_write_active:
            raise PersistenceError(
                "DATA_TRANSACTION_NESTED",
                "Data repository atomic writes cannot be nested.",
            )
        with self.writer_lock.acquire(owner):
            self.connection.execute("BEGIN IMMEDIATE")
            self._atomic_write_active = True
            try:
                yield
                self._fault("data.before_atomic_commit")
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise
            finally:
                self._atomic_write_active = False
            self._fault("data.after_atomic_commit")

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        if self._atomic_write_active:
            yield
            return
        with self.connection:
            yield

    @contextmanager
    def _writer_scope(self, owner: str) -> Iterator[None]:
        if self._atomic_write_active:
            yield
            return
        with self.writer_lock.acquire(owner):
            yield

    def register_policy_context(
        self,
        query_policy: QueryPolicy,
        source_policy: SourcePolicy,
        fixture_rights: FixtureRights | None,
    ) -> str:
        query_json = json.dumps(
            query_policy.canonical_content,
            sort_keys=True,
            separators=(",", ":"),
        )
        source_json = json.dumps(
            source_policy.canonical_content,
            sort_keys=True,
            separators=(",", ":"),
        )
        if fixture_rights is None:
            subject_type = "source"
            subject_id = (
                f"{source_policy.provider_id}:{source_policy.adapter_version}"
            )
            terms_version = source_policy.terms_profile
            automation_allowed = source_policy.rights.automation_allowed
            local_storage_allowed = source_policy.rights.local_storage_allowed
            derived_use_allowed = source_policy.rights.derived_use_allowed
            repository_redistribution_allowed = (
                source_policy.rights.redistribution_allowed
            )
            packaged_distribution_allowed = (
                source_policy.rights.redistribution_allowed
            )
            reviewed_on = source_policy.rights.reviewed_on
            evidence_sha256 = source_policy.rights.evidence_sha256
        else:
            subject_type = "fixture_member"
            subject_id = fixture_rights.member_id
            terms_version = fixture_rights.terms_version
            automation_allowed = (
                fixture_rights.deterministic_replay_allowed
            )
            local_storage_allowed = fixture_rights.local_storage_allowed
            derived_use_allowed = False
            repository_redistribution_allowed = (
                fixture_rights.repository_redistribution_allowed
            )
            packaged_distribution_allowed = (
                fixture_rights.packaged_distribution_allowed
            )
            reviewed_on = fixture_rights.reviewed_on
            evidence_sha256 = None
        rights_content = {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "source_identity": source_policy.source_identity,
            "terms_version": terms_version,
            "automation_allowed": automation_allowed,
            "local_storage_allowed": local_storage_allowed,
            "derived_use_allowed": derived_use_allowed,
            "repository_redistribution_allowed": (
                repository_redistribution_allowed
            ),
            "packaged_distribution_allowed": (
                packaged_distribution_allowed
            ),
            "reviewed_on": reviewed_on,
            "evidence_sha256": evidence_sha256,
            "declared_fixture_raw_sha256": (
                fixture_rights.raw_sha256
                if fixture_rights is not None
                else None
            ),
        }
        rights_profile_id = (
            "rights_" + canonical_hash(rights_content)[:24]
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._write_transaction():
            self.connection.execute(
                "INSERT OR IGNORE INTO query_policy_record VALUES(?,?,?,?,?)",
                (
                    query_policy.identity,
                    query_policy.schema_version,
                    hashlib.sha256(query_json.encode()).hexdigest(),
                    query_json,
                    now,
                ),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO source_policy_record VALUES(?,?,?,?,?)",
                (
                    source_policy.identity,
                    source_policy.schema_version,
                    hashlib.sha256(source_json.encode()).hexdigest(),
                    source_json,
                    now,
                ),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO source_rights_profile VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rights_profile_id,
                    subject_type,
                    subject_id,
                    source_policy.source_identity,
                    terms_version,
                    int(automation_allowed),
                    int(local_storage_allowed),
                    int(derived_use_allowed),
                    int(repository_redistribution_allowed),
                    int(packaged_distribution_allowed),
                    reviewed_on,
                    evidence_sha256,
                ),
            )
        return rights_profile_id

    def publish_raw(
        self, envelope: RawEnvelope
    ) -> tuple[str | None, bool]:
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
        return raw_hash, not already_cached and raw_hash is not None

    def record_attempt(
        self,
        invocation_id: str,
        provider_id: str,
        adapter_version: str,
        dataset: str,
        envelope: RawEnvelope,
        cache_disposition: str,
        cursor_before: str | None,
        query_policy_identity: str,
        source_policy_identity: str,
        rights_profile_id: str,
        raw_hash: str | None,
        raw_created: bool,
    ) -> tuple[str, str | None, bool]:
        attempt_id = f"attempt_{canonical_hash({'invocation': invocation_id, 'provider': provider_id, 'adapter': adapter_version, 'dataset': dataset, 'retrieved': envelope.retrieved_at, 'source': envelope.source_identity})[:24]}"
        with self._write_transaction():
            self.connection.execute(
                "INSERT OR IGNORE INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, invocation_id, provider_id, adapter_version, dataset, envelope.source_identity, envelope.source_authority.value, envelope.real_source_url, json.dumps(dict(envelope.redacted_params), sort_keys=True), json.dumps(dict(envelope.response_headers), sort_keys=True), envelope.source_time_precision, envelope.terms_profile, envelope.status.value, cache_disposition, raw_hash, envelope.retrieved_at.isoformat(), envelope.error_code, cursor_before, envelope.cursor_value, "not_advanced", query_policy_identity, source_policy_identity, rights_profile_id),
            )
        return attempt_id, raw_hash, raw_created

    def register_rights(self, rights: FixtureRights, raw_hash: str | None) -> None:
        if not rights.local_storage_allowed or not rights.deterministic_replay_allowed:
            raise PersistenceError("FIXTURE_RIGHTS_BLOCKING", "Fixture is not authorized for local deterministic replay.")
        if rights.raw_sha256 is not None and rights.raw_sha256 != raw_hash:
            raise PersistenceError("FIXTURE_RIGHTS_HASH_MISMATCH", "Fixture rights hash does not match raw content.")

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
        blocked = self.connection.execute("SELECT 1 FROM source_rights_profile WHERE repository_redistribution_allowed=0 OR packaged_distribution_allowed=0 LIMIT 1").fetchone()
        if blocked is None:
            blocked = self.connection.execute("SELECT 1 FROM provider_attempt WHERE error_code IN ('FIXTURE_RIGHTS_BLOCKING','PRIVATE_FIXTURE_IN_GIT_WORKTREE') LIMIT 1").fetchone()
        return DistributionQualification.EXTERNAL_BLOCKED if blocked else DistributionQualification.QUALIFIED

    def snapshot_members(self, snapshot_id: str) -> tuple[tuple[str, str], ...]:
        return tuple((str(row[0]), str(row[1])) for row in self.connection.execute("SELECT m.normalized_version_id,r.dataset FROM data_snapshot_member m JOIN normalized_version v USING(normalized_version_id) JOIN normalized_record r USING(normalized_record_id) WHERE m.data_snapshot_id=? ORDER BY m.member_order", (snapshot_id,)))

    def snapshot_source_attempt_ids(
        self, snapshot_id: str
    ) -> tuple[str, ...]:
        return tuple(
            str(row[0])
            for row in self.connection.execute(
                "SELECT DISTINCT v.source_attempt_id "
                "FROM data_snapshot_member m "
                "JOIN normalized_version v USING(normalized_version_id) "
                "WHERE m.data_snapshot_id=? ORDER BY v.source_attempt_id",
                (snapshot_id,),
            )
        )

    def validate_fixture_location(self, rights: FixtureRights) -> None:
        if rights.repository_redistribution_allowed and rights.packaged_distribution_allowed:
            return
        if any((parent / ".git").exists() for parent in (self.data_root, *self.data_root.parents)):
            raise PersistenceError("PRIVATE_FIXTURE_IN_GIT_WORKTREE", "Private fixture raw must use a data root outside the Git worktree.")

    def prepare_items(
        self, items: Iterable[NormalizedItem]
    ) -> tuple[NormalizedItem, ...]:
        prepared: list[NormalizedItem] = []
        for item in items:
            if item.dataset != "official_filing":
                prepared.append(item)
                continue
            payload = dict(item.payload)
            encoded = payload.pop("document_base64", None)
            if not isinstance(encoded, str):
                raise PersistenceError(
                    "OFFICIAL_FILING_DOCUMENT_MISSING",
                    "Official filing document bytes are required.",
                )
            try:
                document = base64.b64decode(encoded, validate=True)
            except ValueError as error:
                raise PersistenceError(
                    "OFFICIAL_FILING_DOCUMENT_INVALID",
                    "Official filing document encoding is invalid.",
                ) from error
            published = self.workflow_ledger.commit_artifacts(
                GenericObjectCommit(document)
            )
            if published.sha256 != payload.get("document_sha256"):
                raise PersistenceError(
                    "OFFICIAL_FILING_DOCUMENT_HASH_MISMATCH",
                    "Official filing document hash does not match metadata.",
                )
            payload["document_object_sha256"] = published.sha256
            prepared.append(replace(item, payload=payload))
        return tuple(prepared)

    def persist_items(self, attempt_id: str, items: Iterable[NormalizedItem], cutoff: datetime, cursor: CursorCheckpoint | None = None) -> tuple[tuple[tuple[str, str], ...], bool, int, int]:
        items = tuple(items)
        admitted: list[tuple[str, str]] = []
        accepted_items: list[NormalizedItem] = []
        batch_blocked = False
        created_count = 0
        reused_count = 0
        with self._writer_scope(f"normalize:{attempt_id}"):
            with self._write_transaction():
                current_attempt = self.connection.execute(
                    "SELECT provider_id,source_authority,"
                    "source_policy_identity FROM provider_attempt "
                    "WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()
                if current_attempt is None:
                    raise PersistenceError(
                        "PROVIDER_ATTEMPT_MISSING",
                        "Normalization requires a persisted provider attempt.",
                    )
                for item in items:
                    record_id = f"record_{canonical_hash({'dataset': item.dataset, 'key': item.natural_key})[:24]}"
                    content = json.dumps(item.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    self.connection.execute("INSERT OR IGNORE INTO normalized_record VALUES(?,?,?)", (record_id, item.dataset, item.natural_key))
                    existing = self.connection.execute(
                        "SELECT nv.normalized_version_id "
                        "FROM normalized_version nv "
                        "JOIN provider_attempt pa "
                        "ON pa.attempt_id=nv.source_attempt_id "
                        "WHERE nv.normalized_record_id=? "
                        "AND nv.content_hash=? "
                        "AND pa.source_policy_identity=?",
                        (
                            record_id,
                            content_hash,
                            current_attempt["source_policy_identity"],
                        ),
                    ).fetchone()
                    if existing:
                        version_id = existing[0]
                        reused_count += 1
                    else:
                        previous = self.connection.execute("SELECT nv.normalized_version_id,nv.revision_no,pa.provider_id,pa.source_authority FROM normalized_version nv JOIN provider_attempt pa ON pa.attempt_id=nv.source_attempt_id WHERE nv.normalized_record_id=? ORDER BY nv.revision_no DESC LIMIT 1", (record_id,)).fetchone()
                        authority_rank = {"official": 4, "structured_aggregator": 3, "secondary": 2, "fixture": 1}
                        if previous and previous["provider_id"] != current_attempt["provider_id"] and authority_rank.get(current_attempt["source_authority"], 0) <= authority_rank.get(previous["source_authority"], 0):
                            issue_id = f"quality_{canonical_hash({'record': record_id, 'code': 'SOURCE_CONFLICT'})[:24]}"
                            self.connection.execute("INSERT OR IGNORE INTO data_quality_issue VALUES(?,?,?,?,?,?)", (issue_id, attempt_id, None, "blocking", "SOURCE_CONFLICT", "Same-authority providers disagree for one natural key."))
                            batch_blocked = True
                            continue
                        revision = 1 if previous is None else previous["revision_no"] + 1
                        version_id = f"version_{canonical_hash({'record': record_id, 'content': content_hash, 'source_policy': current_attempt['source_policy_identity']})[:24]}"
                        self.connection.execute(
                            "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (version_id, record_id, revision, content_hash, attempt_id, item.event_at, item.published_at, item.published_precision, item.available_at, item.availability_basis, item.retrieved_at, item.quality.value, previous["normalized_version_id"] if previous else None),
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
                    policy_row = self.connection.execute(
                        "SELECT source_policy_identity FROM provider_attempt "
                        "WHERE attempt_id=?",
                        (attempt_id,),
                    ).fetchone()
                    if policy_row is None:
                        raise PersistenceError(
                            "SOURCE_POLICY_IDENTITY_MISSING",
                            "Market-universe persistence requires its attempt source-policy identity.",
                        )
                    self.connection.execute(
                        "INSERT OR IGNORE INTO market_universe_version "
                        "VALUES(?,?,?,?,?)",
                        (
                            universe_id,
                            universe_items[0].payload["market_scope_id"],
                            cutoff.isoformat(),
                            policy_row["source_policy_identity"],
                            membership_hash,
                        ),
                    )
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
        with self._write_transaction():
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
        elif item.dataset == "official_filing":
            document_sha256 = row.get("document_object_sha256")
            if not isinstance(document_sha256, str):
                raise PersistenceError(
                    "OFFICIAL_FILING_RAW_OBJECT_MISSING",
                    "Official filing metadata must bind a durable raw object.",
                )
            filing_identity_hash = canonical_hash(
                {
                    "security_id": row["security_id"],
                    "authority": row["authority"],
                    "document_identity": row["document_identity"],
                    "raw_sha256": document_sha256,
                }
            )
            self.connection.execute(
                "INSERT INTO official_filing_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    row["security_id"],
                    row["issuer_identity"],
                    row["authority"],
                    row["document_identity"],
                    row["accession_or_document_id"],
                    row["filing_type"],
                    row.get("report_period_end"),
                    document_sha256,
                    row["content_type"],
                    row["byte_size"],
                    row["correction_status"],
                    filing_identity_hash,
                ),
            )
        elif item.dataset in {"income", "balancesheet", "cashflow"}:
            extracted_fields_json = json.dumps(
                row["extracted_fields"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            statement_identity_hash = canonical_hash(
                {
                    "security_id": row["security_id"],
                    "statement_kind": row["statement_kind"],
                    "period_end": row["period_end"],
                    "report_type": row["report_type"],
                    "update_flag": row.get("update_flag", ""),
                    "fields": row["extracted_fields"],
                }
            )
            self.connection.execute(
                "INSERT INTO terminal_financial_statement_version "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    row["security_id"],
                    row["statement_kind"],
                    row["period_end"],
                    row["report_type"],
                    row.get("update_flag", ""),
                    row["currency"],
                    row["accounting_standard"],
                    extracted_fields_json,
                    statement_identity_hash,
                ),
            )

    def build_snapshot(
        self, request: SyncRequest, admitted: Iterable[tuple[str, str]],
        disposition: SyncDisposition, query_policy_identity: str,
        source_policy_identity: str, admission_complete: bool,
        freshness_max_stale_days: int,
    ) -> SyncResult:
        members = sorted(set(admitted))
        if members:
            placeholders = ",".join("?" for _ in members)
            member_policy_rows = self.connection.execute(
                "SELECT DISTINCT a.query_policy_identity,"
                "a.source_policy_identity "
                "FROM normalized_version v "
                "JOIN provider_attempt a "
                "ON a.attempt_id=v.source_attempt_id "
                f"WHERE v.normalized_version_id IN ({placeholders})",
                tuple(version_id for version_id, _ in members),
            ).fetchall()
            if len(member_policy_rows) != 1:
                raise PersistenceError(
                    "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                    "Snapshot members do not resolve to one policy identity pair.",
                )
            query_policy_identity = str(
                member_policy_rows[0]["query_policy_identity"]
            )
            source_policy_identity = str(
                member_policy_rows[0]["source_policy_identity"]
            )
        if set(request.datasets) == {"official_filing"}:
            return self._build_filing_snapshot(
                request,
                members,
                disposition,
                query_policy_identity,
                source_policy_identity,
                admission_complete,
                freshness_max_stale_days,
            )
        sessions = self.connection.execute("SELECT session_date,calendar_version FROM market_session_version WHERE market=? AND is_open=1 AND session_date<=? AND available_at<=? ORDER BY session_date DESC", (request.market, request.requested_date, request.as_of_at.isoformat())).fetchall()
        if not sessions:
            return SyncResult(SyncStatus.MISSING, None, request.requested_date, None, FreshnessStatus.MISSING, QualityStatus.BLOCKING, (), Coverage(0, 0, 0, 0), NextStep.SYNC_TRADE_CALENDAR, 0, "no_cutoff_legal_calendar", None, self.distribution_qualification(), disposition)
        effective_session, calendar_version = sessions[0]
        universe = self.connection.execute(
            "SELECT v.market_universe_version_id "
            "FROM market_universe_version v "
            "JOIN market_universe_member m "
            "USING(market_universe_version_id) "
            "WHERE m.security_id=? AND v.as_of_at<=? "
            "ORDER BY v.as_of_at DESC LIMIT 1",
            (request.security_id, request.as_of_at.isoformat()),
        ).fetchone()
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
        membership_hash = canonical_hash(
            [
                {"id": item[0], "role": item[1]}
                for item in eligible_members
            ]
        )
        stale_by_days = max(0, (date.fromisoformat(request.requested_date) - date.fromisoformat(effective_session)).days - 1)
        freshness = (
            FreshnessStatus.VALID if stale_by_days <= freshness_max_stale_days else FreshnessStatus.STALE
        )
        snapshot_id = f"snapshot_{canonical_hash({'purpose': request.snapshot_purpose, 'scope': request.security_id, 'cutoff': request.as_of_at, 'members': membership_hash, 'universe': universe[0] if universe is not None else None, 'query': query_policy_identity, 'source': source_policy_identity, 'freshness': 'freshness@1'})[:24]}"
        if not admission_complete or freshness is FreshnessStatus.STALE:
            return SyncResult(SyncStatus.BLOCKED, None, request.requested_date, effective_session, freshness, QualityStatus.BLOCKING, (), coverage, NextStep.RESOLVE_MISSING_CROSS_SECTION, stale_by_days, "effective_complete_session", None, self.distribution_qualification(), disposition)

        last_success_at = datetime.now(timezone.utc).isoformat()
        snapshot_exists = self.connection.execute("SELECT 1 FROM data_snapshot WHERE data_snapshot_id=?", (snapshot_id,)).fetchone() is not None
        disposition = SyncDisposition(disposition.raw_created, disposition.raw_reused, disposition.normalized_created, disposition.normalized_reused, not snapshot_exists, snapshot_exists)
        with self._writer_scope(f"snapshot:{snapshot_id}"):
            with self._write_transaction():
                self.connection.execute("INSERT OR IGNORE INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (snapshot_id, request.security_id, request.snapshot_purpose.value, request.requested_date, effective_session, request.as_of_at.isoformat(), request.market_timezone, calendar_version, query_policy_identity, source_policy_identity, "freshness@1", membership_hash, freshness.value, "blocking" if quality is QualityStatus.BLOCKING else "pass", expected, len(eligible_ids), excluded, missing, stale_by_days, "effective_complete_session", last_success_at))
                if self.connection.execute(
                    "SELECT 1 FROM data_snapshot WHERE data_snapshot_id=?",
                    (snapshot_id,),
                ).fetchone() is None:
                    raise PersistenceError(
                        "SNAPSHOT_IDENTITY_CONFLICT",
                        "Snapshot identity was rejected by an existing "
                        "immutable uniqueness commitment.",
                    )
                if universe is not None:
                    if self.connection.execute(
                        "SELECT 1 FROM market_universe_version "
                        "WHERE market_universe_version_id=?",
                        (universe[0],),
                    ).fetchone() is None:
                        raise PersistenceError(
                            "MARKET_UNIVERSE_REFERENCE_MISSING",
                            "Selected market-universe version is missing.",
                        )
                    self.connection.execute("INSERT OR IGNORE INTO data_snapshot_universe_ref VALUES(?,?,?)", (snapshot_id, universe[0], request.market))
                for ordinal, (version_id, role) in enumerate(eligible_members):
                    self.connection.execute("INSERT OR IGNORE INTO data_snapshot_member VALUES(?,?,?,?)", (snapshot_id, version_id, role, ordinal))
        status = SyncStatus.BLOCKED if quality is QualityStatus.BLOCKING else SyncStatus.COMPLETE
        return SyncResult(status, snapshot_id, request.requested_date, effective_session, freshness, quality, (), coverage, NextStep.RESOLVE_MISSING_CROSS_SECTION if missing else None, stale_by_days, "effective_complete_session", last_success_at, self.distribution_qualification(), disposition)

    def _build_filing_snapshot(
        self,
        request: SyncRequest,
        members: list[tuple[str, str]],
        disposition: SyncDisposition,
        query_policy_identity: str,
        source_policy_identity: str,
        admission_complete: bool,
        freshness_max_stale_days: int,
    ) -> SyncResult:
        eligible_members = [
            (version_id, role)
            for version_id, role in members
            if role == "official_filing"
            and self.connection.execute(
                "SELECT quality_status FROM normalized_version "
                "WHERE normalized_version_id=?",
                (version_id,),
            ).fetchone()[0]
            in {"pass", "warning"}
        ]
        coverage = Coverage(
            len(members),
            len(eligible_members),
            0,
            len(members) - len(eligible_members),
        )
        if not admission_complete or not eligible_members:
            return SyncResult(
                SyncStatus.BLOCKED,
                None,
                request.requested_date,
                request.requested_date,
                FreshnessStatus.MISSING,
                QualityStatus.BLOCKING,
                (),
                coverage,
                NextStep.RESOLVE_MISSING_CROSS_SECTION,
                0,
                "official_filing_pit_membership",
                None,
                self.distribution_qualification(),
                disposition,
            )
        placeholders = ",".join("?" for _ in eligible_members)
        retrieved_row = self.connection.execute(
            "SELECT max(retrieved_at) FROM normalized_version "
            f"WHERE normalized_version_id IN ({placeholders})",
            tuple(version_id for version_id, _ in eligible_members),
        ).fetchone()
        latest_retrieved_at = (
            None if retrieved_row is None else retrieved_row[0]
        )
        if not isinstance(latest_retrieved_at, str):
            raise PersistenceError(
                "OFFICIAL_FILING_RETRIEVED_AT_MISSING",
                "Filing snapshot members require retrieval evidence.",
            )
        stale_by_days = max(
            0,
            (
                request.as_of_at.date()
                - parse_instant(latest_retrieved_at).date()
            ).days,
        )
        freshness = (
            FreshnessStatus.VALID
            if stale_by_days <= freshness_max_stale_days
            else FreshnessStatus.STALE
        )
        if freshness is FreshnessStatus.STALE:
            return SyncResult(
                SyncStatus.BLOCKED,
                None,
                request.requested_date,
                request.requested_date,
                freshness,
                QualityStatus.BLOCKING,
                (),
                coverage,
                NextStep.AUTHORIZE_REFRESH,
                stale_by_days,
                "official_filing_retrieved_at",
                latest_retrieved_at,
                self.distribution_qualification(),
                disposition,
            )
        membership_hash = canonical_hash(
            [
                {"id": version_id, "role": role}
                for version_id, role in eligible_members
            ]
        )
        snapshot_id = (
            "snapshot_"
            + canonical_hash(
                {
                    "purpose": request.snapshot_purpose,
                    "scope": request.security_id,
                    "cutoff": request.as_of_at,
                    "members": membership_hash,
                    "query": query_policy_identity,
                    "source": source_policy_identity,
                    "freshness": "official-filing-freshness@1",
                }
            )[:24]
        )
        existing = self.connection.execute(
            "SELECT 1 FROM data_snapshot WHERE data_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        disposition = replace(
            disposition,
            snapshot_created=existing is None,
            snapshot_reused=existing is not None,
        )
        last_success_at = latest_retrieved_at
        with self._writer_scope(f"snapshot:{snapshot_id}"):
            with self._write_transaction():
                self.connection.execute(
                    "INSERT OR IGNORE INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        snapshot_id,
                        request.security_id,
                        request.snapshot_purpose.value,
                        request.requested_date,
                        request.requested_date,
                        request.as_of_at.isoformat(),
                        request.market_timezone,
                        "not_applicable:filing_dataset",
                        query_policy_identity,
                        source_policy_identity,
                        "official-filing-freshness@1",
                        membership_hash,
                        freshness.value,
                        QualityStatus.PASS.value,
                        len(eligible_members),
                        len(eligible_members),
                        0,
                        0,
                        stale_by_days,
                        "official_filing_retrieved_at",
                        last_success_at,
                    ),
                )
                for ordinal, (version_id, role) in enumerate(
                    eligible_members
                ):
                    self.connection.execute(
                        "INSERT OR IGNORE INTO data_snapshot_member "
                        "VALUES(?,?,?,?)",
                        (snapshot_id, version_id, role, ordinal),
                    )
        return SyncResult(
            SyncStatus.COMPLETE,
            snapshot_id,
            request.requested_date,
            request.requested_date,
            freshness,
            QualityStatus.PASS,
            (),
            coverage,
            None,
            stale_by_days,
            "official_filing_retrieved_at",
            last_success_at,
            self.distribution_qualification(),
            disposition,
        )

    def offline_result(self, request: SyncRequest) -> SyncResult:
        row = self.connection.execute("SELECT * FROM data_snapshot WHERE scope_id=? AND snapshot_purpose=? AND as_of_at<=? ORDER BY as_of_at DESC LIMIT 1", (request.security_id, request.snapshot_purpose.value, request.as_of_at.isoformat())).fetchone()
        if row is None:
            return SyncResult(SyncStatus.MISSING, None, request.requested_date, None, FreshnessStatus.MISSING, QualityStatus.BLOCKING, (), Coverage(0, 0, 0, 0), NextStep.AUTHORIZE_SYNC, 0, "no_cutoff_legal_cache", None, self.distribution_qualification(), SyncDisposition(0, 0, 0, 0, False, False))
        freshness = FreshnessStatus.VALID if row["requested_date"] == request.requested_date else FreshnessStatus.STALE
        stale_by_days = max(0, (date.fromisoformat(request.requested_date) - date.fromisoformat(row["effective_session_date"])).days - 1)
        coverage = Coverage(row["coverage_expected"], row["coverage_eligible"], row["coverage_excluded"], row["coverage_missing"])
        return SyncResult(SyncStatus.CACHED if freshness is FreshnessStatus.VALID else SyncStatus.CACHED_WITH_LIMITS, row["data_snapshot_id"], request.requested_date, row["effective_session_date"], freshness, QualityStatus(row["quality_status"]), (), coverage, None if freshness is FreshnessStatus.VALID else NextStep.AUTHORIZE_REFRESH, stale_by_days, row["freshness_basis"], row["last_success_at"], self.distribution_qualification(), SyncDisposition(0, 0, 0, 0, False, True))
