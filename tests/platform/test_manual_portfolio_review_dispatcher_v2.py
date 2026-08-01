from __future__ import annotations

from pathlib import Path

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_manual_portfolio_review import (
    _authority_root,
    _complete_session,
)
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandFailure,
    ApplicationCommandResult,
    DecisionActor,
    InteractionChannel,
    TransportActor,
    open_application_commands,
)


def _envelope(
    *,
    invocation_id: str,
    payload: dict[str, object],
    expected_revision: int | None = None,
) -> ApplicationCommandEnvelopeV1:
    return ApplicationCommandEnvelopeV1(
        command_name="manual_portfolio_review.run@2",
        invocation_id=invocation_id,
        payload_schema_version="RunManualPortfolioReview@2",
        expected_revision=expected_revision,
        decision_actor=DecisionActor("agent", "codex"),
        interaction_channel=InteractionChannel.CODEX,
        transport_actor=TransportActor("agent", "codex"),
        approval_challenge_id=None,
        payload=payload,
    )


def _canonical_payload() -> dict[str, object]:
    return {
        "account_id": "account_local",
        "requested_at": "2026-08-02T12:00:00+08:00",
        "session_selection": "latest_proven_complete_session",
    }


def _write_counts(data_root: Path) -> tuple[int, ...]:
    connection = SQLiteOwningAdapterFixture(data_root)
    try:
        return tuple(
            connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "workflow_run",
                "manual_portfolio_review_run",
                "manual_portfolio_review_item",
                "manual_portfolio_review_manifest",
                "manual_portfolio_review_checkpoint",
                "application_command_receipt",
            )
        )
    finally:
        connection.close()


def test_dispatcher_runs_v2_exact_payload_and_replays_selected_session(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-31")
    _complete_session(data_root, "2026-08-03")
    payload = _canonical_payload()
    envelope = _envelope(
        invocation_id="manual-review:dispatcher:success",
        payload=payload,
    )

    with open_application_commands(data_root) as dispatcher:
        first = dispatcher.dispatch(envelope)
        replay = dispatcher.dispatch(envelope)
        same_session_refresh = dispatcher.dispatch(
            _envelope(
                invocation_id="manual-review:dispatcher:same-session",
                payload=payload,
            )
        )

    assert set(payload) == {
        "account_id",
        "requested_at",
        "session_selection",
    }
    assert isinstance(first, ApplicationCommandResult)
    assert replay == first
    assert first.result_type == "ManualPortfolioReviewRun"
    assert first.result["session_selection"] == (
        "latest_proven_complete_session"
    )
    assert first.result["selected_complete_session"] == "2026-07-31"
    assert first.result["window_end_inclusive"] == "2026-07-31"
    assert isinstance(same_session_refresh, ApplicationCommandResult)
    assert same_session_refresh.result["window_start_exclusive"] == (
        first.result["window_start_exclusive"]
    )
    assert same_session_refresh.result["prior_successful_review_run_id"] == (
        first.result["review_run_id"]
    )


def test_dispatcher_rejects_noncanonical_v2_payload_without_writes(
    tmp_path: Path,
) -> None:
    data_root, _ = _authority_root(tmp_path)
    _complete_session(data_root, "2026-07-31")
    before = _write_counts(data_root)
    extra_payload = {
        **_canonical_payload(),
        "selected_complete_session": "2026-07-31",
    }

    with open_application_commands(data_root) as dispatcher:
        extra = dispatcher.dispatch(
            _envelope(
                invocation_id="manual-review:dispatcher:extra",
                payload=extra_payload,
            )
        )
        revised = dispatcher.dispatch(
            _envelope(
                invocation_id="manual-review:dispatcher:revision",
                payload=_canonical_payload(),
                expected_revision=1,
            )
        )

    assert isinstance(extra, ApplicationCommandFailure)
    assert extra.code == "MANUAL_REVIEW_COMMAND_FIELDS_INVALID"
    assert isinstance(revised, ApplicationCommandFailure)
    assert revised.code == "MANUAL_REVIEW_COMMAND_FIELDS_INVALID"
    assert _write_counts(data_root) == before
