from __future__ import annotations

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture

from dataclasses import replace
from pathlib import Path
import json
from urllib.request import Request, urlopen

import pytest

from tests.platform.application_task_fixture import (
    PlatformTaskFixture,
    TEST_CHART_QUERY_POLICY,
    TEST_QUERY_POLICY,
    TEST_SOURCE_POLICY,
)
from trading_platform.application.contracts import SecurityIdentity
from trading_platform.chart import AnnotationError
from trading_platform.domain.chart import (
    AnnotationAnchor,
    AnnotationCommand,
    AnnotationDraft,
    AnnotationLink,
    CoordinateMigration,
)
from tests.platform.test_data_sync_pit import (
    _request as sync_request,
    _root as sync_root,
)
from trading_platform.web_server import LocalChartWorkspaceServer

ROOT = Path(__file__).resolve().parents[2]


def _root(path: Path) -> PlatformTaskFixture:
    root = PlatformTaskFixture(path)
    root.watchlist.add(
        "watch:yihua",
        SecurityIdentity("security_yihua", "SZSE", "002897", "CNY", "2017-09-07"),
    )
    connection = SQLiteOwningAdapterFixture(root.data_root)
    if (
        connection.execute(
            "SELECT count(*) FROM data_snapshot WHERE data_snapshot_id='snapshot_chart'"
        ).fetchone()[0]
        == 0
    ):
        with connection.transaction():
            connection.execute(
                "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "attempt_chart",
                    "chart-fixture",
                    "fixture",
                    "fixture@1",
                    "daily",
                    "derived-fact-fixture",
                    "fixture",
                    "urn:test:chart",
                    "{}",
                    "{}",
                    "timestamp",
                    "test-terms",
                    "complete",
                    "created",
                    None,
                    "2026-07-10T09:00:00+00:00",
                    None,
                    None,
                    None,
                    "not_applicable",
                    TEST_QUERY_POLICY.identity,
                    TEST_SOURCE_POLICY.identity,
                    "rights_test_fixture",
                ),
            )
            connection.execute(
                "INSERT INTO normalized_record VALUES(?,?,?)",
                ("record_chart", "daily", "security_yihua:2026-07-10"),
            )
            connection.execute(
                "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "version_chart",
                    "record_chart",
                    1,
                    "chart-content",
                    "attempt_chart",
                    "2026-07-10",
                    "2026-07-10T08:00:00+00:00",
                    "timestamp",
                    "2026-07-10T08:00:00+00:00",
                    "publisher_timestamp",
                    "2026-07-10T09:00:00+00:00",
                    "pass",
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO ohlcv_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "version_chart",
                    "security_yihua",
                    "2026-07-10",
                    "Asia/Shanghai",
                    "none",
                    "88.51",
                    "91.00",
                    "82.33",
                    "82.33",
                    "221879.03",
                    "hand",
                    "1926373.75544",
                    "thousand_cny",
                    "CNY",
                ),
            )
            connection.execute(
                "INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "snapshot_chart",
                    "security_yihua",
                    "chart",
                    "2026-07-11",
                    "2026-07-10",
                    "2026-07-11T00:00:00+00:00",
                    "Asia/Shanghai",
                    "cn-calendar@2026",
                    TEST_CHART_QUERY_POLICY.identity,
                    TEST_SOURCE_POLICY.identity,
                    "freshness@1",
                    "chart-members",
                    "valid",
                    "pass",
                    1,
                    1,
                    0,
                    0,
                    1,
                    "effective_complete_session",
                    "2026-07-10T09:00:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
                ("snapshot_chart", "version_chart", "daily", 0),
            )
    return root


def _draft(price: str = "82.3300") -> AnnotationDraft:
    return AnnotationDraft(
        "security_yihua",
        "1d",
        "none",
        "snapshot_chart",
        None,
        "horizontal_line",
        "accent",
        "local-user",
        (AnnotationAnchor("2026-07-10T15:00:00+08:00", price),),
        (AnnotationLink("ResearchRun", "rr_fixture", "unresolved_external"),),
    )


