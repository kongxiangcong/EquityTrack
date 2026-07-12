from __future__ import annotations

import json
import re
import secrets
import threading
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from trading_platform.application.facade import ApplicationFacade
from trading_platform.domain.chart import AnnotationAnchor, AnnotationCommand, AnnotationDraft
from trading_platform.chart import AnnotationError
from trading_platform.domain.plans import ConfirmPlanDraftCommand
from trading_platform.plans import PlanError


class LocalChartWorkspaceServer:
    def __init__(self, facade: ApplicationFacade, web_root: Path, security_id: str, snapshot_id: str) -> None:
        self.facade = facade
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
                if not self._host_allowed(): return self.send_error(421)
                path = urlparse(self.path).path
                if path == "/api/chart-series":
                    self._json(asdict(owner.facade.get_chart_series(owner.security_id, owner.snapshot_id)))
                elif path == "/api/annotations":
                    self._json([asdict(item) for item in owner.facade.list_annotation_history(owner.security_id)])
                elif path == "/api/workspace":
                    self._json(owner.facade.get_workspace(owner.security_id, owner.snapshot_id))
                else:
                    relative = "index.html" if path == "/" else path.lstrip("/")
                    target = (owner.web_root / relative).resolve()
                    if owner.web_root not in target.parents and target != owner.web_root:
                        return self.send_error(404)
                    if not target.is_file(): return self.send_error(404)
                    payload = target.read_bytes()
                    if target.name == "index.html":
                        payload = payload.replace(b"<head>", f'<head><meta name="csrf-token" content="{owner.csrf_token}">'.encode())
                    media = "text/html" if target.suffix == ".html" else "text/css" if target.suffix == ".css" else "text/javascript"
                    self.send_response(200); self._security_headers(); self.send_header("Content-Type", media); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

            def do_POST(self) -> None:
                expected_origin = f"http://127.0.0.1:{owner._server.server_port}"
                invocation_id = self.headers.get("X-Invocation-Id", "")
                path = urlparse(self.path).path
                if not self._host_allowed() or self.headers.get("Origin") != expected_origin or path not in {"/api/annotations", "/api/update-authorizations", "/api/plan-confirmations"} or self.headers.get("X-CSRF-Token") != owner.csrf_token or self.headers.get_content_type() != "application/json":
                    return self.send_error(403)
                if not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", invocation_id): return self.send_error(400)
                try: length = int(self.headers.get("Content-Length", "0"))
                except ValueError: return self.send_error(400)
                if length <= 0 or length > 32_768: return self.send_error(413)
                try:
                    payload = json.loads(self.rfile.read(length))
                    if path == "/api/update-authorizations":
                        requested = str(payload["requested_date"]); effective = str(payload["effective_session_date"])
                        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective): return self.send_error(400)
                        try: authorization = owner.facade.authorize_workspace_update(invocation_id, owner.security_id, requested, effective)
                        except ValueError as error: return self._json({"error_code": str(error)}, 409)
                        return self._json(authorization, 201)
                    if path == "/api/plan-confirmations":
                        try:
                            confirmed = owner.facade.confirm_plan_draft(ConfirmPlanDraftCommand(invocation_id, str(payload["draft_id"]), int(payload["expected_revision"]), str(payload.get("activation_intent", "keep_inactive"))))
                        except (KeyError, TypeError, ValueError): return self.send_error(400)
                        except PlanError as error: return self._json({"error_code": error.code}, 422)
                        return self._json(asdict(confirmed), 201)
                    series = owner.facade.get_chart_series(owner.security_id, owner.snapshot_id)
                    operation = payload.get("operation", "create")
                    if operation == "create":
                        draft = AnnotationDraft(owner.security_id, series.interval, series.adjustment_mode, series.data_snapshot_id, series.factor_snapshot_id, payload["kind"], payload["style"], "local-user", tuple(AnnotationAnchor(item["market_timestamp"], item["exact_price_decimal"]) for item in payload["anchors"]))
                        version = owner.facade.create_annotation(AnnotationCommand(invocation_id, None, 0, draft))
                    else:
                        annotation_id = payload["annotation_id"]; expected_version = int(payload["expected_version_no"])
                        history = owner.facade.get_annotation_history(annotation_id)
                        if not history or history[-1].draft.security_id != owner.security_id: return self.send_error(404)
                        if operation == "revise":
                            anchors = tuple(AnnotationAnchor(item["market_timestamp"], item["exact_price_decimal"]) for item in payload["anchors"])
                            draft = replace(history[-1].draft, kind=payload["kind"], style=payload["style"], anchors=anchors)
                            version = owner.facade.revise_annotation(AnnotationCommand(invocation_id, annotation_id, expected_version, draft))
                        elif operation == "delete": version = owner.facade.delete_annotation(AnnotationCommand(invocation_id, annotation_id, expected_version))
                        elif operation == "restore": version = owner.facade.restore_annotation(AnnotationCommand(invocation_id, annotation_id, expected_version))
                        else: return self.send_error(400)
                except (json.JSONDecodeError, KeyError, TypeError): return self.send_error(400)
                except AnnotationError as error: return self._json({"error_code": error.code}, 422)
                self._json(asdict(version), 201)

            def _json(self, value: object, status: int = 200) -> None:
                payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                self.send_response(status); self._security_headers(); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

            def _host_allowed(self) -> bool:
                port = owner._server.server_port
                return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

            def _security_headers(self) -> None:
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True); self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}"

    def close(self) -> None:
        if self._server is not None: self._server.shutdown(); self._server.server_close()
        if self._thread is not None: self._thread.join(timeout=5)
