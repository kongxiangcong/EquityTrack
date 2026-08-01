from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping

from trading_platform.domain.account_snapshots import (
    AccountRegistration,
    AccountSecurityIdentity,
    AccountSnapshotDraft,
    AccountSnapshotError,
    AccountSnapshotPosition,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.manual_review import ManualReviewError
from trading_platform.domain.plan_impacts import PlanImpactError
from trading_platform.domain.plans import PlanValidationError
from trading_platform.domain.risk_policies import (
    PortfolioRiskLimits,
    PortfolioRiskPolicyError,
)
from trading_platform.domain.discipline_reviews import (
    DisciplineReviewError,
    DisciplineReviewPeriodRequest,
)
from trading_platform.identity import canonical_hash

from .account_snapshots import (
    AccountSnapshotCommands,
    ConfirmAccountSnapshot,
    CreateAccountSnapshotDraft,
    RegisterAccountForSnapshots,
    UpdateAccountSnapshotDraft,
)
from .command_envelope import (
    ApplicationCommandEnvelopeV1,
    ApprovalCapability,
)
from .web_command_policy import WebCommandPolicy, WebCommandPolicyError
from .trade_plan_authoring import (
    ConfirmTradePlanVersion,
    IssuePlanConfirmationChallenge,
    PlanCommandActor,
    RejectTradePlanDraft,
    TradePlanTasks,
)
from .plan_drafting import PrepareTradePlanDraft, TradePlanDrafting
from .risk_policies import (
    ConfirmPortfolioRiskPolicy,
    PortfolioRiskPolicies,
)
from .manual_portfolio_review import (
    ManualPortfolioReview,
    StartManualPortfolioReview,
)
from .decision_tasks import (
    DecisionTasks,
    DeferDecisionTask,
    ResolveDecisionTask,
)
from .decision_journal import (
    CorrectExecution,
    DecisionJournal,
    DeclareExecution,
)
from .discipline_reviews import (
    CreateDisciplineReviewDraft,
    ConfirmDisciplineReviewVersion,
    DisciplineReviews,
)
from .plan_impacts import (
    AcceptPlanChangeProposal,
    CreatePlanChangeProposal,
    CreatePlanImpactAssessment,
    PlanImpacts,
    RejectPlanChangeProposal,
)
from trading_platform.domain.chart import (
    AnnotationAnchor,
    AnnotationLifecycleCommand,
)
from .web_tasks import ChartWorkspace
from trading_platform.domain.decision_tasks import (
    DeferralCondition,
    UserDisposition,
)


@dataclass(frozen=True)
class ApplicationCommandResult:
    invocation_id: str
    command_name: str
    request_hash: str
    result_type: str
    aggregate_id: str
    revision_or_version_id: str
    result: Mapping[str, object]
    status: str = "succeeded"
    schema_version: str = "ApplicationCommandResult@1"


@dataclass(frozen=True)
class ApplicationCommandFailure:
    invocation_id: str
    command_name: str
    request_hash: str
    code: str
    message: str = "Application command failed; inspect the typed code."
    status: str = "failed"
    schema_version: str = "ApplicationCommandFailure@1"


_CAPABILITIES = {
    "account_snapshot.register_account@2": ApprovalCapability.ACCOUNT_CONFIRMATION,
    "account_snapshot.create_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "account_snapshot.update_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "account_snapshot.confirm@1": ApprovalCapability.ACCOUNT_CONFIRMATION,
    "portfolio_risk_policy.confirm@1": ApprovalCapability.ACCOUNT_CONFIRMATION,
    "trade_plan.prepare_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "trade_plan.reject_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "trade_plan.issue_confirmation_challenge@1": (ApprovalCapability.DRAFT_MUTATION),
    "trade_plan.confirm@1": ApprovalCapability.PLAN_CONFIRMATION,
    "chart_annotation.apply@1": ApprovalCapability.DRAFT_MUTATION,
    "manual_portfolio_review.run@2": ApprovalCapability.DRAFT_MUTATION,
    "decision_task.defer@1": ApprovalCapability.TASK_DISPOSITION,
    "decision_task.resolve@1": ApprovalCapability.TASK_DISPOSITION,
    "execution_record.declare@1": ApprovalCapability.EXECUTION_TRUTH,
    "execution_record.correct@1": ApprovalCapability.EXECUTION_TRUTH,
    "discipline_review.create_draft@2": ApprovalCapability.DRAFT_MUTATION,
    "discipline_review.confirm@1": ApprovalCapability.REVIEW_CONFIRMATION,
    "plan_impact_assessment.create@1": ApprovalCapability.DRAFT_MUTATION,
    "plan_change_proposal.create@1": ApprovalCapability.DRAFT_MUTATION,
    "plan_change_proposal.accept@1": (ApprovalCapability.PROPOSAL_DISPOSITION),
    "plan_change_proposal.reject@1": (ApprovalCapability.PROPOSAL_DISPOSITION),
}

_IMPLEMENTED = {
    "account_snapshot.register_account@2",
    "account_snapshot.create_draft@1",
    "account_snapshot.update_draft@1",
    "account_snapshot.confirm@1",
    "portfolio_risk_policy.confirm@1",
    "trade_plan.prepare_draft@1",
    "trade_plan.reject_draft@1",
    "trade_plan.issue_confirmation_challenge@1",
    "trade_plan.confirm@1",
    "chart_annotation.apply@1",
    "manual_portfolio_review.run@2",
    "decision_task.defer@1",
    "decision_task.resolve@1",
    "execution_record.declare@1",
    "execution_record.correct@1",
    "discipline_review.create_draft@2",
    "discipline_review.confirm@1",
    "plan_impact_assessment.create@1",
    "plan_change_proposal.create@1",
    "plan_change_proposal.accept@1",
    "plan_change_proposal.reject@1",
}


class ApplicationCommandDispatcher:
    """Finite mutation adapter; business behavior remains in named tasks."""

    def __init__(
        self,
        account_snapshots: AccountSnapshotCommands,
        risk_policies: PortfolioRiskPolicies,
        trade_plans: TradePlanTasks,
        plan_drafting: TradePlanDrafting,
        manual_reviews: ManualPortfolioReview,
        decision_tasks: DecisionTasks,
        decision_journal: DecisionJournal,
        discipline_reviews: DisciplineReviews,
        plan_impacts: PlanImpacts,
        chart_workspace: ChartWorkspace,
    ) -> None:
        self._account_snapshots = account_snapshots
        self._risk_policies = risk_policies
        self._trade_plans = trade_plans
        self._plan_drafting = plan_drafting
        self._manual_reviews = manual_reviews
        self._decision_tasks = decision_tasks
        self._decision_journal = decision_journal
        self._discipline_reviews = discipline_reviews
        self._plan_impacts = plan_impacts
        self._chart_workspace = chart_workspace

    def dispatch(
        self, envelope: ApplicationCommandEnvelopeV1
    ) -> ApplicationCommandResult | ApplicationCommandFailure:
        denied = self._authorize(envelope)
        if denied is not None:
            return denied
        if envelope.command_name not in _IMPLEMENTED:
            return self._failure(envelope, "COMMAND_NOT_AVAILABLE")
        try:
            command, result = self._execute(envelope)
        except (
            AccountSnapshotError,
            PortfolioRiskPolicyError,
            PlanValidationError,
            InvalidOperation,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            return self._failure(
                envelope, getattr(error, "code", "COMMAND_PAYLOAD_INVALID")
            )
        payload = _json_value(result)
        assert isinstance(payload, Mapping)
        aggregate_id, revision_id = _result_identity(payload)
        return ApplicationCommandResult(
            invocation_id=envelope.invocation_id,
            command_name=envelope.command_name,
            request_hash=canonical_hash(command),
            result_type=type(result).__name__,
            aggregate_id=aggregate_id,
            revision_or_version_id=revision_id,
            result=payload,
        )

    def _authorize(
        self, envelope: ApplicationCommandEnvelopeV1
    ) -> ApplicationCommandFailure | None:
        capability = _CAPABILITIES[envelope.command_name]
        actor = envelope.decision_actor.actor_type
        if actor == "system":
            return self._failure(envelope, "SYSTEM_DECISION_CAPABILITY_DENIED")
        if (
            envelope.interaction_channel.value == "skill"
            and envelope.transport_actor.actor_type != "agent"
        ):
            return self._failure(envelope, "SKILL_TRANSPORT_ACTOR_REQUIRED")
        if envelope.interaction_channel.value == "web":
            try:
                WebCommandPolicy().authorize(envelope)
            except WebCommandPolicyError as error:
                return self._failure(envelope, error.code)
        if (
            capability
            in {
                ApprovalCapability.ACCOUNT_CONFIRMATION,
                ApprovalCapability.PLAN_CONFIRMATION,
                ApprovalCapability.TASK_DISPOSITION,
                ApprovalCapability.EXECUTION_TRUTH,
                ApprovalCapability.REVIEW_CONFIRMATION,
                ApprovalCapability.PROPOSAL_DISPOSITION,
            }
            and actor != "user"
        ):
            return self._failure(envelope, "USER_DECISION_CAPABILITY_REQUIRED")
        if (
            capability is ApprovalCapability.PLAN_CONFIRMATION
            and not envelope.approval_challenge_id
        ):
            return self._failure(envelope, "PLAN_CONFIRMATION_CHALLENGE_REQUIRED")
        return None

    def _execute(self, envelope: ApplicationCommandEnvelopeV1) -> tuple[object, object]:
        payload = envelope.payload
        actor = envelope.decision_actor
        transport = envelope.transport_actor
        common = {
            "invocation_id": envelope.invocation_id,
            "decision_actor_type": actor.actor_type,
            "decision_actor_id": actor.actor_id,
            "interaction_channel": envelope.interaction_channel.value,
            "transport_actor_type": transport.actor_type,
            "transport_actor_id": transport.actor_id,
        }
        if envelope.command_name == "account_snapshot.register_account@2":
            command = RegisterAccountForSnapshots(
                registration=_account_registration(payload), **common
            )
            return command, self._account_snapshots.execute(command)
        if envelope.command_name == "account_snapshot.create_draft@1":
            command = CreateAccountSnapshotDraft(
                draft=_account_draft(payload["draft"]), **common
            )
            return command, self._account_snapshots.execute(command)
        if envelope.command_name == "account_snapshot.update_draft@1":
            command = UpdateAccountSnapshotDraft(
                draft=_account_draft(payload["draft"]),
                expected_revision=_revision(envelope),
                **common,
            )
            return command, self._account_snapshots.execute(command)
        if envelope.command_name == "account_snapshot.confirm@1":
            command = ConfirmAccountSnapshot(
                draft_id=str(payload["draft_id"]),
                expected_revision=_revision(envelope),
                **common,
            )
            return command, self._account_snapshots.execute(command)
        if envelope.command_name == "portfolio_risk_policy.confirm@1":
            command = ConfirmPortfolioRiskPolicy(
                account_id=str(payload["account_id"]),
                currency=str(payload["currency"]),
                limits=_risk_limits(payload["limits"]),
                **common,
            )
            return command, self._risk_policies.confirm(command)
        if envelope.command_name == "trade_plan.prepare_draft@1":
            command = _prepare_trade_plan_draft(envelope)
            return command, self._plan_drafting.prepare(command)
        if envelope.command_name == "chart_annotation.apply@1":
            allowed = {
                "operation",
                "security_id",
                "data_snapshot_id",
                "annotation_id",
                "kind",
                "style",
                "anchors",
            }
            if set(payload) - allowed:
                raise ValueError("CHART_ANNOTATION_FIELDS_INVALID")
            operation = str(payload["operation"])
            expected = envelope.expected_revision
            if (operation == "create") != (expected is None):
                raise ValueError("CHART_ANNOTATION_REVISION_INVALID")
            raw_anchors = payload.get("anchors", ())
            if not isinstance(raw_anchors, (list, tuple)):
                raise TypeError("annotation anchors array required")
            command = AnnotationLifecycleCommand(
                invocation_id=envelope.invocation_id,
                operation=operation,
                security_id=str(payload["security_id"]),
                data_snapshot_id=str(payload["data_snapshot_id"]),
                author_id=actor.actor_id,
                annotation_id=(
                    str(payload["annotation_id"])
                    if payload.get("annotation_id") is not None
                    else None
                ),
                expected_version_no=expected or 0,
                kind=(
                    str(payload["kind"])
                    if payload.get("kind") is not None
                    else None
                ),
                style=(
                    str(payload["style"])
                    if payload.get("style") is not None
                    else None
                ),
                anchors=tuple(
                    AnnotationAnchor(
                        str(_mapping(item)["market_timestamp"]),
                        str(_mapping(item)["exact_price_decimal"]),
                    )
                    for item in raw_anchors
                ),
            )
            return command, self._chart_workspace.apply(command)
        if envelope.command_name == "manual_portfolio_review.run@2":
            if (
                set(payload)
                != {"account_id", "requested_at", "session_selection"}
                or envelope.expected_revision is not None
                or envelope.approval_challenge_id is not None
            ):
                raise ManualReviewError(
                    "MANUAL_REVIEW_COMMAND_FIELDS_INVALID"
                )
            command = StartManualPortfolioReview(
                invocation_id=envelope.invocation_id,
                account_id=str(payload["account_id"]),
                requested_at=str(payload["requested_at"]),
                session_selection=str(payload["session_selection"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._manual_reviews.start(command)
        if envelope.command_name == "decision_task.defer@1":
            command = DeferDecisionTask(
                invocation_id=envelope.invocation_id,
                decision_task_id=str(payload["decision_task_id"]),
                condition=DeferralCondition(
                    target_type=str(payload["defer_target_type"]),
                    target_value=(
                        str(payload["defer_target_value"])
                        if payload.get("defer_target_value") is not None
                        else None
                    ),
                ),
                occurred_at=str(payload["occurred_at"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._decision_tasks.defer(command)
        if envelope.command_name == "decision_task.resolve@1":
            command = ResolveDecisionTask(
                invocation_id=envelope.invocation_id,
                decision_task_id=str(payload["decision_task_id"]),
                disposition=UserDisposition(str(payload["disposition"])),
                reason=str(payload["reason"]),
                occurred_at=str(payload["occurred_at"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._decision_tasks.resolve(command)
        if envelope.command_name == "execution_record.declare@1":
            command = DeclareExecution(
                invocation_id=envelope.invocation_id,
                decision_task_id=str(payload["decision_task_id"]),
                reason=str(payload["reason"]),
                effective_at=str(payload["effective_at"]),
                effective_session=str(payload["effective_session"]),
                intent_type=str(payload["intent_type"]),
                quantity=str(payload["quantity"]),
                price_state=str(payload["price_state"]),
                price_value=(
                    str(payload["price_value"])
                    if payload.get("price_value") is not None
                    else None
                ),
                fee_state=str(payload["fee_state"]),
                fee_value=(
                    str(payload["fee_value"])
                    if payload.get("fee_value") is not None
                    else None
                ),
                currency=str(payload["currency"]),
                confirmed_at=str(payload["confirmed_at"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._decision_journal.declare(command)
        if envelope.command_name == "execution_record.correct@1":
            command = CorrectExecution(
                invocation_id=envelope.invocation_id,
                original_execution_record_id=str(
                    payload["original_execution_record_id"]
                ),
                reason=str(payload["reason"]),
                effective_at=str(payload["effective_at"]),
                effective_session=str(payload["effective_session"]),
                intent_type=str(payload["intent_type"]),
                quantity=str(payload["quantity"]),
                price_state=str(payload["price_state"]),
                price_value=(
                    str(payload["price_value"])
                    if payload.get("price_value") is not None
                    else None
                ),
                fee_state=str(payload["fee_state"]),
                fee_value=(
                    str(payload["fee_value"])
                    if payload.get("fee_value") is not None
                    else None
                ),
                currency=str(payload["currency"]),
                confirmed_at=str(payload["confirmed_at"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._decision_journal.correct(command)
        if envelope.command_name == "discipline_review.create_draft@2":
            command = _create_discipline_review_draft(envelope)
            return command, self._discipline_reviews.create_draft(
                command
            )
        if envelope.command_name == "discipline_review.confirm@1":
            command = ConfirmDisciplineReviewVersion(
                invocation_id=envelope.invocation_id,
                discipline_review_id=str(payload["discipline_review_id"]),
                expected_version_no=_revision(envelope),
                confirmed_at=str(payload["confirmed_at"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._discipline_reviews.confirm(command)
        if envelope.command_name == "plan_impact_assessment.create@1":
            command = CreatePlanImpactAssessment(
                invocation_id=envelope.invocation_id,
                review_run_id=str(payload["review_run_id"]),
                review_item_id=str(payload["review_item_id"]),
                review_rule_id=str(payload["review_rule_id"]),
                impact_kind=str(payload["impact_kind"]),
                materiality=str(payload["materiality"]),
                uncertainties=tuple(
                    str(value) for value in payload.get("uncertainties", ())
                ),
                what_changed=str(payload["what_changed"]),
                what_would_change_the_view=str(payload["what_would_change_the_view"]),
                model_identity=str(payload["model_identity"]),
                policy_identity=str(payload["policy_identity"]),
                prompt_identity=str(payload["prompt_identity"]),
                created_by=actor.actor_type,
                created_at=str(payload["created_at"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._plan_impacts.create_assessment(command)
        if envelope.command_name == "plan_change_proposal.create@1":
            command = CreatePlanChangeProposal(
                invocation_id=envelope.invocation_id,
                assessment_id=str(payload["assessment_id"]),
                proposed_content=_mapping(payload["proposed_content"]),
                parameters=_mapping(payload["parameters"]),
                created_by=actor.actor_type,
                created_at=str(payload["created_at"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._plan_impacts.create_proposal(command)
        plan_actor = PlanCommandActor(
            actor.identity,
            envelope.interaction_channel.value,
            transport.identity,
        )
        if envelope.command_name == "plan_change_proposal.accept@1":
            if set(payload) != {"proposal_id", "decided_at"}:
                raise PlanImpactError(
                    "PROPOSAL_DISPOSITION_COMMAND_FIELDS_INVALID"
                )
            command = AcceptPlanChangeProposal(
                invocation_id=envelope.invocation_id,
                proposal_id=str(payload["proposal_id"]),
                expected_revision=_revision(envelope),
                decided_at=str(payload["decided_at"]),
                actor=plan_actor,
            )
            return command, self._plan_impacts.accept(command)
        if envelope.command_name == "plan_change_proposal.reject@1":
            command = RejectPlanChangeProposal(
                invocation_id=envelope.invocation_id,
                proposal_id=str(payload["proposal_id"]),
                expected_revision=_revision(envelope),
                decided_at=str(payload["decided_at"]),
                actor=plan_actor,
            )
            return command, self._plan_impacts.reject(command)
        if envelope.command_name == "trade_plan.reject_draft@1":
            command = RejectTradePlanDraft(
                invocation_id=envelope.invocation_id,
                draft_id=str(payload["draft_id"]),
                expected_revision=_revision(envelope),
                rejected_at=str(payload["rejected_at"]),
                actor=plan_actor,
            )
            return command, self._trade_plans.execute(command)
        if envelope.command_name == "trade_plan.issue_confirmation_challenge@1":
            command = IssuePlanConfirmationChallenge(
                invocation_id=envelope.invocation_id,
                draft_id=str(payload["draft_id"]),
                expected_revision=_revision(envelope),
                activation_intent=ActivationIntent(str(payload["activation_intent"])),
                issued_at=str(payload["issued_at"]),
                expires_at=(
                    str(payload["expires_at"])
                    if payload.get("expires_at") is not None
                    else None
                ),
                actor=plan_actor,
            )
            return command, self._trade_plans.execute(command)
        command = ConfirmTradePlanVersion(
            invocation_id=envelope.invocation_id,
            challenge_id=str(envelope.approval_challenge_id),
            expected_revision=_revision(envelope),
            expected_draft_hash=str(payload["expected_draft_hash"]),
            expected_diff_hash=str(payload["expected_diff_hash"]),
            activation_intent=ActivationIntent(str(payload["activation_intent"])),
            approved_at=str(payload["approved_at"]),
            actor=plan_actor,
        )
        return command, self._trade_plans.execute(command)

    @staticmethod
    def _failure(
        envelope: ApplicationCommandEnvelopeV1, code: str
    ) -> ApplicationCommandFailure:
        return ApplicationCommandFailure(
            invocation_id=envelope.invocation_id,
            command_name=envelope.command_name,
            request_hash=canonical_hash(envelope.canonical_content),
            code=code,
        )


def _prepare_trade_plan_draft(
    envelope: ApplicationCommandEnvelopeV1,
) -> PrepareTradePlanDraft:
    payload = envelope.payload
    if (
        set(payload)
        != {"account_ref", "security_ref", "plan_style", "requested_at"}
        or envelope.expected_revision is not None
        or envelope.approval_challenge_id is not None
    ):
        raise PlanValidationError("PLAN_DRAFT_COMMAND_FIELDS_INVALID")
    actor = envelope.decision_actor
    transport = envelope.transport_actor
    return PrepareTradePlanDraft(
        invocation_id=envelope.invocation_id,
        account_ref=_plan_text(payload["account_ref"]),
        security_ref=_plan_text(payload["security_ref"]),
        plan_style=_plan_text(payload["plan_style"]),
        requested_at=_plan_text(payload["requested_at"]),
        actor=PlanCommandActor(
            actor.identity,
            envelope.interaction_channel.value,
            transport.identity,
        ),
    )

def _plan_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise PlanValidationError(
            "PLAN_DRAFT_COMMAND_FIELDS_INVALID"
        )
    return value


def _create_discipline_review_draft(
    envelope: ApplicationCommandEnvelopeV1,
) -> CreateDisciplineReviewDraft:
    payload = envelope.payload
    if (
        set(payload) != {"account_id", "period_request"}
        or envelope.expected_revision is not None
        or envelope.approval_challenge_id is not None
    ):
        raise DisciplineReviewError(
            "DISCIPLINE_REVIEW_COMMAND_FIELDS_INVALID"
        )
    period_request = _mapping(payload["period_request"])
    if set(period_request) != {
        "period_kind",
        "requested_at",
        "requested_start_date",
        "requested_end_date",
    }:
        raise DisciplineReviewError(
            "DISCIPLINE_REVIEW_COMMAND_FIELDS_INVALID"
        )
    actor = envelope.decision_actor
    transport = envelope.transport_actor
    return CreateDisciplineReviewDraft(
        invocation_id=envelope.invocation_id,
        account_id=_discipline_review_text(payload["account_id"]),
        period_request=DisciplineReviewPeriodRequest(
            period_kind=_discipline_review_text(
                period_request["period_kind"]
            ),
            requested_at=_discipline_review_text(
                period_request["requested_at"]
            ),
            requested_start_date=_optional_discipline_review_text(
                period_request["requested_start_date"]
            ),
            requested_end_date=_optional_discipline_review_text(
                period_request["requested_end_date"]
            ),
        ),
        decision_actor=actor.identity,
        interaction_channel=envelope.interaction_channel.value,
        transport_actor=transport.identity,
    )


def _discipline_review_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise DisciplineReviewError(
            "DISCIPLINE_REVIEW_COMMAND_FIELDS_INVALID"
        )
    return value


def _optional_discipline_review_text(value: object) -> str | None:
    if value is None:
        return None
    return _discipline_review_text(value)


def _revision(envelope: ApplicationCommandEnvelopeV1) -> int:
    if envelope.expected_revision is None:
        raise ValueError("COMMAND_EXPECTED_REVISION_REQUIRED")
    return envelope.expected_revision


def _account_draft(value: object) -> AccountSnapshotDraft:
    if not isinstance(value, Mapping):
        raise TypeError("draft object required")
    positions = value.get("positions", ())
    if not isinstance(positions, (list, tuple)):
        raise TypeError("positions array required")
    fields = dict(value)
    fields["positions"] = tuple(
        AccountSnapshotPosition(**dict(position))
        for position in positions
        if isinstance(position, Mapping)
    )
    if len(fields["positions"]) != len(positions):
        raise TypeError("position object required")
    for key in (
        "validation_errors",
        "capability_impacts",
    ):
        if key in fields:
            fields[key] = tuple(fields[key])
    return AccountSnapshotDraft(**fields)


def _account_registration(value: object) -> AccountRegistration:
    if not isinstance(value, Mapping):
        raise TypeError("account registration object required")
    securities = value.get("securities", ())
    if not isinstance(securities, (list, tuple)):
        raise TypeError("securities array required")
    fields = dict(value)
    fields["securities"] = tuple(
        AccountSecurityIdentity(**dict(identity))
        for identity in securities
        if isinstance(identity, Mapping)
    )
    if len(fields["securities"]) != len(securities):
        raise TypeError("security identity object required")
    return AccountRegistration(**fields)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("object required")
    return value


def _risk_limits(value: object) -> PortfolioRiskLimits:
    raw = _mapping(value)
    keys = (
        "single_security_exposure",
        "industry_exposure",
        "gross_exposure",
        "minimum_cash",
        "single_plan_loss",
        "aggregate_active_plan_loss",
        "drawdown_review",
        "drawdown_freeze",
        "plan_daily_liquidity",
        "position_daily_liquidity",
    )
    if set(raw) != set(keys):
        raise ValueError("RISK_POLICY_LIMIT_FIELDS_INVALID")
    return PortfolioRiskLimits(
        **{key: Decimal(str(raw[key])) for key in keys}
    )


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return str(value) if value.__class__.__module__ == "decimal" else value


def _result_identity(payload: Mapping[str, object]) -> tuple[str, str]:
    if payload.get("discipline_review_id"):
        return (
            str(payload["discipline_review_id"]),
            str(payload.get("version_no", "")),
        )
    aggregate = next(
        (
            str(payload[key])
            for key in (
                "annotation_id",
                "account_id",
                "plan_id",
                "draft_id",
                "decision_task_id",
                "execution_record_id",
                "discipline_review_id",
                "assessment_id",
                "proposal_id",
            )
            if payload.get(key)
        ),
        "",
    )
    revision = next(
        (
            str(payload[key])
            for key in (
                "annotation_version_id",
                "account_snapshot_version_id",
                "portfolio_risk_policy_version_id",
                "registration_id",
                "plan_version_id",
                "review_run_id",
                "draft_id",
                "challenge_id",
                "event_id",
                "latest_transition_id",
                "version_no",
            )
            if payload.get(key)
        ),
        str(payload.get("revision", "")),
    )
    return aggregate, revision


__all__ = [
    "ApplicationCommandDispatcher",
    "ApplicationCommandFailure",
    "ApplicationCommandResult",
]
