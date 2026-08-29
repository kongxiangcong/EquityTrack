from __future__ import annotations

import pytest

from trading_platform.application import open_application
from trading_platform.evidence import build_evidence_set
from trading_platform.planning import TradePlanDraft


AS_OF = "2035-04-18T08:00:00+00:00"


def seed(app) -> tuple[dict, dict, dict]:
    account = app.account_confirm(
        {"account_id": "account-orchid", "as_of": AS_OF, "confirmed": True, "confirmed_by": "synthetic-user", "cash": {"amount": "800", "currency": "XCU"}, "positions": [{"security_id": "security-aster-001", "quantity": "120", "available_quantity": None, "cost_basis": None}]},
        idempotency_key="seed-account",
    ).value
    evidence = build_evidence_set(AS_OF, [
        {"name": "free_cash_flow", "value": {"amount": "100", "currency": "XCU"}, "source_id": "fixture-source-fcf", "as_of": AS_OF},
        {"name": "net_debt", "value": {"amount": "20", "currency": "XCU"}, "source_id": "fixture-source-debt", "as_of": AS_OF},
        {"name": "diluted_shares", "value": {"amount": "10", "unit": "share"}, "source_id": "fixture-source-shares", "as_of": AS_OF},
        {"name": "wacc", "value": "0.10", "source_id": "fixture-source-wacc", "as_of": AS_OF},
        {"name": "terminal_growth", "value": "0.02", "source_id": "fixture-source-growth", "as_of": AS_OF},
    ]).as_dict()
    case = app.research_commit(
        {"security_id": "security-aster-001", "as_of": AS_OF, "evidence_set": evidence, "candidate": {"thesis": "fixture thesis", "counterargument": "fixture counterargument", "drivers": ["fixture driver"], "risks": ["fixture risk"], "falsifiers": ["fixture falsifier"], "uncertainties": ["fixture uncertainty"]}},
        idempotency_key="seed-case",
    ).value
    valuation = app.valuation_assess(
        {"investment_case_id": case["investment_case_id"], "evidence_set": evidence, "method": "dcf", "company_archetype": "mature_non_financial"},
        idempotency_key="seed-valuation",
    ).value
    return account, case, valuation


def prepare_request(account: dict, case: dict, valuation: dict, **plan_overrides: object) -> dict:
    plan = {
        "expires_at": "2035-04-20T08:00:00+00:00",
        "review_window_end": "2035-05-20T08:00:00+00:00",
        "rules": [{"rule_id": "rule-price", "type": "price_above", "threshold": "19", "evidence_name": "market_price"}],
        **plan_overrides,
    }
    return {
        "investment_case_id": case["investment_case_id"],
        "valuation_assessment_id": valuation["valuation_assessment_id"],
        "account_snapshot_id": account["snapshot_id"],
        "prices": {"security-aster-001": {"amount": "10", "currency": "XCU", "source_id": "fixture-source-price"}},
        "risk_policy": {"policy_id": "risk-orchid", "max_concentration": "0.70", "max_position_value": "1500", "confirmed": True, "confirmed_by": "synthetic-user"},
        "plan": plan,
    }


def test_prepare_atomically_persists_risk_card_and_stable_draft(tmp_path) -> None:
    app = open_application(tmp_path)
    account, case, valuation = seed(app)
    request = prepare_request(account, case, valuation)
    prepared = app.planning_prepare(request, idempotency_key="prepare-orchid")
    replay = open_application(tmp_path).planning_prepare(request, idempotency_key="prepare-orchid")

    assert prepared.ok and replay.value == prepared.value
    assert set(prepared.value) == {"risk_limit_result", "decision_card", "trade_plan_draft"}
    card = prepared.value["decision_card"]
    assert card["investment_case_id"] == case["investment_case_id"]
    assert card["valuation_assessment_id"] == valuation["valuation_assessment_id"]
    assert card["risk_limit_result_id"] == prepared.value["risk_limit_result"]["risk_limit_result_id"]
    assert prepared.value["trade_plan_draft"]["content_hash"]
    frozen_draft = TradePlanDraft.from_dict(prepared.value["trade_plan_draft"])
    with pytest.raises(TypeError):
        frozen_draft.rules[0]["threshold"] = "0"


def test_prepare_failure_rolls_back_all_three_records(tmp_path) -> None:
    base = open_application(tmp_path)
    account, case, valuation = seed(base)
    request = prepare_request(account, case, valuation)
    failed = open_application(tmp_path, fault_at="before_commit").planning_prepare(request, idempotency_key="prepare-retry")
    assert not failed.ok and failed.error["code"] == "PERSISTENCE_FAILURE"
    assert open_application(tmp_path).planning_prepare(request, idempotency_key="prepare-retry").ok


