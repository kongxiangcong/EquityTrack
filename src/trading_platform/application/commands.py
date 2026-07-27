from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping

from trading_platform.domain.account_snapshots import (
    AccountSnapshotDraft,
    AccountSnapshotError,
    AccountSnapshotPosition,
)
from trading_platform.domain.approvals import ActivationIntent
from trading_platform.domain.plans import (
    CoreFloor,
    CoreSleeve,
    GridSleeve,
    PlanValidationError,
    TradePlanGraph,
    TradePlanRule,
    TradePlanVersion,
    build_trade_plan_draft,
)
from trading_platform.domain.rules import (
    GridConstraint,
    RuleClass,
    RulePriority,
    RuleScope,
    ast_from_dict,
    candidate_from_dict,
)
from trading_platform.identity import canonical_hash

from .account_snapshots import (
    AccountSnapshotCommands,
    ConfirmAccountSnapshot,
    CreateAccountSnapshotDraft,
    UpdateAccountSnapshotDraft,
)
from .command_envelope import (
    ApplicationCommandEnvelopeV1,
    ApprovalCapability,
)
from .trade_plan_authoring import (
    ConfirmTradePlanVersion,
    CreateTradePlanDraft,
    IssuePlanConfirmationChallenge,
    PlanCommandActor,
    RejectTradePlanDraft,
    ReviseTradePlanDraft,
    TradePlanTasks,
)
from .manual_portfolio_review import (
    ManualPortfolioReview,
    StartManualPortfolioReview,
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
    "account_snapshot.create_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "account_snapshot.update_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "account_snapshot.confirm@1": ApprovalCapability.ACCOUNT_CONFIRMATION,
    "trade_plan.create_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "trade_plan.revise_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "trade_plan.reject_draft@1": ApprovalCapability.DRAFT_MUTATION,
    "trade_plan.issue_confirmation_challenge@1": (
        ApprovalCapability.DRAFT_MUTATION
    ),
    "trade_plan.confirm@1": ApprovalCapability.PLAN_CONFIRMATION,
    "manual_portfolio_review.run@1": ApprovalCapability.DRAFT_MUTATION,
    "decision_task.defer@1": ApprovalCapability.TASK_DISPOSITION,
    "decision_task.resolve@1": ApprovalCapability.TASK_DISPOSITION,
    "execution_record.declare@1": ApprovalCapability.EXECUTION_TRUTH,
    "execution_record.correct@1": ApprovalCapability.EXECUTION_TRUTH,
    "discipline_review.confirm@1": ApprovalCapability.REVIEW_CONFIRMATION,
    "plan_change_proposal.accept@1": ApprovalCapability.DRAFT_MUTATION,
    "plan_change_proposal.reject@1": ApprovalCapability.DRAFT_MUTATION,
}

_IMPLEMENTED = {
    "account_snapshot.create_draft@1",
    "account_snapshot.update_draft@1",
    "account_snapshot.confirm@1",
    "trade_plan.create_draft@1",
    "trade_plan.revise_draft@1",
    "trade_plan.reject_draft@1",
    "trade_plan.issue_confirmation_challenge@1",
    "trade_plan.confirm@1",
    "manual_portfolio_review.run@1",
}


