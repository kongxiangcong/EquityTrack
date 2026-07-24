from trading_platform.application.contracts import StartResearchWorkflow

import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_research import (
    ActualResultEvidence,
    CalibrationChange,
    ComparabilityStatus,
    ForecastReviewEngine,
    ForecastReviewRequest,
    NumericForecastTarget,
)
from tests.platform.test_outlook_artifacts import _request
from tests.platform.test_research_workflow import CountingEngine, _root
from tests.platform.test_valuation_simulation_artifact import _simulation_drafts
from tests.platform.application_task_fixture import PlatformTaskFixture
from trading_platform.data.providers import FixtureProvider
from trading_platform.domain.data import (
    FetchBatch,
    CompletenessRequirement,
    FallbackMode,
    QueryPolicy,
    SourceFailureDisposition,
    FixtureRights,
    SnapshotPurpose,
    SourceAuthority,
    SourcePolicy,
    SourceRights,
    SourceRoute,
    SyncRequest,
    SyncStatus,
)


class ReviewFixtureProvider(FixtureProvider):
    def __init__(self, payloads, source_identity: str, retrieved_at: str) -> None:
        super().__init__(
            "forecast-review-fixture",
            "forecast-review-fixture@1",
            payloads,
            source_identity,
            "forecast-review-fixture-terms@1",
            SourceAuthority.OFFICIAL,
        )
        self._retrieved_at = datetime.fromisoformat(retrieved_at)

    def fetch(self, request):
        batch = super().fetch(request)
        return FetchBatch(
            tuple(
                replace(envelope, retrieved_at=self._retrieved_at)
                for envelope in batch.envelopes
            )
        )


def review_request(artifacts) -> ForecastReviewRequest:
    forecast, valuation, simulation = artifacts[1], artifacts[2], artifacts[3]
    scenarios = {
        scenario["role"]: scenario for scenario in valuation.payload["scenarios"]
    }
    node_id = "components.volume.2026E"

    def quantity(role: str):
        return next(
            node["quantity"]
            for node in scenarios[role]["forecast_graph"]["nodes"]
            if node["node_id"] == node_id
        )

    low = quantity("stress")
    base = quantity("base")
    high = quantity("improvement")
    assumption = next(
        item
        for item in simulation.payload["assumptions"]
        if item["assumption_id"] == "volume_growth"
    )
    change = CalibrationChange(
        assumption_id="volume_growth",
        previous_version_identity=(
            f"{simulation.source_identity}:assumption:volume_growth"
        ),
        new_version_identity="pending",
        previous_value=Decimal(assumption["reference_value"]),
        new_value=Decimal("0.04"),
        unit="decimal",
        rationale="Actual volume was closer to the frozen base scenario.",
        evidence_refs=("cninfo:2026-annual:revenue",),
    )
    change = replace(
        change,
        new_version_identity=(
            ForecastReviewEngine.calibrated_assumption_identity(change)
        ),
    )
    new_model_identity = ForecastReviewEngine.calibrated_model_identity(
        simulation.model_identity,
        (change,),
    )
    return ForecastReviewRequest(
        review_id="forecast-review:2026-results",
        security_id=forecast.subject_id,
        reviewed_at="2027-03-21T09:00:00+08:00",
        reviewer_identity="local-user@1",
        policy_identity="forecast-review-policy@1",
        review_data_snapshot_id="snapshot_forecast_review_20270321",
        forecast_artifact_record_id=forecast.artifact_record_id,
        valuation_artifact_record_id=valuation.artifact_record_id,
        simulation_artifact_record_id=simulation.artifact_record_id,
        forecast_source_identity=forecast.source_identity,
        valuation_source_identity=valuation.source_identity,
        simulation_source_identity=simulation.source_identity,
        actual_evidence=(
            ActualResultEvidence(
                evidence_id="cninfo:2026-annual:revenue",
                normalized_version_id="forecast-actual:revenue:2026FY:v1",
                metric_id=node_id,
                value=Decimal("109"),
                unit=base["unit"],
                scale=Decimal(base["scale"]),
                currency=base["currency"],
                period=base["period"],
                published_at="2027-03-20T08:00:00+08:00",
                available_at="2027-03-20T08:00:00+08:00",
                retrieved_at="2027-03-20T09:00:00+08:00",
                source_id="cninfo:annual-report:2026",
                official=True,
                comparability_status=ComparabilityStatus.COMPARABLE,
                comparability_explanation=(
                    "Same segment boundary and accounting basis as the forecast."
                ),
            ),
        ),
        probability_targets=(),
        numeric_targets=(
            NumericForecastTarget(
                target_id=node_id,
                driver_id="components.volume.2026E",
                metric_id=node_id,
                forecast_low=Decimal(low["value"]),
                forecast_base=Decimal(base["value"]),
                forecast_high=Decimal(high["value"]),
                unit=base["unit"],
                scale=Decimal(base["scale"]),
                currency=base["currency"],
                period=base["period"],
                actual_evidence_id="cninfo:2026-annual:revenue",
            ),
        ),
        previous_model_identity=simulation.model_identity,
        new_model_identity=new_model_identity,
        calibration_changes=(change,),
    )


