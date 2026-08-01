from __future__ import annotations

from inspect import signature

import trading_platform.application as application
from trading_platform.application import AcceptPlanChangeProposal
from trading_platform.application import trade_plan_authoring


def test_plan_change_acceptance_does_not_accept_draft_storage_controls() -> None:
    assert tuple(signature(AcceptPlanChangeProposal).parameters) == (
        "invocation_id",
        "proposal_id",
        "expected_revision",
        "decided_at",
        "actor",
    )


def test_low_level_draft_mutation_is_not_a_public_application_surface() -> None:
    assert not hasattr(application, "open_trade_plan")
    assert "CreateTradePlanDraft" not in trade_plan_authoring.__all__
    assert "ReviseTradePlanDraft" not in trade_plan_authoring.__all__
    assert not hasattr(trade_plan_authoring, "CreateTradePlanDraft")
    assert not hasattr(trade_plan_authoring, "ReviseTradePlanDraft")
