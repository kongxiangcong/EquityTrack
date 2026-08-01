from __future__ import annotations

import json
import hashlib
import subprocess
import sys

import pytest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills/scripts/source_manifest_validator.py"

def _run_validator(path: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--manifest", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return completed, json.loads(completed.stdout)


def _yihua_manifest() -> dict[str, object]:
    return json.loads(
        (ROOT / "examples/yihua-002897/source_manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_v2_manifest_is_valid_with_capability_limits_instead_of_failing_globally() -> None:
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--manifest", str(ROOT / "examples/yihua-002897/source_manifest.json")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert result["validator_version"] == 2 and result["manifest_version"] == 2
    assert result["authority"] == "platform_source_manifest_gate@1"
    assert result["passed"] is True
    assert result["source_manifest_status"] == "valid_with_limits"
    assert result["data_insufficient_memo_required"] is False
    manifest = json.loads(
        (ROOT / "examples/yihua-002897/source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected_hash = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert result["manifest_content_hash"] == expected_hash
    assert set(result["limitations"]["missing_critical_fields"]) == {"d_and_a", "lease_debt"}
    declared_missing = [
        issue
        for issue in result["issues"]
        if issue["code"] == "CAPABILITY_INPUT_MISSING"
    ]
    assert {issue["details"]["field_name"] for issue in declared_missing} == {
        "d_and_a",
        "lease_debt",
    }
    assert {issue["severity"] for issue in declared_missing} == {"warning"}

def test_v2_terminal_and_secondary_critical_coverage_is_a_warning_not_a_global_error(
    tmp_path: Path,
) -> None:
    manifest = _yihua_manifest()
    sources = manifest["sources"]
    assert isinstance(sources, list)
    for source in sources:
        assert isinstance(source, dict)
        if source["tier"] == "official":
            source["tier"] = "terminal"
            source["official_or_secondary"] = "secondary"
    first_fields = sources[0]["extracted_fields"]
    assert isinstance(first_fields, list)
    for field_name in ("d_and_a", "lease_debt"):
        first_fields.append(
            {
                "field_name": field_name,
                "period": "2026Q1",
                "value": 0,
                "unit": "CNY",
                "currency": "CNY",
                "extraction_method": "terminal_structured_field",
                "confidence": "medium",
            }
        )
    manifest["missing_critical_data"] = []
    path = tmp_path / "terminal-secondary-v2.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    completed, result = _run_validator(path)

    assert completed.returncode == 0
    assert result["passed"] is True
    assert result["source_manifest_status"] == "valid_with_limits"
    authority_issues = [
        issue
        for issue in result["issues"]
        if issue["code"] == "OFFICIAL_SOURCE_MISSING"
    ]
    assert authority_issues
    assert {issue["severity"] for issue in authority_issues} == {"warning"}



def test_v2_manifest_still_fails_closed_on_source_integrity_errors(tmp_path: Path) -> None:
    manifest = _yihua_manifest()
    manifest["sources"][0].pop("retrieved_at")
    path = tmp_path / "invalid-v2.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--manifest", str(path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert result["authority"] == "platform_source_manifest_gate@1"
    assert result["passed"] is False and result["source_manifest_status"] == "invalid"
    assert any(item["code"] == "REQUIRED_FIELD_MISSING" for item in result["issues"])


@pytest.mark.parametrize(
    ("case_name", "expected_code"),
    (
        ("duplicate_identity", "DUPLICATE_SOURCE_ID"),
        ("invalid_pit", "SOURCE_AVAILABLE_AT_INVALID"),
        ("hash_mismatch", "RAW_FILE_SHA256_MISMATCH"),
        ("non_numeric", "FIELD_VALUE_NOT_NUMERIC"),
        ("unit_conflict", "UNIT_CONFLICT"),
        ("currency_conflict", "REPORTING_CURRENCY_CONFLICT"),
        ("source_conflict", "UNRESOLVED_SOURCE_CONFLICT"),
        ("classification_conflict", "SOURCE_CLASSIFICATION_CONFLICT"),
        ("estimate_without_basis", "ESTIMATE_SOURCE_BASIS_INVALID"),
    ),
)
def test_v2_integrity_failures_remain_global_errors(
    tmp_path: Path,
    case_name: str,
    expected_code: str,
) -> None:
    manifest = _yihua_manifest()
    sources = manifest["sources"]
    assert isinstance(sources, list)
    first_source = sources[0]
    assert isinstance(first_source, dict)
    first_fields = first_source["extracted_fields"]
    assert isinstance(first_fields, list)

    if case_name == "duplicate_identity":
        sources.append(dict(first_source))
    elif case_name == "invalid_pit":
        first_source.pop("available_at", None)
        first_source.pop("published_at", None)
        first_source["report_date"] = "not-an-iso-date"
    elif case_name == "hash_mismatch":
        first_source["raw_file_path"] = str(
            ROOT
            / "skills/scripts/fixtures/source_manifest/raw/testcorp_2024_10k.txt"
        )
        first_source["raw_file_sha256"] = "0" * 64
    elif case_name == "non_numeric":
        first_field = first_fields[0]
        assert isinstance(first_field, dict)
        first_field["value"] = "not available"
    elif case_name == "unit_conflict":
        conflicting_field = dict(first_fields[0])
        conflicting_field["unit"] = "CNY million"
        first_fields.append(conflicting_field)
    elif case_name == "currency_conflict":
        first_field = first_fields[0]
        assert isinstance(first_field, dict)
        first_field["currency"] = "USD"
    elif case_name == "source_conflict":
        cross_checks = first_source["cross_checks"]
        assert isinstance(cross_checks, list)
        second_source = sources[1]
        assert isinstance(second_source, dict)
        cross_checks.append(
            {
                "source_id": second_source["source_id"],
                "status": "mismatch",
                "notes": "unresolved fixture conflict",
            }
        )
    elif case_name == "classification_conflict":
        first_source["official_or_secondary"] = "secondary"
    else:
        sources.append(
            {
                "source_id": "SRC_ESTIMATE_WITHOUT_BASIS",
                "tier": "estimate",
                "publisher": "Explicit estimate fixture",
                "title": "Estimate without evidence basis",
                "url_or_api": "fixture:estimate-without-basis",
                "retrieved_at": "2026-07-07T13:00:00+08:00",
                "report_date": "2026-07-07",
                "extracted_fields": [
                    {
                        "field_name": "d_and_a",
                        "period": "2026Q1",
                        "value": 1,
                        "unit": "CNY",
                        "currency": "CNY",
                        "extraction_method": "scenario_estimate",
                        "confidence": "low",
                    }
                ],
                "cross_checks": [],
            }
        )

    path = tmp_path / f"{case_name}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    completed, result = _run_validator(path)

    assert completed.returncode == 1, (case_name, result)
    assert result["passed"] is False, (case_name, result)
    assert result["source_manifest_status"] == "invalid", (case_name, result)
    assert expected_code in {
        issue["code"] for issue in result["issues"]
    }, (case_name, result["issues"])


def test_duofuduo_v2_manifest_passes_with_only_per_share_limits() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--manifest",
            str(ROOT / "examples/duofuduo-002407/source_manifest.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert result["passed"] is True
    assert result["source_manifest_status"] == "valid_with_limits"
    assert result["summary"]["hash_checks"] == 11
    assert result["summary"]["errors"] == 0
    assert set(result["limitations"]["missing_critical_fields"]) == {
        "diluted_shares",
        "pension_deficit",
        "sbc_options_dilution",
    }
