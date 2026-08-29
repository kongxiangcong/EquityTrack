from __future__ import annotations

import json

from trading_platform.cli import main


def test_cli_calls_account_operations_and_markdown_is_not_persisted(tmp_path, capsys) -> None:
    request = tmp_path / "account.json"
    request.write_text(json.dumps({
        "account_id": "account-orchid", "as_of": "2035-04-18T08:00:00+00:00",
        "confirmed": True, "confirmed_by": "synthetic-user", "cash": None,
        "positions": [{"security_id": "security-aster-001", "quantity": "120", "available_quantity": None, "cost_basis": None}],
    }), encoding="utf-8")
    assert main(["account-confirm", "--data-root", str(tmp_path / "root"), "--input-file", str(request), "--idempotency-key", "cli-confirm"]) == 0
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed["ok"] and confirmed["operation"] == "account-confirm"

    assert main(["account-show", "--data-root", str(tmp_path / "root"), "--account-id", "account-orchid", "--format", "markdown"]) == 0
    markdown = capsys.readouterr().out
    assert "# Decision result" in markdown
    assert "snapshot_id" not in markdown
    assert list((tmp_path / "root").iterdir()) == [tmp_path / "root" / "decision-core.sqlite3"]
