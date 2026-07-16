from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import Enum
from typing import Any

from .financial import valuation_decimal_context


class ForecastReviewInvariantError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ComparabilityStatus(str, Enum):
    COMPARABLE = "comparable"
    MISSING = "missing"
    RESTATED = "restated"
    BASIS_CHANGED = "basis_changed"
    DELAYED_DISCLOSURE = "delayed_disclosure"


def _text(value: Decimal) -> str:
    with valuation_decimal_context():
        if value == 0:
            return "0"
        return format(value.normalize(), "f")


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ForecastReviewInvariantError(
            "FORECAST_REVIEW_TIMESTAMP_INVALID",
            f"{field_name} must be an ISO timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        raise ForecastReviewInvariantError(
            "FORECAST_REVIEW_TIMESTAMP_INVALID",
            f"{field_name} must include an explicit timezone.",
        )
    return parsed


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ForecastReviewInvariantError(
            "FORECAST_REVIEW_DECIMAL_REQUIRED",
            f"{field_name} must be a finite Decimal.",
        )
    return value


@dataclass(frozen=True)
class ActualResultEvidence:
    evidence_id: str
    normalized_version_id: str
    metric_id: str
    value: Decimal | None
    unit: str
    scale: Decimal
    currency: str
    period: str
    published_at: str
    available_at: str
    retrieved_at: str
    source_id: str
    official: bool
    comparability_status: ComparabilityStatus
    comparability_explanation: str

    @property
    def semantic_content_hash(self) -> str:
        value = {
            "metric_id": self.metric_id,
            "value": None if self.value is None else _text(self.value),
            "unit": self.unit,
            "scale": _text(self.scale),
            "currency": self.currency,
            "period": self.period,
            "published_at": self.published_at,
            "available_at": self.available_at,
            "source_id": self.source_id,
            "official": self.official,
            "comparability_status": self.comparability_status.value,
        }
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def validate(self, reviewed_at: datetime) -> None:
        if not all(
            (
                self.evidence_id,
                self.normalized_version_id,
                self.metric_id,
                self.unit,
                self.period,
                self.source_id,
                self.comparability_explanation,
            )
        ):
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_EVIDENCE_IDENTITY_INVALID",
                "Actual evidence requires identity, dimensions, source, and a comparability explanation.",
            )
        _decimal(self.scale, "ActualResultEvidence.scale")
        if self.scale <= 0:
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_SCALE_INVALID",
                "Actual evidence scale must be positive.",
            )
        absent_statuses = {
            ComparabilityStatus.MISSING,
            ComparabilityStatus.DELAYED_DISCLOSURE,
        }
        if self.comparability_status in absent_statuses:
            if self.value is not None:
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_MISSING_EVIDENCE_HAS_VALUE",
                    "Missing or delayed evidence cannot silently carry an observed value.",
                )
        elif self.value is None:
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_EVIDENCE_VALUE_MISSING",
                "Non-missing evidence requires an observed value.",
            )
        else:
            _decimal(self.value, "ActualResultEvidence.value")
            if (
                self.comparability_status is ComparabilityStatus.COMPARABLE
                and not self.official
            ):
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_OFFICIAL_EVIDENCE_REQUIRED",
                    "Comparable actual results require official disclosure evidence.",
                )
        retrieved = _timestamp(self.retrieved_at, "retrieved_at")
        if self.comparability_status in absent_statuses:
            if self.published_at or self.available_at or retrieved > reviewed_at:
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_EVIDENCE_TIME_INVALID",
                    "Missing or delayed evidence has no publication/availability time and must preserve a completed retrieval attempt.",
                )
        else:
            published = _timestamp(self.published_at, "published_at")
            available = _timestamp(self.available_at, "available_at")
            if not published <= available <= retrieved <= reviewed_at:
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_EVIDENCE_TIME_INVALID",
                    "Evidence publication, availability, retrieval, and review times must be ordered.",
                )
        if retrieved > reviewed_at:
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_EVIDENCE_TIME_INVALID",
                "Evidence retrieval cannot occur after the review.",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "normalized_version_id": self.normalized_version_id,
            "semantic_content_hash": self.semantic_content_hash,
            "metric_id": self.metric_id,
            "value": None if self.value is None else _text(self.value),
            "unit": self.unit,
            "scale": _text(self.scale),
            "currency": self.currency,
            "period": self.period,
            "published_at": self.published_at,
            "available_at": self.available_at,
            "retrieved_at": self.retrieved_at,
            "source_id": self.source_id,
            "official": self.official,
            "comparability_status": self.comparability_status.value,
            "comparability_explanation": self.comparability_explanation,
        }


