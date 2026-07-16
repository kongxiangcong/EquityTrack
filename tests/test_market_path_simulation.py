from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import json

import pytest

from equity_research import (
    MarketConstraintPolicy,
    MarketPathBudget,
    MarketPathCalibration,
    MarketPathEngine,
    MarketPathInvariantError,
    MarketPathObservation,
    MarketPathRequest,
)


def observations(count: int = 50) -> tuple[MarketPathObservation, ...]:
    session = date(2026, 7, 6)
    price = Decimal("100")
    rows: list[MarketPathObservation] = []
    sessions: list[date] = []
    day = session
    while len(sessions) < count:
        if day.weekday() < 5:
            sessions.append(day)
        day -= timedelta(days=1)
    sessions.reverse()
    previous_price: Decimal | None = None
    previous_ref: str | None = None
    for index, day in enumerate(sessions):
        suspended = index in {11, 28}
        if index and not suspended:
            price *= Decimal("1.01") if index % 3 else Decimal("0.985")
        state = (
            "warmup"
            if previous_price is None
            else "flat"
            if price == previous_price
            else "risk_on"
            if price > previous_price
            else "risk_off"
        )
        current_ref = f"Evidence:bar:{day.isoformat()}"
        rows.append(
            MarketPathObservation(
                session_date=day.isoformat(),
                unadjusted_close=price,
                adjustment_factor=Decimal("1"),
                market_state=state,
                close_available_at=f"{day.isoformat()}T15:00:00+08:00",
                factor_available_at=f"{day.isoformat()}T15:00:00+08:00",
                state_available_at=f"{day.isoformat()}T15:00:00+08:00",
                retrieved_at="2026-07-07T08:00:00Z",
                suspended=suspended,
                limit_state="none",
                corporate_action_identity=None,
                evidence_refs=tuple(
                    ref
                    for ref in (current_ref, previous_ref)
                    if ref is not None
                ),
            )
        )
        previous_price = price
        previous_ref = current_ref
    return tuple(rows)


def request(
    *,
    rows: tuple[MarketPathObservation, ...] | None = None,
    state: str | None = None,
) -> MarketPathRequest:
    rows = rows or observations()
    starting_price = Decimal("105")
    current_state = state or (
        "risk_on"
        if starting_price > rows[-1].adjusted_close
        else "risk_off"
        if starting_price < rows[-1].adjusted_close
        else "flat"
    )
    starting_member_id = "Evidence:starting-close"
    next_session_calendar_member_id = "Calendar:2026-07-07"
    return MarketPathRequest(
        simulation_id="market_path_fixture",
        security_id="002897.SZ",
        as_of="2026-07-07",
        as_of_at="2026-07-07T16:00:00+08:00",
        valuation_simulation_source_identity="valuation-simulation:fixture",
        model_identity="state-block-bootstrap@1",
        policy_identity="market-path-policy@1",
        price_unit="CNY/share",
        currency="CNY",
        starting_price=starting_price,
        starting_price_session="2026-07-07",
        starting_price_member_id=starting_member_id,
        starting_price_available_at="2026-07-07T15:00:00+08:00",
        starting_price_evidence_refs=(starting_member_id,),
        current_market_state=current_state,
        current_state_available_at="2026-07-07T15:00:00+08:00",
        current_state_evidence_refs=(
            starting_member_id,
            rows[-1].evidence_refs[0],
            "one_session_return_sign@1",
        ),
        calibration=MarketPathCalibration(
            snapshot_id="market-calibration-fixture@1",
            platform_snapshot_id="platform-market-snapshot-fixture@1",
            market="SZSE",
            market_timezone="Asia/Shanghai",
            series_identity="pit-adjusted-series@1",
            series_evidence_refs=("Evidence:adjusted-close-series",),
            adjustment_mode="backward_adjusted_return",
            trading_calendar_identity="sse-trade-cal-fixture@1",
            calendar_evidence_refs=tuple(
                f"Calendar:{item.session_date}" for item in rows
            )
            + (next_session_calendar_member_id,),
            calendar_member_ids=tuple(
                f"Calendar:{item.session_date}" for item in rows
            ),
            trading_sessions=tuple(item.session_date for item in rows),
            next_session_date="2026-07-07",
            next_session_calendar_member_id=(
                next_session_calendar_member_id
            ),
            series_member_ids=tuple(
                item.evidence_refs[0] for item in rows
            ),
            adjustment_member_ids=(),
            corporate_action_member_ids=(),
            state_model_identity="one_session_return_sign@1",
            observations=rows,
            window_start=rows[0].session_date,
            window_end=rows[-1].session_date,
            as_of="2026-07-07",
            basis="State-conditioned contiguous block bootstrap fixture.",
        ),
        constraints=MarketConstraintPolicy(
            policy_identity="cn-a-share-path-constraints@1",
            one_way_transaction_cost_bps=Decimal("8"),
            minimum_execution_lag_sessions=1,
            price_limit_fraction=Decimal("0.10"),
            preserve_observed_suspensions=True,
            preserve_observed_limit_states=True,
        ),
        budget=MarketPathBudget(
            rng_algorithm="splitmix64_state_block_bootstrap@1",
            seed=20260707,
            path_count=5000,
            horizon_sessions=20,
            block_length=5,
            minimum_candidate_blocks=10,
        ),
        price_thresholds=(Decimal("95"), Decimal("115")),
        tail_return_threshold=Decimal("-0.10"),
    )


