from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from equity_research.forecast import (
    CompanyArchetype,
    DataInsufficientForecastRequest,
    DataInsufficientSnapshot,
    ForecastEngine,
    Security,
)
from equity_research.scenario_valuation import (
    DataInsufficientScenarioRequest,
    ScenarioValuationEngine,
)
from equity_research import validate_source_manifest_runtime
from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.data.service import DataSyncService
from trading_platform.data.providers import FixtureProvider
from trading_platform.domain.data import FixtureRights, SnapshotPurpose, SyncRequest
from trading_platform.domain.plans import (
    CreatePlanDraftCommand,
    PlanCondition,
    PlanConstant,
    PlanDraftContent,
    PlanReference,
    PlanRule,
)
from trading_platform.domain.research_inputs import ResearchInputs
from trading_platform.domain.workflow import (
    FieldSemantics,
    ImmutableArtifactDraft,
    ResearchProjection,
    ResearchWorkflowRequest,
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
        repo_root: Path,
    ) -> None:
        self._watchlist = watchlist
        self._data = data
        self._research = research
        self._plans = plans
        self._repo_root = repo_root

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
                "002897.SZ",
                "2026-07-11",
                datetime(2026, 7, 11, tzinfo=timezone.utc),
                "Asia/Shanghai",
                "SZSE",
                SnapshotPurpose.CHART,
                ("trade_cal", "market_universe", "daily"),
                network_authorized=True,
                offline=False,
            )
        )
        projection = self._projection()
        analysis_artifacts = self.analysis_artifacts(security_id)
        research = self._research.handle(
            StartResearchWorkflow(
                ResearchWorkflowRequest(
                    invocation_id="browser-acceptance:research",
                    security_id=security_id,
                    requested_date="2026-07-07",
                    effective_session_date="2026-07-07",
                    projection=projection,
                    analysis_artifacts=analysis_artifacts,
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

    def _projection(self) -> ResearchProjection:
        example = self._repo_root / "examples" / "yihua-002897"
        manifest = self._load(example / "source_manifest.json")
        semantics = tuple(
            FieldSemantics(
                source_id=str(source["source_id"]),
                source_authority=str(source["tier"]),
                field_name=str(field["field_name"]),
                period=str(field["period"]),
                statement_scope=str(field.get("statement_scope", "consolidated")),
                unit=str(field.get("unit", "")),
                currency=str(field.get("currency", "")),
                scale=str(field.get("scale", "1")),
                restatement_status=str(field.get("restatement_status", "as_reported")),
                published_at=str(source.get("published_at", source["report_date"])),
                available_at=str(source["retrieved_at"]),
                retrieved_at=str(source["retrieved_at"]),
                supersedes_identity=(
                    str(source["supersedes_identity"])
                    if source.get("supersedes_identity") is not None
                    else None
                ),
                availability_basis=(
                    "publisher_timestamp"
                    if source.get("available_at")
                    else "conservative_retrieval_time"
                ),
            )
            for source in manifest["sources"]
            for field in source["extracted_fields"]
        )
        source_validation = validate_source_manifest_runtime(
            manifest,
            example / "source_manifest.json",
        )
        return ResearchProjection(
            manifest=manifest,
            estimates=self._load(example / "estimate_overlay.json"),
            research_inputs=replace(
                ResearchInputs.from_mapping(
                    self._load(example / "research_context.json")
                ),
                workflow_research_member_ids=(),
            ),
            as_of_date="2026-07-07",
            profile="standard",
            field_semantics=semantics,
            diluted_share_identity="SRC_CNINFO_2026Q1:diluted_shares:2026Q1",
            net_debt_bridge_identity="SRC_CNINFO_2026Q1:cash+debt:2026Q1",
            source_manifest_validation_result=source_validation,
            source_manifest_path="examples/yihua-002897/source_manifest.json",
        )

    @staticmethod
    def analysis_artifacts(
        security_id: str,
    ) -> tuple[ImmutableArtifactDraft, ...]:
        """Build a fail-closed analysis set containing no financial claims."""

        snapshot = DataInsufficientSnapshot(
            snapshot_id="browser-acceptance-analysis-snapshot",
            security_id=security_id,
            as_of="2026-07-07",
            missing_fields=(
                "official_financial_statements",
                "valuation_method_inputs",
            ),
        )
        request = DataInsufficientForecastRequest(
            security=Security(
                security_id,
                "温州意华接插件股份有限公司",
                "SZSE",
                "CNY",
                CompanyArchetype.GENERAL_MANUFACTURING,
                ("company",),
            ),
            as_of=snapshot.as_of,
            data_snapshot=snapshot,
            forecast_periods=("2027E",),
            review_date="2026-08-07",
        )
        forecast = ForecastEngine().build(request)
        valuation = ScenarioValuationEngine().run(
            DataInsufficientScenarioRequest(forecast, "2027E")
        )
        identities = {
            "model_identity": "browser-acceptance-analysis@1",
            "policy_identity": "data-insufficient-browser-acceptance@1",
        }
        return (
            ImmutableArtifactDraft.from_data_snapshot(snapshot, **identities),
            ImmutableArtifactDraft.from_forecast_graph(forecast, **identities),
            ImmutableArtifactDraft.from_scenario_valuation(
                valuation,
                forecast_graph=forecast,
                **identities,
            ),
        )

    @staticmethod
    def _load(path: Path) -> Mapping[str, object]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("BROWSER_FIXTURE_INPUT_INVALID")
        return value


def load_browser_fixture(
    manifest_path: Path,
) -> tuple[FixtureProvider, dict[tuple[str, str], FixtureRights]]:
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
    return provider, rights


__all__ = [
    "BrowserAcceptanceFixture",
    "BrowserAcceptanceFixtureResult",
    "load_browser_fixture",
]