@dataclass(frozen=True)
class ProbabilityForecastTarget:
    target_id: str
    event_id: str
    probability: Decimal
    outcome_evidence_id: str


@dataclass(frozen=True)
class NumericForecastTarget:
    target_id: str
    driver_id: str
    metric_id: str
    forecast_low: Decimal
    forecast_base: Decimal
    forecast_high: Decimal
    unit: str
    scale: Decimal
    currency: str
    period: str
    actual_evidence_id: str


@dataclass(frozen=True)
class CalibrationChange:
    assumption_id: str
    previous_version_identity: str
    new_version_identity: str
    previous_value: Decimal
    new_value: Decimal
    unit: str
    rationale: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "previous_version_identity": self.previous_version_identity,
            "new_version_identity": self.new_version_identity,
            "previous_value": _text(self.previous_value),
            "new_value": _text(self.new_value),
            "unit": self.unit,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ForecastReviewRequest:
    review_id: str
    security_id: str
    reviewed_at: str
    reviewer_identity: str
    policy_identity: str
    review_data_snapshot_id: str
    forecast_artifact_record_id: str
    valuation_artifact_record_id: str
    simulation_artifact_record_id: str
    forecast_source_identity: str
    valuation_source_identity: str
    simulation_source_identity: str
    actual_evidence: tuple[ActualResultEvidence, ...]
    probability_targets: tuple[ProbabilityForecastTarget, ...]
    numeric_targets: tuple[NumericForecastTarget, ...]
    previous_model_identity: str
    new_model_identity: str
    calibration_changes: tuple[CalibrationChange, ...]


@dataclass(frozen=True)
class ProbabilityReviewResult:
    target_id: str
    event_id: str
    forecast_probability: Decimal
    observed_outcome: Decimal | None
    evidence_id: str
    comparability_status: str
    comparability_explanation: str
    brier_score: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "event_id": self.event_id,
            "forecast_probability": _text(self.forecast_probability),
            "observed_outcome": (
                None if self.observed_outcome is None else _text(self.observed_outcome)
            ),
            "evidence_id": self.evidence_id,
            "comparability_status": self.comparability_status,
            "comparability_explanation": self.comparability_explanation,
            "brier_score": None if self.brier_score is None else _text(self.brier_score),
        }


@dataclass(frozen=True)
class NumericReviewResult:
    target_id: str
    driver_id: str
    metric_id: str
    evidence_id: str
    comparability_status: str
    comparability_explanation: str
    absolute_error: Decimal | None
    relative_error: Decimal | None
    direction: str | None
    interval_covered: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "driver_id": self.driver_id,
            "metric_id": self.metric_id,
            "evidence_id": self.evidence_id,
            "comparability_status": self.comparability_status,
            "comparability_explanation": self.comparability_explanation,
            "absolute_error": (
                None if self.absolute_error is None else _text(self.absolute_error)
            ),
            "relative_error": (
                None if self.relative_error is None else _text(self.relative_error)
            ),
            "direction": self.direction,
            "interval_covered": self.interval_covered,
        }


