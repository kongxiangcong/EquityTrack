from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from trading_platform.application import (
    open_browser_acceptance_fixture,
    open_decision_workspace,
    open_platform_operations,
)
from trading_platform.domain.chart import (
    AnnotationDraft,
    AnnotationLifecycleCommand,
    AnnotationVersion,
    ChartBar,
    ChartSeries,
)
from trading_platform.web_server import LocalChartWorkspaceServer
from trading_platform.application.browser_acceptance import BrowserAcceptanceFixture


class _DecisionWorkspace:
    def build(self, security_id: str, snapshot_id: str) -> dict[str, object]:
        return {"task": {"security_id": security_id, "snapshot_id": snapshot_id}}


class _ChartWorkspace:
    def get_series(self, security_id: str, snapshot_id: str) -> ChartSeries:
        return ChartSeries(
            security_id,
            "1d",
            "none",
            snapshot_id,
            None,
            "2026-07-10",
            "valid",
            (ChartBar("2026-07-10T15:00:00+08:00", "80", "84", "79", "82", "1"),),
        )


class _ChartAnnotations:
    def __init__(self) -> None:
        self.commands: list[AnnotationLifecycleCommand] = []

    def apply(self, command: AnnotationLifecycleCommand) -> AnnotationVersion:
        self.commands.append(command)
        draft = AnnotationDraft(
            command.security_id,
            "1d",
            "none",
            command.data_snapshot_id,
            None,
            command.kind or "horizontal_line",
            command.style or "accent",
            command.author_id,
            command.anchors,
        )
        return AnnotationVersion(
            "annotation_fixture",
            "annotation_version_fixture",
            1,
            None,
            "active",
            draft,
            "2026-07-10T00:00:00+00:00",
            "fixture-hash",
        )

    def list_history(self, security_id: str) -> tuple[AnnotationVersion, ...]:
        del security_id
        return ()


class _UpdateAuthorizations:
    pass


def test_web_annotation_route_invokes_one_typed_lifecycle_task(
    tmp_path: Path,
) -> None:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
    annotations = _ChartAnnotations()
    server = LocalChartWorkspaceServer(
        decision_workspace=_DecisionWorkspace(),
        chart_workspace=_ChartWorkspace(),
        chart_annotations=annotations,
        update_authorizations=_UpdateAuthorizations(),
        web_root=web_root,
        security_id="security_yihua",
        snapshot_id="snapshot_chart",
    )
    base = server.start()
    try:
        html = urlopen(base).read().decode("utf-8")
        token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
        payload = json.dumps(
            {
                "kind": "horizontal_line",
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
                "X-Invocation-Id": "web:create",
            },
        )
        created = json.loads(urlopen(request).read())
    finally:
        server.close()

    assert created["version_no"] == 1
    assert len(annotations.commands) == 1
    assert annotations.commands[0].operation == "create"


def test_public_browser_fixture_prepares_decision_journey(
    tmp_path: Path,
) -> None:
    open_platform_operations(tmp_path).bootstrap()
    fixture_manifest = (
        Path(__file__).parents[1] / "fixtures" / "platform_data" / "manifest.json"
    )
    with open_browser_acceptance_fixture(
        tmp_path,
        fixture_manifest,
        Path(__file__).parents[2],
    ) as fixture:
        prepared = fixture.prepare()

    with open_decision_workspace(tmp_path) as workspace:
        projected = workspace.build(prepared.security_id, prepared.snapshot_id)

    assert projected["research_views"][0]["schema_version"] == "ResearchDecisionView@2"
    assert projected["research_views"][0]["workflow_run_id"] == prepared.workflow_run_id
    assert projected["plan_drafts"] == []


def test_browser_fixture_has_no_caller_authored_research_artifact_surface() -> None:
    assert not hasattr(BrowserAcceptanceFixture, "analysis_artifacts")
