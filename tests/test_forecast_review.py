from dataclasses import replace
from decimal import Decimal

import pytest

from equity_research import (
    ActualResultEvidence,
    CalibrationChange,
    ComparabilityStatus,
    ForecastReviewEngine,
    ForecastReviewInvariantError,
    ForecastReviewRequest,
    NumericForecastTarget,
    ProbabilityForecastTarget,
)


def evidence(
    evidence_id: str,
    metric_id: str,
    value: str | None,
    *,
    status: ComparabilityStatus = ComparabilityStatus.COMPARABLE,
    explanation: str = "Same definition and reporting basis as the forecast.",
) -> ActualResultEvidence:
    return ActualResultEvidence(
        evidence_id=evidence_id,
        normalized_version_id=f"normalized:{evidence_id}",
        metric_id=metric_id,
        value=None if value is None else Decimal(value),
        unit="CNYm",
        scale=Decimal("1"),
        currency="CNY",
        period="FY2026",
        published_at="2027-03-20T08:00:00+08:00",
        available_at="2027-03-20T08:00:00+08:00",
        retrieved_at="2027-03-20T09:00:00+08:00",
        source_id="cninfo:annual-report:2026",
        official=True,
        comparability_status=status,
        comparability_explanation=explanation,
    )


def request() -> ForecastReviewRequest:
    change = CalibrationChange(
        assumption_id="gross-margin",
        previous_version_identity="assumption:gross-margin@1",
        new_version_identity="pending",
        previous_value=Decimal("0.22"),
        new_value=Decimal("0.19"),
        unit="decimal",
        rationale="Observed unit economics were below the frozen base case.",
        evidence_refs=("actual-margin",),
    )
    change = replace(
        change,
        new_version_identity=(
            ForecastReviewEngine.calibrated_assumption_identity(change)
        ),
    )
    return ForecastReviewRequest(
        review_id="forecast-review-2026",
        security_id="002897.SZ",
        reviewed_at="2027-03-21T09:00:00+08:00",
        reviewer_identity="local-user@1",
        policy_identity="forecast-review-policy@1",
        review_data_snapshot_id="snapshot:review:2027-03-21",
        forecast_artifact_record_id="forecast-record@1",
        valuation_artifact_record_id="valuation-record@1",
        simulation_artifact_record_id="simulation-record@1",
        forecast_source_identity="forecast-graph@1",
        valuation_source_identity="valuation-scenario-set@1",
        simulation_source_identity="valuation-simulation@1",
        actual_evidence=(
            evidence("actual-event", "capacity_release", "1"),
            evidence("actual-revenue", "revenue", "108"),
            evidence("actual-margin", "gross_profit", "18"),
            evidence(
                "actual-restated",
                "operating_profit",
                "9",
                status=ComparabilityStatus.RESTATED,
                explanation="The issuer restated the segment boundary.",
            ),
        ),
        probability_targets=(
            ProbabilityForecastTarget(
                target_id="event-capacity-release",
                event_id="capacity_release",
                probability=Decimal("0.7"),
                outcome_evidence_id="actual-event",
            ),
        ),
        numeric_targets=(
            NumericForecastTarget(
                target_id="driver-revenue",
                driver_id="volume_x_asp",
                metric_id="revenue",
                forecast_low=Decimal("90"),
                forecast_base=Decimal("100"),
                forecast_high=Decimal("110"),
                unit="CNYm",
                scale=Decimal("1"),
                currency="CNY",
                period="FY2026",
                actual_evidence_id="actual-revenue",
            ),
            NumericForecastTarget(
                target_id="driver-gross-profit",
                driver_id="unit_economics",
                metric_id="gross_profit",
                forecast_low=Decimal("20"),
                forecast_base=Decimal("22"),
                forecast_high=Decimal("24"),
                unit="CNYm",
                scale=Decimal("1"),
                currency="CNY",
                period="FY2026",
                actual_evidence_id="actual-margin",
            ),
            NumericForecastTarget(
                target_id="driver-operating-profit",
                driver_id="unit_economics",
                metric_id="operating_profit",
                forecast_low=Decimal("10"),
                forecast_base=Decimal("12"),
                forecast_high=Decimal("14"),
                unit="CNYm",
                scale=Decimal("1"),
                currency="CNY",
                period="FY2026",
                actual_evidence_id="actual-restated",
            ),
        ),
        previous_model_identity="company-outlook-model@1",
        new_model_identity=ForecastReviewEngine.calibrated_model_identity(
            "company-outlook-model@1",
            (change,),
        ),
        calibration_changes=(change,),
    )


