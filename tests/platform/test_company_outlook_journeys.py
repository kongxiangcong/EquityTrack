from __future__ import annotations

import json
from pathlib import Path

from tests.platform.test_research_workflow import _request, _root
from trading_platform.application.contracts import StartResearchWorkflow
from trading_platform.domain.research_evaluation import (
    StrategyValidationSelection,
)


def test_a_share_outlook_is_bound_to_official_frozen_snapshot_evidence(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("journey:a-share-official"))
    )
    view = json.loads(
        root.archive.decision_view(result.workflow_run_id).json_bytes
    )

    assert view["security_id"] == "security_yihua"
    assert view["data_snapshot_id"] == "snapshot_filing"
    assert view["as_of"] == "2026-07-11"
    assert view["data_quality_grade"] in {"warning", "insufficient"}
    assert view["what_would_change_the_view"]
    root.close()


def test_nonofficial_semantic_financial_inputs_complete_with_valuation_limits(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(_request("journey:data-insufficient"))
    )
    source = root.archive.source_payload(result.research_run_id)
    view = json.loads(
        root.archive.decision_view(result.workflow_run_id).json_bytes
    )

    assert source["status"] == "completed_with_limits"
    assert view["valuation_view"]["status"] == "not_ready"
    assert view["valuation_artifact_record_id"] is None
    assert view["forecast_artifact_record_id"] is None
    assert view["simulation_artifact_record_id"] is None
    root.close()


def test_unavailable_strategy_validation_does_not_block_outlook_publication(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    result = root.research.handle(
        StartResearchWorkflow(
            _request(
                "journey:strategy-unavailable",
                strategy=(
                    StrategyValidationSelection.REQUESTED_UNAVAILABLE
                ),
            )
        )
    )
    view = json.loads(
        root.archive.decision_view(result.workflow_run_id).json_bytes
    )

    assert result.final_manifest_id
    assert view["audit"]["strategy_validation"]["status"] == (
        "requested_unavailable"
    )
    assert "strategy_validation_artifact_id" not in view
    root.close()
