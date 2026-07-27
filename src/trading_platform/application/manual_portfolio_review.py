from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Protocol

from trading_platform.domain.manual_review import (
    ManualPortfolioReviewCheckpoint,
    ManualPortfolioReviewItem,
    ManualPortfolioReviewManifest,
    ManualPortfolioReviewRun,
    ManualReviewContext,
    ManualReviewError,
    build_review_manifest,
    build_review_items,
    build_review_run,
    prepare_review_manifest,
)
from trading_platform.domain.decision_tasks import (
    DecisionTask,
    finalize_decision_tasks,
    prepare_decision_tasks,
)
from trading_platform.domain.workflow import NodeDefinition, WorkflowDefinition
from trading_platform.identity import canonical_hash

from .account_state import AccountStateQueries, GetEstimatedAccountState
from .workflow_ledger import (
    FinalizeManualReviewWorkflow,
    ManualReviewManifestCommit,
    ManualReviewManifestCommitResult,
    StartWorkflow,
    WorkflowLedgerPort,
)


_WORKFLOW = WorkflowDefinition(
    "manual_portfolio_review",
    "1",
    (
        NodeDefinition(
            "review_holdings",
            "1",
            "StartManualPortfolioReview@1",
            "ManualPortfolioReviewManifest@1",
            (
                "confirmed_account_snapshot",
                "selected_complete_session",
                "active_plan_uniqueness",
            ),
            True,
            "input_fingerprint",
            "resume_failed_items",
            (
                "SELECTED_COMPLETE_SESSION_NOT_PROVEN",
                "MANUAL_REVIEW_GRAPH_CORRUPT",
                "MANUAL_REVIEW_MANIFEST_INVALID",
            ),
        ),
    ),
)


@dataclass(frozen=True)
class StartManualPortfolioReview:
    invocation_id: str
    account_id: str
    requested_at: str
    selected_complete_session: str
    first_window_start_exclusive: str | None
    code_identity: str
    config_identity: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "StartManualPortfolioReview@1"


@dataclass(frozen=True)
class ResumeManualPortfolioReview:
    invocation_id: str
    failed_review_run_id: str
    requested_at: str
    code_identity: str
    config_identity: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str


@dataclass(frozen=True)
class GetManualPortfolioReview:
    review_run_id: str


class ManualPortfolioReviewRepository(Protocol):
    fault_injector: object

    def latest_success(
        self, account_id: str
    ) -> ManualPortfolioReviewRun | None: ...

    def by_invocation(
        self, invocation_id: str
    ) -> ManualPortfolioReviewRun | None: ...

    def receipt_hash(self, invocation_id: str) -> str | None: ...

    def context(
        self, estimated, selected_complete_session: str
    ) -> ManualReviewContext: ...

    def begin(
        self, run: ManualPortfolioReviewRun, invocation_id: str
    ) -> ManualPortfolioReviewRun: ...

    def commit(
        self,
        *,
        run: ManualPortfolioReviewRun,
        items: tuple[ManualPortfolioReviewItem, ...],
        decision_tasks: tuple[DecisionTask, ...],
        checkpoints: tuple[ManualPortfolioReviewCheckpoint, ...],
        manifest: ManualPortfolioReviewManifest,
        invocation_id: str,
        request_hash: str,
        decision_actor: str,
        interaction_channel: str,
        transport_actor: str,
        terminal_status: str,
        completed_at: str,
    ) -> ManualPortfolioReviewRun: ...

    def fail(
        self, review_run_id: str, completed_at: str
    ) -> ManualPortfolioReviewRun: ...

    def get(self, review_run_id: str) -> ManualPortfolioReviewRun: ...

    def manifest(
        self, review_run_id: str
    ) -> ManualPortfolioReviewManifest: ...


