from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import (
    SQLiteOwningAdapterFixture,
)
from tests.platform.test_plan_confirmation import (
    USER,
    _authority_root,
    _draft,
    _open_trade_plan_test_seams,
)
from trading_platform.application.trade_plan_authoring import (
    _UpsertOpenTradePlanDraft,
)
from trading_platform.domain.plans import PlanValidationError


def _command(snapshot_id: str) -> _UpsertOpenTradePlanDraft:
    draft = _draft(snapshot_id, suffix="authoring-query")
    return _UpsertOpenTradePlanDraft(
        invocation_id="authoring-query:create",
        account_id=draft.account_id,
        security_id=draft.security_id,
        proposed_graph=draft.proposed_graph,
        parameters=draft.parameters,
        updated_at=draft.updated_at,
        actor=USER,
    )


def test_open_draft_and_authoring_invocation_use_internal_upsert_policy(
    tmp_path: Path,
) -> None:
    data_root, snapshot_id = _authority_root(tmp_path)
    command = _command(snapshot_id)

    with _open_trade_plan_test_seams(data_root) as (_, drafts):
        created = drafts.upsert(command)

    with _open_trade_plan_test_seams(data_root) as (_, drafts):
        replay = drafts.upsert(command)

        assert replay == created
        assert drafts.get_open(
            "account_local", "security_600000"
        ) == created
        assert drafts.get_by_invocation(command.invocation_id) == created
        assert drafts.get_by_invocation("authoring-query:missing") is None

        conflict_draft = _draft(
            snapshot_id, suffix="authoring-query-conflict"
        )
        with pytest.raises(
            PlanValidationError, match="INVOCATION_CONFLICT"
        ):
            drafts.upsert(
                replace(
                    command,
                    proposed_graph=conflict_draft.proposed_graph,
                )
            )

    connection = SQLiteOwningAdapterFixture(data_root)
    receipt = connection.execute(
        "SELECT command_name,aggregate_id,revision_or_version_id "
        "FROM application_command_receipt WHERE invocation_id=?",
        (command.invocation_id,),
    ).fetchone()
    connection.close()
    assert tuple(receipt) == (
        "UpsertOpenTradePlanDraft",
        created.draft_id,
        str(created.revision),
    )