def test_chart_query_exposes_versioned_unadjusted_series_and_freshness(
    tmp_path: Path,
) -> None:
    root = sync_root(tmp_path)
    snapshot = root.data.sync(sync_request())
    series = root.chart.get_series("security_yihua", snapshot.snapshot_id)
    assert series.adjustment_mode == "none" and series.factor_snapshot_id is None
    assert (
        series.data_snapshot_id == snapshot.snapshot_id
        and series.effective_session_date == "2026-07-10"
    )
    assert series.freshness == "valid" and [
        bar.close_decimal for bar in series.bars
    ] == ["82.33"]
    with pytest.raises(AnnotationError, match="CHART_MAPPING_UNAVAILABLE"):
        root.chart.get_series("security_yihua", snapshot.snapshot_id, "1w")
    root.close()


def test_annotation_append_only_lifecycle_idempotency_and_restart(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    v1 = root.chart.create(AnnotationCommand("annotation:create", None, 0, _draft()))
    assert (
        root.chart.create(AnnotationCommand("annotation:create", None, 0, _draft()))
        == v1
    )
    equivalent = replace(
        _draft("82.33"), anchors=(AnnotationAnchor("2026-07-10T07:00:00Z", "82.33"),)
    )
    assert (
        root.chart.create(AnnotationCommand("annotation:create", None, 0, equivalent))
        == v1
    )
    v2 = root.chart.revise(
        AnnotationCommand("annotation:revise", v1.annotation_id, 1, _draft("83.1250"))
    )
    v3 = root.chart.delete(AnnotationCommand("annotation:delete", v1.annotation_id, 2))
    v4 = root.chart.restore(
        AnnotationCommand("annotation:restore", v1.annotation_id, 3)
    )
    assert (
        root.chart.revise(
            AnnotationCommand(
                "annotation:revise", v1.annotation_id, 1, _draft("83.1250")
            )
        )
        == v2
    )
    with pytest.raises(AnnotationError, match="INVOCATION_CONFLICT"):
        root.chart.delete(AnnotationCommand("annotation:revise", v1.annotation_id, 4))
    assert [item.status for item in root.chart.get_history(v1.annotation_id)] == [
        "active",
        "active",
        "deleted",
        "active",
    ]
    assert [item.version_no for item in root.chart.get_history(v1.annotation_id)] == [
        1,
        2,
        3,
        4,
    ]
    assert (
        v2.supersedes_version_id == v1.annotation_version_id
        and v4.draft.anchors[0].exact_price_decimal == "83.1250"
    )
    with pytest.raises(Exception, match="ANNOTATION_HISTORY_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute(
            "DELETE FROM chart_annotation_version WHERE annotation_version_id=?",
            (v1.annotation_version_id,),
        )
    with pytest.raises(Exception, match="ANNOTATION_IDENTITY_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute(
            "UPDATE chart_annotation SET security_id='other' WHERE annotation_id=?",
            (v1.annotation_id,),
        )
    with pytest.raises(Exception, match="ANNOTATION_IDENTITY_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute(
            "DELETE FROM chart_annotation WHERE annotation_id=?", (v1.annotation_id,)
        )
    with pytest.raises(Exception, match="ANNOTATION_HISTORY_IMMUTABLE"):
        SQLiteOwningAdapterFixture(root.data_root).execute(
            "INSERT INTO chart_annotation_anchor VALUES(?,?,?,?)",
            (v1.annotation_version_id, 7, "2026-07-10T15:00:00+08:00", "90"),
        )
    with pytest.raises(Exception, match="ANNOTATION_LINEAGE_INVALID"):
        SQLiteOwningAdapterFixture(root.data_root).execute(
            "INSERT INTO chart_annotation_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "invalid_lineage",
                v1.annotation_id,
                5,
                v1.annotation_version_id,
                "active",
                "1d",
                "none",
                "snapshot_chart",
                None,
                "horizontal_line",
                "accent",
                "local-user",
                "2026-07-10T00:00:00Z",
                "invalid",
            ),
        )
    root.close()

    rebuilt = _root(tmp_path)
    restored = rebuilt.chart.get_history(v1.annotation_id)
    assert restored[-1] == v4
    assert (
        restored[0].draft.interval == "1d"
        and restored[0].draft.adjustment_mode == "none"
    )
    assert (
        restored[0].draft.data_snapshot_id == "snapshot_chart"
        and restored[0].draft.links[0].link_id == "rr_fixture"
    )
    rebuilt.close()


