from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any


FIXTURE = Path(__file__).with_name("vibe-mcp-failure-fixture.py")


async def exercise(mode: str) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(FIXTURE),
        mode,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "ticket06-failure-probe", "version": "1"},
        },
    }
    process.stdin.write(
        (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    )
    await process.stdin.drain()
    outcome: dict[str, Any] = {"mode": mode}
    try:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
        if not line:
            return_code = await asyncio.wait_for(process.wait(), timeout=1.0)
            outcome.update({"classification": "server_crash", "exit_code": return_code})
        else:
            try:
                json.loads(line)
                outcome["classification"] = "unexpected_valid_json"
            except json.JSONDecodeError:
                outcome.update(
                    {
                        "classification": "malformed_json_rpc",
                        "bytes": len(line),
                    }
                )
    except asyncio.TimeoutError:
        outcome["classification"] = "client_timeout"
        process.kill()
        await process.wait()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return outcome


async def run() -> dict[str, Any]:
    outcomes = [await exercise(mode) for mode in ("crash", "timeout", "malformed")]
    return {
        "suite": "vibe-mcp-client-failure-smoke",
        "outcomes": outcomes,
        "passed": sum(
            outcome["classification"]
            in {"server_crash", "client_timeout", "malformed_json_rpc"}
            for outcome in outcomes
        ),
        "failed": sum(
            outcome["classification"]
            not in {"server_crash", "client_timeout", "malformed_json_rpc"}
            for outcome in outcomes
        ),
    }


def main() -> None:
    print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
