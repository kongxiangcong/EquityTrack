from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.platform.test_plan_change_proposals import _proposal_authority
from trading_platform.application import (
    open_application_commands,
    open_read_models,
)
from trading_platform.web_server import LocalChartWorkspaceServer


class Cdp:
    def __init__(self, url: str) -> None:
        self.socket = websocket.create_connection(
            url, timeout=10, origin="http://127.0.0.1"
        )
        self.next_id = 1
        self.events: list[dict[str, Any]] = []

    def call(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        identifier = self.next_id
        self.next_id += 1
        self.socket.send(
            json.dumps(
                {
                    "id": identifier,
                    "method": method,
                    "params": params or {},
                }
            )
        )
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            self.events.append(message)

    def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 10) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = self.evaluate(expression)
            if value:
                return value
            time.sleep(0.1)
        raise TimeoutError(expression)

    def close(self) -> None:
        self.socket.close()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _chrome_path() -> Path:
    candidates = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("CHROMIUM_BROWSER_NOT_FOUND")


def _connect(port: int) -> Cdp:
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            request = Request(
                f"http://127.0.0.1:{port}/json/new?about:blank",
                method="PUT",
            )
            page = json.loads(urlopen(request, timeout=1).read())
            return Cdp(page["webSocketDebuggerUrl"])
        except (
            URLError,
            TimeoutError,
            KeyError,
            websocket.WebSocketException,
        ):
            time.sleep(0.2)
    raise RuntimeError("CHROMIUM_CDP_UNAVAILABLE")


def _navigate(cdp: Cdp, url: str) -> None:
    cdp.call("Page.navigate", {"url": url})
    cdp.wait_for("document.readyState === 'complete'")
    cdp.wait_for(
        "document.querySelector('#load-status')?.dataset.state === 'ready'"
    )


def _server(
    stack: ExitStack, data_root: Path
) -> tuple[LocalChartWorkspaceServer, str]:
    server = LocalChartWorkspaceServer(
        read_models=stack.enter_context(open_read_models(data_root)),
        application_commands=stack.enter_context(
            open_application_commands(data_root)
        ),
        web_root=ROOT / "web" / "dist",
        account_id="account_local",
        security_id="security_600000",
    )
    base_url = server.start()
    stack.callback(server.close)
    return server, base_url


