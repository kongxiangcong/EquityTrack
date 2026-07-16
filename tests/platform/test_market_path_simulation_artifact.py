from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_research import MarketPathEngine
from tests.platform.test_outlook_artifacts import _request
from tests.platform.test_research_workflow import CountingEngine, _root
from tests.platform.test_valuation_simulation_artifact import _simulation_drafts
from tests.test_market_path_simulation import request as market_path_request
from trading_platform.domain.workflow import ImmutableArtifactDraft
from trading_platform.research_view import ResearchDecisionViewBuilder
from trading_platform.workflows.research import WorkflowError


def _market_path_drafts(
    base_market_request=None,
) -> tuple[ImmutableArtifactDraft, ...]:
    deterministic = _simulation_drafts()
    simulation = deterministic[-1]
    result = MarketPathEngine().run(
        replace(
            base_market_request or market_path_request(),
            security_id=simulation.subject_id,
            as_of=simulation.as_of,
            starting_price_session=simulation.as_of,
            valuation_simulation_source_identity=simulation.source_identity,
        )
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        result.calibration,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    market_path = ImmutableArtifactDraft.from_market_path_simulation(
        result,
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    return (*deterministic, market_data, market_path)


def _install_market_snapshot(root, base_request):
    snapshot_id = "snapshot_market_path_fixture"
    calendar_ids = tuple(
        f"market_path_cal_{index:03d}"
        for index, _ in enumerate(base_request.calibration.observations)
    )
    series_ids = tuple(
        f"market_path_daily_{index:03d}"
        for index, _ in enumerate(base_request.calibration.observations)
    )
    next_calendar_id = "market_path_cal_starting_session"
    starting_price_member_id = "market_path_starting_daily"
    rows = tuple(
        replace(
            observation,
            evidence_refs=tuple(
                ref
                for ref in (
                    series_ids[index],
                    series_ids[index - 1] if index else None,
                    *observation.evidence_refs,
                )
                if ref is not None
            ),
        )
        for index, observation in enumerate(
            base_request.calibration.observations
        )
    )
    bound = replace(
        base_request,
        starting_price_member_id=starting_price_member_id,
        starting_price_evidence_refs=(starting_price_member_id,),
        current_state_evidence_refs=(
            starting_price_member_id,
            series_ids[-1],
            base_request.calibration.state_model_identity,
        ),
        calibration=replace(
            base_request.calibration,
            platform_snapshot_id=snapshot_id,
            observations=rows,
            calendar_member_ids=calendar_ids,
            calendar_evidence_refs=(*calendar_ids, next_calendar_id),
            next_session_calendar_member_id=next_calendar_id,
            series_member_ids=series_ids,
            series_evidence_refs=series_ids,
        ),
    )
    connection = root._store.connection
    with connection:
        connection.execute(
            "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "attempt_market_path_calendar",
                "market-path-calendar",
                "fixture",
                "fixture@1",
                "trade_cal",
                "fixture-authoritative-calendar",
                "fixture",
                "urn:test:market-path-calendar",
                "{}",
                "{}",
                "timestamp",
                "test-terms",
                "complete",
                "created",
                None,
                base_request.as_of_at,
                None,
                None,
                None,
                "not_applicable",
            ),
        )
        connection.execute(
            "INSERT INTO provider_attempt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "attempt_market_path_daily",
                "market-path-daily",
                "fixture",
                "fixture@1",
                "daily",
                "fixture-authoritative-daily",
                "fixture",
                "urn:test:market-path-daily",
                "{}",
                "{}",
                "timestamp",
                "test-terms",
                "complete",
                "created",
                None,
                base_request.as_of_at,
                None,
                None,
                None,
                "not_applicable",
            ),
        )
        connection.execute(
            "INSERT INTO data_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id,
                "security_yihua",
                "workflow",
                base_request.as_of,
                rows[-1].session_date,
                base_request.as_of_at,
                bound.calibration.market_timezone,
                bound.calibration.trading_calendar_identity,
                "query@market-path-1",
                "source@market-path-1",
                "freshness@market-path-1",
                "market-path-members",
                "valid",
                "pass",
                len(calendar_ids) + len(series_ids) + 2,
                len(calendar_ids) + len(series_ids) + 2,
                0,
                0,
                0,
                "frozen-market-path-calibration",
                base_request.as_of_at,
            ),
        )
        member_order = 0
        for index, observation in enumerate(rows):
            calendar_id = calendar_ids[index]
            calendar_record = f"record_{calendar_id}"
            connection.execute(
                "INSERT INTO normalized_record VALUES(?,?,?)",
                (
                    calendar_record,
                    "trade_cal",
                    f"SZSE:{observation.session_date}:"
                    f"{bound.calibration.trading_calendar_identity}",
                ),
            )
            connection.execute(
                "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    calendar_id,
                    calendar_record,
                    1,
                    f"hash-{calendar_id}",
                    "attempt_market_path_calendar",
                    observation.session_date,
                    observation.session_date,
                    "date",
                    observation.close_available_at,
                    "publisher_timestamp",
                    base_request.as_of_at,
                    "pass",
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO market_session_version VALUES(?,?,?,?,?,?,?)",
                (
                    f"session_{calendar_id}",
                    bound.calibration.market,
                    observation.session_date,
                    1,
                    bound.calibration.trading_calendar_identity,
                    observation.close_available_at,
                    "attempt_market_path_calendar",
                ),
            )
            connection.execute(
                "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
                (snapshot_id, calendar_id, "trade_cal", member_order),
            )
            member_order += 1

            series_id = series_ids[index]
            series_record = f"record_{series_id}"
            connection.execute(
                "INSERT INTO normalized_record VALUES(?,?,?)",
                (
                    series_record,
                    "daily",
                    f"security_yihua:{observation.session_date}:none",
                ),
            )
            connection.execute(
                "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    series_id,
                    series_record,
                    1,
                    f"hash-{series_id}",
                    "attempt_market_path_daily",
                    observation.session_date,
                    observation.session_date,
                    "date",
                    observation.close_available_at,
                    "publisher_timestamp",
                    base_request.as_of_at,
                    "pass",
                    None,
                ),
            )
            close = observation.to_dict()["unadjusted_close"]
            connection.execute(
                "INSERT INTO ohlcv_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    series_id,
                    "security_yihua",
                    observation.session_date,
                    bound.calibration.market_timezone,
                    "none",
                    close,
                    close,
                    close,
                    close,
                    "100",
                    "hand",
                    "1000",
                    "CNY",
                    "CNY",
                ),
            )
            connection.execute(
                "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
                (snapshot_id, series_id, "daily", member_order),
            )
            member_order += 1
        next_calendar_record = f"record_{next_calendar_id}"
        connection.execute(
            "INSERT INTO normalized_record VALUES(?,?,?)",
            (
                next_calendar_record,
                "trade_cal",
                f"SZSE:{base_request.starting_price_session}:"
                f"{bound.calibration.trading_calendar_identity}",
            ),
        )
        connection.execute(
            "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                next_calendar_id,
                next_calendar_record,
                1,
                f"hash-{next_calendar_id}",
                "attempt_market_path_calendar",
                base_request.starting_price_session,
                base_request.starting_price_session,
                "date",
                base_request.starting_price_available_at,
                "publisher_timestamp",
                base_request.as_of_at,
                "pass",
                None,
            ),
        )
        connection.execute(
            "INSERT INTO market_session_version VALUES(?,?,?,?,?,?,?)",
            (
                f"session_{next_calendar_id}",
                bound.calibration.market,
                base_request.starting_price_session,
                1,
                bound.calibration.trading_calendar_identity,
                base_request.starting_price_available_at,
                "attempt_market_path_calendar",
            ),
        )
        connection.execute(
            "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
            (snapshot_id, next_calendar_id, "trade_cal", member_order),
        )
        member_order += 1
        starting_record = f"record_{starting_price_member_id}"
        connection.execute(
            "INSERT INTO normalized_record VALUES(?,?,?)",
            (
                starting_record,
                "daily",
                f"security_yihua:{base_request.starting_price_session}:none",
            ),
        )
        connection.execute(
            "INSERT INTO normalized_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                starting_price_member_id,
                starting_record,
                1,
                f"hash-{starting_price_member_id}",
                "attempt_market_path_daily",
                base_request.starting_price_session,
                base_request.starting_price_session,
                "date",
                base_request.starting_price_available_at,
                "publisher_timestamp",
                base_request.as_of_at,
                "pass",
                None,
            ),
        )
        starting_close = str(base_request.starting_price)
        connection.execute(
            "INSERT INTO ohlcv_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                starting_price_member_id,
                "security_yihua",
                base_request.starting_price_session,
                bound.calibration.market_timezone,
                "none",
                starting_close,
                starting_close,
                starting_close,
                starting_close,
                "100",
                "hand",
                "1000",
                "CNY",
                "CNY",
            ),
        )
        connection.execute(
            "INSERT INTO data_snapshot_member VALUES(?,?,?,?)",
            (
                snapshot_id,
                starting_price_member_id,
                "daily",
                member_order,
            ),
        )
    return bound, (
        *calendar_ids,
        *series_ids,
        next_calendar_id,
        starting_price_member_id,
    )


