from __future__ import annotations

import hashlib
import json
from pathlib import Path

import backtest.run_card as run_card_module
from backtest.run_card import write_run_card


RUN_DIR = (
    Path(r"E:\workspace\tradingSystem-upstreams\Vibe-Trading")
    / ".venv"
    / "qualification-runtime"
    / "run-card-tamper"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    artifacts = RUN_DIR / "artifacts"
    code = RUN_DIR / "code"
    artifacts.mkdir(parents=True, exist_ok=True)
    code.mkdir(parents=True, exist_ok=True)
    config = {
        "codes": ["FIXTURE"],
        "start_date": "2026-01-01",
        "end_date": "2026-01-10",
        "source": "local",
    }
    (RUN_DIR / "config.json").write_text(
        json.dumps(config, sort_keys=True), encoding="utf-8"
    )
    strategy = code / "signal_engine.py"
    strategy.write_text(
        "class SignalEngine:\n    def generate(self, data_map):\n        return {}\n",
        encoding="utf-8",
    )
    target = artifacts / "metrics.json"
    target.write_text('{"total_return":0.1}\n', encoding="utf-8")
    card = write_run_card(
        RUN_DIR,
        config,
        {"total_return": 0.1},
        data_sources=["local"],
        strategy_path=strategy,
    )
    recorded = next(
        item["sha256"]
        for item in card["artifacts"]
        if item["path"] == "artifacts/metrics.json"
    )
    before = sha256(target)
    target.write_text('{"total_return":9.9}\n', encoding="utf-8")
    after = sha256(target)
    result = {
        "suite": "vibe-trading-run-card-tamper",
        "recorded_hash_matches_before_tamper": recorded == before,
        "recorded_hash_matches_after_tamper": recorded == after,
        "tamper_detectable_by_external_rehash": before != after,
        "upstream_verify_function_present": hasattr(
            run_card_module, "verify_run_card"
        ),
        "run_card_records_own_hash": any(
            item["path"] == "run_card.json" for item in card["artifacts"]
        ),
        "run_card_schema_version": card["schema_version"],
        "passed": 5,
        "failed": 0,
        "interpretation": (
            "The inventory hash is useful, but upstream does not invoke an "
            "independent verifier or bind the card to an external trust anchor."
        ),
    }
    assert result["recorded_hash_matches_before_tamper"] is True
    assert result["recorded_hash_matches_after_tamper"] is False
    assert result["tamper_detectable_by_external_rehash"] is True
    assert result["upstream_verify_function_present"] is False
    assert result["run_card_records_own_hash"] is False
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
