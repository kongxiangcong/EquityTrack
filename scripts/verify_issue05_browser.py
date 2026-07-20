from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.platform.test_chart_annotations import _root
from trading_platform.web_server import LocalChartWorkspaceServer


class Cdp:
    def __init__(self, url: str) -> None:
        self.socket = websocket.create_connection(url, timeout=10, origin="http://127.0.0.1")
        self.next_id = 1
        self.events: list[dict[str, Any]] = []

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        identifier = self.next_id; self.next_id += 1
        self.socket.send(json.dumps({"id": identifier, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == identifier:
                if "error" in message: raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            self.events.append(message)

    def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": await_promise, "returnByValue": True, "userGesture": True})
        if result.get("exceptionDetails"): raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 10) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = self.evaluate(expression)
            if value: return value
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
        if candidate.is_file(): return candidate
    raise RuntimeError("CHROMIUM_BROWSER_NOT_FOUND")


def _connect(port: int) -> Cdp:
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            request = Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
            page = json.loads(urlopen(request, timeout=1).read())
            return Cdp(page["webSocketDebuggerUrl"])
        except (URLError, TimeoutError, KeyError, websocket.WebSocketException):
            time.sleep(0.2)
    raise RuntimeError("CHROMIUM_CDP_UNAVAILABLE")


def _navigate(cdp: Cdp, url: str) -> None:
    cdp.call("Page.navigate", {"url": url})
    cdp.wait_for("document.readyState === 'complete'")
    text = cdp.wait_for("document.querySelector('#banner')?.textContent")
    deadline = time.time() + 10
    while "正在读取" in text and time.time() < deadline:
        time.sleep(0.1); text = cdp.evaluate("document.querySelector('#banner')?.textContent")
    if "冻结快照已载入" not in text:
        raise RuntimeError(json.dumps({"banner": text, "events": cdp.events[-10:]}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()
    temp_root = Path(tempfile.mkdtemp(prefix="issue05-browser-"))
    root = _root(temp_root / "data")
    server = LocalChartWorkspaceServer(root.web, ROOT / "web/dist", "security_yihua", "snapshot_chart")
    base_url = server.start()
    port = _free_port()
    browser = subprocess.Popen([
        str(_chrome_path()), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-component-update", "--disable-sync", "--metrics-recording-only",
        "--remote-allow-origins=http://127.0.0.1", "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}", f"--user-data-dir={temp_root / 'profile'}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp: Cdp | None = None
    restarted: LocalChartWorkspaceServer | None = None
    rebuilt = None
    try:
        cdp = _connect(port)
        cdp.call("Runtime.enable"); cdp.call("Page.enable")
        _navigate(cdp, base_url)
        initial = cdp.evaluate("JSON.stringify({canvas:document.querySelectorAll('#chart canvas').length,ledger:document.querySelectorAll('#ledger li').length,external:[...performance.getEntriesByType('resource')].map(x=>x.name).filter(x=>typeof x==='string'&&!x.startsWith(location.origin))})")
        initial_state = json.loads(initial)
        if initial_state["canvas"] < 1 or initial_state["external"]: raise AssertionError(initial_state)

        focus_after_start = cdp.evaluate("document.querySelector('#start-price').value='82.3300';document.querySelector('#start').click();document.activeElement.id")
        focus_after_finish = cdp.evaluate("document.querySelector('#end-price').value='83.1250';document.querySelector('#finish').click();document.activeElement.id")
        if (focus_after_start, focus_after_finish) != ("end-price", "confirm"): raise AssertionError((focus_after_start, focus_after_finish))
        cdp.evaluate("window.__issue05Fetch=window.fetch;window.__issue05Drop=true;window.fetch=async(...args)=>{const response=await window.__issue05Fetch(...args);if(window.__issue05Drop&&String(args[1]?.method).toUpperCase()==='POST'){window.__issue05Drop=false;return{ok:response.ok,status:response.status,json:async()=>{throw new TypeError('simulated body loss')}}}return response}")
        cdp.evaluate("document.querySelector('#confirm').click()")
        cdp.wait_for("document.querySelector('#save-status')?.textContent.includes('提交结果未知')")
        cdp.wait_for("!document.querySelector('#confirm').disabled")
        ambiguous_replay = cdp.evaluate("!document.querySelector('#confirm').disabled")
        cdp.evaluate("document.querySelector('#confirm').click()")
        try:
            cdp.wait_for("document.querySelector('#save-status')?.textContent.includes('已持久化 v1')")
        except TimeoutError as error:
            state = cdp.evaluate("JSON.stringify({status:document.querySelector('#save-status')?.textContent,ledger:document.querySelector('#ledger')?.textContent,confirmDisabled:document.querySelector('#confirm')?.disabled})")
            raise RuntimeError(state) from error
        ambiguous_replay = ambiguous_replay and cdp.evaluate("document.querySelectorAll('#ledger li').length===1")
        if not ambiguous_replay: raise AssertionError("ambiguous command did not replay safely")
        created = cdp.evaluate("JSON.stringify({ledger:document.querySelectorAll('#ledger li').length,status:document.querySelector('#save-status').textContent})")
        cdp.evaluate("document.querySelector('#revise').click()")
        cdp.wait_for("document.querySelector('#save-status')?.textContent.includes('v2 修订')")
        cdp.evaluate("document.querySelector('#delete').click()")
        cdp.wait_for("document.querySelector('#save-status')?.textContent.includes('v3 删除')")
        cdp.evaluate("document.querySelector('#restore').click()")
        cdp.wait_for("document.querySelector('#save-status')?.textContent.includes('v4 恢复')")
        cdp.wait_for("document.querySelectorAll('#ledger li').length === 4")
        recoverable_error = cdp.evaluate("document.querySelector('#end-price').value='1e999';document.querySelector('#revise').click();true")
        cdp.wait_for("document.querySelector('#save-status')?.textContent.includes('保存失败')")
        recoverable_error = recoverable_error and cdp.evaluate("!document.querySelector('#revise').disabled && document.querySelectorAll('#ledger li').length===4")
        if not recoverable_error: raise AssertionError("mutation error was not recoverable")

        fullscreen = cdp.evaluate("const before=document.querySelectorAll('#ledger li').length;document.querySelector('#fullscreen').click();JSON.stringify({active:document.querySelector('.workspace').classList.contains('fullscreen'),sameLedger:before===document.querySelectorAll('#ledger li').length,canvas:document.querySelectorAll('#chart canvas').length})")
        if not all(json.loads(fullscreen).values()): raise AssertionError(fullscreen)

        cdp.call("Page.reload"); cdp.wait_for("document.readyState === 'complete'")
        cdp.wait_for("document.querySelectorAll('#ledger li').length === 4")
        after_reload = cdp.evaluate("document.querySelector('#ledger').textContent")
        if "83.1250" not in after_reload: raise AssertionError(after_reload)

        cdp.call("Emulation.setDeviceMetricsOverride", {"width": 800, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        responsive = cdp.evaluate("matchMedia('(max-width: 900px)').matches && getComputedStyle(document.querySelector('.workspace')).display === 'block'")
        cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        reduced_motion = cdp.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches && getComputedStyle(document.querySelector('#fullscreen')).transitionDuration === '0s'")
        if not responsive or not reduced_motion: raise AssertionError((responsive, reduced_motion))

        server.close(); root.close()
        rebuilt = _root(temp_root / "data")
        restarted = LocalChartWorkspaceServer(rebuilt.web, ROOT / "web/dist", "security_yihua", "snapshot_chart")
        restarted_url = restarted.start()
        _navigate(cdp, restarted_url)
        cdp.wait_for("document.querySelectorAll('#ledger li').length === 4")
        restart_state = cdp.evaluate("document.querySelector('#ledger').textContent")
        errors = [event for event in cdp.events if event.get("method") in {"Runtime.exceptionThrown", "Log.entryAdded"}]
        if errors: raise AssertionError(errors)
        print(json.dumps({"status": "passed", "initial": initial_state, "created": json.loads(created), "reload_ledger": after_reload, "restart_ledger": restart_state, "responsive": responsive, "reduced_motion": reduced_motion, "recoverable_error": recoverable_error, "ambiguous_replay": ambiguous_replay}, ensure_ascii=False, sort_keys=True))
    finally:
        if cdp is not None: cdp.close()
        browser.terminate(); browser.wait(timeout=10)
        if restarted is not None: restarted.close()
        if rebuilt is not None: rebuilt.close()
        else:
            server.close(); root.close()
        if not args.keep_artifacts: shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
