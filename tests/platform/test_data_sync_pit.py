from __future__ import annotations

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application.contracts import Capability, CapabilityStatus, HealthQuery, SecurityIdentity
from trading_platform.data.kimi_agentgw import KimiAgentGatewayProvider
from trading_platform.data.providers import FixtureProvider
from trading_platform.domain.data import CompletenessRequirement, DistributionQualification, FallbackMode, FetchStatus, FinancialStatementQuery, FixtureRights, FreshnessStatus, MarketDataCapability, ProviderCapabilityStatus, QualifiedEquivalentBinding, QualityStatus, QueryPolicy, SnapshotPurpose, SourceAuthority, SourceFailureDisposition, SourcePolicy, SourceRights, SourceRoute, SyncRequest, SyncStatus, TradingCalendarQuery


def _bytes(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"rows": rows}, sort_keys=True).encode("utf-8")


FIXTURE_SOURCE = "derived-fact-fixture:ed5e784c2f4f335b430783f1e5160add4e1df086559748a679f30b95df758e11"


def _payloads(close: str = "82.33", include_old: bool = True) -> dict[str, bytes]:
    fixture_root = Path(__file__).parents[1] / "fixtures/platform_data"
    if close == "82.33" and include_old:
        return {name: (fixture_root / f"{name}.json").read_bytes().rstrip(b"\r\n") for name in ("trade_cal", "market_universe", "daily")}
    common = {"availability_basis": "publisher_timestamp", "published_precision": "date"}
    calendar = [
        {**common, "market": "SZSE", "session_date": "2026-07-10", "is_open": True, "calendar_version": "cn-calendar@2026", "available_at": "2026-07-10T00:00:00Z"},
        {**common, "market": "SZSE", "session_date": "2026-07-11", "is_open": False, "calendar_version": "cn-calendar@2026", "available_at": "2026-07-10T00:00:00Z"},
    ]
    universe = [
        {**common, "market_scope_id": "SZSE", "security_id": "security_yihua", "listed_from": "2017-09-07", "source_ref": f"{FIXTURE_SOURCE}:stock_basic", "available_at": "2017-09-07T00:00:00Z"},
        {**common, "market_scope_id": "SZSE", "security_id": "security_old", "listed_from": "2010-01-01", "delisted_after": "2026-07-11", "source_ref": "synthetic-contract-sentinel:later-delisting", "available_at": "2026-07-10T00:00:00Z"},
        {**common, "market_scope_id": "SZSE", "security_id": "security_later", "listed_from": "2026-07-11", "source_ref": "synthetic-contract-sentinel:later-listing", "available_at": "2026-07-10T00:00:00Z"},
    ]
    daily = [
        {**common, "security_id": "security_yihua", "session_date": "2026-07-10", "market_timezone": "Asia/Shanghai", "adjustment_mode": "none", "open": "88.51", "high": "91.0", "low": "82.33", "close": close, "volume": "221879.03", "volume_unit": "hand", "amount": "1926373.75544", "amount_unit": "thousand_cny", "currency": "CNY", "published_at": "2026-07-10", "available_at": "2026-07-10T08:30:00Z"},
    ]
    if include_old:
        daily.append({**common, "security_id": "security_old", "session_date": "2026-07-10", "market_timezone": "Asia/Shanghai", "adjustment_mode": "none", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "100", "volume_unit": "hand", "amount": "1000", "amount_unit": "thousand_cny", "currency": "CNY", "published_at": "2026-07-10", "available_at": "2026-07-10T08:00:00Z"})
    daily.append({**common, "security_id": "security_yihua", "session_date": "2026-07-10", "market_timezone": "Asia/Shanghai", "adjustment_mode": "none", "open": "88.51", "high": "99", "low": "82.33", "close": "99", "volume": "221879.03", "volume_unit": "hand", "currency": "CNY", "available_at": "2026-07-12T08:00:00Z"})
    return {"trade_cal": _bytes(calendar), "market_universe": _bytes(universe), "daily": _bytes(daily)}


def _rights(provider_id: str, source_identity: str = FIXTURE_SOURCE) -> dict[tuple[str, str], FixtureRights]:
    return {(provider_id, dataset): FixtureRights(f"{provider_id}:{dataset}", source_identity, True, True, True, True, "fixture-terms@1", "2026-07-12") for dataset in ("trade_cal", "market_universe", "daily")}


