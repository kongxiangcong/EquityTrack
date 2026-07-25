from __future__ import annotations

import hashlib
import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Callable, NoReturn

from equity_research import ResearchEngine

from trading_platform.application.contracts import (
    CancellationAccepted,
    CancelWorkflowCommand,
    ResearchWorkflowCommand,
    ResumeWorkflowCommand,
    StartResearchWorkflow,
)
from trading_platform.application.research_request_codec import (
    decode_research_workflow_request,
)
from trading_platform.application.workflow_ledger import (
    AcquireLease,
    ArtifactPayload,
    BeginNode,
    CheckpointQuery,
    CommitEvaluationNode,
    CompletedEvaluationQuery,
    EvaluationCheckpointResult,
    FailExecution,
    FinalizeEvaluationSuccess,
    Heartbeat,
    NodeNameQuery,
    RequestCancellation,
    RequestPayloadQuery,
    SnapshotEvidenceQuery,
    StartDisposition,
    StartWorkflow,
    StopIfCancelled,
    WorkflowLedgerPort,
    WorkflowPersistenceError,
    WorkflowResultQuery,
    WorkflowRunQuery,
)
from trading_platform.domain.research_evaluation import (
    ResearchDecisionViewFactory,
    ResearchWorkflowRequest,
    ResearchWorkflowResult,
)
from trading_platform.domain.workflow import NodeDefinition, WorkflowDefinition
from trading_platform.identity.code import build_code_identity
from trading_platform.research import ResearchEvaluation, ResearchEvaluationError
from trading_platform.research_presentation import (
    render_research_decision_html,
)
from trading_platform.research_view import ResearchDecisionView


_RESEARCH_WORKFLOW = WorkflowDefinition(
    "research-workflow",
    "3",
    (
        NodeDefinition(
            "evaluate_research",
            "1",
            "ResearchWorkflowRequest@2",
            "ResearchDecisionViewBundle@2",
            (
                "security_exists",
                "snapshot_frozen",
                "source_policy_bound",
                "evaluation_plan_closed",
            ),
            True,
            "evaluation_fingerprint",
            "new_attempt_same_run",
            (
                "WORKFLOW_SNAPSHOT_INVALID",
                "WORKFLOW_SNAPSHOT_PURPOSE_INVALID",
                "WORKFLOW_DOMAIN_REFERENCE_INVALID",
                "WORKFLOW_PIT_INVARIANT_FAILED",
                "WORKFLOW_QUALITY_BLOCKED",
                "RESEARCH_EVALUATION_DATA_INSUFFICIENT",
                "RESEARCH_ENGINE_FAILED",
                "RESEARCH_PRESENTATION_FAILED",
                "RESEARCH_ARTIFACT_PERSISTENCE_FAILED",
            ),
        ),
        NodeDefinition(
            "publish_run_manifest",
            "3",
            "ResearchDecisionViewBundle@2",
            "ArtifactManifestRef@1",
            ("research_evaluation_committed",),
            True,
            "none",
            "new_attempt_same_run",
            ("MANIFEST_PUBLICATION_FAILED",),
        ),
    ),
)


class WorkflowError(RuntimeError):
    def __init__(self, code: str, workflow_run_id: str) -> None:
        super().__init__(code)
        self.code = code
        self.workflow_run_id = workflow_run_id