def persist_review_snapshot(
    root: PlatformTaskFixture,
    request: ForecastReviewRequest,
) -> ForecastReviewRequest:
    actual = request.actual_evidence[0]
    common = {
        "availability_basis": "publisher_timestamp",
        "published_precision": "second",
    }
    payloads = {
        "trade_cal": json.dumps(
            {
                "rows": [
                    {
                        **common,
                        "market": "SZSE",
                        "session_date": "2027-03-20",
                        "is_open": True,
                        "calendar_version": "cn-calendar@2027",
                        "published_at": "2027-03-20T00:00:00+08:00",
                        "available_at": "2027-03-20T00:00:00+08:00",
                    }
                ]
            },
            sort_keys=True,
        ).encode(),
        "market_universe": json.dumps(
            {
                "rows": [
                    {
                        **common,
                        "market_scope_id": "SZSE",
                        "security_id": "security_yihua",
                        "listed_from": "2017-09-07",
                        "source_ref": f"{actual.source_id}:stock_basic",
                        "published_at": "2017-09-07T00:00:00+08:00",
                        "available_at": "2017-09-07T00:00:00+08:00",
                    }
                ]
            },
            sort_keys=True,
        ).encode(),
        "daily": json.dumps(
            {
                "rows": [
                    {
                        **common,
                        "security_id": "security_yihua",
                        "session_date": "2027-03-20",
                        "market_timezone": "Asia/Shanghai",
                        "adjustment_mode": "none",
                        "open": "80",
                        "high": "82",
                        "low": "79",
                        "close": "81",
                        "volume": "100",
                        "volume_unit": "hand",
                        "amount": "8100",
                        "amount_unit": "CNY",
                        "currency": "CNY",
                        "published_at": "2027-03-20T15:00:00+08:00",
                        "available_at": "2027-03-20T15:00:00+08:00",
                    }
                ]
            },
            sort_keys=True,
        ).encode(),
        "forecast_actual": json.dumps(
            {
                "rows": [
                    {
                        **common,
                        "security_id": "security_yihua",
                        "metric_id": actual.metric_id,
                        "value": str(actual.value),
                        "unit": actual.unit,
                        "scale": str(actual.scale),
                        "currency": actual.currency,
                        "period": actual.period,
                        "published_at": actual.published_at,
                        "available_at": actual.available_at,
                        "source_id": actual.source_id,
                        "official": actual.official,
                        "comparability_status": actual.comparability_status.value,
                    }
                ]
            },
            sort_keys=True,
        ).encode(),
    }
    provider = ReviewFixtureProvider(payloads, actual.source_id, actual.retrieved_at)
    rights = {
        (provider.provider_id, dataset): FixtureRights(
            f"forecast-review:{dataset}",
            actual.source_id,
            True,
            True,
            True,
            True,
            "forecast-review-fixture-terms@1",
            "2027-03-21",
        )
        for dataset in payloads
    }
    query_policy = QueryPolicy("QueryPolicy@1", 7, "L", "none")
    source_policy = SourcePolicy(
        "SourcePolicy@1",
        provider.provider_id,
        provider.adapter_version,
        actual.source_id,
        SourceAuthority.OFFICIAL,
        "forecast-review-fixture-terms@1",
        SourceRights(True, True, False),
        tuple(SourceRoute(dataset, 1, CompletenessRequirement.REQUIRED, 1, FallbackMode.NO_FALLBACK, SourceFailureDisposition.BLOCK) for dataset in payloads),
    )
    data_tasks = PlatformTaskFixture(
        root.data_root,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
        fixture_rights=rights,
    )
    sync = data_tasks.data.sync(
        SyncRequest(
            "forecast-review-evidence",
            "security_yihua",
            "002897",
            "2027-03-21",
            datetime.fromisoformat("2027-03-21T00:00:00+08:00"),
            "Asia/Shanghai",
            "SZSE",
            SnapshotPurpose.RESEARCH,
            tuple(payloads),
            False,
            False,
        )
    )
    assert sync.status is SyncStatus.COMPLETE
    assert sync.snapshot_id is not None
    evidence = data_tasks.inspection.snapshot(sync.snapshot_id)
    normalized_version_id = next(
        version_id
        for version_id, dataset in evidence.members.items()
        if dataset == "forecast_actual"
    )
    data_tasks.close()
    return replace(
        request,
        review_data_snapshot_id=sync.snapshot_id,
        actual_evidence=(
            replace(actual, normalized_version_id=normalized_version_id),
        ),
    )


