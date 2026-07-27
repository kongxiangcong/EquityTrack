from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from urllib.request import urlopen

from trading_platform.application import (
    open_application_commands,
    open_browser_acceptance_fixture,
    open_read_models,
    open_platform_operations,
)
from tests.platform.test_plan_change_proposals import _proposal_authority
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
    assert portfolio["schema_version"] == "PortfolioWorkspaceView@1"
    assert set(portfolio) >= {
        "projection_id",
        "source_ids",
        "generated_at",
        "content_hash",
    }
    assert holding["schema_version"] == "HoldingWorkspaceView@1"


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

    assert projected.schema_version == "ResearchIndexView@1"
    assert projected.research_items[0]["research_run_id"]
    assert prepared.workflow_run_id in projected.source_ids


def test_browser_fixture_has_no_caller_authored_research_artifact_surface() -> None:
    assert not hasattr(BrowserAcceptanceFixture, "analysis_artifacts")
