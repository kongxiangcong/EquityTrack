from __future__ import annotations

from decimal import Decimal

from trading_platform.application import open_application
from trading_platform.evidence import build_evidence_set


AS_OF = "2035-04-18T08:00:00+00:00"


def seed_case(app) -> tuple[dict[str, object], dict[str, object]]:
    raw = [
        {"name": "free_cash_flow", "value": {"amount": "100", "currency": "XCU"}, "source_id": "fixture-source-fcf", "as_of": AS_OF},
        {"name": "net_debt", "value": {"amount": "20", "currency": "XCU"}, "source_id": "fixture-source-debt", "as_of": AS_OF},
        {"name": "diluted_shares", "value": {"amount": "10", "unit": "share"}, "source_id": "fixture-source-shares", "as_of": AS_OF},
        {"name": "wacc", "value": "0.10", "source_id": "fixture-source-wacc", "as_of": AS_OF},
        {"name": "terminal_growth", "value": "0.02", "source_id": "fixture-source-growth", "as_of": AS_OF},
    ]
    evidence = build_evidence_set(AS_OF, raw).as_dict()
    research = app.research_commit(
        {
            "security_id": "security-aster-001", "as_of": AS_OF, "evidence_set": evidence,
            "candidate": {
                "thesis": "fixture thesis", "counterargument": "fixture counterargument",
                "drivers": ["fixture driver"], "risks": ["fixture risk"],
                "falsifiers": ["fixture falsifier"], "uncertainties": ["fixture uncertainty"],
            },
        },
        idempotency_key="case-seed",
    )
    return research.value, evidence


def test_dcf_completed_is_deterministic_and_replays(tmp_path) -> None:
    app = open_application(tmp_path)
    case, evidence = seed_case(app)
    request = {
        "investment_case_id": case["investment_case_id"],
        "evidence_set": evidence,
        "method": "dcf",
        "company_archetype": "mature_non_financial",
        "scenarios": {"stress": {"wacc": "0.11", "growth": "0.01"}, "base": {"wacc": "0.10", "growth": "0.02"}, "improvement": {"wacc": "0.09", "growth": "0.025"}},
    }
    first = app.valuation_assess(request, idempotency_key="valuation-orchid")
    replay = open_application(tmp_path).valuation_assess(request, idempotency_key="valuation-orchid")

    assert first.ok and first.value["status"] == "completed"
    assert first.value["result"]["enterprise_value"] == "1275"
    assert first.value["result"]["equity_value"] == "1255"
    assert first.value["result"]["per_share_value"] == "125.5"
    assert set(first.value["scenarios"]) == {"stress", "base", "improvement"}
    assert len(first.value["sensitivity"]) == 9
    base_point = next(point for point in first.value["sensitivity"] if point["wacc"] == "0.1" and point["terminal_growth"] == "0.02")
    assert base_point["per_share_value"] == first.value["result"]["per_share_value"]
    assert Decimal(first.value["sensitivity"][0]["per_share_value"]) > Decimal(first.value["sensitivity"][-1]["per_share_value"])
    assert "probability" not in str(first.value).lower()
    assert replay.value == first.value


def test_missing_method_input_is_local_insufficient(tmp_path) -> None:
    app = open_application(tmp_path)
    case, evidence = seed_case(app)
    evidence["items"] = [item for item in evidence["items"] if item["name"] != "diluted_shares"]
    evidence.pop("evidence_set_id")
    result = app.valuation_assess(
        {"investment_case_id": case["investment_case_id"], "evidence_set": evidence, "method": "dcf", "company_archetype": "mature_non_financial"},
        idempotency_key="valuation-missing",
    )
    assert result.ok and result.value["status"] == "insufficient"
    assert result.value["missing_inputs"] == ["diluted_shares"]
    assert result.value["disabled_conclusion"] == "per_share_valuation"


def test_industry_method_gates_and_comparable_minimum(tmp_path) -> None:
    app = open_application(tmp_path)
    case, evidence = seed_case(app)
    for archetype, method, expected in [
        ("financial", "dcf", "ordinary DCF is disabled for financial institutions"),
        ("pipeline_biopharma", "dcf", "pipeline biopharma routes to rNPV"),
        ("cyclical_resource", "dcf", "cyclical and resource valuation requires a mid-cycle method"),
    ]:
        result = app.valuation_assess(
            {"investment_case_id": case["investment_case_id"], "evidence_set": evidence, "method": method, "company_archetype": archetype},
            idempotency_key=f"gate-{archetype}",
        )
        assert result.ok and result.value["status"] == "insufficient"
        assert result.value["disabled_reason"] == expected

    comps = app.valuation_assess(
        {"investment_case_id": case["investment_case_id"], "evidence_set": evidence, "method": "comparables", "company_archetype": "mature_non_financial", "comparable_currency": "XCU", "accounting_basis": "fixture-gaap", "peers": [{"peer_id": "peer-a", "source_id": "fixture-peer-a", "currency": "XCU", "accounting_basis": "fixture-gaap", "multiple": "8"}, {"peer_id": "peer-b", "source_id": "fixture-peer-b", "currency": "OTHER", "accounting_basis": "fixture-gaap", "multiple": "9"}, {"peer_id": "peer-c", "source_id": "fixture-peer-c", "currency": "XCU", "accounting_basis": "other-basis", "multiple": "10"}]},
        idempotency_key="too-few-peers",
    )
    assert comps.ok and comps.value["status"] == "insufficient"
    assert comps.value["missing_inputs"] == ["at_least_three_usable_peers"]

    completed = app.valuation_assess(
        {"investment_case_id": case["investment_case_id"], "evidence_set": evidence, "method": "comparables", "company_archetype": "mature_non_financial", "comparable_currency": "XCU", "accounting_basis": "fixture-gaap", "peers": [{"peer_id": f"peer-{index}", "source_id": f"fixture-peer-{index}", "currency": "XCU", "accounting_basis": "fixture-gaap", "multiple": str(7 + index)} for index in range(3)]},
        idempotency_key="valid-peers",
    )
    assert completed.ok and completed.value["status"] == "completed"
    assert completed.value["result"]["median_multiple"] == "8"


def test_valuation_failure_rolls_back_result_and_command(tmp_path) -> None:
    base = open_application(tmp_path)
    case, evidence = seed_case(base)
    request = {
        "investment_case_id": case["investment_case_id"],
        "evidence_set": evidence,
        "method": "dcf",
        "company_archetype": "mature_non_financial",
    }

    failed = open_application(tmp_path, fault_at="before_commit").valuation_assess(
        request, idempotency_key="valuation-retry"
    )
    retry = open_application(tmp_path).valuation_assess(
        request, idempotency_key="valuation-retry"
    )

    assert not failed.ok and failed.error["code"] == "PERSISTENCE_FAILURE"
    assert retry.ok and retry.value["status"] == "completed"