def test_review_is_append_only_replayable_and_visible_in_workspace(
    tmp_path: Path,
) -> None:
    engine = CountingEngine()
    root = _root(tmp_path, engine)
    run = root.research.handle(StartResearchWorkflow(_request("forecast-review:parents", _simulation_drafts())))
    parents = tuple(
        root.archive.artifact(record_id)
        for record_id in run.artifact_record_ids
    )
    request = review_request(parents)
    request = persist_review_snapshot(root, request)

    first = root.forecast_review.review(request)
    replay = root.forecast_review.review(request)

    assert replay.artifact_record_id == first.artifact_record_id
    assert first.artifact_kind == "ForecastReview"
    assert first.as_of == "2027-03-21"
    assert first.data_snapshot_id == request.review_data_snapshot_id
    assert first.model_identity == request.new_model_identity
    assert first.code_identity == parents[0].code_identity
    assert first.dependency_record_ids == tuple(
        sorted(run.artifact_record_ids[1:4])
    )
    assert first.payload["numeric_results"][0]["absolute_error"] == "4"
    assert first.payload["numeric_interval_coverage"] == "1"
    assert first.payload["calibration_version"]["new_model_identity"] == (
        request.new_model_identity
    )
    assert root.archive.artifact(first.artifact_record_id) == first
    assert root.archive.artifact(
        run.artifact_record_ids[-1]
    ).content_hash == parents[-1].content_hash
    history = root.inspection.inspect(run.workflow_run_id)
    review_manifest = next(
        item["ref_id"]
        for item in history.refs
        if item["ref_role"] == "forecast_review_manifest"
    )
    assert [
        item["member_role"]
        for item in root.archive.manifest(review_manifest).members
    ] == ["forecast", "valuation", "simulation", "forecast_review"]
    workspace = root.workspace.build(
        "security_yihua",
        run.research_snapshot_id,
    )
    assert workspace["forecast_registry"][0]["review_status"] == "reviewed"
    assert workspace["forecast_reviews"][0]["artifact_record_id"] == (
        first.artifact_record_id
    )
    assert workspace["forecast_reviews"][0]["interpretation"].startswith(
        "ForecastReview measures"
    )
    root.close()

    rebuilt = PlatformTaskFixture(tmp_path, research_engine=engine)
    restored = rebuilt.archive.artifact(first.artifact_record_id)
    assert restored.content_hash == first.content_hash
    assert (
        rebuilt.workspace.build(
            "security_yihua",
            run.research_snapshot_id,
        )["forecast_reviews"][0]["artifact_record_id"]
        == first.artifact_record_id
    )
    rebuilt.close()


