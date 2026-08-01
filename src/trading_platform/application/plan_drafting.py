from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Mapping, Protocol

from trading_platform.domain.account_snapshots import AccountSnapshotVersion
from trading_platform.domain.plans import PlanValidationError, TradePlanDraft
from trading_platform.domain.research_evaluation import ResearchWorkflowRequest
from trading_platform.research_view import ResearchDecisionView, ResearchViewError

from .account_snapshots import GetAccountSnapshot
from .plan_compiler import (
    _CompileTradePlanDraft,
    TradePlanCompiler,
    TrendHoldBreakExitIntent,
)
from .research_tasks import ResearchArchive
from .trade_plan_authoring import PlanCommandActor
from .watchlist import Watchlist


@dataclass(frozen=True)
class PrepareTradePlanDraft:
    invocation_id: str
    account_ref: str
    security_ref: str
    plan_style: str
    requested_at: str
    actor: PlanCommandActor
    schema_version: str = "PrepareTradePlanDraft@1"

    def validate(self) -> None:
        self.actor.validate()
        try:
            requested = datetime.fromisoformat(self.requested_at)
        except ValueError as error:
            raise PlanValidationError("PLAN_DRAFT_REQUEST_TIME_INVALID") from error
        if (
            self.schema_version != "PrepareTradePlanDraft@1"
            or not self.account_ref
            or not self.security_ref
            or self.plan_style != "existing_position_review"
            or requested.tzinfo is None
            or requested.utcoffset() is None
        ):
            raise PlanValidationError("PLAN_DRAFT_REQUEST_INVALID")


class AccountSnapshotReader(Protocol):
    def get(self, query: GetAccountSnapshot) -> AccountSnapshotVersion: ...

    def resolve(self, reference: str) -> str: ...


class TradePlanDrafting:
    """Selects current authorities and prepares a conservative plan draft."""

    def __init__(
        self,
        *,
        archive: ResearchArchive,
        accounts: AccountSnapshotReader,
        watchlist: Watchlist,
        compiler: TradePlanCompiler,
    ) -> None:
        self._archive = archive
        self._accounts = accounts
        self._watchlist = watchlist
        self._compiler = compiler

    def prepare(self, command: PrepareTradePlanDraft) -> TradePlanDraft:
        command.validate()
        account_id = self._accounts.resolve(command.account_ref)
        security_id = _resolve_security(self._watchlist, command.security_ref)
        workflow_id, view, request = self._latest_research(
            security_id=security_id,
            requested_at=command.requested_at,
        )
        account = self._accounts.get(GetAccountSnapshot(account_id=account_id))
        quantity = _confirmed_position_quantity(account, security_id)
        trend_id = _recent_trend_assessment_id(view)
        intent = TrendHoldBreakExitIntent(
            core_floor_quantity=quantity,
            candidate_decrease_quantity=None,
            break_confirmation_sessions=2,
            horizon_end=request.evaluation_plan.horizon.forecast_end,
            review_by=request.evaluation_plan.horizon.review_by,
        )
        return self._compiler.compile(
            _CompileTradePlanDraft(
                invocation_id=command.invocation_id,
                workflow_run_id=workflow_id,
                recent_trend_assessment_id=trend_id,
                account_id=account_id,
                strategy_key="trend_hold_break_exit",
                intent=intent,
                created_at=command.requested_at,
                actor=command.actor,
            )
        )

    def _latest_research(
        self, *, security_id: str, requested_at: str
    ) -> tuple[str, ResearchDecisionView, ResearchWorkflowRequest]:
        requested = datetime.fromisoformat(requested_at)
        incomplete = 0
        for item in self._archive.workspace(security_id).workflows:
            if item.get("status") not in {"succeeded", "succeeded_with_limits"}:
                continue
            completed_at = item.get("completed_at")
            if completed_at is not None:
                completed = datetime.fromisoformat(str(completed_at))
                if completed > requested:
                    continue
            workflow_id = str(item.get("workflow_run_id", ""))
            try:
                payload = self._archive.decision_view(workflow_id)
                view = ResearchDecisionView.from_dict(json.loads(payload.json_bytes))
                request_payload = json.loads(self._archive.request_payload(workflow_id))
                if not isinstance(request_payload, dict):
                    raise ValueError("research request object required")
                request = ResearchWorkflowRequest.from_mapping(request_payload)
            except Exception as error:
                if getattr(error, "code", None) == "RESEARCH_DECISION_VIEW_INCOMPLETE":
                    incomplete += 1
                    continue
                if isinstance(
                    error,
                    (UnicodeDecodeError, json.JSONDecodeError, ResearchViewError),
                ):
                    raise PlanValidationError("PLAN_DRAFT_RESEARCH_INVALID") from error
                raise
            if (
                not workflow_id
                or view.workflow_run_id != workflow_id
                or view.security_id != security_id
                or request.security_id != security_id
            ):
                raise PlanValidationError("PLAN_DRAFT_RESEARCH_IDENTITY_MISMATCH")
            return workflow_id, view, request
        raise PlanValidationError(
            "PLAN_DRAFT_RESEARCH_NOT_AVAILABLE"
            if incomplete == 0
            else "PLAN_DRAFT_COMPLETE_RESEARCH_NOT_AVAILABLE"
        )


def _resolve_security(watchlist: Watchlist, reference: str) -> str:
    normalized = reference.strip().upper()
    matches = tuple(
        item.security_id
        for item in watchlist.list()
        if normalized
        in {
            item.security_id.upper(),
            item.code.upper(),
            f"{item.code}.{_market_suffix(item.market)}".upper(),
        }
    )
    identities = tuple(dict.fromkeys(matches))
    if len(identities) != 1:
        raise PlanValidationError(
            "PLAN_DRAFT_SECURITY_NOT_FOUND"
            if not identities
            else "PLAN_DRAFT_SECURITY_AMBIGUOUS"
        )
    return identities[0]


def _market_suffix(market: str) -> str:
    try:
        return {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[market]
    except KeyError as error:
        raise PlanValidationError("PLAN_DRAFT_SECURITY_MARKET_UNSUPPORTED") from error


def _recent_trend_assessment_id(view: ResearchDecisionView) -> str:
    summary = view.audit.get("recent_trend_assessment")
    assessment = summary.get("assessment") if isinstance(summary, Mapping) else None
    assessment_id = (
        assessment.get("assessment_id") if isinstance(assessment, Mapping) else None
    )
    if not isinstance(assessment_id, str) or not assessment_id:
        raise PlanValidationError("PLAN_DRAFT_RECENT_TREND_NOT_AVAILABLE")
    return assessment_id


def _confirmed_position_quantity(
    account: AccountSnapshotVersion, security_id: str
) -> Decimal:
    positions = tuple(
        position
        for position in account.positions
        if position.security_id == security_id
    )
    if len(positions) > 1:
        raise PlanValidationError("PLAN_DRAFT_ACCOUNT_POSITION_DUPLICATE")
    if not positions:
        return Decimal("0")
    try:
        quantity = Decimal(positions[0].total_quantity)
    except (InvalidOperation, ValueError) as error:
        raise PlanValidationError("PLAN_DRAFT_ACCOUNT_POSITION_INVALID") from error
    if (
        not quantity.is_finite()
        or quantity < 0
        or quantity != quantity.to_integral_value()
    ):
        raise PlanValidationError("PLAN_DRAFT_ACCOUNT_POSITION_INVALID")
    return quantity


__all__ = ["PrepareTradePlanDraft", "TradePlanDrafting"]
