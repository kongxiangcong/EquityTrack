from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from tests.platform.test_decision_tasks import _task_review
from tests.platform.canonical_plan_journey_fixture import (
    arrange_canonical_plan_journey,
)
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
    data_root, assessment, _ = _proposal_authority(tmp_path, "read-model")
    plan_id = None
    with open_read_models(data_root) as reads:
        portfolio = reads.portfolio("account_local", GENERATED_AT)
        plan_id = portfolio.holding_active_plan_summaries[0]["plan_id"]
        views = (
            portfolio,
            reads.holding("account_local", "security_600000", GENERATED_AT),
            reads.plan_detail(str(plan_id), GENERATED_AT),
            reads.review(
                "account_local",
                GENERATED_AT,
                assessment.evidence.review_run_id,
            ),
            reads.research_index(GENERATED_AT, "security_600000"),
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
        holding = reads.holding("account_local", "security_600000", GENERATED_AT)
    estimated = portfolio.account_state_summary["estimated_state"]
    assert estimated["cash_state"] == "unknown"
    assert estimated["cash_value"] is None
    assert estimated["unverified_count"] == 1
    assert holding.position_summary["available_quantity_state"] == ("unknown")
    assert "available_quantity:unknown" in (holding.ability_changing_warnings)
    assert f"unverified:{execution.execution_record_id}" in (
        holding.ability_changing_warnings
    )


def test_plan_detail_defaults_to_user_language_decision_summary(
    tmp_path: Path,
) -> None:
    with arrange_canonical_plan_journey(tmp_path, activate=True) as journey:
        detail = journey.platform.read_models.plan_detail(
            journey.plan_id, journey.review_requested_at
        )

    summary = detail.decision_summary
    assert set(summary) == {
        "lifecycle_label",
        "user_control_boundary",
        "horizon",
        "quantities",
        "trigger_conditions",
        "risk_constraints",
        "evidence_status",
        "evaluation",
    }
    assert summary["lifecycle_label"] == "已确认并启用"
    assert summary["horizon"] == {
        "start": "2026-07-11",
        "end": "2028-12-31",
        "review_by": "2026-10-31",
    }
    assert summary["quantities"] == {
        "core_floor": {"state": "known", "value": "1000", "unit": "股"},
        "candidate_adjustment": {
            "state": "unknown",
            "value": None,
            "unit": "股",
        },
    }
    assert summary["trigger_conditions"]
    assert summary["risk_constraints"]
    assert summary["evidence_status"]["items"]
    assert summary["evaluation"]["next_step"]
    encoded = encode_read_model(detail).decode("utf-8")
    rendered = json.dumps(json.loads(encoded)["decision_summary"], ensure_ascii=False)
    assert "plan_rule_" not in rendered
    assert "strategy_version_" not in rendered
    assert "Open discipline draft" not in encoded
    assert "financial_boundary" not in encoded