class ApplicationCommandDispatcher:
    """Finite mutation adapter; business behavior remains in named tasks."""

    def __init__(
        self,
        account_snapshots: AccountSnapshotCommands,
        trade_plans: TradePlanTasks,
        manual_reviews: ManualPortfolioReview,
    ) -> None:
        self._account_snapshots = account_snapshots
        self._trade_plans = trade_plans
        self._manual_reviews = manual_reviews

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
        except (AccountSnapshotError, PlanValidationError, ValueError, KeyError, TypeError) as error:
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
        if (
            envelope.interaction_channel.value == "web"
            and not envelope.command_name.startswith("account_snapshot.")
        ):
            return self._failure(envelope, "WEB_MUTATION_CAPABILITY_DENIED")
        if capability in {
            ApprovalCapability.ACCOUNT_CONFIRMATION,
            ApprovalCapability.PLAN_CONFIRMATION,
            ApprovalCapability.TASK_DISPOSITION,
            ApprovalCapability.EXECUTION_TRUTH,
            ApprovalCapability.REVIEW_CONFIRMATION,
        } and actor != "user":
            return self._failure(envelope, "USER_DECISION_CAPABILITY_REQUIRED")
        if (
            capability is ApprovalCapability.PLAN_CONFIRMATION
            and not envelope.approval_challenge_id
        ):
            return self._failure(envelope, "PLAN_CONFIRMATION_CHALLENGE_REQUIRED")
        return None

    def _execute(
        self, envelope: ApplicationCommandEnvelopeV1
    ) -> tuple[object, object]:
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
        if envelope.command_name == "manual_portfolio_review.run@1":
            command = StartManualPortfolioReview(
                invocation_id=envelope.invocation_id,
                account_id=str(payload["account_id"]),
                requested_at=str(payload["requested_at"]),
                selected_complete_session=str(
                    payload["selected_complete_session"]
                ),
                first_window_start_exclusive=(
                    str(payload["first_window_start_exclusive"])
                    if payload.get("first_window_start_exclusive")
                    is not None
                    else None
                ),
                code_identity=str(payload["code_identity"]),
                config_identity=str(payload["config_identity"]),
                decision_actor=actor.identity,
                interaction_channel=envelope.interaction_channel.value,
                transport_actor=transport.identity,
            )
            return command, self._manual_reviews.start(command)
        plan_actor = PlanCommandActor(
            actor.identity,
            envelope.interaction_channel.value,
            transport.identity,
        )
        if envelope.command_name == "trade_plan.create_draft@1":
            raw_draft = payload["draft"]
            if not isinstance(raw_draft, Mapping):
                raise TypeError("draft object required")
            graph = _plan_graph(raw_draft["proposed_graph"])
            command = CreateTradePlanDraft(
                invocation_id=envelope.invocation_id,
                draft=build_trade_plan_draft(
                    draft_id=str(raw_draft["draft_id"]),
                    account_id=str(raw_draft["account_id"]),
                    security_id=str(raw_draft["security_id"]),
                    proposed_graph=graph,
                    parameters=_mapping(raw_draft["parameters"]),
                    created_at=str(raw_draft["created_at"]),
                    decision_actor=actor.identity,
                    interaction_channel=envelope.interaction_channel.value,
                    transport_actor=transport.identity,
                ),
                actor=plan_actor,
            )
            return command, self._trade_plans.execute(command)
        if envelope.command_name == "trade_plan.revise_draft@1":
            command = ReviseTradePlanDraft(
                invocation_id=envelope.invocation_id,
                draft_id=str(payload["draft_id"]),
                expected_revision=_revision(envelope),
                proposed_graph=_plan_graph(payload["proposed_graph"]),
                parameters=_mapping(payload["parameters"]),
                updated_at=str(payload["updated_at"]),
                actor=plan_actor,
            )
            return command, self._trade_plans.execute(command)
        if envelope.command_name == "trade_plan.reject_draft@1":
            command = RejectTradePlanDraft(
                invocation_id=envelope.invocation_id,
                draft_id=str(payload["draft_id"]),
                expected_revision=_revision(envelope),
                rejected_at=str(payload["rejected_at"]),
                actor=plan_actor,
            )
            return command, self._trade_plans.execute(command)
        if (
            envelope.command_name
            == "trade_plan.issue_confirmation_challenge@1"
        ):
            command = IssuePlanConfirmationChallenge(
                invocation_id=envelope.invocation_id,
                draft_id=str(payload["draft_id"]),
                expected_revision=_revision(envelope),
                activation_intent=ActivationIntent(
                    str(payload["activation_intent"])
                ),
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
            activation_intent=ActivationIntent(
                str(payload["activation_intent"])
            ),
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


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("object required")
    return value


def _plan_graph(value: object) -> TradePlanGraph:
    payload = _mapping(value)
    raw_version = _mapping(payload["version"])
    version = TradePlanVersion(
        plan_version_id=str(raw_version["plan_version_id"]),
        plan_id=str(raw_version["plan_id"]),
        version_no=int(raw_version["version_no"]),
        supersedes_version_id=(
            str(raw_version["supersedes_version_id"])
            if raw_version.get("supersedes_version_id") is not None
            else None
        ),
        strategy_version_id=str(raw_version["strategy_version_id"]),
        investment_thesis_version_id=(
            str(raw_version["investment_thesis_version_id"])
            if raw_version.get("investment_thesis_version_id") is not None
            else None
        ),
        account_snapshot_version_id=str(
            raw_version["account_snapshot_version_id"]
        ),
        data_snapshot_id=str(raw_version["data_snapshot_id"]),
        horizon_start=str(raw_version["horizon_start"]),
        horizon_end=str(raw_version["horizon_end"]),
        review_by=str(raw_version["review_by"]),
        risk_policy_version_id=(
            str(raw_version["risk_policy_version_id"])
            if raw_version.get("risk_policy_version_id") is not None
            else None
        ),
        metric_catalog_version=str(raw_version["metric_catalog_version"]),
        evaluator_policy_version=str(raw_version["evaluator_policy_version"]),
        conflict_policy_version=str(raw_version["conflict_policy_version"]),
        ast_version=str(raw_version["ast_version"]),
        content=_mapping(raw_version["content"]),
        content_hash=str(raw_version["content_hash"]),
        graph_seal_hash=str(raw_version["graph_seal_hash"]),
        confirmed_at=str(raw_version["confirmed_at"]),
        user_approval_receipt_id=str(
            raw_version["user_approval_receipt_id"]
        ),
    )
    sleeves = tuple(_plan_sleeve(_mapping(raw)) for raw in payload.get("sleeves", ()))
    rules = tuple(_plan_rule(_mapping(raw)) for raw in payload.get("rules", ()))
    graph = TradePlanGraph(
        version=version,
        sleeves=sleeves,
        rules=rules,
        evidence_references=tuple(
            _mapping(raw) for raw in payload.get("evidence_references", ())
        ),
        adjusted_price_evidence=tuple(
            _mapping(raw) for raw in payload.get("adjusted_price_evidence", ())
        ),
        schema_version=str(payload["schema_version"]),
    )
    graph.validate()
    return graph


def _plan_sleeve(raw: Mapping[str, object]) -> CoreSleeve | GridSleeve:
    def decimal_value(state_key: str, value_key: str) -> Decimal | None:
        return (
            Decimal(str(raw[value_key]))
            if raw[state_key] == "known"
            else None
        )

    common = {
        "sleeve_id": str(raw["sleeve_id"]),
        "quantity_budget": decimal_value(
            "quantity_budget_state", "quantity_budget_value"
        ),
        "core_floor": CoreFloor(Decimal(str(raw["core_floor_value"]))),
        "max_notional": decimal_value("max_notional_state", "max_notional_value"),
        "max_loss": decimal_value("max_loss_state", "max_loss_value"),
    }
    if raw["sleeve_kind"] == "core":
        return CoreSleeve(**common)
    grid = _mapping(raw["grid_constraint"])
    return GridSleeve(
        **common,
        constraint=GridConstraint(
            grid_constraint_id=str(grid["grid_constraint_id"]),
            lower_price=Decimal(str(grid["lower_price"])),
            upper_price=Decimal(str(grid["upper_price"])),
            level_count=int(grid["level_count"]),
            quantity_per_level=Decimal(str(grid["quantity_per_level"])),
            total_quantity_budget=Decimal(str(grid["total_quantity_budget"])),
            price_basis=str(grid["price_basis"]),
            trigger_mode=str(grid["trigger_mode"]),
            cooldown_trading_sessions=int(grid["cooldown_trading_sessions"]),
            lot_size=Decimal(str(grid["lot_size"])),
        ),
    )


def _plan_rule(raw: Mapping[str, object]) -> TradePlanRule:
    return TradePlanRule(
        rule_id=str(raw["rule_id"]),
        rule_class=RuleClass(str(raw["rule_class"])),
        rule_kind=str(raw["rule_kind"]),
        priority=RulePriority(str(raw["priority"])),
        scope=RuleScope(str(raw["scope"])),
        sleeve_id=(
            str(raw["sleeve_id"])
            if raw.get("sleeve_id") is not None
            else None
        ),
        effect=str(raw["effect"]),
        applies_to=str(raw["applies_to"]),
        candidate_intent=candidate_from_dict(raw.get("candidate_intent")),
        input_applicability=tuple(raw.get("input_applicability", ())),
        condition=ast_from_dict(_mapping(raw["condition"])),
        content_hash=str(raw["content_hash"]),
        ast_version=str(raw["ast_version"]),
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
    aggregate = next(
        (
            str(payload[key])
            for key in ("account_id", "plan_id", "draft_id")
            if payload.get(key)
        ),
        "",
    )
    revision = next(
        (
            str(payload[key])
            for key in (
                "account_snapshot_version_id",
                "plan_version_id",
                "review_run_id",
                "draft_id",
                "challenge_id",
                "event_id",
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
