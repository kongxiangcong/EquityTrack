from __future__ import annotations

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.application.contracts import Capability, CapabilityStatus, HealthQuery, SecurityIdentity
from trading_platform.data.providers import FixtureProvider, HttpJsonProvider, TransportResponse, TushareCompatibleProvider
from trading_platform.domain.data import DistributionQualification, FetchBatch, FetchRequest, FetchStatus, FixtureRights, FreshnessStatus, QualityStatus, RawEnvelope, SnapshotPurpose, SourceAuthority, SyncRequest, SyncStatus


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
    return SyncRequest(invocation, "security_yihua", "002897.SZ", requested_date, datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc), "Asia/Shanghai", "SZSE", SnapshotPurpose.WORKFLOW, ("trade_cal", "market_universe", "daily"), False, offline)


def _root(tmp_path: Path, payloads: dict[str, bytes] | None = None) -> PlatformTaskFixture:
    provider = FixtureProvider("fixture", "fixture@1", payloads or _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    root = PlatformTaskFixture(tmp_path, providers=(provider,), fixture_rights=_rights("fixture"))
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
    rights = connection.execute("SELECT repository_redistribution_allowed,packaged_distribution_allowed FROM fixture_rights_profile").fetchall()
    assert rights and all(tuple(row) == (1, 1) for row in rights)
    root.close()


def test_startup_and_unauthorized_http_provider_make_no_network_call(tmp_path: Path) -> None:
    calls: list[object] = []
    provider = HttpJsonProvider("gateway", "http@1", "https://invalid.example", "secret", "compatible-gateway-not-official", "unknown-terms", lambda request: calls.append(request) or b"{}")
    root = PlatformTaskFixture(tmp_path, providers=(provider,))
    assert calls == []
    result = root.data.sync(_request())
    assert calls == []
    assert result.status == "missing"
    attempt = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT source_identity,error_code,raw_sha256 FROM provider_attempt").fetchone()
    assert tuple(attempt) == ("compatible-gateway-not-official", "NETWORK_NOT_AUTHORIZED", None)
    root.close()


def test_offline_valid_stale_missing_and_coverage_missing_fail_closed(tmp_path: Path) -> None:
    empty_provider = FixtureProvider("fixture", "fixture@1", _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    empty = PlatformTaskFixture(tmp_path / "empty", providers=(empty_provider,), fixture_rights=_rights("fixture"))
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
    root = PlatformTaskFixture(repo_root / "data", providers=(provider,), fixture_rights=rights)
    result = root.data.sync(_request())
    assert result.status is SyncStatus.MISSING
    assert result.distribution_qualification is DistributionQualification.EXTERNAL_BLOCKED
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM object_blob").fetchone()[0] == 0
    errors = {row[0] for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT error_code FROM provider_attempt")}
    assert errors == {"PRIVATE_FIXTURE_IN_GIT_WORKTREE"}
    root.close()


def test_same_authority_source_conflict_blocks_new_revision_and_cursor(tmp_path: Path) -> None:
    first_provider = FixtureProvider("p1", "fixture@1", _payloads("82.33"), "source:p1", "terms@1", SourceAuthority.STRUCTURED_AGGREGATOR)
    first = PlatformTaskFixture(tmp_path, providers=(first_provider,), fixture_rights=_rights("p1", "source:p1"))
    for stable_id, code in (("security_yihua", "002897"), ("security_old", "000001")):
        first.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    assert first.data.sync(_request()).status is SyncStatus.COMPLETE
    first.close()
    second_provider = FixtureProvider("p2", "fixture@1", _payloads("83.00"), "source:p2", "terms@1", SourceAuthority.STRUCTURED_AGGREGATOR)
    second = PlatformTaskFixture(tmp_path, providers=(second_provider,), fixture_rights=_rights("p2", "source:p2"))
    result = second.data.sync(_request("conflict"))
    assert result.status is SyncStatus.BLOCKED
    assert SQLiteOwningAdapterFixture(second.data_root).execute("SELECT count(*) FROM data_quality_issue WHERE code='SOURCE_CONFLICT'").fetchone()[0] >= 1
    assert SQLiteOwningAdapterFixture(second.data_root).execute("SELECT count(*) FROM sync_cursor WHERE provider_id='p2' AND dataset='daily'").fetchone()[0] == 0
    second.close()


def test_tushare_compatible_provider_uses_same_raw_normalize_quality_pit_path(tmp_path: Path) -> None:
    responses = {
        "trade_cal": {"data": {"fields": ["exchange", "cal_date", "is_open", "pretrade_date"], "items": [["SZSE", "20260711", 0, "20260710"], ["SZSE", "20260710", 1, "20260709"]]}},
        "daily": {"data": {"fields": ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"], "items": [["002897.SZ", "20260710", 88.51, 91.0, 82.33, 82.33, 88.55, -6.22, -7.0243, 221879.03, 1926373.75544]]}},
        "stock_basic": {"data": {"fields": ["ts_code", "symbol", "name", "market", "list_date"], "items": [["002897.SZ", "002897", "意华股份", "主板", "20170907"]]}},
    }
    calls: list[str] = []
    def transport(request):
        body = json.loads(request.data.decode("utf-8")); calls.append(body["api_name"])
        return TransportResponse(json.dumps(responses[body["api_name"]]).encode("utf-8"), {"Date": "Sun, 12 Jul 2026 04:27:47 GMT"})
    provider = TushareCompatibleProvider("gateway", "tushare-http@1", "https://compatible.invalid/", "not-logged-secret", "preconfigured_tushare_compatible_non_official", "gateway-terms-unknown", transport)
    root = PlatformTaskFixture(tmp_path, providers=(provider,))
    root.watchlist.add("watch:yihua", SecurityIdentity("security_yihua", "SZSE", "002897", "CNY", "2017-09-07"))
    result = root.data.sync(replace(_request("authorized-live"), network_authorized=True))
    assert result.status is SyncStatus.MISSING
    assert calls == ["trade_cal", "stock_basic", "daily"]
    row = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT open_decimal,close_decimal,volume_decimal,amount_decimal FROM ohlcv_version").fetchone()
    assert tuple(row) == ("88.51", "82.33", "221879.03", "1926373.75544")
    attempts_json = json.dumps([dict(row) for row in SQLiteOwningAdapterFixture(root.data_root).execute("SELECT * FROM provider_attempt")])
    assert "not-logged-secret" not in attempts_json
    assert "preconfigured_tushare_compatible_non_official" in attempts_json
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM data_snapshot_member").fetchone()[0] == 0
    root.close()


def test_fixture_manifest_separates_real_derived_facts_from_synthetic_sentinels() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures/platform_data/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["source_identity"] == "preconfigured_tushare_compatible_non_official"
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


class _FailureProvider:
    fixture = False

    def __init__(self, provider_id: str, status: FetchStatus, payload: bytes | None, error_code: str) -> None:
        self.provider_id = provider_id
        self.adapter_version = "failure@1"
        self.status = status
        self.payload = payload
        self.error_code = error_code
        self.endpoint = f"failure://{provider_id}"

    def fetch(self, request: FetchRequest) -> FetchBatch:
        import hashlib
        return FetchBatch((RawEnvelope(f"source:{self.provider_id}", SourceAuthority.SECONDARY, self.endpoint, {}, {}, "date", "test-terms", datetime(2026, 7, 11, tzinfo=timezone.utc), self.status, self.payload, hashlib.sha256(self.payload).hexdigest() if self.payload is not None else None, error_code=self.error_code),))


def test_empty_rate_limit_and_schema_drift_do_not_advance_cursor_and_fallback_attempts_remain(tmp_path: Path) -> None:
    empty = _FailureProvider("empty", FetchStatus.COMPLETE, _bytes([]), "EMPTY")
    limited = _FailureProvider("limited", FetchStatus.RATE_LIMITED, None, "RATE_LIMITED")
    fixture = FixtureProvider("fixture", "fixture@1", _payloads(), FIXTURE_SOURCE, "derived-fact-fixture-terms@1")
    root = PlatformTaskFixture(tmp_path, providers=(empty, limited, fixture), fixture_rights=_rights("fixture"))
    for stable_id, code in (("security_yihua", "002897"), ("security_old", "000001")):
        root.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    result = root.data.sync(_request())
    assert result.status is SyncStatus.COMPLETE
    attempts = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT provider_id,status,error_code FROM provider_attempt ORDER BY rowid").fetchall()
    assert any(tuple(row) == ("empty", "complete", "EMPTY") for row in attempts)
    assert any(tuple(row) == ("limited", "rate_limited", "RATE_LIMITED") for row in attempts)
    assert SQLiteOwningAdapterFixture(root.data_root).execute("SELECT count(*) FROM sync_cursor WHERE provider_id IN ('empty','limited')").fetchone()[0] == 0
    root.close()


def test_private_fixture_rights_are_preserved_without_upgrading_redistribution(tmp_path: Path) -> None:
    provider = FixtureProvider("private", "fixture@1", _payloads(), "local-private-fixture", "private-terms@1")
    rights = {("private", dataset): FixtureRights(f"private:{dataset}", "local-private-fixture", True, True, False, False, "private-terms@1", "2026-07-12") for dataset in ("trade_cal", "market_universe", "daily")}
    root = PlatformTaskFixture(tmp_path, providers=(provider,), fixture_rights=rights)
    for stable_id, code in (("security_yihua", "002897"), ("security_old", "000001")):
        root.watchlist.add(f"watch:{stable_id}", SecurityIdentity(stable_id, "SZSE", code, "CNY", "2010-01-01"))
    private_result = root.data.sync(_request())
    assert private_result.status is SyncStatus.COMPLETE
    assert private_result.distribution_qualification is DistributionQualification.EXTERNAL_BLOCKED
    recorded = SQLiteOwningAdapterFixture(root.data_root).execute("SELECT repository_redistribution_allowed,packaged_distribution_allowed FROM fixture_rights_profile").fetchall()
    assert recorded and all(tuple(row) == (0, 0) for row in recorded)
    root.close()
