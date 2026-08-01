from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_platform.domain.market import MarketBar
from trading_platform.identity import canonical_hash


class RecentTrendError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RecentTrendAssessment:
    assessment_id: str
    security_id: str
    data_snapshot_id: str
    as_of_session: str
    status: str
    classification: str | None
    close: Decimal | None
    sma20: Decimal | None
    sma60: Decimal | None
    sma20_five_sessions_prior: Decimal | None
    window_low_20: Decimal | None
    observation_count: int
    price_basis: str
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    content_hash: str
    schema_version: str = "RecentTrendAssessment@1"

    @property
    def canonical_content(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "security_id": self.security_id,
            "data_snapshot_id": self.data_snapshot_id,
            "as_of_session": self.as_of_session,
            "status": self.status,
            "classification": self.classification,
            "close": self.close,
            "sma20": self.sma20,
            "sma60": self.sma60,
            "sma20_five_sessions_prior": self.sma20_five_sessions_prior,
            "window_low_20": self.window_low_20,
            "observation_count": self.observation_count,
            "price_basis": self.price_basis,
            "evidence_refs": self.evidence_refs,
            "reason_codes": self.reason_codes,
        }

    def validate(self) -> None:
        expected = canonical_hash(self.canonical_content)
        if (
            self.schema_version != "RecentTrendAssessment@1"
            or not self.security_id
            or not self.data_snapshot_id
            or not self.as_of_session
            or self.status not in {"complete", "blocked"}
            or self.price_basis != "unadjusted_close"
            or self.observation_count != len(self.evidence_refs)
            or self.content_hash != expected
            or self.assessment_id != f"recent_trend_{expected[:24]}"
        ):
            raise RecentTrendError("RECENT_TREND_INTEGRITY_INVALID")
        metrics = (
            self.close,
            self.sma20,
            self.sma60,
            self.sma20_five_sessions_prior,
            self.window_low_20,
        )
        if self.status == "complete":
            if (
                self.classification not in {"up", "down", "mixed"}
                or any(value is None for value in metrics)
                or self.reason_codes
                or self.observation_count < 60
            ):
                raise RecentTrendError("RECENT_TREND_COMPLETE_INVALID")
        elif self.classification is not None or any(
            value is not None for value in metrics[1:]
        ):
            raise RecentTrendError("RECENT_TREND_BLOCKED_INVALID")
        elif self.observation_count == 0:
            if (
                self.close is not None
                or self.evidence_refs
                or self.reason_codes
                != ("RECENT_TREND_OBSERVATIONS_REQUIRED",)
            ):
                raise RecentTrendError("RECENT_TREND_BLOCKED_INVALID")
        elif (
            self.close is None
            or self.reason_codes
            != ("RECENT_TREND_HISTORY_INSUFFICIENT",)
            or self.observation_count >= 60
        ):
            raise RecentTrendError("RECENT_TREND_BLOCKED_INVALID")


def assess_recent_trend(
    *,
    security_id: str,
    data_snapshot_id: str,
    as_of_session: str,
    bars: tuple[MarketBar, ...],
) -> RecentTrendAssessment:
    """Derive an observed trend from frozen daily bars without prediction."""

    eligible = tuple(
        sorted(
            (
                bar
                for bar in bars
                if bar.security_id == security_id
                and bar.session_date <= as_of_session
            ),
            key=lambda item: item.session_date,
        )
    )
    if len({bar.session_date for bar in eligible}) != len(eligible):
        raise RecentTrendError("RECENT_TREND_SESSION_DUPLICATE")
    if any(
        not bar.normalized_version_id
        or not bar.close.is_finite()
        or bar.close <= 0
        for bar in eligible
    ):
        raise RecentTrendError("RECENT_TREND_OBSERVATION_INVALID")

    close = eligible[-1].close if eligible else None
    common = {
        "security_id": security_id,
        "data_snapshot_id": data_snapshot_id,
        "as_of_session": as_of_session,
        "close": close,
        "observation_count": len(eligible),
        "price_basis": "unadjusted_close",
        "evidence_refs": tuple(
            bar.normalized_version_id for bar in eligible
        ),
    }
    if not eligible:
        prototype = RecentTrendAssessment(
            assessment_id="",
            status="blocked",
            classification=None,
            sma20=None,
            sma60=None,
            sma20_five_sessions_prior=None,
            window_low_20=None,
            reason_codes=("RECENT_TREND_OBSERVATIONS_REQUIRED",),
            content_hash="",
            **common,
        )
    elif len(eligible) < 60:
        prototype = RecentTrendAssessment(
            assessment_id="",
            status="blocked",
            classification=None,
            sma20=None,
            sma60=None,
            sma20_five_sessions_prior=None,
            window_low_20=None,
            reason_codes=("RECENT_TREND_HISTORY_INSUFFICIENT",),
            content_hash="",
            **common,
        )
    else:
        closes = tuple(bar.close for bar in eligible)
        sma20 = _mean(closes[-20:])
        sma60 = _mean(closes[-60:])
        prior_sma20 = _mean(closes[-25:-5])
        classification = (
            "up"
            if close > sma20 > sma60 and sma20 > prior_sma20
            else "down"
            if close < sma20 < sma60 and sma20 < prior_sma20
            else "mixed"
        )
        prototype = RecentTrendAssessment(
            assessment_id="",
            status="complete",
            classification=classification,
            sma20=sma20,
            sma60=sma60,
            sma20_five_sessions_prior=prior_sma20,
            window_low_20=min(closes[-20:]),
            reason_codes=(),
            content_hash="",
            **common,
        )
    content_hash = canonical_hash(prototype.canonical_content)
    result = RecentTrendAssessment(
        **{
            **prototype.__dict__,
            "assessment_id": f"recent_trend_{content_hash[:24]}",
            "content_hash": content_hash,
        }
    )
    result.validate()
    return result


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


__all__ = [
    "RecentTrendAssessment",
    "RecentTrendError",
    "assess_recent_trend",
]
