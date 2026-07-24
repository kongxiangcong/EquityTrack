from __future__ import annotations

import argparse
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
FORBIDDEN_NAME_FRAGMENTS = (
    "trading_",
    "order",
    "broker",
    "read_file",
    "write_file",
    "read_url",
    "read_document",
    "web_search",
    "remember",
    "memory",
    "schedule",
    "swarm",
    "shell",
    "bash",
    "background",
)
CANDIDATE_NAMES = {
    "backtest",
    "run_shadow_backtest",
    "render_shadow_report",
}


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sanitized_environment() -> dict[str, str]:
    home = RUNTIME_ROOT / "home"
    temp = RUNTIME_ROOT / "temp"
    home.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    path_parts = [
        str(UPSTREAM / ".venv" / "Scripts"),
        str(Path(system_root) / "System32"),
        system_root,
    ]
    return {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "PATH": os.pathsep.join(path_parts),
        "USERPROFILE": str(home),
        "HOMEDRIVE": home.drive,
        "HOMEPATH": str(home)[len(home.drive) :],
        "TEMP": str(temp),
        "TMP": str(temp),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "VIBE_TRADING_ENABLE_SHELL_TOOLS": "0",
    }


def initialize_summary(result: Any) -> dict[str, Any]:
    return {
        "protocol_version": result.protocolVersion,
        "server_name": result.serverInfo.name,
        "server_version": result.serverInfo.version,
        "capabilities": result.capabilities.model_dump(mode="json"),
        "instructions_sha256": (
            hashlib.sha256(result.instructions.encode("utf-8")).hexdigest()
            if result.instructions
            else None
        ),
    }


def tool_summary(tool: Any) -> dict[str, Any]:
    schema = tool.inputSchema
    description = tool.description or ""
    entry = {
        "name": tool.name,
        "description_sha256": hashlib.sha256(
            description.encode("utf-8")
        ).hexdigest(),
        "input_schema_sha256": canonical_hash(schema),
        "input_schema_bytes": len(
            json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "forbidden_by_goal": any(
            fragment in tool.name.lower() for fragment in FORBIDDEN_NAME_FRAGMENTS
        ),
    }
    if tool.name in CANDIDATE_NAMES:
        entry["input_schema"] = schema
    return entry


async def discover(timeout_seconds: float) -> dict[str, Any]:
    params = StdioServerParameters(
        command=str(EXECUTABLE),
        args=["--transport", "stdio"],
        env=sanitized_environment(),
        cwd=str(UPSTREAM),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await asyncio.wait_for(
                session.initialize(), timeout=timeout_seconds
            )
            listed = await asyncio.wait_for(
                session.list_tools(), timeout=timeout_seconds
            )
            tools = [tool_summary(tool) for tool in listed.tools]
            return {
                "suite": "vibe-trading-mcp-discovery",
                "pinned_commit": PINNED_COMMIT,
                "executable": str(EXECUTABLE),
                "runtime_root": str(RUNTIME_ROOT),
                "environment_keys": sorted(sanitized_environment().keys()),
                "initialize": initialize_summary(initialized),
                "tools_count": len(tools),
                "tools_schema_set_sha256": canonical_hash(tools),
                "forbidden_tools_count": sum(
                    1 for tool in tools if tool["forbidden_by_goal"]
                ),
                "candidate_tools_present": sorted(
                    tool["name"] for tool in tools if tool["name"] in CANDIDATE_NAMES
                ),
                "tools": tools,
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = asyncio.run(discover(args.timeout_seconds))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
