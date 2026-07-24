from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import SyncRequest, SyncResult
from trading_platform.domain.market import MarketSnapshotView, PlanEvaluationView
from trading_platform.domain.workflow import ResearchWorkflowResult
from trading_platform.market import MarketEvaluationService
from trading_platform.workflows.research import ResearchWorkflow

from .contracts import DoctorReport, StartResearchWorkflow
from .watchlist import Watchlist
from .market_contracts import EvaluatePlanCommand
from .provider_job import ProviderJob


class DoctorTask(Protocol):
    def doctor(self) -> DoctorReport: ...


class DailyResearchContractError(RuntimeError):
    code = "DAILY_RESEARCH_RESULT_INVALID"
    substep = "daily.research"
    cause_type = "ResearchWorkflowResult"


def _register_job_security(watchlist: Watchlist, job: ProviderJob) -> None:
    identity = job.security_identity
    if identity is None:
        return
    watchlist.add(job.security_invocation_id or f"provider-security:{identity.security_id}", identity)


class DataSynchronization:
    """Own the complete configured data-sync application journey."""

    def __init__(
        self,
        job: ProviderJob,
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
        job: ProviderJob,
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
        if self._job.research_request is not None:
            research_request = self._job.research_request
            outcome = self._research.handle(StartResearchWorkflow(research_request))
            if not isinstance(outcome, ResearchWorkflowResult):
                raise DailyResearchContractError(
                    "Research workflow returned the wrong typed result."
                )
            research = outcome
        if self._job.market_command is not None:
            market = self._market.build_market_snapshot(self._job.market_command)
            if self._job.evaluation_template is not None:
                template = self._job.evaluation_template
                evaluation = self._market.evaluate_plan(EvaluatePlanCommand(
                    template.invocation_id,
                    template.plan_version_id,
                    market.market_snapshot_id,
                    template.evaluator_version,
                    template.evaluation_policy_version,
                ))
        return DailyResearchResult(
            sync=sync,
            research=research,
            market=market,
            evaluation=evaluation,
            doctor=self._doctor.doctor(),
        )


__all__ = ["DailyResearchCycle", "DailyResearchResult", "DataSynchronization"]
