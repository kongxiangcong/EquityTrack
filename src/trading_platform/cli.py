from __future__ import annotations

import argparse
import json
import sys
import subprocess
import sqlite3
import zipfile
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

from trading_platform import ProductionCompositionRoot
from trading_platform.application.contracts import ResumeWorkflowCommand
from trading_platform.operations import OperationError, PlatformOperations
from trading_platform.data.providers import HttpJsonProvider
from trading_platform.domain.data import SnapshotPurpose, SyncRequest
from trading_platform.web_server import LocalChartWorkspaceServer
from trading_platform.persistence.presence import RuntimePresence
from trading_platform.credentials import CredentialAdapter, EnvironmentCredentialAdapter
from trading_platform.workflows.research import decode_research_workflow_request
from trading_platform.application.market_contracts import BuildMarketSnapshotCommand, EvaluatePlanCommand
from trading_platform.identity.code import CodeIdentity
from trading_platform.acceptance import AcceptanceEvidenceService
from trading_platform.account_import import TonghuashunImportPreviewer
from trading_platform.account import AccountOpeningService


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise OperationError("CLI_ARGUMENT_INVALID", message)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="trading-platform")
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("bootstrap", "doctor", "migrate"):
        command = sub.add_parser(name); command.add_argument("--data-root", type=Path, required=True)
        if name == "doctor": command.add_argument("--job-file", type=Path)
    backup = sub.add_parser("backup"); backup.add_argument("--data-root", type=Path, required=True); backup.add_argument("--archive", type=Path, required=True)
    restore = sub.add_parser("restore"); restore.add_argument("--archive", type=Path, required=True); restore.add_argument("--target-root", type=Path, required=True)
    switch = sub.add_parser("switch-restored-root"); switch.add_argument("--restored-root", type=Path, required=True); switch.add_argument("--pointer-file", type=Path, required=True)
    resume = sub.add_parser("resume"); resume.add_argument("--data-root", type=Path, required=True); resume.add_argument("--workflow-run-id", required=True); resume.add_argument("--owner-token", required=True)
    history = sub.add_parser("history"); history.add_argument("--data-root", type=Path, required=True); history.add_argument("--workflow-run-id", required=True)
    for name in ("sync", "daily"):
        command = sub.add_parser(name); command.add_argument("--data-root", type=Path, required=True); command.add_argument("--job-file", type=Path, required=True)
    serve = sub.add_parser("serve"); serve.add_argument("--data-root", type=Path, required=True); serve.add_argument("--web-root", type=Path, required=True); serve.add_argument("--security-id", required=True); serve.add_argument("--snapshot-id", required=True)
    test = sub.add_parser("test"); test.add_argument("--repo-root", type=Path, default=Path.cwd())
    inventory = sub.add_parser("inventory"); inventory.add_argument("--repo-root", type=Path, default=Path.cwd())
    acceptance = sub.add_parser("acceptance"); acceptance.add_argument("--data-root", type=Path, required=True); acceptance.add_argument("--fixture-manifest", type=Path, required=True); acceptance.add_argument("--repo-root", type=Path, default=Path.cwd())
    preview = sub.add_parser("import-preview"); preview.add_argument("--source", type=Path, action="append", required=True); preview.add_argument("--account-alias", required=True); preview.add_argument("--base-currency", required=True); preview.add_argument("--private-root", type=Path); preview.add_argument("--trading-session", action="append", default=[]); preview.add_argument("--repo-root", type=Path, default=Path.cwd())
    initialize = sub.add_parser("account-initialize"); initialize.add_argument("--data-root", type=Path, required=True); initialize.add_argument("--source", type=Path, action="append", required=True); initialize.add_argument("--account-alias", required=True); initialize.add_argument("--base-currency", required=True); initialize.add_argument("--confirmed-as-of", required=True); initialize.add_argument("--private-root", type=Path, required=True); initialize.add_argument("--trading-session", action="append", required=True); initialize.add_argument("--invocation-id", required=True); initialize.add_argument("--repo-root", type=Path, default=Path.cwd())
    account_show = sub.add_parser("account-show"); account_show.add_argument("--data-root", type=Path, required=True); account_show.add_argument("--account-id", required=True); account_show.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def _load_sync_job(job_file: Path, credential_adapter: CredentialAdapter | None = None):
    job = json.loads(job_file.read_text(encoding="utf-8")); provider = job["provider"]
    credential_variable = provider["credential_env"]
    credential = (credential_adapter or EnvironmentCredentialAdapter()).get(credential_variable)
    if not credential: raise OperationError("CREDENTIAL_MISSING", "Configured credential scope is missing.")
    adapter = HttpJsonProvider(provider["provider_id"], provider["adapter_version"], provider["endpoint"], credential, provider["source_identity"], provider["terms_profile"])
    request_data = job["request"]
    request = SyncRequest(request_data["invocation_id"], request_data["security_id"], request_data["provider_security_code"], request_data["requested_date"], datetime.fromisoformat(request_data["as_of_at"]), request_data["market_timezone"], request_data["market"], SnapshotPurpose(request_data["snapshot_purpose"]), tuple(request_data["datasets"]), bool(request_data["network_authorized"]), bool(request_data["offline"]))
    return job, adapter, request


def _sync(data_root: Path, job_file: Path, credential_adapter: CredentialAdapter | None = None):
    _, adapter, request = _load_sync_job(job_file, credential_adapter)
    root = ProductionCompositionRoot(data_root, providers=(adapter,))
    try: return asdict(root.facade.sync_data(request))
    finally: root.close()


