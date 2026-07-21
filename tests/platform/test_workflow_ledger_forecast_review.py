from pathlib import Path

import pytest

from trading_platform.application.contracts import StartResearchWorkflow
from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_forecast_review_artifact import (
    persist_review_snapshot,
    review_request,
)
from tests.platform.test_outlook_artifacts import _request
from tests.platform.test_research_workflow import CountingEngine, _root
from tests.platform.test_valuation_simulation_artifact import _simulation_drafts
from tests.platform.test_workflow_ledger_recovery import CrashAt, InjectedCrash


def test_review_database_failure_leaves_no_partial_graph_or_manifest(
    tmp_path: Path,
) -> None:
    root = _root(
        tmp_path,
        CountingEngine(),
        CrashAt("forecast_review.before_commit"),
    )
    result = root.research.handle(
        StartResearchWorkflow(
            _request("forecast-review:rollback", _simulation_drafts())
        )
    )
    parents = tuple(
        root.archive.artifact(record_id)
        for record_id in result.artifact_record_ids
    )
    request = persist_review_snapshot(root, review_request(parents))

    with pytest.raises(InjectedCrash):
        root.forecast_review.review(request)

    connection = SQLiteOwningAdapterFixture(root.data_root)
    assert connection.execute(
        "SELECT count(*) FROM research_artifact_record "
        "WHERE artifact_kind='ForecastReview'"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM artifact_manifest "
        "WHERE manifest_role='forecast_review_append'"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM workflow_run_ref "
        "WHERE ref_role LIKE 'forecast_review_%'"
    ).fetchone()[0] == 0
    connection.close()
    root.close()