def research_engine_identity(repo_root: Path) -> str:
    identity = build_code_identity(
        repo_root,
        {
            "workflow": (
                f"{_RESEARCH_WORKFLOW.workflow_id}@"
                f"{_RESEARCH_WORKFLOW.version}"
            ),
            "research_evaluation_policy": ResearchEvaluation.POLICY_IDENTITY,
        },
    )
    structured = asdict(identity)
    return json.dumps(
        {
            name: structured[name]
            for name in (
                "source_hash",
                "lock_hash",
                "migration_hash",
                "workflow_hash",
                "package_build_hash",
                "model_policy_hash",
                "dependency_license_hash",
                "determinism_basis",
                "random_seed",
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class ResearchWorkflow:
    """Sole lifecycle owner for the concrete local research evaluation."""

    def __init__(
        self,
        repository: WorkflowLedgerPort,
        repo_root: Path,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.repository = repository
        self.repo_root = repo_root.resolve()
        self.evaluation = ResearchEvaluation(ResearchEngine())
        self.engine_identity = research_engine_identity(self.repo_root)
        self.fault_injector = fault_injector

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    def handle(
        self, command: ResearchWorkflowCommand
    ) -> ResearchWorkflowResult | CancellationAccepted:
        if isinstance(command, StartResearchWorkflow):
            if not isinstance(command.request, ResearchWorkflowRequest):
                raise TypeError(
                    "StartResearchWorkflow requires "
                    "ResearchWorkflowRequest@2"
                )
            return self._start(command.request)
        if isinstance(command, ResumeWorkflowCommand):
            return self._resume(command)
        if isinstance(command, CancelWorkflowCommand):
            self.repository.record_transition(
                RequestCancellation(
                    command.workflow_run_id,
                    command.reason,
                )
            )
            return CancellationAccepted(command.workflow_run_id)
        raise TypeError("Unsupported research workflow command")

    def _start(
        self, request: ResearchWorkflowRequest
    ) -> ResearchWorkflowResult:
        payload = json.dumps(
            request.canonical_content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        fingerprint = self._hash(
            {
                "workflow": (
                    f"{_RESEARCH_WORKFLOW.workflow_id}@"
                    f"{_RESEARCH_WORKFLOW.version}"
                ),
                "request": request.canonical_content,
            }
        )
        owner = f"owner-{uuid.uuid4().hex}"
        try:
            started = self.repository.start_or_replay(
                StartWorkflow(
                    invocation_id=request.invocation_id,
                    request_fingerprint=fingerprint,
                    requested_date=request.requested_date,
                    effective_session_date=request.effective_session_date,
                    definition=_RESEARCH_WORKFLOW,
                    owner_token=owner,
                    request_payload=payload,
                    request_schema="ResearchWorkflowRequest@2",
                )
            )
        except WorkflowPersistenceError as error:
            code = (
                "INVOCATION_REQUEST_MISMATCH"
                if error.code
                in {
                    "WORKFLOW_FINGERPRINT_MISMATCH",
                    "WORKFLOW_REQUEST_INTEGRITY_FAILED",
                }
                else error.code
            )
            raise WorkflowError(code, request.invocation_id) from error
        run_id = started.workflow_run_id
        if started.disposition is StartDisposition.REPLAYED:
            state = self.repository.load(WorkflowRunQuery(run_id))
            if state.status in {"succeeded", "succeeded_with_limits"}:
                return self.repository.load(WorkflowResultQuery(run_id))
            self.repository.record_transition(
                AcquireLease(run_id, owner, _RESEARCH_WORKFLOW, 30)
            )
        return self._execute(run_id, request, owner)

    def _resume(
        self, command: ResumeWorkflowCommand
    ) -> ResearchWorkflowResult:
        try:
            state = self.repository.load(
                WorkflowRunQuery(command.workflow_run_id)
            )
            if state.status in {"succeeded", "succeeded_with_limits"}:
                return self.repository.load(
                    WorkflowResultQuery(command.workflow_run_id)
                )
            request = decode_research_workflow_request(
                self.repository.load(
                    RequestPayloadQuery(command.workflow_run_id)
                )
            )
            self.repository.record_transition(
                AcquireLease(
                    command.workflow_run_id,
                    command.owner_token,
                    _RESEARCH_WORKFLOW,
                    command.lease_seconds,
                )
            )
            return self._execute(
                command.workflow_run_id,
                request,
                command.owner_token,
                command.lease_seconds,
            )
        except WorkflowError:
            raise
        except (TypeError, ValueError) as error:
            raise WorkflowError(
                str(error), command.workflow_run_id
            ) from error

    def _execute(
        self,
        run_id: str,
        request: ResearchWorkflowRequest,
        owner: str,
        lease_seconds: int = 30,
    ) -> ResearchWorkflowResult:
        try:
            self.repository.record_transition(
                Heartbeat(run_id, owner, lease_seconds)
            )
            self.repository.record_transition(StopIfCancelled(run_id))
            checkpoint, evaluation_node, evaluation_attempt = (
                self._evaluate(
                    run_id,
                    request,
                    owner,
                    lease_seconds,
                )
            )
            self.repository.record_transition(StopIfCancelled(run_id))
            self.repository.record_transition(
                Heartbeat(run_id, owner, lease_seconds)
            )
            contract = self._node("publish_run_manifest")
            final_fingerprint = self._hash(
                {
                    "node": asdict(contract),
                    "research_run_id": checkpoint.record.research_run_id,
                    "members": checkpoint.members,
                }
            )
            completed = self.repository.load(
                CheckpointQuery(run_id, contract, final_fingerprint)
            )
            if completed is not None:
                return self.repository.load(WorkflowResultQuery(run_id))
            final_node, final_attempt = self.repository.record_transition(
                BeginNode(
                    run_id,
                    contract,
                    final_fingerprint,
                    owner,
                    lease_seconds,
                )
            )
            self._fault(
                "workflow.node_attempt_started:publish_run_manifest"
            )
            terminal = (
                "succeeded"
                if checkpoint.record.status == "completed"
                else "succeeded_with_limits"
            )
            self.repository.complete(
                FinalizeEvaluationSuccess(
                    workflow_run_id=run_id,
                    owner_token=owner,
                    evaluation_node_id=evaluation_node,
                    evaluation_attempt_id=evaluation_attempt,
                    final_node_id=final_node,
                    final_attempt_id=final_attempt,
                    checkpoint=checkpoint,
                    data_snapshot_id=request.data_snapshot_id,
                    workflow_snapshot_id=request.workflow_snapshot_id,
                    terminal_status=terminal,
                )
            )
            self._fault("workflow.final_manifest_committed")
            return self.repository.load(WorkflowResultQuery(run_id))
        except WorkflowError:
            raise
        except ResearchEvaluationError as error:
            raise WorkflowError(error.code, run_id) from error
        except WorkflowPersistenceError as error:
            raise WorkflowError(error.code, run_id) from error
        except ValueError as error:
            raise WorkflowError(str(error), run_id) from error

    def _evaluate(
        self,
        run_id: str,
        request: ResearchWorkflowRequest,
        owner: str,
        lease_seconds: int,
    ) -> tuple[EvaluationCheckpointResult, str, str]:
        evidence = self.repository.load(
            SnapshotEvidenceQuery(request.data_snapshot_id)
        )
        evaluation_fingerprint = self.evaluation.fingerprint(
            request, evidence
        )
        contract = self._node("evaluate_research")
        node_fingerprint = self._hash(
            {
                "node": asdict(contract),
                "evaluation_fingerprint": evaluation_fingerprint,
                "engine_identity": self.engine_identity,
            }
        )
        completed = self.repository.load(
            CheckpointQuery(run_id, contract, node_fingerprint)
        )
        if completed is not None:
            restored = self.repository.load(
                CompletedEvaluationQuery(
                    completed.workflow_node_run_id
                )
            )
            return (
                restored.checkpoint,
                completed.workflow_node_run_id,
                restored.workflow_node_attempt_id,
            )
        node, attempt = self.repository.record_transition(
            BeginNode(
                run_id,
                contract,
                node_fingerprint,
                owner,
                lease_seconds,
            )
        )
        self._fault("workflow.node_attempt_started:evaluate_research")
        try:
            with self._supervise_lease(
                run_id, owner, lease_seconds
            ):
                produced = self.evaluation.evaluate(request, evidence)
            research_payload = produced.to_dict()
            view = ResearchDecisionViewFactory().build(
                workflow_run_id=run_id,
                request=request,
                research_payload=research_payload,
                model_identity=self.engine_identity,
                source_policy_identity=evidence.source_policy_identity,
            )
            decision_json = json.dumps(
                view,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            decision_html = render_research_decision_html(
                ResearchDecisionView.from_dict(view)
            ).encode("utf-8")
            from trading_platform.research_pdf import ResearchDecisionPdf

            decision_pdf = ResearchDecisionPdf().render(view)
            research_json = json.dumps(
                research_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            checkpoint = self.repository.commit_checkpoint(
                CommitEvaluationNode(
                    workflow_run_id=run_id,
                    workflow_node_run_id=node,
                    workflow_node_attempt_id=attempt,
                    owner_token=owner,
                    request=request,
                    evaluation_fingerprint=evaluation_fingerprint,
                    engine_code_identity=self.engine_identity,
                    research_json_artifact=ArtifactPayload(
                        research_json,
                        "application/json",
                        f"ResearchRun@{produced.schema_version}",
                    ),
                    decision_json_artifact=ArtifactPayload(
                        decision_json,
                        "application/json",
                        "ResearchDecisionView@2",
                    ),
                    decision_html_artifact=ArtifactPayload(
                        decision_html,
                        "text/html",
                        "ResearchDecisionHtml@2",
                    ),
                    decision_pdf_artifact=ArtifactPayload(
                        decision_pdf,
                        "application/pdf",
                        "ResearchDecisionPdf@1",
                    ),
                )
            )
        except ResearchEvaluationError as error:
            self._fail_node(
                run_id,
                node,
                attempt,
                owner,
                error.code,
                substep="research_evaluation.evaluate",
                cause_type=type(error).__name__,
            )
        except (AttributeError, ImportError, RuntimeError, ValueError) as error:
            self._fail_node(
                run_id,
                node,
                attempt,
                owner,
                "RESEARCH_PRESENTATION_FAILED",
                substep="research_evaluation.presentation",
                cause_type=type(error).__name__,
            )
        except Exception as error:
            self._fail_node(
                run_id,
                node,
                attempt,
                owner,
                "RESEARCH_ENGINE_FAILED",
                substep="research_evaluation.unexpected",
                cause_type=type(error).__name__,
            )
        self._fault("workflow.research_checkpoint_committed")
        return checkpoint, node, attempt

    def _fail_node(
        self,
        run_id: str,
        node: str,
        attempt: str,
        owner: str,
        code: str,
        *,
        substep: str,
        cause_type: str,
    ) -> NoReturn:
        node_name = self.repository.load(NodeNameQuery(node))
        contract = self._node(node_name)
        if code not in contract.failure_codes:
            code = contract.failure_codes[0]
        diagnostic = ArtifactPayload(
            json.dumps(
                {
                    "error_code": code,
                    "failing_substep": substep,
                    "redacted_cause_type": cause_type,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            "application/json",
            "WorkflowDiagnostic@1",
        )
        self.repository.record_transition(
            FailExecution(
                run_id,
                node,
                attempt,
                owner,
                code,
                diagnostic,
            )
        )
        raise WorkflowError(code, run_id)

    @staticmethod
    def _node(node_id: str) -> NodeDefinition:
        return next(
            node
            for node in _RESEARCH_WORKFLOW.nodes
            if node.node_id == node_id
        )

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    @contextmanager
    def _supervise_lease(
        self, run_id: str, owner: str, lease_seconds: int
    ):
        stopped = threading.Event()
        failures: list[Exception] = []

        def renew() -> None:
            interval = max(0.1, lease_seconds / 3)
            while not stopped.wait(interval):
                try:
                    self.repository.record_transition(
                        Heartbeat(run_id, owner, lease_seconds)
                    )
                except Exception as error:
                    failures.append(error)
                    return

        worker = threading.Thread(
            target=renew,
            name=f"workflow-heartbeat-{run_id}",
            daemon=True,
        )
        worker.start()
        try:
            yield
        finally:
            stopped.set()
            worker.join(timeout=max(1.0, lease_seconds))
        if failures:
            raise failures[0]


__all__ = [
    "ResearchWorkflow",
    "WorkflowError",
    "research_engine_identity",
]