def _daily(data_root: Path, job_file: Path, credential_adapter: CredentialAdapter | None = None):
    job, adapter, request = _load_sync_job(job_file, credential_adapter); root = ProductionCompositionRoot(data_root, providers=(adapter,))
    try:
        result: dict[str, object] = {"sync": asdict(root.facade.sync_data(request))}
        if "research_request" in job:
            research = decode_research_workflow_request(json.dumps(job["research_request"]).encode()); result["research"] = asdict(root.facade.run_research_workflow(research))
        if "market" in job:
            market_data = dict(job["market"]); market_data["code_identity"] = CodeIdentity(**market_data["code_identity"])
            market = root.facade.build_market_snapshot(BuildMarketSnapshotCommand(**market_data)); result["market"] = asdict(market)
            if "evaluation" in job:
                evaluation_data = {**job["evaluation"], "market_snapshot_id": market.market_snapshot_id}
                result["evaluation"] = asdict(root.facade.evaluate_plan(EvaluatePlanCommand(**evaluation_data)))
        result["doctor"] = PlatformOperations(data_root).doctor()
        return result
    finally: root.close()


def main(argv: list[str] | None = None) -> int:
    operation = "unknown"
    try:
        args = _parser().parse_args(argv); operation = args.operation
        if operation in {"bootstrap", "doctor", "migrate"}: result = PlatformOperations(args.data_root).doctor(args.job_file) if operation == "doctor" else getattr(PlatformOperations(args.data_root), operation)()
        elif operation == "backup": result = PlatformOperations(args.data_root).backup(args.archive)
        elif operation == "restore": result = PlatformOperations.restore(args.archive, args.target_root)
        elif operation == "switch-restored-root": result = PlatformOperations.switch_restored_root(args.restored_root, args.pointer_file)
        elif operation in {"sync", "daily"}:
            result = _daily(args.data_root, args.job_file) if operation == "daily" else _sync(args.data_root, args.job_file)
        elif operation == "test":
            python = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=args.repo_root, check=False, capture_output=True, text=True)
            node = subprocess.run(["npm.cmd", "test"], cwd=args.repo_root / "web", check=False, capture_output=True, text=True)
            if python.returncode or node.returncode: raise OperationError("TEST_FAILED", "One or more test suites failed.")
            result = {"status": "passed", "python_exit_code": python.returncode, "npm_exit_code": node.returncode}
        elif operation == "inventory": result = PlatformOperations.dependency_inventory(args.repo_root)
        elif operation == "acceptance":
            evidence = AcceptanceEvidenceService(args.data_root, args.repo_root).run(args.fixture_manifest)
            result = {"slice_acceptance": evidence.slice_acceptance, "manifest_sha256": evidence.manifest_sha256, "manifest_ref": evidence.manifest_path.name}
            print(json.dumps({"ok": evidence.slice_acceptance == "passed", "operation": operation, "result": result}, ensure_ascii=False, sort_keys=True))
            return 0 if evidence.slice_acceptance == "passed" else 2
        elif operation == "import-preview":
            result = TonghuashunImportPreviewer(args.repo_root).preview(args.source, args.account_alias, args.base_currency, args.private_root, args.trading_session).to_safe_dict()
        elif operation == "account-initialize":
            result = asdict(AccountOpeningService(args.data_root, args.repo_root).initialize(args.invocation_id, args.source, args.account_alias, args.base_currency, args.confirmed_as_of, args.private_root, args.trading_session))
        elif operation == "account-show":
            result = asdict(AccountOpeningService(args.data_root, args.repo_root).get_detail(args.account_id))
        elif operation == "serve":
            root = ProductionCompositionRoot(args.data_root); server = LocalChartWorkspaceServer(root.facade, args.web_root, args.security_id, args.snapshot_id)
            try:
                with RuntimePresence(args.data_root, "server").acquire():
                    url = server.start(); print(json.dumps({"ok": True, "operation": operation, "result": {"status": "serving", "url": url}}, sort_keys=True), flush=True)
                    import threading; threading.Event().wait()
            except KeyboardInterrupt: pass
            finally: server.close(); root.close()
            return 0
        else:
            root = ProductionCompositionRoot(args.data_root)
            try:
                if operation == "resume":
                    with RuntimePresence(args.data_root, "workflow").acquire(): result = asdict(root.facade.resume_workflow(ResumeWorkflowCommand(args.workflow_run_id, args.owner_token)))
                else: result = asdict(root.facade.get_workflow_history(args.workflow_run_id))
            finally: root.close()
        if operation in {"bootstrap", "doctor", "migrate"} and result.get("status") != "passed":
            raise OperationError("DOCTOR_FAILED" if operation != "migrate" else "MIGRATION_VALIDATION_FAILED", ",".join(result.get("errors", ())))
        if operation == "daily" and result["doctor"]["status"] != "passed":
            raise OperationError("DAILY_DOCTOR_FAILED", ",".join(result["doctor"]["errors"]))
        print(json.dumps({"ok": True, "operation": operation, "result": result}, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    except (OperationError, ValueError, KeyError, RuntimeError, OSError, sqlite3.DatabaseError, zipfile.BadZipFile, TypeError, AttributeError, json.JSONDecodeError) as error:
        code = getattr(error, "code", type(error).__name__.upper())
        print(json.dumps({"ok": False, "operation": operation, "error": {"code": code, "message": "Operation failed; inspect the typed code and local diagnostics."}}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"ok": False, "operation": operation, "error": {"code": "UNEXPECTED_OPERATION_FAILURE", "message": "Operation failed; inspect local diagnostics."}}, ensure_ascii=False, sort_keys=True))
        return 3


if __name__ == "__main__": raise SystemExit(main())
