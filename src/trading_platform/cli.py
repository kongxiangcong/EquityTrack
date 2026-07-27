from __future__ import annotations

import argparse
import json
import shutil
import sys
import sqlite3
import threading
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from trading_platform.application import (
    open_acceptance_evidence,
    open_account_current_export,
    open_account_acceptance,
    open_account_history,
    open_data_synchronization,
    open_import_preview,
    open_market,
    open_application_commands,
    open_platform_health,
    open_platform_operations,
    open_project_verification,
    open_provider_qualification,
    open_research_archive,
    open_research_workflow,
    open_server_runtime,
    open_watchlist,
    open_chart_annotations,
    open_chart_workspace,
    open_decision_workspace,
    open_update_authorizations,
    open_workflow_inspection,
    open_workflow_runtime,
    HealthQuery,
    ResumeWorkflowCommand,
    StartResearchWorkflow,
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    decode_research_workflow_request,
)
from trading_platform.operations import OperationError
from trading_platform.web_server import LocalChartWorkspaceServer


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise OperationError("CLI_ARGUMENT_INVALID", message)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="trading-platform")
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("bootstrap", "doctor", "migrate", "health"):
        command = sub.add_parser(name)
        command.add_argument("--data-root", type=Path, required=True)
        if name == "doctor":
            command.add_argument("--job-file", type=Path)
    backup = sub.add_parser("backup")
    backup.add_argument("--data-root", type=Path, required=True)
    backup.add_argument("--archive", type=Path, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--target-root", type=Path, required=True)
    switch = sub.add_parser("switch-restored-root")
    switch.add_argument("--restored-root", type=Path, required=True)
    switch.add_argument("--pointer-file", type=Path, required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--data-root", type=Path, required=True)
    resume.add_argument("--workflow-run-id", required=True)
    resume.add_argument("--owner-token", required=True)
    history = sub.add_parser("history")
    history.add_argument("--data-root", type=Path, required=True)
    history.add_argument("--workflow-run-id", required=True)
    research = sub.add_parser("research")
    research.add_argument("--data-root", type=Path, required=True)
    research.add_argument("--request-file", type=Path, required=True)
    archive = sub.add_parser("archive")
    archive.add_argument("--data-root", type=Path, required=True)
    archive.add_argument(
        "--kind", choices=("manifest", "artifact", "source"), required=True
    )
    archive.add_argument("--id", required=True)
    application_command = sub.add_parser("application-command")
    application_command.add_argument("--data-root", type=Path, required=True)
    application_command.add_argument("--envelope-file", type=Path, required=True)
    watch_list = sub.add_parser("watchlist-list")
    watch_list.add_argument("--data-root", type=Path, required=True)
    market_show = sub.add_parser("market-show")
    market_show.add_argument("--data-root", type=Path, required=True)
    market_show.add_argument("--market-snapshot-id", required=True)
    evaluation_show = sub.add_parser("evaluation-show")
    evaluation_show.add_argument("--data-root", type=Path, required=True)
    evaluation_show.add_argument("--evaluation-id", required=True)
    for name in ("sync",):
        command = sub.add_parser(name)
        command.add_argument("--data-root", type=Path, required=True)
        command.add_argument("--job-file", type=Path, required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--data-root", type=Path, required=True)
    serve.add_argument("--web-root", type=Path, required=True)
    serve.add_argument("--security-id", required=True)
    serve.add_argument("--snapshot-id", required=True)
    test = sub.add_parser("test")
    test.add_argument("--repo-root", type=Path, default=Path.cwd())
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--repo-root", type=Path, default=Path.cwd())
    acceptance = sub.add_parser("acceptance")
    acceptance.add_argument("--data-root", type=Path, required=True)
    acceptance.add_argument("--fixture-manifest", type=Path, required=True)
    acceptance.add_argument("--repo-root", type=Path, default=Path.cwd())
    acceptance.add_argument("--live-qualification-artifact-id")
    qualify = sub.add_parser("provider-qualify")
    qualify.add_argument("--data-root", type=Path, required=True)
    qualify.add_argument("--job-file", type=Path, required=True)
    preview = sub.add_parser("import-preview")
    preview.add_argument("--source", type=Path, action="append", required=True)
    preview.add_argument("--account-alias", required=True)
    preview.add_argument("--base-currency", required=True)
    preview.add_argument("--private-root", type=Path)
    preview.add_argument("--trading-session", action="append", default=[])
    preview.add_argument("--repo-root", type=Path, default=Path.cwd())
    initialize = sub.add_parser("account-current-export-draft")
    initialize.add_argument("--data-root", type=Path, required=True)
    initialize.add_argument("--source", type=Path, action="append", required=True)
    initialize.add_argument("--account-alias", required=True)
    initialize.add_argument("--base-currency", required=True)
    initialize.add_argument("--selected-as-of", required=True)
    initialize.add_argument("--private-root", type=Path, required=True)
    initialize.add_argument("--trading-session", action="append", required=True)
    initialize.add_argument("--invocation-id", required=True)
    initialize.add_argument("--repo-root", type=Path, default=Path.cwd())
    account_show = sub.add_parser("account-current-export-draft-show")
    account_show.add_argument("--data-root", type=Path, required=True)
    account_show.add_argument("--account-id", required=True)
    account_show.add_argument("--repo-root", type=Path, default=Path.cwd())
    history_import = sub.add_parser("account-history-import")
    history_import.add_argument("--data-root", type=Path, required=True)
    history_import.add_argument("--account-id", required=True)
    history_import.add_argument("--source", type=Path, action="append", required=True)
    history_import.add_argument("--private-root", type=Path, required=True)
    history_import.add_argument("--trading-session", action="append", default=[])
    history_import.add_argument("--invocation-id", required=True)
    history_import.add_argument("--repo-root", type=Path, default=Path.cwd())
    account_acceptance = sub.add_parser("account-acceptance")
    account_acceptance.add_argument("--data-root", type=Path, required=True)
    account_acceptance.add_argument("--account-id", required=True)
    account_acceptance.add_argument(
        "--suite-artifact", type=Path, action="append", required=True
    )
    account_acceptance.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    operation = "unknown"
    try:
        args = _parser().parse_args(argv)
        operation = args.operation
        if operation in {"bootstrap", "doctor", "migrate"}:
            operations = open_platform_operations(args.data_root)
            if operation == "bootstrap":
                result = operations.bootstrap()
            elif operation == "doctor":
                result = operations.doctor(args.job_file)
            else:
                result = operations.migrate()
        elif operation == "health":
            with open_platform_health(args.data_root) as health:
                result = asdict(health.inspect(HealthQuery()))
        elif operation == "research":
            request = decode_research_workflow_request(args.request_file.read_bytes())
            with open_research_workflow(args.data_root) as workflow:
                result = asdict(workflow.handle(StartResearchWorkflow(request)))
        elif operation == "archive":
            with open_research_archive(args.data_root) as archive_task:
                if args.kind == "manifest":
                    result = asdict(archive_task.manifest(args.id))
                elif args.kind == "artifact":
                    result = asdict(archive_task.artifact(args.id))
                else:
                    result = dict(archive_task.source_payload(args.id))
        elif operation == "application-command":
            command = ApplicationCommandEnvelopeV1.from_bytes(
                args.envelope_file.read_bytes()
            )
            with open_application_commands(args.data_root) as dispatcher:
                dispatched = dispatcher.dispatch(command)
            if isinstance(dispatched, ApplicationCommandFailure):
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "operation": operation,
                            "error": asdict(dispatched),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 2
            result = asdict(dispatched)
        elif operation == "watchlist-list":
            with open_watchlist(args.data_root) as watchlist:
                result = {"items": [asdict(item) for item in watchlist.list()]}
        elif operation in {
            "market-show",
            "evaluation-show",
        }:
            with open_market(args.data_root) as market_task:
                if operation == "market-show":
                    result = asdict(
                        market_task.get_market_snapshot(args.market_snapshot_id)
                    )
                else:
                    result = asdict(market_task.get_plan_evaluation(args.evaluation_id))
        elif operation == "backup":
            result = open_platform_operations(args.data_root).backup(args.archive)
        elif operation == "restore":
            result = open_platform_operations(args.target_root).restore(
                args.archive, args.target_root
            )
        elif operation == "switch-restored-root":
            result = open_platform_operations(args.restored_root).switch_restored_root(
                args.restored_root, args.pointer_file
            )
        elif operation == "sync":
            with open_data_synchronization(
                args.data_root, args.job_file
            ) as synchronization:
                result = asdict(synchronization.run())
        elif operation == "test":
            npm_executable = shutil.which("npm.cmd") or shutil.which("npm")
            if npm_executable is None:
                raise OperationError(
                    "NPM_UNAVAILABLE", "The Web test runtime is unavailable."
                )
            event_lock = threading.Lock()

            def emit(event: dict[str, object]) -> None:
                with event_lock:
                    print(
                        json.dumps(event, ensure_ascii=True, sort_keys=True),
                        file=sys.stderr,
                        flush=True,
                    )

            report = open_project_verification(npm_executable).run(args.repo_root, emit)
            result = report.to_dict()
            envelope: dict[str, object] = {
                "ok": report.status == "passed",
                "operation": operation,
                "result": result,
            }
            if report.status != "passed":
                envelope["error"] = {
                    "code": "TEST_FAILED",
                    "message": "One or more named test suites failed.",
                }
            print(json.dumps(envelope, ensure_ascii=True, sort_keys=True))
            return 0 if report.status == "passed" else 2
        elif operation == "inventory":
            result = open_platform_operations(args.repo_root).dependency_inventory(
                args.repo_root
            )
        elif operation == "provider-qualify":
            with open_provider_qualification(
                args.data_root, args.job_file
            ) as qualification_task:
                qualification = qualification_task.run()
            result = qualification.to_dict()
            if qualification.status != "qualified":
                raise OperationError(
                    "PROVIDER_QUALIFICATION_FAILED",
                    "Provider qualification did not pass.",
                )
        elif operation == "acceptance":
            evidence = open_acceptance_evidence(args.data_root, args.repo_root).run(
                args.fixture_manifest, args.live_qualification_artifact_id
            )
            result = {
                "slice_acceptance": evidence.slice_acceptance,
                "manifest_sha256": evidence.manifest_sha256,
                "manifest_ref": evidence.manifest_path.name,
            }
            print(
                json.dumps(
                    {
                        "ok": evidence.slice_acceptance == "passed",
                        "operation": operation,
                        "result": result,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0 if evidence.slice_acceptance == "passed" else 2
        elif operation == "import-preview":
            result = (
                open_import_preview(args.repo_root)
                .preview(
                    args.source,
                    args.account_alias,
                    args.base_currency,
                    args.private_root,
                    args.trading_session,
                )
                .to_safe_dict()
            )
        elif operation == "account-current-export-draft":
            result = asdict(
                open_account_current_export(args.data_root, args.repo_root).initialize(
                    args.invocation_id,
                    args.source,
                    args.account_alias,
                    args.base_currency,
                    args.selected_as_of,
                    args.private_root,
                    args.trading_session,
                )
            )
        elif operation == "account-current-export-draft-show":
            result = asdict(
                open_account_current_export(args.data_root, args.repo_root).get_detail(args.account_id)
            )
        elif operation == "account-history-import":
            result = asdict(
                open_account_history(args.data_root, args.repo_root).import_history(
                    args.invocation_id,
                    args.account_id,
                    args.source,
                    args.private_root,
                    args.trading_session,
                )
            )
        elif operation == "account-acceptance":
            result = {
                "manifest": open_account_acceptance(
                    args.data_root, args.repo_root / "migrations"
                )
                .write_manifest(args.account_id, tuple(args.suite_artifact))
                .name
            }
        elif operation == "serve":
            with (
                open_decision_workspace(args.data_root) as decision_workspace,
                open_chart_workspace(args.data_root) as chart_workspace,
                open_chart_annotations(args.data_root) as chart_annotations,
                open_update_authorizations(args.data_root) as update_authorizations,
            ):
                server = LocalChartWorkspaceServer(
                    decision_workspace=decision_workspace,
                    chart_workspace=chart_workspace,
                    chart_annotations=chart_annotations,
                    update_authorizations=update_authorizations,
                    web_root=args.web_root,
                    security_id=args.security_id,
                    snapshot_id=args.snapshot_id,
                )
                try:
                    with open_server_runtime(args.data_root):
                        url = server.start()
                        print(
                            json.dumps(
                                {
                                    "ok": True,
                                    "operation": operation,
                                    "result": {"status": "serving", "url": url},
                                },
                                sort_keys=True,
                            ),
                            flush=True,
                        )
                        threading.Event().wait()
                except KeyboardInterrupt:
                    pass
                finally:
                    server.close()
            return 0
        else:
            if operation == "resume":
                with open_research_workflow(args.data_root) as workflow:
                    with open_workflow_runtime(args.data_root):
                        result = asdict(
                            workflow.handle(
                                ResumeWorkflowCommand(
                                    args.workflow_run_id, args.owner_token
                                )
                            )
                        )
            else:
                with open_workflow_inspection(args.data_root) as inspection:
                    result = asdict(inspection.inspect(args.workflow_run_id))
        if (
            operation in {"bootstrap", "doctor", "migrate"}
            and result.get("status") != "passed"
        ):
            raise OperationError(
                (
                    "DOCTOR_FAILED"
                    if operation != "migrate"
                    else "MIGRATION_VALIDATION_FAILED"
                ),
                ",".join(result.get("errors", ())),
            )
        print(
            json.dumps(
                {"ok": True, "operation": operation, "result": result},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )
        return 0
    except (
        OperationError,
        ValueError,
        KeyError,
        RuntimeError,
        OSError,
        sqlite3.DatabaseError,
        zipfile.BadZipFile,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ) as error:
        code = getattr(error, "code", type(error).__name__.upper())
        diagnostic = {
            name: getattr(error, name)
            for name in (
                "substep",
                "cause_type",
                "workflow_run_id",
                "exit_code",
                "command_identity",
                "output_tail",
            )
            if getattr(error, name, None) is not None
        }
        payload = {
            "code": code,
            "message": "Operation failed; inspect the typed code and local diagnostics.",
        }
        if diagnostic:
            payload["diagnostic"] = diagnostic
        print(
            json.dumps(
                {"ok": False, "operation": operation, "error": payload},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "operation": operation,
                    "error": {
                        "code": "UNEXPECTED_OPERATION_FAILURE",
                        "message": "Operation failed; inspect local diagnostics.",
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
