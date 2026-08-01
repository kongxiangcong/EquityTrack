from __future__ import annotations

from decimal import Decimal

from trading_platform.domain.market import MarketBar
from trading_platform.domain.recent_trend import assess_recent_trend


def _bars(count: int) -> tuple[MarketBar, ...]:
    return tuple(
        MarketBar(
            security_id="security_002897_sz",
            session_date=f"2026-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}",
            close=Decimal(index + 1),
            amount=Decimal("1000000"),
            normalized_version_id=f"daily:{index + 1}",
        )
        for index in range(count)
    )


def test_recent_trend_is_a_typed_observed_assessment() -> None:
    result = assess_recent_trend(
        security_id="security_002897_sz",
        data_snapshot_id="data_snapshot_research",
        as_of_session="2026-03-04",
        bars=_bars(60),
    )

    assert result.status == "complete"
    assert result.classification == "up"
    assert result.close == Decimal("60")
    assert result.sma20 == Decimal("50.5")
    assert result.sma60 == Decimal("30.5")
    assert result.sma20_five_sessions_prior == Decimal("45.5")
    assert result.window_low_20 == Decimal("41")
    assert result.evidence_refs == tuple(f"daily:{index}" for index in range(1, 61))
    result.validate()


def test_recent_trend_degrades_locally_when_history_is_insufficient() -> None:
    result = assess_recent_trend(
        security_id="security_002897_sz",
        data_snapshot_id="data_snapshot_research",
        as_of_session="2026-02-02",
        bars=_bars(30),
    )

    assert result.status == "blocked"
    assert result.classification is None
    assert result.reason_codes == ("RECENT_TREND_HISTORY_INSUFFICIENT",)
    assert result.close == Decimal("30")
    result.validate()


def test_recent_trend_returns_a_typed_block_when_no_daily_bar_is_available() -> None:
    result = assess_recent_trend(
        security_id="security_002897_sz",
        data_snapshot_id="data_snapshot_research",
        as_of_session="2026-02-02",
        bars=(),
    )

    assert result.status == "blocked"
    assert result.close is None
    assert result.observation_count == 0
    assert result.reason_codes == ("RECENT_TREND_OBSERVATIONS_REQUIRED",)
    result.validate()
