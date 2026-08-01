from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tests.platform.test_secure_workspace import production_server


ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "web/dist"


def _html(base: str) -> str:
    return urlopen(base).read().decode("utf-8")


def _csrf(html: str) -> str:
    return html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]


def _post(base: str, token: str, payload: dict[str, object]):
    return json.loads(
        urlopen(
            Request(
                base + "/api/application-commands",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={
                    "Origin": base,
                    "Content-Type": "application/json",
                    "X-CSRF-Token": token,
                },
            )
        ).read()
    )


def _envelope(
    command_name: str,
    payload_schema_version: str,
    invocation_id: str,
    payload: dict[str, object],
    expected_revision: int | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "ApplicationCommandEnvelope@1",
        "command_name": command_name,
        "invocation_id": invocation_id,
        "payload_schema_version": payload_schema_version,
        "expected_revision": expected_revision,
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
        "payload": payload,
    }


def test_navigation_home_allowlist_progressive_disclosure_and_accessibility(
    tmp_path: Path,
) -> None:
    with production_server(tmp_path) as (_, base):
        html = _html(base)
        portfolio = json.loads(
            urlopen(base + "/api/read-models/portfolio@1").read()
        )
    navigation = re.findall(
        r'<button type="button" data-page="[^"]+"[^>]*>([^<]+)</button>',
        html,
    )
    assert navigation == ["今日", "组合", "研究与计划", "周期复盘"]
    metadata = {
        "schema_version",
        "projection_id",
        "source_ids",
        "generated_at",
        "content_hash",
    }
    assert set(portfolio) - metadata == {
        "account_state_summary",
        "unresolved_decision_tasks",
        "material_changes_since_last_review",
        "holding_active_plan_summaries",
        "discipline_exception_summary",
    }
    for expected in (
        'class="skip-link"',
        '<main id="workspace-content" tabindex="-1">',
        'aria-label="一级导航"',
        'aria-labelledby="account-dialog-title"',
        "<details>",
        'id="account-form-status" role="status"',
    ):
        assert expected in html
    assert html.count("<h1>") == 1
    assert "<script>" not in html
    for forbidden in (
        "policy_identity",
        "model_identity",
        "manifest_id",
        "workflow_log",
        "readiness",
        "forecast_registry",
    ):
        assert forbidden not in html.lower()
        assert forbidden not in json.dumps(portfolio).lower()


def test_unversioned_workspace_and_public_daily_routes_are_absent(
    tmp_path: Path,
) -> None:
    retired = (
        "/api/workspace",
        "/daily",
        "/api/daily",
        "/api/chart-series",
        "/api/annotations",
        "/api/update-authorizations",
    )
    with production_server(tmp_path) as (_, base):
        for path in retired:
            with pytest.raises(HTTPError) as missing:
                urlopen(base + path)
            assert missing.value.code == 404
    active_sources = (
        (ROOT / "src/trading_platform/web_server.py").read_text(
            encoding="utf-8"
        )
        + (ROOT / "web/src/app.js").read_text(encoding="utf-8")
        + b"".join(
            path.read_bytes()
            for path in DIST.rglob("*")
            if path.is_file()
        ).decode("utf-8", errors="ignore")
    )
    for path in retired:
        assert path not in active_sources


def test_account_editor_uses_shared_envelope_and_requires_user_confirmation(
    tmp_path: Path,
) -> None:
    with production_server(tmp_path) as (_, base):
        html = _html(base)
        token = _csrf(html)
        editor = json.loads(
            urlopen(
                base
                + "/api/read-models/account-snapshot-editor@1"
            ).read()
        )
        confirmed = editor["confirmed_snapshot_summary"]
        draft = {
            "draft_id": "draft_web_acceptance",
            "account_id": "account_local",
            "revision": 1,
            "status": "open",
            "source_kind": "manual_web_entry",
            "redacted_source_ref": "web-acceptance",
            "as_of_at": "2026-07-27",
            "as_of_precision": "date",
            "timezone": "Asia/Shanghai",
            "session_semantics": "complete_session",
            "currency": "CNY",
            "cash_state": "unknown",
            "cash_value": None,
            "nav_state": "unknown",
            "nav_value": None,
            "fees_state": "unknown",
            "fees_value": None,
            "positions": confirmed["positions"],
            "previous_snapshot_version_id": confirmed[
                "account_snapshot_version_id"
            ],
            "revises_snapshot_version_id": None,
            "corrects_snapshot_version_id": None,
            "correction_reason": None,
        }
        created = _post(
            base,
            token,
            _envelope(
                "account_snapshot.create_draft@1",
                "CreateAccountSnapshotDraft@1",
                "web:acceptance:create-draft",
                {"draft": draft},
            ),
        )
        assert created["schema_version"] == "ApplicationCommandResult@1"
        assert created["result"]["validation_state"] == "valid"
        projected = json.loads(
            urlopen(
                base
                + "/api/read-models/account-snapshot-editor@1"
            ).read()
        )
        assert projected["current_draft"]["draft_id"] == draft["draft_id"]
        confirmed_result = _post(
            base,
            token,
            _envelope(
                "account_snapshot.confirm@1",
                "ConfirmAccountSnapshot@1",
                "web:acceptance:confirm-draft",
                {"draft_id": draft["draft_id"]},
                expected_revision=1,
            ),
        )
        assert confirmed_result["result_type"] == "AccountSnapshotVersion"
        rebuilt = json.loads(
            urlopen(
                base
                + "/api/read-models/account-snapshot-editor@1"
            ).read()
        )
        assert rebuilt["current_draft"] is None
        assert rebuilt["confirmed_snapshot_summary"]["version_no"] == (
            confirmed["version_no"] + 1
        )
