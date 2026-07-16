from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/scripts/source_manifest_validator.py"


def test_v2_manifest_is_valid_with_capability_limits_instead_of_failing_globally() -> None:
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--manifest", str(ROOT / "examples/yihua-002897/source_manifest.json")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert result["validator_version"] == 2 and result["manifest_version"] == 2
    assert result["authority"] == "legacy_compatibility_only"
    assert result["passed"] is True
    assert result["source_manifest_status"] == "valid_with_limits"
    assert result["data_insufficient_memo_required"] is False
    assert set(result["limitations"]["missing_critical_fields"]) == {"d_and_a", "lease_debt"}


def test_v2_manifest_still_fails_closed_on_source_integrity_errors(tmp_path: Path) -> None:
    manifest = json.loads((ROOT / "examples/yihua-002897/source_manifest.json").read_text(encoding="utf-8"))
    manifest["sources"][0].pop("retrieved_at")
    path = tmp_path / "invalid-v2.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--manifest", str(path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert result["authority"] == "legacy_compatibility_only"
    assert result["passed"] is False and result["source_manifest_status"] == "invalid"
    assert any(item["code"] == "REQUIRED_FIELD_MISSING" for item in result["issues"])
