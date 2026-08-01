from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from urllib.request import Request, urlopen

from trading_platform.application import (
    open_application_commands,
    open_browser_acceptance_fixture,
    open_read_models,
    open_platform_operations,
)
from tests.platform.test_plan_change_proposals import _proposal_authority
from tests.platform.test_chart_annotations import _root as chart_root
from trading_platform.web_server import LocalChartWorkspaceServer
from trading_platform.application.browser_acceptance import BrowserAcceptanceFixture


def test_web_read_route_serializes_the_application_dto(
    tmp_path: Path,
) -> None:
    data_root, _, _ = _proposal_authority(tmp_path, "web-route")
    with ExitStack() as stack:
        reads = stack.enter_context(open_read_models(data_root))
        commands = stack.enter_context(open_application_commands(data_root))
        server = LocalChartWorkspaceServer(
            read_models=reads,
            application_commands=commands,
            web_root=Path(__file__).parents[2] / "web/dist",
            account_id="account_local",
            security_id="security_600000",
        )
        base = server.start()
        stack.callback(server.close)
        portfolio = json.loads(
            urlopen(base + "/api/read-models/portfolio@1").read()
        )
        holding = json.loads(
            urlopen(base + "/api/read-models/holding@1").read()
        )
        plan_id = portfolio["holding_active_plan_summaries"][0]["plan_id"]
        plan = json.loads(
            urlopen(
                base + "/api/read-models/trade-plan-detail@1?plan_id=" + plan_id
            ).read()
        )
        review = json.loads(
            urlopen(base + "/api/read-models/review@1").read()
        )
    assert portfolio["schema_version"] == "PortfolioWorkspaceView@1"
    assert set(portfolio) >= {
        "projection_id",
        "source_ids",
        "generated_at",
        "content_hash",
    }
    assert holding["schema_version"] == "HoldingWorkspaceView@1"
    assert portfolio["account_state_summary"]["positions"]
    assert "watchlist" in portfolio["account_state_summary"]
    assert set(plan) >= {
        "evidence_freshness",
        "rule_states",
        "related_tasks",
        "review_history",
        "change_diffs",
        "version_history",
    }
    assert "periodic_discipline_review" in review


def test_chart_workspace_read_and_annotation_command_survive_restart(
    tmp_path: Path,
) -> None:
    chart = chart_root(tmp_path)
    chart.close()

    def start(stack: ExitStack) -> tuple[LocalChartWorkspaceServer, str]:
        reads = stack.enter_context(open_read_models(tmp_path))
        commands = stack.enter_context(open_application_commands(tmp_path))
        server = LocalChartWorkspaceServer(
            read_models=reads,
            application_commands=commands,
            web_root=Path(__file__).parents[2] / "web/dist",
            account_id="account_chart",
            security_id="security_yihua",
        )
        base = server.start()
        stack.callback(server.close)
        return server, base

    with ExitStack() as stack:
        server, base = start(stack)
        initial = json.loads(
            urlopen(base + "/api/read-models/chart-workspace@1").read()
        )
        assert initial["schema_version"] == "ChartWorkspaceView@1"
        assert initial["bars"][0]["market_timestamp"] == (
            "2026-07-10T15:00:00+08:00"
        )
        envelope = {
            "schema_version": "ApplicationCommandEnvelope@1",
            "command_name": "chart_annotation.apply@1",
            "invocation_id": "web:chart:create:restart",
            "payload_schema_version": "ApplyChartAnnotation@1",
            "expected_revision": None,
            "decision_actor": {
                "actor_type": "user",
                "actor_id": "local-user",
            },
            "interaction_channel": "web",
            "transport_actor": {
                "actor_type": "adapter",
                "actor_id": "web-local",
            },
            "approval": None,
            "payload": {
                "operation": "create",
                "security_id": "security_yihua",
                "data_snapshot_id": "snapshot_chart",
                "annotation_id": None,
                "kind": "horizontal_line",
                "style": "accent",
                "anchors": [
                    {
                        "market_timestamp": "2026-07-10T15:00:00+08:00",
                        "exact_price_decimal": "82.33",
                    }
                ],
            },
        }
        request = Request(
            base + "/api/application-commands",
            data=json.dumps(envelope).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": base,
                "X-CSRF-Token": server.csrf_token,
            },
            method="POST",
        )
        result = json.loads(urlopen(request).read())
        assert result["status"] == "succeeded"
        refreshed = json.loads(
            urlopen(base + "/api/read-models/chart-workspace@1").read()
        )
        assert refreshed["annotations"][0]["anchors"] == [
            {
                "market_timestamp": "2026-07-10T15:00:00+08:00",
                "exact_price_decimal": "82.33",
            }
        ]

    with ExitStack() as restarted:
        _, base = start(restarted)
        restored = json.loads(
            urlopen(base + "/api/read-models/chart-workspace@1").read()
        )
        assert restored["annotations"] == refreshed["annotations"]
        assert restored["frame"] == refreshed["frame"]

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

    with open_read_models(tmp_path) as read_models:
        projected = read_models.research_index(
            "2026-07-27T18:30:00+08:00",
            prepared.security_id,
        )
        chart = read_models.chart_workspace(
            prepared.security_id,
            "2026-07-27T18:30:00+08:00",
        )

    assert projected.schema_version == "ResearchIndexView@1"
    assert chart.schema_version == "ChartWorkspaceView@1"
    assert chart.bars
    assert projected.research_items[0]["research_run_id"]
    assert prepared.workflow_run_id in projected.source_ids


def test_browser_fixture_has_no_caller_authored_research_artifact_surface() -> None:
    assert not hasattr(BrowserAcceptanceFixture, "analysis_artifacts")
