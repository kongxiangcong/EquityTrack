from __future__ import annotations

import json
import re
import secrets
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from trading_platform.application import (
    ChartAnnotations,
    ChartWorkspace,
    DecisionWorkspace,
    TradePlan,
    UpdateAuthorizations,
    WorkspaceUpdateCommand,
)
from trading_platform.chart import AnnotationError
from trading_platform.domain.chart import AnnotationAnchor, AnnotationLifecycleCommand
from trading_platform.domain.plans import ConfirmPlanDraftCommand
from trading_platform.plans import PlanError


class LocalChartWorkspaceServer:
    def __init__(
        self,
        *,
        decision_workspace: DecisionWorkspace,
        chart_workspace: ChartWorkspace,
        chart_annotations: ChartAnnotations,
        trade_plan: TradePlan,
        update_authorizations: UpdateAuthorizations,
        web_root: Path,
        security_id: str,
        snapshot_id: str,
    ) -> None:
        self.decision_workspace = decision_workspace
        self.chart_workspace = chart_workspace
        self.chart_annotations = chart_annotations
        self.trade_plan = trade_plan
        self.update_authorizations = update_authorizations
        self.web_root = web_root.resolve()
        self.security_id = security_id
        self.snapshot_id = snapshot_id
        self.csrf_token = secrets.token_urlsafe(32)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if not self._host_allowed():
                    return self.send_error(421)
                path = urlparse(self.path).path
                if path == "/api/chart-series":
                    self._json(
                        asdict(
                            owner.chart_workspace.get_series(
                                owner.security_id, owner.snapshot_id
                            )
                        )
                    )
                elif path == "/api/annotations":
                    self._json(
                        [
                            asdict(item)
                            for item in owner.chart_annotations.list_history(
                                owner.security_id
                            )
                        ]
                    )
                elif path == "/api/workspace":
                    self._json(
                        owner.decision_workspace.build(
                            owner.security_id, owner.snapshot_id
                        )
                    )
                else:
                    relative = "index.html" if path == "/" else path.lstrip("/")
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
                            f'<head><meta name="csrf-token" content="{owner.csrf_token}">'.encode(),
                        )
                    media = (
                        "text/html"
                        if target.suffix == ".html"
                        else (
                            "text/css"
                            if target.suffix == ".css"
                            else (
                                "text/javascript"
                                if target.suffix == ".js"
                                else "text/plain"
                            )
                        )
                    )
                    self.send_response(200)
                    self._security_headers()
                    self.send_header("Content-Type", media)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

            def do_POST(self) -> None:
                expected_origin = f"http://127.0.0.1:{owner._server.server_port}"
                invocation_id = self.headers.get("X-Invocation-Id", "")
                path = urlparse(self.path).path
                if (
                    not self._host_allowed()
                    or self.headers.get("Origin") != expected_origin
                    or path
                    not in {
                        "/api/annotations",
                        "/api/update-authorizations",
                        "/api/plan-confirmations",
                    }
                    or self.headers.get("X-CSRF-Token") != owner.csrf_token
                    or self.headers.get_content_type() != "application/json"
                ):
                    return self.send_error(403)
                if not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", invocation_id):
                    return self.send_error(400)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self.send_error(400)
                if length <= 0 or length > 32_768:
                    return self.send_error(413)
                try:
                    payload = json.loads(self.rfile.read(length))
                    if path == "/api/update-authorizations":
                        requested = str(payload["requested_date"])
                        effective = str(payload["effective_session_date"])
                        if not re.fullmatch(
                            r"\d{4}-\d{2}-\d{2}", requested
                        ) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective):
                            return self.send_error(400)
                        try:
                            authorization = owner.update_authorizations.authorize(
                                WorkspaceUpdateCommand(
                                    invocation_id,
                                    owner.security_id,
                                    requested,
                                    effective,
                                )
                            )
                        except ValueError as error:
                            return self._json({"error_code": str(error)}, 409)
                        return self._json(authorization, 201)
                    if path == "/api/plan-confirmations":
                        try:
                            confirmed = owner.trade_plan.confirm_draft(
                                ConfirmPlanDraftCommand(
                                    invocation_id,
                                    str(payload["draft_id"]),
                                    int(payload["expected_revision"]),
                                    str(
                                        payload.get(
                                            "activation_intent", "keep_inactive"
                                        )
                                    ),
                                )
                            )
                        except PlanError as error:
                            return self._json({"error_code": error.code}, 422)
                        except (KeyError, TypeError, ValueError):
                            return self.send_error(400)
                        return self._json(asdict(confirmed), 201)
                    operation = payload.get("operation", "create")
                    if operation not in {"create", "revise", "delete", "restore"}:
                        return self.send_error(400)
                    anchors = tuple(
                        AnnotationAnchor(
                            item["market_timestamp"], item["exact_price_decimal"]
                        )
                        for item in payload.get("anchors", ())
                    )
                    version = owner.chart_annotations.apply(
                        AnnotationLifecycleCommand(
                            invocation_id=invocation_id,
                            operation=operation,
                            security_id=owner.security_id,
                            data_snapshot_id=owner.snapshot_id,
                            author_id="local-user",
                            annotation_id=payload.get("annotation_id"),
                            expected_version_no=int(
                                payload.get("expected_version_no", 0)
                            ),
                            kind=payload.get("kind"),
                            style=payload.get("style"),
                            anchors=anchors,
                        )
                    )
                except AnnotationError as error:
                    if error.code == "ANNOTATION_NOT_FOUND":
                        return self.send_error(404)
                    return self._json({"error_code": error.code}, 422)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    return self.send_error(400)
                self._json(asdict(version), 201)

            def _json(self, value: object, status: int = 200) -> None:
                payload = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":")
                ).encode()
                self.send_response(status)
                self._security_headers()
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _host_allowed(self) -> bool:
                port = owner._server.server_port
                return self.headers.get("Host") in {
                    f"127.0.0.1:{port}",
                    f"localhost:{port}",
                }

            def _security_headers(self) -> None:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
                )
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header(
                    "Permissions-Policy",
                    "camera=(), microphone=(), geolocation=(), payment=()",
                )

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}"

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
