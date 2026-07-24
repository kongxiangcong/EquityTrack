from __future__ import annotations

import asyncio
import csv
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
RUNTIME_HOME = RUNTIME_ROOT / "home"
RUN_DIR = RUNTIME_HOME / ".vibe-trading" / "runs" / "known-answer"
PINNED_COMMIT = "0aa45a9ff3df58fab1c50f5400d9b112d19cacc6"


def environment() -> dict[str, str]:
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
        "USERPROFILE": str(RUNTIME_HOME),
        "HOMEDRIVE": RUNTIME_HOME.drive,
        "HOMEPATH": str(RUNTIME_HOME)[len(RUNTIME_HOME.drive) :],
        "TEMP": str(RUNTIME_ROOT / "temp"),
        "TMP": str(RUNTIME_ROOT / "temp"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "VIBE_TRADING_ENABLE_SHELL_TOOLS": "0",
        "VIBE_TRADING_ALLOWED_RUN_ROOTS": str(RUN_DIR.parent),
    }


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory() -> dict[str, str]:
    paths = [
        path
        for path in RUN_DIR.rglob("*")
        if path.is_file()
        and (
            "artifacts" in path.relative_to(RUN_DIR).parts
            or path.name in {"run_card.json", "run_card.md"}
        )
    ]
    return {
        path.relative_to(RUN_DIR).as_posix(): hash_file(path)
        for path in sorted(paths)
    }


def text_payload(result: Any) -> str:
    return "".join(
        content.text
        for content in result.content
        if getattr(content, "type", None) == "text"
    )


def artifact_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in ("metrics.json", "validation.json"):
        path = RUN_DIR / "artifacts" / name
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            summary[name] = {
                "top_level_keys": sorted(payload.keys()),
                "sha256": hash_file(path),
                "payload": payload,
            }
    card_path = RUN_DIR / "run_card.json"
    if card_path.exists():
        card = json.loads(card_path.read_text(encoding="utf-8"))
        summary["run_card.json"] = {
            "top_level_keys": sorted(card.keys()),
            "sha256": hash_file(card_path),
            "schema_version": card.get("schema_version"),
            "reproducibility": card.get("reproducibility"),
            "data_sources": card.get("data_sources"),
            "artifact_count": len(card.get("artifacts", [])),
            "records_own_hash": any(
                item.get("path") == "run_card.json"
                for item in card.get("artifacts", [])
            ),
        }
    trades_path = RUN_DIR / "artifacts" / "trades.csv"
    if trades_path.exists():
        with trades_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        summary["trades.csv"] = {
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "first_trade": rows[0] if rows else None,
            "sha256": hash_file(trades_path),
        }
    return summary


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
            first = await asyncio.wait_for(
                session.call_tool("backtest", {"run_dir": str(RUN_DIR)}),
                timeout=120,
            )
            first_text = text_payload(first)
            first_inventory = inventory()
            second = await asyncio.wait_for(
                session.call_tool("backtest", {"run_dir": str(RUN_DIR)}),
                timeout=120,
            )
            second_text = text_payload(second)
            second_inventory = inventory()

    stable_paths = sorted(
        path
        for path in set(first_inventory) & set(second_inventory)
        if path not in {"run_card.json", "run_card.md"}
    )
    return {
        "suite": "vibe-trading-local-known-answer",
        "pinned_commit": PINNED_COMMIT,
        "server": {
            "name": initialized.serverInfo.name,
            "version": initialized.serverInfo.version,
            "protocol_version": initialized.protocolVersion,
        },
        "run_dir": str(RUN_DIR),
        "first_call": {
            "is_error": bool(first.isError),
            "json": json.loads(first_text),
            "text_sha256": hashlib.sha256(first_text.encode("utf-8")).hexdigest(),
        },
        "second_call": {
            "is_error": bool(second.isError),
            "json": json.loads(second_text),
            "text_sha256": hashlib.sha256(second_text.encode("utf-8")).hexdigest(),
        },
        "same_call_text_hash": hashlib.sha256(first_text.encode("utf-8")).digest()
        == hashlib.sha256(second_text.encode("utf-8")).digest(),
        "stable_artifact_paths_compared": stable_paths,
        "stable_artifacts_byte_identical": all(
            first_inventory[path] == second_inventory[path] for path in stable_paths
        ),
        "first_inventory": first_inventory,
        "second_inventory": second_inventory,
        "artifact_summary": artifact_summary(),
        "network_provider_calls_executed": [],
        "source": "local",
    }


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
