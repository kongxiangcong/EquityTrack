from __future__ import annotations

import json
import mimetypes
import secrets
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trading_platform.application.command_envelope import (
    ApplicationCommandEnvelopeV1,
    CommandEnvelopeError,
    InteractionChannel,
)
from trading_platform.application.commands import ApplicationCommandDispatcher
from trading_platform.application.read_model_codecs import encode_read_model
from trading_platform.application.web_command_policy import (
    WebCommandPolicy,
    WebCommandPolicyError,
)
from trading_platform.application.read_models import (
    ReadModelError,
    ReadModelService,
)


class LocalChartWorkspaceServer:
    """Serve the local discipline workspace through application task seams."""

    def __init__(
        self,
        *,
        read_models: ReadModelService,
        application_commands: ApplicationCommandDispatcher,
        web_root: Path,
        account_id: str,
        security_id: str,
    ) -> None:
        self.read_models = read_models
        self.application_commands = application_commands
        self.web_root = web_root.resolve()
        self.account_id = account_id
        self.security_id = security_id
        self.csrf_token = secrets.token_urlsafe(32)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            _READ_ROUTES = {
                "/api/read-models/portfolio@1",
                "/api/read-models/holding@1",
                "/api/read-models/trade-plan-detail@1",
                "/api/read-models/review@1",
                "/api/read-models/research-index@1",
                "/api/read-models/account-snapshot-editor@1",
                "/api/read-models/chart-workspace@1",
            }

            def do_GET(self) -> None:
                if not self._host_allowed():
                    return self.send_error(421)
                parsed = urlparse(self.path)
                if parsed.path in self._READ_ROUTES:
                    return self._read_model(parsed.path, parse_qs(parsed.query))
                relative = (
                    "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
                )
                target = (owner.web_root / relative).resolve()
                if (
                    owner.web_root not in target.parents
                    and target != owner.web_root
                ):
                    return self.send_error(404)
                if not target.is_file():
                    return self.send_error(404)
                payload = target.read_bytes()
                if target.name == "index.html":
                    payload = payload.replace(
                        b"<head>",
                        (
                            '<head><meta name="csrf-token" '
                            f'content="{owner.csrf_token}">'
                        ).encode(),
                        1,
                    )
                media = mimetypes.guess_type(target.name)[0] or (
                    "application/octet-stream"
                )
                self.send_response(200)
                self._security_headers()
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                expected_origin = (
                    f"http://127.0.0.1:{owner._server.server_port}"
                )
                parsed = urlparse(self.path)
                if (
                    not self._host_allowed()
                    or self.headers.get("Origin") != expected_origin
                    or parsed.path != "/api/application-commands"
                    or self.headers.get("X-CSRF-Token") != owner.csrf_token
                    or self.headers.get_content_type() != "application/json"
                ):
                    return self.send_error(403)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self.send_error(400)
                if length <= 0 or length > 65_536:
                    return self.send_error(413)
                encoded = self.rfile.read(length)
                try:
                    envelope = ApplicationCommandEnvelopeV1.from_bytes(encoded)
                except CommandEnvelopeError as error:
                    return self._json(
                        {
                            "schema_version": "ApplicationCommandFailure@1",
                            "status": "failed",
                            "code": error.code,
                        },
                        400,
                    )
                try:
                    WebCommandPolicy().authorize(envelope)
                except WebCommandPolicyError as error:
                    return self._json(
                        {
                            "schema_version": "ApplicationCommandFailure@1",
                            "status": "failed",
                            "code": error.code,
                        },
                        403,
                    )
                result = owner.application_commands.dispatch(envelope)
                status = 201 if result.status == "succeeded" else 422
                return self._json(asdict(result), status)

            def _read_model(
                self, path: str, query: dict[str, list[str]]
            ) -> None:
                generated_at = datetime.now(timezone.utc).isoformat()
                try:
                    if path == "/api/read-models/portfolio@1":
                        self._require_no_query(query)
                        view = owner.read_models.portfolio(
                            owner.account_id, generated_at
                        )
                    elif path == "/api/read-models/holding@1":
                        self._require_keys(query, {"security_id"})
                        selected_security = self._single(
                            query, "security_id", optional=True
                        )
                        view = owner.read_models.holding(
                            owner.account_id,
                            selected_security or owner.security_id,
                            generated_at,
                        )
                    elif path == "/api/read-models/review@1":
                        self._require_keys(query, {"review_run_id"})
                        view = owner.read_models.review(
                            owner.account_id,
                            generated_at,
                            self._single(query, "review_run_id", optional=True),
                        )
                    elif path == "/api/read-models/research-index@1":
                        self._require_no_query(query)
                        view = owner.read_models.research_index(
                            generated_at, owner.security_id
                        )
                    elif path == "/api/read-models/chart-workspace@1":
                        self._require_keys(query, {"snapshot_id"})
                        view = owner.read_models.chart_workspace(
                            owner.security_id,
                            generated_at,
                            self._single(
                                query, "snapshot_id", optional=True
                            ),
                        )
                    elif path == (
                        "/api/read-models/account-snapshot-editor@1"
                    ):
                        self._require_no_query(query)
                        view = owner.read_models.account_editor(
                            owner.account_id, generated_at
                        )
                    elif path == (
                        "/api/read-models/trade-plan-detail@1"
                    ):
                        self._require_keys(query, {"plan_id"})
                        plan_id = self._single(query, "plan_id")
                        view = owner.read_models.plan_detail(
                            plan_id, generated_at
                        )
                        identity = view.plan_identity
                        if identity["account_id"] != owner.account_id:
                            return self.send_error(404)
                    else:
                        return self.send_error(404)
                except (ReadModelError, ValueError, KeyError):
                    return self.send_error(404)
                self._encoded_json(encode_read_model(view))

            @staticmethod
            def _require_no_query(query: dict[str, list[str]]) -> None:
                if query:
                    raise ValueError("READ_MODEL_QUERY_NOT_ALLOWED")

            @staticmethod
            def _require_keys(
                query: dict[str, list[str]], allowed: set[str]
            ) -> None:
                if set(query) - allowed:
                    raise ValueError("READ_MODEL_QUERY_NOT_ALLOWED")

            @staticmethod
            def _single(
                query: dict[str, list[str]],
                key: str,
                *,
                optional: bool = False,
            ) -> str | None:
                values = query.get(key, [])
                if not values and optional:
                    return None
                if len(values) != 1 or not values[0]:
                    raise ValueError("READ_MODEL_QUERY_INVALID")
                return values[0]

            def _encoded_json(self, payload: bytes, status: int = 200) -> None:
                self.send_response(status)
                self._security_headers()
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _json(self, value: object, status: int = 200) -> None:
                payload = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                self._encoded_json(payload, status)

            def _host_allowed(self) -> bool:
                port = owner._server.server_port
                return self.headers.get("Host") in {
                    f"127.0.0.1:{port}",
                    f"localhost:{port}",
                }

            def _security_headers(self) -> None:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; "
                    "style-src 'self'; img-src 'self' data:; "
                    "connect-src 'self'; font-src 'self'; "
                    "object-src 'none'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'",
                )
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Cross-Origin-Opener-Policy", "same-origin"
                )
                self.send_header(
                    "Cross-Origin-Resource-Policy", "same-origin"
                )
                self.send_header(
                    "Permissions-Policy",
                    "camera=(), microphone=(), geolocation=(), payment=()",
                )

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}"

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
