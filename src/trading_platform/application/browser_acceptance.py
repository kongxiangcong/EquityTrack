from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.data.service import DataSyncService
from trading_platform.data.providers import FixtureProvider
from trading_platform.domain.data import CompletenessRequirement, FallbackMode, FixtureRights, QueryPolicy, SnapshotPurpose, SourceAuthority, SourceFailureDisposition, SourcePolicy, SourceRights, SourceRoute, SyncRequest
from trading_platform.domain.plans import (
    CreatePlanDraftCommand,
    PlanCondition,
    PlanConstant,
    PlanDraftContent,
    PlanReference,
    PlanRule,
)
from trading_platform.domain.research_evaluation import (
    EvaluationDimension,
    EvaluationHorizon,
    EvaluationPurpose,
    ResearchEvaluationPlan,
    ResearchWorkflowRequest,
    StrategyValidationSelection,
)
from trading_platform.plans import PlanService
from trading_platform.workflows.research import ResearchWorkflow

from .watchlist import Watchlist


@dataclass(frozen=True)
class BrowserAcceptanceFixtureResult:
    security_id: str
    snapshot_id: str
    workflow_run_id: str
    research_run_id: str
    plan_draft_id: str


class BrowserAcceptanceFixture:
    """Prepare the canonical public journeys used by real-browser acceptance."""

    def __init__(
        self,
        watchlist: Watchlist,
        data: DataSyncService,
        research: ResearchWorkflow,
        plans: PlanService,
    ) -> None:
        self._watchlist = watchlist
        self._data = data
        self._research = research
        self._plans = plans

    def prepare(self) -> BrowserAcceptanceFixtureResult:
        security_id = "security_yihua"
        self._watchlist.add(
            "browser-acceptance:watchlist",
            SecurityIdentity(security_id, "SZSE", "002897", "CNY", "2017-09-07"),
        )
        self._watchlist.add(
            "browser-acceptance:watchlist-sentinel",
            SecurityIdentity("security_old", "SZSE", "000001", "CNY", "1991-04-03"),
        )
        snapshot = self._data.sync(
            SyncRequest(
                "browser-acceptance:sync",
                security_id,
                "002897",
                "2026-07-11",
                datetime(2026, 7, 11, tzinfo=timezone.utc),
                "Asia/Shanghai",
                "SZSE",
                SnapshotPurpose.WORKFLOW,
                ("trade_cal", "market_universe", "daily"),
                network_authorized=True,
                offline=False,
            )
        )
        if snapshot.snapshot_id is None or snapshot.effective_session_date is None:
            raise ValueError("BROWSER_FIXTURE_SNAPSHOT_UNAVAILABLE")
        research = self._research.handle(
            StartResearchWorkflow(
                ResearchWorkflowRequest(
                    schema_version="ResearchWorkflowRequest@2",
                    invocation_id="browser-acceptance:research",
                    security_id=security_id,
                    requested_date=snapshot.requested_date,
                    effective_session_date=snapshot.effective_session_date,
                    data_snapshot_id=snapshot.snapshot_id,
                    evaluation_plan=ResearchEvaluationPlan(
                        schema_version="ResearchEvaluationPlan@1",
                        purpose=EvaluationPurpose.COMPANY_OUTLOOK,
                        horizon=EvaluationHorizon(
                            as_of=snapshot.requested_date,
                            forecast_end="2028-12-31",
                            review_by="2026-10-11",
                        ),
                        required_dimensions=(
                            EvaluationDimension.SOURCE_QUALITY,
                            EvaluationDimension.FORECAST,
                            EvaluationDimension.VALUATION,
                        ),
                        strategy_validation=(
                            StrategyValidationSelection.NOT_REQUESTED
                        ),
                    ),
                )
            )
        )
        plan = self._plans.create_draft(
            CreatePlanDraftCommand(
                "browser-acceptance:plan-draft",
                PlanDraftContent(
                    security_id=security_id,
                    based_on_version_id=None,
                    references=(
                        PlanReference("ResearchRun", research.research_run_id),
                        PlanReference(
                            "Evidence",
                            "browser-acceptance:fixture",
                            "unresolved_external",
                        ),
                    ),
                    data_snapshot_id=snapshot.snapshot_id,
                    horizon_start="2026-07-11",
                    horizon_end="2026-10-11",
                    review_by="2026-08-11",
                    rules=(
                        PlanRule(
                            "browser_acceptance_review",
                            "entry_review",
                            "prompt_review",
                            "entry",
                            PlanCondition(
                                "leaf",
                                "security.close_unadjusted",
                                "lte",
                                PlanConstant(
                                    "decimal",
                                    "82.33",
                                    "CNY_per_share",
                                    "CNY",
                                ),
                                "current_complete_session",
                            ),
                        ),
                    ),
                    max_planned_notional="10000",
                    max_planned_loss="500",
                    currency="CNY",
                    market_gate_policy_version="market-gate@1",
                    metric_catalog_version="metric-catalog@1",
                    evaluator_policy_version="plan-evaluator@1",
                    user_input_source="user_fixture_input",
                    rationale="用户声明的验收规则，仅用于验证计划确认流程，不构成投资建议。",
                ),
            )
        )
        return BrowserAcceptanceFixtureResult(
            security_id,
            snapshot.snapshot_id,
            research.workflow_run_id,
            research.research_run_id,
            plan.draft_id,
        )

    @staticmethod
    def _load(path: Path) -> Mapping[str, object]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("BROWSER_FIXTURE_INPUT_INVALID")
        return value