def _screenshot(cdp: Cdp, target: Path) -> dict[str, object]:
    encoded = cdp.call(
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": True},
    )["data"]
    payload = base64.b64decode(encoded)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "name": target.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _page(cdp: Cdp, page: str) -> None:
    cdp.evaluate(
        f"document.querySelector('[data-page=\"{page}\"]').click()"
    )
    cdp.wait_for(
        f"!document.querySelector('#page-{page}').hidden"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-artifacts", action="store_true")
    parser.add_argument("--evidence-file", type=Path)
    args = parser.parse_args()
    temp_root = Path(tempfile.mkdtemp(prefix="tdk-browser-"))
    data_root, _, _ = _proposal_authority(
        temp_root, "production-browser"
    )
    evidence_file = (
        args.evidence_file.resolve()
        if args.evidence_file is not None
        else temp_root / "browser-cdp.json"
    )
    screenshot_root = evidence_file.parent / "browser-cdp-screenshots"
    server_stack = ExitStack()
    _, base_url = _server(server_stack, data_root)
    port = _free_port()
    browser = subprocess.Popen(
        [
            str(_chrome_path()),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--metrics-recording-only",
            "--remote-allow-origins=http://127.0.0.1",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={temp_root / 'profile'}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cdp: Cdp | None = None
    restarted_stack: ExitStack | None = None
    try:
        cdp = _connect(port)
        browser_version = cdp.call("Browser.getVersion")
        for domain in ("Runtime", "Page", "Log", "Network"):
            cdp.call(f"{domain}.enable")
        _navigate(cdp, base_url)

        initial = json.loads(
            cdp.evaluate(
                """JSON.stringify({
                  navigation:[...document.querySelectorAll('.primary-nav [data-page]')].map(x=>x.textContent.trim()),
                  homeGroups:['account-summary','task-summary','change-summary','plan-summary','exception-summary'].filter(id=>document.getElementById(id)),
                  external:[...performance.getEntriesByType('resource')].map(x=>x.name).filter(x=>typeof x==='string'&&!x.startsWith(location.origin)),
                  unknownVisible:document.querySelector('#page-overview').textContent.includes('未知（未按零处理）'),
                  skipLink:Boolean(document.querySelector('.skip-link[href="#workspace-content"]')),
                  mainFocusable:document.querySelector('#workspace-content')?.tabIndex===-1,
                  oneH1:document.querySelectorAll('h1').length===1,
                  dialogLabels:[...document.querySelectorAll('dialog')].every(x=>Boolean(x.getAttribute('aria-labelledby')))
                })"""
            )
        )
        if (
            initial["navigation"] != ["总览", "组合", "复核", "研究"]
            or initial["homeGroups"]
            != [
                "account-summary",
                "task-summary",
                "change-summary",
                "plan-summary",
                "exception-summary",
            ]
            or initial["external"]
            or not all(
                initial[name]
                for name in (
                    "unknownVisible",
                    "skipLink",
                    "mainFocusable",
                    "oneH1",
                    "dialogLabels",
                )
            )
        ):
            raise AssertionError(initial)

        routes_and_headers = json.loads(
            cdp.evaluate(
                """(async()=>{
                  const current=await fetch('/api/read-models/portfolio@1');
                  const model=await current.json();
                  return JSON.stringify({
                    schema:model.schema_version,
                    homeKeys:Object.keys(model).filter(x=>!['schema_version','projection_id','source_ids','generated_at','content_hash'].includes(x)).sort(),
                    headers:{
                      csp:current.headers.get('content-security-policy'),
                      nosniff:current.headers.get('x-content-type-options'),
                      referrer:current.headers.get('referrer-policy'),
                      opener:current.headers.get('cross-origin-opener-policy')
                    }
                  });
                })()""",
                await_promise=True,
            )
        )
        retired_routes = (
            "/api/workspace",
            "/daily",
            "/api/daily",
            "/api/chart-series",
            "/api/annotations",
            "/api/update-authorizations",
        )
        retired_status: dict[str, int] = {}
        for route in retired_routes:
            try:
                urlopen(base_url + route)
            except HTTPError as error:
                retired_status[route] = error.code
            else:
                retired_status[route] = 200
        routes_and_headers["retired"] = retired_status
        expected_home = sorted(
            [
                "account_state_summary",
                "unresolved_decision_tasks",
                "material_changes_since_last_review",
                "holding_active_plan_summaries",
                "discipline_exception_summary",
            ]
        )
        if (
            routes_and_headers["schema"]
            != "PortfolioWorkspaceView@1"
            or routes_and_headers["homeKeys"] != expected_home
            or set(routes_and_headers["retired"].values()) != {404}
            or "default-src 'self'"
            not in routes_and_headers["headers"]["csp"]
            or routes_and_headers["headers"]["nosniff"] != "nosniff"
            or routes_and_headers["headers"]["referrer"] != "no-referrer"
            or routes_and_headers["headers"]["opener"] != "same-origin"
        ):
            raise AssertionError(routes_and_headers)

        screenshots: dict[str, dict[str, object]] = {}
        screenshots["overview"] = _screenshot(
            cdp, screenshot_root / "overview.png"
        )
        for page in ("portfolio", "review", "research"):
            _page(cdp, page)
            if page == "review":
                review_rendering = cdp.evaluate(
                    "!document.querySelector('#page-review').textContent.includes('undefined') && document.querySelector('#page-review').textContent.includes('impact_assessment_')"
                )
                if not review_rendering:
                    raise AssertionError(
                        cdp.evaluate(
                            "document.querySelector('#page-review').textContent"
                        )
                    )
            screenshots[page] = _screenshot(
                cdp, screenshot_root / f"{page}.png"
            )

        _page(cdp, "overview")
        cdp.evaluate(
            "document.querySelector('#plan-summary button').click()"
        )
        cdp.wait_for("document.querySelector('#plan-dialog').open")
        try:
            cdp.wait_for(
                "Boolean(document.querySelector('#plan-detail-content details'))"
            )
        except TimeoutError as error:
            state = cdp.evaluate(
                "document.querySelector('#plan-detail-content').textContent"
            )
            raise RuntimeError(state) from error
        plan_disclosure = json.loads(
            cdp.evaluate(
                """JSON.stringify({
                  open:document.querySelector('#plan-dialog').open,
                  rules:document.querySelector('#plan-detail-content').textContent.includes('HardRule / ReviewRule'),
                  diagnosticsClosed:!document.querySelector('#plan-detail-content details').open
                })"""
            )
        )
        if not all(plan_disclosure.values()):
            raise AssertionError(plan_disclosure)
        cdp.evaluate("document.querySelector('#plan-dialog').close()")

        cdp.evaluate(
            "document.querySelector('#open-account-editor').click()"
        )
        cdp.wait_for("document.querySelector('#account-dialog').open")
        cdp.evaluate(
            """document.querySelector('[name="as_of_at"]').value='2026-07-27';
               document.querySelector('#account-form').requestSubmit()"""
        )
        cdp.wait_for(
            "document.querySelector('#account-form-status').textContent.includes('通过校验')"
        )
        cdp.evaluate("document.querySelector('#confirm-draft').click()")
        cdp.wait_for(
            "document.querySelector('#account-form-status').textContent.includes('已由用户明确确认')"
        )
        editor = json.loads(
            cdp.evaluate(
                """JSON.stringify({
                  draftSaved:document.querySelector('#account-form-status').textContent.includes('已由用户明确确认'),
                  confirmDisabled:document.querySelector('#confirm-draft').disabled,
                  summary:document.querySelector('#account-editor-summary').textContent,
                  detailsClosed:!document.querySelector('#account-dialog details').open
                })"""
            )
        )
        if (
            not editor["draftSaved"]
            or not editor["confirmDisabled"]
            or "已确认 v2" not in editor["summary"]
            or not editor["detailsClosed"]
        ):
            raise AssertionError(editor)
        cdp.evaluate("document.querySelector('#account-dialog').close()")

        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 620,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        responsive = cdp.evaluate(
            "matchMedia('(max-width: 720px)').matches && getComputedStyle(document.querySelector('.primary-nav')).gridTemplateColumns.split(' ').length===2"
        )
        cdp.call(
            "Emulation.setEmulatedMedia",
            {
                "features": [
                    {
                        "name": "prefers-reduced-motion",
                        "value": "reduce",
                    }
                ]
            },
        )
        reduced_motion = cdp.evaluate(
            "matchMedia('(prefers-reduced-motion: reduce)').matches && parseFloat(getComputedStyle(document.querySelector('.primary-nav button')).transitionDuration||'0')<=0.001"
        )
        if not responsive or not reduced_motion:
            raise AssertionError((responsive, reduced_motion))

        server_stack.close()
        restarted_stack = ExitStack()
        _, restarted_url = _server(restarted_stack, data_root)
        _navigate(cdp, restarted_url)
        cdp.evaluate(
            "document.querySelector('#open-account-editor').click()"
        )
        cdp.wait_for("document.querySelector('#account-dialog').open")
        restart_state = cdp.evaluate(
            "document.querySelector('#account-editor-summary').textContent"
        )
        if "已确认 v2" not in restart_state:
            raise AssertionError(restart_state)

        cdp.call("Runtime.evaluate", {"expression": "void 0"})
        console_errors = [
            event
            for event in cdp.events
            if event.get("method") == "Runtime.exceptionThrown"
            or (
                event.get("method") == "Log.entryAdded"
                and event.get("params", {})
                .get("entry", {})
                .get("level")
                == "error"
            )
        ]
        network_failures = [
            event
            for event in cdp.events
            if event.get("method") == "Network.loadingFailed"
            and not event.get("params", {}).get("canceled")
        ]
        if console_errors or network_failures:
            raise AssertionError(
                {
                    "console_errors": console_errors,
                    "network_failures": network_failures,
                }
            )

        result = {
            "schema_version": "BrowserAcceptanceEvidence@1",
            "verifier": {
                "identity": "production-browser-cdp@1",
                "source_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "command_identity": hashlib.sha256(
                    json.dumps(
                        [
                            "python",
                            "scripts/verify_issue05_browser.py",
                            "--evidence-file",
                            "<redacted>",
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            },
            "browser": {
                "product": browser_version.get("product"),
                "protocol_version": browser_version.get(
                    "protocolVersion"
                ),
            },
            "status": "passed",
            "initial": initial,
            "routes_and_headers": routes_and_headers,
            "screenshots": screenshots,
            "plan_progressive_disclosure": plan_disclosure,
            "account_editor": editor,
            "responsive": responsive,
            "reduced_motion": reduced_motion,
            "restart_state": restart_state,
            "console_errors": console_errors,
            "network_failures": network_failures,
        }
        rendered = json.dumps(
            result, ensure_ascii=False, sort_keys=True
        )
        evidence_file.parent.mkdir(parents=True, exist_ok=True)
        evidence_file.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    finally:
        if cdp is not None:
            cdp.close()
        browser.terminate()
        browser.wait(timeout=10)
        if restarted_stack is not None:
            restarted_stack.close()
        server_stack.close()
        if not args.keep_artifacts:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