def test_state_block_bootstrap_is_reproducible_and_publishes_market_risk_metrics() -> None:
    engine = MarketPathEngine()
    first = engine.run(request())
    second = engine.run(request())

    assert first.status == "ready"
    assert first.terminal_price_quantiles["p50"]
    assert first.horizon_return_quantiles["p5"]
    assert Decimal(first.maximum_drawdown_quantiles["p5"]) <= Decimal("0")
    assert {item["threshold"] for item in first.threshold_trigger_probabilities} == {
        "95",
        "115",
    }
    assert first.tail_results["return_threshold"] == "-0.1"
    assert "not intrinsic value" in first.interpretation
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(),
        sort_keys=True,
    )


def test_pit_dates_are_compared_in_the_declared_market_timezone() -> None:
    rows = observations()
    leaked = replace(
        rows[0],
        close_available_at=f"{rows[0].session_date}T23:30:00Z",
    )
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(request(rows=(leaked, *rows[1:])))
    assert error.value.code == "MARKET_PATH_PIT_INVALID"


def test_retrieval_cutoff_does_not_reject_a_valid_western_market_local_date() -> None:
    base = request()
    rows = tuple(
        replace(
            item,
            retrieved_at="2026-07-07T20:00:00-04:00",
        )
        for item in base.calibration.observations
    )
    result = MarketPathEngine().run(
        replace(
            base,
            as_of_at="2026-07-07T23:00:00-04:00",
            starting_price_available_at="2026-07-07T16:00:00-04:00",
            current_state_available_at="2026-07-07T16:00:00-04:00",
            calibration=replace(
                base.calibration,
                market="NYSE",
                market_timezone="America/New_York",
                observations=rows,
            ),
        )
    )
    assert result.status == "ready"


def test_threshold_probability_includes_the_execution_session() -> None:
    base = request()
    prices = (
        Decimal("100"),
        Decimal("109"),
        Decimal("100"),
        Decimal("109"),
    )
    states = ("warmup", "risk_on", "risk_off", "risk_on")
    rows = tuple(
        replace(
            base.calibration.observations[index],
            unadjusted_close=price,
            market_state=states[index],
            suspended=False,
        )
        for index, price in enumerate(prices)
    )
    calendar_ids = base.calibration.calendar_member_ids[: len(rows)]
    result = MarketPathEngine().run(
        replace(
            base,
            starting_price=Decimal("120"),
            current_market_state="risk_on",
            current_state_evidence_refs=(
                base.starting_price_member_id,
                rows[-1].evidence_refs[0],
                base.calibration.state_model_identity,
            ),
            price_thresholds=(Decimal("115"),),
            calibration=replace(
                base.calibration,
                observations=rows,
                trading_sessions=tuple(item.session_date for item in rows),
                calendar_member_ids=calendar_ids,
                calendar_evidence_refs=(
                    *calendar_ids,
                    base.calibration.next_session_calendar_member_id,
                ),
                series_member_ids=tuple(
                    item.evidence_refs[0] for item in rows
                ),
                window_end=rows[-1].session_date,
            ),
            budget=replace(
                base.budget,
                horizon_sessions=1,
                block_length=2,
                minimum_candidate_blocks=1,
            ),
        )
    )
    assert result.threshold_trigger_probabilities == (
        {"threshold": "115", "probability": "1"},
    )


@pytest.mark.parametrize(
    "mutator,code",
    [
        (
            lambda value: replace(
                value,
                calibration=replace(
                    value.calibration,
                    observations=(
                        *value.calibration.observations[:-1],
                        replace(
                            value.calibration.observations[-1],
                            session_date="2026-08-01",
                        ),
                    ),
                ),
            ),
            "MARKET_PATH_WINDOW_INVALID",
        ),
        (
            lambda value: replace(
                value,
                calibration=replace(
                    value.calibration,
                    observations=(
                        replace(
                            value.calibration.observations[0],
                            state_available_at="2026-08-01T00:00:00Z",
                        ),
                        *value.calibration.observations[1:],
                    ),
                ),
            ),
            "MARKET_PATH_PIT_INVALID",
        ),
        (
            lambda value: replace(
                value,
                constraints=replace(
                    value.constraints,
                    minimum_execution_lag_sessions=0,
                ),
            ),
            "MARKET_PATH_POLICY_INVALID",
        ),
        (
            lambda value: replace(
                value,
                calibration=replace(
                    value.calibration,
                    observations=(
                        replace(
                            value.calibration.observations[0],
                            adjustment_factor=Decimal("1.2"),
                            corporate_action_identity=None,
                        ),
                        *value.calibration.observations[1:],
                    ),
                ),
            ),
            "MARKET_PATH_CORPORATE_ACTION_INVALID",
        ),
    ],
)
def test_forward_same_close_state_and_corporate_action_leakage_fail_closed(
    mutator,
    code: str,
) -> None:
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(mutator(request()))
    assert error.value.code == code


