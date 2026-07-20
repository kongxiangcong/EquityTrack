from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Mapping, Protocol

from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import SyncRequest, SyncResult
from trading_platform.domain.market import MarketSnapshotView, PlanEvaluationView
from trading_platform.domain.workflow import ResearchWorkflowResult
from trading_platform.market import MarketEvaluationService
from trading_platform.workflows.research import ResearchWorkflow

from .contracts import DoctorReport, StartResearchWorkflow
from .research_request_codec import decode_research_workflow_request
from .watchlist import Watchlist
from .command_codecs import (
    CommandCodecError,
    decode_market_snapshot_command_value,
    decode_plan_evaluation_command_value,
    decode_provider_security_identity_value,
)


class DoctorTask(Protocol):
    def doctor(self) -> DoctorReport: ...


class DailyResearchContractError(RuntimeError):
    code = "DAILY_RESEARCH_RESULT_INVALID"
    substep = "daily.research"
    cause_type = "ResearchWorkflowResult"


def _register_job_security(
    watchlist: Watchlist, job: Mapping[str, object]
) -> None:
    value = job.get("security_identity")
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise CommandCodecError(
            "WATCHLIST_IDENTITY_INVALID",
            "watchlist_identity.decode",
            "TypeError",
        )
    identity_payload = dict(value)
    invocation_id = identity_payload.pop("invocation_id", None)
    if invocation_id is not None and not isinstance(invocation_id, str):
        raise CommandCodecError(
            "WATCHLIST_IDENTITY_INVALID",
            "watchlist_identity.decode",
            "TypeError",
        )
    identity = decode_provider_security_identity_value(identity_payload)
    watchlist.add(
        invocation_id or f"provider-security:{identity.security_id}",
        identity,
    )


class DataSynchronization:
    """Own the complete configured data-sync application journey."""

    def __init__(
        self,
        job: Mapping[str, object],
        request: SyncRequest,
        watchlist: Watchlist,
        data: DataSyncService,
    ) -> None:
        self._job = job
        self._request = request
        self._watchlist = watchlist
        self._data = data

    def run(self) -> SyncResult:
        _register_job_security(self._watchlist, self._job)
        return self._data.sync(self._request)

@dataclass(frozen=True)
class DailyResearchResult:
    sync: SyncResult
    doctor: DoctorReport
    research: ResearchWorkflowResult | None = None
    market: MarketSnapshotView | None = None
    evaluation: PlanEvaluationView | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"sync": asdict(self.sync)}
        if self.research is not None:
            result["research"] = asdict(self.research)
        if self.market is not None:
            result["market"] = asdict(self.market)
        if self.evaluation is not None:
            result["evaluation"] = asdict(self.evaluation)
        result["doctor"] = asdict(self.doctor)
        return result


class DailyResearchCycle:
    """Own the one daily sync, research, market, and health policy."""

    def __init__(
        self,
        job: Mapping[str, object],
        request: SyncRequest,
        watchlist: Watchlist,
        data: DataSyncService,
        research: ResearchWorkflow,
        market: MarketEvaluationService,
        doctor: DoctorTask,
    ) -> None:
        self._job = job
        self._request = request
        self._watchlist = watchlist
        self._data = data
        self._research = research
        self._market = market
        self._doctor = doctor

    def run(self) -> DailyResearchResult:
        _register_job_security(self._watchlist, self._job)
        sync = self._data.sync(self._request)
        research = None
        market = None
        evaluation = None
        research_input = self._job.get("research_request")
        if research_input is not None:
            research_request = decode_research_workflow_request(
                json.dumps(research_input).encode()
            )
            outcome = self._research.handle(StartResearchWorkflow(research_request))
            if not isinstance(outcome, ResearchWorkflowResult):
                raise DailyResearchContractError(
                    "Research workflow returned the wrong typed result."
                )
            research = outcome
        market_input = self._job.get("market")
        if market_input is not None:
            market = self._market.build_market_snapshot(
                decode_market_snapshot_command_value(market_input)
            )
            evaluation_input = self._job.get("evaluation")
            if evaluation_input is not None:
                if not isinstance(evaluation_input, Mapping):
                    raise CommandCodecError(
                        "PLAN_EVALUATION_COMMAND_INVALID",
                        "plan_evaluation_command.decode",
                        "TypeError",
                    )
                evaluation_data = {
                    **dict(evaluation_input),
                    "market_snapshot_id": market.market_snapshot_id,
                }
                evaluation = self._market.evaluate_plan(
                    decode_plan_evaluation_command_value(evaluation_data)
                )
        return DailyResearchResult(
            sync=sync,
            research=research,
            market=market,
            evaluation=evaluation,
            doctor=self._doctor.doctor(),
        )


__all__ = ["DailyResearchCycle", "DailyResearchResult", "DataSynchronization"]
