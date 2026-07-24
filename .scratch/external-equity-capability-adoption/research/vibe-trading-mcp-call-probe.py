from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


UPSTREAM = Path(r"E:\workspace\tradingSystem-upstreams\Vibe-Trading")
EXECUTABLE = UPSTREAM / ".venv" / "Scripts" / "vibe-trading-mcp.exe"
RUNTIME_ROOT = UPSTREAM / ".venv" / "qualification-runtime"
PINNED_COMMIT = "0aa45a9ff3df58fab1c50f5400d9b112d19cacc6"


def environment() -> dict[str, str]:
    home = RUNTIME_ROOT / "home"
    temp = RUNTIME_ROOT / "temp"
    home.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "PATH": os.pathsep.join(
            [
                str(UPSTREAM / ".venv" / "Scripts"),
                str(Path(system_root) / "System32"),
                system_root,
            ]
        ),
        "USERPROFILE": str(home),
        "HOMEDRIVE": home.drive,
        "HOMEPATH": str(home)[len(home.drive) :],
        "TEMP": str(temp),
        "TMP": str(temp),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "VIBE_TRADING_ENABLE_SHELL_TOOLS": "0",
    }


def text_payload(result: Any) -> str:
    return "".join(
        content.text
        for content in result.content
        if getattr(content, "type", None) == "text"
    )


def summarize(name: str, result: Any) -> dict[str, Any]:
    text = text_payload(result)
    try:
        decoded = json.loads(text)
        json_valid = True
        top_level = sorted(decoded.keys()) if isinstance(decoded, dict) else None
    except json.JSONDecodeError:
        json_valid = False
        top_level = None
    return {
        "name": name,
        "is_error": bool(result.isError),
        "content_types": [content.type for content in result.content],
        "text_bytes": len(text.encode("utf-8")),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "json_valid": json_valid,
        "json_top_level_keys": top_level,
        "structured_content_present": result.structuredContent is not None,
    }


async def run() -> dict[str, Any]:
    params = StdioServerParameters(
        command=str(EXECUTABLE),
        args=["--transport", "stdio"],
        env=environment(),
        cwd=str(UPSTREAM),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await asyncio.wait_for(session.initialize(), timeout=120)
            args = {
                "spot": 100.0,
                "strike": 100.0,
                "expiry_days": 365,
                "risk_free_rate": 0.0,
                "volatility": 0.2,
                "option_type": "call",
            }
            first = await asyncio.wait_for(
                session.call_tool("analyze_options", args), timeout=30
            )
            second = await asyncio.wait_for(
                session.call_tool("analyze_options", args), timeout=30
            )
            missing = RUNTIME_ROOT / "home" / ".vibe-trading" / "runs" / "missing"
            missing_result = await asyncio.wait_for(
                session.call_tool("backtest", {"run_dir": str(missing)}), timeout=30
            )
            invalid_args = await asyncio.wait_for(
                session.call_tool("backtest", {}), timeout=30
            )
            absent_tool = await asyncio.wait_for(
                session.call_tool("walk_forward", {}), timeout=30
            )

            summaries = [
                summarize("analyze_options_first", first),
                summarize("analyze_options_second", second),
                summarize("backtest_missing_run", missing_result),
                summarize("backtest_invalid_arguments", invalid_args),
                summarize("absent_walk_forward_tool", absent_tool),
            ]
            return {
                "suite": "vibe-trading-mcp-restricted-tools-call",
                "pinned_commit": PINNED_COMMIT,
                "server": {
                    "name": initialized.serverInfo.name,
                    "version": initialized.serverInfo.version,
                    "protocol_version": initialized.protocolVersion,
                },
                "calls": summaries,
                "same_input_same_text_hash": (
                    summaries[0]["text_sha256"] == summaries[1]["text_sha256"]
                ),
                "allowlist_executed": ["analyze_options", "backtest"],
                "network_provider_calls_executed": [],
                "forbidden_tools_executed": [],
            }


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
