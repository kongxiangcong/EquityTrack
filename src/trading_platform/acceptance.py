from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from trading_platform.identity.canonical import CANONICALIZATION_VERSION, canonical_hash
from trading_platform.identity.code import build_code_identity


@dataclass(frozen=True)
class AcceptanceEvidenceResult:
    slice_acceptance: str
    manifest_sha256: str
    manifest_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class AcceptanceEvidenceService:
    """Validate and freeze evidence without creating a test-only business facade."""

    SCHEMA_VERSION = "VerticalSliceAcceptance@1"
    REQUIRED_SUITES = (
        "domain",
        "provider_contract",
        "persistence_migration",
        "application_journey",
        "fault_recovery",
        "browser",
        "windows_maintenance",
        "architecture_security",
        "legacy_regression",
    )
    REQUIRED_APPLICABILITY = {
        "position_accounting": "not_applicable",
        "full_trade_backtest": "not_applicable",
        "valuation_formula_regression": "passed",
        "adapter_financial_invariants": "passed",
    }
    SUITE_PLAN = {
        "domain": ("tests/platform/test_market_evaluation.py", "tests/platform/test_trade_plans.py"),
        "provider_contract": ("tests/platform/test_data_sync_pit.py",),
        "persistence_migration": ("tests/platform/test_watchlist_persistence.py", "tests/platform/test_chart_annotations.py"),
        "application_journey": ("tests/platform/test_research_workflow.py", "tests/platform/test_secure_workspace.py"),
        "fault_recovery": ("tests/platform/test_workflow_recovery.py",),
        "windows_maintenance": ("tests/platform/test_operations_backup_restore.py",),
        "architecture_security": ("tests/platform/test_runtime_skeleton.py",),
        "legacy_regression": ("tests", "--ignore=tests/platform"),
    }
    CRITERION_SUITE = {
        **{number: "provider_contract" for number in (4, 5, 6, 7, 17, 18, 19, 20, 21, 39, 41, 42, 51)},
        **{number: "application_journey" for number in (3, 8, 15, 34, 40, 49)},
        **{number: "domain" for number in (11, 12, 13, 14, 22, 23, 25, 26, 43)},
        **{number: "persistence_migration" for number in (2, 9, 10, 24)},
        **{number: "fault_recovery" for number in (27, 28)},
        **{number: "browser" for number in (31, 32, 37, 45)},
        **{number: "windows_maintenance" for number in (1, 16, 29, 30, 33, 46, 47, 48)},
        **{number: "architecture_security" for number in (35, 36, 38, 44, 50)},
    }
    CRITERION_SUITE.update({1: "persistence_migration", 29: "persistence_migration", 34: "architecture_security", 39: "application_journey"})
    CRITERION_ASSERTION_PATTERN = {
        1: "test_bootstrap_watchlist_replay_restart_and_doctor", 2: "test_bootstrap_watchlist_replay_restart_and_doctor",
        3: "test_public_workflow_creates_canonical_research_artifacts", 4: "test_startup_and_unauthorized_http_provider_make_no_network_call",
        5: "test_explicit_fixture_sync_freezes_pit_snapshot_and_reuses_identity", 6: "test_explicit_fixture_sync_freezes_pit_snapshot_and_reuses_identity",
        7: "test_fixture_manifest_separates_real_derived_facts_from_synthetic_sentinels", 8: "test_new_invocation_reuses_immutable_research",
        9: "test_chart_query_exposes_versioned_unadjusted_series_and_freshness", 10: "test_annotation_append_only_lifecycle_idempotency_and_restart",
        11: "test_atomic_confirmation_idempotency_preview_and_restart", 12: "test_atomic_confirmation_idempotency_preview_and_restart",
        13: "test_transparent_market_snapshot_and_read_only_plan_evaluation", 14: "test_transparent_market_snapshot_and_read_only_plan_evaluation",
        15: "test_frozen_timeline_traverses_plan_market_evaluation_and_policy_versions", 16: "test_windows_cli_backup_restore_doctor_serve_history",
        17: "test_explicit_fixture_sync_freezes_pit_snapshot_and_reuses_identity", 18: "test_offline_valid_stale_missing_and_coverage_missing_fail_closed",
        19: "test_fixture_manifest_separates_real_derived_facts_from_synthetic_sentinels", 20: "test_empty_rate_limit_and_schema_drift_do_not_advance_cursor",
        21: "test_revision_creates_parallel_version_and_new_snapshot", 22: "test_revision_v2_switch_discard_and_ended_terminal",
        23: "test_revision_v2_switch_discard_and_ended_terminal", 24: "test_annotation_append_only_lifecycle_idempotency_and_restart",
        25: "test_suspension_and_limit_facts_are_evaluated_without_lifecycle_side_effects", 26: "test_typed_ast_references_account_applicability_and_adjusted_evidence",
        27: "test_resume_reuses_committed_nodes_and_never_duplicates_research", 28: "test_resume_fails_closed_on_definition_fingerprint_or_artifact_corruption",
        29: "test_migrations_are_idempotent_atomic_and_reject_drift_and_future", 30: "test_backup_restore_new_root_preserves_database_objects_and_history",
        31: "workspace is task-first", 32: "accessibility policy includes keyboard focus", 33: "test_windows_cli_returns_stable_json_envelopes",
        34: "test_recorded_legacy_regression_baseline_is_executable_and_complete", 35: "test_platform_imports_only_public_research_package",
        36: "test_platform_imports_only_public_research_package", 37: "workspace copy contains no rating",
        38: "acceptance_service::self_verify_manifest", 39: "test_public_workflow_creates_canonical_research_artifacts", 40: "test_new_invocation_reuses_immutable_research",
        41: "test_fixture_manifest_separates_real_derived_facts_from_synthetic_sentinels", 42: "test_non_structural_cross_section_gap_blocks_snapshot",
        43: "test_confirmation_contract_rejects_invalid_risk_and_time", 44: "test_code_identity_changes_with_source_lock_workflow_frontend_migration_and_config",
        45: "workspace assets stay local and output uses text nodes", 46: "test_dependency_locks_offline_assets_skill_routing", 47: "test_restore_rejects",
        48: "test_dependency_locks_offline_assets_skill_routing", 49: "test_frozen_timeline_traverses_plan_market_evaluation_and_policy_versions", 50: "test_platform_imports_only_public_research_package",
        51: "test_private_fixture_rights_are_preserved_without_upgrading_redistribution",
    }
    MULTI_ASSERTION_REQUIREMENTS = {
        15: (("application_journey", "test_connected_golden_journey_records_one_graph_on_one_data_root"),),
        34: (("architecture_security", "test_recorded_legacy_regression_baseline_is_executable_and_complete"), ("application_journey", "test_public_workflow_creates_canonical_research_artifacts")),
        36: (("provider_contract", "test_startup_and_unauthorized_http_provider_make_no_network_call"), ("application_journey", "test_secret_and_personal_paths_never_reach_dom_logs_or_artifacts"), ("architecture_security", "test_platform_imports_only_public_research_package")),
        50: (("domain", "test_typed_ast_references_account_applicability_and_adjusted_evidence"), ("architecture_security", "test_recorded_legacy_regression_baseline_is_executable_and_complete"), ("provider_contract", "test_tushare_compatible_provider_uses_same_raw_normalize_quality_pit_path")),
    }

    def __init__(self, data_root: Path, repo_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.repo_root = repo_root.resolve()

    def run(self, fixture_manifest_path: Path, live_qualification: Mapping[str, Any] | None = None) -> AcceptanceEvidenceResult:
        trusted_root = (self.repo_root / "tests/fixtures/platform_data").resolve()
        fixture_path = fixture_manifest_path.resolve()
        if fixture_path.parent != trusted_root or fixture_path.name != "manifest.json":
            raise ValueError("FIXTURE_MANIFEST_OUTSIDE_TRUSTED_ROOT")
        evidence_root = self.data_root / ".acceptance-run"
        evidence_root.mkdir(parents=True, exist_ok=True)
        runner_temporary = tempfile.TemporaryDirectory(prefix="tp-accept-")
        runner_temp = Path(runner_temporary.name)
        artifacts: dict[str, dict[str, str]] = {}
        suites: list[dict[str, Any]] = []
        golden_evidence_path = evidence_root / "golden-journey.json"
        for name in self.REQUIRED_SUITES:
            if name == "browser":
                test_files = sorted((self.repo_root / "web/tests").glob("*.test.js"))
                command = ["node", "--test", "--test-reporter=junit", *(str(path) for path in test_files)]
                environment = os.environ.copy()
                if name == "application_journey":
                    environment["TRADING_PLATFORM_GOLDEN_EVIDENCE"] = str(golden_evidence_path)
                completed = subprocess.run(command, cwd=self.repo_root, env=os.environ.copy(), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
                artifact = evidence_root / "browser.xml"
                artifact.write_text(completed.stdout, encoding="utf-8")
                collected, skipped, xfailed, assertion_ids = self._parse_junit(artifact)
                command_identity = canonical_hash(["node", "--test", "--test-reporter=junit", *(path.name for path in test_files)])
            else:
                planned = self.SUITE_PLAN[name]
                artifact = evidence_root / f"{name}.xml"
                suite_data = runner_temp / f"{name}-data"
                command = [os.sys.executable, "-m", "pytest", *planned, "-q", f"--junitxml={artifact}", f"--basetemp={suite_data}"]
                environment = os.environ.copy()
                if name == "application_journey":
                    environment["TRADING_PLATFORM_GOLDEN_EVIDENCE"] = str(golden_evidence_path)
                completed = subprocess.run(command, cwd=self.repo_root, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
                collected, skipped, xfailed, assertion_ids = self._parse_junit(artifact)
                command_identity = canonical_hash(list(planned))
            artifacts[name] = {"path": str(artifact), "sha256": _sha256(artifact)}
            suites.append({"name": name, "version": "1", "status": "passed" if completed.returncode == 0 and collected and skipped == 0 and xfailed == 0 else "failed", "command_identity": command_identity, "exit_code": completed.returncode, "collected": collected, "skipped": skipped, "xfailed": xfailed, "assertion_ids": assertion_ids, "artifact_refs": [name]})
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture["manifest_sha256"] = _sha256(fixture_path)
        rights_profile = fixture.get("derived_fact_fixture", {})
        for member in fixture.get("members", ()):
            payload_path = trusted_root / str(member.get("payload_path", ""))
            if payload_path.parent != trusted_root or not payload_path.is_file():
                raise ValueError("FIXTURE_MEMBER_MISSING")
            payload = payload_path.read_bytes().rstrip(b"\r\n")
            if hashlib.sha256(payload).hexdigest() != member.get("payload_sha256"):
                raise ValueError("FIXTURE_MEMBER_HASH_MISMATCH")
            json.loads(payload)
            member["terms_version"] = rights_profile.get("terms_version")
            member["reviewed_on"] = rights_profile.get("reviewed_on")
        criteria = []
        all_assertions = {item["name"]: item["assertion_ids"] for item in suites}
        for number in range(1, 52):
            suite_name = self.CRITERION_SUITE.get(number, "domain")
            suite = next(item for item in suites if item["name"] == suite_name)
            requirements = self.MULTI_ASSERTION_REQUIREMENTS.get(number, ((suite_name, self.CRITERION_ASSERTION_PATTERN[number]),))
            matched = []
            artifact_refs = []
            for required_suite, pattern in requirements:
                found = [assertion for assertion in all_assertions[required_suite] if pattern in assertion]
                if found:
                    matched.extend(found); artifact_refs.append(required_suite)
                else:
                    matched = []; break
            if number == 38:
                matched = [pattern]
                artifact_refs = [suite_name]
            criteria.append({"criterion": f"AC-{number:03d}", "status": "passed" if all(next(item for item in suites if item["name"] == required_suite)["status"] == "passed" for required_suite, _ in requirements) and matched else "failed", "suite": suite["name"], "assertion_ids": matched, "artifact_refs": sorted(set(artifact_refs))})
        golden = json.loads(golden_evidence_path.read_text(encoding="utf-8")) if golden_evidence_path.is_file() else {}
        runner_temporary.cleanup()
        golden_fields = {"workflow_run_id": "WorkflowRun", "original_workflow_run_id": "WorkflowRun", "data_snapshot_id": "DataSnapshot", "research_snapshot_id": "DataSnapshot", "research_run_id": "ResearchRun", "research_json_artifact_id": "Artifact", "research_html_artifact_id": "Artifact", "annotation_version_id": "ChartAnnotationVersion", "plan_version_id": "TradePlanVersion", "market_snapshot_id": "MarketSnapshot", "plan_evaluation_id": "PlanEvaluation", "final_artifact_manifest_id": "ArtifactManifest"}
        golden_valid = golden.get("schema_version") == "GoldenJourneyEvidence@1" and all(golden.get(field) for field in golden_fields) and golden.get("dispositions", {}).get("research") == "reused" and golden.get("reuse_reason_code") == "ROUTINE_MARKET_ONLY_INPUTS" and golden.get("stale_by_days") == 3
        if not golden_valid:
            for criterion in criteria:
                if criterion["criterion"] == "AC-015": criterion["status"] = "failed"
        golden_entities = [{"entity_type": entity_type, "identity": str(golden[field]), "disposition": str(golden.get("dispositions", {}).get(field.removesuffix("_id").replace("_version", ""), "as_recorded"))} for field, entity_type in golden_fields.items() if golden.get(field)]
        supplied = {
            "slice_spec_version": "0.2.0", "versions": {"workflow": "research-workflow@1", "node": "registry@1", "evaluator": "plan-evaluator@1", "model": "equity-research@0.3.0", "policy": "research_input_policy@1"},
            "fixed_clock": "2026-07-11T09:30:00+08:00", "network_policy": "offline-deny-all", "fixture": fixture,
            "criteria": criteria, "suites": suites, "artifacts": artifacts,
            "golden_entities": golden_entities,
            "applicability": [{"capability": "position_accounting", "status": "not_applicable", "rationale": "Watchlist slice has no account or Position model.", "counter_capability_test": next(assertion for assertion in all_assertions["domain"] if "test_typed_ast_references_account_applicability_and_adjusted_evidence" in assertion)}, {"capability": "full_trade_backtest", "status": "not_applicable", "rationale": "No execution, fee, slippage or T+1 simulator is in scope.", "counter_capability_test": next(assertion for assertion in all_assertions["architecture_security"] if "test_platform_imports_only_public_research_package" in assertion)}, {"capability": "valuation_formula_regression", "status": "passed", "rationale": "Legacy regression evidence.", "artifact_refs": ["legacy_regression"]}, {"capability": "adapter_financial_invariants", "status": "passed", "rationale": "Provider contract evidence.", "artifact_refs": ["provider_contract"]}],
            "live_qualification": live_qualification or {"status": "external_blocked", "provider_identity": "preconfigured_tushare_compatible_non_official", "source_authority": "structured_aggregator_not_official_disclosure", "terms_profile": "qualification_pending@1", "attempts": [], "blockers": ["live_qualification_artifact_not_supplied"]},
            "credential_scope_ids": [live_qualification["credential_scope_id"]] if live_qualification and live_qualification.get("credential_scope_id") else [],
            "final_artifact_manifest_id": golden.get("final_artifact_manifest_id"),
        }
        return self._freeze(supplied)

    def _freeze(self, supplied: Mapping[str, Any]) -> AcceptanceEvidenceResult:
        failure_codes: list[str] = []
        artifacts = self._validate_artifacts(supplied.get("artifacts"), failure_codes)
        criteria = list(supplied.get("criteria", ()))
        expected = {f"AC-{number:03d}" for number in range(1, 52)}
        actual = {item.get("criterion") for item in criteria if isinstance(item, Mapping)}
        if actual != expected or len(criteria) != 51:
            failure_codes.append("ACCEPTANCE_CRITERIA_INCOMPLETE")
        if any(item.get("status") != "passed" for item in criteria if isinstance(item, Mapping)):
            failure_codes.append("LOCAL_CRITERION_NOT_PASSED")

        suites = list(supplied.get("suites", ()))
        suite_names = {item.get("name") for item in suites if isinstance(item, Mapping)}
        if suite_names != set(self.REQUIRED_SUITES) or len(suites) != len(self.REQUIRED_SUITES):
            failure_codes.append("SUITE_LEDGER_INCOMPLETE")
        if any(item.get("status") != "passed" for item in suites if isinstance(item, Mapping)):
            failure_codes.append("LOCAL_SUITE_NOT_PASSED")
        for item in suites:
            if not isinstance(item, Mapping):
                continue
            if item.get("exit_code") != 0 or not isinstance(item.get("collected"), int) or item.get("collected", 0) < 1 or item.get("skipped") != 0 or item.get("xfailed") != 0:
                failure_codes.append("LOCAL_SUITE_EXECUTION_INVALID")
            if item.get("artifact_refs") != [item.get("name")] or not item.get("assertion_ids") or not item.get("command_identity"):
                failure_codes.append("SUITE_EVIDENCE_NOT_DISTINCT")
        self._validate_references((*criteria, *suites), artifacts, failure_codes)

        fixture = supplied.get("fixture")
        fixture_distribution = self._fixture_qualification(fixture, failure_codes)
        applicability = list(supplied.get("applicability", ()))
        self._validate_applicability(applicability, artifacts, failure_codes)
        live = self._live_qualification(supplied.get("live_qualification"), failure_codes)

        required_scalars = ("slice_spec_version", "fixed_clock", "network_policy", "final_artifact_manifest_id")
        if any(not supplied.get(field) for field in required_scalars) or not supplied.get("golden_entities"):
            failure_codes.append("ACCEPTANCE_IDENTITY_INCOMPLETE")
        versions = supplied.get("versions")
        if not isinstance(versions, Mapping) or set(versions) != {"workflow", "node", "evaluator", "model", "policy"} or any(not value for value in versions.values()):
            failure_codes.append("VERSION_LEDGER_INCOMPLETE")

        code_identity = asdict(build_code_identity(self.repo_root, {"network_policy": supplied.get("network_policy"), "fixed_clock": supplied.get("fixed_clock")}))
        slice_acceptance = "failed" if failure_codes else "passed"
        acceptance_identity = canonical_hash({
            "schema": self.SCHEMA_VERSION,
            "spec": supplied.get("slice_spec_version"),
            "versions": versions,
            "code_identity": code_identity,
            "fixture_manifest_sha256": fixture.get("manifest_sha256") if isinstance(fixture, Mapping) else None,
            "fixed_clock": supplied.get("fixed_clock"),
            "network_policy": supplied.get("network_policy"),
            "live_qualification": live,
            "suites": [{key: item.get(key) for key in ("name", "version", "status", "command_identity", "assertion_ids")} for item in suites],
            "criteria": [{key: item.get(key) for key in ("criterion", "status", "suite", "assertion_ids")} for item in criteria],
        })
        manifest = {
            "acceptance_schema_version": self.SCHEMA_VERSION,
            "slice_spec_version": supplied.get("slice_spec_version"),
            "versions": versions,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "code_identity": code_identity,
            "config_safe_hash": code_identity["config_hash"],
            "acceptance_identity": acceptance_identity,
            "credential_scope_ids": tuple(supplied.get("credential_scope_ids", ())),
            "environment": {"os": platform.platform(), "python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
            "fixture": fixture,
            "fixture_distribution_qualification": fixture_distribution,
            "fixed_clock": supplied.get("fixed_clock"),
            "network_policy": supplied.get("network_policy"),
            "suites": suites,
            "criteria": criteria,
            "golden_entities": supplied.get("golden_entities", ()),
            "random_seed": None,
            "determinism_basis": "fixed-clock+canonical-json+content-addressed-artifacts",
            "artifact_evidence": artifacts,
            "dependency_license_inventory_ref": supplied.get("dependency_license_inventory_ref", "architecture_security"),
            "third_party_notices_ref": supplied.get("third_party_notices_ref", "architecture_security"),
            "applicability_ledger": applicability,
            "final_artifact_manifest_id": supplied.get("final_artifact_manifest_id"),
            "doctor_report_ref": supplied.get("doctor_report_ref", "windows_maintenance"),
            "browser_evidence_ref": supplied.get("browser_evidence_ref", "browser"),
            "backup_restore_report_ref": supplied.get("backup_restore_report_ref", "windows_maintenance"),
            "legacy_regression_ref": supplied.get("legacy_regression_ref", "legacy_regression"),
            "live_qualification": live,
            "slice_acceptance": slice_acceptance,
            "long_term_platform_complete": False,
            "failure_codes": sorted(set(failure_codes)),
        }
        payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        evidence_root = self.data_root / "acceptance"
        evidence_root.mkdir(parents=True, exist_ok=True)
        target = evidence_root / f"acceptance-{digest}.json"
        if target.exists() and target.read_bytes() != payload:
            raise RuntimeError("ACCEPTANCE_EVIDENCE_HASH_COLLISION")
        if not target.exists():
            descriptor, temporary_name = tempfile.mkstemp(prefix=".acceptance-", dir=evidence_root)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, target)
            finally:
                Path(temporary_name).unlink(missing_ok=True)
        target.chmod(stat.S_IREAD)
        verified = json.loads(target.read_text(encoding="utf-8"))
        if _sha256(target) != digest or verified.get("acceptance_schema_version") != self.SCHEMA_VERSION or len(verified.get("criteria", ())) != 51 or target.stat().st_mode & stat.S_IWUSR:
            raise RuntimeError("ACCEPTANCE_SELF_VERIFICATION_FAILED")
        return AcceptanceEvidenceResult(slice_acceptance, digest, target)


    @staticmethod
    def _parse_junit(path: Path) -> tuple[int, int, int, list[str]]:
        if not path.is_file():
            return 0, 0, 0, []
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        cases = list(root.findall("testcase")) if root.tag == "testsuites" and not suites else [case for suite in suites for case in suite.findall("testcase")]
        collected = len(cases) if cases else sum(int(item.attrib.get("tests", "0")) for item in suites)
        skipped = sum(1 for case in cases if case.find("skipped") is not None) + sum(int(item.attrib.get("skipped", "0")) for item in suites if not cases)
        failed = sum(1 for case in cases if case.find("failure") is not None or case.find("error") is not None) + sum(int(item.attrib.get("failures", "0")) + int(item.attrib.get("errors", "0")) for item in suites if not cases)
        assertions = [f"{case.attrib.get('classname')}::{case.attrib.get('name')}" for case in cases]
        return collected, skipped, failed, assertions

    @staticmethod
    def _validate_artifacts(value: Any, failure_codes: list[str]) -> dict[str, dict[str, Any]]:
        if not isinstance(value, Mapping) or not value:
            failure_codes.append("ARTIFACT_EVIDENCE_INCOMPLETE")
            return {}
        result: dict[str, dict[str, Any]] = {}
        for ref, item in value.items():
            if not isinstance(ref, str) or not isinstance(item, Mapping):
                failure_codes.append("ARTIFACT_EVIDENCE_INVALID"); continue
            path = Path(str(item.get("path", "")))
            expected = item.get("sha256")
            if not path.is_file() or not isinstance(expected, str) or _sha256(path) != expected:
                failure_codes.append("ARTIFACT_HASH_MISMATCH"); continue
            result[ref] = {"sha256": expected, "size_bytes": path.stat().st_size}
        return result

    @staticmethod
    def _validate_references(records: tuple[Any, ...], artifacts: Mapping[str, Any], failure_codes: list[str]) -> None:
        for record in records:
            if not isinstance(record, Mapping) or not record.get("artifact_refs"):
                failure_codes.append("EXECUTION_EVIDENCE_MISSING"); continue
            if any(reference not in artifacts for reference in record["artifact_refs"]):
                failure_codes.append("ARTIFACT_REFERENCE_MISSING")

    def _validate_applicability(self, items: list[Any], artifacts: Mapping[str, Any], failure_codes: list[str]) -> None:
        indexed = {item.get("capability"): item for item in items if isinstance(item, Mapping)}
        for capability, status in self.REQUIRED_APPLICABILITY.items():
            item = indexed.get(capability)
            if not item or item.get("status") != status or not item.get("rationale"):
                failure_codes.append("APPLICABILITY_LEDGER_INVALID"); continue
            if status == "not_applicable" and not item.get("counter_capability_test"):
                failure_codes.append("COUNTER_CAPABILITY_EVIDENCE_MISSING")
            if status == "passed" and any(ref not in artifacts for ref in item.get("artifact_refs", ())):
                failure_codes.append("APPLICABILITY_ARTIFACT_MISSING")

    @staticmethod
    def _fixture_qualification(value: Any, failure_codes: list[str]) -> str:
        if not isinstance(value, Mapping) or not value.get("fixture_pack_id") or not value.get("manifest_sha256") or not value.get("members"):
            failure_codes.append("FIXTURE_RIGHTS_INCOMPLETE"); return "external_blocked"
        distribution = "external_blocked" if value.get("raw_response_distribution_qualification") == "external_blocked" else "qualified"
        for member in value["members"]:
            rights = member.get("rights", {}) if isinstance(member, Mapping) else {}
            required = {"local_storage_allowed", "deterministic_replay_allowed", "repository_redistribution_allowed", "packaged_distribution_allowed"}
            if set(rights) != required or not rights.get("local_storage_allowed") or not rights.get("deterministic_replay_allowed") or not member.get("terms_version") or not member.get("reviewed_on"):
                failure_codes.append("FIXTURE_RIGHTS_INCOMPLETE")
            if not rights.get("repository_redistribution_allowed") or not rights.get("packaged_distribution_allowed"):
                distribution = "external_blocked"
        return distribution

    @staticmethod
    def _live_qualification(value: Any, failure_codes: list[str]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or value.get("status") not in {"qualified", "external_blocked", "failed"}:
            failure_codes.append("LIVE_QUALIFICATION_INVALID")
            return {"status": "failed", "failure_code": "LIVE_QUALIFICATION_INVALID"}
        live = dict(value)
        required = ("provider_identity", "source_authority", "terms_profile", "attempts")
        if any(field not in live for field in required):
            failure_codes.append("LIVE_QUALIFICATION_EVIDENCE_INCOMPLETE"); live["status"] = "failed"
        elif live["status"] == "qualified":
            attempts = live.get("attempts")
            valid_attempts = isinstance(attempts, list) and bool(attempts)
            if valid_attempts:
                for attempt in attempts:
                    if not isinstance(attempt, Mapping):
                        valid_attempts = False; break
                    raw_sha256 = attempt.get("raw_sha256")
                    if (
                        not attempt.get("attempt_id")
                        or not attempt.get("dataset")
                        or attempt.get("status") != "complete"
                        or not isinstance(raw_sha256, str)
                        or len(raw_sha256) != 64
                        or any(character not in "0123456789abcdef" for character in raw_sha256.lower())
                        or not attempt.get("retrieved_at")
                        or attempt.get("error_code")
                    ):
                        valid_attempts = False; break
            if not valid_attempts or live.get("blockers"):
                failure_codes.append("LIVE_QUALIFICATION_EVIDENCE_INVALID"); live["status"] = "failed"
        elif live["status"] == "external_blocked" and not live.get("blockers"):
            failure_codes.append("LIVE_QUALIFICATION_BLOCKER_MISSING"); live["status"] = "failed"
        return live


__all__ = ["AcceptanceEvidenceResult", "AcceptanceEvidenceService"]
