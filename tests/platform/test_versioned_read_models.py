from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from tests.platform.test_decision_tasks import _task_review
from tests.platform.test_execution_records import _declare
from tests.platform.test_plan_change_proposals import (
    _proposal_authority,
)
from trading_platform.application import (
    encode_read_model,
    open_decision_journal,
    open_read_models,
)


GENERATED_AT = "2026-07-27T18:30:00+08:00"


def test_web_and_skill_serialize_identical_application_dtos(
    tmp_path: Path,
) -> None:
    data_root, assessment, _ = _proposal_authority(
        tmp_path, "read-model"
    )
    plan_id = None
    with open_read_models(data_root) as reads:
        portfolio = reads.portfolio("account_local", GENERATED_AT)
        plan_id = portfolio.holding_active_plan_summaries[0]["plan_id"]
        views = (
            portfolio,
            reads.holding(
                "account_local", "security_600000", GENERATED_AT
            ),
            reads.plan_detail(str(plan_id), GENERATED_AT),
            reads.review(
                "account_local",
                GENERATED_AT,
                assessment.evidence.review_run_id,
            ),
            reads.research_index(
                GENERATED_AT, "security_600000"
            ),
            reads.account_editor("account_local", GENERATED_AT),
        )
    assert len({view.schema_version for view in views}) == 6
    for view in views:
        skill_payload = encode_read_model(view)
        web_payload = encode_read_model(view)
        assert web_payload == skill_payload
        decoded = json.loads(skill_payload)
        assert decoded["projection_id"] == view.projection_id
        assert decoded["content_hash"] == view.content_hash
        assert decoded["source_ids"] == list(view.source_ids)
    with pytest.raises(TypeError):
        portfolio.account_state_summary["status"] = "tampered"

    with open_read_models(data_root) as restarted:
        rebuilt = restarted.portfolio("account_local", GENERATED_AT)
    assert rebuilt == portfolio
    assert rebuilt.projection_id == portfolio.projection_id
    assert rebuilt.content_hash == portfolio.content_hash


def test_portfolio_home_has_only_five_decision_summary_groups(
    tmp_path: Path,
) -> None:
    data_root, _, _ = _proposal_authority(tmp_path, "home-allowlist")
    with open_read_models(data_root) as reads:
        view = reads.portfolio("account_local", GENERATED_AT)
    metadata = {
        "projection_id",
        "source_ids",
        "generated_at",
        "content_hash",
        "schema_version",
    }
    groups = {field.name for field in fields(view)} - metadata
    assert groups == {
        "account_state_summary",
        "unresolved_decision_tasks",
        "material_changes_since_last_review",
        "holding_active_plan_summaries",
        "discipline_exception_summary",
    }
    encoded = encode_read_model(view).decode("utf-8").lower()
    for forbidden in (
        "graph_seal_hash",
        "policy_identity",
        "model_identity",
        "manifest_id",
        "workflow_log",
        "readiness",
        "forecast_registry",
    ):
        assert forbidden not in encoded


def test_unknown_unable_and_unverified_states_are_not_coerced(
    tmp_path: Path,
) -> None:
    data_root, _, task = _task_review(
        tmp_path,
        suffix="read-model-unverified",
        invocation_id="read-model:unverified-review",
    )
    with open_decision_journal(data_root) as journal:
        execution = journal.declare(
            _declare(
                task.decision_task_id,
                "read-model:unverified-execution",
            )
        )
    with open_read_models(data_root) as reads:
        portfolio = reads.portfolio("account_local", GENERATED_AT)
        holding = reads.holding(
            "account_local", "security_600000", GENERATED_AT
        )
    estimated = portfolio.account_state_summary["estimated_state"]
    assert estimated["cash_state"] == "unknown"
    assert estimated["cash_value"] is None
    assert estimated["unverified_count"] == 1
    assert holding.position_summary["available_quantity_state"] == (
        "unknown"
    )
    assert "available_quantity:unknown" in (
        holding.ability_changing_warnings
    )
    assert f"unverified:{execution.execution_record_id}" in (
        holding.ability_changing_warnings
    )