@dataclass(frozen=True)
class ForecastReviewResult:
    request: ForecastReviewRequest
    status: str
    probability_results: tuple[ProbabilityReviewResult, ...]
    numeric_results: tuple[NumericReviewResult, ...]
    numeric_interval_coverage: Decimal | None
    driver_error_decomposition: tuple[dict[str, str], ...]
    calibration_version: dict[str, Any] | None
    interpretation: str
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        request = self.request
        return {
            "review_id": request.review_id,
            "security_id": request.security_id,
            "reviewed_at": request.reviewed_at,
            "reviewer_identity": request.reviewer_identity,
            "policy_identity": request.policy_identity,
            "review_data_snapshot_id": request.review_data_snapshot_id,
            "original_artifacts": {
                "forecast_artifact_record_id": request.forecast_artifact_record_id,
                "valuation_artifact_record_id": request.valuation_artifact_record_id,
                "simulation_artifact_record_id": request.simulation_artifact_record_id,
                "forecast_source_identity": request.forecast_source_identity,
                "valuation_source_identity": request.valuation_source_identity,
                "simulation_source_identity": request.simulation_source_identity,
            },
            "status": self.status,
            "actual_evidence": [item.to_dict() for item in request.actual_evidence],
            "probability_results": [
                item.to_dict() for item in self.probability_results
            ],
            "numeric_results": [item.to_dict() for item in self.numeric_results],
            "numeric_interval_coverage": (
                None
                if self.numeric_interval_coverage is None
                else _text(self.numeric_interval_coverage)
            ),
            "driver_error_decomposition": list(self.driver_error_decomposition),
            "calibration_version": self.calibration_version,
            "interpretation": self.interpretation,
            "diagnostics": list(self.diagnostics),
        }


