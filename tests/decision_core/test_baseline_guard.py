from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_synthetic_baseline_is_explicitly_fictional_and_offline() -> None:
    fixture = json.loads(
        (ROOT / "tests/fixtures/decision_core/synthetic_baseline.json").read_text(encoding="utf-8")
    )

    serialized = json.dumps(fixture, sort_keys=True).lower()
    assert fixture["fixture_id"] == "imaginary-decision-loop"
    assert fixture["account"]["cash"] is None
    assert "fixture-source" in serialized
    assert "api_key" not in serialized
    assert "e:\\trading-data" not in serialized


def test_target_names_do_not_use_project_progress_labels() -> None:
    target = [
        "evidence",
        "portfolio",
        "research",
        "valuation",
        "planning",
        "review",
    ]

    assert all("phase" not in name and "v2" not in name and "dsh" not in name for name in target)