def test_concurrency_validation_and_coordinate_migration_fail_closed(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    v1 = root.chart.create(AnnotationCommand("annotation:create", None, 0, _draft()))
    with pytest.raises(AnnotationError, match="ANNOTATION_VERSION_CONFLICT"):
        root.chart.revise(
            AnnotationCommand("annotation:stale", v1.annotation_id, 0, _draft("90"))
        )
    with pytest.raises(AnnotationError):
        root.chart.revise(
            AnnotationCommand(
                "annotation:frame-change",
                v1.annotation_id,
                1,
                replace(_draft("90"), interval="1w"),
            )
        )
    with pytest.raises(AnnotationError, match="ANNOTATION_NON_TRADING_ANCHOR"):
        root.chart.revise(
            AnnotationCommand(
                "annotation:non-trading",
                v1.annotation_id,
                1,
                replace(
                    _draft("90"),
                    anchors=(AnnotationAnchor("2026-07-11T15:00:00+08:00", "90"),),
                ),
            )
        )
    with pytest.raises(AnnotationError):
        root.chart.revise(
            AnnotationCommand(
                "annotation:cross-security",
                v1.annotation_id,
                1,
                replace(_draft("90"), security_id="security_other"),
            )
        )
    unresolved = root.chart.migrate(
        CoordinateMigration(
            "annotation:migrate-bad",
            v1.annotation_id,
            1,
            "1w",
            "none",
            "snapshot_chart",
            None,
            {},
        )
    )
    assert unresolved.status == "unresolved_requires_confirmation"
    assert root.chart.get_history(v1.annotation_id) == (v1,)
    cross_period = root.chart.migrate(
        CoordinateMigration(
            "annotation:migrate",
            v1.annotation_id,
            1,
            "1w",
            "none",
            "snapshot_chart",
            None,
            {
                "2026-07-10T15:00:00+08:00": AnnotationAnchor(
                    "2026-07-06T00:00:00+08:00", "82.3300"
                )
            },
        )
    )
    assert cross_period.status == "unresolved_requires_confirmation"
    assert root.chart.get_history(v1.annotation_id) == (v1,)
    altered = root.chart.migrate(
        CoordinateMigration(
            "annotation:migrate-altered",
            v1.annotation_id,
            1,
            "1d",
            "none",
            "snapshot_chart",
            None,
            {
                "2026-07-10T15:00:00+08:00": AnnotationAnchor(
                    "2026-07-10T15:00:00+08:00", "99.00"
                )
            },
        )
    )
    assert (
        altered.status == "unresolved_requires_confirmation"
        and root.chart.get_history(v1.annotation_id) == (v1,)
    )
    root.close()


def test_local_workspace_http_reload_and_server_restart_restore_sqlite_state(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    server = LocalChartWorkspaceServer(
        decision_workspace=root.workspace,
        chart_workspace=root.chart,
        chart_annotations=root.chart,
        update_authorizations=root.update_authorizations,
        web_root=ROOT / "web/dist",
        security_id="security_yihua",
        snapshot_id="snapshot_chart",
    )
    base = server.start()
    html = urlopen(base).read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    assert "版本化 K 线工作台" in html
    payload = json.dumps(
        {
            "kind": "trend_line",
            "style": "accent",
            "anchors": [
                {
                    "market_timestamp": "2026-07-10T15:00:00+08:00",
                    "exact_price_decimal": "82.3300",
                }
            ],
        }
    ).encode()
    request = Request(
        base + "/api/annotations",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Origin": base,
            "X-CSRF-Token": token,
            "X-Invocation-Id": "browser:create",
        },
    )
    created = json.loads(urlopen(request).read())
    assert created["version_no"] == 1

    def command(invocation: str, body: dict[str, object]) -> dict[str, object]:
        encoded = json.dumps(body).encode()
        call = Request(
            base + "/api/annotations",
            data=encoded,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Origin": base,
                "X-CSRF-Token": token,
                "X-Invocation-Id": invocation,
            },
        )
        return json.loads(urlopen(call).read())

    revised = command(
        "browser:revise",
        {
            "operation": "revise",
            "annotation_id": created["annotation_id"],
            "expected_version_no": 1,
            "kind": "trend_line",
            "style": "warning",
            "anchors": [
                {
                    "market_timestamp": "2026-07-10T15:00:00+08:00",
                    "exact_price_decimal": "83.1250",
                }
            ],
        },
    )
    deleted = command(
        "browser:delete",
        {
            "operation": "delete",
            "annotation_id": created["annotation_id"],
            "expected_version_no": 2,
        },
    )
    restored_version = command(
        "browser:restore",
        {
            "operation": "restore",
            "annotation_id": created["annotation_id"],
            "expected_version_no": 3,
        },
    )
    assert [
        revised["version_no"],
        deleted["version_no"],
        restored_version["version_no"],
    ] == [2, 3, 4]
    assert len(json.loads(urlopen(base + "/api/annotations").read())) == 4
    server.close()
    root.close()

    rebuilt = _root(tmp_path)
    restarted = LocalChartWorkspaceServer(
        decision_workspace=rebuilt.workspace,
        chart_workspace=rebuilt.chart,
        chart_annotations=rebuilt.chart,
        update_authorizations=rebuilt.update_authorizations,
        web_root=ROOT / "web/dist",
        security_id="security_yihua",
        snapshot_id="snapshot_chart",
    )
    second_base = restarted.start()
    restored = json.loads(urlopen(second_base + "/api/annotations").read())
    assert (
        restored[-1]["annotation_id"] == created["annotation_id"]
        and restored[-1]["draft"]["anchors"][0]["exact_price_decimal"] == "83.1250"
    )
    restarted.close()
    rebuilt.close()


