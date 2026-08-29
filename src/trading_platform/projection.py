from __future__ import annotations

from typing import Any, Iterable, Mapping


def cycle_summary(
    *,
    account_snapshot: Mapping[str, Any],
    executions: Iterable[Mapping[str, Any]],
    open_tasks: Iterable[Mapping[str, Any]],
    reviews: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    execution_rows = list(executions)
    task_rows = list(open_tasks)
    review_rows = list(reviews)
    return {
        "account_as_of": account_snapshot["as_of"],
        "execution_count": len(execution_rows),
        "open_task_ids": [task["task_id"] for task in task_rows if task.get("status") == "open"],
        "process_review_count": sum(review.get("review_type") == "PROCESS" for review in review_rows),
        "outcome_review_count": sum(review.get("review_type") == "OUTCOME" for review in review_rows),
    }