def test_review_scores_only_comparable_outcomes_and_creates_new_calibration_version() -> None:
    result = ForecastReviewEngine().run(request())

    assert result.status == "partial"
    assert result.probability_results[0].brier_score == Decimal("0.09")
    assert result.numeric_results[0].absolute_error == Decimal("8")
    assert result.numeric_results[0].relative_error == Decimal("0.08")
    assert result.numeric_results[0].direction == "actual_above_forecast"
    assert result.numeric_results[0].interval_covered is True
    assert result.numeric_results[1].absolute_error == Decimal("4")
    assert result.numeric_results[1].relative_error == Decimal(
        "0.1818181818181818181818181818"
    )
    assert result.numeric_results[1].direction == "actual_below_forecast"
    assert result.numeric_results[1].interval_covered is False
    assert result.numeric_results[2].comparability_status == "restated"
    assert result.numeric_results[2].absolute_error is None
    assert result.numeric_interval_coverage == Decimal("0.5")
    assert result.driver_error_decomposition == (
        {
            "driver_id": "volume_x_asp",
            "unit": "CNYm",
            "currency": "CNY",
            "period": "FY2026",
            "scale": "1",
            "absolute_error": "8",
            "share": "0.6666666666666666666666666667",
        },
        {
            "driver_id": "unit_economics",
            "unit": "CNYm",
            "currency": "CNY",
            "period": "FY2026",
            "scale": "1",
            "absolute_error": "4",
            "share": "0.3333333333333333333333333333",
        },
    )
    assert result.calibration_version == {
        "previous_model_identity": "company-outlook-model@1",
        "new_model_identity": request().new_model_identity,
        "assumption_versions": [
            {
                "assumption_id": "gross-margin",
                "previous_version_identity": "assumption:gross-margin@1",
                "new_version_identity": (
                    request().calibration_changes[0].new_version_identity
                ),
                "previous_value": "0.22",
                "new_value": "0.19",
                "unit": "decimal",
                "rationale": (
                    "Observed unit economics were below the frozen base case."
                ),
                "evidence_refs": ["actual-margin"],
            }
        ],
    }
    assert "单次复核" in result.interpretation


@pytest.mark.parametrize(
    "invalid,code",
    [
        (
            replace(
                request(),
                new_model_identity="company-outlook-model@1",
            ),
            "FORECAST_REVIEW_MODEL_VERSION_NOT_ADVANCED",
        ),
        (
            replace(
                request(),
                calibration_changes=(
                    replace(
                        request().calibration_changes[0],
                        new_version_identity="assumption:gross-margin@1",
                    ),
                ),
            ),
            "FORECAST_REVIEW_ASSUMPTION_VERSION_NOT_ADVANCED",
        ),
        (
            replace(
                request(),
                actual_evidence=(
                    *request().actual_evidence[:-1],
                    replace(
                        request().actual_evidence[-1],
                        comparability_status=ComparabilityStatus.MISSING,
                    ),
                ),
            ),
            "FORECAST_REVIEW_MISSING_EVIDENCE_HAS_VALUE",
        ),
    ],
)
def test_review_fails_closed_when_versions_or_comparability_are_invalid(
    invalid: ForecastReviewRequest,
    code: str,
) -> None:
    with pytest.raises(ForecastReviewInvariantError) as error:
        ForecastReviewEngine().run(invalid)

    assert error.value.code == code


def test_delayed_disclosure_is_recorded_without_becoming_a_forecast_failure() -> None:
    delayed = replace(
        request(),
        actual_evidence=(
            *request().actual_evidence[:-1],
            replace(
                request().actual_evidence[-1],
                value=None,
                published_at="",
                available_at="",
                comparability_status=ComparabilityStatus.DELAYED_DISCLOSURE,
                comparability_explanation=(
                    "The filing was due but had not been disclosed by review time."
                ),
            ),
        ),
        calibration_changes=(),
        previous_model_identity="",
        new_model_identity="",
    )

    result = ForecastReviewEngine().run(delayed)

    assert result.status == "partial"
    assert result.numeric_results[-1].comparability_status == (
        "delayed_disclosure"
    )
    assert result.numeric_results[-1].absolute_error is None
    assert "delayed_disclosure" in result.diagnostics[-1]


def test_driver_error_shares_are_calculated_only_within_matching_dimensions() -> None:
    base = request()
    margin_evidence = replace(
        base.actual_evidence[2],
        unit="decimal",
        currency="N/A",
        value=Decimal("0.18"),
    )
    dimensioned = replace(
        base,
        actual_evidence=(
            base.actual_evidence[0],
            base.actual_evidence[1],
            margin_evidence,
        ),
        numeric_targets=(
            base.numeric_targets[0],
            replace(
                base.numeric_targets[1],
                forecast_low=Decimal("0.20"),
                forecast_base=Decimal("0.22"),
                forecast_high=Decimal("0.24"),
                unit="decimal",
                currency="N/A",
            ),
        ),
        calibration_changes=(),
        previous_model_identity="",
        new_model_identity="",
    )

    result = ForecastReviewEngine().run(dimensioned)

    assert [item["share"] for item in result.driver_error_decomposition] == [
        "1",
        "1",
    ]
    assert {
        (item["unit"], item["currency"], item["period"])
        for item in result.driver_error_decomposition
    } == {
        ("CNYm", "CNY", "FY2026"),
        ("decimal", "N/A", "FY2026"),
    }