def test_prepare_requires_a_user_confirmed_risk_policy(tmp_path) -> None:
    app = open_application(tmp_path)
    account, case, valuation = seed(app)
    request = prepare_request(account, case, valuation)
    request["risk_policy"] = request["risk_policy"] | {"confirmed": False}
    result = app.planning_prepare(request, idempotency_key="unconfirmed-policy")
    assert not result.ok and result.error["code"] == "INVALID_INPUT"


def test_confirm_binds_hash_and_records_confirmation_without_receipt(tmp_path) -> None:
    app = open_application(tmp_path)
    account, case, valuation = seed(app)
    draft = app.planning_prepare(prepare_request(account, case, valuation), idempotency_key="prepare").value["trade_plan_draft"]
    confirmation = {"draft_id": draft["draft_id"], "content_hash": draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T08:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"}
    plan = app.planning_confirm(confirmation, idempotency_key="confirm-plan")

    assert plan.ok and plan.value["revision"] == 1
    assert plan.value["confirmed_by"] == "synthetic-user"
    assert "receipt" not in str(plan.value).lower() and "order" not in str(plan.value).lower()

    stale = app.planning_confirm(confirmation | {"content_hash": "old-hash"}, idempotency_key="stale-hash")
    assert not stale.ok and stale.error["code"] == "STALE_INPUT"


def test_expired_draft_cannot_create_a_trade_plan(tmp_path) -> None:
    app = open_application(tmp_path)
    account, case, valuation = seed(app)
    draft = app.planning_prepare(
        prepare_request(account, case, valuation), idempotency_key="prepare-expired"
    ).value["trade_plan_draft"]

    expired = app.planning_confirm(
        {
            "draft_id": draft["draft_id"],
            "content_hash": draft["content_hash"],
            "explicit_confirmation": True,
            "confirmed_at": "2035-04-21T08:00:00+00:00",
            "confirmed_by": "synthetic-user",
            "channel": "fixture-chat",
        },
        idempotency_key="confirm-expired",
    )

    assert not expired.ok and expired.error["code"] == "STALE_INPUT"


def test_revision_and_close_are_append_only(tmp_path) -> None:
    app = open_application(tmp_path)
    account, case, valuation = seed(app)
    draft = app.planning_prepare(prepare_request(account, case, valuation), idempotency_key="prepare-one").value["trade_plan_draft"]
    first = app.planning_confirm({"draft_id": draft["draft_id"], "content_hash": draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T08:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"}, idempotency_key="confirm-one").value

    revision_draft = app.planning_prepare(prepare_request(account, case, valuation, supersedes_plan_id=first["trade_plan_id"], review_window_end="2035-06-20T08:00:00+00:00"), idempotency_key="prepare-two").value["trade_plan_draft"]
    second = app.planning_confirm({"draft_id": revision_draft["draft_id"], "content_hash": revision_draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T09:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"}, idempotency_key="confirm-two").value
    assert second["plan_family_id"] == first["plan_family_id"] and second["revision"] == 2
    assert second["supersedes_plan_id"] == first["trade_plan_id"]

    close_draft = app.planning_prepare(prepare_request(account, case, valuation, close_plan_id=second["trade_plan_id"], rules=[]), idempotency_key="prepare-close").value["trade_plan_draft"]
    closed = app.planning_confirm({"draft_id": close_draft["draft_id"], "content_hash": close_draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T10:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"}, idempotency_key="confirm-close")
    assert closed.ok and closed.value["closed_plan_id"] == second["trade_plan_id"]

    duplicate_close = app.planning_confirm(
        {"draft_id": close_draft["draft_id"], "content_hash": close_draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T10:01:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"},
        idempotency_key="confirm-close-again",
    )
    assert not duplicate_close.ok and duplicate_close.error["code"] == "STALE_INPUT"

    stale_revision = app.planning_prepare(
        prepare_request(account, case, valuation, supersedes_plan_id=first["trade_plan_id"]),
        idempotency_key="prepare-from-inactive-plan",
    )
    assert not stale_revision.ok and stale_revision.error["code"] == "INVALID_INPUT"


def test_same_draft_cannot_be_confirmed_twice_with_different_keys(tmp_path) -> None:
    app = open_application(tmp_path)
    account, case, valuation = seed(app)
    draft = app.planning_prepare(
        prepare_request(account, case, valuation), idempotency_key="prepare-single-confirm"
    ).value["trade_plan_draft"]
    confirmation = {"draft_id": draft["draft_id"], "content_hash": draft["content_hash"], "explicit_confirmation": True, "confirmed_at": "2035-04-19T08:00:00+00:00", "confirmed_by": "synthetic-user", "channel": "fixture-chat"}
    assert app.planning_confirm(confirmation, idempotency_key="confirm-first").ok
    duplicate = app.planning_confirm(confirmation, idempotency_key="confirm-second")
    assert not duplicate.ok and duplicate.error["code"] == "STALE_INPUT"
