from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import stat
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from trading_platform.identity.canonical import (
    CANONICALIZATION_VERSION,
    canonical_hash,
)
from trading_platform.identity.code import build_code_identity
from trading_platform.provider_qualification import (
    decode_provider_qualification_receipt,
)
from trading_platform.verification import VerificationOutputRedactor


@dataclass(frozen=True)
class AcceptanceEvidenceResult:
    status: str
    manifest_sha256: str
    manifest_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class AcceptanceEvidenceService:
    """Run and freeze the one canonical trading-discipline-kernel gate."""

    SCHEMA_VERSION = "TradingDisciplineKernelAcceptance@1"
    FIXTURE_SCHEMA_VERSION = "TradingDisciplineKernelFixtureManifest@1"
    REQUIRED_SUITES = (
        "contract",
        "workflow_and_journal",
        "presentation",
        "migration_and_operations",
    )
    SUITE_PLAN = {
        "contract": (
            "tests/platform/test_account_snapshots.py",
            "tests/platform/test_estimated_account_state.py",
            "tests/platform/test_strategy_catalog.py",
            "tests/platform/test_trade_plan_model_b.py",
            "tests/platform/test_trade_plan_sleeves.py",
            "tests/platform/test_rule_ast_v2.py",
            "tests/platform/test_conflict_resolver.py",
            "tests/platform/test_plan_confirmation.py",
            "tests/platform/test_application_command_envelope.py",
        ),
        "workflow_and_journal": (
            "tests/platform/test_manual_portfolio_review.py",
            "tests/platform/test_decision_tasks.py",
            "tests/platform/test_execution_records.py",
            "tests/platform/test_discipline_reviews.py",
            "tests/platform/test_plan_change_proposals.py",
        ),
        "presentation": (
            "tests/platform/test_versioned_read_models.py",
            "tests/platform/test_web_application_tasks.py",
            "tests/platform/test_secure_workspace.py",
            "tests/platform/test_production_web.py",
            "tests/platform/test_skill_contract.py",
        ),
        "migration_and_operations": (
            "tests/platform/test_migration_0015_0017.py",
            "tests/platform/test_trading_discipline_kernel_e2e.py",
            "tests/platform/test_trading_discipline_kernel_backup_restore.py",
            "tests/platform/test_operations_backup_restore.py",
            "tests/platform/test_workflow_ledger_recovery.py",
            "tests/platform/test_architecture_boundaries.py",
            "tests/platform/test_acceptance_evidence.py",
            "-m",
            "not release_acceptance",
        ),
    }
    CRITERIA = (
        ("TDK-AC-001", "migration_and_operations", "test_fresh_and_populated_roots_upgrade_idempotently"),
        ("TDK-AC-002", "migration_and_operations", "test_legacy_account_values_unknowns_and_refs_migrate_losslessly"),
        ("TDK-AC-003", "migration_and_operations", "test_active_legacy_plan_requires_explicit_sleeve_mapping"),
        ("TDK-AC-004", "contract", "test_agent_draft_and_user_confirmation_capabilities"),
        ("TDK-AC-005", "contract", "test_optional_unknowns_only_disable_dependent_capabilities"),
        ("TDK-AC-006", "contract", "test_projection_uses_latest_snapshot_and_confirmed_executions_only"),
        ("TDK-AC-007", "contract", "test_new_snapshot_assesses_drift_without_rewriting_history"),
        ("TDK-AC-008", "contract", "test_only_two_builtin_strategy_versions_are_available"),
        ("TDK-AC-009", "contract", "test_database_allows_one_active_master_per_account_security"),
        ("TDK-AC-010", "contract", "test_confirmed_plan_graph_rejects_late_mutation"),
        ("TDK-AC-011", "contract", "test_only_strategy_compatible_core_and_grid_sleeves_are_accepted"),
        ("TDK-AC-012", "contract", "test_grid_sell_cannot_cross_core_floor"),
        ("TDK-AC-013", "contract", "test_ast_v2_operands_sessions_events_and_grid_replay"),
        ("TDK-AC-014", "contract", "test_conflict_precedence_table"),
        ("TDK-AC-015", "contract", "test_agent_denied_and_stale_or_mismatched_challenge_rejected"),
        ("TDK-AC-016", "contract", "test_confirm_and_enable_emits_events_and_receipt_atomically"),
        ("TDK-AC-017", "contract", "test_confirm_only_and_rejected_draft_leave_active_slot_unchanged"),
        ("TDK-AC-018", "contract", "test_skill_cli_and_web_codecs_share_request_hash_and_result_schema"),
        ("TDK-AC-019", "workflow_and_journal", "test_window_uses_last_successful_cutoff_to_selected_complete_session"),
        ("TDK-AC-020", "workflow_and_journal", "test_no_change_creates_no_task"),
        ("TDK-AC-021", "workflow_and_journal", "test_single_grid_trigger_creates_one_persistent_task"),
        ("TDK-AC-022", "workflow_and_journal", "test_all_deferral_conditions_reopen_the_same_task"),
        ("TDK-AC-023", "workflow_and_journal", "test_executed_disposition_updates_estimated_state"),
        ("TDK-AC-024", "workflow_and_journal", "test_overridden_is_identified_and_unrecorded_is_not_skipped"),
        ("TDK-AC-025", "workflow_and_journal", "test_accept_or_reject_proposal_has_only_draft_side_effects"),
        ("TDK-AC-026", "contract", "test_new_activation_preserves_old_version_history"),
        ("TDK-AC-027", "presentation", "test_web_and_skill_serialize_identical_application_dtos"),
        ("TDK-AC-028", "migration_and_operations", "test_restart_replay_is_idempotent"),
        ("TDK-AC-029", "migration_and_operations", "test_full_chain_rebuilds_after_restore"),
        ("TDK-AC-030", "workflow_and_journal", "test_missing_broker_evidence_is_unverified_not_not_executed"),
        ("TDK-AC-031", "presentation", "test_navigation_home_allowlist_progressive_disclosure_and_accessibility"),
        ("TDK-AC-032", "presentation", "test_unversioned_workspace_and_public_daily_routes_are_absent"),
        ("TDK-AC-033", "migration_and_operations", "test_business_import_graph_has_no_llm_order_or_scheduler_surface"),
        ("TDK-AC-034", "contract", "test_all_mutations_cross_named_tasks_and_envelope"),
        ("TDK-AC-035", "migration_and_operations", "test_report_preserves_exact_failure_timeout_and_external_status"),
    )

    def __init__(
        self,
        data_root: Path,
        repo_root: Path,
        receipt_loader: Callable[[str], bytes] | None = None,
    ) -> None:
        self.data_root = data_root.resolve()
        self.repo_root = repo_root.resolve()
        self._receipt_loader = receipt_loader

    def run(
        self,
        fixture_manifest_path: Path,
        live_qualification_artifact_id: str | None = None,
    ) -> AcceptanceEvidenceResult:
        fixture = self._load_fixture(fixture_manifest_path)
        live = self._live_status(live_qualification_artifact_id)
        evidence_root = (
            self.repo_root
            / ".scratch"
            / "trading-discipline-kernel"
            / "evidence"
            / "acceptance"
        )
        evidence_root.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, dict[str, Any]] = {}

        browser_path = evidence_root / "browser-cdp.json"
        browser = self._run_browser(browser_path)
        if browser["status"] == "passed":
            self.validate_browser_evidence(browser_path)
            artifacts["browser_cdp"] = self._artifact(browser_path)
            screenshot_root = browser_path.parent / "browser-cdp-screenshots"
            for name in ("overview", "portfolio", "review", "research"):
                artifacts[f"browser_{name}"] = self._artifact(
                    screenshot_root / f"{name}.png"
                )

        suites: list[dict[str, Any]] = []
        for name in self.REQUIRED_SUITES:
            suite = self._run_pytest_suite(
                name,
                self.SUITE_PLAN[name],
                evidence_root,
            )
            suites.append(suite)
            artifacts[name] = self._artifact(
                evidence_root / f"{name}.json"
            )

        migration_hashes = {
            path.name: _sha256(path)
            for path in (
                self.repo_root / "migrations" / "0015_account_snapshot_version.sql",
                self.repo_root / "migrations" / "0016_strategy_plan_model_b.sql",
                self.repo_root / "migrations" / "0017_manual_review_journal.sql",
            )
        }
        migration_manifest = evidence_root / "migration-hashes.json"
        migration_manifest.write_text(
            json.dumps(
                {
                    "schema_version": "KernelMigrationHashEvidence@1",
                    "expected_versions": [15, 16, 17],
                    "script_sha256": migration_hashes,
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        artifacts["migration_manifest"] = self._artifact(migration_manifest)
        for name, filename in (
            ("restart_replay", "restart-replay.json"),
            ("backup_restore", "backup-restore.json"),
            ("architecture_import_graph", "architecture-import-graph.json"),
            (
                "acceptance_status_semantics",
                "acceptance-status-semantics.json",
            ),
        ):
            candidate = evidence_root / filename
            if candidate.is_file():
                artifacts[name] = self._artifact(candidate)
        criteria = self._criteria(suites, browser["status"])
        supplied = {
            "fixture": fixture,
            "criteria": criteria,
            "suites": suites,
            "browser": browser,
            "artifacts": artifacts,
            "migration_hashes": migration_hashes,
            "external_checks": (live,),
        }
        return self._freeze(supplied)

    def _load_fixture(self, path: Path) -> dict[str, Any]:
        trusted_root = (
            self.repo_root / "tests" / "fixtures" / "trading_discipline_kernel"
        ).resolve()
        fixture_path = path.resolve()
        if (
            fixture_path.parent != trusted_root
            or fixture_path.name != "expected-manifest.json"
        ):
            raise ValueError("FIXTURE_MANIFEST_OUTSIDE_TRUSTED_ROOT")
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("FIXTURE_MANIFEST_INVALID") from error
        if (
            fixture.get("schema_version") != self.FIXTURE_SCHEMA_VERSION
            or fixture.get("securities") != ["002897.SZ", "600183.SH"]
            or fixture.get("step_count") != 20
        ):
            raise ValueError("FIXTURE_MANIFEST_INVALID")
        for member in fixture.get("members", ()):
            relative = Path(str(member.get("path", "")))
            target = (trusted_root / relative).resolve()
            if (
                trusted_root not in target.parents
                or not target.is_file()
                or _sha256(target) != member.get("sha256")
            ):
                raise ValueError("FIXTURE_MEMBER_HASH_MISMATCH")
        fixture["manifest_sha256"] = _sha256(fixture_path)
        return fixture

    def _run_browser(self, path: Path) -> dict[str, Any]:
        command = [
            os.sys.executable,
            str(self.repo_root / "scripts" / "verify_issue05_browser.py"),
            "--evidence-file",
            str(path),
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=300,
            )
            status = "passed" if completed.returncode == 0 else "failed"
            exit_code = completed.returncode
            output = "\n".join(
                part for part in (completed.stdout, completed.stderr) if part
            )
        except subprocess.TimeoutExpired as error:
            status = "timeout"
            exit_code = None
            output = "\n".join(
                str(part)
                for part in (error.stdout, error.stderr)
                if part
            )
        return {
            "name": "browser_cdp",
            "status": status,
            "duration_seconds": round(time.monotonic() - started, 3),
            "exit_code": exit_code,
            "output_tail": VerificationOutputRedactor().redact(output)[-2000:],
            "command_identity": canonical_hash(
                [
                    "python",
                    "scripts/verify_issue05_browser.py",
                    "--evidence-file",
                    "<evidence-root>",
                ]
            ),
        }

    def _run_pytest_suite(
        self,
        name: str,
        plan: Sequence[str],
        evidence_root: Path,
    ) -> dict[str, Any]:
        junit_path = evidence_root / f"{name}.xml"
        artifact_path = evidence_root / f"{name}.json"
        command = [
            os.sys.executable,
            "-m",
            "pytest",
            *plan,
            "-q",
            f"--junitxml={junit_path}",
            f"--basetemp={evidence_root / (name + '-tmp')}",
        ]
        environment = os.environ.copy()
        environment["TDK_ACCEPTANCE_EVIDENCE_ROOT"] = str(evidence_root)
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=600,
            )
            exit_code = completed.returncode
            output = "\n".join(
                part for part in (completed.stdout, completed.stderr) if part
            )
        except subprocess.TimeoutExpired as error:
            timed_out = True
            exit_code = None
            output = "\n".join(
                str(part)
                for part in (error.stdout, error.stderr)
                if part
            )
        collected, skipped, failed, assertion_ids = self._parse_junit(junit_path)
        if timed_out:
            status = "timeout"
        elif exit_code == 0 and collected > 0 and skipped == 0 and failed == 0:
            status = "passed"
        else:
            status = "failed"
        suite = {
            "name": name,
            "status": status,
            "duration_seconds": round(time.monotonic() - started, 3),
            "exit_code": exit_code,
            "collected": collected,
            "passed": max(collected - skipped - failed, 0),
            "failed": failed,
            "skipped": skipped,
            "timed_out": timed_out,
            "assertion_ids": assertion_ids,
            "command_identity": canonical_hash(list(plan)),
            "artifact_refs": [name],
            "first_failing_substep": (
                None
                if status == "passed"
                else next(
                    (
                        line
                        for line in output.splitlines()
                        if "FAILED " in line or "ERROR " in line
                    ),
                    "suite_timeout" if timed_out else "suite_process",
                )
            ),
            "output_tail": VerificationOutputRedactor().redact(output)[-2000:],
        }
        artifact_path.write_text(
            json.dumps(suite, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return suite

    def _criteria(
        self,
        suites: Sequence[Mapping[str, Any]],
        browser_status: str,
    ) -> list[dict[str, Any]]:
        by_name = {str(item["name"]): item for item in suites}
        criteria: list[dict[str, Any]] = []
        for criterion, suite_name, pattern in self.CRITERIA:
            suite = by_name[suite_name]
            matched = [
                assertion
                for assertion in suite["assertion_ids"]
                if pattern in assertion
            ]
            passed = suite["status"] == "passed" and bool(matched)
            artifact_refs = [suite_name]
            if criterion in {"TDK-AC-001", "TDK-AC-002", "TDK-AC-003"}:
                artifact_refs.append("migration_manifest")
            if criterion == "TDK-AC-028":
                artifact_refs.append("restart_replay")
            if criterion == "TDK-AC-029":
                artifact_refs.append("backup_restore")
            if criterion == "TDK-AC-031":
                passed = passed and browser_status == "passed"
                artifact_refs.append("browser_cdp")
            if criterion == "TDK-AC-033":
                artifact_refs.append("architecture_import_graph")
            if criterion == "TDK-AC-035":
                artifact_refs.append("acceptance_status_semantics")
            criteria.append(
                {
                    "criterion": criterion,
                    "status": "passed" if passed else "failed",
                    "suite": suite_name,
                    "assertion_ids": matched,
                    "artifact_refs": artifact_refs,
                }
            )
        return criteria

    def _live_status(self, artifact_id: str | None) -> dict[str, Any]:
        if artifact_id is None:
            return {
                "name": "live_provider_qualification",
                "status": "not_applicable",
                "reason": "synthetic_offline_kernel_acceptance",
            }
        if self._receipt_loader is None:
            raise ValueError("QUALIFICATION_RECEIPT_STORE_UNAVAILABLE")
        receipt = decode_provider_qualification_receipt(
            self._receipt_loader(artifact_id),
            artifact_id,
        ).to_dict()
        return {
            "name": "live_provider_qualification",
            "status": receipt["status"],
            "artifact_id": artifact_id,
            "provider_identity": receipt.get("provider_identity"),
        }

    def _freeze(self, supplied: Mapping[str, Any]) -> AcceptanceEvidenceResult:
        failures: list[str] = []
        suites = list(supplied.get("suites", ()))
        criteria = list(supplied.get("criteria", ()))
        browser = supplied.get("browser")
        external_checks = list(supplied.get("external_checks", ()))
        expected_criteria = {item[0] for item in self.CRITERIA}
        if (
            {item.get("name") for item in suites} != set(self.REQUIRED_SUITES)
            or len(suites) != len(self.REQUIRED_SUITES)
        ):
            failures.append("SUITE_LEDGER_INCOMPLETE")
        if (
            {item.get("criterion") for item in criteria} != expected_criteria
            or len(criteria) != 35
        ):
            failures.append("ACCEPTANCE_CRITERIA_INCOMPLETE")
        if any(item.get("status") != "passed" for item in suites):
            failures.append("LOCAL_SUITE_NOT_PASSED")
        if any(item.get("status") != "passed" for item in criteria):
            failures.append("LOCAL_CRITERION_NOT_PASSED")
        if not isinstance(browser, Mapping) or browser.get("status") != "passed":
            failures.append("BROWSER_CDP_NOT_PASSED")
        for item in suites:
            if item.get("status") == "passed" and (
                item.get("exit_code") != 0
                or item.get("collected", 0) < 1
                or item.get("skipped") != 0
                or item.get("failed") != 0
                or item.get("timed_out") is not False
            ):
                failures.append("SUITE_STATUS_INCONSISTENT")

        artifact_evidence: dict[str, dict[str, Any]] = {}
        for name, item in dict(supplied.get("artifacts", {})).items():
            path = Path(str(item.get("path", "")))
            if (
                not path.is_file()
                or _sha256(path) != item.get("sha256")
                or path.stat().st_size != item.get("size")
            ):
                failures.append("ARTIFACT_EVIDENCE_INVALID")
                continue
            artifact_evidence[name] = {
                "sha256": item["sha256"],
                "size": item["size"],
            }
        required_refs = {
            ref
            for item in (*criteria, *suites)
            for ref in item.get("artifact_refs", ())
        }
        if not required_refs.issubset(artifact_evidence):
            failures.append("ARTIFACT_REFERENCE_MISSING")

        status = "failed" if failures else "passed"
        code_identity = asdict(
            build_code_identity(
                self.repo_root,
                {
                    "acceptance_schema": self.SCHEMA_VERSION,
                    "fixture_manifest": supplied.get("fixture", {}).get(
                        "manifest_sha256"
                    ),
                },
            )
        )
        manifest = {
            "acceptance_schema_version": self.SCHEMA_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "acceptance_identity": canonical_hash(
                {
                    "schema": self.SCHEMA_VERSION,
                    "code": code_identity,
                    "fixture": supplied.get("fixture"),
                    "suites": [
                        {
                            key: item.get(key)
                            for key in (
                                "name",
                                "status",
                                "exit_code",
                                "collected",
                                "passed",
                                "failed",
                                "skipped",
                                "timed_out",
                                "assertion_ids",
                                "command_identity",
                            )
                        }
                        for item in suites
                    ],
                    "criteria": criteria,
                    "browser": (
                        {
                            key: browser.get(key)
                            for key in (
                                "name",
                                "status",
                                "exit_code",
                                "command_identity",
                            )
                        }
                        if isinstance(browser, Mapping)
                        else browser
                    ),
                    "migration_hashes": supplied.get("migration_hashes"),
                    "external_checks": external_checks,
                }
            ),
            "code_identity": code_identity,
            "environment": {
                "os": platform.platform(),
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
            },
            "fixture": supplied.get("fixture"),
            "migration_hashes": supplied.get("migration_hashes"),
            "suites": suites,
            "criteria": criteria,
            "browser": browser,
            "external_checks": external_checks,
            "artifact_evidence": artifact_evidence,
            "trading_discipline_kernel_acceptance": status,
            "trading_discipline_kernel_complete": status == "passed",
            "failure_codes": sorted(set(failures)),
        }
        payload = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        evidence_root = (
            self.repo_root
            / ".scratch"
            / "trading-discipline-kernel"
            / "evidence"
            / "acceptance"
        )
        evidence_root.mkdir(parents=True, exist_ok=True)
        target = evidence_root / f"acceptance-{digest}.json"
        if target.exists() and target.read_bytes() != payload:
            raise RuntimeError("ACCEPTANCE_EVIDENCE_HASH_COLLISION")
        if not target.exists():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".acceptance-",
                dir=evidence_root,
            )
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
        if (
            _sha256(target) != digest
            or verified.get("acceptance_schema_version") != self.SCHEMA_VERSION
            or len(verified.get("criteria", ())) != 35
            or target.stat().st_mode & stat.S_IWUSR
        ):
            raise RuntimeError("ACCEPTANCE_SELF_VERIFICATION_FAILED")
        return AcceptanceEvidenceResult(status, digest, target)

    @staticmethod
    def _artifact(path: Path) -> dict[str, Any]:
        return {
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }

    def validate_browser_evidence(self, path: Path) -> Mapping[str, Any]:
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("BROWSER_EVIDENCE_INVALID") from error
        verifier = evidence.get("verifier") if isinstance(evidence, Mapping) else None
        browser = evidence.get("browser") if isinstance(evidence, Mapping) else None
        initial = evidence.get("initial") if isinstance(evidence, Mapping) else None
        routes = evidence.get("routes_and_headers") if isinstance(evidence, Mapping) else None
        headers = routes.get("headers") if isinstance(routes, Mapping) else None
        screenshots = evidence.get("screenshots") if isinstance(evidence, Mapping) else None
        plan = evidence.get("plan_progressive_disclosure") if isinstance(evidence, Mapping) else None
        editor = evidence.get("account_editor") if isinstance(evidence, Mapping) else None
        expected_source_hash = _sha256(
            self.repo_root / "scripts/verify_issue05_browser.py"
        )
        expected_command_identity = hashlib.sha256(
            json.dumps(
                [
                    "python",
                    "scripts/verify_issue05_browser.py",
                    "--evidence-file",
                    "<redacted>",
                ],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        product = browser.get("product", "") if isinstance(browser, Mapping) else ""
        expected_navigation = ["总览", "组合", "复核", "研究"]
        expected_groups = [
            "account-summary",
            "task-summary",
            "change-summary",
            "plan-summary",
            "exception-summary",
        ]
        expected_home_keys = sorted(
            [
                "account_state_summary",
                "unresolved_decision_tasks",
                "material_changes_since_last_review",
                "holding_active_plan_summaries",
                "discipline_exception_summary",
            ]
        )
        expected_retired = {
            "/api/workspace",
            "/daily",
            "/api/daily",
            "/api/chart-series",
            "/api/annotations",
            "/api/update-authorizations",
        }

        def screenshot_valid(name: str) -> bool:
            if not isinstance(screenshots, Mapping):
                return False
            item = screenshots.get(name)
            if not isinstance(item, Mapping):
                return False
            filename = item.get("name")
            if not isinstance(filename, str) or filename != f"{name}.png":
                return False
            target = path.parent / "browser-cdp-screenshots" / filename
            return (
                target.is_file()
                and item.get("size") == target.stat().st_size
                and item.get("sha256") == _sha256(target)
            )

        valid = (
            evidence.get("schema_version") == "BrowserAcceptanceEvidence@1"
            and evidence.get("status") == "passed"
            and isinstance(verifier, Mapping)
            and verifier.get("identity") == "production-browser-cdp@1"
            and verifier.get("source_sha256") == expected_source_hash
            and verifier.get("command_identity") == expected_command_identity
            and isinstance(browser, Mapping)
            and isinstance(product, str)
            and ("Chrome/" in product or "Edg/" in product)
            and bool(browser.get("protocol_version"))
            and isinstance(initial, Mapping)
            and initial.get("navigation") == expected_navigation
            and initial.get("homeGroups") == expected_groups
            and initial.get("external") == []
            and all(initial.get(name) is True for name in ("unknownVisible", "skipLink", "mainFocusable", "oneH1", "dialogLabels"))
            and isinstance(routes, Mapping)
            and routes.get("schema") == "PortfolioWorkspaceView@1"
            and routes.get("homeKeys") == expected_home_keys
            and isinstance(routes.get("retired"), Mapping)
            and set(routes["retired"]) == expected_retired
            and set(routes["retired"].values()) == {404}
            and isinstance(headers, Mapping)
            and "default-src 'self'" in headers.get("csp", "")
            and headers.get("nosniff") == "nosniff"
            and headers.get("referrer") == "no-referrer"
            and headers.get("opener") == "same-origin"
            and isinstance(plan, Mapping)
            and all(plan.get(name) is True for name in ("open", "rules", "diagnosticsClosed"))
            and isinstance(editor, Mapping)
            and editor.get("draftSaved") is True
            and editor.get("confirmDisabled") is True
            and "已确认 v2" in editor.get("summary", "")
            and editor.get("detailsClosed") is True
            and all(evidence.get(name) is True for name in ("responsive", "reduced_motion"))
            and all(screenshot_valid(name) for name in ("overview", "portfolio", "review", "research"))
            and "已确认 v2" in evidence.get("restart_state", "")
            and evidence.get("console_errors") == []
            and evidence.get("network_failures") == []
        )
        if not valid:
            raise ValueError("BROWSER_EVIDENCE_INVALID")
        return evidence

    @staticmethod
    def _parse_junit(path: Path) -> tuple[int, int, int, list[str]]:
        if not path.is_file():
            return 0, 0, 0, []
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        cases = (
            list(root.findall("testcase"))
            if root.tag == "testsuites" and not suites
            else [case for suite in suites for case in suite.findall("testcase")]
        )
        collected = (
            len(cases)
            if cases
            else sum(int(item.attrib.get("tests", "0")) for item in suites)
        )
        skipped = sum(1 for case in cases if case.find("skipped") is not None)
        failed = sum(
            1
            for case in cases
            if case.find("failure") is not None or case.find("error") is not None
        )
        assertions = [
            f"{case.attrib.get('classname')}::{case.attrib.get('name')}"
            for case in cases
        ]
        return collected, skipped, failed, assertions
