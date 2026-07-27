from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tests.platform.test_chart_annotations import ROOT, _root
from trading_platform.web_server import LocalChartWorkspaceServer
from trading_platform.application import ApplicationCommandEnvelopeV1


def _server(tmp_path: Path):
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
    return root, server, server.start()


def test_workspace_security_headers_and_safe_history_projection(
    tmp_path: Path,
) -> None:
    root, server, base = _server(tmp_path)
    response = urlopen(base + "/api/workspace")
    payload = json.loads(response.read())
    assert response.headers["Content-Security-Policy"].startswith(
        "default-src 'self'"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert payload["task"]["security_id"] == "security_yihua"
    assert payload["history"]["annotations"] == []
    serialized = json.dumps(payload)
    assert str(tmp_path) not in serialized
    assert "csrf" not in serialized.lower()
    server.close()
    root.close()


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
    root, server, base = _server(tmp_path)
    request = Request(
        base + "/api/annotations", data=b"{}", method="POST", headers=headers
    )
    with pytest.raises(HTTPError) as rejected:
        urlopen(request)
    assert rejected.value.code in {403, 421}
    server.close()
    root.close()


def test_get_cannot_mutate_and_oversized_body_is_rejected(
    tmp_path: Path,
) -> None:
    root, server, base = _server(tmp_path)
    with pytest.raises(HTTPError) as get_mutation:
        urlopen(base + "/api/annotations/delete")
    assert get_mutation.value.code == 404
    html = urlopen(base).read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    request = Request(
        base + "/api/annotations",
        data=b"x" * 32769,
        method="POST",
        headers={
            "Origin": base,
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
            "X-Invocation-Id": "oversized",
        },
    )
    with pytest.raises(HTTPError) as oversized:
        urlopen(request)
    assert oversized.value.code == 413
    server.close()
    root.close()


def test_update_authorization_is_csrf_protected_immutable_and_replay_safe(
    tmp_path: Path,
) -> None:
    root, server, base = _server(tmp_path)
    html = urlopen(base).read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    body = json.dumps(
        {
            "requested_date": "2026-07-11",
            "effective_session_date": "2026-07-10",
        }
    ).encode()
    headers = {
        "Origin": base,
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
        "X-Invocation-Id": "browser:update-auth",
    }
    first = json.loads(
        urlopen(
            Request(
                base + "/api/update-authorizations",
                data=body,
                method="POST",
                headers=headers,
            )
        ).read()
    )
    replay = json.loads(
        urlopen(
            Request(
                base + "/api/update-authorizations",
                data=body,
                method="POST",
                headers=headers,
            )
        ).read()
    )
    assert replay["update_authorization_id"] == first["update_authorization_id"]
    server.close()
    root.close()


def test_script_shaped_annotation_and_path_inputs_cannot_execute_or_escape(
    tmp_path: Path,
) -> None:
    root, server, base = _server(tmp_path)
    html = urlopen(base).read().decode()
    token = html.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]
    attack = json.dumps(
        {
            "kind": "<script>alert(1)</script>",
            "style": "accent",
            "anchors": [
                {
                    "market_timestamp": "2026-07-10T15:00:00+08:00",
                    "exact_price_decimal": "82.33",
                }
            ],
        }
    ).encode()
    headers = {
        "Origin": base,
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
        "X-Invocation-Id": "browser:script-attack",
    }
    with pytest.raises(HTTPError) as rejected:
        urlopen(
            Request(
                base + "/api/annotations",
                data=attack,
                method="POST",
                headers=headers,
            )
        )
    assert rejected.value.code == 422
    with pytest.raises(HTTPError) as traversal:
        urlopen(base + "/..%2f..%2fAGENTS.md")
    assert traversal.value.code == 404
    assert "sandbox" in html
    assert "allow-scripts" not in html
    assert "allow-same-origin" not in html
    server.close()
    root.close()


def test_secret_and_personal_paths_never_reach_dom_logs_or_artifacts(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    marker = "sk-test-DO-NOT-LEAK-issue09"
    monkeypatch.setenv("OPENAI_API_KEY", marker)
    root, server, base = _server(tmp_path)
    html = urlopen(base).read()
    workspace = urlopen(base + "/api/workspace").read()
    artifact_payloads = b"".join(
        path.read_bytes()
        for path in (tmp_path / "objects").rglob("*")
        if path.is_file()
    )
    output = capsys.readouterr()
    combined = (
        html
        + workspace
        + artifact_payloads
        + output.out.encode()
        + output.err.encode()
    )
    assert marker.encode() not in combined
    assert str(tmp_path).encode() not in html + workspace
    request = Request(
        base + "/api/provider-destination",
        data=json.dumps({"url": "https://evil.example"}).encode(),
        method="POST",
        headers={"Origin": base, "Content-Type": "application/json"},
    )
    with pytest.raises(HTTPError) as blocked:
        urlopen(request)
    assert blocked.value.code == 403
    server.close()
    root.close()


def test_application_command_decode_failure_never_echoes_payload_secret() -> None:
    marker = "command-payload-secret-must-not-leak"
    with pytest.raises(ValueError) as caught:
        ApplicationCommandEnvelopeV1.from_bytes(
            json.dumps({"payload": {"credential": marker}}).encode()
        )
    assert marker not in str(caught.value)