class ManualPortfolioReview:
    """Runs one explicit-session portfolio review behind a named task."""

    def __init__(
        self,
        repository: ManualPortfolioReviewRepository,
        account_states: AccountStateQueries,
        ledger: WorkflowLedgerPort,
    ) -> None:
        self._repository = repository
        self._account_states = account_states
        self._ledger = ledger

    def start(
        self, command: StartManualPortfolioReview
    ) -> ManualPortfolioReviewRun:
        if (
            command.schema_version != "StartManualPortfolioReview@1"
            or not command.invocation_id
            or not command.account_id
            or not command.code_identity
            or not command.config_identity
            or command.interaction_channel not in {"skill", "cli"}
            or not command.decision_actor.startswith(("user:", "agent:"))
            or not command.transport_actor.startswith(
                ("user:", "agent:", "adapter:")
            )
        ):
            raise ManualReviewError("MANUAL_REVIEW_COMMAND_INVALID")
        replay = self._repository.by_invocation(command.invocation_id)
        if replay is not None and replay.status in {
            "succeeded",
            "succeeded_with_limits",
            "failed",
        }:
            stored_hash = self._repository.receipt_hash(
                command.invocation_id
            )
            if (
                stored_hash is not None
                and stored_hash != canonical_hash(command)
            ):
                raise ManualReviewError(
                    "MANUAL_REVIEW_INVOCATION_CONFLICT"
                )
            return replay
        request_payload = json.dumps(
            asdict(command),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        request_hash = canonical_hash(command)
        started = self._ledger.start_or_replay(
            StartWorkflow(
                invocation_id=command.invocation_id,
                request_fingerprint=request_hash,
                requested_date=command.requested_at[:10],
                effective_session_date=command.selected_complete_session,
                definition=_WORKFLOW,
                owner_token=f"manual-review:{request_hash[:24]}",
                request_payload=request_payload,
                request_schema=command.schema_version,
            )
        )
        try:
            estimated = self._account_states.get(
                GetEstimatedAccountState(command.account_id)
            )
            context = self._repository.context(
                estimated, command.selected_complete_session
            )
            run = build_review_run(
                workflow_run_id=started.workflow_run_id,
                account_id=command.account_id,
                requested_at=command.requested_at,
                selected_complete_session=command.selected_complete_session,
                first_window_start_exclusive=(
                    command.first_window_start_exclusive
                ),
                prior_successful=self._repository.latest_success(
                    command.account_id
                ),
                context=context,
            )
        except Exception:
            self._ledger.complete(
                FinalizeManualReviewWorkflow(
                    workflow_run_id=started.workflow_run_id,
                    terminal_status="failed",
                    artifact_manifest_id="",
                    completed_at=command.requested_at,
                )
            )
            raise
        run = self._repository.begin(run, command.invocation_id)
        if run.status in {"succeeded", "succeeded_with_limits"}:
            return run
        try:
            items = build_review_items(run, context)
            items, task_seeds = prepare_decision_tasks(run, items)
            completed_at = command.requested_at
            manifest_identity, checkpoints = prepare_review_manifest(
                run=run,
                context=context,
                items=items,
                code_identity=command.code_identity,
                config_identity=command.config_identity,
                created_at=completed_at,
            )
            content_hash = canonical_hash(manifest_identity)
            manifest_id = f"manual_review_manifest_{content_hash[:24]}"
            decision_tasks = finalize_decision_tasks(
                task_seeds, manifest_id
            )
            payload = {
                **manifest_identity,
                "manifest_id": manifest_id,
                "content_hash": content_hash,
            }
            payload_bytes = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            committed = self._ledger.commit_artifacts(
                ManualReviewManifestCommit(
                    workflow_run_id=run.workflow_run_id,
                    payload=payload_bytes,
                    content_hash=canonical_hash(payload),
                )
            )
            if not isinstance(
                committed, ManualReviewManifestCommitResult
            ):
                raise ManualReviewError(
                    "MANUAL_REVIEW_MANIFEST_COMMIT_INVALID"
                )
            manifest = build_review_manifest(
                identity=manifest_identity,
                manifest_id=manifest_id,
                object_sha256=committed.object_sha256,
                artifact_manifest_id=committed.artifact_manifest_id,
            )
            terminal = (
                "succeeded_with_limits"
                if any(
                    item.unable_reasons or item.blocked_reasons
                    for item in items
                )
                else "succeeded"
            )
            result = self._repository.commit(
                run=run,
                items=items,
                decision_tasks=decision_tasks,
                checkpoints=checkpoints,
                manifest=manifest,
                invocation_id=command.invocation_id,
                request_hash=request_hash,
                decision_actor=command.decision_actor,
                interaction_channel=command.interaction_channel,
                transport_actor=command.transport_actor,
                terminal_status=terminal,
                completed_at=completed_at,
            )
            self._ledger.complete(
                FinalizeManualReviewWorkflow(
                    workflow_run_id=run.workflow_run_id,
                    terminal_status=terminal,
                    artifact_manifest_id=committed.artifact_manifest_id,
                    completed_at=completed_at,
                )
            )
            return result
        except Exception:
            self._repository.fail(run.review_run_id, command.requested_at)
            self._ledger.complete(
                FinalizeManualReviewWorkflow(
                    workflow_run_id=run.workflow_run_id,
                    terminal_status="failed",
                    artifact_manifest_id="",
                    completed_at=command.requested_at,
                )
            )
            raise

    def resume(
        self, command: ResumeManualPortfolioReview
    ) -> ManualPortfolioReviewRun:
        failed = self._repository.get(command.failed_review_run_id)
        if failed.status != "failed":
            raise ManualReviewError("MANUAL_REVIEW_NOT_FAILED")
        return self.start(
            StartManualPortfolioReview(
                invocation_id=command.invocation_id,
                account_id=failed.account_id,
                requested_at=command.requested_at,
                selected_complete_session=failed.selected_complete_session,
                first_window_start_exclusive=failed.window_start_exclusive,
                code_identity=command.code_identity,
                config_identity=command.config_identity,
                decision_actor=command.decision_actor,
                interaction_channel=command.interaction_channel,
                transport_actor=command.transport_actor,
            )
        )

    def get(
        self, query: GetManualPortfolioReview
    ) -> ManualPortfolioReviewRun:
        if not query.review_run_id:
            raise ManualReviewError("MANUAL_REVIEW_ID_REQUIRED")
        return self._repository.get(query.review_run_id)

__all__ = [
    "GetManualPortfolioReview",
    "ManualPortfolioReview",
    "ResumeManualPortfolioReview",
    "StartManualPortfolioReview",
]