def load_browser_fixture(
    manifest_path: Path,
) -> tuple[FixtureProvider, QueryPolicy, SourcePolicy, dict[tuple[str, str], FixtureRights]]:
    root = manifest_path.resolve().parent
    manifest = BrowserAcceptanceFixture._load(manifest_path.resolve())
    members = manifest.get("members")
    if not isinstance(members, list) or not members:
        raise ValueError("BROWSER_FIXTURE_MANIFEST_INVALID")
    payloads: dict[str, bytes] = {}
    rights: dict[tuple[str, str], FixtureRights] = {}
    provider_id = "browser-acceptance-fixture"
    source_identity = "derived-fact-fixture:" + str(manifest["safe_capture_sha256"])
    fixture_policy = manifest.get("derived_fact_fixture")
    if not isinstance(fixture_policy, dict):
        raise ValueError("BROWSER_FIXTURE_RIGHTS_INVALID")
    for raw_member in members:
        if not isinstance(raw_member, dict):
            raise ValueError("BROWSER_FIXTURE_MANIFEST_INVALID")
        member_id = str(raw_member["member_id"])
        target = (root / str(raw_member["payload_path"])).resolve()
        if root not in target.parents or not target.is_file():
            raise ValueError("BROWSER_FIXTURE_MEMBER_INVALID")
        payload = target.read_bytes().rstrip(b"\r\n")
        if hashlib.sha256(payload).hexdigest() != raw_member.get("payload_sha256"):
            raise ValueError("BROWSER_FIXTURE_MEMBER_HASH_MISMATCH")
        raw_rights = raw_member.get("rights")
        if not isinstance(raw_rights, dict):
            raise ValueError("BROWSER_FIXTURE_RIGHTS_INVALID")
        dataset = "market_universe" if member_id == "market_universe" else member_id
        payloads[dataset] = payload
        rights[(provider_id, dataset)] = FixtureRights(
            member_id=member_id,
            source_identity=source_identity,
            local_storage_allowed=raw_rights.get("local_storage_allowed") is True,
            deterministic_replay_allowed=raw_rights.get("deterministic_replay_allowed")
            is True,
            repository_redistribution_allowed=raw_rights.get(
                "repository_redistribution_allowed"
            )
            is True,
            packaged_distribution_allowed=raw_rights.get(
                "packaged_distribution_allowed"
            )
            is True,
            terms_version=str(fixture_policy["terms_version"]),
            reviewed_on=str(fixture_policy["reviewed_on"]),
        )
    provider = FixtureProvider(
        provider_id,
        "fixture@1",
        payloads,
        source_identity,
        "derived-fact-fixture-terms@1",
    )
    query_policy = QueryPolicy("QueryPolicy@1", 7, "L", "none")
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        source_identity,
        SourceAuthority.FIXTURE,
        "derived-fact-fixture-terms@1",
        SourceRights(True, True, True, True, False, "2026-07-24"),
        tuple(SourceRoute(dataset, 1, CompletenessRequirement.REQUIRED, 1, FallbackMode.NO_FALLBACK, SourceFailureDisposition.BLOCK) for dataset in payloads),
    )
    return provider, query_policy, source_policy, rights


__all__ = [
    "BrowserAcceptanceFixture",
    "BrowserAcceptanceFixtureResult",
    "load_browser_fixture",
]