def _request(invocation: str = "sync-1", requested_date: str = "2026-07-11", offline: bool = False) -> SyncRequest:
    return SyncRequest(invocation, "security_yihua", "002897", requested_date, datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc), "Asia/Shanghai", "SZSE", SnapshotPurpose.WORKFLOW, ("trade_cal", "market_universe", "daily"), False, offline)

def _composition(provider, source_identity: str = FIXTURE_SOURCE, source_authority: SourceAuthority = SourceAuthority.FIXTURE, terms_profile: str = "derived-fact-fixture-terms@1") -> dict[str, object]:
    query_policy = QueryPolicy("QueryPolicy@1", 7, "L", "none")
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        source_identity,
        source_authority,
        terms_profile,
        SourceRights(True, True, True, True, False, "2026-07-10"),
        tuple(
            SourceRoute(dataset, 1, CompletenessRequirement.REQUIRED, 1, FallbackMode.NO_FALLBACK, SourceFailureDisposition.BLOCK)
            for dataset in ("trade_cal", "market_universe", "daily")
        ),
    )
    return {
        "provider": provider,
        "query_policy": query_policy,
        "source_policy": source_policy,
    }




def _root(tmp_path: Path, payloads: dict[str, bytes] | None = None) -> PlatformTaskFixture:
    provider = FixtureProvider("fixture", "fixture@1", payloads or _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    root = PlatformTaskFixture(tmp_path, **_composition(provider), fixture_rights=_rights("fixture"))
    for stable_id, code in (("security_yihua", "002897"), ("security_old", "000001")):
        root.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    return root


def test_explicit_fixture_sync_freezes_pit_snapshot_and_reuses_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert root.health.inspect(HealthQuery()).capabilities[Capability.SYNC] is CapabilityStatus.AVAILABLE
    result = root.data.sync(_request())
    assert result.status is SyncStatus.COMPLETE
    assert result.requested_date == "2026-07-11"
    assert result.effective_session_date == "2026-07-10"
    assert result.freshness is FreshnessStatus.VALID and result.quality is QualityStatus.PASS
    assert result.coverage == type(result.coverage)(expected=3, eligible=2, excluded=1, missing=0)
    assert result.disposition.raw_created == 3 and result.disposition.normalized_created > 0 and result.disposition.snapshot_created
    cursor_times = {tuple(row) for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT dataset,advanced_at FROM sync_cursor")}
    replay = root.data.sync(_request("sync-2"))
    assert replay.snapshot_id == result.snapshot_id
    assert replay.disposition.raw_reused == 3 and replay.disposition.normalized_reused > 0 and replay.disposition.snapshot_reused
    assert {tuple(row) for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT dataset,advanced_at FROM sync_cursor")} == cursor_times
    connection = SQLiteOwningAdapterFixture(root.data_root)  # production composition state verified through persisted contracts
    assert connection.execute("SELECT count(*) FROM provider_attempt").fetchone()[0] == 6
    assert connection.execute("SELECT count(*) FROM sync_cursor").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM provider_attempt WHERE cursor_disposition='advanced'").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM provider_attempt WHERE cursor_disposition='unchanged'").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM data_quality_issue WHERE code='PIT_FUTURE_EXCLUDED'").fetchone()[0] >= 1
    assert connection.execute("SELECT count(*) FROM data_snapshot_member d JOIN normalized_version n USING(normalized_version_id) WHERE d.data_snapshot_id=? AND n.available_at>?", (result.snapshot_id, "2026-07-11T00:00:00+00:00")).fetchone()[0] == 0
    rights = connection.execute("SELECT repository_redistribution_allowed,packaged_distribution_allowed FROM source_rights_profile WHERE subject_type='fixture_member'").fetchall()
    assert rights and all(tuple(row) == (1, 1) for row in rights)
    root.close()


def test_partial_provider_response_is_persisted_and_blocks_required_route(tmp_path: Path) -> None:
    class PartialFixtureProvider(FixtureProvider):
        def fetch(self, request):
            batch = super().fetch(request)
            if request.dataset != "daily":
                return batch
            return replace(
                batch,
                envelopes=tuple(
                    replace(envelope, status=FetchStatus.PARTIAL, error_code="PROVIDER_PARTIAL")
                    for envelope in batch.envelopes
                ),
            )

    provider = PartialFixtureProvider("fixture", "fixture@1", _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    root = PlatformTaskFixture(tmp_path, **_composition(provider), fixture_rights=_rights("fixture"))
    result = root.data.sync(_request("partial-provider"))
    persisted = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT status,error_code FROM provider_attempt WHERE dataset='daily'"
    ).fetchone()
    assert result.snapshot_id is None and tuple(persisted) == ("partial", "PROVIDER_PARTIAL")
    root.close()

def test_offline_valid_stale_missing_and_coverage_missing_fail_closed(tmp_path: Path) -> None:
    empty_provider = FixtureProvider("fixture", "fixture@1", _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    empty = PlatformTaskFixture(tmp_path / "empty", **_composition(empty_provider), fixture_rights=_rights("fixture"))
    missing = empty.data.sync(_request("offline-missing", offline=True))
    assert missing.freshness is FreshnessStatus.MISSING and missing.next_step == "authorize_sync"
    empty.close()
    root = _root(tmp_path / "cached")
    assert root.data.sync(_request()).status is SyncStatus.COMPLETE
    assert root.data.sync(_request("offline-valid", offline=True)).freshness is FreshnessStatus.VALID
    stale = root.data.sync(_request("offline-stale", "2026-07-12", True))
    assert stale.freshness is FreshnessStatus.STALE and stale.next_step == "authorize_refresh"
    assert stale.coverage.expected == 3 and stale.coverage.eligible == 2
    assert stale.stale_by_days == 1 and stale.freshness_basis == "effective_complete_session" and stale.last_success_at is not None
    root.close()


def test_missing_or_git_unsafe_fixture_rights_never_persist_raw(tmp_path: Path) -> None:
    provider = FixtureProvider("private", "fixture@1", _payloads(), "private-source", "private-terms@1")
    repo_root = tmp_path / "repo"; (repo_root / ".git").mkdir(parents=True)
    rights = {("private", dataset): FixtureRights(f"private:{dataset}", "private-source", True, True, False, False, "private-terms@1", "2026-07-12") for dataset in ("trade_cal", "market_universe", "daily")}
    root = PlatformTaskFixture(repo_root / "data", **_composition(provider, "private-source", terms_profile="private-terms@1"), fixture_rights=rights)
    result = root.data.sync(_request())
    assert result.status is SyncStatus.MISSING
    assert result.distribution_qualification is DistributionQualification.EXTERNAL_BLOCKED
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM object_blob").fetchone()[0] == 0
    errors = {row[0] for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT error_code FROM provider_attempt")}
    assert errors == {"PRIVATE_FIXTURE_IN_GIT_WORKTREE"}
    root.close()


def test_same_authority_source_conflict_blocks_new_revision_and_cursor(tmp_path: Path) -> None:
    first_provider = FixtureProvider("p1", "fixture@1", _payloads("82.33"), "source:p1", "terms@1", SourceAuthority.STRUCTURED_AGGREGATOR)
    first = PlatformTaskFixture(tmp_path, **_composition(first_provider, "source:p1", SourceAuthority.STRUCTURED_AGGREGATOR, "terms@1"), fixture_rights=_rights("p1", "source:p1"))
    for stable_id, code in (("security_yihua", "002897"), ("security_old", "000001")):
        first.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    assert first.data.sync(_request()).status is SyncStatus.COMPLETE
    first.close()
    second_provider = FixtureProvider("p2", "fixture@1", _payloads("83.00"), "source:p2", "terms@1", SourceAuthority.STRUCTURED_AGGREGATOR)
    second = PlatformTaskFixture(tmp_path, **_composition(second_provider, "source:p2", SourceAuthority.STRUCTURED_AGGREGATOR, "terms@1"), fixture_rights=_rights("p2", "source:p2"))
    result = second.data.sync(_request("conflict"))
    assert result.status is SyncStatus.BLOCKED
    assert SQLiteOwningAdapterFixture(second.data_root).execute("SELECT count(*) FROM data_quality_issue WHERE code='SOURCE_CONFLICT'").fetchone()[0] >= 1
    assert SQLiteOwningAdapterFixture(second.data_root).execute("SELECT count(*) FROM sync_cursor WHERE provider_id='p2' AND dataset='daily'").fetchone()[0] == 0
    second.close()
def test_empty_schema_drift_and_wrong_security_never_advance_daily_cursor(
    tmp_path: Path,
) -> None:
    empty = _payloads()
    empty["daily"] = json.dumps({"rows": []}).encode("utf-8")
    schema_drift = {**_payloads(), "daily": b"{}"}
    wrong_security = _payloads()
    wrong_document = json.loads(wrong_security["daily"])
    for row in wrong_document["rows"]:
        row["security_id"] = "security_wrong"
    wrong_security["daily"] = json.dumps(wrong_document, sort_keys=True).encode("utf-8")

    for name, payloads, expected_code in (
        ("empty", empty, "EMPTY_CONFIRMED"),
        ("schema", schema_drift, "SCHEMA_DRIFT"),
        ("identity", wrong_security, "IDENTITY_OR_PERSISTENCE_CONFLICT"),
    ):
        root = _root(tmp_path / name, payloads)
        result = root.data.sync(_request(f"failure-{name}"))
        connection = SQLiteOwningAdapterFixture(root.data_root)
        codes = {row[0] for row in connection.execute("SELECT q.code FROM data_quality_issue q JOIN provider_attempt a USING(attempt_id) WHERE a.dataset='daily'")}
        assert expected_code in codes and result.snapshot_id is None
        assert connection.execute("SELECT count(*) FROM sync_cursor WHERE dataset='daily'").fetchone()[0] == 0
        root.close()


def test_single_security_universes_do_not_cross_contaminate_snapshots(
    tmp_path: Path,
) -> None:
    common = {"availability_basis": "publisher_timestamp", "published_precision": "date"}

    def per_security_payloads(security_id: str) -> dict[str, bytes]:
        calendar = [
            {**common, "market": "SZSE", "session_date": "2026-07-10", "is_open": True, "calendar_version": "cn-calendar@2026", "published_at": "2026-07-10", "available_at": "2026-07-10T00:00:00Z"},
        ]
        universe = [
            {**common, "market_scope_id": "CN_A_SHARE", "security_id": security_id, "listed_from": "2010-01-01", "source_ref": "synthetic-contract-sentinel:per-security-universe", "published_at": "2010-01-01", "available_at": "2010-01-01T00:00:00Z"},
        ]
        daily = [
            {**common, "security_id": security_id, "session_date": "2026-07-10", "market_timezone": "Asia/Shanghai", "adjustment_mode": "none", "open": "10", "high": "11", "low": "9", "close": "10", "volume": "100", "volume_unit": "share", "amount": "1000", "amount_unit": "yuan", "currency": "CNY", "published_at": "2026-07-10", "available_at": "2026-07-10T08:00:00Z"},
        ]
        return {
            "trade_cal": _bytes(calendar),
            "market_universe": _bytes(universe),
            "daily": _bytes(daily),
        }

    class PerSecurityFixtureProvider(FixtureProvider):
        def fetch(self, request):
            self._payloads = per_security_payloads(
                getattr(request, "security_id", "")
            )
            return super().fetch(request)

    provider = PerSecurityFixtureProvider(
        "per-security", "fixture@1", {}, "source:terminal", "terms@1",
        SourceAuthority.STRUCTURED_AGGREGATOR,
    )
    root = PlatformTaskFixture(
        tmp_path,
        **_composition(
            provider,
            "source:terminal",
            SourceAuthority.STRUCTURED_AGGREGATOR,
            "terms@1",
        ),
        fixture_rights=_rights("per-security", "source:terminal"),
    )
    securities = (
        ("security_first", "002897"),
        ("security_second", "002407"),
    )
    for security_id, code in securities:
        root.watchlist.add(
            f"watch:{security_id}",
            SecurityIdentity(
                security_id,
                "SZSE",
                code,
                "CNY",
                "2010-01-01",
            ),
        )
        result = root.data.sync(
            replace(
                _request(f"sync:{security_id}"),
                security_id=security_id,
                security_code=code,
                network_authorized=True,
            )
        )
        assert result.status is SyncStatus.COMPLETE
        assert result.coverage.missing == 0
    root.close()


def test_fixture_manifest_separates_real_derived_facts_from_synthetic_sentinels() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures/platform_data/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["source_identity"] == "derived_fact_fixture_non_official"
    assert manifest["raw_response_committed"] is False
    assert manifest["raw_response_distribution_qualification"] == "external_blocked"
    assert len(manifest["safe_capture_sha256"]) == 64
    assert all("synthetic-contract-sentinel" in item or "future-available-at" in item for item in manifest["sentinels"])
    import hashlib
    payload_hashes = {dataset: hashlib.sha256(payload).hexdigest() for dataset, payload in _payloads().items()}
    assert {member["member_id"]: member["payload_sha256"] for member in manifest["members"]} == payload_hashes
    assert all(set(member["rights"]) == {"local_storage_allowed", "deterministic_replay_allowed", "repository_redistribution_allowed", "packaged_distribution_allowed"} for member in manifest["members"])


def test_non_structural_cross_section_gap_blocks_snapshot(tmp_path: Path) -> None:
    missing_root = _root(tmp_path / "missing-coverage", _payloads(include_old=False))
    blocked = missing_root.data.sync(_request())
    assert blocked.status == "blocked" and blocked.coverage.missing == 1
    missing_root.close()


def test_revision_creates_parallel_version_and_new_snapshot(tmp_path: Path) -> None:
    first_root = _root(tmp_path, _payloads("82.33"))
    first = first_root.data.sync(_request())
    first_root.close()
    second_root = _root(tmp_path, _payloads("83.00"))
    second = second_root.data.sync(_request("sync-revision"))
    assert second.snapshot_id != first.snapshot_id
    revisions = SQLiteOwningAdapterFixture(second_root.data_root).execute("SELECT revision_no FROM normalized_version nv JOIN normalized_record nr USING(normalized_record_id) WHERE nr.dataset='daily' AND nr.natural_key='security_yihua:2026-07-10:none' ORDER BY revision_no").fetchall()
    assert [row[0] for row in revisions] == [1, 2, 3]
    second_root.close()




def test_private_fixture_rights_are_preserved_without_upgrading_redistribution(tmp_path: Path) -> None:
    provider = FixtureProvider("private", "fixture@1", _payloads(), "local-private-fixture", "private-terms@1")
    rights = {("private", dataset): FixtureRights(f"private:{dataset}", "local-private-fixture", True, True, False, False, "private-terms@1", "2026-07-12") for dataset in ("trade_cal", "market_universe", "daily")}
    root = PlatformTaskFixture(tmp_path, **_composition(provider, "local-private-fixture", terms_profile="private-terms@1"), fixture_rights=rights)
    for stable_id, code in (("security_yihua", "002897"), ("security_old", "000001")):
        root.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    private_result = root.data.sync(_request())
    assert private_result.status is SyncStatus.COMPLETE
    assert private_result.distribution_qualification is DistributionQualification.EXTERNAL_BLOCKED
    recorded = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT repository_redistribution_allowed,packaged_distribution_allowed FROM source_rights_profile WHERE subject_type='fixture_member'").fetchall()
    assert recorded and all(tuple(row) == (0, 0) for row in recorded)
    root.close()


def test_provider_capabilities_make_unsupported_market_facts_explicit() -> None:
    statuses = {
        item.capability: (item.status, item.reason_code)
        for item in KimiAgentGatewayProvider.capabilities
    }
    assert statuses[MarketDataCapability.TRADING_CALENDAR] == (
        ProviderCapabilityStatus.SUPPORTED,
        "WIND_INDEX_SESSIONS",
    )
    assert statuses[MarketDataCapability.DAILY_UNADJUSTED] == (
        ProviderCapabilityStatus.SUPPORTED,
        "WIND_GET_PRICE_UNADJUSTED",
    )
    for capability in (
        MarketDataCapability.ADJUSTMENT_FACTORS,
        MarketDataCapability.CORPORATE_ACTIONS,
        MarketDataCapability.SUSPENSION_STATUS,
        MarketDataCapability.PRICE_LIMIT_STATUS,
    ):
        assert statuses[capability][0] is ProviderCapabilityStatus.UNAVAILABLE


def test_declared_qualified_equivalent_persists_primary_and_substitute_attempts(tmp_path: Path) -> None:
    receipt_id = "artifact_qualified_equivalent_01"
    primary = FixtureProvider(
        "primary", "fixture@1", {}, "source:primary", "terms@1",
        SourceAuthority.STRUCTURED_AGGREGATOR,
    )
    equivalent = FixtureProvider(
        "equivalent", "fixture@1", _payloads(), "source:equivalent", "terms@1",
        SourceAuthority.STRUCTURED_AGGREGATOR,
    )
    primary_composition = _composition(
        primary, "source:primary", SourceAuthority.STRUCTURED_AGGREGATOR, "terms@1"
    )
    primary_policy = replace(
        primary_composition["source_policy"],
        routes=tuple(
            SourceRoute(
                dataset, 1, CompletenessRequirement.REQUIRED, 1,
                FallbackMode.QUALIFIED_EQUIVALENT, SourceFailureDisposition.BLOCK,
                (receipt_id,),

                ("FIXTURE_DATASET_MISSING",),
            )
            for dataset in ("trade_cal", "market_universe", "daily")
        ),
    )
    equivalent_policy = _composition(
        equivalent, "source:equivalent", SourceAuthority.STRUCTURED_AGGREGATOR, "terms@1"
    )["source_policy"]
    class QualifiedReceiptAuthorityFixture:
        def authorize(
            self, artifact_id: str, provider_id: str, adapter_version: str,
            source_policy_identity: str, dataset: str,
            adapter_code_identity: str, transport_identity: str,
        ) -> None:
            assert artifact_id == receipt_id
            assert provider_id == "equivalent"
            assert adapter_version == "fixture@1"
            assert source_policy_identity == equivalent_policy.identity
            assert dataset in {"trade_cal", "market_universe", "daily"}
            assert adapter_code_identity == equivalent.code_identity
            assert transport_identity == equivalent.transport_identity

    root = PlatformTaskFixture(
        tmp_path,
        provider=primary,
        query_policy=primary_composition["query_policy"],
        qualified_equivalent_authority=QualifiedReceiptAuthorityFixture(),
        source_policy=primary_policy,
        qualified_equivalents=(
            QualifiedEquivalentBinding(receipt_id, equivalent, equivalent_policy),
        ),
        fixture_rights={
            **_rights("primary", "source:primary"),
            **_rights("equivalent", "source:equivalent"),
        },
    )
    for stable_id, code in (("security_yihua", "002897"), ("security_old", "000001")):
        root.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    result = root.data.sync(_request("qualified-fallback"))
    assert result.status is SyncStatus.COMPLETE_WITH_SUBSTITUTION
    assert result.disposition.substitution_receipt_ids == (receipt_id,)
    attempts = SQLiteOwningAdapterFixture(root.data_root).execute(
        "SELECT provider_id,status FROM provider_attempt ORDER BY attempt_id"
    ).fetchall()
    assert sum(row[0] == "primary" and row[1] != "complete" for row in attempts) == 3

    assert sum(row[0] == "equivalent" and row[1] == "complete" for row in attempts) == 3
    root.close()
def test_unallowed_equivalent_failure_stops_before_next_candidate(tmp_path: Path) -> None:
    class AccessDeniedFixture(FixtureProvider):
        def fetch(self, request):
            batch = super().fetch(request)
            return replace(
                batch,
                envelopes=tuple(
                    replace(envelope, status=FetchStatus.FAILED, error_code="ACCESS_FORBIDDEN")
                    for envelope in batch.envelopes
                ),
            )

    primary = FixtureProvider("primary", "fixture@1", {}, "source:primary", "terms@1", SourceAuthority.STRUCTURED_AGGREGATOR)
    denied = AccessDeniedFixture("denied", "fixture@1", {}, "source:denied", "terms@1", SourceAuthority.STRUCTURED_AGGREGATOR)
    unused = FixtureProvider("unused", "fixture@1", _payloads(), "source:unused", "terms@1", SourceAuthority.STRUCTURED_AGGREGATOR)
    primary_composition = _composition(primary, "source:primary", SourceAuthority.STRUCTURED_AGGREGATOR, "terms@1")
    receipt_ids = ("artifact_denied_equivalent", "artifact_unused_equivalent")
    primary_policy = replace(
        primary_composition["source_policy"],
        routes=tuple(
            SourceRoute(
                dataset, 1, CompletenessRequirement.REQUIRED, 1,
                FallbackMode.QUALIFIED_EQUIVALENT, SourceFailureDisposition.BLOCK,
                receipt_ids, ("FIXTURE_DATASET_MISSING",),
            )
            for dataset in ("trade_cal", "market_universe", "daily")
        ),
    )
    denied_policy = _composition(denied, "source:denied", SourceAuthority.STRUCTURED_AGGREGATOR, "terms@1")["source_policy"]
    unused_policy = _composition(unused, "source:unused", SourceAuthority.STRUCTURED_AGGREGATOR, "terms@1")["source_policy"]

    class AuthorityFixture:
        def authorize(self, *_args) -> None:
            return

    root = PlatformTaskFixture(
        tmp_path,
        provider=primary,
        query_policy=primary_composition["query_policy"],
        source_policy=primary_policy,
        qualified_equivalents=(
            QualifiedEquivalentBinding(receipt_ids[0], denied, denied_policy),
            QualifiedEquivalentBinding(receipt_ids[1], unused, unused_policy),
        ),
        qualified_equivalent_authority=AuthorityFixture(),
        fixture_rights={
            **_rights("primary", "source:primary"),
            **_rights("denied", "source:denied"),
            **_rights("unused", "source:unused"),
        },
    )
    result = root.data.sync(_request("equivalent-hard-stop"))
    providers = {
        row[0] for row in SQLiteOwningAdapterFixture(root.data_root).execute(
            "SELECT DISTINCT provider_id FROM provider_attempt"
        )
    }
    assert result.snapshot_id is None
    assert providers == {"primary", "denied"}
    root.close()


def test_route_freshness_budget_blocks_snapshot_beyond_declared_limit(tmp_path: Path) -> None:
    provider = FixtureProvider("fixture", "fixture@1", _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    composition = _composition(provider)
    policy = replace(
        composition["source_policy"],
        routes=tuple(replace(route, freshness_max_stale_days=0) for route in composition["source_policy"].routes),
    )
    root = PlatformTaskFixture(tmp_path, provider=provider, query_policy=composition["query_policy"], source_policy=policy, fixture_rights=_rights("fixture"))
    result = root.data.sync(_request("stale-policy", requested_date="2026-07-12"))
    assert result.status is SyncStatus.BLOCKED
    assert result.snapshot_id is None and result.freshness is FreshnessStatus.STALE
    assert result.stale_by_days == 1
    root.close()


def test_identical_content_resyncs_under_rotated_policy_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = root.data.sync(_request("policy-era-one"))
    assert first.status is SyncStatus.COMPLETE and first.snapshot_id is not None
    root.close()

    # Rotate only the source-policy identity (rights review-date bump) while
    # the provider, authority, and byte-identical content stay the same.
    provider = FixtureProvider("fixture", "fixture@1", _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    composition = _composition(provider)
    rotated_policy = replace(
        composition["source_policy"],
        rights=replace(composition["source_policy"].rights, reviewed_on="2026-07-13"),
    )
    assert rotated_policy.identity != composition["source_policy"].identity
    reopened = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=composition["query_policy"],
        source_policy=rotated_policy,
        fixture_rights=_rights("fixture"),
    )
    second = reopened.data.sync(_request("policy-era-two"))
    assert second.status is SyncStatus.COMPLETE and second.snapshot_id is not None
    assert second.disposition.normalized_created > 0
    connection = SQLiteOwningAdapterFixture(reopened.data_root)
    assert connection.execute(
        "SELECT count(*) FROM data_quality_issue WHERE code IN ('IDENTITY_OR_PERSISTENCE_CONFLICT','SOURCE_POLICY_IDENTITY_UNMIGRATABLE')"
    ).fetchone()[0] == 0
    member_policies = {
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT v.source_policy_identity "
            "FROM data_snapshot_member m "
            "JOIN normalized_version v USING(normalized_version_id) "
            "WHERE m.data_snapshot_id=?",
            (second.snapshot_id,),
        )
    }
    assert member_policies == {rotated_policy.identity}
    reopened.close()
