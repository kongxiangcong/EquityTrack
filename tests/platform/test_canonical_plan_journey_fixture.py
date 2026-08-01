from __future__ import annotations

from pathlib import Path

from tests.platform.canonical_plan_journey_fixture import (
    application_envelope_bytes,
    arrange_canonical_plan_journey,
)
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandResult,
)


def test_canonical_journey_arranges_an_active_plan_through_public_commands(
    tmp_path: Path,
) -> None:
    with arrange_canonical_plan_journey(
        tmp_path, activate=True
    ) as journey:
        assert journey.platform.data_root == tmp_path.resolve()
        assert journey.data_root == tmp_path.resolve()
        assert journey.account_id == "account_authoring"
        assert journey.security_id == "security_yihua"
        assert journey.data_snapshot_id
        assert journey.workflow_run_id
        assert journey.recent_trend_assessment_id
        assert journey.draft_id
        assert journey.draft_revision == 1
        assert journey.plan_id
        assert journey.plan_version_id
        assert journey.challenge_id
        assert journey.activation_id

        review = journey.platform.application_commands.dispatch(
            ApplicationCommandEnvelopeV1.from_bytes(
                application_envelope_bytes(
                    command_name="manual_portfolio_review.run@2",
                    payload_schema_version="RunManualPortfolioReview@2",
                    invocation_id="canonical-journey:manual-review",
                    payload={
                        "account_id": journey.account_id,
                        "requested_at": journey.review_requested_at,
                        "session_selection": (
                            "latest_proven_complete_session"
                        ),
                    },
                )
            )
        )
        assert isinstance(review, ApplicationCommandResult)
        assert review.result_type == "ManualPortfolioReviewRun"
        assert review.result["selected_complete_session"] == "2026-07-10"
        assert review.result["window_start_exclusive"] == "2026-07-09"