def test_insufficient_state_conditioned_blocks_withhold_path_distribution() -> None:
    base = request()
    result = MarketPathEngine().run(
        replace(
            base,
            starting_price=base.calibration.observations[-1].adjusted_close,
            current_market_state="flat",
        )
    )
    assert result.status == "partial"
    assert result.terminal_price_quantiles is None
    assert result.threshold_trigger_probabilities == ()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: replace(
            value,
            calibration=replace(
                value.calibration,
                observations=(
                    value.calibration.observations[0],
                    replace(
                        value.calibration.observations[1],
                        market_state="fabricated_regime",
                    ),
                    *value.calibration.observations[2:],
                ),
            ),
        ),
        lambda value: replace(
            value,
            current_market_state="fabricated_regime",
            current_state_evidence_refs=("fabricated-state",),
        ),
        lambda value: replace(
            value,
            calibration=replace(
                value.calibration,
                observations=(
                    value.calibration.observations[0],
                    replace(
                        value.calibration.observations[1],
                        state_available_at=(
                            f"{value.calibration.observations[1].session_date}"
                            "T09:00:00+08:00"
                        ),
                    ),
                    *value.calibration.observations[2:],
                ),
            ),
        ),
        lambda value: replace(
            value,
            current_state_available_at="2026-07-07T09:00:00+08:00",
        ),
    ],
)
def test_market_state_must_be_reproducible_from_frozen_prices(mutator) -> None:
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(mutator(request()))
    assert error.value.code == "MARKET_PATH_STATE_LINEAGE_INVALID"


def test_suspension_and_limit_semantics_cannot_be_silently_discarded() -> None:
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(
            replace(
                request(),
                constraints=replace(
                    request().constraints,
                    preserve_observed_suspensions=False,
                ),
            )
        )
    assert error.value.code == "MARKET_PATH_SUSPENSION_POLICY_INVALID"


def test_calendar_corporate_action_unit_and_microstructure_contradictions_fail() -> None:
    base = request()
    weekly = tuple(
        replace(
            item,
            session_date=(date(2025, 1, 1) + timedelta(days=index * 7)).isoformat(),
        )
        for index, item in enumerate(base.calibration.observations)
    )
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(
            replace(
                base,
                calibration=replace(
                    base.calibration,
                    observations=weekly,
                ),
            )
        )
    assert error.value.code == "MARKET_PATH_WINDOW_INVALID"

    suspended = base.calibration.observations[11]
    contradictory_suspension = replace(
        suspended,
        unadjusted_close=suspended.unadjusted_close + Decimal("1"),
    )
    rows = (
        *base.calibration.observations[:11],
        contradictory_suspension,
        *base.calibration.observations[12:],
    )
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(
            replace(
                base,
                calibration=replace(base.calibration, observations=rows),
            )
        )
    assert error.value.code == "MARKET_PATH_SUSPENSION_CONTRADICTION"

    limit_row = replace(
        base.calibration.observations[5],
        limit_state="up",
    )
    rows = (
        *base.calibration.observations[:5],
        limit_row,
        *base.calibration.observations[6:],
    )
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(
            replace(
                base,
                calibration=replace(base.calibration, observations=rows),
            )
        )
    assert error.value.code == "MARKET_PATH_LIMIT_STATE_CONTRADICTION"

    factor_row = replace(
        base.calibration.observations[8],
        adjustment_factor=Decimal("1.1"),
        corporate_action_identity=None,
    )
    rows = (
        *base.calibration.observations[:8],
        factor_row,
        *base.calibration.observations[9:],
    )
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(
            replace(
                base,
                calibration=replace(base.calibration, observations=rows),
            )
        )
    assert error.value.code == "MARKET_PATH_CORPORATE_ACTION_INVALID"

    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(
            replace(base, price_unit="USD/share", currency="CNY")
        )
    assert error.value.code == "MARKET_PATH_IDENTITY_INVALID"


def test_next_local_day_market_inputs_are_not_admitted_by_utc_date() -> None:
    with pytest.raises(MarketPathInvariantError) as error:
        MarketPathEngine().run(
            replace(
                request(),
                starting_price_available_at="2026-07-08T00:30:00+08:00",
            )
        )
    assert error.value.code == "MARKET_PATH_POLICY_INVALID"
