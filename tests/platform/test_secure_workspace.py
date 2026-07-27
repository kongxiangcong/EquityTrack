from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tests.platform.test_plan_change_proposals import _proposal_authority
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    open_application_commands,
    open_read_models,
)
from trading_platform.web_server import LocalChartWorkspaceServer


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def production_server(tmp_path: Path):
    data_root, _, _ = _proposal_authority(tmp_path, "secure-web")
    with ExitStack() as stack:
        reads = stack.enter_context(open_read_models(data_root))
        commands = stack.enter_context(open_application_commands(data_root))
        server = LocalChartWorkspaceServer(
            read_models=reads,
            application_commands=commands,
            web_root=ROOT / "web/dist",
            account_id="account_local",
            security_id="security_600000",
        )
        base = server.start()
        stack.callback(server.close)
        yield data_root, base


def _csrf(base: str) -> str:
    html = urlopen(base).read().decode()
    return html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]


def test_workspace_security_headers_and_safe_read_projection(
    tmp_path: Path,
) -> None:
    with production_server(tmp_path) as (_, base):
        response = urlopen(base + "/api/read-models/portfolio@1")
        payload = json.loads(response.read())
        assert response.headers["Content-Security-Policy"].startswith(
            "default-src 'self'"
        )
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert payload["schema_version"] == "PortfolioWorkspaceView@1"
        serialized = json.dumps(payload)
        assert str(tmp_path) not in serialized
        assert "csrf" not in serialized.lower()


@pytest.mark.parametrize(
    "path",
    [
        "/api/workspace",
        "/api/chart-series",
        "/api/annotations",
        "/api/update-authorizations",
        "/daily",
        "/api/daily",
    ],
)
def test_retired_public_routes_are_absent(
    tmp_path: Path, path: str
) -> None:
    with production_server(tmp_path) as (_, base):
        with pytest.raises(HTTPError) as missing:
            urlopen(base + path)
        assert missing.value.code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Origin": "http://evil.example", "Content-Type": "application/json"},
        {"Origin": "http://127.0.0.1:1", "Content-Type": "text/plain"},
    ],
)
def test_rejects_rebinding_cross_origin_and_wrong_content_type(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    with production_server(tmp_path) as (_, base):
        request = Request(
            base + "/api/application-commands",
            data=b"{}",
            method="POST",
            headers=headers,
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(request)
        assert rejected.value.code in {403, 421}


def test_get_cannot_mutate_and_oversized_body_is_rejected(
    tmp_path: Path,
) -> None:
    with production_server(tmp_path) as (_, base):
        with pytest.raises(HTTPError) as get_mutation:
            urlopen(base + "/api/application-commands")
        assert get_mutation.value.code == 404
        request = Request(
            base + "/api/application-commands",
            data=b"x" * 65_537,
            method="POST",
            headers={
                "Origin": base,
                "Content-Type": "application/json",
                "X-CSRF-Token": _csrf(base),
            },
        )
        with pytest.raises(HTTPError) as oversized:
            urlopen(request)
        assert oversized.value.code == 413


def test_non_user_or_non_account_web_command_is_denied(
    tmp_path: Path,
) -> None:
    with production_server(tmp_path) as (_, base):
        encoded = json.dumps(
            {
                "schema_version": "ApplicationCommandEnvelope@1",
                "command_name": "account_snapshot.confirm@1",
                "invocation_id": "web:agent-confirm-denied",
                "payload_schema_version": "ConfirmAccountSnapshot@1",
                "expected_revision": 1,
                "decision_actor": {
                    "actor_type": "agent",
                    "actor_id": "codex",
                },
                "interaction_channel": "web",
                "transport_actor": {
                    "actor_type": "adapter",
                    "actor_id": "web-local",
                },
                "approval": None,
                "payload": {"draft_id": "not-authorized"},
            }
        ).encode()
        request = Request(
            base + "/api/application-commands",
            data=encoded,
            method="POST",
            headers={
                "Origin": base,
                "Content-Type": "application/json",
                "X-CSRF-Token": _csrf(base),
            },
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)
        assert denied.value.code == 403
        assert json.loads(denied.value.read())["code"] == (
            "WEB_COMMAND_CAPABILITY_DENIED"
        )


def test_path_inputs_cannot_escape_static_root(tmp_path: Path) -> None:
    with production_server(tmp_path) as (_, base):
        with pytest.raises(HTTPError) as traversal:
            urlopen(base + "/..%2f..%2fAGENTS.md")
        assert traversal.value.code == 404


def test_secret_and_personal_paths_never_reach_dom_or_read_models(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    marker = "sk-test-DO-NOT-LEAK-ticket15"
    monkeypatch.setenv("OPENAI_API_KEY", marker)
    with production_server(tmp_path) as (_, base):
        html = urlopen(base).read()
        portfolio = urlopen(
            base + "/api/read-models/portfolio@1"
        ).read()
        output = capsys.readouterr()
        combined = (
            html
            + portfolio
            + output.out.encode()
            + output.err.encode()
        )
        assert marker.encode() not in combined
        assert str(tmp_path).encode() not in html + portfolio


def test_application_command_decode_failure_never_echoes_payload_secret() -> None:
    marker = "command-payload-secret-must-not-leak"
    with pytest.raises(ValueError) as caught:
        ApplicationCommandEnvelopeV1.from_bytes(
            json.dumps({"payload": {"credential": marker}}).encode()
        )
    assert marker not in str(caught.value)