def test_market_path_is_an_independent_simulation_child_and_workspace_view(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    result = root.facade.run_research_workflow(
        replace(
            _request(
                "market-path:first",
                _market_path_drafts(bound_request),
            ),
            workflow_snapshot_id=bound_request.calibration.platform_snapshot_id,
            candidate_member_ids=market_member_ids,
            market_only_member_ids=market_member_ids,
        )
    )
    artifacts = tuple(
        root.facade.get_research_artifact(record_id)
        for record_id in result.artifact_record_ids
    )
    assert [item.artifact_kind for item in artifacts] == [
        "DataSnapshot",
        "Forecast",
        "Valuation",
        "Simulation",
        "MarketDataSnapshot",
        "MarketPathSimulation",
    ]
    market_path = artifacts[-1]
    assert set(market_path.dependency_record_ids) == {
        artifacts[-3].artifact_record_id,
        artifacts[-2].artifact_record_id,
    }
    assert market_path.payload["interpretation"].startswith(
        "MarketPathSimulation models state-conditional traded-price paths"
    )
    assert "intrinsic value" in market_path.payload["interpretation"]
    view = root.facade.get_workspace(
        "security_yihua",
        result.research_snapshot_id,
    )["research_views"][0]
    assert view["valuation_simulation"]["quantiles"]["p50"]["unit"] == "CNY/share"
    assert view["market_price_paths"]["terminal_price_quantiles"]["p50"]["unit"] == (
        "CNY/share"
    )
    assert view["market_price_paths"]["horizon_return_quantiles"]["p50"]["unit"] == (
        "decimal"
    )
    assert view["value_market_divergence"]["status"] == (
        "not_comparable_horizon"
    )
    assert "期限不同" in view["value_market_divergence"]["explanation"]
    assert "目标价或交易动作" in view["value_market_divergence"]["explanation"]
    assert view["market_price_paths"]["terminal_price_quantiles"]["p50"][
        "period"
    ] == "T+21 trading sessions"
    root.close()


def test_market_path_source_identity_binds_thresholds_and_parent_simulation() -> None:
    drafts = _simulation_drafts()
    simulation = drafts[-1]
    base_request = replace(
        market_path_request(),
        security_id=simulation.subject_id,
        as_of=simulation.as_of,
        starting_price_session=simulation.as_of,
        valuation_simulation_source_identity=simulation.source_identity,
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        base_request.calibration,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    first = ImmutableArtifactDraft.from_market_path_simulation(
        MarketPathEngine().run(base_request),
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    second = ImmutableArtifactDraft.from_market_path_simulation(
        MarketPathEngine().run(
            replace(
                base_request,
                price_thresholds=(Decimal("90"), Decimal("120")),
            )
        ),
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    assert first.source_identity != second.source_identity


def test_formal_persistence_rejects_a_self_declared_weekly_calendar(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    deterministic = _simulation_drafts()
    simulation = deterministic[-1]
    valid_result = MarketPathEngine().run(
        replace(
            bound_request,
            security_id=simulation.subject_id,
            as_of=simulation.as_of,
            starting_price_session=simulation.as_of,
            valuation_simulation_source_identity=simulation.source_identity,
        )
    )
    first_date = date.fromisoformat(
        valid_result.calibration.observations[0].session_date
    )
    weekly_dates = tuple(
        (first_date + timedelta(days=index * 7)).isoformat()
        for index in range(len(valid_result.calibration.observations))
    )
    fabricated_calibration = replace(
        valid_result.calibration,
        trading_calendar_identity="fabricated-weekly-calendar@1",
        trading_sessions=weekly_dates,
        observations=tuple(
            replace(observation, session_date=weekly_dates[index])
            for index, observation in enumerate(
                valid_result.calibration.observations
            )
        ),
        window_start=weekly_dates[0],
        window_end=weekly_dates[-1],
    )
    fabricated_result = replace(
        valid_result,
        calibration=fabricated_calibration,
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        fabricated_calibration,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    market_path = ImmutableArtifactDraft.from_market_path_simulation(
        fabricated_result,
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    with pytest.raises(WorkflowError):
        root.facade.run_research_workflow(
            replace(
                _request(
                    "market-path:fabricated-calendar",
                    (*deterministic, market_data, market_path),
                ),
                workflow_snapshot_id=(
                    bound_request.calibration.platform_snapshot_id
                ),
                candidate_member_ids=market_member_ids,
                market_only_member_ids=market_member_ids,
            )
        )
    assert (
        root._store.connection.execute(
            "SELECT count(*) FROM research_artifact_record"
        ).fetchone()[0]
        == 0
    )
    root.close()


def test_formal_persistence_uses_the_frozen_snapshot_cutoff(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    with root._store.connection:
        root._store.connection.execute(
            "UPDATE data_snapshot SET as_of_at=? WHERE data_snapshot_id=?",
            (
                "2026-07-07T14:00:00+08:00",
                bound_request.calibration.platform_snapshot_id,
            ),
        )
        root._store.connection.execute(
            "UPDATE normalized_version SET available_at=? "
            "WHERE normalized_version_id=?",
            (
                "2026-07-07T15:00:00+08:00",
                bound_request.calibration.series_member_ids[0],
            ),
        )
    with pytest.raises(WorkflowError):
        root.facade.run_research_workflow(
            replace(
                _request(
                    "market-path:snapshot-cutoff",
                    _market_path_drafts(bound_request),
                ),
                workflow_snapshot_id=(
                    bound_request.calibration.platform_snapshot_id
                ),
                candidate_member_ids=market_member_ids,
                market_only_member_ids=market_member_ids,
            )
        )
    assert (
        root._store.connection.execute(
            "SELECT count(*) FROM research_artifact_record"
        ).fetchone()[0]
        == 0
    )
    root.close()


def test_formal_persistence_rejects_unbound_starting_price_and_state(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    deterministic = _simulation_drafts()
    simulation = deterministic[-1]
    valid_result = MarketPathEngine().run(
        replace(
            bound_request,
            security_id=simulation.subject_id,
            as_of=simulation.as_of,
            starting_price_session=simulation.as_of,
            valuation_simulation_source_identity=simulation.source_identity,
        )
    )
    fabricated = replace(
        valid_result,
        starting_price="999",
        starting_price_member_id="fabricated-start",
        starting_price_evidence_refs=("fabricated-start",),
        current_market_state="fabricated_regime",
        current_state_evidence_refs=("fabricated-state",),
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        valid_result.calibration,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    market_path = ImmutableArtifactDraft.from_market_path_simulation(
        fabricated,
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    with pytest.raises(WorkflowError):
        root.facade.run_research_workflow(
            replace(
                _request(
                    "market-path:fabricated-state",
                    (*deterministic, market_data, market_path),
                ),
                workflow_snapshot_id=(
                    bound_request.calibration.platform_snapshot_id
                ),
                candidate_member_ids=market_member_ids,
                market_only_member_ids=market_member_ids,
            )
        )
    assert (
        root._store.connection.execute(
            "SELECT count(*) FROM research_artifact_record"
        ).fetchone()[0]
        == 0
    )
    root.close()


def test_formal_persistence_rejects_a_non_adjacent_current_state(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    deterministic = _simulation_drafts()
    simulation = deterministic[-1]
    valid_result = MarketPathEngine().run(
        replace(
            bound_request,
            security_id=simulation.subject_id,
            as_of=simulation.as_of,
            starting_price_session=simulation.as_of,
            valuation_simulation_source_identity=simulation.source_identity,
        )
    )
    calibration = valid_result.calibration
    shortened = replace(
        calibration,
        observations=calibration.observations[:-1],
        trading_sessions=calibration.trading_sessions[:-1],
        calendar_member_ids=calibration.calendar_member_ids[:-1],
        series_member_ids=calibration.series_member_ids[:-1],
        window_end=calibration.observations[-2].session_date,
    )
    starting_price = Decimal(valid_result.starting_price)
    last_price = shortened.observations[-1].adjusted_close
    current_state = (
        "risk_on"
        if starting_price > last_price
        else "risk_off"
        if starting_price < last_price
        else "flat"
    )
    non_adjacent = replace(
        valid_result,
        calibration=shortened,
        current_market_state=current_state,
        current_state_evidence_refs=(
            valid_result.starting_price_member_id,
            shortened.series_member_ids[-1],
            shortened.state_model_identity,
        ),
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        shortened,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    market_path = ImmutableArtifactDraft.from_market_path_simulation(
        non_adjacent,
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    with pytest.raises(WorkflowError):
        root.facade.run_research_workflow(
            replace(
                _request(
                    "market-path:non-adjacent-state",
                    (*deterministic, market_data, market_path),
                ),
                workflow_snapshot_id=(
                    bound_request.calibration.platform_snapshot_id
                ),
                candidate_member_ids=market_member_ids,
                market_only_member_ids=market_member_ids,
            )
        )
    assert (
        root._store.connection.execute(
            "SELECT count(*) FROM research_artifact_record"
        ).fetchone()[0]
        == 0
    )
    root.close()


def test_formal_persistence_rejects_declared_start_availability_before_member(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    deterministic = _simulation_drafts()
    simulation = deterministic[-1]
    valid_result = MarketPathEngine().run(
        replace(
            bound_request,
            security_id=simulation.subject_id,
            as_of=simulation.as_of,
            starting_price_session=simulation.as_of,
            valuation_simulation_source_identity=simulation.source_identity,
        )
    )
    early = replace(
        valid_result,
        starting_price_available_at="2026-07-07T09:00:00+08:00",
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        valid_result.calibration,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    market_path = ImmutableArtifactDraft.from_market_path_simulation(
        early,
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    with pytest.raises(WorkflowError):
        root.facade.run_research_workflow(
            replace(
                _request(
                    "market-path:early-start-availability",
                    (*deterministic, market_data, market_path),
                ),
                workflow_snapshot_id=(
                    bound_request.calibration.platform_snapshot_id
                ),
                candidate_member_ids=market_member_ids,
                market_only_member_ids=market_member_ids,
            )
        )
    assert (
        root._store.connection.execute(
            "SELECT count(*) FROM research_artifact_record"
        ).fetchone()[0]
        == 0
    )
    root.close()


def test_formal_persistence_rejects_false_historical_availability(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, CountingEngine())
    bound_request, market_member_ids = _install_market_snapshot(
        root,
        market_path_request(),
    )
    deterministic = _simulation_drafts()
    simulation = deterministic[-1]
    valid_result = MarketPathEngine().run(
        replace(
            bound_request,
            security_id=simulation.subject_id,
            as_of=simulation.as_of,
            starting_price_session=simulation.as_of,
            valuation_simulation_source_identity=simulation.source_identity,
        )
    )
    fabricated_calibration = replace(
        valid_result.calibration,
        observations=tuple(
            replace(
                observation,
                close_available_at=(
                    f"{observation.session_date}T09:00:00+08:00"
                ),
            )
            for observation in valid_result.calibration.observations
        ),
    )
    fabricated = replace(
        valid_result,
        calibration=fabricated_calibration,
    )
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        fabricated_calibration,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    market_path = ImmutableArtifactDraft.from_market_path_simulation(
        fabricated,
        valuation_simulation_artifact=simulation,
        market_data_snapshot_artifact=market_data,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )
    with pytest.raises(WorkflowError):
        root.facade.run_research_workflow(
            replace(
                _request(
                    "market-path:false-history-availability",
                    (*deterministic, market_data, market_path),
                ),
                workflow_snapshot_id=(
                    bound_request.calibration.platform_snapshot_id
                ),
                candidate_member_ids=market_member_ids,
                market_only_member_ids=market_member_ids,
            )
        )
    assert (
        root._store.connection.execute(
            "SELECT count(*) FROM research_artifact_record"
        ).fetchone()[0]
        == 0
    )
    root.close()


def test_market_path_artifact_rejects_unfrozen_data_dimensions_and_unsafe_copy() -> None:
    simulation = _simulation_drafts()[-1]
    base_request = replace(
        market_path_request(),
        security_id=simulation.subject_id,
        as_of=simulation.as_of,
        starting_price_session=simulation.as_of,
        valuation_simulation_source_identity=simulation.source_identity,
    )
    result = MarketPathEngine().run(base_request)
    market_data = ImmutableArtifactDraft.from_market_data_snapshot(
        result.calibration,
        security_id=simulation.subject_id,
        model_identity="company-outlook-model@1",
        policy_identity="company-outlook-policy@1",
    )

    for invalid in (
        replace(result, currency="USD", price_unit="USD/share"),
        replace(result, interpretation="BUY now; target price 20."),
        replace(result, terminal_period=result.as_of),
        replace(
            result,
            calibration=replace(
                result.calibration,
                trading_calendar_identity="unfrozen-calendar@1",
            ),
        ),
    ):
        with pytest.raises(
            ValueError,
            match="RESEARCH_ARTIFACT_MARKET_PATH_LINEAGE_INVALID",
        ):
            ImmutableArtifactDraft.from_market_path_simulation(
                invalid,
                valuation_simulation_artifact=simulation,
                market_data_snapshot_artifact=market_data,
                model_identity="company-outlook-model@1",
                policy_identity="company-outlook-policy@1",
            )


def test_value_market_divergence_fails_closed_across_dimensions() -> None:
    result = ResearchDecisionViewBuilder._value_market_divergence(
        {
            "quantiles": {
                "p50": {
                    "value": "12",
                    "unit": "CNY/share",
                    "currency": "CNY",
                }
            }
        },
        {
            "terminal_price_quantiles": {
                "p50": {
                    "value": "10",
                    "unit": "USD/share",
                    "currency": "USD",
                }
            }
        },
    )
    assert result == {
        "status": "not_comparable",
        "explanation": (
            "价值分布与市场路径的单位或币种不同；未提供冻结汇率转换，"
            "因此禁止计算两者背离。"
        ),
    }
