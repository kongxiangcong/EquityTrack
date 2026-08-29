from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from trading_platform.application import open_application


MUTATIONS = {
    "account-confirm": "account_confirm",
    "research-commit": "research_commit",
    "valuation-assess": "valuation_assess",
    "planning-prepare": "planning_prepare",
    "planning-confirm": "planning_confirm",
    "monitor-evaluate": "monitor_evaluate",
    "review-commit": "review_commit",
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="trading-platform")
    commands = root.add_subparsers(dest="operation", required=True)
    show = commands.add_parser("account-show")
    show.add_argument("--data-root", type=Path, required=True)
    show.add_argument("--account-id", required=True)
    show.add_argument("--as-of")
    show.add_argument("--format", choices=("json", "markdown"), default="json")
    for name in MUTATIONS:
        command = commands.add_parser(name)
        command.add_argument("--data-root", type=Path, required=True)
        command.add_argument("--input-file", type=Path, required=True)
        command.add_argument("--idempotency-key", required=True)
        command.add_argument("--format", choices=("json", "markdown"), default="json")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    app = open_application(args.data_root)
    if args.operation == "account-show":
        result = app.account_show(args.account_id, args.as_of)
    else:
        request = json.loads(args.input_file.read_text(encoding="utf-8"))
        result = getattr(app, MUTATIONS[args.operation])(
            request, idempotency_key=args.idempotency_key
        )
    envelope: dict[str, Any] = {"ok": result.ok, "operation": args.operation}
    if result.ok:
        envelope["result"] = result.value
    else:
        envelope["error"] = result.error
    if args.format == "markdown":
        print(_markdown(envelope))
    else:
        print(json.dumps(envelope, ensure_ascii=False, sort_keys=True))
    return 0 if result.ok else 2


def _markdown(envelope: dict[str, Any]) -> str:
    if not envelope["ok"]:
        error = envelope["error"]
        return f"# Operation failed\n\n{error['message']}\n\nStep: `{error['step']}`"
    visible = _without_internal_ids(envelope["result"])
    return "# Decision result\n\n```json\n" + json.dumps(visible, ensure_ascii=False, indent=2, sort_keys=True) + "\n```"


def _without_internal_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_internal_ids(item) for key, item in value.items() if not key.endswith("_id") and key not in {"content_hash"}}
    if isinstance(value, list):
        return [_without_internal_ids(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