def test_review_rejects_forged_parent_or_scenario_values(tmp_path: Path) -> None:
    root = _root(tmp_path, CountingEngine())
    run = root.research.handle(StartResearchWorkflow(_request("forecast-review:invalid", _simulation_drafts())))
    parents = tuple(
        root.archive.artifact(record_id)
        for record_id in run.artifact_record_ids
    )
    valid = review_request(parents)
    valid = persist_review_snapshot(root, valid)

    with pytest.raises(ValueError, match="FORECAST_REVIEW_PARENT_LINEAGE_INVALID"):
        root.forecast_review.review(
            replace(valid, forecast_source_identity="forged-forecast")
        )
    with pytest.raises(ValueError, match="FORECAST_REVIEW_TARGET_LINEAGE_INVALID"):
        root.forecast_review.review(
            replace(
                valid,
                numeric_targets=(
                    replace(
                        valid.numeric_targets[0],
                        forecast_base=Decimal("106"),
                    ),
                ),
            )
        )
    with pytest.raises(
        ValueError,
        match="FORECAST_REVIEW_EVIDENCE_LINEAGE_INVALID",
    ):
        root.forecast_review.review(
            replace(
                valid,
                actual_evidence=(
                    replace(valid.actual_evidence[0], value=Decimal("110")),
                ),
            )
        )
    with pytest.raises(
        ValueError,
        match="FORECAST_REVIEW_CALIBRATION_LINEAGE_INVALID",
    ):
        root.forecast_review.review(
            replace(
                valid,
                previous_model_identity="fabricated-model@0",
                new_model_identity=(
                    ForecastReviewEngine.calibrated_model_identity(
                        "fabricated-model@0",
                        valid.calibration_changes,
                    )
                ),
            )
        )
    fabricated_assumption = replace(
        valid.calibration_changes[0],
        assumption_id="fabricated-assumption",
        new_version_identity="pending",
    )
    fabricated_assumption = replace(
        fabricated_assumption,
        new_version_identity=(
            ForecastReviewEngine.calibrated_assumption_identity(
                fabricated_assumption
            )
        ),
    )
    with pytest.raises(
        ValueError,
        match="FORECAST_REVIEW_CALIBRATION_LINEAGE_INVALID",
    ):
        root.forecast_review.review(
            replace(
                valid,
                calibration_changes=(fabricated_assumption,),
                new_model_identity=(
                    ForecastReviewEngine.calibrated_model_identity(
                        valid.previous_model_identity,
                        (fabricated_assumption,),
                    )
                ),
            )
        )
    wrong_unit = replace(
        valid.calibration_changes[0],
        unit="kg",
        new_version_identity="pending",
    )
    wrong_unit = replace(
        wrong_unit,
        new_version_identity=(
            ForecastReviewEngine.calibrated_assumption_identity(wrong_unit)
        ),
    )
    with pytest.raises(
        ValueError,
        match="FORECAST_REVIEW_CALIBRATION_LINEAGE_INVALID",
    ):
        root.forecast_review.review(
            replace(
                valid,
                calibration_changes=(wrong_unit,),
                new_model_identity=(
                    ForecastReviewEngine.calibrated_model_identity(
                        valid.previous_model_identity,
                        (wrong_unit,),
                    )
                ),
            )
        )
    out_of_bounds = replace(
        valid.calibration_changes[0],
        new_value=Decimal("2"),
        new_version_identity="pending",
    )
    out_of_bounds = replace(
        out_of_bounds,
        new_version_identity=(
            ForecastReviewEngine.calibrated_assumption_identity(out_of_bounds)
        ),
    )
    with pytest.raises(
        ValueError,
        match="FORECAST_REVIEW_CALIBRATION_LINEAGE_INVALID",
    ):
        root.forecast_review.review(
            replace(
                valid,
                calibration_changes=(out_of_bounds,),
                new_model_identity=(
                    ForecastReviewEngine.calibrated_model_identity(
                        valid.previous_model_identity,
                        (out_of_bounds,),
                    )
                ),
            )
        )
    root.close()