class ForecastReviewEngine:
    INTERPRETATION = (
        "ForecastReview measures frozen forecast errors against later evidence; "
        "单次复核不构成模型有效性证明，校准版本也不改写历史预测或模拟。"
    )

    @staticmethod
    def calibrated_assumption_identity(change: CalibrationChange) -> str:
        identity = {
            "assumption_id": change.assumption_id,
            "previous_version_identity": change.previous_version_identity,
            "previous_value": _text(change.previous_value),
            "new_value": _text(change.new_value),
            "unit": change.unit,
            "rationale": change.rationale,
            "evidence_refs": list(change.evidence_refs),
        }
        return "calibrated-assumption:" + hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def calibrated_model_identity(
        cls,
        previous_model_identity: str,
        changes: tuple[CalibrationChange, ...],
    ) -> str:
        identity = {
            "previous_model_identity": previous_model_identity,
            "assumption_versions": [
                cls.calibrated_assumption_identity(item)
                for item in changes
            ],
        }
        return "calibrated-model:" + hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def run(self, request: ForecastReviewRequest) -> ForecastReviewResult:
        reviewed_at = self._validate_request(request)
        del reviewed_at
        evidence = {item.evidence_id: item for item in request.actual_evidence}
        probability_results = tuple(
            self._score_probability(target, evidence[target.outcome_evidence_id])
            for target in request.probability_targets
        )
        numeric_results = tuple(
            self._score_numeric(target, evidence[target.actual_evidence_id])
            for target in request.numeric_targets
        )
        comparable_numeric = tuple(
            item
            for item in numeric_results
            if item.comparability_status == ComparabilityStatus.COMPARABLE.value
        )
        with localcontext() as context:
            context.prec = 28
            coverage = (
                Decimal(
                    sum(item.interval_covered is True for item in comparable_numeric)
                )
                / Decimal(len(comparable_numeric))
                if comparable_numeric
                else None
            )
        by_cohort_driver: dict[
            tuple[str, str, str, Decimal, str],
            Decimal,
        ] = {}
        cohort_totals: dict[tuple[str, str, str, Decimal], Decimal] = {}
        target_by_id = {
            item.target_id: item for item in request.numeric_targets
        }
        for item in comparable_numeric:
            assert item.absolute_error is not None
            target = target_by_id[item.target_id]
            cohort = (
                target.unit,
                target.currency,
                target.period,
                target.scale,
            )
            key = (*cohort, item.driver_id)
            by_cohort_driver[key] = (
                by_cohort_driver.get(key, Decimal("0")) + item.absolute_error
            )
            cohort_totals[cohort] = (
                cohort_totals.get(cohort, Decimal("0")) + item.absolute_error
            )
        with localcontext() as context:
            context.prec = 28
            decomposition = tuple(
                {
                    "driver_id": driver_id,
                    "unit": unit,
                    "currency": currency,
                    "period": period,
                    "scale": _text(scale),
                    "absolute_error": _text(error),
                    "share": _text(
                        error / cohort_totals[(unit, currency, period, scale)]
                        if cohort_totals[(unit, currency, period, scale)]
                        else Decimal("0")
                    ),
                }
                for (
                    unit,
                    currency,
                    period,
                    scale,
                    driver_id,
                ), error in by_cohort_driver.items()
            )
        calibration = (
            {
                "previous_model_identity": request.previous_model_identity,
                "new_model_identity": request.new_model_identity,
                "assumption_versions": [
                    item.to_dict() for item in request.calibration_changes
                ],
            }
            if request.calibration_changes
            else None
        )
        diagnostics = tuple(
            f"{item.target_id}:{item.comparability_status}"
            for item in (*probability_results, *numeric_results)
            if item.comparability_status != ComparabilityStatus.COMPARABLE.value
        )
        return ForecastReviewResult(
            request=request,
            status="ready" if not diagnostics else "partial",
            probability_results=probability_results,
            numeric_results=numeric_results,
            numeric_interval_coverage=coverage,
            driver_error_decomposition=decomposition,
            calibration_version=calibration,
            interpretation=self.INTERPRETATION,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _validate_request(request: ForecastReviewRequest) -> datetime:
        reviewed_at = _timestamp(request.reviewed_at, "reviewed_at")
        required = (
            request.review_id,
            request.security_id,
            request.reviewer_identity,
            request.policy_identity,
            request.review_data_snapshot_id,
            request.forecast_artifact_record_id,
            request.valuation_artifact_record_id,
            request.simulation_artifact_record_id,
            request.forecast_source_identity,
            request.valuation_source_identity,
            request.simulation_source_identity,
        )
        if not all(required) or not request.actual_evidence:
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_IDENTITY_INVALID",
                "Review, reviewer, policy, parent artifacts, and actual evidence are required.",
            )
        evidence_ids = [item.evidence_id for item in request.actual_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_EVIDENCE_DUPLICATE",
                "Actual evidence identities must be unique.",
            )
        for item in request.actual_evidence:
            item.validate(reviewed_at)
        evidence = {item.evidence_id: item for item in request.actual_evidence}
        target_ids = [
            item.target_id
            for item in (*request.probability_targets, *request.numeric_targets)
        ]
        if not target_ids or len(target_ids) != len(set(target_ids)):
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_TARGET_INVALID",
                "Review targets must be present and uniquely identified.",
            )
        for target in request.probability_targets:
            _decimal(target.probability, "ProbabilityForecastTarget.probability")
            if (
                not target.event_id
                or target.outcome_evidence_id not in evidence
                or evidence[target.outcome_evidence_id].metric_id
                != target.event_id
                or not Decimal("0") <= target.probability <= Decimal("1")
            ):
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_PROBABILITY_TARGET_INVALID",
                    "Probability targets require a [0,1] probability and linked evidence.",
                )
        for target in request.numeric_targets:
            for field_name in (
                "forecast_low",
                "forecast_base",
                "forecast_high",
                "scale",
            ):
                _decimal(getattr(target, field_name), f"NumericForecastTarget.{field_name}")
            actual = evidence.get(target.actual_evidence_id)
            if (
                not all(
                    (
                        target.driver_id,
                        target.metric_id,
                        target.unit,
                        target.period,
                    )
                )
                or actual is None
                or target.scale <= 0
                or not target.forecast_low
                <= target.forecast_base
                <= target.forecast_high
                or actual.metric_id != target.metric_id
                or (
                    actual.comparability_status is ComparabilityStatus.COMPARABLE
                    and (
                        actual.unit,
                        actual.scale,
                        actual.currency,
                        actual.period,
                    )
                    != (
                        target.unit,
                        target.scale,
                        target.currency,
                        target.period,
                    )
                )
            ):
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_NUMERIC_TARGET_INVALID",
                    "Numeric targets require ordered bounds and dimension-matched actual evidence.",
                )
        changes = request.calibration_changes
        if changes:
            assumption_ids = [item.assumption_id for item in changes]
            if len(assumption_ids) != len(set(assumption_ids)):
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_ASSUMPTION_DUPLICATE",
                    "A calibration version can change each assumption once.",
                )
            for change in changes:
                _decimal(change.previous_value, "CalibrationChange.previous_value")
                _decimal(change.new_value, "CalibrationChange.new_value")
                if (
                    not all(
                        (
                            change.assumption_id,
                            change.previous_version_identity,
                            change.new_version_identity,
                            change.unit,
                            change.rationale,
                        )
                    )
                    or change.previous_version_identity
                    == change.new_version_identity
                    or change.new_version_identity
                    != ForecastReviewEngine.calibrated_assumption_identity(
                        change
                    )
                ):
                    raise ForecastReviewInvariantError(
                        "FORECAST_REVIEW_ASSUMPTION_VERSION_NOT_ADVANCED",
                        "Each calibration change must create a distinct assumption version.",
                    )
                if not change.evidence_refs or not set(
                    change.evidence_refs
                ).issubset(evidence):
                    raise ForecastReviewInvariantError(
                        "FORECAST_REVIEW_CALIBRATION_EVIDENCE_INVALID",
                        "Calibration changes require actual-evidence lineage.",
                    )
            expected_model_identity = (
                ForecastReviewEngine.calibrated_model_identity(
                    request.previous_model_identity,
                    changes,
                )
            )
            if (
                not request.previous_model_identity
                or not request.new_model_identity
                or request.previous_model_identity == request.new_model_identity
                or request.new_model_identity != expected_model_identity
            ):
                raise ForecastReviewInvariantError(
                    "FORECAST_REVIEW_MODEL_VERSION_NOT_ADVANCED",
                    "A calibration change must create a content-bound model version.",
                )
        elif request.previous_model_identity or request.new_model_identity:
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_EMPTY_CALIBRATION_VERSION",
                "Model version identities are allowed only with calibration changes.",
            )
        return reviewed_at

    @staticmethod
    def _score_probability(
        target: ProbabilityForecastTarget,
        actual: ActualResultEvidence,
    ) -> ProbabilityReviewResult:
        comparable = actual.comparability_status is ComparabilityStatus.COMPARABLE
        if comparable and actual.value not in {Decimal("0"), Decimal("1")}:
            raise ForecastReviewInvariantError(
                "FORECAST_REVIEW_BINARY_OUTCOME_INVALID",
                "Comparable probability outcomes must be encoded as zero or one.",
            )
        score = (
            (target.probability - actual.value) ** 2
            if comparable and actual.value is not None
            else None
        )
        return ProbabilityReviewResult(
            target_id=target.target_id,
            event_id=target.event_id,
            forecast_probability=target.probability,
            observed_outcome=actual.value,
            evidence_id=actual.evidence_id,
            comparability_status=actual.comparability_status.value,
            comparability_explanation=actual.comparability_explanation,
            brier_score=score,
        )

    @staticmethod
    def _score_numeric(
        target: NumericForecastTarget,
        actual: ActualResultEvidence,
    ) -> NumericReviewResult:
        if actual.comparability_status is not ComparabilityStatus.COMPARABLE:
            return NumericReviewResult(
                target_id=target.target_id,
                driver_id=target.driver_id,
                metric_id=target.metric_id,
                evidence_id=actual.evidence_id,
                comparability_status=actual.comparability_status.value,
                comparability_explanation=actual.comparability_explanation,
                absolute_error=None,
                relative_error=None,
                direction=None,
                interval_covered=None,
            )
        assert actual.value is not None
        with localcontext() as context:
            context.prec = 28
            base = target.forecast_base * target.scale
            observed = actual.value * actual.scale
            low = target.forecast_low * target.scale
            high = target.forecast_high * target.scale
            error = abs(observed - base)
            relative = error / abs(base) if base else None
        direction = (
            "actual_above_forecast"
            if observed > base
            else "actual_below_forecast"
            if observed < base
            else "actual_matches_forecast"
        )
        return NumericReviewResult(
            target_id=target.target_id,
            driver_id=target.driver_id,
            metric_id=target.metric_id,
            evidence_id=actual.evidence_id,
            comparability_status=actual.comparability_status.value,
            comparability_explanation=actual.comparability_explanation,
            absolute_error=error,
            relative_error=relative,
            direction=direction,
            interval_covered=low <= observed <= high,
        )