@pytest.mark.parametrize(
    "draft",
    [
        replace(_draft(), kind="pixel"),
        replace(_draft(), adjustment_mode="mystery"),
        replace(
            _draft(), adjustment_mode="forward", factor_snapshot_id="snapshot_chart"
        ),
        replace(_draft(), anchors=(AnnotationAnchor("not-a-market-time", "82"),)),
        replace(_draft(), anchors=(AnnotationAnchor("garbageTvalue", "82"),)),
        replace(
            _draft(), anchors=(AnnotationAnchor("2026-07-10T15:00:00+08:00", "NaN"),)
        ),
        replace(
            _draft(),
            anchors=(AnnotationAnchor("2026-07-10T15:00:00+08:00", "1e100000000"),),
        ),
        replace(
            _draft(),
            anchors=(
                AnnotationAnchor("2026-07-10T15:00:00+08:00", "123456789012345678901"),
            ),
        ),
    ],
)
def test_annotation_rejects_library_private_or_invalid_domain_state(
    tmp_path: Path, draft: AnnotationDraft
) -> None:
    root = _root(tmp_path)
    with pytest.raises(AnnotationError):
        root.chart.create(
            AnnotationCommand(
                "invalid:"
                + draft.kind
                + draft.adjustment_mode
                + draft.anchors[0].market_timestamp,
                None,
                0,
                draft,
            )
        )
    assert (
        SQLiteOwningAdapterFixture(root.data_root).execute(
            "SELECT count(*) FROM chart_annotation_version"
        ).fetchone()[0]
        == 0
    )
    root.close()
