from __future__ import annotations

import json
import os
from pathlib import Path

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.trading_discipline_kernel_scenario import (
    build_kernel_scenario,
)
from trading_platform.application import (
    GetEstimatedAccountState,
    encode_read_model,
    open_account_state_queries,
    open_read_models,
)


GENERATED_AT = "2026-08-03T20:00:00+08:00"


def test_restart_replay_is_idempotent(tmp_path: Path) -> None:
    scenario = build_kernel_scenario(tmp_path / "live")
    assert len(scenario.steps) == 20
    assert len(set(scenario.steps)) == 20
    assert scenario.agent_snapshot_denied is True
    assert scenario.agent_plan_denied is True
    assert scenario.proposal_rejected is True
    assert scenario.replay_execution_equal is True
    assert scenario.first_plan_version_ids[0] != (
        scenario.current_plan_version_ids[0]
    )

    with open_account_state_queries(scenario.data_root) as states:
        estimated = states.get(GetEstimatedAccountState("account_local"))
    assert {item.security_id for item in estimated.positions} == {
        "security_002897_sz",
        "security_600183_sh",
    }
    grid_position = next(
        item
        for item in estimated.positions
        if item.security_id == "security_600183_sh"
    )
    assert grid_position.total_quantity == "90"
    assert estimated.unverified_evidence == (
        scenario.execution_record_id,
    )

    with open_read_models(scenario.data_root) as reads:
        portfolio = reads.portfolio("account_local", GENERATED_AT)
        views = (
            portfolio,
            reads.holding(
                "account_local",
                "security_600183_sh",
                GENERATED_AT,
            ),
            reads.plan_detail(
                portfolio.holding_active_plan_summaries[1]["plan_id"],
                GENERATED_AT,
            ),
            reads.review(
                "account_local",
                GENERATED_AT,
                scenario.review_run_ids[1],
            ),
            reads.research_index(
                GENERATED_AT,
                "security_600183_sh",
            ),
            reads.account_editor("account_local", GENERATED_AT),
        )
        first_payloads = tuple(encode_read_model(view) for view in views)
    with open_read_models(scenario.data_root) as restarted:
        rebuilt = restarted.portfolio("account_local", GENERATED_AT)
        second_payloads = (
            encode_read_model(rebuilt),
            encode_read_model(
                restarted.holding(
                    "account_local",
                    "security_600183_sh",
                    GENERATED_AT,
                )
            ),
            encode_read_model(
                restarted.plan_detail(
                    rebuilt.holding_active_plan_summaries[1]["plan_id"],
                    GENERATED_AT,
                )
            ),
            encode_read_model(
                restarted.review(
                    "account_local",
                    GENERATED_AT,
                    scenario.review_run_ids[1],
                )
            ),
            encode_read_model(
                restarted.research_index(
                    GENERATED_AT,
                    "security_600183_sh",
                )
            ),
            encode_read_model(
                restarted.account_editor("account_local", GENERATED_AT)
            ),
        )
    assert second_payloads == first_payloads

    adapter = SQLiteOwningAdapterFixture(scenario.data_root)
    identity_sets = {
        "account_snapshot_versions": [
            row[0]
            for row in adapter.execute(
                "SELECT account_snapshot_version_id "
                "FROM account_snapshot_version ORDER BY 1"
            )
        ],
        "plan_versions": [
            row[0]
            for row in adapter.execute(
                "SELECT plan_version_id FROM trade_plan_version ORDER BY 1"
            )
        ],
        "review_runs": [
            row[0]
            for row in adapter.execute(
                "SELECT review_run_id "
                "FROM manual_portfolio_review_run ORDER BY 1"
            )
        ],
        "decision_tasks": [
            row[0]
            for row in adapter.execute(
                "SELECT decision_task_id FROM decision_task ORDER BY 1"
            )
        ],
        "executions": [
            row[0]
            for row in adapter.execute(
                "SELECT execution_record_id "
                "FROM execution_record ORDER BY 1"
            )
        ],
    }
    assert len(identity_sets["decision_tasks"]) == 2
    assert len(identity_sets["executions"]) == 1
    assert all(
        len(values) == len(set(values))
        for values in identity_sets.values()
    )
    adapter.close()

    evidence_root = os.environ.get("TDK_ACCEPTANCE_EVIDENCE_ROOT")
    if evidence_root:
        (Path(evidence_root) / "restart-replay.json").write_text(
            json.dumps(
                {
                    "schema_version": "KernelRestartReplayEvidence@1",
                    "status": "passed",
                    "steps": list(scenario.steps),
                    "identity_sets": identity_sets,
                    "read_model_content_hashes": [
                        json.loads(payload)["content_hash"]
                        for payload in first_payloads
                    ],
                    "execution_replay_equal": (
                        scenario.replay_execution_equal
                    ),
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
