from __future__ import annotations

from trading_platform.projection import cycle_summary


def test_cycle_summary_is_a_read_only_projection_without_identity() -> None:
    summary = cycle_summary(
        account_snapshot={"snapshot_id": "snapshot-orchid", "as_of": "2035-04-18T08:00:00+00:00"},
        executions=[{"execution_id": "execution-lantern"}],
        open_tasks=[{"task_id": "task-orchid", "status": "open"}],
        reviews=[{"decision_review_id": "review-process", "review_type": "PROCESS"}],
    )
    assert summary == {"account_as_of": "2035-04-18T08:00:00+00:00", "execution_count": 1, "open_task_ids": ["task-orchid"], "process_review_count": 1, "outcome_review_count": 0}
    assert not any(key.endswith("_id") for key in summary)
